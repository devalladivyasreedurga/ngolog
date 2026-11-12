"""LangGraph accountability workflow: one graph thread per reporting request.

    START -> load_context -> await_ngo (interrupt)
    await_ngo --message--------> interpret_ngo_response (+ extract_claims) --\
    await_ngo --claim_confirmed-> determine_evidence_needs -------------------+-> [draft_update -> queue_for_review] -> await_ngo
    await_ngo --evidence-------> evaluate_evidence (+ clarify) --------------+
    await_ngo --no_evidence----> record_no_evidence --------------------------/
    await_ngo --close----------> END

The graph pauses at `await_ngo` and resumes when the NGO acts (API routes call
`runtime.dispatch`). Business state lives in Postgres; the checkpoint only holds
where the conversation is. The clarification cap lives in workflow._ask.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import interrupt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent import workflow
from app.db.models import (
    Campaign,
    ClaimEvidence,
    DonorUpdate,
    ExpenseClaim,
    ImpactClaim,
    ReportingRequest,
)
from contracts.reporting_schemas import ClaimStatus, MessageSender, PublicationStatus


@dataclass
class AgentContext:
    db: Session  # request-scoped session; never checkpointed


class CycleState(TypedDict, total=False):
    request_id: str
    event: dict
    steps: int


def _load(runtime: Runtime[AgentContext], state: CycleState) -> tuple[Session, ReportingRequest, Campaign]:
    db = runtime.context.db
    req = db.get(ReportingRequest, state["request_id"])
    return db, req, db.get(Campaign, req.campaign_id)


def _claim(db: Session, event: dict) -> ExpenseClaim | ImpactClaim | None:
    model = {"expense": ExpenseClaim, "impact": ImpactClaim}.get(event.get("claim_type", ""))
    return db.get(model, event.get("claim_id")) if model else None


# ---------------------------------------------------------------- nodes


def load_context(state: CycleState, runtime: Runtime[AgentContext]) -> CycleState:
    _load(runtime, state)  # fails fast if the request vanished
    return {"steps": 0}


def await_ngo(state: CycleState) -> CycleState:
    event = interrupt({"waiting_for": "ngo", "request_id": state["request_id"]})
    return {"event": event, "steps": state.get("steps", 0) + 1}


def interpret_ngo_response(state: CycleState, runtime: Runtime[AgentContext]) -> CycleState:
    db, req, campaign = _load(runtime, state)
    ev = state["event"]
    workflow.handle_ngo_message(db, req, campaign, ev["user_id"], ev["text"])
    return {}


def determine_evidence_needs(state: CycleState, runtime: Runtime[AgentContext]) -> CycleState:
    db, req, _ = _load(runtime, state)
    claim = _claim(db, state["event"])
    if claim is not None and claim.status == ClaimStatus.REPORTED:
        workflow.on_claim_confirmed(db, req, claim)
    return {}


def evaluate_evidence(state: CycleState, runtime: Runtime[AgentContext]) -> CycleState:
    db, req, _ = _load(runtime, state)
    evidence_id = state["event"]["evidence_id"]
    for link in db.scalars(select(ClaimEvidence).where(ClaimEvidence.evidence_id == evidence_id)):
        if link.claim_type == "expense":
            claim = db.get(ExpenseClaim, link.claim_id)
            if claim is not None and claim.status == ClaimStatus.REPORTED:
                workflow.evaluate_expense(db, req, claim)
    return {}


def confirm_claims(state: CycleState, runtime: Runtime[AgentContext]) -> CycleState:
    db, req, _ = _load(runtime, state)
    workflow.confirm_proposed(db, req, state["event"]["user_id"])
    return {}


def record_no_evidence(state: CycleState, runtime: Runtime[AgentContext]) -> CycleState:
    db, req, _ = _load(runtime, state)
    ev = state["event"]
    claim = _claim(db, ev)
    if claim is not None:
        workflow.record_no_evidence(db, req, claim, ev["explanation"], ev["user_id"])
    return {}


def draft_update(state: CycleState, runtime: Runtime[AgentContext]) -> CycleState:
    """Replace any unpublished draft for this cycle with one built from current records."""
    db, req, campaign = _load(runtime, state)
    for old in db.scalars(
        select(DonorUpdate).where(
            DonorUpdate.reporting_request_id == req.id,
            DonorUpdate.status.in_([PublicationStatus.DRAFT, PublicationStatus.APPROVED]),
        )
    ):
        old.status = PublicationStatus.WITHDRAWN
    workflow.draft_donor_update(db, campaign, req)
    return {}


def queue_for_review(state: CycleState, runtime: Runtime[AgentContext]) -> CycleState:
    db, req, _ = _load(runtime, state)
    workflow.say(
        db,
        req,
        "All set. I've drafted a donor update from what you reported. Nothing is shared until you approve it.",
        MessageSender.AGENT,
        step="queue_for_review",
        actions=[{"kind": "link", "label": "Review the draft", "href": "updates"}],
    )
    return {}


# ---------------------------------------------------------------- routing

EVENT_ROUTES = {
    "message": "interpret_ngo_response",
    "claim_confirmed": "determine_evidence_needs",
    "claims_confirmed": "confirm_claims",
    "evidence": "evaluate_evidence",
    "no_evidence": "record_no_evidence",
}


def route_event(state: CycleState) -> str:
    kind = state["event"].get("type")
    return END if kind == "close" else EVENT_ROUTES.get(kind, "await_ngo")


def after_step(state: CycleState, runtime: Runtime[AgentContext]) -> str:
    db, req, _ = _load(runtime, state)
    return "draft_update" if workflow.is_ready_for_draft(db, req) else "await_ngo"


def build_graph():
    g = StateGraph(CycleState, context_schema=AgentContext)
    for name, fn in [
        ("load_context", load_context),
        ("await_ngo", await_ngo),
        ("interpret_ngo_response", interpret_ngo_response),
        ("determine_evidence_needs", determine_evidence_needs),
        ("evaluate_evidence", evaluate_evidence),
        ("confirm_claims", confirm_claims),
        ("record_no_evidence", record_no_evidence),
        ("draft_update", draft_update),
        ("queue_for_review", queue_for_review),
    ]:
        g.add_node(name, fn)
    g.add_edge(START, "load_context")
    g.add_edge("load_context", "await_ngo")
    g.add_conditional_edges("await_ngo", route_event, [*EVENT_ROUTES.values(), "await_ngo", END])
    for step in EVENT_ROUTES.values():
        g.add_conditional_edges(step, after_step, ["draft_update", "await_ngo"])
    g.add_edge("draft_update", "queue_for_review")
    g.add_edge("queue_for_review", "await_ngo")
    return g

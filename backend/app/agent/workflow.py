"""Accountability workflow (spec section 4, suggested graph).

    load_context -> interpret_ngo_response -> extract_claims -> determine_evidence_needs
      -> [request_more_information (wait) | evaluate_evidence]
      -> [clarify (wait) | draft_update] -> queue_for_review

P0 runs these steps as plain functions driven by API events (NGO message, claim
confirmation, evidence upload). Each "wait" is the NGO's next request. The step
boundaries match the LangGraph nodes so the P1 graph can wrap them unchanged.

Rules enforced here:
- The agent proposes; it never moves money, publishes or declares fraud.
- Financial totals come from Postgres records, not from the model.
- At most `max_clarification_rounds` automated questions per reporting cycle,
  then the request escalates to human review.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.checks import compare_claim_evidence, linked_evidence, money
from app.agent.llm import AIUnavailable, get_ai
from app.audit import audit
from app.config import get_settings
from app.db.base import utcnow
from app.db.models import (
    ActivityReport,
    AgentMessage,
    AgentThread,
    Campaign,
    DonorUpdate,
    EvidenceCheck,
    ExpenseClaim,
    ImpactClaim,
    Investigation,
    ReportingPlan,
    ReportingRequest,
)
from contracts.reporting_schemas import (
    CheckStatus,
    CheckType,
    ClaimStatus,
    EvidenceReviewStatus,
    EvidenceVisibility,
    InvestigationStatus,
    MessageSender,
    PublicationStatus,
    ReportingRequestStatus,
)

OPEN_REQUEST_STATUSES = (
    ReportingRequestStatus.OPEN,
    ReportingRequestStatus.IN_REVIEW,
    ReportingRequestStatus.AWAITING_APPROVAL,
    ReportingRequestStatus.ESCALATED,
)


# ---------------------------------------------------------------- helpers


def thread_for(db: Session, req: ReportingRequest) -> AgentThread:
    return db.scalar(select(AgentThread).where(AgentThread.reporting_request_id == req.id))


def say(db: Session, req: ReportingRequest, content: str, sender: MessageSender = MessageSender.AGENT, **meta) -> AgentMessage:
    msg = AgentMessage(thread_id=thread_for(db, req).id, sender_role=sender, content=content, meta_json=meta)
    db.add(msg)
    return msg


def current_cycle_key(campaign: Campaign, now: datetime | None = None) -> str:
    now = now or utcnow()
    anchor = campaign.published_at or campaign.created_at
    cycle = max(0, (now - anchor).days // max(1, campaign.reporting_frequency_days))
    return f"cycle-{cycle}"


def claims_for_request(db: Session, req: ReportingRequest) -> tuple[list[ExpenseClaim], list[ImpactClaim]]:
    report_ids = select(ActivityReport.id).where(ActivityReport.reporting_request_id == req.id)
    expenses = list(db.scalars(select(ExpenseClaim).where(ExpenseClaim.activity_report_id.in_(report_ids)).order_by(ExpenseClaim.created_at)))
    impacts = list(db.scalars(select(ImpactClaim).where(ImpactClaim.activity_report_id.in_(report_ids)).order_by(ImpactClaim.created_at)))
    return expenses, impacts


def _latest_report(db: Session, req: ReportingRequest) -> ActivityReport | None:
    return db.scalar(
        select(ActivityReport).where(ActivityReport.reporting_request_id == req.id).order_by(ActivityReport.reported_at.desc())
    )


# ---------------------------------------------------------------- load_context / open


def open_reporting_request(db: Session, campaign: Campaign, *, cycle_key: str | None = None, actor_id: str | None = None) -> tuple[ReportingRequest, bool]:
    """Idempotent: one reporting request per (campaign, cycle_key)."""
    key = cycle_key or current_cycle_key(campaign)
    existing = db.scalar(select(ReportingRequest).where(ReportingRequest.campaign_id == campaign.id, ReportingRequest.cycle_key == key))
    if existing:
        return existing, False
    req = ReportingRequest(campaign_id=campaign.id, cycle_key=key, due_at=utcnow() + timedelta(days=3))
    db.add(req)
    db.flush()
    db.add(AgentThread(reporting_request_id=req.id))
    db.flush()
    plan = db.scalar(select(ReportingPlan).where(ReportingPlan.campaign_id == campaign.id, ReportingPlan.approved_at.is_not(None)).order_by(ReportingPlan.version.desc()))
    questions = plan.proposed_questions_json if plan else ["What has happened since the last update, and have campaign funds been spent?"]
    lines = "\n".join(f"- {q}" for q in questions[:5])
    say(
        db,
        req,
        f"Hi! It's time for a quick update on \"{campaign.title}\" for your donors.\n{lines}\n"
        "Reply in your own words; I'll turn it into a draft for you to check.",
    )
    campaign.next_followup_at = utcnow() + timedelta(days=campaign.reporting_frequency_days)
    audit(db, actor_type="agent" if actor_id is None else "user", actor_id=actor_id, action="reporting_request.open", entity_type="reporting_request", entity_id=req.id)
    return req, True


# ---------------------------------------------------------------- interpret / extract


def handle_ngo_message(db: Session, req: ReportingRequest, campaign: Campaign, user_id: str, text: str) -> None:
    say(db, req, text, MessageSender.NGO, user_id=user_id)
    if req.status == ReportingRequestStatus.OPEN:
        req.status = ReportingRequestStatus.IN_REVIEW
    open_inv = db.scalar(
        select(Investigation).where(Investigation.campaign_id == campaign.id, Investigation.status == InvestigationStatus.OPEN)
    )
    if open_inv is not None:
        # A reply to a clarification question: record it on the investigation; numbers
        # only change when evidence or a confirmed claim changes.
        open_inv.resolution = ((open_inv.resolution or "") + f"\nNGO reply: {text}").strip()
        say(db, req, "Thanks, I've noted your explanation. If you have a document for the difference, upload it and I'll re-check the totals.")
        return

    report = ActivityReport(campaign_id=campaign.id, reporting_request_id=req.id, description=text)
    db.add(report)
    db.flush()
    ai = get_ai()
    if ai is None:
        say(db, req, "Thanks! Automatic reading is off right now, so please add each expense and activity with the form below.", mode="manual")
        return
    try:
        extracted = ai.extract_claims(campaign.title, text)
    except AIUnavailable:
        say(db, req, "Thanks! I couldn't read that automatically. Please add each expense and activity with the form below.", mode="manual")
        return

    lines: list[str] = []
    for e in extracted.expenses:
        db.add(
            ExpenseClaim(
                campaign_id=campaign.id,
                activity_report_id=report.id,
                description=e.description,
                category=e.category,
                amount_cents=round(e.amount * 100),
                currency=(e.currency or campaign.currency).upper(),
                expense_date=e.expense_date.isoformat() if e.expense_date else None,
                amount_uncertain=e.amount_uncertain,
                source="ai",
            )
        )
        hedge = " (you said this was approximate)" if e.amount_uncertain else ""
        lines.append(f"- Expense: {e.description}, {money(round(e.amount * 100), e.currency or campaign.currency)}{hedge}")
    for i in extracted.impacts:
        db.add(ImpactClaim(campaign_id=campaign.id, activity_report_id=report.id, description=i.description, quantity=i.quantity, unit=i.unit, source="ai"))
        qty = f" ({i.quantity:g} {i.unit or ''})".rstrip() if i.quantity is not None else ""
        lines.append(f"- Activity: {i.description}{qty}")
    if not lines:
        say(db, req, "Thanks! I didn't find specific expenses or activities. Could you say what was bought or done, and roughly how much was spent?")
        return
    follow = "".join(f"\nAlso: {q}" for q in extracted.unanswered_questions[:2])
    say(db, req, "Here's what I understood. Please confirm or correct each item:\n" + "\n".join(lines) + follow, step="extract_claims")


# ---------------------------------------------------------------- determine_evidence_needs


def on_claim_confirmed(db: Session, req: ReportingRequest, claim: ExpenseClaim | ImpactClaim) -> None:
    if isinstance(claim, ExpenseClaim):
        if linked_evidence(db, "expense", claim.id):
            evaluate_expense(db, req, claim)
            return
        say(
            db,
            req,
            f"To back up \"{claim.description}\" ({money(claim.amount_cents, claim.currency)}), please upload the "
            "invoice, receipt or payment confirmation. If you don't have one, tell me why and I'll label it "
            "as reported but not documented.",
            step="request_more_information",
            claim_id=claim.id,
        )
    else:
        say(
            db,
            req,
            f"For \"{claim.description}\", an aggregate distribution log (counts and dates, no names) helps donors. "
            "It's optional; without it this stays labelled as your statement.",
            step="request_more_information",
            claim_id=claim.id,
        )


# ---------------------------------------------------------------- evaluate_evidence / clarify


def evaluate_expense(db: Session, req: ReportingRequest, claim: ExpenseClaim) -> None:
    if claim.status != ClaimStatus.REPORTED:
        return  # proposed claims are compared once the NGO confirms them
    cmp = compare_claim_evidence(db, claim)
    findings = {
        "claim_cents": cmp.claim_cents,
        "documented_cents": cmp.documented_cents,
        "gap_cents": cmp.gap_cents,
        "counted_evidence_ids": cmp.counted_evidence_ids,
        "unreadable_evidence_ids": cmp.unreadable_evidence_ids,
        "duplicate_evidence_ids": cmp.duplicate_evidence_ids,
        "currency_mismatch_ids": cmp.currency_mismatch_ids,
    }
    db.add(
        EvidenceCheck(
            claim_type="expense",
            claim_id=claim.id,
            check_type=CheckType.AMOUNT_MATCH,
            status=CheckStatus.PASS if cmp.matches else (CheckStatus.INCONCLUSIVE if cmp.unreadable_evidence_ids and not cmp.counted_evidence_ids else CheckStatus.FLAG),
            findings_json=findings,
        )
    )
    previous = claim.evidence_status
    claim.supported_amount_cents = min(cmp.documented_cents, cmp.claim_cents)
    open_inv = db.scalar(
        select(Investigation).where(Investigation.claim_type == "expense", Investigation.claim_id == claim.id, Investigation.status == InvestigationStatus.OPEN)
    )

    if cmp.unreadable_evidence_ids:
        # Waiting for the NGO to type a total: the upload step already asked, so this
        # is not a discrepancy and must not use up a clarification round.
        claim.evidence_status = EvidenceReviewStatus.SUBMITTED
    elif cmp.matches:
        claim.evidence_status = EvidenceReviewStatus.CONSISTENT
        if open_inv:
            open_inv.status = InvestigationStatus.RECONCILED
            open_inv.resolution = ((open_inv.resolution or "") + f"\nDocuments now total {money(cmp.documented_cents, claim.currency)}, matching the reported amount.").strip()
        say(
            db,
            req,
            f"Thanks. The documents for \"{claim.description}\" now total {money(cmp.documented_cents, claim.currency)}, "
            "which is consistent with what you reported. (That means the paperwork matches; it isn't an independent audit.)",
            step="evaluate_evidence",
            claim_id=claim.id,
        )
    else:
        claim.evidence_status = EvidenceReviewStatus.NEEDS_CLARIFICATION
        question = _clarifying_question(claim, cmp)
        if open_inv is None:
            db.add(Investigation(campaign_id=claim.campaign_id, claim_type="expense", claim_id=claim.id, question=question))
        else:
            open_inv.question = question
        _ask(db, req, question, claim.id)
    audit(db, actor_type="agent", actor_id=None, action="claim.evaluate", entity_type="expense_claim", entity_id=claim.id, previous={"evidence_status": previous}, new={"evidence_status": claim.evidence_status, **findings})


def _clarifying_question(claim: ExpenseClaim, cmp) -> str:
    cur = claim.currency
    if cmp.duplicate_evidence_ids:
        return "One of the documents looks like a copy of a receipt already submitted, so I counted it once. Is there a different document for the rest?"
    if cmp.currency_mismatch_ids:
        return f"A document is in a different currency from the {cur} you reported. What exchange rate or converted amount should be used?"
    if cmp.gap_cents > 0:
        return (
            f"You reported {money(cmp.claim_cents, cur)} for \"{claim.description}\", but the documents total "
            f"{money(cmp.documented_cents, cur)}. Is there another receipt for the remaining {money(cmp.gap_cents, cur)}, "
            "or was the reported amount an estimate?"
        )
    return (
        f"The documents total {money(cmp.documented_cents, cur)}, which is more than the {money(cmp.claim_cents, cur)} "
        "you reported. Should the reported amount be updated, or do some documents belong to a different expense?"
    )


def _ask(db: Session, req: ReportingRequest, question: str, claim_id: str) -> None:
    limit = get_settings().max_clarification_rounds
    if req.clarification_rounds >= limit:
        req.status = ReportingRequestStatus.ESCALATED
        inv = db.scalar(select(Investigation).where(Investigation.claim_id == claim_id, Investigation.status == InvestigationStatus.OPEN))
        if inv:
            inv.status = InvestigationStatus.ESCALATED
        say(db, req, "I've asked a few times without resolving this, so a reviewer will take a look. Nothing has been marked as wrongdoing.", step="escalate", claim_id=claim_id)
        return
    req.clarification_rounds += 1
    say(db, req, question, step="clarify", claim_id=claim_id)


def record_no_evidence(db: Session, req: ReportingRequest, claim: ExpenseClaim | ImpactClaim, explanation: str, user_id: str) -> None:
    claim.evidence_status = EvidenceReviewStatus.NOT_DOCUMENTED
    say(db, req, f"No document available: {explanation}", MessageSender.NGO, user_id=user_id, claim_id=claim.id)
    say(db, req, "Understood. Donors will see this as reported by you, not independently documented.", claim_id=claim.id)


# ---------------------------------------------------------------- draft_update / queue_for_review


def _settled(status: str) -> bool:
    return status in (EvidenceReviewStatus.CONSISTENT, EvidenceReviewStatus.NOT_DOCUMENTED, EvidenceReviewStatus.REVIEWED_BY_HUMAN)


def is_ready_for_draft(db: Session, req: ReportingRequest) -> bool:
    """Every confirmed expense is settled and nothing is waiting for NGO confirmation."""
    db.flush()
    expenses, impacts = claims_for_request(db, req)
    reported = [c for c in expenses if c.status == ClaimStatus.REPORTED]
    pending = [c for c in expenses + impacts if c.status == ClaimStatus.PROPOSED]
    return bool(reported) and not pending and all(_settled(c.evidence_status) for c in reported)


def draft_donor_update(db: Session, campaign: Campaign, req: ReportingRequest | None) -> DonorUpdate:
    """Build a campaign-level update ONLY from persisted claims and checks.

    Every sentence carries provenance (claim ids and evidence ids). Wording is a
    deterministic template so the draft can never contain a claim the records lack.
    """
    q = select(ExpenseClaim).where(ExpenseClaim.campaign_id == campaign.id, ExpenseClaim.status == ClaimStatus.REPORTED)
    iq = select(ImpactClaim).where(ImpactClaim.campaign_id == campaign.id, ImpactClaim.status == ClaimStatus.REPORTED)
    if req is not None:
        report_ids = select(ActivityReport.id).where(ActivityReport.reporting_request_id == req.id)
        q, iq = q.where(ExpenseClaim.activity_report_id.in_(report_ids)), iq.where(ImpactClaim.activity_report_id.in_(report_ids))
    expenses, impacts = list(db.scalars(q)), list(db.scalars(iq))

    sentences: list[dict] = []
    public_refs: list[str] = []
    for c in expenses:
        evs = linked_evidence(db, "expense", c.id)
        ev_ids = [e.id for e in evs]
        public_refs += [e.id for e in evs if e.visibility == EvidenceVisibility.PUBLIC]
        amt = money(c.amount_cents, c.currency)
        if c.evidence_status == EvidenceReviewStatus.CONSISTENT:
            n = len(evs)
            text = f"The organization reported spending {amt} on {c.description}. {n} supporting document{'s' if n != 1 else ''} totaling {money(c.supported_amount_cents, c.currency)} {'were' if n != 1 else 'was'} reviewed and {'are' if n != 1 else 'is'} consistent with this amount."
        elif c.evidence_status == EvidenceReviewStatus.NEEDS_CLARIFICATION:
            text = f"The organization reported spending {amt} on {c.description}. Documents reviewed so far support {money(c.supported_amount_cents, c.currency)}; the rest is awaiting clarification."
        elif c.evidence_status == EvidenceReviewStatus.REVIEWED_BY_HUMAN:
            text = f"The organization reported spending {amt} on {c.description}. A platform reviewer examined the supporting material."
        elif c.evidence_status == EvidenceReviewStatus.NOT_DOCUMENTED:
            text = f"The organization reported spending {amt} on {c.description}. This has not been independently documented."
        else:
            text = f"The organization reported spending {amt} on {c.description}. Supporting documents have not been provided yet."
        sentences.append({"text": text, "claim_type": "expense", "claim_id": c.id, "evidence_ids": ev_ids, "evidence_status": c.evidence_status})
    for i in impacts:
        qty = f" ({i.quantity:g} {i.unit or ''})".rstrip() if i.quantity is not None else ""
        text = f"The organization reports: {i.description}{qty}. This is the organization's statement; NGOLog has not independently confirmed it."
        sentences.append({"text": text, "claim_type": "impact", "claim_id": i.id, "evidence_ids": [], "evidence_status": i.evidence_status})
    if not sentences:
        sentences.append({"text": "No new spending or activity has been reported for this period.", "claim_type": None, "claim_id": None, "evidence_ids": [], "evidence_status": None})
    footer = "\"Consistent\" means the documents match the reported amounts. It is not an independent audit."
    body = "\n\n".join(s["text"] for s in sentences) + "\n\n" + footer

    update = DonorUpdate(
        campaign_id=campaign.id,
        reporting_request_id=req.id if req else None,
        title=f"Update on {campaign.title}",
        body=body,
        evidence_refs_json=sorted(set(public_refs)),
        provenance_json=sentences,
    )
    db.add(update)
    if req is not None and req.status in (ReportingRequestStatus.OPEN, ReportingRequestStatus.IN_REVIEW):
        req.status = ReportingRequestStatus.AWAITING_APPROVAL
    audit(db, actor_type="agent", actor_id=None, action="donor_update.draft", entity_type="donor_update", entity_id=update.id)
    return update


def mark_published(db: Session, update: DonorUpdate) -> None:
    update.status = PublicationStatus.PUBLISHED
    update.published_at = utcnow()
    if update.reporting_request_id:
        req = db.get(ReportingRequest, update.reporting_request_id)
        if req and req.status != ReportingRequestStatus.ESCALATED:
            req.status = ReportingRequestStatus.COMPLETED

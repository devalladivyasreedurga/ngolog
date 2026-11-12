from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent import retrieval, runtime, workflow
from app.agent.checks import linked_evidence
from app.reporting import jobs
from app.audit import audit
from app.auth.deps import current_user, load_campaign_for_editor, require_role
from app.db.base import get_db, utcnow
from app.db.models import (
    ActivityReport,
    AgentMessage,
    Campaign,
    Evidence,
    EvidenceCheck,
    ExpenseClaim,
    DonorUpdate,
    ImpactClaim,
    Investigation,
    ReportingRequest,
    User,
)
from contracts.reporting_schemas import (
    CampaignStatus,
    CheckType,
    ClaimOut,
    ClaimStatus,
    EvidenceCheckOut,
    EvidenceReviewStatus,
    InvestigationStatus,
    PublicationStatus,
    ReportingRequestOut,
    ReportingRequestStatus,
    Role,
)

router = APIRouter(prefix="/api", tags=["reporting"])


class TriggerIn(BaseModel):
    cycle_key: str | None = Field(default=None, max_length=40)


class MessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=5000)


class MessageOut(BaseModel):
    id: str
    sender_role: str
    content: str
    meta: dict
    created_at: datetime


class EvidenceOut(BaseModel):
    id: str
    kind: str
    original_filename: str
    file_type: str
    visibility: str
    extracted: dict | None
    confirmed: dict | None
    claim_ids: list[str]
    created_at: datetime


class InvestigationOut(BaseModel):
    id: str
    campaign_id: str
    claim_type: str
    claim_id: str
    status: InvestigationStatus
    question: str
    resolution: str | None
    created_at: datetime


class ThreadOut(BaseModel):
    request: ReportingRequestOut
    campaign_id: str
    campaign_title: str
    messages: list[MessageOut]
    claims: list[ClaimOut]
    evidence: list[EvidenceOut]
    checks: list[EvidenceCheckOut]
    investigations: list[InvestigationOut]


class ManualClaimIn(BaseModel):
    claim_type: str = Field(pattern="^(expense|impact)$")
    description: str = Field(min_length=2, max_length=500)
    amount: float | None = Field(default=None, gt=0, le=1_000_000)
    quantity: float | None = Field(default=None, ge=0)
    unit: str | None = None


class ConfirmIn(BaseModel):
    amount: float | None = Field(default=None, gt=0, le=1_000_000)
    description: str | None = None


class NoEvidenceIn(BaseModel):
    explanation: str = Field(min_length=3, max_length=2000)


class ResolveIn(BaseModel):
    resolution: str = Field(min_length=3, max_length=2000)


# ---------------------------------------------------------------- serializers


def request_out(r: ReportingRequest) -> ReportingRequestOut:
    return ReportingRequestOut(
        id=r.id, campaign_id=r.campaign_id, cycle_key=r.cycle_key, status=ReportingRequestStatus(r.status),
        due_at=r.due_at, clarification_rounds=r.clarification_rounds, created_at=r.created_at,
    )


def claim_out(db: Session, c: ExpenseClaim | ImpactClaim) -> ClaimOut:
    is_exp = isinstance(c, ExpenseClaim)
    ctype = "expense" if is_exp else "impact"
    return ClaimOut(
        id=c.id, campaign_id=c.campaign_id, claim_type=ctype, description=c.description,
        amount_cents=c.amount_cents if is_exp else None, currency=c.currency if is_exp else None,
        quantity=None if is_exp else c.quantity, unit=None if is_exp else c.unit,
        status=ClaimStatus(c.status), evidence_status=EvidenceReviewStatus(c.evidence_status),
        supported_amount_cents=c.supported_amount_cents if is_exp else None,
        evidence_ids=[e.id for e in linked_evidence(db, ctype, c.id)],
        report_id=c.activity_report_id,
    )


def evidence_out(db: Session, e: Evidence) -> EvidenceOut:
    from app.db.models import ClaimEvidence

    claim_ids = list(db.scalars(select(ClaimEvidence.claim_id).where(ClaimEvidence.evidence_id == e.id)))
    return EvidenceOut(
        id=e.id, kind=e.kind, original_filename=e.original_filename, file_type=e.file_type, visibility=e.visibility,
        extracted=e.extracted_json, confirmed=e.confirmed_json, claim_ids=claim_ids, created_at=e.created_at,
    )


def check_out(c: EvidenceCheck) -> EvidenceCheckOut:
    from contracts.reporting_schemas import CheckStatus

    return EvidenceCheckOut(id=c.id, evidence_id=c.evidence_id, claim_id=c.claim_id, check_type=CheckType(c.check_type), status=CheckStatus(c.status), findings=c.findings_json, created_at=c.created_at)


def investigation_out(i: Investigation) -> InvestigationOut:
    return InvestigationOut(id=i.id, campaign_id=i.campaign_id, claim_type=i.claim_type, claim_id=i.claim_id, status=InvestigationStatus(i.status), question=i.question, resolution=i.resolution, created_at=i.created_at)


def load_request_for_editor(db: Session, user: User, request_id: str) -> tuple[ReportingRequest, Campaign]:
    req = db.get(ReportingRequest, request_id)
    if req is None:
        raise HTTPException(404, "Reporting request not found")
    return req, load_campaign_for_editor(db, user, req.campaign_id)


def load_claim(db: Session, user: User, claim_type: str, claim_id: str) -> tuple[ExpenseClaim | ImpactClaim, ReportingRequest]:
    model = {"expense": ExpenseClaim, "impact": ImpactClaim}.get(claim_type)
    claim = db.get(model, claim_id) if model else None
    if claim is None:
        raise HTTPException(404, "Claim not found")
    load_campaign_for_editor(db, user, claim.campaign_id)
    report = db.get(ActivityReport, claim.activity_report_id)
    return claim, db.get(ReportingRequest, report.reporting_request_id)


def build_thread(db: Session, req: ReportingRequest, campaign: Campaign) -> ThreadOut:
    thread = workflow.thread_for(db, req)
    messages = db.scalars(select(AgentMessage).where(AgentMessage.thread_id == thread.id).order_by(AgentMessage.created_at, AgentMessage.id))
    expenses, impacts = workflow.claims_for_request(db, req)
    claims = [claim_out(db, c) for c in expenses + impacts]
    claim_ids = [c.id for c in claims]
    evidence = db.scalars(select(Evidence).where(Evidence.reporting_request_id == req.id).order_by(Evidence.created_at))
    checks = db.scalars(select(EvidenceCheck).where(EvidenceCheck.claim_id.in_(claim_ids)).order_by(EvidenceCheck.created_at)) if claim_ids else []
    invs = db.scalars(select(Investigation).where(Investigation.claim_id.in_(claim_ids)).order_by(Investigation.created_at)) if claim_ids else []
    return ThreadOut(
        request=request_out(req), campaign_id=campaign.id, campaign_title=campaign.title,
        messages=[MessageOut(id=m.id, sender_role=m.sender_role, content=m.content, meta=m.meta_json or {}, created_at=m.created_at) for m in messages],
        claims=claims, evidence=[evidence_out(db, e) for e in evidence], checks=[check_out(c) for c in checks],
        investigations=[investigation_out(i) for i in invs],
    )


# ---------------------------------------------------------------- routes


@router.get("/campaigns/{campaign_id}/reporting-requests", response_model=list[ReportingRequestOut])
def list_requests(campaign_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = load_campaign_for_editor(db, user, campaign_id)
    rows = db.scalars(select(ReportingRequest).where(ReportingRequest.campaign_id == c.id).order_by(ReportingRequest.created_at.desc()))
    return [request_out(r) for r in rows]


def _request_to_open(db: Session, campaign: Campaign, cycle_key: str | None, user_id: str) -> ReportingRequest:
    """The update to work on now. An update that is still open (or overdue, so it can still be answered) is
    reopened as it is. Otherwise a new one starts: this period's if it has not been used, else an extra one,
    so an NGO can report again after publishing without waiting for the schedule."""
    if cycle_key is None:
        open_one = db.scalar(
            select(ReportingRequest)
            .where(
                ReportingRequest.campaign_id == campaign.id,
                ReportingRequest.status.in_([*jobs.BLOCKING_STATUSES, ReportingRequestStatus.OVERDUE]),
            )
            .order_by(ReportingRequest.created_at.desc())
        )
        if open_one is not None:
            return open_one
    req, created = workflow.open_reporting_request(db, campaign, cycle_key=cycle_key, actor_id=user_id)
    if not created and cycle_key is None:  # this period's update is already finished: start an extra one
        req, _ = workflow.open_reporting_request(db, campaign, cycle_key=f"extra-{utcnow():%Y%m%d%H%M%S}", actor_id=user_id)
    return req


@router.post("/campaigns/{campaign_id}/reporting-requests/trigger", response_model=ThreadOut)
def trigger(campaign_id: str, body: TriggerIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Demo/admin: open this cycle's follow-up now instead of waiting for the scheduler."""
    c = load_campaign_for_editor(db, user, campaign_id)
    if c.status != CampaignStatus.PUBLISHED:
        raise HTTPException(409, "Publish the campaign first")
    if not workflow.campaign_has_donations(db, c.id):
        raise HTTPException(409, "No donations yet, so there is nothing to report. Updates start after the first donation.")
    req = _request_to_open(db, c, body.cycle_key, user.id)
    runtime.start_cycle(db, req)
    db.commit()
    return build_thread(db, req, c)


@router.get("/reporting-requests/{request_id}/thread", response_model=ThreadOut)
def get_thread(request_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    req, c = load_request_for_editor(db, user, request_id)
    return build_thread(db, req, c)


@router.post("/reporting-requests/{request_id}/messages", response_model=ThreadOut)
def post_message(request_id: str, body: MessageIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    req, c = load_request_for_editor(db, user, request_id)
    if req.status in (ReportingRequestStatus.COMPLETED,):
        raise HTTPException(409, "This reporting cycle is closed")
    runtime.dispatch(db, req, {"type": "message", "user_id": user.id, "text": body.content})
    db.commit()
    return build_thread(db, req, c)


@router.post("/reporting-requests/{request_id}/claims", response_model=ThreadOut)
def add_manual_claim(request_id: str, body: ManualClaimIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Manual entry path (works when AI is off or wrong). Saved as REPORTED directly."""
    req, c = load_request_for_editor(db, user, request_id)
    report = workflow._latest_report(db, req)
    if report is None:
        report = ActivityReport(campaign_id=c.id, reporting_request_id=req.id, description=body.description)
        db.add(report)
        db.flush()
        retrieval.index(db, retrieval.doc_for_report(db, report))
    if body.claim_type == "expense":
        if body.amount is None:
            raise HTTPException(422, "Expense claims need an amount")
        claim = ExpenseClaim(campaign_id=c.id, activity_report_id=report.id, description=body.description, amount_cents=round(body.amount * 100), currency=c.currency, status=ClaimStatus.REPORTED, source="manual")
    else:
        claim = ImpactClaim(campaign_id=c.id, activity_report_id=report.id, description=body.description, quantity=body.quantity, unit=body.unit, status=ClaimStatus.REPORTED, source="manual")
    db.add(claim)
    if req.status in (ReportingRequestStatus.OPEN, ReportingRequestStatus.OVERDUE):
        req.status = ReportingRequestStatus.IN_REVIEW
    db.flush()
    audit(db, actor_type="user", actor_id=user.id, action="claim.manual_create", entity_type=f"{body.claim_type}_claim", entity_id=claim.id)
    runtime.dispatch(db, req, {"type": "claim_confirmed", "claim_type": body.claim_type, "claim_id": claim.id})
    db.commit()
    return build_thread(db, req, c)


@router.post("/reporting-requests/{request_id}/claims/confirm", response_model=ThreadOut)
def confirm_all_claims(request_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Chat button: 'Yes, that's right' confirms everything the assistant proposed."""
    req, c = load_request_for_editor(db, user, request_id)
    if req.status == ReportingRequestStatus.COMPLETED:
        raise HTTPException(409, "This reporting cycle is closed")
    runtime.dispatch(db, req, {"type": "claims_confirmed", "user_id": user.id})
    db.commit()
    return build_thread(db, req, c)


@router.post("/reporting-requests/{request_id}/claims/reject", response_model=ThreadOut)
def reject_all_claims(request_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Chat button: 'Not quite' drops the proposal and asks again."""
    req, c = load_request_for_editor(db, user, request_id)
    if req.status == ReportingRequestStatus.COMPLETED:
        raise HTTPException(409, "This reporting cycle is closed")
    workflow.reject_proposed(db, req, user.id)
    db.commit()
    return build_thread(db, req, c)


@router.post("/claims/{claim_type}/{claim_id}/confirm", response_model=ThreadOut)
def confirm_claim(claim_type: str, claim_id: str, body: ConfirmIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    claim, req = load_claim(db, user, claim_type, claim_id)
    before = {"status": claim.status, "description": claim.description}
    if body.description:
        claim.description = body.description
    if isinstance(claim, ExpenseClaim):
        before["amount_cents"] = claim.amount_cents
        if body.amount is not None:
            claim.amount_cents = round(body.amount * 100)
            claim.amount_uncertain = False
    claim.status = ClaimStatus.REPORTED
    audit(db, actor_type="user", actor_id=user.id, action="claim.confirm", entity_type=f"{claim_type}_claim", entity_id=claim.id, previous=before, new={"status": claim.status})
    runtime.dispatch(db, req, {"type": "claim_confirmed", "claim_type": claim_type, "claim_id": claim.id})
    db.commit()
    return build_thread(db, req, db.get(Campaign, claim.campaign_id))


@router.post("/claims/{claim_type}/{claim_id}/withdraw", response_model=ThreadOut)
def withdraw_claim(claim_type: str, claim_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    claim, req = load_claim(db, user, claim_type, claim_id)
    if claim.status == ClaimStatus.WITHDRAWN:
        return build_thread(db, req, db.get(Campaign, claim.campaign_id))
    shown = db.scalars(select(DonorUpdate).where(DonorUpdate.campaign_id == claim.campaign_id, DonorUpdate.status == PublicationStatus.PUBLISHED))
    if any(p.get("claim_id") == claim.id for u in shown for p in u.provenance_json):
        raise HTTPException(409, "Donors have already seen this in a published update, so it can't be removed")
    workflow.claim_removed(db, req, claim, user.id)
    db.commit()
    return build_thread(db, req, db.get(Campaign, claim.campaign_id))


@router.post("/claims/{claim_type}/{claim_id}/no-evidence", response_model=ThreadOut)
def no_evidence(claim_type: str, claim_id: str, body: NoEvidenceIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    claim, req = load_claim(db, user, claim_type, claim_id)
    if claim.status != ClaimStatus.REPORTED:
        raise HTTPException(409, "Confirm the claim first")
    runtime.dispatch(db, req, {"type": "no_evidence", "claim_type": claim_type, "claim_id": claim.id, "explanation": body.explanation, "user_id": user.id})
    db.commit()
    return build_thread(db, req, db.get(Campaign, claim.campaign_id))


@router.get("/campaigns/{campaign_id}/claims", response_model=list[ClaimOut])
def campaign_claims(campaign_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = load_campaign_for_editor(db, user, campaign_id)
    exp = db.scalars(select(ExpenseClaim).where(ExpenseClaim.campaign_id == c.id).order_by(ExpenseClaim.created_at))
    imp = db.scalars(select(ImpactClaim).where(ImpactClaim.campaign_id == c.id).order_by(ImpactClaim.created_at))
    return [claim_out(db, x) for x in list(exp) + list(imp)]


@router.get("/campaigns/{campaign_id}/investigations", response_model=list[InvestigationOut])
def campaign_investigations(campaign_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = load_campaign_for_editor(db, user, campaign_id)
    return [investigation_out(i) for i in db.scalars(select(Investigation).where(Investigation.campaign_id == c.id).order_by(Investigation.created_at))]


@router.post("/investigations/{investigation_id}/resolve", response_model=InvestigationOut)
def resolve_investigation(investigation_id: str, body: ResolveIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_role(user, Role.REVIEWER)
    inv = db.get(Investigation, investigation_id)
    if inv is None:
        raise HTTPException(404, "Investigation not found")
    before = {"status": inv.status}
    inv.status = InvestigationStatus.RESOLVED_BY_REVIEWER
    inv.resolution = ((inv.resolution or "") + f"\nReviewer: {body.resolution}").strip()
    inv.resolved_by_user_id = user.id
    claim = db.get(ExpenseClaim if inv.claim_type == "expense" else ImpactClaim, inv.claim_id)
    if claim is not None:
        claim.evidence_status = EvidenceReviewStatus.REVIEWED_BY_HUMAN
    audit(db, actor_type="user", actor_id=user.id, action="investigation.resolve", entity_type="investigation", entity_id=inv.id, previous=before, new={"status": inv.status}, reason=body.resolution)
    db.commit()
    return investigation_out(inv)

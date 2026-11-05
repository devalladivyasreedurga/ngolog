"""Accountability console data: one row per claim, plus reporting requests needing attention.

Totals come from Postgres. Reviewers see every campaign; an NGO sees only its own.
"""

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.checks import linked_evidence
from app.auth.deps import current_user, ngo_for_user, require_role
from app.db.base import get_db, utcnow
from app.db.models import (
    ActivityReport,
    Campaign,
    EvidenceCheck,
    ExpenseClaim,
    ImpactClaim,
    Investigation,
    Ngo,
    ReportingRequest,
    User,
)
from contracts.reporting_schemas import InvestigationStatus, ReportingRequestStatus, Role

router = APIRouter(prefix="/api/accountability", tags=["accountability"])

OPEN_INVESTIGATIONS = (InvestigationStatus.OPEN, InvestigationStatus.ESCALATED)


class CheckRow(BaseModel):
    check_type: str
    status: str
    findings: dict
    created_at: datetime


class ClaimRow(BaseModel):
    claim_id: str
    claim_type: str
    campaign_id: str
    campaign_title: str
    ngo_name: str
    description: str
    claim_status: str
    evidence_status: str
    reported_cents: int | None
    supported_cents: int | None
    gap_cents: int | None
    currency: str | None
    evidence_count: int
    reporting_request_id: str
    request_status: str
    investigation_id: str | None
    investigation_status: str | None
    open_question: str | None
    checks: list[CheckRow]
    created_at: datetime


class RequestRow(BaseModel):
    reporting_request_id: str
    campaign_id: str
    campaign_title: str
    ngo_name: str
    cycle_key: str
    status: str
    due_at: datetime | None
    past_due: bool
    clarification_rounds: int


class ConsoleOut(BaseModel):
    claims: list[ClaimRow]
    requests: list[RequestRow]


def _campaigns(db: Session, user: User) -> list[Campaign]:
    require_role(user, Role.NGO_ADMIN, Role.REVIEWER)
    q = select(Campaign)
    if user.role == Role.NGO_ADMIN:
        q = q.where(Campaign.ngo_id == ngo_for_user(db, user).id)
    return list(db.scalars(q))


def _claim_row(db: Session, claim: ExpenseClaim | ImpactClaim, campaign: Campaign, ngo_name: str) -> ClaimRow:
    is_expense = isinstance(claim, ExpenseClaim)
    claim_type = "expense" if is_expense else "impact"
    report = db.get(ActivityReport, claim.activity_report_id)
    req = db.get(ReportingRequest, report.reporting_request_id)
    inv = db.scalar(
        select(Investigation)
        .where(Investigation.claim_type == claim_type, Investigation.claim_id == claim.id)
        .order_by(Investigation.created_at.desc())
    )
    evidence = linked_evidence(db, claim_type, claim.id)
    evidence_ids = [e.id for e in evidence]
    checks = list(
        db.scalars(
            select(EvidenceCheck)
            .where((EvidenceCheck.claim_id == claim.id) | (EvidenceCheck.evidence_id.in_(evidence_ids)))
            .order_by(EvidenceCheck.created_at.desc())
        )
    )
    return ClaimRow(
        claim_id=claim.id,
        claim_type=claim_type,
        campaign_id=campaign.id,
        campaign_title=campaign.title,
        ngo_name=ngo_name,
        description=claim.description,
        claim_status=claim.status,
        evidence_status=claim.evidence_status,
        reported_cents=claim.amount_cents if is_expense else None,
        supported_cents=claim.supported_amount_cents if is_expense else None,
        gap_cents=(claim.amount_cents - claim.supported_amount_cents) if is_expense else None,
        currency=claim.currency if is_expense else None,
        evidence_count=len(evidence),
        reporting_request_id=req.id,
        request_status=req.status,
        investigation_id=inv.id if inv else None,
        investigation_status=inv.status if inv else None,
        open_question=inv.question if inv and inv.status in OPEN_INVESTIGATIONS else None,
        checks=[CheckRow(check_type=c.check_type, status=c.status, findings=c.findings_json, created_at=c.created_at) for c in checks],
        created_at=claim.created_at,
    )


@router.get("", response_model=ConsoleOut)
def console(user: User = Depends(current_user), db: Session = Depends(get_db)) -> ConsoleOut:
    claims: list[ClaimRow] = []
    requests: list[RequestRow] = []
    now = utcnow()
    for c in _campaigns(db, user):
        ngo = db.get(Ngo, c.ngo_id)
        for model in (ExpenseClaim, ImpactClaim):
            for claim in db.scalars(select(model).where(model.campaign_id == c.id).order_by(model.created_at.desc())):
                claims.append(_claim_row(db, claim, c, ngo.name))
        for r in db.scalars(select(ReportingRequest).where(ReportingRequest.campaign_id == c.id)):
            past_due = r.status == ReportingRequestStatus.OVERDUE or (
                r.status == ReportingRequestStatus.OPEN and r.due_at is not None and r.due_at < now
            )
            requests.append(
                RequestRow(
                    reporting_request_id=r.id,
                    campaign_id=c.id,
                    campaign_title=c.title,
                    ngo_name=ngo.name,
                    cycle_key=r.cycle_key,
                    status=r.status,
                    due_at=r.due_at,
                    past_due=past_due,
                    clarification_rounds=r.clarification_rounds,
                )
            )
    return ConsoleOut(claims=claims, requests=requests)

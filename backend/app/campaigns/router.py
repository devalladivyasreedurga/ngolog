from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agent.llm import AIUnavailable, get_ai
from app.audit import audit
from app.auth.deps import (
    current_user,
    load_campaign_for_editor,
    ngo_for_user,
    optional_user,
    require_role,
)
from app.db.base import get_db, utcnow
from app.db.models import Campaign, Donation, ExpenseClaim, Ngo, ReportingPlan, User
from contracts.reporting_schemas import (
    CampaignStatus,
    ClaimStatus,
    DonationStatus,
    Role,
)

router = APIRouter(prefix="/api", tags=["campaigns"])

COUNTED_DONATION_STATUSES = (DonationStatus.CAPTURED, DonationStatus.COMPLETED)

TEMPLATE_PLANS: dict[str, dict[str, list[str]]] = {
    "school_supplies": {
        "questions": [
            "What did you buy since the last update, from whom, and for how much?",
            "How many kits or items have been handed out so far?",
            "Is anything delayed or different from the plan?",
        ],
        "evidence": [
            "Supplier invoice or receipt for each purchase",
            "Aggregate distribution log (counts only, no student names)",
            "A photo of supplies without identifiable children",
        ],
    },
    "general": {
        "questions": [
            "What happened since the last update?",
            "Have campaign funds been spent? On what, and how much?",
            "Is anything delayed or different from the plan?",
        ],
        "evidence": [
            "Receipts or invoices for purchases",
            "Payment confirmations",
            "Photos of the activity that do not identify beneficiaries",
        ],
    },
}
TEMPLATE_LIMITATIONS = [
    "Receipts show what was purchased, not that items reached beneficiaries.",
    "Photos can show an activity happened somewhere; they are not proof on their own.",
]


class NgoIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    description: str = ""
    accept_reporting_agreement: bool


class NgoOut(BaseModel):
    id: str
    name: str
    description: str
    reporting_agreement_accepted_at: datetime | None


class CampaignIn(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(min_length=10)
    category: str = "general"
    target_amount: float = Field(gt=0, le=1_000_000)
    expected_activities: str = ""
    location_coarse: str | None = None
    reporting_frequency_days: int = Field(default=7, ge=1, le=90)


class CampaignPatch(BaseModel):
    title: str | None = None
    description: str | None = None
    expected_activities: str | None = None
    location_coarse: str | None = None
    reporting_frequency_days: int | None = Field(default=None, ge=1, le=90)


class PlanIn(BaseModel):
    questions: list[str]
    evidence_suggestions: list[str]
    limitations: list[str] = []


class PlanOut(PlanIn):
    id: str
    version: int
    source: str
    approved_at: datetime | None


class CampaignOut(BaseModel):
    id: str
    ngo_id: str
    ngo_name: str
    title: str
    description: str
    category: str
    target_amount_cents: int
    currency: str
    expected_activities: str
    location_coarse: str | None
    status: CampaignStatus
    reporting_frequency_days: int
    next_followup_at: datetime | None
    donations_received_cents: int
    donor_count: int
    reported_expenses_cents: int
    document_supported_cents: int


def campaign_out(db: Session, c: Campaign) -> CampaignOut:
    ngo = db.get(Ngo, c.ngo_id)
    received, donors = db.execute(
        select(func.coalesce(func.sum(Donation.amount_cents), 0), func.count(func.distinct(Donation.donor_user_id)))
        .where(Donation.campaign_id == c.id, Donation.status.in_(COUNTED_DONATION_STATUSES))
    ).one()
    reported, supported = db.execute(
        select(
            func.coalesce(func.sum(ExpenseClaim.amount_cents), 0),
            func.coalesce(func.sum(ExpenseClaim.supported_amount_cents), 0),
        ).where(ExpenseClaim.campaign_id == c.id, ExpenseClaim.status == ClaimStatus.REPORTED)
    ).one()
    return CampaignOut(
        id=c.id,
        ngo_id=c.ngo_id,
        ngo_name=ngo.name if ngo else "",
        title=c.title,
        description=c.description,
        category=c.category,
        target_amount_cents=c.target_amount_cents,
        currency=c.currency,
        expected_activities=c.expected_activities,
        location_coarse=c.location_coarse,
        status=CampaignStatus(c.status),
        reporting_frequency_days=c.reporting_frequency_days,
        next_followup_at=c.next_followup_at,
        donations_received_cents=int(received),
        donor_count=int(donors),
        reported_expenses_cents=int(reported),
        document_supported_cents=int(supported),
    )


def _plan_out(p: ReportingPlan) -> PlanOut:
    return PlanOut(
        id=p.id,
        version=p.version,
        source=p.source,
        approved_at=p.approved_at,
        questions=p.proposed_questions_json,
        evidence_suggestions=p.evidence_suggestions_json,
        limitations=p.limitations_json,
    )


def latest_plan(db: Session, campaign_id: str) -> ReportingPlan | None:
    return db.scalar(
        select(ReportingPlan).where(ReportingPlan.campaign_id == campaign_id).order_by(ReportingPlan.version.desc())
    )


# ---------------------------------------------------------------- NGOs


@router.post("/ngos", response_model=NgoOut)
def create_ngo(body: NgoIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> NgoOut:
    require_role(user, Role.NGO_ADMIN)
    if not body.accept_reporting_agreement:
        raise HTTPException(422, "NGOs must accept the reporting agreement")
    if db.scalar(select(Ngo).where(Ngo.owner_user_id == user.id)):
        raise HTTPException(409, "NGO already exists for this account")
    ngo = Ngo(owner_user_id=user.id, name=body.name, description=body.description, reporting_agreement_accepted_at=utcnow())
    db.add(ngo)
    db.commit()
    return NgoOut(id=ngo.id, name=ngo.name, description=ngo.description, reporting_agreement_accepted_at=ngo.reporting_agreement_accepted_at)


@router.get("/ngos/me", response_model=NgoOut)
def my_ngo(user: User = Depends(current_user), db: Session = Depends(get_db)) -> NgoOut:
    ngo = ngo_for_user(db, user)
    return NgoOut(id=ngo.id, name=ngo.name, description=ngo.description, reporting_agreement_accepted_at=ngo.reporting_agreement_accepted_at)


# ---------------------------------------------------------------- campaigns


@router.post("/campaigns", response_model=CampaignOut)
def create_campaign(body: CampaignIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> CampaignOut:
    require_role(user, Role.NGO_ADMIN)
    ngo = ngo_for_user(db, user)
    c = Campaign(
        ngo_id=ngo.id,
        title=body.title,
        description=body.description,
        category=body.category,
        target_amount_cents=round(body.target_amount * 100),
        expected_activities=body.expected_activities,
        location_coarse=body.location_coarse,
        reporting_frequency_days=body.reporting_frequency_days,
    )
    db.add(c)
    audit(db, actor_type="user", actor_id=user.id, action="campaign.create", entity_type="campaign", entity_id=c.id)
    db.commit()
    return campaign_out(db, c)


@router.get("/campaigns", response_model=list[CampaignOut])
def list_campaigns(mine: bool = False, user: User | None = Depends(optional_user), db: Session = Depends(get_db)):
    q = select(Campaign).order_by(Campaign.created_at.desc())
    if mine:
        if user is None:
            raise HTTPException(401, "Sign in required")
        q = q.where(Campaign.ngo_id == ngo_for_user(db, user).id)
    else:
        q = q.where(Campaign.status == CampaignStatus.PUBLISHED)
    return [campaign_out(db, c) for c in db.scalars(q)]


@router.get("/campaigns/{campaign_id}", response_model=CampaignOut)
def get_campaign(campaign_id: str, user: User | None = Depends(optional_user), db: Session = Depends(get_db)):
    c = db.get(Campaign, campaign_id)
    if c is None:
        raise HTTPException(404, "Campaign not found")
    if c.status == CampaignStatus.DRAFT:
        if user is None:
            raise HTTPException(404, "Campaign not found")
        c = load_campaign_for_editor(db, user, campaign_id)
    return campaign_out(db, c)


@router.patch("/campaigns/{campaign_id}", response_model=CampaignOut)
def patch_campaign(campaign_id: str, body: CampaignPatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = load_campaign_for_editor(db, user, campaign_id)
    before = {k: getattr(c, k) for k in body.model_fields_set}
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(c, k, v)
    audit(db, actor_type="user", actor_id=user.id, action="campaign.update", entity_type="campaign", entity_id=c.id, previous=before, new=body.model_dump(exclude_unset=True))
    db.commit()
    return campaign_out(db, c)


@router.post("/campaigns/{campaign_id}/publish", response_model=CampaignOut)
def publish_campaign(campaign_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = load_campaign_for_editor(db, user, campaign_id)
    plan = latest_plan(db, c.id)
    if plan is None or plan.approved_at is None:
        raise HTTPException(409, "Accept a reporting plan before publishing")
    if c.status != CampaignStatus.PUBLISHED:
        c.status = CampaignStatus.PUBLISHED
        c.published_at = utcnow()
        c.next_followup_at = utcnow() + timedelta(days=c.reporting_frequency_days)
        audit(db, actor_type="user", actor_id=user.id, action="campaign.publish", entity_type="campaign", entity_id=c.id)
        db.commit()
    return campaign_out(db, c)


# ---------------------------------------------------------------- reporting plan


@router.post("/campaigns/{campaign_id}/reporting-plan/draft", response_model=PlanOut)
def draft_plan(campaign_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = load_campaign_for_editor(db, user, campaign_id)
    template = TEMPLATE_PLANS.get(c.category, TEMPLATE_PLANS["general"])
    questions, evidence, limitations, source = template["questions"], template["evidence"], TEMPLATE_LIMITATIONS, "template"
    ai = get_ai()
    if ai is not None:
        try:
            draft = ai.draft_reporting_plan(c.title, c.category, c.description, c.expected_activities)
            questions, evidence, limitations, source = draft.questions, draft.evidence_suggestions, draft.limitations, "ai"
        except AIUnavailable:
            pass  # template plan is a safe fallback
    prev = latest_plan(db, c.id)
    plan = ReportingPlan(
        campaign_id=c.id,
        version=(prev.version + 1) if prev else 1,
        proposed_questions_json=questions,
        evidence_suggestions_json=evidence,
        limitations_json=limitations,
        source=source,
    )
    db.add(plan)
    db.commit()
    return _plan_out(plan)


@router.get("/campaigns/{campaign_id}/reporting-plan", response_model=PlanOut | None)
def get_plan(campaign_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = load_campaign_for_editor(db, user, campaign_id)
    p = latest_plan(db, c.id)
    return _plan_out(p) if p else None


@router.put("/campaigns/{campaign_id}/reporting-plan", response_model=PlanOut)
def accept_plan(campaign_id: str, body: PlanIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """NGO edits and accepts the plan. Saved as a new version with source='ngo'."""
    c = load_campaign_for_editor(db, user, campaign_id)
    if not body.questions:
        raise HTTPException(422, "A reporting plan needs at least one question")
    prev = latest_plan(db, c.id)
    plan = ReportingPlan(
        campaign_id=c.id,
        version=(prev.version + 1) if prev else 1,
        proposed_questions_json=body.questions,
        evidence_suggestions_json=body.evidence_suggestions,
        limitations_json=body.limitations,
        source="ngo",
        approved_at=utcnow(),
    )
    db.add(plan)
    audit(db, actor_type="user", actor_id=user.id, action="reporting_plan.accept", entity_type="campaign", entity_id=c.id)
    db.commit()
    return _plan_out(plan)

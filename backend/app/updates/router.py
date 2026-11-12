from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent import retrieval, runtime, workflow
from app.audit import audit
from app.auth.deps import current_user, load_campaign_for_editor, optional_user, require_role
from app.campaigns.router import CampaignOut, campaign_out, latest_plan
from app.db.base import get_db, utcnow
from app.notifications import zapier_email
from app.db.models import (
    Campaign,
    DonorUpdate,
    Evidence,
    Notification,
    NotificationSubscription,
    ReportingRequest,
    User,
)
from contracts.reporting_schemas import (
    CampaignStatus,
    DeliveryStatus,
    DonorUpdateOut,
    EvidenceKind,
    EvidenceVisibility,
    PublicationStatus,
    ReportingRequestStatus,
    Role,
)

router = APIRouter(prefix="/api", tags=["donor updates"])


class DraftIn(BaseModel):
    reporting_request_id: str | None = None


class SubscribeIn(BaseModel):
    email_enabled: bool = True


class TimelineEntry(BaseModel):
    update: DonorUpdateOut
    provenance: list[dict]
    photos: list[str] = []  # ids of photos the NGO shared for this update (never receipts)


class TimelineOut(BaseModel):
    campaign: CampaignOut
    entries: list[TimelineEntry]
    totals_note: str
    reporting_overdue: bool
    limitations: list[str] = []


class NotificationOut(BaseModel):
    id: str
    donor_update_id: str
    campaign_id: str
    title: str
    channel: str
    status: str
    created_at: datetime


def update_out(u: DonorUpdate) -> DonorUpdateOut:
    return DonorUpdateOut(
        id=u.id, campaign_id=u.campaign_id, title=u.title, body=u.body, evidence_refs=u.evidence_refs_json,
        status=PublicationStatus(u.status), approved_by=u.approved_by, published_at=u.published_at, created_at=u.created_at,
    )


def _shared_photos(db: Session, u: DonorUpdate) -> list[str]:
    """Photos from this update's reporting round that the NGO has not made private. Receipts are never included."""
    if not u.reporting_request_id:
        return []
    return list(db.scalars(
        select(Evidence.id)
        .where(Evidence.reporting_request_id == u.reporting_request_id, Evidence.kind == EvidenceKind.PHOTO, Evidence.visibility == EvidenceVisibility.PUBLIC)
        .order_by(Evidence.created_at)
    ))


def _load_update(db: Session, user: User, update_id: str) -> tuple[DonorUpdate, Campaign]:
    u = db.get(DonorUpdate, update_id)
    if u is None:
        raise HTTPException(404, "Update not found")
    return u, load_campaign_for_editor(db, user, u.campaign_id)


def _assert_refs_publishable(db: Session, u: DonorUpdate) -> None:
    """A donor-facing update may only cite this campaign's evidence that the NGO made public."""
    for ref in u.evidence_refs_json:
        ev = db.get(Evidence, ref)
        if ev is None or ev.campaign_id != u.campaign_id or ev.visibility != EvidenceVisibility.PUBLIC:
            raise HTTPException(409, f"Update cites evidence {ref} that is not public for this campaign")


@router.post("/campaigns/{campaign_id}/updates/draft", response_model=DonorUpdateOut)
def draft(campaign_id: str, body: DraftIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = load_campaign_for_editor(db, user, campaign_id)
    req = None
    if body.reporting_request_id:
        req = db.get(ReportingRequest, body.reporting_request_id)
        if req is None or req.campaign_id != c.id:
            raise HTTPException(404, "Reporting request not found")
    u = workflow.draft_donor_update(db, c, req)
    db.commit()
    return update_out(u)


@router.get("/campaigns/{campaign_id}/updates", response_model=list[TimelineEntry])
def list_updates(campaign_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = load_campaign_for_editor(db, user, campaign_id)
    rows = db.scalars(select(DonorUpdate).where(DonorUpdate.campaign_id == c.id).order_by(DonorUpdate.created_at.desc()))
    return [TimelineEntry(update=update_out(u), provenance=u.provenance_json, photos=_shared_photos(db, u)) for u in rows]


@router.post("/updates/{update_id}/approve", response_model=DonorUpdateOut)
def approve(update_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_role(user, Role.NGO_ADMIN, Role.REVIEWER)
    u, _ = _load_update(db, user, update_id)
    if u.status != PublicationStatus.DRAFT:
        raise HTTPException(409, f"Update is {u.status}")
    _assert_refs_publishable(db, u)
    u.status = PublicationStatus.APPROVED
    u.approved_by = user.id
    audit(db, actor_type="user", actor_id=user.id, action="donor_update.approve", entity_type="donor_update", entity_id=u.id)
    db.commit()
    return update_out(u)


@router.post("/updates/{update_id}/publish", response_model=DonorUpdateOut)
def publish(update_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_role(user, Role.NGO_ADMIN, Role.REVIEWER)
    u, c = _load_update(db, user, update_id)
    if u.status == PublicationStatus.PUBLISHED:
        return update_out(u)  # idempotent
    if u.status != PublicationStatus.APPROVED:
        raise HTTPException(409, "Approve the update before publishing")
    _assert_refs_publishable(db, u)
    workflow.mark_published(db, u)
    retrieval.index(db, retrieval.doc_for_update(db, u))
    if u.reporting_request_id:
        runtime.dispatch(db, db.get(ReportingRequest, u.reporting_request_id), {"type": "close"})
    # In-app notifications always; email via Zapier MCP only when configured (see app/notifications/zapier_email.py).
    for sub in db.scalars(select(NotificationSubscription).where(NotificationSubscription.campaign_id == c.id)):
        key = f"update:{u.id}:donor:{sub.donor_user_id}:in_app"
        if db.scalar(select(Notification).where(Notification.idempotency_key == key)) is None:
            db.add(Notification(donor_user_id=sub.donor_user_id, donor_update_id=u.id, channel="in_app", status=DeliveryStatus.SENT, provider="in_app", idempotency_key=key, sent_at=utcnow()))
    audit(db, actor_type="user", actor_id=user.id, action="donor_update.publish", entity_type="donor_update", entity_id=u.id)
    db.commit()  # publication is durable before any email goes out
    zapier_email.deliver_update_emails(db, u, c)
    db.commit()
    return update_out(u)


@router.get("/campaigns/{campaign_id}/timeline", response_model=TimelineOut)
def timeline(campaign_id: str, user: User | None = Depends(optional_user), db: Session = Depends(get_db)):
    c = db.get(Campaign, campaign_id)
    if c is None or (c.status == CampaignStatus.DRAFT and (user is None or not _can_edit(db, user, c.id))):
        raise HTTPException(404, "Campaign not found")
    rows = db.scalars(
        select(DonorUpdate).where(DonorUpdate.campaign_id == c.id, DonorUpdate.status == PublicationStatus.PUBLISHED).order_by(DonorUpdate.published_at.desc())
    )
    plan = latest_plan(db, c.id)
    return TimelineOut(
        campaign=campaign_out(db, c),
        entries=[TimelineEntry(update=update_out(u), provenance=_public_provenance(u.provenance_json), photos=_shared_photos(db, u)) for u in rows],
        totals_note=(
            "Donations received are PayPal-confirmed captures. Reported spending is what the organization "
            "says it spent; document-supported spending is the part matched by reviewed documents. "
            "Neither is an audited account balance."
        ),
        reporting_overdue=db.scalar(select(ReportingRequest.id).where(ReportingRequest.campaign_id == c.id, ReportingRequest.status == ReportingRequestStatus.OVERDUE).limit(1)) is not None,
        limitations=list(plan.limitations_json) if plan else [],
    )


def _public_provenance(prov: list[dict]) -> list[dict]:
    # Donors see statuses and claim links, not private evidence ids.
    return [{k: v for k, v in p.items() if k != "evidence_ids"} | {"evidence_count": len(p.get("evidence_ids", []))} for p in prov]


def _can_edit(db: Session, user: User, campaign_id: str) -> bool:
    try:
        load_campaign_for_editor(db, user, campaign_id)
        return True
    except HTTPException:
        return False


@router.post("/campaigns/{campaign_id}/notifications/subscribe")
def subscribe(campaign_id: str, body: SubscribeIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_role(user, Role.DONOR)
    if db.get(Campaign, campaign_id) is None:
        raise HTTPException(404, "Campaign not found")
    sub = db.scalar(select(NotificationSubscription).where(NotificationSubscription.campaign_id == campaign_id, NotificationSubscription.donor_user_id == user.id))
    if sub is None:
        sub = NotificationSubscription(campaign_id=campaign_id, donor_user_id=user.id)
        db.add(sub)
    sub.email_enabled = body.email_enabled
    db.commit()
    return {"campaign_id": campaign_id, "email_enabled": sub.email_enabled}


@router.get("/notifications/mine", response_model=list[NotificationOut])
def my_notifications(user: User = Depends(current_user), db: Session = Depends(get_db)):
    out = []
    for n in db.scalars(select(Notification).where(Notification.donor_user_id == user.id).order_by(Notification.created_at.desc())):
        u = db.get(DonorUpdate, n.donor_update_id)
        out.append(NotificationOut(id=n.id, donor_update_id=n.donor_update_id, campaign_id=u.campaign_id, title=u.title, channel=n.channel, status=n.status, created_at=n.created_at))
    return out

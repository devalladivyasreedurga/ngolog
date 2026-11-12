"""Scheduled accountability jobs. Safe to run repeatedly or concurrently: reporting
requests are unique per cycle and reminders have unique idempotency keys.

No-response path (spec flow E): first request -> one reminder -> one final follow-up
-> `overdue`. Overdue means no update was provided; it says nothing about spending.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agent import runtime, workflow
from app.audit import audit
from app.config import get_settings
from app.db.base import utcnow
from app.db.models import Campaign, Ngo, OutboundMessage, ReportingRequest
from contracts.reporting_schemas import (
    CampaignStatus,
    DeliveryStatus,
    MessageSender,
    OutboundKind,
    ReportingRequestStatus,
)

log = logging.getLogger(__name__)

BLOCKING_STATUSES = (
    ReportingRequestStatus.OPEN,
    ReportingRequestStatus.IN_REVIEW,
    ReportingRequestStatus.AWAITING_APPROVAL,
    ReportingRequestStatus.ESCALATED,
)
REMINDER_TEXT = "Just a reminder: donors are waiting to hear how \"{title}\" is going. A short reply here is enough to start."
FINAL_TEXT = "This is the last follow-up for this update on \"{title}\". If nothing arrives, the campaign page will say no recent update has been provided."


@dataclass
class JobResult:
    opened: int = 0
    reminded: int = 0
    overdue: int = 0


def run_due_followups(db: Session, now: datetime | None = None) -> int:
    now = now or utcnow()
    due = db.scalars(
        select(Campaign).where(Campaign.status == CampaignStatus.PUBLISHED, Campaign.next_followup_at <= now)
    ).all()
    opened = 0
    for campaign in due:
        next_at = now + timedelta(days=campaign.reporting_frequency_days)
        if not workflow.campaign_has_donations(db, campaign.id):  # nothing donated, nothing to report yet
            campaign.next_followup_at = next_at
            db.commit()
            continue
        unfinished = db.scalar(
            select(ReportingRequest).where(ReportingRequest.campaign_id == campaign.id, ReportingRequest.status.in_(BLOCKING_STATUSES))
        )
        if unfinished is not None:  # never stack a new request on an unanswered one
            campaign.next_followup_at = next_at
            db.commit()
            continue
        try:
            req, created = workflow.open_reporting_request(db, campaign, cycle_key=workflow.current_cycle_key(campaign, now))
            campaign.next_followup_at = next_at
            runtime.start_cycle(db, req)
            db.commit()
            opened += int(created)
        except IntegrityError:
            db.rollback()  # another worker opened this cycle first
    return opened


def _queue_in_app(db: Session, req: ReportingRequest, campaign: Campaign, kind: OutboundKind, n: int, text: str, now: datetime) -> bool:
    """Record the delivery; False if this reminder was already sent."""
    key = f"{req.id}:{kind}:{n}"
    if db.scalar(select(OutboundMessage).where(OutboundMessage.idempotency_key == key)):
        return False
    ngo = db.get(Ngo, campaign.ngo_id)
    db.add(
        OutboundMessage(
            campaign_id=campaign.id,
            reporting_request_id=req.id,
            kind=kind,
            recipient_user_id=ngo.owner_user_id,
            body=text,
            content_hash=hashlib.sha256(text.encode()).hexdigest(),
            provider="in_app",
            idempotency_key=key,
            status=DeliveryStatus.SENT,
            sent_at=now,
        )
    )
    workflow.say(db, req, text, MessageSender.AGENT, step="reminder", reminder=n)
    return True


def send_reminders(db: Session, now: datetime | None = None) -> tuple[int, int]:
    now = now or utcnow()
    gap = timedelta(days=get_settings().reminder_interval_days)
    reminded = overdue = 0
    for req in db.scalars(select(ReportingRequest).where(ReportingRequest.status == ReportingRequestStatus.OPEN)).all():
        campaign = db.get(Campaign, req.campaign_id)
        if campaign.status != CampaignStatus.PUBLISHED:
            continue
        last_touch = req.last_reminded_at or req.created_at
        if now < last_touch + gap:
            continue
        if req.reminder_count < 2:
            n = req.reminder_count + 1
            text = (REMINDER_TEXT if n == 1 else FINAL_TEXT).format(title=campaign.title)
            kind = OutboundKind.NGO_REMINDER
            if _queue_in_app(db, req, campaign, kind, n, text, now):
                reminded += 1
            req.reminder_count = n
            req.last_reminded_at = now
        elif req.due_at is None or now >= req.due_at:
            req.status = ReportingRequestStatus.OVERDUE
            audit(db, actor_type="system", actor_id=None, action="reporting_request.overdue", entity_type="reporting_request", entity_id=req.id)
            overdue += 1
        db.commit()
    return reminded, overdue


def run_all(db: Session, now: datetime | None = None) -> JobResult:
    opened = run_due_followups(db, now)
    reminded, overdue = send_reminders(db, now)
    return JobResult(opened=opened, reminded=reminded, overdue=overdue)

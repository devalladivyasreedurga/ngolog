import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit import audit
from app.auth.deps import current_user, require_role
from app.config import get_settings
from app.db.base import get_db, utcnow
from app.db.models import Campaign, Donation, NotificationSubscription, User, WebhookEvent
from app.payments.paypal_client import PayPalError, get_paypal
from contracts.reporting_schemas import CampaignStatus, DonationStatus, Role

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["payments"])

MIN_DONATION_CENTS, MAX_DONATION_CENTS = 100, 1_000_000


class OrderIn(BaseModel):
    amount: float = Field(ge=1, le=10_000)


class OrderOut(BaseModel):
    donation_id: str
    paypal_order_id: str


class DonationOut(BaseModel):
    id: str
    campaign_id: str
    campaign_title: str
    amount_cents: int
    currency: str
    status: DonationStatus
    paypal_order_id: str | None
    paypal_capture_id: str | None
    webhook_confirmed: bool
    created_at: datetime


def _donation_out(db: Session, d: Donation) -> DonationOut:
    c = db.get(Campaign, d.campaign_id)
    return DonationOut(
        id=d.id,
        campaign_id=d.campaign_id,
        campaign_title=c.title if c else "",
        amount_cents=d.amount_cents,
        currency=d.currency,
        status=DonationStatus(d.status),
        paypal_order_id=d.paypal_order_id,
        paypal_capture_id=d.paypal_capture_id,
        webhook_confirmed=d.webhook_confirmed_at is not None,
        created_at=d.created_at,
    )


def _paypal_http_error(e: PayPalError) -> HTTPException:
    log.warning("PayPal error %s: %s", e.status_code, e.body)
    if e.status_code == 503:
        return HTTPException(503, str(e))
    return HTTPException(502, "PayPal request failed; no money was taken")


@router.post("/campaigns/{campaign_id}/paypal/orders", response_model=OrderOut)
def create_order(campaign_id: str, body: OrderIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_role(user, Role.DONOR)
    c = db.get(Campaign, campaign_id)
    if c is None or c.status != CampaignStatus.PUBLISHED:
        raise HTTPException(404, "Campaign not found")
    amount_cents = round(body.amount * 100)
    donation = Donation(campaign_id=c.id, donor_user_id=user.id, amount_cents=amount_cents, currency=c.currency)
    db.add(donation)
    db.flush()
    try:
        order = get_paypal().create_order(
            donation_id=donation.id,
            campaign_id=c.id,
            amount_cents=amount_cents,
            currency=c.currency,
            description=f"NGOLog donation: {c.title}",
        )
    except PayPalError as e:
        db.rollback()
        raise _paypal_http_error(e)
    donation.paypal_order_id = order["id"]
    db.commit()
    return OrderOut(donation_id=donation.id, paypal_order_id=order["id"])


@router.post("/paypal/orders/{order_id}/capture", response_model=DonationOut)
def capture_order(order_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    donation = db.scalar(select(Donation).where(Donation.paypal_order_id == order_id))
    if donation is None or donation.donor_user_id != user.id:
        raise HTTPException(404, "Donation not found")
    if donation.status in (DonationStatus.CAPTURED, DonationStatus.COMPLETED):
        return _donation_out(db, donation)  # idempotent repeat
    try:
        result = get_paypal().capture_order(order_id=order_id, donation_id=donation.id)
    except PayPalError as e:
        # 422 ORDER_ALREADY_CAPTURED and friends: re-read the order instead of guessing.
        if e.status_code == 422:
            try:
                result = get_paypal().get_order(order_id)
            except PayPalError as e2:
                raise _paypal_http_error(e2)
        else:
            raise _paypal_http_error(e)
    capture = _first_capture(result)
    if result.get("status") != "COMPLETED" or capture is None or capture.get("status") != "COMPLETED":
        donation.status = DonationStatus.FAILED
        db.commit()
        raise HTTPException(402, "PayPal did not complete the payment; no money was taken")
    _apply_capture(db, donation, capture)
    db.commit()
    return _donation_out(db, donation)


def _first_capture(order: dict) -> dict | None:
    for unit in order.get("purchase_units", []):
        for cap in unit.get("payments", {}).get("captures", []):
            return cap
    return None


def _apply_capture(db: Session, donation: Donation, capture: dict) -> None:
    """Record a server-confirmed capture. The amount must match what we asked for."""
    value = capture.get("amount", {}).get("value")
    if value is not None and round(float(value) * 100) != donation.amount_cents:
        log.error("Capture amount mismatch for donation %s: %s", donation.id, value)
        raise HTTPException(409, "Captured amount does not match the donation; flagged for review")
    donation.paypal_capture_id = capture["id"]
    if donation.status != DonationStatus.COMPLETED:
        donation.status = DonationStatus.CAPTURED
    if not db.scalar(
        select(NotificationSubscription).where(
            NotificationSubscription.campaign_id == donation.campaign_id,
            NotificationSubscription.donor_user_id == donation.donor_user_id,
        )
    ):
        db.add(NotificationSubscription(campaign_id=donation.campaign_id, donor_user_id=donation.donor_user_id))
    audit(db, actor_type="paypal", actor_id=capture["id"], action="donation.captured", entity_type="donation", entity_id=donation.id)


@router.post("/paypal/webhook")
async def paypal_webhook(request: Request, db: Session = Depends(get_db)):
    event = await request.json()
    settings = get_settings()
    try:
        verified = get_paypal().verify_webhook(headers=dict(request.headers), event=event, webhook_id=settings.paypal_webhook_id)
    except PayPalError as e:
        log.warning("Webhook verification call failed: %s", e)
        raise HTTPException(503, "Could not verify webhook; PayPal will retry")
    if not verified:
        raise HTTPException(400, "Webhook signature verification failed")

    record = WebhookEvent(provider="paypal", event_id=event["id"], event_type=event.get("event_type", ""), payload_json=event)
    db.add(record)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return {"status": "duplicate"}  # already processed: idempotent

    if event.get("event_type") == "PAYMENT.CAPTURE.COMPLETED":
        resource = event.get("resource", {})
        order_id = resource.get("supplementary_data", {}).get("related_ids", {}).get("order_id")
        donation = db.scalar(select(Donation).where(Donation.paypal_capture_id == resource.get("id")))
        if donation is None and order_id:
            donation = db.scalar(select(Donation).where(Donation.paypal_order_id == order_id))
        if donation is not None:
            if donation.paypal_capture_id is None:
                _apply_capture(db, donation, resource)
            donation.status = DonationStatus.COMPLETED
            donation.webhook_confirmed_at = utcnow()
    elif event.get("event_type") in ("PAYMENT.CAPTURE.REFUNDED", "PAYMENT.CAPTURE.REVERSED"):
        capture_id = resource_capture_id(event)
        donation = db.scalar(select(Donation).where(Donation.paypal_capture_id == capture_id)) if capture_id else None
        if donation is not None:
            donation.status = DonationStatus.REFUNDED
    record.processed_at = utcnow()
    db.commit()
    return {"status": "processed"}


def resource_capture_id(event: dict) -> str | None:
    for link in event.get("resource", {}).get("links", []):
        if link.get("rel") == "up" and "/captures/" in link.get("href", ""):
            return link["href"].rstrip("/").rsplit("/", 1)[-1]
    return None


@router.get("/donations/mine", response_model=list[DonationOut])
def my_donations(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(Donation)
        .where(Donation.donor_user_id == user.id, Donation.status != DonationStatus.CREATED)
        .order_by(Donation.created_at.desc())
    )
    return [_donation_out(db, d) for d in rows]

"""Seed the demo story (spec section 8). Safe to run repeatedly.

    backend/.venv/bin/python scripts/seed_demo.py

Creates demo accounts, the school-supplies campaign, an overdue campaign, and fictional
receipt images in scripts/demo_assets/. It deliberately creates NO donations: the demo
money must be a real PayPal sandbox capture, never a seeded row.
"""

import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT)]

from PIL import Image, ImageDraw, ImageFont  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.agent import runtime, workflow  # noqa: E402
from app.campaigns.router import TEMPLATE_LIMITATIONS, TEMPLATE_PLANS  # noqa: E402
from app.db.base import SessionLocal, utcnow  # noqa: E402
from app.db.models import Campaign, Ngo, ReportingPlan, ReportingRequest, User  # noqa: E402
from contracts.reporting_schemas import CampaignStatus, ReportingRequestStatus, Role  # noqa: E402

ASSETS = ROOT / "scripts" / "demo_assets"
USERS = [
    ("ngo@brightfutures.org", Role.NGO_ADMIN),
    ("donor@example.com", Role.DONOR),
    ("reviewer@ngolog.org", Role.REVIEWER),
]
RECEIPTS = {
    "receipt-420.png": ("INV-1042", [("School kit, 21 units at $20.00", 420.00)]),
    "receipt-80.png": ("INV-1043", [("Kit carry bags, 40 units at $2.00", 80.00)]),
    "receipt-25.png": ("INV-1044", [("Pens and notebooks set, 5 units at $5.00", 25.00)]),
    # Same story, different invoice numbers and bytes, for practice runs. The reused-receipt
    # check works across an NGO's campaigns, so rehearsing with the recording files would
    # make the recording flag them as already submitted.
    "rehearsal-receipt-420.png": ("INV-2042", [("School kit, 21 units at $20.00", 420.00)]),
    "rehearsal-receipt-80.png": ("INV-2043", [("Kit carry bags, 40 units at $2.00", 80.00)]),
}


def font(size: int):
    for name in ("Helvetica.ttc", "Arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def draw_receipt(path: Path, number: str, items: list[tuple[str, float]]) -> None:
    img = Image.new("RGB", (620, 620), "white")
    d = ImageDraw.Draw(img)
    d.text((40, 30), "Demo Stationers", fill="black", font=font(34))
    d.text((40, 76), "FICTIONAL BUSINESS - DEMO DATA", fill=(170, 30, 30), font=font(20))
    d.text((40, 130), f"Invoice no: {number}", fill="black", font=font(24))
    d.text((40, 166), "Date: 2026-11-03", fill="black", font=font(24))
    y = 240
    for label, amount in items:
        d.text((40, y), label, fill="black", font=font(22))
        d.text((480, y), f"${amount:,.2f}", fill="black", font=font(22))
        y += 40
    d.line((40, y + 10, 580, y + 10), fill="black", width=2)
    d.text((40, y + 30), "TOTAL (USD)", fill="black", font=font(28))
    d.text((460, y + 30), f"${sum(a for _, a in items):,.2f}", fill="black", font=font(28))
    img.save(path)


def user(db, email: str, role: Role) -> User:
    found = db.scalar(select(User).where(User.email == email))
    if found is None:
        found = User(email=email, role=role)
        db.add(found)
        db.flush()
    return found


def ensure_plan(db, campaign: Campaign) -> None:
    if db.scalar(select(ReportingPlan).where(ReportingPlan.campaign_id == campaign.id, ReportingPlan.approved_at.is_not(None))):
        return
    template = TEMPLATE_PLANS.get(campaign.category, TEMPLATE_PLANS["general"])
    db.add(ReportingPlan(campaign_id=campaign.id, version=1, proposed_questions_json=template["questions"], evidence_suggestions_json=template["evidence"], limitations_json=TEMPLATE_LIMITATIONS, source="template", approved_at=utcnow()))


def campaign(db, ngo: Ngo, title: str, description: str, category: str, target_cents: int, published_days_ago: int) -> Campaign:
    found = db.scalar(select(Campaign).where(Campaign.ngo_id == ngo.id, Campaign.title == title))
    if found is None:
        when = utcnow() - timedelta(days=published_days_ago)
        found = Campaign(ngo_id=ngo.id, title=title, description=description, category=category, target_amount_cents=target_cents, status=CampaignStatus.PUBLISHED, published_at=when, created_at=when, next_followup_at=utcnow() + timedelta(days=7))
        db.add(found)
        db.flush()
    ensure_plan(db, found)
    return found


def main() -> None:
    ASSETS.mkdir(exist_ok=True)
    for name, (number, items) in RECEIPTS.items():
        draw_receipt(ASSETS / name, number, items)

    db = SessionLocal()
    try:
        ngo_user, _, _ = [user(db, e, r) for e, r in USERS]
        ngo = db.scalar(select(Ngo).where(Ngo.owner_user_id == ngo_user.id))
        if ngo is None:
            ngo = Ngo(owner_user_id=ngo_user.id, name="Bright Futures School Trust", description="Fictional demo organization.", reporting_agreement_accepted_at=utcnow())
            db.add(ngo)
            db.flush()
        school = campaign(db, ngo, "Supply 50 students with school kits", "School supply kits (notebooks, pens, bags) for 50 students at a rural primary school. Fictional demo data.", "school_supplies", 100000, 0)
        library = campaign(db, ngo, "Restock the village reading room", "New books for a community reading room. Fictional demo data, seeded to show an overdue update.", "general", 50000, 10)

        # The no-response path: asked, reminded twice, nothing received.
        key = "seed-overdue"
        req = db.scalar(select(ReportingRequest).where(ReportingRequest.campaign_id == library.id, ReportingRequest.cycle_key == key))
        if req is None:
            req, _ = workflow.open_reporting_request(db, library, cycle_key=key)
            req.created_at = utcnow() - timedelta(days=6)
            req.due_at = utcnow() - timedelta(days=3)
            req.last_reminded_at = utcnow() - timedelta(days=4)
            req.reminder_count = 2
            req.status = ReportingRequestStatus.OVERDUE
            runtime.start_cycle(db, req)
        db.commit()
        print(f"Seeded. School campaign: {school.id}  Overdue campaign: {library.id}")
        print(f"Demo receipts: {ASSETS}")
    finally:
        db.close()


if __name__ == "__main__":
    main()

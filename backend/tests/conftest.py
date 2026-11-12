"""Test harness. PayPal and Claude are replaced with in-process fakes HERE ONLY;
the running app always talks to the real PayPal sandbox and Claude API."""

import json
import os
import re
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="ngolog-test-"))
os.environ.update(
    DATABASE_URL=f"sqlite:///{_tmp / 'unused.db'}",
    UPLOAD_DIR=str(_tmp / "uploads"),
    SECRET_KEY="test-secret",
    REVIEWER_EMAILS="reviewer@ngolog.org",
    PAYPAL_WEBHOOK_ID="WH-TEST",
    SCHEDULER_ENABLED="false",
    ANTHROPIC_API_KEY="",
    PAYPAL_CLIENT_ID="",
    PAYPAL_CLIENT_SECRET="",
)

import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.agent.llm import set_ai_provider  # noqa: E402
from app.agent.runtime import set_checkpointer  # noqa: E402
from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402
from app.db.base import Base, get_db, make_engine  # noqa: E402
from app.main import app  # noqa: E402
from app.payments.paypal_client import set_paypal_transport  # noqa: E402
from contracts.reporting_schemas import (  # noqa: E402
    ExtractedClaims,
    ExtractedExpense,
    ExtractedImpact,
    ReceiptExtraction,
)

# ---------------------------------------------------------------- fake PayPal


class FakePayPal:
    def __init__(self):
        self.orders: dict[str, dict] = {}
        self.capture_calls = 0
        self.request_ids: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "A21-test", "expires_in": 3600})
        if "PayPal-Request-Id" in request.headers:
            self.request_ids.append(request.headers["PayPal-Request-Id"])
        if path == "/v2/checkout/orders" and request.method == "POST":
            body = json.loads(request.content)
            oid = f"ORDER{len(self.orders) + 1}"
            unit = body["purchase_units"][0]
            self.orders[oid] = {"id": oid, "status": "CREATED", "amount": unit["amount"], "reference_id": unit["reference_id"]}
            return httpx.Response(201, json={"id": oid, "status": "CREATED"})
        m = re.fullmatch(r"/v2/checkout/orders/(\w+)/capture", path)
        if m:
            self.capture_calls += 1
            order = self.orders[m.group(1)]
            if order["status"] == "COMPLETED":
                return httpx.Response(422, json={"name": "UNPROCESSABLE_ENTITY", "details": [{"issue": "ORDER_ALREADY_CAPTURED"}]})
            order["status"] = "COMPLETED"
            return httpx.Response(201, json=self._order_body(order))
        m = re.fullmatch(r"/v2/checkout/orders/(\w+)", path)
        if m:
            return httpx.Response(200, json=self._order_body(self.orders[m.group(1)]))
        if path == "/v1/notifications/verify-webhook-signature":
            body = json.loads(request.content)
            ok = body["transmission_sig"] == "valid-sig" and body["webhook_id"] == "WH-TEST"
            return httpx.Response(200, json={"verification_status": "SUCCESS" if ok else "FAILURE"})
        return httpx.Response(404, json={"name": "NOT_FOUND"})

    def _order_body(self, order: dict) -> dict:
        return {
            "id": order["id"],
            "status": order["status"],
            "purchase_units": [
                {"reference_id": order["reference_id"], "payments": {"captures": [{"id": f"CAP-{order['id']}", "status": "COMPLETED", "amount": order["amount"]}]}}
            ],
        }


# ---------------------------------------------------------------- fake Claude


class FakeAI:
    """Deterministic stand-in for Claude: reads '$N' amounts and 'TOTAL=N' markers."""

    def draft_reporting_plan(self, title, category, description, activities):
        from app.agent.llm import ReportingPlanDraft

        return ReportingPlanDraft(questions=["What did you buy?"], evidence_suggestions=["Receipts"], limitations=["Receipts don't prove delivery"])

    def extract_claims(self, campaign_title, ngo_message):
        expenses, impacts = [], []
        m = re.search(r"bought (\d+) (\w[\w ]*?) for \$(\d+)", ngo_message)
        if m:
            expenses.append(ExtractedExpense(description=f"{m.group(1)} {m.group(2)}", amount=float(m.group(3))))
        else:
            n = re.search(r"bought (\d+) ([a-z ]+?)(?: and |\.|$)", ngo_message)
            if n:  # no price stated: the real model returns amount=null
                expenses.append(ExtractedExpense(description=f"{n.group(1)} {n.group(2).strip()}", amount=None))
        d = re.search(r"(?:distributed|handed out) (\d+)", ngo_message)
        if d:
            impacts.append(ExtractedImpact(description="kits distributed to students", quantity=float(d.group(1)), unit="kits"))
        shares = bool(re.search(r"pictures|photos", ngo_message))
        return ExtractedClaims(is_report="?" not in ngo_message and not shares, wants_to_share_files=shares, expenses=expenses, impacts=impacts)

    def classify_reply(self, campaign_title, open_question, ngo_message):
        from contracts.reporting_schemas import ClassifiedReply, ReplyIntent

        t = ngo_message.lower()
        if "pictures" in t or "photos" in t:
            intent = ReplyIntent.SHARE_FILES
        elif "?" in t:
            intent = ReplyIntent.QUESTION
        elif "nope" in t or "no doc" in t or "threw it away" in t or "dont have" in t:
            intent = ReplyIntent.NO_DOCUMENT
        elif "bought" in t or "handed out" in t:
            intent = ReplyIntent.NEW_REPORT
        else:
            intent = ReplyIntent.EXPLANATION
        return ClassifiedReply(intent=intent)

    def extract_receipt(self, data, media_type):
        m = re.search(rb"TOTAL=(\d+(?:\.\d+)?)", data)
        n = re.search(rb"NO=(\w+)", data)
        return ReceiptExtraction(
            merchant="Demo Stationers",
            receipt_number=n.group(1).decode() if n else None,
            total=float(m.group(1)) if m else None,
            currency="USD",
        )


def png(marker: str) -> bytes:
    return b"\x89PNG\r\n\x1a\n" + marker.encode()


# ---------------------------------------------------------------- fixtures


@pytest.fixture
def paypal():
    fake = FakePayPal()
    set_paypal_transport(httpx.MockTransport(fake.handler))
    yield fake
    set_paypal_transport(None)


@pytest.fixture
def ai():
    set_ai_provider(FakeAI())
    yield
    set_ai_provider(None)


@pytest.fixture
def no_ai():
    set_ai_provider(None)
    yield


@pytest.fixture
def client(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    def _db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _db
    set_checkpointer(InMemorySaver())
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    engine.dispose()


def fund_campaign(client, campaign_id, cents=2500):
    """Record one counted donation straight in the test database (the PayPal flow has its own tests)."""
    from app.db.models import Donation, User
    from contracts.reporting_schemas import DonationStatus

    login(client, "funder@example.com", "donor")
    db = next(app.dependency_overrides[get_db]())
    donor = db.query(User).filter_by(email="funder@example.com").one()
    db.add(Donation(campaign_id=campaign_id, donor_user_id=donor.id, amount_cents=cents, status=DonationStatus.CAPTURED))
    db.commit()
    db.close()


def login(client, email, role) -> dict:
    r = client.post("/api/auth/demo-login", json={"email": email, "role": role})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture
def ngo(client):
    h = login(client, "ngo@school.example.com", "ngo_admin")
    r = client.post("/api/ngos", json={"name": "Bright Futures School Trust", "accept_reporting_agreement": True}, headers=h)
    assert r.status_code == 200, r.text
    return h


@pytest.fixture
def published_campaign(client, ngo):
    r = client.post(
        "/api/campaigns",
        json={"title": "Supply 50 students with school kits", "description": "School supply kits for 50 students in a rural school.", "category": "school_supplies", "target_amount": 1000},
        headers=ngo,
    )
    assert r.status_code == 200, r.text
    cid = r.json()["id"]
    plan = client.post(f"/api/campaigns/{cid}/reporting-plan/draft", headers=ngo).json()
    r = client.put(f"/api/campaigns/{cid}/reporting-plan", json={"questions": plan["questions"], "evidence_suggestions": plan["evidence_suggestions"], "limitations": plan["limitations"]}, headers=ngo)
    assert r.status_code == 200, r.text
    r = client.post(f"/api/campaigns/{cid}/publish", headers=ngo)
    assert r.status_code == 200, r.text
    return cid


def webhook_headers(sig="valid-sig"):
    return {
        "PAYPAL-AUTH-ALGO": "SHA256withRSA",
        "PAYPAL-CERT-URL": "https://api.sandbox.paypal.com/cert.pem",
        "PAYPAL-TRANSMISSION-ID": "tid-1",
        "PAYPAL-TRANSMISSION-SIG": sig,
        "PAYPAL-TRANSMISSION-TIME": "2026-11-04T10:00:00Z",
    }


def capture_webhook(event_id: str, order_id: str, amount: str = "25.00") -> dict:
    return {
        "id": event_id,
        "event_type": "PAYMENT.CAPTURE.COMPLETED",
        "resource": {
            "id": f"CAP-{order_id}",
            "status": "COMPLETED",
            "amount": {"currency_code": "USD", "value": amount},
            "supplementary_data": {"related_ids": {"order_id": order_id}},
        },
    }

"""Scheduler: idempotent follow-ups, capped reminders, neutral overdue wording."""

from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.db.base import get_db, utcnow
from app.db.models import AgentMessage, Campaign, OutboundMessage, ReportingRequest
from app.main import app
from app.reporting import jobs
from tests.conftest import login
from tests.test_safeguards import open_request


@pytest.fixture
def db(client):
    gen = app.dependency_overrides[get_db]()
    session = next(gen)
    yield session
    session.close()


def _make_due(db, cid):
    c = db.get(Campaign, cid)
    c.next_followup_at = utcnow() - timedelta(minutes=1)
    db.commit()
    return c


def _request(db, cid):
    return db.scalars(select(ReportingRequest).where(ReportingRequest.campaign_id == cid)).one()


def test_due_campaign_gets_one_request_however_often_the_job_runs(client, db, published_campaign):
    _make_due(db, published_campaign)
    assert jobs.run_due_followups(db) == 1
    _make_due(db, published_campaign)
    assert jobs.run_due_followups(db) == 0  # unanswered request blocks a new one
    assert db.scalar(select(func.count()).select_from(ReportingRequest)) == 1
    assert db.get(Campaign, published_campaign).next_followup_at > utcnow()


def test_not_due_and_draft_campaigns_are_skipped(client, db, ngo, published_campaign):
    r = client.post("/api/campaigns", json={"title": "Draft one", "description": "Still a draft campaign.", "target_amount": 10}, headers=ngo)
    db.get(Campaign, r.json()["id"]).next_followup_at = utcnow() - timedelta(days=1)
    db.commit()
    assert jobs.run_due_followups(db) == 0


def test_reminder_then_final_then_overdue(client, db, ngo, published_campaign):
    open_request(client, ngo, published_campaign)
    req = _request(db, published_campaign)
    start = utcnow()
    assert jobs.send_reminders(db, start) == (0, 0)  # too soon
    assert jobs.send_reminders(db, start + timedelta(days=1, hours=1)) == (1, 0)
    assert jobs.send_reminders(db, start + timedelta(days=1, hours=2)) == (0, 0)  # no spam
    assert jobs.send_reminders(db, start + timedelta(days=2, hours=2)) == (1, 0)
    assert jobs.send_reminders(db, start + timedelta(days=4)) == (0, 1)
    db.refresh(req)
    assert req.status == "overdue" and req.reminder_count == 2
    assert jobs.send_reminders(db, start + timedelta(days=9)) == (0, 0)
    assert db.scalar(select(func.count()).select_from(OutboundMessage)) == 2

    tl = client.get(f"/api/campaigns/{published_campaign}/timeline").json()
    assert tl["reporting_overdue"] is True
    messages = " ".join(db.scalars(select(AgentMessage.content)))
    assert "fraud" not in messages.lower() and "misuse" not in messages.lower()


def test_reply_stops_reminders_and_clears_overdue(client, db, no_ai, ngo, published_campaign):
    req_id = open_request(client, ngo, published_campaign)
    req = _request(db, published_campaign)
    req.status, req.reminder_count = "overdue", 2
    db.commit()
    r = client.post(f"/api/reporting-requests/{req_id}/messages", json={"content": "Sorry for the delay, here is our update."}, headers=ngo)
    assert r.json()["request"]["status"] == "in_review"
    assert client.get(f"/api/campaigns/{published_campaign}/timeline").json()["reporting_overdue"] is False
    assert jobs.send_reminders(db, utcnow() + timedelta(days=30)) == (0, 0)


def test_run_jobs_endpoint_is_reviewer_only(client, ngo):
    assert client.post("/api/accountability/run-jobs", headers=ngo).status_code == 403
    reviewer = login(client, "reviewer@ngolog.org", "reviewer")
    assert client.post("/api/accountability/run-jobs", headers=reviewer).json() == {"opened": 0, "reminded": 0, "overdue": 0}

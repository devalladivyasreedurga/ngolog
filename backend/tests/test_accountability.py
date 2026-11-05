"""Accountability console: real data, scoped per NGO, no fraud language, reviewer actions."""

from tests.conftest import login, png
from tests.test_safeguards import open_request
from tests.test_vertical_slice import upload


def _discrepancy(client, ngo, cid):
    req_id = open_request(client, ngo, cid)
    t = client.post(f"/api/reporting-requests/{req_id}/claims", json={"claim_type": "expense", "description": "school kits", "amount": 500}, headers=ngo).json()
    return upload(client, ngo, req_id, png("TOTAL=420"), t["claims"][-1]["id"])


def test_console_row_shows_gap_question_and_checks(client, ai, ngo, published_campaign):
    _discrepancy(client, ngo, published_campaign)
    data = client.get("/api/accountability", headers=ngo).json()
    row = data["claims"][0]
    assert row["reported_cents"] == 50000 and row["supported_cents"] == 42000 and row["gap_cents"] == 8000
    assert row["evidence_status"] == "needs_clarification" and row["investigation_status"] == "open"
    assert "$80.00" in row["open_question"]
    assert {"amount_match", "extraction"} <= {c["check_type"] for c in row["checks"]}
    assert data["requests"][0]["past_due"] is False


def test_console_is_scoped_to_the_ngo(client, ai, ngo, published_campaign):
    _discrepancy(client, ngo, published_campaign)
    other = login(client, "other@ngo.example.com", "ngo_admin")
    client.post("/api/ngos", json={"name": "Other NGO", "accept_reporting_agreement": True}, headers=other)
    assert client.get("/api/accountability", headers=other).json() == {"claims": [], "requests": []}


def test_console_blocks_donors_and_anonymous(client):
    assert client.get("/api/accountability").status_code == 401
    donor = login(client, "donor@example.com", "donor")
    assert client.get("/api/accountability", headers=donor).status_code == 403


def test_reviewer_sees_all_and_resolution_updates_the_row(client, ai, ngo, published_campaign):
    _discrepancy(client, ngo, published_campaign)
    reviewer = login(client, "reviewer@ngolog.org", "reviewer")
    row = client.get("/api/accountability", headers=reviewer).json()["claims"][0]
    r = client.post(f"/api/investigations/{row['investigation_id']}/resolve", json={"resolution": "Spoke to the NGO; invoice is on the way."}, headers=reviewer)
    assert r.status_code == 200
    row = client.get("/api/accountability", headers=reviewer).json()["claims"][0]
    assert row["evidence_status"] == "reviewed_by_human" and row["open_question"] is None

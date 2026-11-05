"""LangGraph runtime: pause/resume, persistence across restarts, auto-draft, close on publish."""

import sqlite3

from langgraph.checkpoint.sqlite import SqliteSaver

from app.agent import runtime
from tests.conftest import png
from tests.test_safeguards import open_request
from tests.test_vertical_slice import upload


def _expense(client, ngo, req_id, amount=500):
    thread = client.post(f"/api/reporting-requests/{req_id}/claims", json={"claim_type": "expense", "description": "25 school kits", "amount": amount}, headers=ngo).json()
    return thread["claims"][-1]["id"]


def test_graph_auto_drafts_when_everything_is_settled(client, ai, ngo, published_campaign):
    req_id = open_request(client, ngo, published_campaign)
    claim_id = _expense(client, ngo, req_id)
    upload(client, ngo, req_id, png("TOTAL=420"), claim_id)
    assert client.get(f"/api/campaigns/{published_campaign}/updates", headers=ngo).json() == []
    thread = upload(client, ngo, req_id, png("TOTAL=80"), claim_id, name="r2.png")
    assert thread["messages"][-1]["meta"]["step"] == "queue_for_review"
    assert thread["request"]["status"] == "awaiting_approval"
    drafts = client.get(f"/api/campaigns/{published_campaign}/updates", headers=ngo).json()
    assert len(drafts) == 1 and drafts[0]["update"]["status"] == "draft"


def test_graph_survives_restart(client, ai, ngo, published_campaign, tmp_path):
    path = tmp_path / "ckpt.sqlite"
    runtime.set_checkpointer(SqliteSaver(sqlite3.connect(path, check_same_thread=False)))
    req_id = open_request(client, ngo, published_campaign)
    claim_id = _expense(client, ngo, req_id)
    # Simulate a process restart: brand-new saver over the same file.
    runtime.set_checkpointer(SqliteSaver(sqlite3.connect(path, check_same_thread=False)))
    thread = upload(client, ngo, req_id, png("TOTAL=500"), claim_id)
    assert thread["claims"][0]["evidence_status"] == "consistent"
    assert thread["messages"][-1]["meta"]["step"] == "queue_for_review"


def test_publish_closes_the_cycle(client, ai, ngo, published_campaign):
    req_id = open_request(client, ngo, published_campaign)
    claim_id = _expense(client, ngo, req_id, amount=10)
    upload(client, ngo, req_id, png("TOTAL=10"), claim_id)
    draft = client.get(f"/api/campaigns/{published_campaign}/updates", headers=ngo).json()[0]["update"]
    client.post(f"/api/updates/{draft['id']}/approve", headers=ngo)
    client.post(f"/api/updates/{draft['id']}/publish", headers=ngo)
    thread = client.get(f"/api/reporting-requests/{req_id}/thread", headers=ngo).json()
    assert thread["request"]["status"] == "completed"
    assert client.post(f"/api/reporting-requests/{req_id}/messages", json={"content": "one more thing"}, headers=ngo).status_code == 409


def test_new_evidence_replaces_stale_draft(client, ai, ngo, published_campaign):
    req_id = open_request(client, ngo, published_campaign)
    claim_id = _expense(client, ngo, req_id, amount=10)
    upload(client, ngo, req_id, png("TOTAL=10"), claim_id)
    # A second confirmed expense arrives and settles: the old draft is withdrawn, a fresh one drafted.
    claim2 = _expense(client, ngo, req_id, amount=5)
    upload(client, ngo, req_id, png("TOTAL=5"), claim2, name="b.png")
    updates = client.get(f"/api/campaigns/{published_campaign}/updates", headers=ngo).json()
    statuses = sorted(u["update"]["status"] for u in updates)
    assert statuses == ["draft", "withdrawn"]

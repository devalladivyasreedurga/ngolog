"""Donor update emails via Zapier MCP: only after publish, once per donor, never fatal."""

import json

import httpx
import pytest

from app.config import Settings
from app.notifications import zapier_email
from tests.conftest import login


class FakeZapier:
    def __init__(self, fail_calls: bool = False):
        self.sent: list[dict] = []
        self.auth_headers: list[str | None] = []
        self.fail_calls = fail_calls

    def handler(self, request: httpx.Request) -> httpx.Response:
        msg = json.loads(request.content)
        self.auth_headers.append(request.headers.get("authorization"))
        method = msg.get("method")
        if method == "notifications/initialized":
            return httpx.Response(202)
        if method == "initialize":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": msg["id"], "result": {"protocolVersion": "2025-03-26", "capabilities": {}}}, headers={"mcp-session-id": "S1"})
        if method == "tools/list":
            tools = [
                {"name": "gmail_find_email", "inputSchema": {"properties": {"query": {}}}},
                {"name": "gmail_send_email", "inputSchema": {"properties": {"instructions": {}, "to": {}, "subject": {}, "body": {}}}},
            ]
            # Zapier-style answer: server-sent events instead of plain JSON.
            body = "event: message\ndata: " + json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": {"tools": tools}}) + "\n\n"
            return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})
        if method == "tools/call":
            if self.fail_calls:
                return httpx.Response(500)
            self.sent.append(msg["params"])
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": msg["id"], "result": {"content": [{"type": "text", "text": "sent"}]}})
        return httpx.Response(404)


@pytest.fixture
def zapier(monkeypatch):
    fake = FakeZapier()
    zapier_email.set_zapier_transport(httpx.MockTransport(fake.handler))
    settings = Settings(zapier_mcp_server_url="https://zapier.test/mcp", zapier_mcp_auth_token="tok", notification_from_email="ngolog@example.com")
    monkeypatch.setattr(zapier_email, "get_settings", lambda: settings)
    yield fake
    zapier_email.set_zapier_transport(None)


def _approved_update(client, ngo, cid) -> str:
    upd = client.post(f"/api/campaigns/{cid}/updates/draft", json={}, headers=ngo).json()
    assert client.post(f"/api/updates/{upd['id']}/approve", headers=ngo).status_code == 200
    return upd["id"]


def _donor(client, cid, email="donor@example.com") -> dict:
    h = login(client, email, "donor")
    assert client.post(f"/api/campaigns/{cid}/notifications/subscribe", json={"email_enabled": True}, headers=h).status_code == 200
    return h


def _email_rows(client, donor):
    return [n for n in client.get("/api/notifications/mine", headers=donor).json() if n["channel"] == "email"]


def test_email_sent_once_on_publish(client, ai, ngo, published_campaign, zapier):
    donor = _donor(client, published_campaign)
    uid = _approved_update(client, ngo, published_campaign)
    assert zapier.sent == []  # approving alone sends nothing

    assert client.post(f"/api/updates/{uid}/publish", headers=ngo).json()["status"] == "published"
    assert len(zapier.sent) == 1
    call = zapier.sent[0]
    assert call["name"] == "gmail_send_email"
    assert call["arguments"]["to"] == "donor@example.com"
    assert call["arguments"]["subject"].startswith("New update on")
    assert f"/campaigns/{published_campaign}" in call["arguments"]["body"]
    assert "instructions" in call["arguments"]
    assert zapier.auth_headers[0] == "Bearer tok"
    assert [n["status"] for n in _email_rows(client, donor)] == ["sent"]

    client.post(f"/api/updates/{uid}/publish", headers=ngo)  # idempotent re-publish
    assert len(zapier.sent) == 1


def test_opted_out_donor_gets_no_email(client, ai, ngo, published_campaign, zapier):
    h = login(client, "quiet@example.com", "donor")
    client.post(f"/api/campaigns/{published_campaign}/notifications/subscribe", json={"email_enabled": False}, headers=h)
    uid = _approved_update(client, ngo, published_campaign)
    client.post(f"/api/updates/{uid}/publish", headers=ngo)
    assert zapier.sent == [] and _email_rows(client, h) == []


def test_provider_failure_does_not_block_publish(client, ai, ngo, published_campaign, zapier):
    zapier.fail_calls = True
    donor = _donor(client, published_campaign)
    uid = _approved_update(client, ngo, published_campaign)
    assert client.post(f"/api/updates/{uid}/publish", headers=ngo).json()["status"] == "published"
    assert [n["status"] for n in _email_rows(client, donor)] == ["failed"]


def test_unconfigured_means_in_app_only(client, ai, ngo, published_campaign):
    donor = _donor(client, published_campaign)
    uid = _approved_update(client, ngo, published_campaign)
    assert client.post(f"/api/updates/{uid}/publish", headers=ngo).json()["status"] == "published"
    assert _email_rows(client, donor) == []


def test_generic_zapier_server_uses_write_action(client, ai, ngo, published_campaign, monkeypatch):
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        msg = json.loads(request.content)
        m = msg.get("method")
        if m == "notifications/initialized":
            return httpx.Response(202)
        if m == "initialize":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": msg["id"], "result": {}})
        if m == "tools/list":
            tools = [{"name": "execute_zapier_read_action"}, {"name": "execute_zapier_write_action"}]
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": msg["id"], "result": {"tools": tools}})
        calls.append(msg["params"])
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": msg["id"], "result": {"content": [{"type": "text", "text": '{"status":"success"}'}]}})

    zapier_email.set_zapier_transport(httpx.MockTransport(handler))
    settings = Settings(zapier_mcp_server_url="https://zapier.test/mcp")
    monkeypatch.setattr(zapier_email, "get_settings", lambda: settings)
    try:
        _donor(client, published_campaign)
        uid = _approved_update(client, ngo, published_campaign)
        client.post(f"/api/updates/{uid}/publish", headers=ngo)
    finally:
        zapier_email.set_zapier_transport(None)
    assert len(calls) == 1 and calls[0]["name"] == "execute_zapier_write_action"
    args = calls[0]["arguments"]
    assert (args["selected_api"], args["action"], args["tool_name"]) == ("GoogleMailV2CLIAPI", "message", "gmail_send_email")
    assert args["params"]["to"] == ["donor@example.com"] and args["params"]["subject"].startswith("New update on")

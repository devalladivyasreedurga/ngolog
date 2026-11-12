"""Donor "new update" emails through Zapier MCP.

Zapier does one thing here: send the email. Whether an email may go out is decided by the publish
endpoint (approved + published updates only) and the notification outbox (one row per donor per update).
The agent never calls this module, and the MCP URL/token are never logged.
"""

import json
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.base import utcnow
from app.db.models import Campaign, DonorUpdate, Notification, NotificationSubscription, User
from contracts.reporting_schemas import DeliveryStatus

PROVIDER = "zapier_mcp"
_MCP_HEADERS = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}

# Tests swap this for an in-process fake (see tests/conftest.py); production leaves it None.
_transport: httpx.BaseTransport | None = None


def set_zapier_transport(transport: httpx.BaseTransport | None) -> None:
    global _transport
    _transport = transport


class ZapierError(Exception):
    pass


def _parse(resp: httpx.Response) -> dict[str, Any] | None:
    """MCP over HTTP answers with plain JSON or a server-sent-events stream; accept both."""
    if resp.status_code == 202 or not resp.content:
        return None
    if "text/event-stream" in resp.headers.get("content-type", ""):
        last = None
        for line in resp.text.splitlines():
            if line.startswith("data:") and line[5:].strip():
                last = json.loads(line[5:].strip())
        return last
    return resp.json()


class ZapierMCP:
    def __init__(self, url: str, token: str, app: str = "GoogleMailV2CLIAPI", action: str = "message", tool_name: str = "gmail_send_email"):
        self._url = url
        self._app, self._action, self._tool_name = app, action, tool_name
        self._headers = dict(_MCP_HEADERS)
        if token:
            self._headers["Authorization"] = f"Bearer {token}"
        self._client = httpx.Client(transport=_transport, timeout=20)
        self._next_id = 0
        self._initialized = False
        self._tools: list[dict[str, Any]] | None = None

    def __enter__(self) -> "ZapierMCP":
        return self

    def __exit__(self, *exc) -> None:
        self._client.close()

    def _rpc(self, method: str, params: dict | None = None, notify: bool = False) -> dict | None:
        msg: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        if not notify:
            self._next_id += 1
            msg["id"] = self._next_id
        try:
            resp = self._client.post(self._url, json=msg, headers=self._headers)
            resp.raise_for_status()
            data = _parse(resp)
        except (httpx.HTTPError, ValueError) as e:
            raise ZapierError(f"Zapier MCP {method} failed: {type(e).__name__}") from None
        if sid := resp.headers.get("mcp-session-id"):
            self._headers["Mcp-Session-Id"] = sid
        if data and "error" in data:
            raise ZapierError(f"Zapier MCP {method} error: {data['error'].get('message', 'unknown')}")
        return data

    def _ensure_ready(self) -> list[dict[str, Any]]:
        if not self._initialized:
            self._rpc("initialize", {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "ngolog", "version": "0.1"}})
            self._rpc("notifications/initialized", notify=True)
            self._initialized = True
        if self._tools is None:
            data = self._rpc("tools/list") or {}
            self._tools = (data.get("result") or {}).get("tools", [])
        return self._tools

    def _call(self, name: str, arguments: dict[str, Any]) -> str:
        data = self._rpc("tools/call", {"name": name, "arguments": arguments}) or {}
        result = data.get("result") or {}
        text = " ".join(c.get("text", "") for c in result.get("content", []) if isinstance(c, dict))
        if result.get("isError") or '"error"' in text[:40]:
            raise ZapierError("Zapier tool reported an error")
        return text[:120] or "ok"

    def send_email(self, to: str, subject: str, body: str, from_email: str = "") -> str:
        tools = self._ensure_ready()
        if any(t.get("name") == "execute_zapier_write_action" for t in tools):
            # Generic Zapier MCP server: one write tool, the app/action are named per call.
            params: dict[str, Any] = {"to": [to], "subject": subject, "body": body, "body_type": "plain"}
            return self._call(
                "execute_zapier_write_action",
                {"selected_api": self._app, "action": self._action, "tool_name": self._tool_name, "params": params},
            )
        tool = _pick_email_tool(tools)
        return self._call(tool["name"], _build_args(tool, to, subject, body, from_email))


def _pick_email_tool(tools: list[dict]) -> dict:
    def score(t: dict) -> int:
        n = t.get("name", "").lower()
        return (2 if "send" in n else 0) + (2 if "email" in n or "mail" in n else 0) - (1 if "draft" in n or "reply" in n else 0)

    best = max(tools, key=score, default=None)
    if best is None or score(best) < 3:
        raise ZapierError("No send-email tool is exposed by this Zapier MCP server")
    return best


def _build_args(tool: dict, to: str, subject: str, body: str, from_email: str) -> dict[str, Any]:
    """Fill the tool's input schema by field name; the exact names differ per email app."""
    props = (tool.get("inputSchema") or {}).get("properties", {})
    args: dict[str, Any] = {}
    for name in props:
        k = name.lower()
        if k in ("to", "recipient", "recipients", "to_email", "to_address"):
            args[name] = to
        elif k == "subject":
            args[name] = subject
        elif k in ("body", "message", "text", "content", "body_plain", "body_html"):
            args[name] = body
        elif k in ("from", "from_email", "sender") and from_email:
            args[name] = from_email
        elif k == "instructions":
            args[name] = "Send this email exactly as written, to the single recipient given."
        elif k == "output_hint":
            args[name] = "send confirmation"
    return args


def _email_text(update: DonorUpdate, campaign: Campaign, public_app_url: str) -> tuple[str, str]:
    subject = f"New update on {campaign.title}"
    link = f"{public_app_url.rstrip('/')}/campaigns/{campaign.id}"
    body = (
        f"{update.title}\n\n{update.body}\n\n"
        f"Read the full update and how it was checked: {link}\n\n"
        "This is the organization's own report, checked against the documents it shared. "
        "It is campaign-level and is not an audit of how any individual donation was used."
    )
    return subject, body


def deliver_update_emails(db: Session, update: DonorUpdate, campaign: Campaign) -> None:
    """Email subscribed donors about a PUBLISHED update. Never raises: a failed email must not undo a publish."""
    settings = get_settings()
    if not settings.zapier_configured:
        return
    pending: list[tuple[Notification, str]] = []
    for sub in db.scalars(
        select(NotificationSubscription).where(NotificationSubscription.campaign_id == campaign.id, NotificationSubscription.email_enabled.is_(True))
    ):
        key = f"update:{update.id}:donor:{sub.donor_user_id}:email"
        if db.scalar(select(Notification).where(Notification.idempotency_key == key)) is not None:
            continue  # already queued, sent or failed once: no duplicate emails on re-publish
        donor = db.get(User, sub.donor_user_id)
        if donor is None:
            continue
        n = Notification(donor_user_id=donor.id, donor_update_id=update.id, channel="email", status=DeliveryStatus.QUEUED, provider=PROVIDER, idempotency_key=key)
        db.add(n)
        pending.append((n, donor.email))
    if not pending:
        return
    db.flush()
    subject, body = _email_text(update, campaign, settings.public_app_url)
    with ZapierMCP(settings.zapier_mcp_server_url, settings.zapier_mcp_auth_token, settings.zapier_email_app, settings.zapier_email_action, settings.zapier_email_tool_name) as mcp:
        for n, address in pending:
            try:
                n.provider_message_id = mcp.send_email(address, subject, body, settings.notification_from_email)
                n.status = DeliveryStatus.SENT
                n.sent_at = utcnow()
            except ZapierError:
                n.status = DeliveryStatus.FAILED

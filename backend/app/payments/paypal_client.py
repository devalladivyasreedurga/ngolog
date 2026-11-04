"""Minimal PayPal REST client: OAuth token, Orders v2 create/capture, webhook verification.

Direct FastAPI integration by design: PayPal writes are never exposed to the agent or MCP.
"""

from __future__ import annotations

import time

import httpx

from app.config import get_settings


class PayPalError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None, body: dict | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body or {}


class PayPalClient:
    def __init__(self, client_id: str, client_secret: str, base_url: str, transport: httpx.BaseTransport | None = None):
        self._id = client_id
        self._secret = client_secret
        self._http = httpx.Client(base_url=base_url, timeout=30, transport=transport)
        self._token: str | None = None
        self._token_expires = 0.0

    def _access_token(self) -> str:
        if self._token and time.time() < self._token_expires - 60:
            return self._token
        r = self._http.post(
            "/v1/oauth2/token",
            data={"grant_type": "client_credentials"},
            auth=(self._id, self._secret),
        )
        if r.status_code != 200:
            raise PayPalError("PayPal authentication failed", r.status_code, _json(r))
        body = r.json()
        self._token = body["access_token"]
        self._token_expires = time.time() + int(body.get("expires_in", 300))
        return self._token

    def _request(self, method: str, path: str, *, json: dict | None = None, request_id: str | None = None) -> dict:
        headers = {"Authorization": f"Bearer {self._access_token()}", "Content-Type": "application/json"}
        if request_id:
            headers["PayPal-Request-Id"] = request_id  # PayPal-side idempotency
        r = self._http.request(method, path, json=json, headers=headers)
        if r.status_code >= 400:
            raise PayPalError(f"PayPal {method} {path} failed", r.status_code, _json(r))
        return r.json() if r.content else {}

    def create_order(self, *, donation_id: str, campaign_id: str, amount_cents: int, currency: str, description: str) -> dict:
        return self._request(
            "POST",
            "/v2/checkout/orders",
            request_id=f"order-{donation_id}",
            json={
                "intent": "CAPTURE",
                "purchase_units": [
                    {
                        "reference_id": donation_id,
                        "custom_id": campaign_id,
                        "description": description[:127],
                        "amount": {"currency_code": currency, "value": f"{amount_cents / 100:.2f}"},
                    }
                ],
            },
        )

    def capture_order(self, *, order_id: str, donation_id: str) -> dict:
        return self._request(
            "POST", f"/v2/checkout/orders/{order_id}/capture", request_id=f"capture-{donation_id}", json={}
        )

    def get_order(self, order_id: str) -> dict:
        return self._request("GET", f"/v2/checkout/orders/{order_id}")

    def verify_webhook(self, *, headers: dict[str, str], event: dict, webhook_id: str) -> bool:
        h = {k.lower(): v for k, v in headers.items()}
        required = ["paypal-auth-algo", "paypal-cert-url", "paypal-transmission-id", "paypal-transmission-sig", "paypal-transmission-time"]
        if not webhook_id or any(k not in h for k in required):
            return False
        body = self._request(
            "POST",
            "/v1/notifications/verify-webhook-signature",
            json={
                "auth_algo": h["paypal-auth-algo"],
                "cert_url": h["paypal-cert-url"],
                "transmission_id": h["paypal-transmission-id"],
                "transmission_sig": h["paypal-transmission-sig"],
                "transmission_time": h["paypal-transmission-time"],
                "webhook_id": webhook_id,
                "webhook_event": event,
            },
        )
        return body.get("verification_status") == "SUCCESS"


def _json(r: httpx.Response) -> dict:
    try:
        return r.json()
    except ValueError:
        return {"raw": r.text[:500]}


_client: PayPalClient | None = None
_transport_override: httpx.BaseTransport | None = None


def set_paypal_transport(transport: httpx.BaseTransport | None) -> None:
    """Test hook: route PayPal HTTP calls to an in-process fake. Never used by the app."""
    global _client, _transport_override
    _transport_override, _client = transport, None


def get_paypal() -> PayPalClient:
    global _client
    s = get_settings()
    if not s.paypal_configured and _transport_override is None:
        raise PayPalError("PayPal sandbox credentials are not configured (PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET)", 503)
    if _client is None:
        _client = PayPalClient(s.paypal_client_id or "test", s.paypal_client_secret or "test", s.paypal_base_url, _transport_override)
    return _client

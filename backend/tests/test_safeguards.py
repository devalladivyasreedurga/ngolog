"""Idempotency, authorization and labelling rules from spec section 10."""

from tests.conftest import capture_webhook, login, png, webhook_headers
from tests.test_vertical_slice import donate, upload


def open_request(client, ngo, cid, key="demo-1"):
    return client.post(f"/api/campaigns/{cid}/reporting-requests/trigger", json={"cycle_key": key}, headers=ngo).json()["request"]["id"]


# ---------------------------------------------------------------- PayPal


def test_capture_and_webhook_are_idempotent(client, paypal, published_campaign):
    donor = login(client, "donor@example.com", "donor")
    order_id, _ = donate(client, published_campaign, donor)
    again = client.post(f"/api/paypal/orders/{order_id}/capture", headers=donor)
    assert again.status_code == 200 and paypal.capture_calls == 1
    event = capture_webhook("WH-EVT-9", order_id)
    assert client.post("/api/paypal/webhook", json=event, headers=webhook_headers()).json()["status"] == "processed"
    assert client.post("/api/paypal/webhook", json=event, headers=webhook_headers()).json()["status"] == "duplicate"
    c = client.get(f"/api/campaigns/{published_campaign}").json()
    assert c["donations_received_cents"] == 2500  # counted once


def test_unverified_webhook_rejected(client, paypal, published_campaign):
    donor = login(client, "donor@example.com", "donor")
    order_id, _ = donate(client, published_campaign, donor)
    r = client.post("/api/paypal/webhook", json=capture_webhook("WH-EVT-X", order_id), headers=webhook_headers("forged"))
    assert r.status_code == 400


def test_no_donation_without_server_capture(client, paypal, published_campaign):
    donor = login(client, "donor@example.com", "donor")
    client.post(f"/api/campaigns/{published_campaign}/paypal/orders", json={"amount": 40}, headers=donor)
    assert client.get(f"/api/campaigns/{published_campaign}").json()["donations_received_cents"] == 0
    assert client.get("/api/donations/mine", headers=donor).json() == []


def test_paypal_not_configured_fails_loudly(client, published_campaign):
    donor = login(client, "donor@example.com", "donor")
    r = client.post(f"/api/campaigns/{published_campaign}/paypal/orders", json={"amount": 10}, headers=donor)
    assert r.status_code == 503


def test_paypal_request_ids_sent(client, paypal, published_campaign):
    donor = login(client, "donor@example.com", "donor")
    donate(client, published_campaign, donor)
    assert any(r.startswith("order-") for r in paypal.request_ids)
    assert any(r.startswith("capture-") for r in paypal.request_ids)


# ---------------------------------------------------------------- authorization


def test_other_ngo_cannot_touch_campaign(client, ai, published_campaign):
    other = login(client, "other@ngo.example.com", "ngo_admin")
    client.post("/api/ngos", json={"name": "Other NGO", "accept_reporting_agreement": True}, headers=other)
    assert client.post(f"/api/campaigns/{published_campaign}/reporting-requests/trigger", json={}, headers=other).status_code == 404
    assert client.patch(f"/api/campaigns/{published_campaign}", json={"title": "Hijacked"}, headers=other).status_code == 404
    assert client.get(f"/api/campaigns/{published_campaign}/claims", headers=other).status_code == 404


def test_donor_cannot_publish_or_view_private_evidence(client, ai, ngo, published_campaign):
    req_id = open_request(client, ngo, published_campaign)
    thread = upload(client, ngo, req_id, png("TOTAL=10"))
    ev_id = thread["evidence"][0]["id"]
    donor = login(client, "donor@example.com", "donor")
    assert client.get(f"/api/evidence/{ev_id}/file").status_code == 404
    assert client.get(f"/api/evidence/{ev_id}/file", headers=donor).status_code == 404
    upd = client.post(f"/api/campaigns/{published_campaign}/updates/draft", json={}, headers=ngo).json()
    assert client.post(f"/api/updates/{upd['id']}/approve", headers=donor).status_code == 403


def test_update_cannot_cite_private_evidence(client, ai, ngo, published_campaign):
    req_id = open_request(client, ngo, published_campaign)
    thread = client.post(f"/api/reporting-requests/{req_id}/claims", json={"claim_type": "expense", "description": "school kits", "amount": 10}, headers=ngo).json()
    claim_id = thread["claims"][0]["id"]
    thread = upload(client, ngo, req_id, png("TOTAL=10"), claim_id)
    ev_id = thread["evidence"][0]["id"]
    client.post(f"/api/evidence/{ev_id}/visibility", json={"visibility": "public"}, headers=ngo)
    upd = client.post(f"/api/campaigns/{published_campaign}/updates/draft", json={"reporting_request_id": req_id}, headers=ngo).json()
    assert upd["evidence_refs"] == [ev_id]
    client.post(f"/api/evidence/{ev_id}/visibility", json={"visibility": "private"}, headers=ngo)
    assert client.post(f"/api/updates/{upd['id']}/approve", headers=ngo).status_code == 409


def test_reviewer_role_is_allowlisted(client):
    r = client.post("/api/auth/demo-login", json={"email": "someone@example.org", "role": "reviewer"})
    assert r.status_code == 403


# ---------------------------------------------------------------- agent rules


def test_followup_trigger_is_idempotent(client, ngo, published_campaign):
    a = open_request(client, ngo, published_campaign, "cycle-7")
    b = open_request(client, ngo, published_campaign, "cycle-7")
    assert a == b
    assert len(client.get(f"/api/campaigns/{published_campaign}/reporting-requests", headers=ngo).json()) == 1


def test_partial_receipt_is_not_fully_supported(client, ai, ngo, published_campaign):
    req_id = open_request(client, ngo, published_campaign)
    thread = client.post(f"/api/reporting-requests/{req_id}/claims", json={"claim_type": "expense", "description": "school kits", "amount": 500}, headers=ngo).json()
    claim_id = thread["claims"][0]["id"]
    thread = upload(client, ngo, req_id, png("TOTAL=420"), claim_id)
    claim = thread["claims"][0]
    assert claim["evidence_status"] == "needs_clarification"
    assert claim["supported_amount_cents"] == 42000
    upd = client.post(f"/api/campaigns/{published_campaign}/updates/draft", json={"reporting_request_id": req_id}, headers=ngo).json()
    assert "awaiting clarification" in upd["body"] and "support $420.00" in upd["body"]


def test_duplicate_receipt_counted_once(client, ai, ngo, published_campaign):
    req_id = open_request(client, ngo, published_campaign)
    thread = client.post(f"/api/reporting-requests/{req_id}/claims", json={"claim_type": "expense", "description": "kits", "amount": 840}, headers=ngo).json()
    claim_id = thread["claims"][0]["id"]
    upload(client, ngo, req_id, png("TOTAL=420"), claim_id)
    thread = upload(client, ngo, req_id, png("TOTAL=420"), claim_id, name="again.png")
    assert thread["claims"][0]["supported_amount_cents"] == 42000
    last = thread["messages"][-1]
    assert last["meta"]["step"] == "clarify" and "already submitted" in last["content"]  # one combined question
    trail = client.get("/api/accountability", headers=ngo).json()["claims"][0]["checks"]
    assert any(c["check_type"] == "exact_duplicate" and c["status"] == "flag" for c in trail)


def test_no_evidence_is_labelled_not_fraud(client, ai, ngo, published_campaign):
    req_id = open_request(client, ngo, published_campaign)
    thread = client.post(f"/api/reporting-requests/{req_id}/claims", json={"claim_type": "expense", "description": "local transport", "amount": 30}, headers=ngo).json()
    claim_id = thread["claims"][0]["id"]
    thread = client.post(f"/api/claims/expense/{claim_id}/no-evidence", json={"explanation": "Paid a driver in cash"}, headers=ngo).json()
    assert thread["claims"][0]["evidence_status"] == "not_documented"
    upd = client.post(f"/api/campaigns/{published_campaign}/updates/draft", json={"reporting_request_id": req_id}, headers=ngo).json()
    assert "not been independently documented" in upd["body"]
    assert "fraud" not in upd["body"].lower()


def test_clarifications_capped_then_escalated(client, ai, ngo, published_campaign):
    req_id = open_request(client, ngo, published_campaign)
    thread = client.post(f"/api/reporting-requests/{req_id}/claims", json={"claim_type": "expense", "description": "kits", "amount": 500}, headers=ngo).json()
    claim_id = thread["claims"][0]["id"]
    for i in range(4):
        thread = upload(client, ngo, req_id, png(f"TOTAL=1{i}"), claim_id, name=f"r{i}.png")
    assert thread["request"]["status"] == "escalated"
    assert thread["request"]["clarification_rounds"] == 3
    assert thread["investigations"][0]["status"] == "escalated"


def test_reviewer_resolves_with_audit_reason(client, ai, ngo, published_campaign):
    req_id = open_request(client, ngo, published_campaign)
    thread = client.post(f"/api/reporting-requests/{req_id}/claims", json={"claim_type": "expense", "description": "kits", "amount": 500}, headers=ngo).json()
    thread = upload(client, ngo, req_id, png("TOTAL=420"), thread["claims"][0]["id"])
    inv_id = thread["investigations"][0]["id"]
    assert client.post(f"/api/investigations/{inv_id}/resolve", json={"resolution": "looks fine"}, headers=ngo).status_code == 403
    reviewer = login(client, "reviewer@ngolog.org", "reviewer")
    r = client.post(f"/api/investigations/{inv_id}/resolve", json={"resolution": "Second invoice seen by phone; amount is plausible."}, headers=reviewer)
    assert r.json()["status"] == "resolved_by_reviewer"


# ---------------------------------------------------------------- degraded modes


def test_manual_mode_without_ai(client, no_ai, ngo, published_campaign):
    req_id = open_request(client, ngo, published_campaign)
    thread = client.post(f"/api/reporting-requests/{req_id}/messages", json={"content": "We bought 25 kits for $500."}, headers=ngo).json()
    assert thread["claims"] == [] and thread["messages"][-1]["meta"].get("mode") == "manual"
    thread = client.post(f"/api/reporting-requests/{req_id}/claims", json={"claim_type": "expense", "description": "25 school kits", "amount": 500}, headers=ngo).json()
    claim_id = thread["claims"][0]["id"]
    thread = upload(client, ngo, req_id, png("anything"), claim_id)
    assert "type the total" in thread["messages"][-2]["content"] or "type the total" in thread["messages"][-1]["content"]
    ev_id = thread["evidence"][0]["id"]
    assert thread["claims"][0]["evidence_status"] == "submitted"
    assert thread["request"]["clarification_rounds"] == 0  # waiting for a typed total is not a discrepancy
    thread = client.post(f"/api/evidence/{ev_id}/confirm-values", json={"total": 500}, headers=ngo).json()
    assert thread["claims"][0]["evidence_status"] == "consistent"
    assert thread["request"]["clarification_rounds"] == 0


def test_upload_rejects_non_documents(client, ngo, published_campaign):
    req_id = open_request(client, ngo, published_campaign)
    r = client.post(
        "/api/evidence/upload",
        data={"reporting_request_id": req_id, "kind": "receipt"},
        files={"file": ("evil.png", b"<script>alert(1)</script>", "image/png")},
        headers=ngo,
    )
    assert r.status_code == 415

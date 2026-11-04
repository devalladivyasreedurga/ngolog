"""The P0 story end to end (spec section 8): campaign -> PayPal donation -> agent
follow-up -> $500 claim vs $420 receipt -> clarification -> $80 receipt ->
approval -> donor timeline."""

from tests.conftest import capture_webhook, login, png, webhook_headers


def donate(client, cid, donor_h, amount=25):
    r = client.post(f"/api/campaigns/{cid}/paypal/orders", json={"amount": amount}, headers=donor_h)
    assert r.status_code == 200, r.text
    order_id = r.json()["paypal_order_id"]
    r = client.post(f"/api/paypal/orders/{order_id}/capture", headers=donor_h)
    assert r.status_code == 200, r.text
    return order_id, r.json()


def upload(client, h, req_id, data, claim_id=None, kind="receipt", name="receipt.png"):
    form = {"reporting_request_id": req_id, "kind": kind}
    if claim_id:
        form |= {"claim_type": "expense", "claim_id": claim_id}
    r = client.post("/api/evidence/upload", data=form, files={"file": (name, data, "image/png")}, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def test_full_story(client, paypal, ai, ngo, published_campaign):
    cid = published_campaign
    donor = login(client, "donor@example.com", "donor")

    # Donor funds the campaign through PayPal (sandbox fake in tests).
    order_id, donation = donate(client, cid, donor)
    assert donation["status"] == "captured"
    r = client.post("/api/paypal/webhook", json=capture_webhook("WH-EVT-1", order_id), headers=webhook_headers())
    assert r.json() == {"status": "processed"}
    mine = client.get("/api/donations/mine", headers=donor).json()
    assert mine[0]["status"] == "completed" and mine[0]["webhook_confirmed"]
    assert client.get(f"/api/campaigns/{cid}").json()["donations_received_cents"] == 2500

    # Agent asks for a spending update.
    thread = client.post(f"/api/campaigns/{cid}/reporting-requests/trigger", json={"cycle_key": "demo-1"}, headers=ngo).json()
    req_id = thread["request"]["id"]
    assert thread["messages"][0]["sender_role"] == "agent"

    # NGO reports in plain words; agent proposes structured claims.
    thread = client.post(f"/api/reporting-requests/{req_id}/messages", json={"content": "We bought 25 school kits for $500 and distributed 20."}, headers=ngo).json()
    expense = next(c for c in thread["claims"] if c["claim_type"] == "expense")
    impact = next(c for c in thread["claims"] if c["claim_type"] == "impact")
    assert expense["status"] == "proposed" and expense["amount_cents"] == 50000

    # NGO confirms; agent asks for evidence.
    client.post(f"/api/claims/expense/{expense['id']}/confirm", json={}, headers=ngo)
    thread = client.post(f"/api/claims/impact/{impact['id']}/confirm", json={}, headers=ngo).json()
    assert any(m["meta"].get("step") == "request_more_information" for m in thread["messages"])

    # $420 receipt: agent catches the $80 gap and asks a focused question.
    thread = upload(client, ngo, req_id, png("TOTAL=420 NO=R1"), expense["id"])
    exp = next(c for c in thread["claims"] if c["id"] == expense["id"])
    assert exp["evidence_status"] == "needs_clarification"
    assert exp["supported_amount_cents"] == 42000
    assert "$80.00" in thread["messages"][-1]["content"]
    assert thread["investigations"][0]["status"] == "open"

    # NGO explains, then uploads the second receipt; totals reconcile.
    client.post(f"/api/reporting-requests/{req_id}/messages", json={"content": "The $80 was a second invoice for kit bags."}, headers=ngo)
    thread = upload(client, ngo, req_id, png("TOTAL=80 NO=R2"), expense["id"], name="receipt2.png")
    exp = next(c for c in thread["claims"] if c["id"] == expense["id"])
    assert exp["evidence_status"] == "consistent" and exp["supported_amount_cents"] == 50000
    assert thread["investigations"][0]["status"] == "reconciled"

    # Draft is grounded in records; delivery claim stays an NGO statement.
    upd = client.post(f"/api/campaigns/{cid}/updates/draft", json={"reporting_request_id": req_id}, headers=ngo).json()
    assert upd["status"] == "draft"
    assert "$500.00" in upd["body"] and "consistent" in upd["body"]
    assert "not independently confirmed" in upd["body"]

    # Donor timeline shows nothing until the NGO approves and publishes.
    assert client.get(f"/api/campaigns/{cid}/timeline").json()["entries"] == []
    assert client.post(f"/api/updates/{upd['id']}/publish", headers=ngo).status_code == 409
    assert client.post(f"/api/updates/{upd['id']}/approve", headers=ngo).status_code == 200
    assert client.post(f"/api/updates/{upd['id']}/publish", headers=ngo).json()["status"] == "published"

    tl = client.get(f"/api/campaigns/{cid}/timeline").json()
    assert len(tl["entries"]) == 1
    assert tl["campaign"]["reported_expenses_cents"] == 50000
    assert tl["campaign"]["document_supported_cents"] == 50000
    assert "evidence_ids" not in tl["entries"][0]["provenance"][0]
    notes = client.get("/api/notifications/mine", headers=donor).json()
    assert len(notes) == 1 and notes[0]["donor_update_id"] == upd["id"]

    # Publishing again is a no-op: no duplicate notification.
    client.post(f"/api/updates/{upd['id']}/publish", headers=ngo)
    assert len(client.get("/api/notifications/mine", headers=donor).json()) == 1

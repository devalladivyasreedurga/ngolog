"""One question at a time: short turns, no guessed $0 claims, quick-reply buttons."""

from app.agent.workflow import parse_amount
from tests.conftest import png
from tests.test_safeguards import open_request
from tests.test_vertical_slice import upload


def say(client, ngo, req_id, text):
    r = client.post(f"/api/reporting-requests/{req_id}/messages", json={"content": text}, headers=ngo)
    assert r.status_code == 200, r.text
    return r.json()


def agent_msgs(thread):
    return [m for m in thread["messages"] if m["sender_role"] == "agent"]


def action_kinds(msg):
    return [a["kind"] for a in msg["meta"].get("actions", [])]


def test_opening_is_one_short_question(client, ngo, published_campaign):
    req_id = open_request(client, ngo, published_campaign)
    thread = client.get(f"/api/reporting-requests/{req_id}/thread", headers=ngo).json()
    first = agent_msgs(thread)[0]
    assert first["content"].count("?") == 1 and "\n-" not in first["content"]
    assert first["meta"]["awaiting"] == "ask_spend"


def test_missing_amount_asks_only_for_the_amount_and_never_saves_zero(client, ai, ngo, published_campaign):
    req_id = open_request(client, ngo, published_campaign)
    thread = say(client, ngo, req_id, "we bought 25 school kits")
    assert thread["claims"] == []  # no $0 claim
    assert len(agent_msgs(thread)) == 2  # opening + exactly one reply
    last = agent_msgs(thread)[-1]
    assert "How much" in last["content"] and last["meta"]["awaiting"] == "ask_amount"

    thread = say(client, ngo, req_id, "no idea")  # not a number: ask once more, still no claim
    assert thread["claims"] == [] and "number" in agent_msgs(thread)[-1]["content"]

    thread = say(client, ngo, req_id, "It was $500")
    [claim] = thread["claims"]
    assert claim["amount_cents"] == 50000 and claim["status"] == "proposed"
    last = agent_msgs(thread)[-1]
    assert last["content"] == "Got it: 25 school kits for $500.00. Is that right?"
    assert action_kinds(last) == ["confirm_all", "reject_all"]


def test_confirm_button_confirms_everything_and_asks_for_the_receipt_once(client, ai, ngo, published_campaign):
    req_id = open_request(client, ngo, published_campaign)
    thread = say(client, ngo, req_id, "We bought 25 school kits for $500 and distributed 20.")
    assert len(thread["claims"]) == 2 and agent_msgs(thread)[-1]["content"].startswith("Got it:")
    before = len(agent_msgs(thread))
    thread = client.post(f"/api/reporting-requests/{req_id}/claims/confirm", headers=ngo).json()
    assert all(c["status"] == "reported" for c in thread["claims"])
    new = agent_msgs(thread)[before:]
    assert len(new) == 1  # one bubble, not a pile
    assert action_kinds(new[0]) == ["upload", "no_evidence"] and "$500.00" in new[0]["content"]


def test_typing_yes_also_confirms(client, ai, ngo, published_campaign):
    req_id = open_request(client, ngo, published_campaign)
    say(client, ngo, req_id, "We bought 25 school kits for $500.")
    thread = say(client, ngo, req_id, "yes")
    assert thread["claims"][0]["status"] == "reported"
    assert agent_msgs(thread)[-1]["meta"]["awaiting"] == "ask_receipt"


def test_not_quite_drops_the_proposal_and_asks_again(client, ai, ngo, published_campaign):
    req_id = open_request(client, ngo, published_campaign)
    say(client, ngo, req_id, "We bought 25 school kits for $500.")
    thread = client.post(f"/api/reporting-requests/{req_id}/claims/reject", headers=ngo).json()
    assert [c["status"] for c in thread["claims"]] == ["withdrawn"]
    assert agent_msgs(thread)[-1]["meta"]["awaiting"] == "ask_spend"


def test_a_correction_replaces_the_proposal(client, ai, ngo, published_campaign):
    req_id = open_request(client, ngo, published_campaign)
    say(client, ngo, req_id, "We bought 25 school kits for $500.")
    thread = say(client, ngo, req_id, "Actually we bought 30 school kits for $600.")
    live = [c for c in thread["claims"] if c["status"] != "withdrawn"]
    assert [c["amount_cents"] for c in live] == [60000]


def test_gap_question_is_short_and_offers_one_tap_fix(client, ai, ngo, published_campaign):
    req_id = open_request(client, ngo, published_campaign)
    say(client, ngo, req_id, "We bought 25 school kits for $500.")
    thread = client.post(f"/api/reporting-requests/{req_id}/claims/confirm", headers=ngo).json()
    claim = thread["claims"][0]
    thread = upload(client, ngo, req_id, png("TOTAL=420"), claim["id"])
    q = agent_msgs(thread)[-1]
    assert "$80.00" in q["content"] and q["content"].count("?") == 1 and len(q["content"]) < 170
    assert action_kinds(q) == ["upload", "set_amount"]
    fix = q["meta"]["actions"][1]
    assert fix["amount"] == 420.0 and "$420.00" in fix["label"]

    # Tapping "It was an estimate" goes through the normal confirm path and is audited.
    thread = client.post(f"/api/claims/expense/{claim['id']}/confirm", json={"amount": fix["amount"]}, headers=ngo).json()
    assert thread["claims"][0]["amount_cents"] == 42000 and thread["claims"][0]["evidence_status"] == "consistent"
    assert thread["investigations"][0]["status"] == "reconciled"


def test_no_receipt_button_moves_on_without_calling_it_fraud(client, ai, ngo, published_campaign):
    req_id = open_request(client, ngo, published_campaign)
    say(client, ngo, req_id, "We bought 25 school kits for $500.")
    thread = client.post(f"/api/reporting-requests/{req_id}/claims/confirm", headers=ngo).json()
    claim = thread["claims"][0]
    thread = client.post(f"/api/claims/expense/{claim['id']}/no-evidence", json={"explanation": "I don't have one."}, headers=ngo).json()
    assert thread["claims"][0]["evidence_status"] == "not_documented"
    last = agent_msgs(thread)[-1]
    assert "not documented" in last["content"] and "fraud" not in last["content"].lower()
    assert last["meta"]["awaiting"] == "ask_delivery"


def test_delivery_question_is_asked_once_and_an_answer_becomes_a_claim(client, ai, ngo, published_campaign):
    req_id = open_request(client, ngo, published_campaign)
    say(client, ngo, req_id, "We bought 25 school kits for $500.")
    thread = client.post(f"/api/reporting-requests/{req_id}/claims/confirm", headers=ngo).json()
    upload(client, ngo, req_id, png("TOTAL=500"), thread["claims"][0]["id"])
    thread = say(client, ngo, req_id, "We handed out 20 so far.")
    impact = [c for c in thread["claims"] if c["claim_type"] == "impact"]
    assert impact and impact[0]["status"] == "proposed" and impact[0]["quantity"] == 20
    assert agent_msgs(thread)[-1]["meta"]["awaiting"] == "confirm_claims"
    thread = client.post(f"/api/reporting-requests/{req_id}/claims/confirm", headers=ngo).json()
    assert thread["request"]["status"] == "awaiting_approval"  # drafted; delivery is never asked twice
    assert sum(1 for m in agent_msgs(thread) if m["meta"].get("asked_delivery")) == 1


def test_closed_cycle_rejects_chat_buttons(client, ai, ngo, published_campaign):
    req_id = open_request(client, ngo, published_campaign)
    say(client, ngo, req_id, "We bought 25 school kits for $500.")
    client.post(f"/api/reporting-requests/{req_id}/claims/confirm", headers=ngo)
    claim = client.get(f"/api/campaigns/{published_campaign}/claims", headers=ngo).json()[0]
    upload(client, ngo, req_id, png("TOTAL=500"), claim["id"])
    say(client, ngo, req_id, "Skip")
    draft = client.get(f"/api/campaigns/{published_campaign}/updates", headers=ngo).json()[0]["update"]
    client.post(f"/api/updates/{draft['id']}/approve", headers=ngo)
    client.post(f"/api/updates/{draft['id']}/publish", headers=ngo)
    assert client.post(f"/api/reporting-requests/{req_id}/claims/confirm", headers=ngo).status_code == 409
    assert client.post(f"/api/reporting-requests/{req_id}/claims/reject", headers=ngo).status_code == 409


def test_parse_amount():
    assert parse_amount("$500") == 500 and parse_amount("about 1,250.50 dollars") == 1250.5
    assert parse_amount("25 kits cost $500") == 500  # prefers the dollar amount
    assert parse_amount("no idea") is None and parse_amount("$0") is None


def test_a_flagged_duplicate_does_not_block_reconciling_with_the_real_receipts(client, ai, ngo, published_campaign):
    req_id = open_request(client, ngo, published_campaign)
    say(client, ngo, req_id, "We bought 25 school kits for $500.")
    claim = client.post(f"/api/reporting-requests/{req_id}/claims/confirm", headers=ngo).json()["claims"][0]
    upload(client, ngo, req_id, png("TOTAL=420 NO=A1"), claim["id"])
    thread = upload(client, ngo, req_id, png("TOTAL=420 NO=A1"), claim["id"], name="copy.png")  # same receipt again
    q = agent_msgs(thread)[-1]
    assert "didn't count it again" in q["content"] and "$420.00 of $500.00" in q["content"]
    thread = upload(client, ngo, req_id, png("TOTAL=80 NO=B2"), claim["id"], name="second.png")
    assert thread["claims"][0]["evidence_status"] == "consistent" and thread["claims"][0]["supported_amount_cents"] == 50000
    assert agent_msgs(thread)[-1]["content"].startswith("That matches")


def test_update_items_carry_amounts_for_the_donor_timeline(client, ai, ngo, published_campaign):
    req_id = open_request(client, ngo, published_campaign)
    say(client, ngo, req_id, "We bought 25 school kits for $500 and distributed 20.")
    thread = client.post(f"/api/reporting-requests/{req_id}/claims/confirm", headers=ngo).json()
    expense = next(c for c in thread["claims"] if c["claim_type"] == "expense")
    upload(client, ngo, req_id, png("TOTAL=500 NO=Z1"), expense["id"])
    drafts = client.get(f"/api/campaigns/{published_campaign}/updates", headers=ngo).json()
    draft = drafts[0]["update"]
    client.post(f"/api/updates/{draft['id']}/approve", headers=ngo)
    client.post(f"/api/updates/{draft['id']}/publish", headers=ngo)
    entry = client.get(f"/api/campaigns/{published_campaign}/timeline").json()["entries"][0]
    items = {p["claim_type"]: p for p in entry["provenance"]}
    assert items["expense"]["amount_cents"] == 50000 and items["expense"]["supported_cents"] == 50000
    assert items["expense"]["evidence_status"] == "consistent" and items["impact"]["quantity"] == 20
    assert all("evidence_ids" not in p for p in entry["provenance"])  # private ids still never reach donors


def test_activity_phrase_does_not_repeat_the_unit():
    from app.agent.workflow import _phrase
    from app.db.models import ImpactClaim

    def impact(description, quantity, unit):
        return ImpactClaim(description=description, quantity=quantity, unit=unit)

    assert _phrase(impact("blankets handed out", 15.0, "blankets")) == "15 blankets handed out"
    assert _phrase(impact("Delivered to homeless people", 2.0, "people")) == "Delivered to homeless people (2 people)"
    assert _phrase(impact("meals served", None, None)) == "meals served"
    assert _phrase(impact("meals served", 40.0, None)) == "meals served (40)"


def test_an_upload_shows_up_in_the_chat_as_the_ngos_message(client, ai, ngo, published_campaign):
    req_id = open_request(client, ngo, published_campaign)
    say(client, ngo, req_id, "We bought 25 school kits for $500.")
    claim = client.post(f"/api/reporting-requests/{req_id}/claims/confirm", headers=ngo).json()["claims"][0]
    thread = upload(client, ngo, req_id, png("TOTAL=420 NO=C3"), claim["id"], name="receipt.png")
    sent = [m for m in thread["messages"] if m["sender_role"] == "ngo" and m["meta"].get("evidence_id")]
    assert len(sent) == 1 and sent[0]["meta"]["filename"] == "receipt.png" and sent[0]["meta"]["file_type"] == "image/png"
    assert thread["messages"][-1]["sender_role"] == "agent"  # the assistant still answers last, so its buttons show


def test_nothing_spent_yet_moves_to_the_delivery_question(client, ai, ngo, published_campaign):
    req_id = open_request(client, ngo, published_campaign)
    first = agent_msgs(client.get(f"/api/reporting-requests/{req_id}/thread", headers=ngo).json())[0]
    assert action_kinds(first) == ["nothing_spent"] and "For example" in first["content"]
    thread = say(client, ngo, req_id, "Nothing spent yet")
    assert thread["claims"] == []
    last = agent_msgs(thread)[-1]
    assert "handed out" in last["content"] and last["meta"]["awaiting"] == "ask_delivery"


def test_public_timeline_carries_the_plan_limitations(client, published_campaign):
    tl = client.get(f"/api/campaigns/{published_campaign}/timeline").json()
    assert tl["limitations"] and all(isinstance(x, str) for x in tl["limitations"])

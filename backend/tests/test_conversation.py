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
    assert action_kinds(q) == ["upload", "set_amount", "no_evidence"]
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
    assert "no receipt for" in last["content"] and "fraud" not in last["content"].lower()
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


def test_a_question_gets_a_scope_reply_and_changes_nothing(client, ai, ngo, published_campaign):
    req_id = open_request(client, ngo, published_campaign)
    thread = say(client, ngo, req_id, "what else can we do with the money?")
    assert thread["claims"] == []
    last = agent_msgs(thread)[-1]
    assert "can only help with your spending update" in last["content"] and last["meta"]["awaiting"] == "ask_spend"
    assert action_kinds(last) == ["nothing_spent"]
    assert not any("drafted" in m["content"] for m in agent_msgs(thread))


def test_a_question_does_not_wipe_a_proposal_waiting_for_yes(client, ai, ngo, published_campaign):
    req_id = open_request(client, ngo, published_campaign)
    say(client, ngo, req_id, "We bought 25 school kits for $500.")
    thread = say(client, ngo, req_id, "wait, can we spend it on something else?")
    live = [c for c in thread["claims"] if c["status"] != "withdrawn"]
    assert [c["status"] for c in live] == ["proposed"]
    assert agent_msgs(thread)[-1]["meta"]["awaiting"] == "confirm_claims"


def test_no_second_draft_while_a_follow_up_question_is_open(client, ai, ngo, published_campaign):
    req_id = open_request(client, ngo, published_campaign)
    say(client, ngo, req_id, "We bought 25 school kits for $500.")
    claim = client.post(f"/api/reporting-requests/{req_id}/claims/confirm", headers=ngo).json()["claims"][0]
    upload(client, ngo, req_id, png("TOTAL=500 NO=D4"), claim["id"])
    thread = say(client, ngo, req_id, "Skip")
    drafts = sum(1 for m in agent_msgs(thread) if m["meta"].get("step") == "queue_for_review")
    assert drafts == 1

    thread = say(client, ngo, req_id, "We also bought 10 pens")  # no price: the assistant must ask, not re-draft
    assert agent_msgs(thread)[-1]["meta"]["awaiting"] == "ask_amount"
    assert sum(1 for m in agent_msgs(thread) if m["meta"].get("step") == "queue_for_review") == 1
    thread = say(client, ngo, req_id, "30$")  # the answer belongs to the pens, not to a new "unspecified expense"
    assert any("10 pens" in c["description"] and c["amount_cents"] == 3000 for c in thread["claims"])
    assert not any("unspecified" in c["description"] for c in thread["claims"])


def test_that_is_all_finishes_when_something_is_already_reported(client, ai, ngo, published_campaign):
    req_id = open_request(client, ngo, published_campaign)
    thread = say(client, ngo, req_id, "Nothing spent yet")
    thread = say(client, ngo, req_id, "Skip")  # nothing was reported at all: no draft, a plain note
    assert "nothing to report" in agent_msgs(thread)[-1]["content"].lower()
    assert not any("drafted" in m["content"] for m in agent_msgs(thread))


def test_a_question_during_a_receipt_gap_is_not_recorded_as_an_explanation(client, ai, ngo, published_campaign):
    req_id = open_request(client, ngo, published_campaign)
    say(client, ngo, req_id, "We bought 25 school kits for $500.")
    claim = client.post(f"/api/reporting-requests/{req_id}/claims/confirm", headers=ngo).json()["claims"][0]
    thread = upload(client, ngo, req_id, png("TOTAL=420 NO=E5"), claim["id"])
    gap = agent_msgs(thread)[-1]
    thread = say(client, ngo, req_id, "what else can we do with the money?")
    last = agent_msgs(thread)[-1]
    assert "can only help with your spending update" in last["content"]
    assert [a["kind"] for a in last["meta"]["actions"]] == [a["kind"] for a in gap["meta"]["actions"]]  # buttons stay
    open_inv = thread["investigations"][0]
    assert "NGO reply" not in (open_inv.get("resolution") or "")
    thread = say(client, ngo, req_id, "The supplier gave us a discount.")  # a real explanation is still noted
    assert "noted that" in agent_msgs(thread)[-1]["content"]


def _gap(client, ai, ngo, cid):
    req_id = open_request(client, ngo, cid)
    say(client, ngo, req_id, "We bought 25 school kits for $500.")
    claim = client.post(f"/api/reporting-requests/{req_id}/claims/confirm", headers=ngo).json()["claims"][0]
    thread = upload(client, ngo, req_id, png("TOTAL=420 NO=F6"), claim["id"])
    return req_id, claim, thread


def test_an_explanation_keeps_the_buttons_so_the_ngo_is_not_stuck(client, ai, ngo, published_campaign):
    req_id, claim, gap = _gap(client, ai, ngo, published_campaign)
    thread = say(client, ngo, req_id, "The supplier gave us a discount.")
    last = agent_msgs(thread)[-1]
    assert "noted that" in last["content"] and last["meta"]["awaiting"] == "ask_clarification"
    assert action_kinds(last) == action_kinds(gap and agent_msgs(gap)[-1])


def test_a_no_document_reply_asks_to_confirm_then_records_it(client, ai, ngo, published_campaign):
    req_id, claim, _ = _gap(client, ai, ngo, published_campaign)
    thread = say(client, ngo, req_id, "nope, we threw it away")  # wording no keyword list would catch
    assert thread["claims"][0]["evidence_status"] == "needs_clarification"  # a label alone changes nothing
    ask = agent_msgs(thread)[-1]
    assert ask["meta"]["awaiting"] == "confirm_no_doc" and "no_evidence" in action_kinds(ask)
    thread = say(client, ngo, req_id, "yes")
    assert thread["claims"][0]["evidence_status"] == "not_documented"
    last = agent_msgs(thread)[-1]
    assert "no receipt for" in last["content"] and "your own report" in last["content"] and "fraud" not in last["content"].lower()
    assert sum(1 for m in thread["messages"] if m["sender_role"] == "ngo" and m["content"] == "yes") == 1


def test_the_confirm_button_records_not_documented(client, ai, ngo, published_campaign):
    req_id, claim, _ = _gap(client, ai, ngo, published_campaign)
    say(client, ngo, req_id, "no doc")
    thread = client.post(f"/api/claims/expense/{claim['id']}/no-evidence", json={"explanation": "I don't have one."}, headers=ngo).json()
    assert thread["claims"][0]["evidence_status"] == "not_documented"


def test_without_ai_the_plain_patterns_still_classify_replies(client, no_ai, ngo, published_campaign):
    from app.agent.workflow import reply_intent
    from contracts.reporting_schemas import ReplyIntent

    assert reply_intent("c", "q", "no doc") == ReplyIntent.NO_DOCUMENT
    assert reply_intent("c", "q", "can we spend it elsewhere?") == ReplyIntent.QUESTION
    assert reply_intent("c", "q", "we also bought 2 pens") == ReplyIntent.NEW_REPORT
    assert reply_intent("c", "q", "a discount applied") == ReplyIntent.EXPLANATION


def test_if_the_ai_call_fails_the_patterns_take_over(client, ngo, published_campaign):
    from app.agent.llm import AIUnavailable, set_ai_provider
    from app.agent.workflow import reply_intent
    from contracts.reporting_schemas import ReplyIntent

    class Down:
        def classify_reply(self, *a):
            raise AIUnavailable("down")

    set_ai_provider(Down())
    try:
        assert reply_intent("c", "q", "no doc") == ReplyIntent.NO_DOCUMENT
    finally:
        set_ai_provider(None)


def test_a_new_expense_during_a_receipt_question_is_not_swallowed(client, ai, ngo, published_campaign):
    req_id, claim, _ = _gap(client, ai, ngo, published_campaign)
    thread = say(client, ngo, req_id, "We also bought 10 pens for $30.")
    proposed = [c for c in thread["claims"] if c["status"] == "proposed"]
    assert [c["amount_cents"] for c in proposed] == [3000]
    assert agent_msgs(thread)[-1]["meta"]["awaiting"] == "confirm_claims"


def test_the_earlier_receipt_gap_comes_back_after_the_new_expense_is_settled(client, ai, ngo, published_campaign):
    req_id, claim, _ = _gap(client, ai, ngo, published_campaign)
    say(client, ngo, req_id, "We also bought 10 pens for $30.")
    thread = client.post(f"/api/reporting-requests/{req_id}/claims/confirm", headers=ngo).json()
    last = agent_msgs(thread)[-1]
    assert "$30.00" in last["content"] and last["meta"]["awaiting"] == "ask_receipt"  # the new item first, no repeat of the old gap
    assert not any(m["content"].startswith("Back to the earlier") for m in agent_msgs(thread))
    pens = next(c for c in thread["claims"] if c["amount_cents"] == 3000)
    thread = client.post(f"/api/claims/expense/{pens['id']}/no-evidence", json={"explanation": "I don't have one."}, headers=ngo).json()
    last = agent_msgs(thread)[-1]
    assert "Back to the earlier question" in last["content"] and "$80.00" in last["content"]
    assert last["meta"]["awaiting"] == "ask_clarification" and "no_evidence" in action_kinds(last)


def test_button_taps_appear_in_the_chat_as_the_ngos_messages(client, ai, ngo, published_campaign):
    req_id = open_request(client, ngo, published_campaign)
    say(client, ngo, req_id, "We bought 25 school kits for $500.")
    thread = client.post(f"/api/reporting-requests/{req_id}/claims/confirm", headers=ngo).json()
    assert [m["content"] for m in thread["messages"] if m["sender_role"] == "ngo"][-1] == "Yes, that's right"
    say(client, ngo, req_id, "no")  # a typed reply is never echoed twice
    req2 = open_request(client, ngo, published_campaign, key="demo-2")
    say(client, ngo, req2, "We bought 5 pens for $10.")
    thread = say(client, ngo, req2, "yes")
    assert sum(1 for m in thread["messages"] if m["sender_role"] == "ngo" and m["content"].lower().startswith("yes")) == 1
    say(client, ngo, req2, "We also bought 3 pads for $9.")
    thread = client.post(f"/api/reporting-requests/{req2}/claims/reject", headers=ngo).json()
    assert [m["content"] for m in thread["messages"] if m["sender_role"] == "ngo"][-1] == "Not quite"


def test_a_resurfaced_gap_has_a_lead_in_and_an_impact_phrase_keeps_one_number():
    from app.agent.workflow import _phrase
    from app.db.models import ImpactClaim

    assert _phrase(ImpactClaim(description="20 kits handed out to students", quantity=20.0, unit="kits")) == "20 kits handed out to students"


def test_claims_from_one_message_share_a_report_id_so_the_panel_can_show_them_together(client, ai, ngo, published_campaign):
    req_id = open_request(client, ngo, published_campaign)
    thread = say(client, ngo, req_id, "We bought 25 school kits for $500 and distributed 20.")
    ids = {c["claim_type"]: c["report_id"] for c in thread["claims"]}
    assert ids["expense"] and ids["expense"] == ids["impact"]


def test_a_stray_question_keeps_the_receipt_prompt_and_its_buttons(client, ai, ngo, published_campaign):
    req_id = open_request(client, ngo, published_campaign)
    say(client, ngo, req_id, "We bought 25 school kits for $500.")
    thread = client.post(f"/api/reporting-requests/{req_id}/claims/confirm", headers=ngo).json()
    asked = agent_msgs(thread)[-1]
    thread = say(client, ngo, req_id, "what else can we do with the money?")
    last = agent_msgs(thread)[-1]
    assert "can only help with your spending update" in last["content"] and "receipt for 25 school kits ($500.00)" in last["content"]
    assert last["meta"]["awaiting"] == "ask_receipt" and action_kinds(last) == action_kinds(asked)
    thread = say(client, ngo, req_id, "and what about the rest of the budget?")  # asked twice: no nested repeats
    assert agent_msgs(thread)[-1]["content"].count("can only help") == 1


def test_a_question_with_a_number_is_not_taken_as_the_amount(client, ai, ngo, published_campaign):
    req_id = open_request(client, ngo, published_campaign)
    say(client, ngo, req_id, "We also bought 10 pens")
    thread = say(client, ngo, req_id, "can we use 5 pens instead?")
    assert thread["claims"] == [] and agent_msgs(thread)[-1]["meta"]["awaiting"] == "ask_amount"
    assert "How much did 10 pens cost?" in agent_msgs(thread)[-1]["content"]
    for answer in ("30", "$30", "30$", "about 30 dollars"):
        thread = say(client, ngo, req_id, answer)
        if thread["claims"]:
            break
    assert [c["amount_cents"] for c in thread["claims"]] == [3000]


def test_a_stray_question_while_asked_about_handing_out_keeps_that_question(client, ai, ngo, published_campaign):
    req_id = open_request(client, ngo, published_campaign)
    say(client, ngo, req_id, "We bought 25 school kits for $500.")
    claim = client.post(f"/api/reporting-requests/{req_id}/claims/confirm", headers=ngo).json()["claims"][0]
    upload(client, ngo, req_id, png("TOTAL=500 NO=Q7"), claim["id"])
    thread = say(client, ngo, req_id, "why do you ask?")
    last = agent_msgs(thread)[-1]
    assert "handed out" in last["content"] and last["meta"]["awaiting"] == "ask_delivery"


def _photo(client, ngo, req_id, marker, claim=None, name="items.png"):
    form = {"reporting_request_id": req_id, "kind": "photo"}
    if claim:
        form |= {"claim_type": claim["claim_type"], "claim_id": claim["id"]}
    r = client.post("/api/evidence/upload", data=form, files={"file": (name, png(marker), "image/png")}, headers=ngo)
    assert r.status_code == 200, r.text
    return r.json()


def test_asking_to_show_photos_gets_a_yes_and_keeps_the_pending_question(client, ai, ngo, published_campaign):
    req_id = open_request(client, ngo, published_campaign)
    say(client, ngo, req_id, "We bought 25 school kits for $500.")
    client.post(f"/api/reporting-requests/{req_id}/claims/confirm", headers=ngo)
    thread = say(client, ngo, req_id, "can I instead show you pictures of the donated items and the people")
    last = agent_msgs(thread)[-1]
    assert "you can add photos" in last["content"] and "don't replace a receipt" in last["content"]
    assert last["meta"]["awaiting"] == "ask_receipt" and "receipt for 25 school kits" in last["content"]
    assert action_kinds(last) == ["upload", "no_evidence", "upload_photo"]


def test_a_photo_is_kept_but_never_counts_as_proof_or_as_a_receipt(client, ai, ngo, published_campaign):
    req_id = open_request(client, ngo, published_campaign)
    say(client, ngo, req_id, "We bought 25 school kits for $500 and distributed 20.")
    thread = client.post(f"/api/reporting-requests/{req_id}/claims/confirm", headers=ngo).json()
    impact = next(c for c in thread["claims"] if c["claim_type"] == "impact")
    expense = next(c for c in thread["claims"] if c["claim_type"] == "expense")
    thread = _photo(client, ngo, req_id, "PHOTO-1", claim=impact)
    last = agent_msgs(thread)[-1]
    assert "photo added" in last["content"] and last["meta"]["awaiting"] == "ask_receipt"  # the receipt question is still open
    assert "upload" in action_kinds(last)
    assert any(e["kind"] == "photo" for e in thread["evidence"])
    shown = next(c for c in thread["claims"] if c["id"] == impact["id"])
    assert shown["evidence_status"] == "submitted"  # "documents received", never "consistent"
    exp_now = next(c for c in thread["claims"] if c["id"] == expense["id"])
    assert exp_now["evidence_status"] == "reported" and exp_now["supported_amount_cents"] in (0, None)
    thread = _photo(client, ngo, req_id, "PHOTO-1", name="again.png")  # same photo again
    assert "identical to one already added" in agent_msgs(thread)[-1]["content"]


def test_without_ai_a_photo_message_is_still_recognised(client, no_ai):
    from app.agent.workflow import reply_intent
    from contracts.reporting_schemas import ReplyIntent

    assert reply_intent("c", "q", "can I show you pictures of the people") == ReplyIntent.SHARE_FILES


def test_notes_are_never_nested_when_a_stray_question_is_followed_by_a_photo_question(client, ai, ngo, published_campaign):
    req_id = open_request(client, ngo, published_campaign)
    say(client, ngo, req_id, "We bought 25 school kits for $500.")
    client.post(f"/api/reporting-requests/{req_id}/claims/confirm", headers=ngo)
    say(client, ngo, req_id, "what else can we do with the money?")
    thread = say(client, ngo, req_id, "can I instead show you pictures of the donated items")
    text = agent_msgs(thread)[-1]["content"]
    assert text.count("can only help") == 0 and text.count("you can add photos") == 1 and "receipt for 25 school kits" in text


def test_shared_photos_reach_donors_but_a_private_photo_or_receipt_does_not(client, ai, ngo, published_campaign):
    req_id = open_request(client, ngo, published_campaign)
    say(client, ngo, req_id, "We bought 25 school kits for $500.")
    client.post(f"/api/reporting-requests/{req_id}/claims/confirm", headers=ngo)
    _photo(client, ngo, req_id, "shown")
    _photo(client, ngo, req_id, "hidden", name="other.png")
    photos = [m["meta"]["evidence_id"] for m in client.get(f"/api/reporting-requests/{req_id}/thread", headers=ngo).json()["messages"] if m["meta"].get("step") == "evidence_upload"]
    assert len(photos) == 2
    client.post(f"/api/evidence/{photos[1]}/visibility", json={"visibility": "private"}, headers=ngo)
    draft = client.post(f"/api/campaigns/{published_campaign}/updates/draft", json={"reporting_request_id": req_id}, headers=ngo).json()
    entry = next(e for e in client.get(f"/api/campaigns/{published_campaign}/updates", headers=ngo).json() if e["update"]["id"] == draft["id"])
    assert entry["photos"] == [photos[0]]

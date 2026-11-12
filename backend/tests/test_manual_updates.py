"""Starting an extra update by hand, and removing a reported claim."""

from tests.conftest import login, png
from tests.test_conversation import agent_msgs, say
from tests.test_safeguards import open_request
from tests.test_vertical_slice import upload


def trigger(client, ngo, cid):
    r = client.post(f"/api/campaigns/{cid}/reporting-requests/trigger", json={}, headers=ngo)
    assert r.status_code == 200, r.text
    return r.json()["request"]


def test_start_returns_the_open_update_instead_of_stacking_another(client, ai, ngo, published_campaign):
    first = open_request(client, ngo, published_campaign)
    assert trigger(client, ngo, published_campaign)["id"] == first


def test_start_after_a_published_update_opens_an_extra_one(client, ai, ngo, published_campaign):
    req_id = open_request(client, ngo, published_campaign)
    say(client, ngo, req_id, "We bought 25 school kits for $500 and distributed 20.")
    thread = client.post(f"/api/reporting-requests/{req_id}/claims/confirm", headers=ngo).json()
    expense = next(c for c in thread["claims"] if c["claim_type"] == "expense")
    upload(client, ngo, req_id, png("TOTAL=500 NO=Q1"), expense["id"])
    draft = client.get(f"/api/campaigns/{published_campaign}/updates", headers=ngo).json()[0]["update"]
    client.post(f"/api/updates/{draft['id']}/approve", headers=ngo)
    client.post(f"/api/updates/{draft['id']}/publish", headers=ngo)
    extra = trigger(client, ngo, published_campaign)
    assert extra["id"] != req_id and extra["cycle_key"].startswith(("cycle-", "extra-"))


def _two_claims(client, ngo, cid):
    req_id = open_request(client, ngo, cid)
    say(client, ngo, req_id, "We bought 25 school kits for $500 and distributed 20.")
    thread = client.post(f"/api/reporting-requests/{req_id}/claims/confirm", headers=ngo).json()
    return req_id, thread


def test_removing_a_claim_withdraws_it_and_moves_on(client, ai, ngo, published_campaign):
    req_id, thread = _two_claims(client, ngo, published_campaign)
    expense = next(c for c in thread["claims"] if c["claim_type"] == "expense")
    r = client.post(f"/api/claims/expense/{expense['id']}/withdraw", headers=ngo)
    assert r.status_code == 200
    thread = r.json()
    assert next(c for c in thread["claims"] if c["id"] == expense["id"])["status"] == "withdrawn"
    assert "Removed" in agent_msgs(thread)[-1]["content"]
    again = client.post(f"/api/claims/expense/{expense['id']}/withdraw", headers=ngo)
    assert again.status_code == 200  # removing twice is harmless


def test_removing_the_last_claim_asks_what_was_spent(client, ai, ngo, published_campaign):
    req_id = open_request(client, ngo, published_campaign)
    thread = say(client, ngo, req_id, "We bought 25 school kits for $500.")
    claim = thread["claims"][0]
    thread = client.post(f"/api/claims/{claim['claim_type']}/{claim['id']}/withdraw", headers=ngo).json()
    assert agent_msgs(thread)[-1]["meta"]["awaiting"] == "ask_spend"


def test_a_claim_donors_have_seen_cannot_be_removed(client, ai, ngo, published_campaign):
    req_id, thread = _two_claims(client, ngo, published_campaign)
    expense = next(c for c in thread["claims"] if c["claim_type"] == "expense")
    upload(client, ngo, req_id, png("TOTAL=500 NO=Q2"), expense["id"])
    draft = client.get(f"/api/campaigns/{published_campaign}/updates", headers=ngo).json()[0]["update"]
    client.post(f"/api/updates/{draft['id']}/approve", headers=ngo)
    client.post(f"/api/updates/{draft['id']}/publish", headers=ngo)
    assert client.post(f"/api/claims/expense/{expense['id']}/withdraw", headers=ngo).status_code == 409


def test_another_ngo_cannot_remove_my_claim(client, ai, ngo, published_campaign):
    _, thread = _two_claims(client, ngo, published_campaign)
    other = login(client, "other-ngo@example.com", "ngo_admin")
    claim = thread["claims"][0]
    assert client.post(f"/api/claims/{claim['claim_type']}/{claim['id']}/withdraw", headers=other).status_code == 404

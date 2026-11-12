"""Evidence retrieval (Elastic with Postgres fallback): scoping, provenance, degraded mode."""

import pytest

from app.agent import retrieval
from integrations.elastic_retrieval import INDEX, ElasticRetrieval, RetrievalDoc, _rrf, Hit
from tests.conftest import login, png
from tests.test_safeguards import open_request
from tests.test_vertical_slice import upload


class FakeIndices:
    def __init__(self):
        self.created = None

    def exists(self, index):
        return self.created is not None

    def create(self, index, mappings):
        self.created = mappings


class FakeElastic:
    """Tiny in-memory stand-in: term filters + naive keyword match."""

    def __init__(self, fail=False):
        self.indices = FakeIndices()
        self.docs: dict[str, dict] = {}
        self.fail = fail
        self.queries: list[dict] = []

    def index(self, index, id, document, refresh=None):
        assert index == INDEX
        self.docs[id] = document

    def search(self, index, query, size, source_excludes=None):
        if self.fail:
            raise ConnectionError("cluster unavailable")
        self.queries.append(query)
        b = query["bool"]
        filters = {k: v for f in b.get("filter", []) for k, v in f["term"].items()}
        must_not = {k: v for f in b.get("must_not", []) for k, v in f["term"].items()}
        words = set()
        for m in b.get("must", []):
            if "match" in m:
                words = set(m["match"]["text"].lower().split())
        hits = []
        for doc in self.docs.values():
            if any(doc.get(k) != v for k, v in filters.items()) or any(doc.get(k) == v for k, v in must_not.items()):
                continue
            score = len(words & set(doc["text"].lower().split())) if words else 1
            if score:
                hits.append({"_source": doc, "_score": score})
        hits.sort(key=lambda h: -h["_score"])
        return {"hits": {"hits": hits[:size]}}


@pytest.fixture
def fake_es():
    es = FakeElastic()
    retrieval.set_elastic_client(es)
    yield es
    retrieval.set_elastic_client(None)


@pytest.fixture(autouse=True)
def _no_elastic_by_default():
    retrieval.set_elastic_client(None)
    yield


def _claim(client, ngo, req_id, description, amount):
    t = client.post(f"/api/reporting-requests/{req_id}/claims", json={"claim_type": "expense", "description": description, "amount": amount}, headers=ngo).json()
    return t["claims"][-1]["id"]


def test_discrepancy_question_cites_earlier_records_via_elastic(client, ai, ngo, published_campaign, fake_es):
    earlier = open_request(client, ngo, published_campaign, "cycle-earlier")
    client.post(f"/api/reporting-requests/{earlier}/messages", json={"content": "Ordered school kits from Demo Stationers, bags invoiced separately."}, headers=ngo)
    req_id = open_request(client, ngo, published_campaign, "cycle-now")
    claim_id = _claim(client, ngo, req_id, "school kits", 500)
    thread = upload(client, ngo, req_id, png("TOTAL=420 NO=A1"), claim_id)
    assert fake_es.indices.created is not None  # index created with campaign/ngo keyword fields
    question = thread["messages"][-1]["content"]
    assert "$80.00" in question and "[activity_report" not in question  # chat stays short
    ctx = next(c for c in thread["checks"] if c["check_type"] == "context_retrieval")
    assert ctx["findings"]["backend"] == "elastic" and ctx["findings"]["hits"][0]["source_type"] == "activity_report"
    # Every search is scoped to this campaign.
    assert all({"term": {"campaign_id": published_campaign}} in q["bool"]["filter"] for q in fake_es.queries if "match" in str(q))


def test_elastic_outage_falls_back_to_postgres(client, ai, ngo, published_campaign, fake_es):
    fake_es.fail = True
    req_id = open_request(client, ngo, published_campaign)
    client.post(f"/api/reporting-requests/{req_id}/messages", json={"content": "Bought school kits at the market"}, headers=ngo)
    claim_id = _claim(client, ngo, req_id, "school kits", 500)
    thread = upload(client, ngo, req_id, png("TOTAL=420"), claim_id)
    ctx = next(c for c in thread["checks"] if c["check_type"] == "context_retrieval")
    assert ctx["findings"]["backend"] == "postgres"
    assert thread["claims"][-1]["evidence_status"] == "needs_clarification"  # reporting never blocked


def test_postgres_fallback_is_campaign_scoped(client, ai, ngo, published_campaign):
    # A second campaign of the same NGO with very similar wording must not leak in.
    other = client.post("/api/campaigns", json={"title": "Other campaign kits", "description": "Different campaign for school kits.", "target_amount": 100}, headers=ngo).json()["id"]
    hits, backend = retrieval.search_campaign(next(_db(client)), other, "school kits")
    assert backend == "postgres" and hits == []


def _db(client):
    from app.db.base import get_db
    from app.main import app

    yield from app.dependency_overrides[get_db]()


def test_reused_receipt_number_across_claims_not_counted(client, ai, ngo, published_campaign):
    req_id = open_request(client, ngo, published_campaign)
    c1 = _claim(client, ngo, req_id, "school kits", 100)
    upload(client, ngo, req_id, png("TOTAL=100 NO=INV-77"), c1)
    c2 = _claim(client, ngo, req_id, "kit bags", 100)
    thread = upload(client, ngo, req_id, png("TOTAL=100 NO=INV-77 copy"), c2, name="again.png")
    second = next(c for c in thread["claims"] if c["id"] == c2)
    assert second["supported_amount_cents"] == 0 and second["evidence_status"] == "needs_clarification"
    assert "already submitted" in thread["messages"][-1]["content"]  # one combined question, not two bubbles
    trail = next(r for r in client.get("/api/accountability", headers=ngo).json()["claims"] if r["claim_id"] == c2)["checks"]
    assert any(c["check_type"] == "reused_receipt" and c["status"] == "flag" for c in trail)


def test_rrf_merges_keyword_and_semantic_rankings():
    a, b, c = (Hit("evidence", x, x, 0) for x in "abc")
    merged = _rrf([[a, b], [b, c]])
    assert [h.source_id for h in merged][0] == "b"


def test_semantic_field_added_only_with_inference_endpoint():
    es = FakeElastic()
    ElasticRetrieval(es, inference_id=".elser-2-elasticsearch").index(RetrievalDoc("x:1", "c", "n", "activity_report", "1", "text"))
    assert es.indices.created["properties"]["text_semantic"]["type"] == "semantic_text"
    es2 = FakeElastic()
    ElasticRetrieval(es2).index(RetrievalDoc("x:1", "c", "n", "activity_report", "1", "text"))
    assert "text_semantic" not in es2.indices.created["properties"]


def test_donor_never_sees_other_ngo_data(client, ngo):
    login(client, "donor@example.com", "donor")  # retrieval has no public endpoint at all
    assert client.get("/api/search").status_code == 404

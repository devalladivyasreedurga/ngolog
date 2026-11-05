"""Evidence retrieval for the accountability agent (spec section 4, RAG design).

ElasticRetrieval: hybrid keyword + semantic search over a campaign's NGO reports,
receipt summaries and published updates, always filtered to one campaign. Semantic
search uses a `semantic_text` field when ELASTIC_INFERENCE_ID names an inference
endpoint; otherwise it is keyword-only.

PostgresRetrieval: reduced-function fallback when Elastic is not configured or down.

Rules: financial totals never come from here. Hits are leads with provenance
(source_type, source_id, evidence_id), not proof. Only NGO-authored campaign text
is indexed; no donor data.
"""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field

log = logging.getLogger(__name__)

INDEX = "ngolog-evidence"


@dataclass
class RetrievalDoc:
    doc_id: str  # "<source_type>:<source_id>"
    campaign_id: str
    ngo_id: str
    source_type: str  # activity_report | evidence | donor_update
    source_id: str
    text: str
    evidence_id: str | None = None
    receipt_number: str | None = None
    created_at: str | None = None


@dataclass
class Hit:
    source_type: str
    source_id: str
    snippet: str
    score: float
    evidence_id: str | None = None
    campaign_id: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class ElasticRetrieval:
    client: object  # elasticsearch.Elasticsearch (or a test double)
    inference_id: str | None = None
    _ready: bool = field(default=False, init=False)
    name: str = "elastic"

    def ensure_index(self) -> None:
        if self._ready:
            return
        if not self.client.indices.exists(index=INDEX):
            props = {
                "campaign_id": {"type": "keyword"},
                "ngo_id": {"type": "keyword"},
                "source_type": {"type": "keyword"},
                "source_id": {"type": "keyword"},
                "evidence_id": {"type": "keyword"},
                "receipt_number": {"type": "keyword"},
                "created_at": {"type": "date"},
                "text": {"type": "text"},
            }
            if self.inference_id:
                props["text"]["copy_to"] = "text_semantic"
                props["text_semantic"] = {"type": "semantic_text", "inference_id": self.inference_id}
            self.client.indices.create(index=INDEX, mappings={"properties": props})
        self._ready = True

    def index(self, doc: RetrievalDoc) -> str:
        self.ensure_index()
        body = {k: v for k, v in asdict(doc).items() if k != "doc_id" and v is not None}
        self.client.index(index=INDEX, id=doc.doc_id, document=body, refresh="wait_for")
        return doc.doc_id

    def search(self, campaign_id: str, query: str, k: int = 3, exclude_source_ids: set[str] | None = None) -> list[Hit]:
        self.ensure_index()
        exclude = exclude_source_ids or set()
        scope = [{"term": {"campaign_id": campaign_id}}]
        keyword = self._run({"bool": {"filter": scope, "must": [{"match": {"text": query}}]}}, k + len(exclude))
        ranked = [keyword]
        if self.inference_id:
            ranked.append(self._run({"bool": {"filter": scope, "must": [{"semantic": {"field": "text_semantic", "query": query}}]}}, k + len(exclude)))
        return [h for h in _rrf(ranked) if h.source_id not in exclude][:k]

    def find_reused_receipts(self, ngo_id: str, receipt_number: str, exclude_evidence_id: str) -> list[Hit]:
        """Narrow cross-campaign check (same NGO only): identical receipt numbers."""
        self.ensure_index()
        q = {"bool": {"filter": [{"term": {"ngo_id": ngo_id}}, {"term": {"receipt_number": receipt_number}}], "must_not": [{"term": {"evidence_id": exclude_evidence_id}}]}}
        return self._run(q, 5)

    def _run(self, query: dict, size: int) -> list[Hit]:
        res = self.client.search(index=INDEX, query=query, size=size, source_excludes=["text_semantic"])
        hits = []
        for h in res["hits"]["hits"]:
            s = h["_source"]
            hits.append(Hit(source_type=s["source_type"], source_id=s["source_id"], snippet=_snippet(s.get("text", "")), score=float(h.get("_score") or 0), evidence_id=s.get("evidence_id"), campaign_id=s.get("campaign_id")))
        return hits


@dataclass
class PostgresRetrieval:
    """Keyword-overlap fallback over the same documents, read straight from Postgres."""

    docs_loader: object  # callable(campaign_id) -> list[RetrievalDoc]
    reused_loader: object  # callable(ngo_id, receipt_number, exclude_evidence_id) -> list[RetrievalDoc]
    name: str = "postgres"

    def index(self, doc: RetrievalDoc) -> str:
        return doc.doc_id  # nothing to do: Postgres is already the source

    def search(self, campaign_id: str, query: str, k: int = 3, exclude_source_ids: set[str] | None = None) -> list[Hit]:
        terms = _terms(query)
        exclude = exclude_source_ids or set()
        scored = []
        for d in self.docs_loader(campaign_id):
            if d.source_id in exclude:
                continue
            overlap = len(terms & _terms(d.text))
            if overlap:
                scored.append(Hit(d.source_type, d.source_id, _snippet(d.text), float(overlap), d.evidence_id, d.campaign_id))
        return sorted(scored, key=lambda h: -h.score)[:k]

    def find_reused_receipts(self, ngo_id: str, receipt_number: str, exclude_evidence_id: str) -> list[Hit]:
        return [Hit(d.source_type, d.source_id, _snippet(d.text), 1.0, d.evidence_id, d.campaign_id) for d in self.reused_loader(ngo_id, receipt_number, exclude_evidence_id)]


def _rrf(rankings: list[list[Hit]], k: int = 60) -> list[Hit]:
    """Reciprocal rank fusion of keyword and semantic result lists."""
    scores: dict[str, float] = {}
    first: dict[str, Hit] = {}
    for ranking in rankings:
        for rank, hit in enumerate(ranking):
            key = f"{hit.source_type}:{hit.source_id}"
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
            first.setdefault(key, hit)
    out = []
    for key in sorted(scores, key=lambda x: -scores[x]):
        h = first[key]
        out.append(Hit(h.source_type, h.source_id, h.snippet, scores[key], h.evidence_id, h.campaign_id))
    return out


_STOP = {"the", "and", "for", "with", "from", "that", "this", "was", "were", "receipt", "invoice"}


def _terms(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]{3,}", text.lower()) if w not in _STOP}


def _snippet(text: str, n: int = 160) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "…"

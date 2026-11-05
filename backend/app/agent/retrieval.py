"""Wires integrations/elastic_retrieval.py into the app: what gets indexed, and the
Postgres fallback when Elastic is missing or failing."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.checks import effective_receipt_values
from app.config import get_settings
from app.db.models import ActivityReport, Campaign, DonorUpdate, Evidence, RetrievalDocument
from contracts.reporting_schemas import PublicationStatus
from integrations.elastic_retrieval import ElasticRetrieval, Hit, PostgresRetrieval, RetrievalDoc

log = logging.getLogger(__name__)

_client_override: object | None = None
_client_override_set = False
_elastic: ElasticRetrieval | None = None


def set_elastic_client(client: object | None) -> None:
    """Test hook: inject an Elasticsearch double (or None to force the fallback)."""
    global _client_override, _client_override_set, _elastic
    _client_override, _client_override_set, _elastic = client, True, None


def _elastic_backend() -> ElasticRetrieval | None:
    global _elastic
    if _elastic is not None:
        return _elastic
    s = get_settings()
    if _client_override_set:
        client = _client_override
    elif s.elastic_url:
        from elasticsearch import Elasticsearch

        client = Elasticsearch(s.elastic_url, api_key=s.elastic_api_key or None, request_timeout=10)
    else:
        client = None
    if client is not None:
        _elastic = ElasticRetrieval(client, inference_id=s.elastic_inference_id or None)
    return _elastic


# ---------------------------------------------------------------- documents from Postgres


def _ngo_id(db: Session, campaign_id: str) -> str:
    return db.get(Campaign, campaign_id).ngo_id


def evidence_text(ev: Evidence) -> str:
    v = effective_receipt_values(ev)
    items = "; ".join(f"{i.get('description')} {i.get('amount') or ''}".strip() for i in v.get("line_items") or [] if isinstance(i, dict))
    parts = [f"{ev.kind} {ev.original_filename}"]
    for label, key in (("merchant", "merchant"), ("number", "receipt_number"), ("date", "receipt_date"), ("total", "total"), ("currency", "currency")):
        if v.get(key) is not None:
            parts.append(f"{label} {v[key]}")
    if items:
        parts.append(f"items {items}")
    return ", ".join(parts)


def doc_for_report(db: Session, r: ActivityReport) -> RetrievalDoc:
    return RetrievalDoc(f"activity_report:{r.id}", r.campaign_id, _ngo_id(db, r.campaign_id), "activity_report", r.id, r.description, created_at=r.reported_at.isoformat())


def doc_for_evidence(db: Session, ev: Evidence) -> RetrievalDoc:
    number = (effective_receipt_values(ev).get("receipt_number") or "").strip() or None
    return RetrievalDoc(f"evidence:{ev.id}", ev.campaign_id, _ngo_id(db, ev.campaign_id), "evidence", ev.id, evidence_text(ev), evidence_id=ev.id, receipt_number=number, created_at=ev.created_at.isoformat())


def doc_for_update(db: Session, u: DonorUpdate) -> RetrievalDoc:
    return RetrievalDoc(f"donor_update:{u.id}", u.campaign_id, _ngo_id(db, u.campaign_id), "donor_update", u.id, u.body, created_at=(u.published_at or u.created_at).isoformat())


def _fallback(db: Session) -> PostgresRetrieval:
    def docs(campaign_id: str) -> list[RetrievalDoc]:
        out = [doc_for_report(db, r) for r in db.scalars(select(ActivityReport).where(ActivityReport.campaign_id == campaign_id))]
        out += [doc_for_evidence(db, e) for e in db.scalars(select(Evidence).where(Evidence.campaign_id == campaign_id))]
        out += [doc_for_update(db, u) for u in db.scalars(select(DonorUpdate).where(DonorUpdate.campaign_id == campaign_id, DonorUpdate.status == PublicationStatus.PUBLISHED))]
        return out

    def reused(ngo_id: str, number: str, exclude_evidence_id: str) -> list[RetrievalDoc]:
        campaign_ids = select(Campaign.id).where(Campaign.ngo_id == ngo_id)
        rows = db.scalars(select(Evidence).where(Evidence.campaign_id.in_(campaign_ids), Evidence.id != exclude_evidence_id))
        return [d for d in (doc_for_evidence(db, e) for e in rows) if d.receipt_number and d.receipt_number.lower() == number.lower()]

    return PostgresRetrieval(docs, reused)


# ---------------------------------------------------------------- public API


def index(db: Session, doc: RetrievalDoc) -> None:
    backend = _elastic_backend()
    if backend is None:
        return
    try:
        backend.index(doc)
    except Exception as e:  # noqa: BLE001 - indexing must never block reporting
        log.warning("Elastic indexing failed for %s: %s", doc.doc_id, e)
        return
    row = db.scalar(select(RetrievalDocument).where(RetrievalDocument.elastic_doc_id == doc.doc_id))
    if row is None:
        db.add(RetrievalDocument(campaign_id=doc.campaign_id, evidence_id=doc.evidence_id, source_type=doc.source_type, source_id=doc.source_id, elastic_doc_id=doc.doc_id))


def search_campaign(db: Session, campaign_id: str, query: str, k: int = 3, exclude_source_ids: set[str] | None = None) -> tuple[list[Hit], str]:
    """Campaign-scoped retrieval. Returns (hits, backend name) so callers can record provenance."""
    backend = _elastic_backend()
    if backend is not None:
        try:
            return backend.search(campaign_id, query, k, exclude_source_ids), backend.name
        except Exception as e:  # noqa: BLE001
            log.warning("Elastic search failed, using Postgres fallback: %s", e)
    fb = _fallback(db)
    return fb.search(campaign_id, query, k, exclude_source_ids), fb.name


def find_reused_receipts(db: Session, ev: Evidence) -> tuple[list[Hit], str]:
    number = (effective_receipt_values(ev).get("receipt_number") or "").strip()
    if not number:
        return [], "none"
    ngo_id = _ngo_id(db, ev.campaign_id)
    backend = _elastic_backend()
    if backend is not None:
        try:
            return backend.find_reused_receipts(ngo_id, number, ev.id), backend.name
        except Exception as e:  # noqa: BLE001
            log.warning("Elastic duplicate search failed, using Postgres fallback: %s", e)
    fb = _fallback(db)
    return fb.find_reused_receipts(ngo_id, number, ev.id), fb.name

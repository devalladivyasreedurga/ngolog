"""Deterministic claim-vs-evidence comparison. No model involved: numbers decide.

A mismatch is a lead for a follow-up question, never a fraud verdict.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ClaimEvidence, Evidence, ExpenseClaim
from contracts.reporting_schemas import EvidenceKind


def effective_receipt_values(ev: Evidence) -> dict:
    """NGO-confirmed values win over AI-extracted ones; both stay stored for audit."""
    base = dict(ev.extracted_json or {})
    base.update({k: v for k, v in (ev.confirmed_json or {}).items() if v is not None})
    return base


@dataclass
class AmountComparison:
    claim_cents: int
    documented_cents: int
    counted_evidence_ids: list[str] = field(default_factory=list)
    unreadable_evidence_ids: list[str] = field(default_factory=list)
    duplicate_evidence_ids: list[str] = field(default_factory=list)
    currency_mismatch_ids: list[str] = field(default_factory=list)

    @property
    def gap_cents(self) -> int:
        return self.claim_cents - self.documented_cents

    @property
    def matches(self) -> bool:
        return (
            self.gap_cents == 0
            and not self.unreadable_evidence_ids
            and not self.duplicate_evidence_ids
            and not self.currency_mismatch_ids
        )


def linked_evidence(db: Session, claim_type: str, claim_id: str) -> list[Evidence]:
    return list(
        db.scalars(
            select(Evidence)
            .join(ClaimEvidence, ClaimEvidence.evidence_id == Evidence.id)
            .where(ClaimEvidence.claim_type == claim_type, ClaimEvidence.claim_id == claim_id)
            .order_by(Evidence.created_at)
        )
    )


def compare_claim_evidence(db: Session, claim: ExpenseClaim) -> AmountComparison:
    result = AmountComparison(claim_cents=claim.amount_cents, documented_cents=0)
    seen_hashes: set[str] = set()
    seen_numbers: set[str] = set()
    for ev in linked_evidence(db, "expense", claim.id):
        if ev.kind not in (EvidenceKind.RECEIPT, EvidenceKind.PAYMENT_CONFIRMATION):
            continue
        values = effective_receipt_values(ev)
        number = (values.get("receipt_number") or "").strip().lower()
        if ev.sha256 in seen_hashes or (number and number in seen_numbers):
            result.duplicate_evidence_ids.append(ev.id)
            continue
        seen_hashes.add(ev.sha256)
        if number:
            seen_numbers.add(number)
        total = values.get("total")
        if total is None:
            result.unreadable_evidence_ids.append(ev.id)
            continue
        currency = (values.get("currency") or claim.currency).upper()
        if currency != claim.currency.upper():
            result.currency_mismatch_ids.append(ev.id)
            continue
        result.documented_cents += round(float(total) * 100)
        result.counted_evidence_ids.append(ev.id)
    return result


def find_exact_duplicates(db: Session, evidence: Evidence, ngo_campaign_ids: list[str]) -> list[Evidence]:
    """Same file bytes already uploaded to this NGO's campaigns (narrow scope by policy)."""
    return list(
        db.scalars(
            select(Evidence).where(
                Evidence.sha256 == evidence.sha256,
                Evidence.id != evidence.id,
                Evidence.campaign_id.in_(ngo_campaign_ids),
            )
        )
    )


def money(cents: int, currency: str = "USD") -> str:
    symbol = "$" if currency.upper() == "USD" else f"{currency.upper()} "
    return f"{symbol}{cents / 100:,.2f}"

"""Shared contracts between Developer A (platform) and Developer B (agent & evidence).

Change only by a PR both developers approve. The backend imports these enums
directly; the frontend mirrors them in frontend/lib/contracts.ts.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


# ---------------------------------------------------------------- enums


class Role(StrEnum):
    NGO_ADMIN = "ngo_admin"
    DONOR = "donor"
    REVIEWER = "reviewer"


class CampaignStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    PAUSED = "paused"
    COMPLETED = "completed"


class DonationStatus(StrEnum):
    CREATED = "created"  # PayPal order created, donor has not approved
    CAPTURED = "captured"  # server-side capture call returned COMPLETED
    COMPLETED = "completed"  # verified PAYMENT.CAPTURE.COMPLETED webhook received
    FAILED = "failed"
    REFUNDED = "refunded"


class ReportingRequestStatus(StrEnum):
    OPEN = "open"  # waiting for the NGO
    IN_REVIEW = "in_review"  # NGO has responded; agent is working
    AWAITING_APPROVAL = "awaiting_approval"  # donor-update draft waiting for NGO/reviewer
    COMPLETED = "completed"
    OVERDUE = "overdue"
    ESCALATED = "escalated"  # clarification limit reached; human review


class ClaimStatus(StrEnum):
    """What the NGO has said. Independent of evidence review."""

    PROPOSED = "proposed"  # extracted by the agent, NGO has not confirmed
    REPORTED = "reported"  # NGO confirmed this statement
    WITHDRAWN = "withdrawn"


class EvidenceReviewStatus(StrEnum):
    """Spec section 4 taxonomy. 'consistent' is NOT independently verified truth."""

    REPORTED = "reported"  # statement recorded, no evidence yet
    SUBMITTED = "submitted"  # evidence received, not yet reviewed
    CONSISTENT = "consistent"
    NEEDS_CLARIFICATION = "needs_clarification"
    REVIEWED_BY_HUMAN = "reviewed_by_human"
    NOT_DOCUMENTED = "not_documented"  # NGO explained no proof is available


class PublicationStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    PUBLISHED = "published"
    WITHDRAWN = "withdrawn"


class EvidenceVisibility(StrEnum):
    PRIVATE = "private"  # default; never shown to donors
    PUBLIC = "public"  # NGO approved for donor-facing views


class EvidenceKind(StrEnum):
    RECEIPT = "receipt"
    PHOTO = "photo"
    DISTRIBUTION_LOG = "distribution_log"
    PAYMENT_CONFIRMATION = "payment_confirmation"
    OTHER = "other"


class CheckType(StrEnum):
    AMOUNT_MATCH = "amount_match"
    EXACT_DUPLICATE = "exact_duplicate"
    NEAR_DUPLICATE = "near_duplicate"
    REUSED_RECEIPT = "reused_receipt"  # same receipt number elsewhere in this NGO
    CONTEXT_RETRIEVAL = "context_retrieval"
    EXTRACTION = "extraction"


class CheckStatus(StrEnum):
    PASS = "pass"
    FLAG = "flag"  # a lead for review, never a fraud verdict
    INCONCLUSIVE = "inconclusive"


class InvestigationStatus(StrEnum):
    OPEN = "open"
    RECONCILED = "reconciled"  # evidence now consistent with the claim
    ESCALATED = "escalated"  # sent to a human reviewer
    RESOLVED_BY_REVIEWER = "resolved_by_reviewer"


class MessageSender(StrEnum):
    AGENT = "agent"
    NGO = "ngo"
    REVIEWER = "reviewer"
    SYSTEM = "system"


class OutboundKind(StrEnum):
    NGO_FOLLOWUP = "ngo_followup"
    NGO_REMINDER = "ngo_reminder"
    DONOR_UPDATE = "donor_update"


class DeliveryStatus(StrEnum):
    QUEUED = "queued"
    SENT = "sent"  # provider confirmed
    FAILED = "failed"
    SUPPRESSED = "suppressed"  # opted out, cooldown or duplicate


# ---------------------------------------------------------------- agent I/O


class ExtractedExpense(BaseModel):
    description: str
    amount: float | None = Field(
        default=None,
        description="Amount in major units, e.g. 375.00. null when the NGO did not state an amount; never 0.",
    )
    currency: str = "USD"
    category: str | None = None
    expense_date: date | None = None
    amount_uncertain: bool = Field(
        default=False, description="True only if the NGO explicitly hedged ('about', 'roughly', 'estimated'). False when no amount was given."
    )


class ExtractedImpact(BaseModel):
    description: str
    quantity: float | None = None
    unit: str | None = None


class ExtractedClaims(BaseModel):
    """Proposed structured claims from an NGO's free-text reply. Never saved as
    'reported' until the NGO confirms them."""

    is_report: bool = True  # False for questions, small talk or anything that is not a spending/activity report
    expenses: list[ExtractedExpense] = []
    impacts: list[ExtractedImpact] = []
    unanswered_questions: list[str] = []


class ReceiptLineItem(BaseModel):
    description: str
    quantity: float | None = None
    amount: float | None = None


class ReplyIntent(StrEnum):
    """What an NGO's reply to a receipt question is. A label only: it never sets an evidence status."""

    EXPLANATION = "explanation"  # explains the difference or adds context
    NO_DOCUMENT = "no_document"  # says there is no receipt/document or one cannot be obtained
    NEW_REPORT = "new_report"  # reports a different expense or something handed out
    QUESTION = "question"  # asks the assistant something or is off topic
    OTHER = "other"


class ClassifiedReply(BaseModel):
    intent: ReplyIntent


class ReceiptExtraction(BaseModel):
    merchant: str | None = None
    receipt_number: str | None = None
    receipt_date: date | None = None
    total: float | None = None
    currency: str | None = None
    line_items: list[ReceiptLineItem] = []
    legible: bool = True
    notes: str | None = Field(default=None, description="Uncertainty, OCR problems, anything odd.")


# ---------------------------------------------------------------- shared records


class ReportingRequestOut(BaseModel):
    id: str
    campaign_id: str
    cycle_key: str
    status: ReportingRequestStatus
    due_at: datetime | None
    clarification_rounds: int
    created_at: datetime


class ClaimOut(BaseModel):
    id: str
    campaign_id: str
    claim_type: str  # "expense" | "impact"
    description: str
    amount_cents: int | None = None
    currency: str | None = None
    quantity: float | None = None
    unit: str | None = None
    status: ClaimStatus
    evidence_status: EvidenceReviewStatus
    supported_amount_cents: int | None = None
    evidence_ids: list[str] = []
    report_id: str | None = None  # the NGO message the claim came from; claims from one message are shown together


class EvidenceCheckOut(BaseModel):
    id: str
    evidence_id: str | None
    claim_id: str | None
    check_type: CheckType
    status: CheckStatus
    findings: dict
    created_at: datetime


class InvestigationDecision(BaseModel):
    """What the agent proposes for a claim. A proposal, not an authoritative verdict."""

    claim_id: str
    proposed_status: EvidenceReviewStatus
    explanation: str
    evidence_ids: list[str] = []


class DonorUpdateOut(BaseModel):
    id: str
    campaign_id: str
    title: str
    body: str
    evidence_refs: list[str]
    status: PublicationStatus
    approved_by: str | None
    published_at: datetime | None
    created_at: datetime


class OutboundMessageOut(BaseModel):
    id: str
    kind: OutboundKind
    recipient_user_id: str | None
    status: DeliveryStatus
    provider: str | None
    created_at: datetime

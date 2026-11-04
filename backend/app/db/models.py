"""Postgres schema (spec section 5). Shared file: change only by a PR both developers approve.

Money rule: donations_received comes only from PayPal captures. Expense claims are
NGO-reported spending and are never treated as PayPal-confirmed transactions.
"""

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, new_id, utcnow
from contracts.reporting_schemas import (
    CampaignStatus,
    ClaimStatus,
    DeliveryStatus,
    DonationStatus,
    EvidenceReviewStatus,
    EvidenceVisibility,
    InvestigationStatus,
    PublicationStatus,
    ReportingRequestStatus,
)


def _id() -> Mapped[str]:
    return mapped_column(String(32), primary_key=True, default=new_id)


def _created() -> Mapped[datetime]:
    return mapped_column(DateTime, default=utcnow, nullable=False)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = _id()
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    role: Mapped[str] = mapped_column(String(20))
    display_name: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = _created()


class Ngo(Base):
    __tablename__ = "ngos"
    id: Mapped[str] = _id()
    owner_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="active")
    reporting_agreement_accepted_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = _created()


class Campaign(Base):
    __tablename__ = "campaigns"
    id: Mapped[str] = _id()
    ngo_id: Mapped[str] = mapped_column(ForeignKey("ngos.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(50), default="general")
    target_amount_cents: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    expected_activities: Mapped[str] = mapped_column(Text, default="")
    location_coarse: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default=CampaignStatus.DRAFT)
    reporting_frequency_days: Mapped[int] = mapped_column(Integer, default=7)
    next_followup_at: Mapped[datetime | None] = mapped_column(DateTime)
    published_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = _created()


class ReportingPlan(Base):
    __tablename__ = "reporting_plans"
    __table_args__ = (UniqueConstraint("campaign_id", "version"),)
    id: Mapped[str] = _id()
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    proposed_questions_json: Mapped[list] = mapped_column(JSON, default=list)
    evidence_suggestions_json: Mapped[list] = mapped_column(JSON, default=list)
    limitations_json: Mapped[list] = mapped_column(JSON, default=list)
    source: Mapped[str] = mapped_column(String(20), default="template")  # template | ai | ngo
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = _created()


class Donation(Base):
    __tablename__ = "donations"
    id: Mapped[str] = _id()
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id"), index=True)
    donor_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    amount_cents: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    paypal_order_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    paypal_capture_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String(20), default=DonationStatus.CREATED)
    webhook_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = _created()


class WebhookEvent(Base):
    __tablename__ = "webhook_events"
    __table_args__ = (UniqueConstraint("provider", "event_id"),)
    id: Mapped[str] = _id()
    provider: Mapped[str] = mapped_column(String(20))
    event_id: Mapped[str] = mapped_column(String(128))
    event_type: Mapped[str] = mapped_column(String(128))
    payload_json: Mapped[dict] = mapped_column(JSON)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = _created()


class ReportingRequest(Base):
    __tablename__ = "reporting_requests"
    __table_args__ = (UniqueConstraint("campaign_id", "cycle_key"),)
    id: Mapped[str] = _id()
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id"), index=True)
    cycle_key: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(30), default=ReportingRequestStatus.OPEN)
    due_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_reminded_at: Mapped[datetime | None] = mapped_column(DateTime)
    reminder_count: Mapped[int] = mapped_column(Integer, default=0)
    clarification_rounds: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = _created()


class AgentThread(Base):
    __tablename__ = "agent_threads"
    id: Mapped[str] = _id()
    reporting_request_id: Mapped[str] = mapped_column(
        ForeignKey("reporting_requests.id"), unique=True
    )
    graph_thread_id: Mapped[str] = mapped_column(String(64), default=new_id)
    status: Mapped[str] = mapped_column(String(30), default="waiting_for_ngo")
    created_at: Mapped[datetime] = _created()


class AgentMessage(Base):
    __tablename__ = "agent_messages"
    id: Mapped[str] = _id()
    thread_id: Mapped[str] = mapped_column(ForeignKey("agent_threads.id"), index=True)
    sender_role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    meta_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = _created()


class ActivityReport(Base):
    __tablename__ = "activity_reports"
    id: Mapped[str] = _id()
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id"), index=True)
    reporting_request_id: Mapped[str] = mapped_column(ForeignKey("reporting_requests.id"))
    description: Mapped[str] = mapped_column(Text)
    reported_at: Mapped[datetime] = _created()
    review_status: Mapped[str] = mapped_column(String(30), default="in_progress")


class ExpenseClaim(Base):
    __tablename__ = "expense_claims"
    id: Mapped[str] = _id()
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id"), index=True)
    activity_report_id: Mapped[str] = mapped_column(ForeignKey("activity_reports.id"))
    category: Mapped[str | None] = mapped_column(String(50))
    description: Mapped[str] = mapped_column(Text)
    amount_cents: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    expense_date: Mapped[str | None] = mapped_column(String(10))
    amount_uncertain: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default=ClaimStatus.PROPOSED)
    evidence_status: Mapped[str] = mapped_column(String(30), default=EvidenceReviewStatus.REPORTED)
    supported_amount_cents: Mapped[int] = mapped_column(Integer, default=0)
    source: Mapped[str] = mapped_column(String(20), default="ai")  # ai | manual
    created_at: Mapped[datetime] = _created()


class ImpactClaim(Base):
    __tablename__ = "impact_claims"
    id: Mapped[str] = _id()
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id"), index=True)
    activity_report_id: Mapped[str] = mapped_column(ForeignKey("activity_reports.id"))
    description: Mapped[str] = mapped_column(Text)
    quantity: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str | None] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(20), default=ClaimStatus.PROPOSED)
    evidence_status: Mapped[str] = mapped_column(String(30), default=EvidenceReviewStatus.REPORTED)
    source: Mapped[str] = mapped_column(String(20), default="ai")
    created_at: Mapped[datetime] = _created()


class Evidence(Base):
    __tablename__ = "evidence"
    id: Mapped[str] = _id()
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id"), index=True)
    reporting_request_id: Mapped[str | None] = mapped_column(ForeignKey("reporting_requests.id"))
    uploaded_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(30))
    storage_key: Mapped[str] = mapped_column(String(200))
    original_filename: Mapped[str] = mapped_column(String(255))
    file_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    perceptual_hash: Mapped[str | None] = mapped_column(String(32))
    extracted_json: Mapped[dict | None] = mapped_column(JSON)  # what the AI read
    confirmed_json: Mapped[dict | None] = mapped_column(JSON)  # what the NGO confirmed
    visibility: Mapped[str] = mapped_column(String(10), default=EvidenceVisibility.PRIVATE)
    created_at: Mapped[datetime] = _created()


class ClaimEvidence(Base):
    __tablename__ = "claim_evidence"
    __table_args__ = (UniqueConstraint("claim_type", "claim_id", "evidence_id"),)
    id: Mapped[str] = _id()
    claim_type: Mapped[str] = mapped_column(String(10))  # expense | impact
    claim_id: Mapped[str] = mapped_column(String(32), index=True)
    evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence.id"))
    relevance_note: Mapped[str | None] = mapped_column(Text)


class EvidenceCheck(Base):
    __tablename__ = "evidence_checks"
    id: Mapped[str] = _id()
    evidence_id: Mapped[str | None] = mapped_column(ForeignKey("evidence.id"))
    claim_type: Mapped[str | None] = mapped_column(String(10))
    claim_id: Mapped[str | None] = mapped_column(String(32), index=True)
    check_type: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20))
    findings_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = _created()


class Investigation(Base):
    __tablename__ = "investigations"
    id: Mapped[str] = _id()
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id"), index=True)
    claim_type: Mapped[str] = mapped_column(String(10))
    claim_id: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(30), default=InvestigationStatus.OPEN)
    question: Mapped[str] = mapped_column(Text)
    resolution: Mapped[str | None] = mapped_column(Text)
    resolved_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = _created()


class DonorUpdate(Base):
    __tablename__ = "donor_updates"
    id: Mapped[str] = _id()
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id"), index=True)
    reporting_request_id: Mapped[str | None] = mapped_column(ForeignKey("reporting_requests.id"))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    evidence_refs_json: Mapped[list] = mapped_column(JSON, default=list)
    provenance_json: Mapped[list] = mapped_column(JSON, default=list)  # sentence -> claim/evidence ids
    status: Mapped[str] = mapped_column(String(20), default=PublicationStatus.DRAFT)
    approved_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    published_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = _created()


class NotificationSubscription(Base):
    __tablename__ = "notification_subscriptions"
    __table_args__ = (UniqueConstraint("campaign_id", "donor_user_id"),)
    id: Mapped[str] = _id()
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id"))
    donor_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    email_enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[str] = _id()
    donor_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    donor_update_id: Mapped[str] = mapped_column(ForeignKey("donor_updates.id"))
    channel: Mapped[str] = mapped_column(String(20), default="in_app")
    status: Mapped[str] = mapped_column(String(20), default=DeliveryStatus.QUEUED)
    provider: Mapped[str | None] = mapped_column(String(30))
    provider_message_id: Mapped[str | None] = mapped_column(String(128))
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = _created()


class OutboundMessage(Base):
    __tablename__ = "outbound_messages"
    id: Mapped[str] = _id()
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id"), index=True)
    reporting_request_id: Mapped[str | None] = mapped_column(ForeignKey("reporting_requests.id"))
    kind: Mapped[str] = mapped_column(String(30))
    recipient_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    destination: Mapped[str | None] = mapped_column(String(320))
    body: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    approval_status: Mapped[str] = mapped_column(String(20), default="auto_template")
    provider: Mapped[str | None] = mapped_column(String(30))
    provider_action_id: Mapped[str | None] = mapped_column(String(128))
    provider_response_json: Mapped[dict | None] = mapped_column(JSON)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True)
    status: Mapped[str] = mapped_column(String(20), default=DeliveryStatus.QUEUED)
    created_at: Mapped[datetime] = _created()
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)


class RetrievalDocument(Base):
    __tablename__ = "retrieval_documents"
    id: Mapped[str] = _id()
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id"), index=True)
    evidence_id: Mapped[str | None] = mapped_column(ForeignKey("evidence.id"))
    source_type: Mapped[str] = mapped_column(String(30))
    source_id: Mapped[str] = mapped_column(String(32))
    elastic_doc_id: Mapped[str] = mapped_column(String(128))
    access_scope: Mapped[str] = mapped_column(String(30), default="campaign")
    indexed_at: Mapped[datetime] = _created()


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[str] = _id()
    actor_type: Mapped[str] = mapped_column(String(20))  # user | agent | system | paypal
    actor_id: Mapped[str | None] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(80))
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[str] = mapped_column(String(64))
    previous_json: Mapped[dict | None] = mapped_column(JSON)
    new_json: Mapped[dict | None] = mapped_column(JSON)
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()

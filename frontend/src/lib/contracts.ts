// Mirrors contracts/reporting_schemas.py and the FastAPI response models. Keep in sync.

export type Role = "ngo_admin" | "donor" | "reviewer";
export type EvidenceReviewStatus =
  | "reported"
  | "submitted"
  | "consistent"
  | "needs_clarification"
  | "reviewed_by_human"
  | "not_documented";

export interface User {
  id: string;
  email: string;
  role: Role;
  display_name: string | null;
}

export interface Campaign {
  id: string;
  ngo_id: string;
  ngo_name: string;
  title: string;
  description: string;
  category: string;
  target_amount_cents: number;
  currency: string;
  expected_activities: string;
  location_coarse: string | null;
  status: "draft" | "published" | "paused" | "completed";
  reporting_frequency_days: number;
  next_followup_at: string | null;
  donations_received_cents: number;
  donor_count: number;
  reported_expenses_cents: number;
  document_supported_cents: number;
}

export interface Plan {
  id: string;
  version: number;
  source: string;
  approved_at: string | null;
  questions: string[];
  evidence_suggestions: string[];
  limitations: string[];
}

export interface Donation {
  id: string;
  campaign_id: string;
  campaign_title: string;
  amount_cents: number;
  currency: string;
  status: "created" | "captured" | "completed" | "failed" | "refunded";
  paypal_order_id: string | null;
  paypal_capture_id: string | null;
  webhook_confirmed: boolean;
  created_at: string;
}

export interface ReportingRequest {
  id: string;
  campaign_id: string;
  cycle_key: string;
  status: string;
  due_at: string | null;
  clarification_rounds: number;
  created_at: string;
}

export interface Message {
  id: string;
  sender_role: "agent" | "ngo" | "reviewer" | "system";
  content: string;
  meta: Record<string, unknown>;
  created_at: string;
}

export interface Claim {
  id: string;
  campaign_id: string;
  claim_type: "expense" | "impact";
  description: string;
  amount_cents: number | null;
  currency: string | null;
  quantity: number | null;
  unit: string | null;
  status: "proposed" | "reported" | "withdrawn";
  evidence_status: EvidenceReviewStatus;
  supported_amount_cents: number | null;
  evidence_ids: string[];
}

export interface Evidence {
  id: string;
  kind: string;
  original_filename: string;
  file_type: string;
  visibility: "private" | "public";
  extracted: Record<string, unknown> | null;
  confirmed: Record<string, unknown> | null;
  claim_ids: string[];
  created_at: string;
}

export interface Check {
  id: string;
  evidence_id: string | null;
  claim_id: string | null;
  check_type: string;
  status: "pass" | "flag" | "inconclusive";
  findings: Record<string, unknown>;
  created_at: string;
}

export interface Investigation {
  id: string;
  campaign_id: string;
  claim_type: string;
  claim_id: string;
  status: string;
  question: string;
  resolution: string | null;
  created_at: string;
}

export interface Thread {
  request: ReportingRequest;
  campaign_id: string;
  campaign_title: string;
  messages: Message[];
  claims: Claim[];
  evidence: Evidence[];
  checks: Check[];
  investigations: Investigation[];
}

export interface DonorUpdate {
  id: string;
  campaign_id: string;
  title: string;
  body: string;
  evidence_refs: string[];
  status: "draft" | "approved" | "published" | "withdrawn";
  approved_by: string | null;
  published_at: string | null;
  created_at: string;
}

/** One item in a donor update. Amount fields are absent on drafts made before they were added. */
export interface Provenance {
  text: string;
  claim_type: "expense" | "impact" | null;
  claim_id: string | null;
  evidence_status: EvidenceReviewStatus | null;
  evidence_ids?: string[];
  evidence_count?: number;
  description?: string;
  amount_cents?: number;
  supported_cents?: number;
  currency?: string;
  quantity?: number | null;
  unit?: string | null;
}

export interface TimelineEntry {
  update: DonorUpdate;
  provenance: Provenance[];
}

export interface Timeline {
  campaign: Campaign;
  entries: TimelineEntry[];
  totals_note: string;
  reporting_overdue: boolean;
}

export interface NotificationItem {
  id: string;
  donor_update_id: string;
  campaign_id: string;
  title: string;
  channel: string;
  status: string;
  created_at: string;
}

/** Short labels for donors: what the paperwork shows, never "verified". */
export const DONOR_STATUS: Record<EvidenceReviewStatus, { label: string; tone: "good" | "wait" | "plain" }> = {
  consistent: { label: "Documents match", tone: "good" },
  needs_clarification: { label: "Being clarified", tone: "wait" },
  reviewed_by_human: { label: "Reviewed by a person", tone: "good" },
  submitted: { label: "Documents received", tone: "plain" },
  not_documented: { label: "No documents provided", tone: "plain" },
  reported: { label: "Reported, no documents yet", tone: "plain" },
};

export const STATUS_LABEL: Record<EvidenceReviewStatus, string> = {
  reported: "NGO reported, no documents yet",
  submitted: "Evidence received",
  consistent: "Documents consistent with claim",
  needs_clarification: "Clarification pending",
  reviewed_by_human: "Reviewed by a person",
  not_documented: "NGO reported, not documented",
};

export function money(cents: number | null | undefined, currency = "USD"): string {
  return new Intl.NumberFormat("en-US", { style: "currency", currency }).format((cents ?? 0) / 100);
}

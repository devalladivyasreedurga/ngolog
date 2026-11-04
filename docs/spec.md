# NGOLog v3.1 — Claude Code Build Specification

**Updated:** November 4, 2026  
**Hackathon target:** PayPal AI Hackathon, November 12, 2026 submission deadline  
**Product tagline:** *Your donation shouldn't be the end of the story.*  
**Sponsor/tool plan:** PayPal + Elastic + Zapier MCP + AG Grid/AG Studio; Render, APIMatic and Postman support delivery. See Section 14.  
**Authority:** This specification supersedes the milestone-release, escrow and payout portions of the earlier NGOLog plan.

## 1. Product overview

NGOLog is an AI-powered donation transparency platform. NGOs register and create fundraising campaigns describing the cause, goal and expected activities. Donors contribute via PayPal. An AI accountability agent proactively follows up with NGOs, asks how donated funds are being used, requests context-appropriate supporting evidence, examines submitted information for consistency and possible duplication, asks follow-up questions, and publishes accurate campaign-level donor updates after NGO approval or review according to policy.

This is **not an escrow platform**, a milestone-controlled payout product, or an autonomous fraud adjudicator. The AI **does not** move money, certify impact or declare an NGO fraudulent. Fundraising organizations are responsible for their own spending and evidence statements. The product distinguishes NGO-reported claims, document-supported claims, unresolved discrepancies, and independently confirmed facts where such confirmation exists.

### Core promise

Donors can see what the NGO reported doing, which supporting materials were reviewed, what remains uncertain, and the latest updates on the campaign they supported. NGOs receive a lightweight automated reporting assistant instead of a rigid reporting bureaucracy.

### Scope assumptions

- **Campaign-based:** every donation belongs to one campaign; an NGO can run multiple campaigns.
- **No donor-dollar tracing:** show campaign-level allocation and spending, not unsupported claims that a particular $20 purchased a specific item.
- **No mandatory milestones:** campaign goals and reporting cadence replace payout milestones.
- **No conditional disbursements:** NGOLog's core MVP does not use PayPal Payouts, hold money in escrow or promise refunds for failed activities.
- **Sandbox only for demo:** PayPal checkout and captures are demonstrated using sandbox accounts.
- **Reporting agreement:** before publication, each NGO agrees to periodic AI follow-up, applicable evidence requests, and transparent statuses for overdue updates.
- **Privacy:** avoid posting beneficiary identities, medical records or sensitive locations in donor-facing views; NGO controls publication of media.

## 2. Roles

### NGO admin
- Register/login and create/edit/publish campaigns.
- Choose reporting cadence (default: weekly for demo).
- Receive agent messages and reminders inside the application.
- Submit activity summaries, expense amounts, documents, photos and explanations.
- Review proposed expense records and verify extracted values before they are saved.
- View unresolved questions, evidence flags and overdue updates.
- Approve donor-facing summaries and media for publication.

### Donor
- Browse a public campaign, view its purpose and fundraising goal.
- Donate through PayPal sandbox checkout.
- View their donation transaction and **campaign-level** activity/spending timeline.
- See evidence statuses: NGO reported, evidence received, reviewed for consistency, clarification pending, and independently confirmed (only when applicable).
- Opt in/out of email notifications for important updates.

### Platform reviewer (simple admin in MVP)
- Review flagged discrepancies, misleading summaries, or sensitive media.
- Override or correct automated classifications with an auditable reason.
- Publish/hold updates according to policy; cannot silently fabricate or change evidence.

## 3. End-to-end user flows

### Flow A — NGO onboards and starts a campaign
1. NGO signs in.
2. Creates campaign: title, description, target amount, category, expected activities, location at optional coarse granularity, update frequency.
3. AI drafts a *reporting plan* (not milestones) based on category: suggested questions, potentially useful types of evidence, and limitations.
4. NGO edits/accepts reporting plan and publishes the campaign.
5. Public campaign page becomes accessible.

### Flow B — Donor funds the campaign
1. Donor clicks Donate; frontend invokes backend to create PayPal Orders v2 order with campaign metadata.
2. Donor approves in PayPal sandbox.
3. Backend captures payment and stores PayPal order/capture identifiers.
4. Verified webhook updates donation to `completed`; frontend confirmation is not sole source of truth.
5. Donor sees donation receipt and campaign timeline subscription.

### Flow C — Proactive NGO accountability follow-up
1. Scheduler checks campaigns whose `next_followup_at <= now` and aren't paused/completed.
2. Idempotently creates a reporting request and agent thread.
3. Agent asks what has happened since the last report and whether campaign funds have been spent.
4. NGO responds with plain language, e.g. “We bought 25 school supply kits for $375 and distributed 20.”
5. Agent extracts **proposed structured claims**: expense $375, goods 25 kits, reported distribution 20 kits.
6. Agent asks for suitable proof: invoice/receipt or payment confirmation for purchase; aggregate distribution acknowledgment for distribution; alternatives accepted and labeled.
7. NGO uploads evidence or explains why unavailable.
8. Agent evaluates claims and evidence, then requests clarification if necessary.
9. Agent creates a donor-update draft limited to supportable facts; NGO/admin reviews and publishes.
10. Campaign timeline updates; notification sends only for meaningful newly published information.

### Flow D — Investigate inconsistency
1. NGO claims expense of $500.
2. Uploaded receipt appears to show $420.
3. Agent detects $80 discrepancy and asks a focused follow-up.
4. NGO uploads a second $80 receipt or explains that amount was estimated.
5. Agent updates status. If second document matches and there is no other unresolved concern, mark document-supported expense; otherwise mark partially supported and leave discrepancy visible.
6. No automatic declaration of fraud; flagged material can reach reviewer.

### Flow E — No response
1. First request sent.
2. After configured interval, send at most one reminder, then a final follow-up; prevent spam.
3. If unanswered, mark reporting update `overdue` and show “No recent update has been provided” rather than making a negative factual claim about spending.
4. Optional platform review after a longer threshold.

## 4. AI architecture

Build **one LangGraph accountability workflow** with distinct functions; multiple named agents are not needed.

### AI responsibilities
1. **Reporting plan drafting:** suggest sensible questions/evidence by campaign type; NGO can edit.
2. **Conversational reporting:** ask about activities, expenses, dates, quantities and outstanding details.
3. **Claim extraction:** produce schema-validated records from NGO text; require confirmation for uncertain financial amounts.
4. **Evidence interpretation:** extract OCR/vision details from receipts and photos, compare against specific claims, assess missing information, look for possible duplicates.
5. **Investigation:** use retrieval-augmented generation (RAG) over the relevant campaign history and evidence, ask targeted follow-up questions; pause/resume state upon NGO response.
6. **Donor report generation:** produce short plain-language status updates grounded in the stored claims, evidence checks and ledger.

### Tools for LangGraph
- `get_campaign(campaign_id)` — structured campaign details and reporting plan.
- `get_reporting_history(campaign_id)` — previous requests, claims, donor updates.
- `extract_expense_claims(message)` — schema-validated proposed expense/activity records.
- `list_evidence(campaign_id, claim_id)` — stored submissions.
- `inspect_document(evidence_id)` — vision/OCR extracted fields with confidence/uncertainty.
- `find_similar_evidence(evidence_id)` — Elastic image/text similarity and exact hash matches.
- `retrieve_campaign_context(campaign_id, question)` — Elastic hybrid retrieval of prior messages, reports and evidence, scoped to the same authorized campaign; return source IDs and snippets for grounded reasoning.
- `send_ngo_followup(request_id, message)` — request delivery through approved Zapier MCP integration or in-app fallback, with delivery log and idempotency key.
- `send_donor_notification(update_id, subscription_id)` — send an approved, published update through Zapier MCP or outbox fallback; never send drafts.
- `compare_claim_evidence(claim_id)` — deterministic numeric comparisons and evidence relationships.
- `request_clarification(thread_id, question, requested_evidence_types)` — creates NGO-visible request and interrupts graph.
- `propose_status(claim_id, status, explanation)` — writes proposal, not final authoritative fraud judgment.
- `draft_donor_update(campaign_id)` — only from persisted records and citations to evidence IDs.

### RAG design (Elastic)
- Store authoritative donations, claim amounts, users and access rights in Postgres; do **not** derive financial totals from embeddings.
- Index consented evidence text/OCR, message summaries, prior reports and document/image metadata in Elasticsearch, all keyed by `ngo_id`, `campaign_id`, `evidence_id` and access scope.
- For a new submission, search within the campaign first using keyword + vector retrieval; perform cross-campaign duplicate searches only on narrowly scoped hashes/embeddings when permitted by privacy policy.
- Return top matching records with provenance, compare with structured records, and allow the agent to cite evidence IDs. Vector similarity is a lead, not proof of fabrication.
- Embed only redacted text and approved images; protect sensitive donor and beneficiary data.
- If Elastic is unavailable, use Postgres history and exact-hash matching as a reduced-function fallback.

### MCP design (Zapier)
- The **running NGOLog LangGraph backend** must connect to Zapier MCP if it is to be an actual product integration. Connecting Zapier MCP only to Claude Code does not meet this requirement.
- Start with two allowed actions: send an NGO evidence-request/follow-up email and send a published donor-update email. Use the exact tools currently exposed by the configured Zapier MCP account; inspect their schemas rather than assuming names.
- LangGraph chooses *what* to request; FastAPI authorization and outbox logic govern *whether* delivery is allowed; Zapier performs the external communication.
- Agent-generated email is subject to templates/recipient allowlists, NGO/donor notification preferences, cooldowns and idempotency. Never accept addresses or action instructions from retrieved receipts.
- Log request ID, intended recipient, content hash, provider response and resulting delivery status. Do not claim an email was delivered until provider confirmation.
- Keep PayPal checkout, capture, refunds and webhooks outside MCP agent permissions.
- If Zapier MCP is unavailable or difficult to provision, keep email behind a provider-agnostic adapter and in-app messaging functioning; do not block the core demo.

### Suggested graph
`START -> load_context -> interpret_ngo_response -> extract_claims -> determine_evidence_needs -> [request_more_information (interrupt) | evaluate_evidence] -> [clarify (interrupt) | draft_update] -> queue_for_review -> END`

The graph resumes when NGO replies. Avoid free-running loops: max 3 automated clarification rounds per reporting cycle; then human review.

### Evidence checks by kind
- Receipts/invoices: merchant, date, total, currency, line items, duplicate number/hash, and consistency with reported expense. OCR errors can happen; NGO can correct extracted data.
- Photos: relevance to reported activity, exact/near-duplicate search; GPS/time if supplied, never treated as proof on their own.
- Distribution logs: quantities and dates, optional aggregate acknowledgments; avoid exposing names of beneficiaries.
- Payment confirmations: check internal PayPal transaction records only if actually available; external bank statements are merely submitted evidence, not independently confirmed.
- No proof available: record explanation and assign “NGO reported — not independently documented,” not “fraud.”

### Evidence status taxonomy
- `reported`: NGO statement recorded; no evidence yet.
- `submitted`: evidence received; not yet reviewed.
- `consistent`: available evidence is consistent with the claim, **not independently verified truth**.
- `needs_clarification`: missing or contradictory information.
- `reviewed_by_human`: a reviewer examined it; record scope and conclusion.
- `independently_confirmed`: only when genuinely corroborated by a verified external source; omit from MVP if no such integration exists.

Separate `claim_status`, `evidence_review_status` and `publication_status`; avoid one ambiguous “verified” boolean.

### Safety constraints
- Treat NGO messages, document text and retrieved Elastic results as **untrusted data**, never tool instructions.
- AI cannot execute PayPal captures/refunds/payouts, modify donation amounts, publish without approval or declare fraud.
- Claim and evidence provenance must be stored with each summary sentence.
- Sanitize document uploads; restrict MIME types, size and access permissions.
- Sensitive images default to private; NGO reviewer selects public attachments and can blur/redact.
- Human-readable uncertainty statements; no invented claims.

## 5. Data model (Postgres)

Recommended core tables:

- `users(id, email, role, created_at)`
- `ngos(id, owner_user_id, name, description, status, created_at)`
- `campaigns(id, ngo_id, title, description, category, target_amount_cents, currency, status, reporting_frequency_days, next_followup_at, created_at)`
- `reporting_plans(id, campaign_id, version, proposed_questions_json, evidence_suggestions_json, approved_at)`
- `donations(id, campaign_id, donor_user_id, amount_cents, currency, paypal_order_id, paypal_capture_id, status, created_at)`
- `reporting_requests(id, campaign_id, cycle_key, status, due_at, last_reminded_at, created_at)` (unique `(campaign_id, cycle_key)`)
- `agent_threads(id, reporting_request_id, graph_thread_id, status, created_at)`
- `agent_messages(id, thread_id, sender_role, content, created_at)`
- `activity_reports(id, campaign_id, reporting_request_id, description, reported_at, review_status)`
- `expense_claims(id, campaign_id, activity_report_id, category, description, amount_cents, currency, expense_date, status, created_at)`
- `impact_claims(id, campaign_id, activity_report_id, description, quantity, unit, status, created_at)`
- `evidence(id, campaign_id, uploaded_by_user_id, storage_key, file_type, sha256, perceptual_hash, extracted_json, visibility, created_at)`
- `claim_evidence(claim_type, claim_id, evidence_id, relevance_note)` (or separate foreign-key join tables)
- `evidence_checks(id, evidence_id, claim_type, claim_id, check_type, status, findings_json, created_at)`
- `investigations(id, campaign_id, claim_type, claim_id, status, question, resolution, created_at)`
- `donor_updates(id, campaign_id, title, body, evidence_refs_json, status, approved_by, published_at, created_at)`
- `notification_subscriptions(id, campaign_id, donor_user_id, email_enabled)`
- `notifications(id, donor_user_id, donor_update_id, channel, status, provider, provider_message_id, idempotency_key, sent_at)`
- `outbound_messages(id, campaign_id, reporting_request_id, kind, recipient_user_id, destination, body, approval_status, provider, provider_action_id, idempotency_key, status, created_at, sent_at)`
- `retrieval_documents(id, campaign_id, evidence_id, source_type, source_id, elastic_doc_id, indexed_at, access_scope)`
- `webhook_events(id, provider, event_id, event_type, payload_json, processed_at)` (unique `(provider, event_id)`)
- `audit_log(id, actor_type, actor_id, action, entity_type, entity_id, previous_json, new_json, created_at)`

**Financial reporting semantics:** PayPal captures support `donations_received`; `expense_claims` are NGO-reported spending. Display two distinct totals and never treat unverified expense claims as PayPal-confirmed transactions. Campaign funds remaining based on reported expenses should be labeled as an **estimate**, not a confirmed account balance.

## 6. API surface (FastAPI)

### Authentication and campaigns
- `POST /api/ngos`
- `GET /api/ngos/me`
- `POST /api/campaigns`
- `GET /api/campaigns`
- `GET /api/campaigns/{id}`
- `PATCH /api/campaigns/{id}`
- `POST /api/campaigns/{id}/publish`
- `POST /api/campaigns/{id}/reporting-plan/draft`
- `PUT /api/campaigns/{id}/reporting-plan`

### PayPal
- `POST /api/campaigns/{id}/paypal/orders`
- `POST /api/paypal/orders/{order_id}/capture`
- `POST /api/paypal/webhook`
- `GET /api/donations/mine`

### Reporting and AI
- `GET /api/campaigns/{id}/reporting-requests`
- `POST /api/campaigns/{id}/reporting-requests/trigger` (demo/admin only)
- `GET /api/reporting-requests/{id}/thread`
- `POST /api/reporting-requests/{id}/messages` (resume agent)
- `POST /api/evidence/upload` (authenticated, role-restricted)
- `GET /api/campaigns/{id}/claims`
- `GET /api/campaigns/{id}/investigations`
- `POST /api/investigations/{id}/resolve` (reviewer)

### Donor updates
- `GET /api/campaigns/{id}/timeline` (published only)
- `POST /api/campaigns/{id}/updates/draft`
- `POST /api/updates/{id}/approve`
- `POST /api/updates/{id}/publish`
- `POST /api/campaigns/{id}/notifications/subscribe`

### Jobs and operations
- Scheduled job `run_due_followups`: selects due campaigns, creates one reporting request per cycle, generates agent opening message, updates next follow-up.
- Scheduled job `send_reminders`: idempotent, rate-limited reminders and overdue transitions.
- Outbox worker: emails and donor notifications after update publication; retry-safe.

## 7. Pages and UI

### Public
- `/` — campaign discovery
- `/campaigns/[id]` — purpose, amount raised, donate button, published transparency timeline
- `/campaigns/[id]/updates/[updateId]` — full donor update, privacy-safe evidence links

### Donor
- `/donor/dashboard` — donations, subscribed campaigns, recent notifications
- `/donor/donations/[id]` — PayPal receipt reference and campaign-level timeline

### NGO
- `/ngo/dashboard` — campaigns, next update due, open agent questions
- `/ngo/campaigns/new` — campaign editor + AI reporting-plan draft
- `/ngo/campaigns/[id]/reporting` — conversation with agent, uploads, structured claims
- `/ngo/campaigns/[id]/expenses` — AG Grid claimed expenses, evidence status, notes
- `/ngo/campaigns/[id]/updates` — draft, approve and publish donor updates

### Platform admin
- `/admin/investigations` — AG Grid of flagged evidence/discrepancies, filter and review
- `/admin/accountability` — AG Grid operational console: overdue follow-ups, evidence gaps, pending approvals, investigation history; AG Studio widgets only if feasible with its current documented SDK

## 8. Demo narrative (3 minutes)

Use a **single school-supplies campaign** and prepared legitimate test data.

1. **0:00–0:25** — NGO creates campaign: “Supply 50 students with school kits.” AI drafts lightweight reporting questions and suggestions for invoices/distribution confirmation.
2. **0:25–0:50** — Donor funds through PayPal sandbox. A recorded capture updates campaign totals.
3. **0:50–1:20** — Trigger scheduled NGO follow-up in demo mode; agent asks for spending/progress update. NGO says “We bought 25 kits for $500.”
4. **1:20–1:55** — NGO uploads a receipt totaling $420. Agent catches the $80 discrepancy and asks a targeted question.
5. **1:55–2:20** — NGO uploads a second $80 receipt. Agent recomputes evidence support and records the reconciliation, without claiming independent real-world verification.
6. **2:20–2:45** — NGO reviews/publishes update; donor timeline changes to show $500 reported/document-supported spending, receipts reviewed and a separate claim about distribution if any.
7. **2:45–3:00** — Show notification and the accountability dashboard; tagline.

Also seed an overdue reporting request to show what happens when an NGO stops replying; this can appear briefly in the dashboard without extending the main narrative.

## 9. Build plan — two developers / two Claude Code sessions

### Ownership
**Developer A: foundation, money, product UI**
- Database/schema and migrations, authentication, campaigns, PayPal Orders/capture/webhooks, NGO/donor pages, campaign ledger, reporting dashboard and deployment.

**Developer B: accountability AI**
- LangGraph flow, reporting plan, claim extraction, evidence upload/analysis, Elastic duplicate checks, follow-up scheduling, investigation, donor-update drafting.

Shared contracts are agreed before implementation. Separate branches and PR reviews for shared schema/API changes. Root `CLAUDE.md` explains project, file ownership, constraints and commands. CI runs migrations and core tests.

### Sponsor-tool priorities
- **Core runtime:** PayPal sandbox Orders/capture/webhooks; Elastic RAG; Zapier MCP for email follow-ups and donor updates; AG Grid for the accountability console.
- **AG Studio:** aspirational enhancement for an agent-assisted dashboard/sponsor entry, contingent on the current framework documentation and time. It is not interchangeable with basic AG Grid.
- **Development/deployment:** APIMatic for PayPal API context in Claude Code, Postman collection for integration verification, Render for the hosted demo. These are not AI runtime dependencies.
- **Skip:** Astropods, Bryntum, Channel3 and KERNEL unless later genuinely required. Avoid sponsor integration for its own sake.

### Priorities
**P0: must be functioning before extra features**
1. Campaign creation and publication.
2. Real PayPal sandbox donation flow with capture webhook, idempotency and persistence.
3. NGO agent thread: reporting request, response, and single follow-up when evidence is missing.
4. Basic evidence upload and deterministic receipt-vs-claim amount check.
5. Draft/approve/publish donor update and living campaign timeline.

**P1: standout capabilities**
6. LangGraph interrupt/resume and multi-step investigation.
7. Elastic near-duplicate image/doc search with source references.
8. Proactive scheduler and reminders; meaningful donor notifications via Zapier MCP adapter.
9. AG Grid review console and audit trail; optional AG Studio custom widgets.

**P2: stretch only**
10. More campaign categories, phone-camera flows, advanced geolocation checks, external-source integrations, personalized narrative summaries, offline support.

### Suggested daily checkpoints
- **Nov 4:** repo setup, contracts, DB, auth; PayPal sandbox readiness; skeleton campaign and agent API.
- **Nov 5:** campaign creation, checkout/capture/webhook; basic NGO conversation and claims extraction.
- **Nov 6:** evidence upload and receipt extraction; compare amounts; first donor timeline.
- **Nov 7:** LangGraph ask/resume, flags, NGO update approval; demonstrate entire main story once.
- **Nov 8:** scheduled follow-ups, reminders, notification outbox; Elastic RAG and duplicate retrieval; integrate Zapier MCP through a narrow delivery adapter.
- **Nov 9:** AG Grid investigation console (AG Studio only if stable), QA, mobile polish; feature freeze.
- **Nov 10:** deploy public demo, demo seed accounts, security/idempotency tests, README.
- **Nov 11:** record under-three-minute video, finalize submission, verify judge access.
- **Nov 12:** buffer before official deadline; do not depend on last-minute new features.

## 10. Technical rules and acceptance tests

- No success screen means a donation was captured unless server confirms it; webhook processing is idempotent.
- User may not manipulate another NGO's campaign or view private evidence via ID enumeration.
- Only authorized NGO/platform reviewer can publish a donor update.
- A donor-facing update cannot cite evidence IDs not attached to the campaign or not approved for public use.
- If receipt total is $420 and expense claim $500, agent requests clarification and cannot classify the whole $500 as document-supported.
- If second valid $80 document arrives, the matching total updates (but no claim that purchased supplies were delivered).
- If NGO provides no evidence, platform can still show an NGO-reported statement with clear label.
- Repeated scheduled job or webhook processing creates no duplicate request, capture, notification or update.
- If AI provider fails, NGO can manually submit expense report and human reviewer can publish transparently labeled update.
- If Elastic fails, evidence flow degrades to basic hash/structured checks rather than blocking all reporting.
- If notification provider fails, published timeline still updates; notification can retry.
- All demo documents, photos and identities are fictional or owned/licensed and visibly demo data.

## 11. Suggested repository structure

```text
ngolog/
  CLAUDE.md
  .env.example
  docker-compose.yml
  README.md
  contracts/
    api.openapi.yaml
    reporting_schemas.py
  frontend/
    app/
    components/
    lib/
  backend/
    app/
      main.py
      auth/
      campaigns/
      payments/
      reporting/
      agent/
      evidence/
      notifications/
      admin/
      db/
    tests/
  scripts/
    seed_demo.py
  integrations/
    zapier_mcp_adapter.py
    elastic_retrieval.py
  docs/
    architecture.md
    decisions.md
    demo-script.md
```

## 12. Starter prompt to paste into Claude Code

```text
You are the lead engineer for NGOLog v3, an AI-powered donation transparency platform being built for the PayPal AI Hackathon. Read the NGOLog_v3_Claude_Code_Build_Spec.md file completely and treat it as the product source of truth. We have two development lanes, but begin by establishing shared contracts and a runnable end-to-end foundation.

Critical requirements:
- NGOs create fundraising campaigns; donors contribute through PayPal sandbox Orders v2.
- No mandatory milestones, escrow, conditional payouts, or AI-initiated money movement.
- The agent proactively asks NGOs about activities/spending, adapts evidence requests to each reported activity, checks supporting materials, follows up on inconsistencies, and drafts accurate donor updates.
- Donor updates are campaign-level, not claims of precise tracing of each donor's individual dollars.
- Distinguish NGO-reported statements, evidence-consistent claims, and independently verified facts. Never claim that LLM image analysis proves a real-world outcome.
- Public donor-facing updates require explicit NGO/reviewer approval.
- Prefer implementable solutions over unnecessary abstractions; keep the November 12 deadline in mind.
- Sponsor stack: PayPal Orders/capture/webhooks; Elastic for evidence RAG and duplicate retrieval; Zapier MCP for approved NGO follow-up/donor emails; AG Grid for investigation dashboard, with AG Studio only if current docs and time permit; Render deployment; APIMatic and Postman for development/testing.
- MCP must be called by the running LangGraph backend, not merely by Claude Code. PayPal writes remain direct FastAPI integrations. RAG responses must cite retrieved evidence IDs; financial totals must come from Postgres.

First, inspect the repository; don't overwrite existing code. Then:
1. Summarize what already exists and what is missing against the spec.
2. Propose a minimal vertical slice and responsibility split, with exact folders/contracts.
3. Create or update CLAUDE.md, .env.example, README, DB migrations, shared schemas and API contracts.
4. Implement a working local vertical slice: campaign creation -> PayPal sandbox order/capture/webhook -> NGO reporting request/response -> an expense claim and uploaded receipt -> discrepancy detection -> donor-update draft/approval -> donor timeline.
5. Add idempotency, authorization and validation tests.
6. Add an Elastic retrieval adapter and a Zapier MCP communications adapter (with graceful fallback); create an AG Grid accountability view.
7. Produce exact run commands and a list of PayPal/AI/MCP/Elastic/environment credentials still needed.

Do not fabricate external API capabilities. Check current official PayPal SDK/API docs when needed. No mocked payment success in the main demo path. Stop and report any blocked credentials or permissions; implement a clearly marked local test mode only where essential. Commit in small, reviewable steps.
```

## 13. Final demo pitch

> **NGOLog — Your donation shouldn't be the end of the story.**
>
> Most donation experiences end at checkout. NGOLog keeps the story going. NGOs fundraise through PayPal while an AI accountability agent follows up, asks how funds are being used, requests suitable evidence, investigates inconsistencies, and helps publish trustworthy campaign updates. Donors get a living timeline of what the organization reports, what its evidence supports, and what still needs clarification.


## 14. Final sponsor integrations and prize strategy (November 4 update)

**PayPal is the primary hackathon platform**, while the other names below are sponsor resources. The goal is a coherent product, not the maximum number of brand integrations.

| Tool | Role in NGOLog v3.1 | Integration location | Priority |
|---|---|---|---|
| **PayPal** | Campaign donation checkout, captures, verified webhooks, transaction receipts | FastAPI payments service | P0 |
| **Elastic** | RAG over NGO reports, prior conversations and evidence; duplicate/near-duplicate detection | Evidence/search backend + agent retrieval tool | P1, but essential for RAG demo |
| **Zapier MCP** | Deliver AI-crafted NGO follow-up requests and approved donor update notifications | Running LangGraph service via controlled MCP adapter | P1, core sponsor demonstration |
| **AG Grid** | Accountability/review tables with filtering, row expansion, evidence state and reporting overdue status | NGO/admin Next.js console | P1 |
| **AG Studio** | Optional agent-assisted analytic widgets and custom dashboard experience | NGO/admin frontend, contingent on SDK capabilities | P2 sponsor enhancement |
| **Render** | Host public frontend/backend and background worker; keep demo reachable for judging | Deployment infrastructure | P0 for final demo |
| **APIMatic** | Provide API references/context while implementing PayPal; not a production dependency | Claude Code development workflow | Development tool |
| **Postman** | Store and run repeatable PayPal/backend/webhook tests; export collection for reviewers | Repository `postman/` | Development tool |

**Not planned:** Astropods, Bryntum, Channel3, KERNEL. Use only if a clear product need emerges.

### Prize targets
- **Primary general awards:** Most Impactful, Best Use of PayPal + AI, and Best Demo Delivery. Do not imply eligibility or a guaranteed win.
- **Primary sponsor target:** Best Use of AG Grid, **if** the real implementation uses the sponsor's qualifying capabilities. Confirm whether AG Studio is required for the selected award tier.
- **Secondary sponsor opportunity:** Best Use of APIMatic, only if use satisfies the current challenge terms.
- Follow the official category, eligibility and multiple-prize limits at submission; this document is a strategy, not an eligibility ruling.

### Why each sponsor is visible in the demo
1. **PayPal:** donor completes a real sandbox order; webhook-confirmed capture is recorded.
2. **Elastic:** agent retrieves a prior receipt/report with source reference and detects a genuine discrepancy.
3. **Zapier MCP:** running agent sends an authorized targeted follow-up email; NGO replies in the application (avoid promising incoming-email ingestion unless actually built).
4. **AG Grid:** reviewer sees unresolved claims, evidence, reporting requests and state changes.
5. **Render:** live hosted application accessible to judges.
6. **APIMatic/Postman:** README documents tools used for API development and test collection; no need to force them into user-facing scenes.

### Minimal working sponsor demo (don't overbuild)
NGO creates school-supplies campaign → donor pays via PayPal sandbox → scheduled accountability request → NGO reports $500 spent → uploads a $420 receipt → Elastic retrieves earlier evidence/context → agent asks about $80 gap via Zapier MCP → NGO provides supporting explanation or second receipt → agent updates evidence consistency status → reviewer publishes accurate donor report → AG Grid row and donor timeline update → notification is sent.

### Essential acceptance checks for sponsor integrations
- **PayPal:** captured amount, campaign mapping, verified webhook signature, repeat-event idempotency, no false success claims.
- **Elastic/RAG:** retrieval returns source IDs, respects NGO/campaign access control, and doesn't treat similarity as fraud proof.
- **Zapier MCP:** actual runtime MCP tool call is logged; recipient authorization, duplicate suppression, publication approval and provider failures tested.
- **AG Grid:** real data-backed filters, expandable evidence trail, and review actions—not a static screenshot.
- **Render:** public demo works after cold start; required workers/schedules and credentials persist through judging.

## 15. Two-lane build coordination and immediate actions

**Developer A — platform & experience:** PayPal integration, Postgres migrations, campaign/donation frontend, AG Grid accountability console, Render, API tests.

**Developer B — agent & evidence:** LangGraph, vision/OCR extraction, Elastic hybrid RAG and duplicate search, controlled Zapier MCP delivery adapter, follow-up/notification pipeline.

**Shared contract to finalize first:** `ReportingRequest`, `Claim`, `EvidenceCheck`, `InvestigationDecision`, `DonorUpdate`, and `OutboundMessage` schemas; agree on exact ID fields, enums, access rules and statuses. The agent proposes records and communications; server policies authorize publication and sending.

**Build order:** P0 vertical slice (PayPal + campaign + one reporting/receipt discrepancy + donor timeline) → Elastic RAG → Zapier MCP delivery → AG Grid review console → demo polish → optional AG Studio. If deadlines slip, keep the P0 vertical slice working and degrade integrations gracefully rather than substituting fake success.

### Additional environment variables (names are examples; verify provider docs)
```env
PAYPAL_CLIENT_ID=
PAYPAL_CLIENT_SECRET=
PAYPAL_WEBHOOK_ID=
ELASTIC_URL=
ELASTIC_API_KEY=
EMBEDDING_MODEL=
ZAPIER_MCP_SERVER_URL=
ZAPIER_MCP_AUTH_TOKEN=
NOTIFICATION_FROM_EMAIL=
PUBLIC_APP_URL=
```
Never commit secrets, authenticate OAuth/MCP transports using the provider's current supported method, and avoid inventing SDK method names before checking official documentation.

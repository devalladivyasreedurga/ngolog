# Decisions log

Newest first. One line of decision, one line of why.

## 2026-11-04

- **Solo build:** the two-developer split is dropped; scope ordered by judging value (Render, LangGraph, Elastic, AG Grid first; Zapier MCP is stretch).
- **LangGraph runs one thread per reporting request**, paused at `await_ngo` and resumed by API events; checkpoints in Postgres (prod) or SQLite (local). The graph auto-drafts a donor update once every confirmed claim is settled and withdraws stale unpublished drafts.
- **Elastic is optional at runtime:** every search is filtered to one campaign; cross-campaign checks only match exact receipt numbers within the same NGO. If Elastic is unset or errors, a Postgres keyword fallback answers instead and the check records which backend was used.
- **Receipts flagged as exact duplicates or reused receipt numbers are never counted** toward a claim; the agent asks instead.
- **v3.1 spec replaces the milestone/escrow plan.** No Payouts, escrow, refunds-on-failure or automated fraud verdicts. Earlier planning docs are historical only.
- **Donation counts as received once the server-side capture returns COMPLETED (`captured`); the verified webhook upgrades it to `completed`.** The capture response comes from PayPal to our server, not from the browser, so it satisfies "frontend is not the source of truth", and local demos work without a public webhook URL. The donor page shows whether the webhook confirmed it.
- **P0 agent runs as plain step functions in `app/agent/workflow.py`, named after the spec's graph nodes.** LangGraph (P1) will wrap the same functions with interrupt/resume; doing it first would have delayed the end-to-end slice.
- **Donor-update text is a deterministic template over stored claims and checks**, with per-sentence provenance. An LLM may polish wording later, but only if every sentence still maps to a stored claim.
- **Claims extracted by AI start as `proposed`; only NGO-confirmed claims are `reported`** and only reported claims are compared, drafted or counted in totals.
- **Receipt values: AI-read (`extracted_json`) and NGO-entered (`confirmed_json`) are both stored**; NGO values win for comparison, and a difference is logged as an extraction flag.
- **Duplicate receipts (same file hash or same receipt number on one claim) are counted once and trigger a question**, never a fraud label.
- **Clarification cap: 3 automated questions per reporting cycle, then `escalated` to a reviewer.**
- **Auth is demo passwordless sign-in with HMAC-signed tokens**; reviewer role only for `REVIEWER_EMAILS`. Replace before any real use.
- **SQLite for local dev and tests, Postgres on Render**, same SQLAlchemy models and Alembic migrations (`render_as_batch` for SQLite).
- **Claude model `claude-opus-5-5`** with structured outputs and server-side refusal fallback (`fallbacks: "default"`). Without `ANTHROPIC_API_KEY` the app runs in manual mode.

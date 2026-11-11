# NGOLog: Devpost submission text

Copy these into the Devpost form. Replace nothing in angle brackets until you have the real value.

## Tagline

Your donation shouldn't be the end of the story.

## Inspiration

Most donation experiences end at checkout. Donors hear nothing, or get a generic thank-you, and small NGOs can't afford staff or audits to report back in detail. NGOLog gives donors a living, honest timeline of what the organization reports doing with campaign funds, which documents support it, and what is still being clarified.

## What it does

- An NGO creates a campaign and accepts an AI-drafted reporting plan (not milestones, not escrow).
- Donors give through PayPal. The server creates and captures the order, and a signature-verified webhook confirms it.
- An AI accountability assistant follows up with the NGO on a schedule, asks how funds were used, turns the NGO's plain-language reply into proposed expense and activity claims, and asks for suitable evidence.
- Receipts are read by Claude; plain code (not the model) compares them with the claim. A $500 claim against a $420 receipt opens a focused question about the $80 gap. A second receipt reconciles it.
- The assistant drafts a donor update from stored records only. The NGO approves and publishes it. Donors see a campaign-level timeline with separate figures for PayPal-confirmed donations, NGO-reported spending, and spending matched by reviewed documents.
- If an NGO goes quiet, the timeline says "No recent update has been provided". It never says anything negative about the spending itself.
- A reviewer console (AG Grid) shows claims, gaps, evidence trails, open questions and overdue requests.

What it deliberately does not do: hold or release funds, move money after checkout, or call anyone a fraudster. Every status uses precise wording ("consistent", "needs clarification", "reviewed by a person"), and AI similarity or discrepancy flags are leads, never verdicts.

## How we built it

| Tool | What it does in NGOLog |
|---|---|
| **PayPal** Orders v2, JS SDK v6, Webhooks (sandbox) | Donate button, server-side order creation and capture with PayPal-Request-Id idempotency, signature-verified webhook confirmation that is idempotent per event |
| **Claude** (`claude-opus-5-5`) | Drafts the reporting plan, extracts structured claims from NGO messages, and reads receipt images, all through schema-validated structured outputs. Model output is only ever a proposal |
| **LangGraph** | One graph thread per reporting request, paused while waiting for the NGO and resumed on each NGO action, with checkpoints in Postgres so it survives restarts |
| **Elastic** | Retrieval adapter that searches a campaign's earlier reports and receipt summaries (hybrid keyword and semantic when an inference endpoint is configured) and flags reused receipt numbers within one NGO. The hosted demo runs on the built-in Postgres fallback; connect a cluster with `ELASTIC_URL` |
| **AG Grid** (Community) | Accountability console: claims, gaps, evidence status, evidence trail, reporting requests, reviewer actions |
| **Render + Neon** | Free-tier hosting for the API and website; Neon free Postgres for the database |
| **Postman** | Collection in `postman/` with the PayPal sandbox calls and the NGOLog API flow |

Backend: FastAPI, SQLAlchemy, Alembic. Frontend: Next.js 16. 38 automated tests cover the main story plus idempotency, authorization, privacy and labelling rules.

## Challenges

Keeping the AI honest: totals come from Postgres, comparisons are deterministic, drafts are templated over stored claims with per-sentence provenance, and extracted text is treated as untrusted data, never as instructions.

## What we learned

Making AI useful in a trust product mostly means constraining it: it proposes, people and plain code decide, and every status says exactly what it does and doesn't prove.

## What's next

Zapier MCP email delivery of follow-ups and donor updates, a live Elastic cluster, near-duplicate photo search, and routing money through a registered charity (holding donations against conditions has legal implications).

## Built with

PayPal, Claude, LangGraph, Elastic, AG Grid, FastAPI, Next.js, PostgreSQL, Render, Neon, Postman

## Links to add

- Try it: https://ngolog-web.onrender.com
- Code: <public GitHub URL>
- Video: <YouTube URL>

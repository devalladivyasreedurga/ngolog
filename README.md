# NGOLog

**Your donation shouldn't be the end of the story.**

NGOLog is an AI-powered donation transparency platform built for the PayPal AI Hackathon. NGOs run campaigns,
donors give through PayPal, and an AI accountability assistant follows up with the NGO about how funds were used,
asks for suitable evidence, checks documents for consistency, asks about discrepancies, and drafts campaign-level
donor updates. Nothing reaches donors until the NGO approves it.

NGOLog does **not** hold funds, release payouts or declare fraud. "Consistent" means documents match what the NGO
reported; it is not an audit.

## Try it (for judges)

**Live demo:** https://ngolog-web.onrender.com (API: https://ngolog-api.onrender.com)

The demo runs on free hosting, so after idle time the first load can take up to a minute while the services wake. Everything runs against the PayPal **sandbox** only; no real money moves.

1. **Donor:** open `/signin` and click **Demo donor**, open *Supply 50 students with school kits*, click the PayPal **Donate** button and pay with any PayPal sandbox personal (buyer) account. Create one at developer.paypal.com under Sandbox → Accounts if you don't have one. The campaign total updates from the server-side capture, and *My donations* shows whether PayPal's signed webhook confirmed it.
2. **NGO:** (updates only start once a campaign has a donation, so do step 1 first) sign out, click **Demo NGO**, open **Reporting** on the campaign and press **Start an update now**. Reply in plain words (for example "We bought 25 kits from Demo Stationers for $500 and handed out 20."), confirm the proposed claims, then upload the fictional receipts from `scripts/demo_assets/` (`receipt-420.png`, then `receipt-80.png`; use `rehearsal-receipt-420.png` and `rehearsal-receipt-80.png` for a practice run, because a receipt number already submitted by the same NGO is flagged and not counted again). The $420 receipt raises a question about the $80 gap; the $80 receipt reconciles it and a donor update is drafted. Click **Review the draft** to see exactly what donors will see, then **Publish to donors**.
3. **Public timeline:** the campaign page shows the published update as cards, with donations received, reported spending and spending matched by receipts kept separate. Tap the small ⓘ next to each number for what it means.
4. **Reviewer:** on `/signin` choose *Platform reviewer* with the email `reviewer@ngolog.org` to open the **Accountability** console (AG Grid) and see every campaign, open question and overdue request. The *Restock the village reading room* campaign is seeded as overdue.

What NGOLog does not do, on purpose: it holds no funds, pays no one, and never declares anyone fraudulent. "Consistent" means the documents match what the NGO reported, not that anything was audited.

Known limits of the free demo: uploaded receipt files are cleared when the server restarts (the amounts, claims and checks are kept in the database), and Elastic search runs through its built-in Postgres fallback unless `ELASTIC_URL` is set.

## What works today (P0 vertical slice)

1. NGO creates a campaign; a reporting plan is drafted (Claude, or a template in manual mode), edited and accepted, then the campaign is published.
2. Donor gives through the PayPal JS SDK v6 Donate button. The backend creates and captures a PayPal Orders v2 order (with `PayPal-Request-Id` idempotency) and records the capture; a verified `PAYMENT.CAPTURE.COMPLETED` webhook confirms it.
3. The assistant opens a reporting request (idempotent per cycle) and asks for a spending update.
4. NGO replies in plain words; Claude extracts proposed expense/activity claims for the NGO to confirm (or the NGO enters them by hand).
5. NGO uploads receipts; Claude reads the totals (or the NGO types them). A deterministic check compares documents to the claim: $500 reported vs a $420 receipt opens a focused $80 question.
6. A second $80 receipt reconciles the claim. The donor update draft is built only from stored records, with per-sentence provenance.
7. NGO approves and publishes; the public campaign timeline and donor notifications update.

Backend tests cover the full story plus idempotency, authorization, privacy and labelling rules (`backend/tests`).

## Run locally

Requirements: Python 3.12+, Node 20+.

```bash
cp .env.example .env            # add PayPal sandbox + Anthropic keys
cd backend
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:app --port 8000
```

```bash
cd frontend
echo "NEXT_PUBLIC_API_URL=http://localhost:8000" > .env.local
echo "NEXT_PUBLIC_PAYPAL_CLIENT_ID=<sandbox client id>" >> .env.local
npm install && npm run dev       # http://localhost:3000
```

Run tests: `cd backend && .venv/bin/python -m pytest -q`

Sign in at `/signin` with the demo NGO or demo donor buttons (passwordless demo auth).

Load the demo story: `backend/.venv/bin/python scripts/seed_demo.py`. It creates demo accounts, the school-supplies campaign, an overdue campaign and fictional receipts in `scripts/demo_assets/`. It creates no donations; demo money is always a real sandbox capture. Set `REVIEWER_EMAILS=reviewer@ngolog.org` to use the reviewer account.

### PayPal sandbox setup

1. developer.paypal.com → Apps & Credentials → Sandbox → create an app; copy the client ID and secret into `.env` (`PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`) and the client ID into `frontend/.env.local`.
2. Add a webhook to the app pointing at `<public backend URL>/api/paypal/webhook` with event `PAYMENT.CAPTURE.COMPLETED`; copy its ID into `PAYPAL_WEBHOOK_ID`. Locally, expose the backend with a tunnel (e.g. ngrok). Without the webhook, donations still record from the server-side capture and show "webhook pending".
3. Pay with a sandbox personal (buyer) account from Sandbox → Accounts.

Without `ANTHROPIC_API_KEY` the app runs in manual mode: the NGO enters claims and receipt totals by hand.

## Tools

| Tool | Role |
|---|---|
| PayPal Orders v2, JS SDK v6, Webhooks (sandbox) | Donation checkout, server-side capture, verified webhook confirmation |
| Claude (`claude-opus-5-5`) | Reporting-plan drafting, claim extraction from NGO messages, receipt reading (structured outputs) |
| FastAPI, SQLAlchemy, Alembic, Postgres/SQLite | API, ledger of donations/claims/evidence, audit log |
| Next.js 16 | Campaign, donor and NGO pages |
| LangGraph | Accountability workflow with interrupt/resume, one thread per reporting request |
| Elastic | Campaign-scoped retrieval over reports and receipts, reused-receipt search (Postgres fallback) |
| AG Grid Community | Accountability console: claims, evidence status, gaps, reporting requests, reviewer actions |
| Render | Blueprint in `render.yaml`: API, web app, Postgres, disk for evidence uploads |
| Built | Zapier MCP donor "new update" email on publish (needs `ZAPIER_MCP_*` in `.env`; in-app only when unset); reminders are in-app |

## Repository map

`contracts/` shared schemas · `backend/app/` API (ownership in `CLAUDE.md`) · `backend/tests/` · `frontend/src/` · `docs/spec.md` product spec · `docs/decisions.md` design log

License: MIT (see `LICENSE`).

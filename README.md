# NGOLog

NGOLog helps donors see where their money goes. People donate to NGO campaigns through PayPal, while our AI follows up with NGOs, reviews spending evidence, and helps them share updates with donors, making donations more transparent and trustworthy.

Built for the PayPal AI Hackathon. NGOLog holds no funds, makes no payouts and never calls anyone fraudulent. "Consistent" means a document matches what the NGO reported. It is not an audit.

**Live demo:** https://ngolog-web.onrender.com (API: https://ngolog-api.onrender.com)

The demo is on free hosting, so the first load after idle can take about a minute. Everything uses the PayPal **sandbox**. No real money moves.

## Features

- **Campaigns:** an NGO creates a campaign, reviews an AI-drafted reporting plan, and publishes.
- **Donations:** PayPal Orders v2 with server-side capture. A signed webhook confirms each donation.
- **Spending updates:** the assistant asks what was spent, in plain chat. The NGO confirms the claims it proposes, or adds them by hand. Updates open on a schedule, or the NGO can start one at any time.
- **Receipt checks:** the NGO uploads receipts. A deterministic check compares totals to the claim. A $500 claim with a $420 receipt triggers a question about the $80 gap. Reused receipts are flagged.
- **Donor updates:** drafted only from stored records, shown to the NGO as a preview, and published after approval. Photos are shared with donors by default and can be unticked. Receipts stay private.
- **Public timeline:** donations received, reported spending and spending matched by receipts are shown separately.
- **Reviewer console:** an AG Grid view of every campaign, open question and overdue request.
- **Notifications:** in-app reminders for the NGO, and a donor email when an update is published.

Rules the code enforces: totals come from Postgres, never from a model. The AI proposes, the NGO decides. NGO text and documents are treated as data, not instructions. PayPal calls stay in `backend/app/payments/`.

## Try it

1. **Donor:** open `/signin`, click **Demo donor**, open *Supply 50 students with school kits*, and donate with this PayPal sandbox buyer account (fake money, sandbox only): email `sb-zyzym53724247@personal.example.com`, password `Mh!NV9*j`. To use your own, create a Personal account at developer.paypal.com under Sandbox → Accounts.
2. **NGO:** sign out, click **Demo NGO**, open **Reporting** on the campaign and click **Start an update**. Updates need at least one donation, so do step 1 first.
   - Reply: "We bought 25 kits from Demo Stationers for $500 and handed out 20."
   - Confirm the proposed claims.
   - Upload `receipt-420.png`, then `receipt-80.png` from `scripts/demo_assets/`. Use the `rehearsal-` copies for a practice run, because a receipt number already submitted is flagged.
   - The $80 receipt closes the gap and a draft is created. Click **Review the draft**, then **Publish to donors**.
3. **Public page:** the campaign page shows the published update. The ⓘ icons explain each number.
4. **Reviewer:** on `/signin` choose *Platform reviewer* with `reviewer@ngolog.org` to open the **Accountability** console.

Limits of the free demo: uploaded files are cleared when the server restarts (claims and checks stay in the database). Elastic search uses its Postgres fallback unless `ELASTIC_URL` is set.

## Run locally

Requires Python 3.12+ and Node 20+.

```bash
cp .env.example .env     # add PayPal sandbox and Anthropic keys
cd backend
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:app --port 8000
```

```bash
cd frontend
echo "NEXT_PUBLIC_API_URL=http://localhost:8000" > .env.local
echo "NEXT_PUBLIC_PAYPAL_CLIENT_ID=<sandbox client id>" >> .env.local
npm install && npm run dev     # http://localhost:3000
```

Sign in at `/signin` with the demo buttons (passwordless demo auth).

Load the demo campaigns and fictional receipts:

```bash
backend/.venv/bin/python scripts/seed_demo.py
```

Set `REVIEWER_EMAILS=reviewer@ngolog.org` to use the reviewer account.

Run the tests:

```bash
cd backend && .venv/bin/python -m pytest -q
```

### PayPal sandbox

1. At developer.paypal.com, go to Apps & Credentials → Sandbox, create an app, and copy the client ID and secret into `.env` (`PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`). Put the client ID in `frontend/.env.local` too.
2. Optional: add a webhook for `PAYMENT.CAPTURE.COMPLETED` pointing at `<backend URL>/api/paypal/webhook` and set `PAYPAL_WEBHOOK_ID`. Locally, use a tunnel such as ngrok. Without it, donations still record from the server-side capture and show "webhook pending".
3. Pay with a sandbox personal (buyer) account.

Without `ANTHROPIC_API_KEY` the app runs in manual mode: the NGO enters claims and receipt totals by hand.

## Tools

| Tool | Use |
|---|---|
| PayPal Orders v2, JS SDK v6, Webhooks (sandbox) | Donation checkout, capture, webhook confirmation |
| Claude (`claude-opus-5-5`) | Reporting plan, claim extraction, receipt reading |
| LangGraph | Accountability workflow that pauses for the NGO and resumes |
| FastAPI, SQLAlchemy, Alembic, Postgres/SQLite | API, ledger of donations, claims and evidence, audit log |
| Next.js 16 | NGO, donor and public pages |
| Elastic | Campaign-scoped search over reports and receipts (Postgres fallback) |
| AG Grid Community | Reviewer console |
| Zapier MCP | Donor email when an update is published |
| Render | Hosting via `render.yaml`: API, web app, Postgres, disk |

## Repository

`contracts/` shared schemas · `backend/app/` API · `backend/tests/` · `frontend/src/` · `docs/decisions.md` design log

License: MIT (see `LICENSE`).

# Codex Task: Demo Dashboard Frontend

**Repo:** https://github.com/vhmaadhav/razorpay-agentic-firewall
**Branch:** create `feature/dashboard`, PR into `master` when done.
**Scope:** `apps/dashboard/` only — do not touch anything under `app/` (the Python backend). Treat the backend as a black box behind the REST API described below.

## Goal

Build a small React (Vite) single-page app that demonstrates the 4 scenarios in `docs/spec.md` §12 (`12-demo-script.md`) end-to-end against the FastAPI backend. This is a hackathon demo UI — prioritize clarity over polish, but it must actually work against the real API, not mocked data.

## Backend contract

The backend runs at `http://127.0.0.1:8000` (`uvicorn app.main:app --reload`). Endpoints (see `docs/spec.md` §08 for full request/response shapes — by the time you start, these should all exist on `master`; if any are missing, stub against the shapes documented there and flag it in the PR description):

1. `POST /intent/compile` — `{intent_text}` → `{mandate_proposal, confidence}`
2. `POST /authorization/confirm` — `{mandate}` → `{authorization_id, status, public_key, evidence_hash}`
3. `POST /agent/request` — `{authorization_id, nonce, agent_id, cart, agent_signature?}` → `{request_id, status, decision, reason, message}`
4. `POST /payment/execute` — `{authorization_id, request_id}` → `{order_id, amount, currency}` (only call this if decision was `ALLOW`)
5. `GET /transactions/{authorization_id}` — combined view: mandate, cart, decision, payment status
6. `GET /transactions/{authorization_id}/evidence` — the hash-chained event log

## Required screens/flow

1. **Intent step** — a textarea for natural-language intent (e.g. *"Buy 3 chairs, max ₹25,000, from Merchant A only, no substitutions, expires in 20 minutes."*), a "Compile" button that calls `/intent/compile` and renders the returned `mandate_proposal` as an editable JSON/form preview.
2. **Confirm & Sign step** — a "Confirm & Sign Mandate" button that calls `/authorization/confirm` and displays the resulting `authorization_id` and canonical envelope JSON (pretty-printed).
3. **Agent cart step** — a form to enter a cart (merchant_id, line items with sku/unit_price/quantity, shipping, tax) with **4 preset buttons** that pre-fill the exact carts from the demo script's 4 scenarios (ALLOW, RECONSENT budget violation, BLOCK wrong merchant, BLOCK replay — replay just resubmits scenario 1's exact payload including nonce). A "Submit to Agent Firewall" button posts to `/agent/request`.
4. **Decision display** — a colored badge: green `ALLOW`, orange `RECONSENT`, red `BLOCK`, with the `reason` code and human `message` shown prominently (large, demo-readable text — this is the money shot of the demo).
5. **Payment step** — only enabled when decision is `ALLOW`; calls `/payment/execute` and shows the returned order ID.
6. **Evidence log panel** — always-visible sidebar or bottom panel that polls/fetches `/transactions/{id}/evidence` and renders the hash-chained event list (event_type, actor, timestamp, and a visual chain indicator like `prev_hash → chain_hash`).

## Non-goals (explicitly do not build)

- No auth/login system — this is a single-operator demo tool.
- No state management library (Redux/Zustand) — local component state / Context is enough for this size.
- No design system — plain CSS or a single small utility (e.g. plain Tailwind via CDN-free local build if you want) is fine, but keep the dependency footprint minimal since this needs to build fast in CI.
- Don't implement `/webhooks/razorpay` UI — that's server-to-server, not user-facing.

## Definition of done

- `apps/dashboard/` is a working Vite + React app (`npm install && npm run dev`).
- README section (`apps/dashboard/README.md`) with setup/run instructions.
- Manually walking through all 4 demo scenarios via the UI produces the correct ALLOW/RECONSENT/BLOCK/BLOCK(replay) outcomes against a locally running backend.
- Open a PR with screenshots of each of the 4 scenario outcomes in the description.

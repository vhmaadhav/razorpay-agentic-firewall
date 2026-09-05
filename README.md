# Agentic Authorization Firewall (Razorpay)

Deterministic, PSP-level enforcement of user-delegated spending mandates for
AI shopping agents. An agent can be authenticated and hold valid payment
credentials and *still* exceed what the user actually authorized — extra
items, a warranty upsell, a tip, a swapped merchant. This firewall normalizes
whatever authorization evidence an agent presents (AP2 mandates, UPI Reserve
Pay, generic signed delegations, ...) into one **Canonical Authorization
Envelope**, then runs the agent's final cart through a pure, deterministic
policy engine that returns `ALLOW` / `BLOCK` / `RECONSENT` — never an LLM.
Every step is recorded in an append-only, hash-chained evidence log.

Full design spec (problem statement, architecture, schema, threat model,
protocol mapping, build plan, demo script, adversarial test suite,
competitive analysis) lives in [`docs/spec.md`](docs/spec.md).

## Status

Feature-complete MVP: end-to-end flow, hardened against every case in the
adversarial test suite, with a working demo dashboard. 158 tests passing.

- [x] Canonical Authorization Envelope schema + Pydantic models (`app/models/envelope.py`, `app/canonical/schema.json`)
- [x] Canonical JSON hashing + Ed25519 sign/verify (`app/canonical/hashing.py`, `app/crypto/`)
- [x] Deterministic policy engine — ALLOW/BLOCK/RECONSENT (`app/policy/engine.py`)
- [x] Agent adapters: AP2-style + generic signed delegation (`app/adapters/`)
- [x] Evidence log with hash-chain tamper detection (`app/evidence/log.py`)
- [x] Razorpay integration: live client + deterministic mock for keyless dev (`app/payment/razorpay_client.py`)
- [x] All REST routes: `/intent/compile`, `/authorization/confirm`, `/authorization/{id}/revoke`, `/agent/request`, `/policy/evaluate`, `/payment/execute`, `/webhooks/razorpay`, `/transactions/*` (`app/routes/`)
- [x] Agent-level request signatures — `/agent/request` verifies a per-request Ed25519 signature bound to the mandate, not just the mandate itself ([docs/agent-request-signatures.md](docs/agent-request-signatures.md))
- [x] Mandate revocation — operators can withdraw a mandate mid-flight; blocks future requests and payment execution ([docs/mandate-revocation.md](docs/mandate-revocation.md))
- [x] Rate limiting on `/agent/request`, enforced before parsing or DB access ([docs/agent-rate-limiting.md](docs/agent-rate-limiting.md))
- [x] Background cleanup flags stale `CREATED` orders as `STALE` without disturbing late webhooks ([docs/payment-cleanup.md](docs/payment-cleanup.md))
- [x] Adversarial test suite — all 50 cases from `docs/spec.md` §13, closed with no descoped gaps (`tests/`)
- [x] Demo script for the 4 scenarios: ALLOW / RECONSENT / BLOCK-merchant / BLOCK-replay (`scripts/demo_scenarios.py`)
- [x] Demo dashboard — React/Vite SPA driving the real backend end-to-end, including live Ed25519 request signing via Web Crypto (`apps/dashboard/`)

Run `pytest -q` or `python scripts/demo_scenarios.py` for a narrated walkthrough of all 4 demo scenarios.

## Running locally

```bash
pip install -r requirements.txt
cp .env.example .env   # leave RAZORPAY_* blank to use the built-in mock executor
uvicorn app.main:app --reload
```

Then open `http://127.0.0.1:8000/docs` for the interactive API explorer.

No Razorpay account is required to develop against this: leaving
`RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET` unset makes `get_payment_executor()`
return `MockRazorpayClient`, which fabricates order IDs and HMAC-signed
webhook payloads locally. Dropping real test-mode keys into `.env` switches
to the live Razorpay Orders API with no code changes.

## Running the dashboard

With the backend running (above), in a second terminal:

```bash
cd apps/dashboard
npm install
npm run dev
```

Open `http://127.0.0.1:5173`. It drives the real backend end-to-end — compile
an intent, sign the mandate (Ed25519 keys generated in-browser via Web
Crypto, never sent to the server), submit one of the 4 preset carts, and
watch the hash-chained evidence trail update live. See
[`apps/dashboard/README.md`](apps/dashboard/README.md) for details.

## Repository layout

See `docs/spec.md` §09 for the target layout. The current tree is flattened
under `app/` for a single-package MVP rather than the full monorepo split —
logical boundaries (schema / crypto / adapters / policy / payment / evidence /
routes) are preserved as subpackages either way.

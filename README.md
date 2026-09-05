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

Actively being scaffolded. Current state:

- [x] Canonical Authorization Envelope schema + Pydantic models (`app/models/envelope.py`, `app/canonical/schema.json`)
- [x] Canonical JSON hashing (`app/canonical/hashing.py`)
- [x] Ed25519 sign/verify (`app/crypto/signature.py`)
- [x] Deterministic policy engine — ALLOW/BLOCK/RECONSENT (`app/policy/engine.py`)
- [x] Agent adapters: AP2-style + generic signed delegation (`app/adapters/`)
- [x] Evidence log with hash-chain tamper detection (`app/evidence/log.py`)
- [x] Razorpay integration: live client + deterministic mock for keyless dev (`app/payment/razorpay_client.py`)
- [x] DB schema (SQLite by default, Postgres-ready via `DATABASE_URL`) (`app/models/schema.py`)
- [x] All REST routes: `/intent/compile`, `/authorization/confirm`, `/agent/request`, `/policy/evaluate`, `/payment/execute`, `/webhooks/razorpay`, `/transactions/*` (`app/routes/`)
- [x] Adversarial test suite — all 50 cases from `docs/spec.md` §13 (`tests/test_policy_engine.py`, `tests/test_api_flow.py`)
- [x] Demo script for the 4 scenarios: ALLOW / RECONSENT / BLOCK-merchant / BLOCK-replay (`scripts/demo_scenarios.py`)
- [ ] Optional dashboard frontend — brief for a separate agent to build lives at [`docs/codex-task-dashboard.md`](docs/codex-task-dashboard.md)

Run `pytest -q` or `python scripts/demo_scenarios.py` for a narrated walkthrough of all 4 demo scenarios.

Agent requests require Ed25519 signatures. See [the signing protocol and client migration](docs/agent-request-signatures.md).

Operators can revoke mandates with `POST /authorization/{id}/revoke`.
Revocation blocks future agent requests and new payment execution, including
previously allowed requests. See [revocation behavior and in-flight order limits](docs/mandate-revocation.md).

`POST /agent/request` is rate limited before parsing or database access.
See [limits, HTTP 429 behavior, and worker configuration](docs/agent-rate-limiting.md).

Background cleanup flags overdue `CREATED` payments as `STALE`, with an audit
event and support for late webhooks. See [timeouts and cleanup behavior](docs/payment-cleanup.md).

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

## Repository layout

See `docs/spec.md` §09 for the target layout. The current tree is flattened
under `app/` for a single-package MVP rather than the full monorepo split —
logical boundaries (schema / crypto / adapters / policy / payment / evidence /
routes) are preserved as subpackages either way.

# Mandate revocation

The trusted local operator can permanently revoke a mandate with:

```http
POST /authorization/{authorization_id}/revoke
Content-Type: application/json

{"reason":"compromised agent"}
```

The response is HTTP 200:

```json
{
  "authorization_id": "auth-example",
  "status": "REVOKED",
  "reason": "compromised agent",
  "revoked_at": "2026-09-05T14:00:00+00:00"
}
```

Send `{}` to use reason `operator_request`. Reasons must contain 1 to 500
characters and cannot be whitespace only. Unknown IDs return 404 and invalid
bodies return 422. Repeating revocation returns the original reason and timestamp
without appending another event. There is no un-revoke operation; confirm a new
mandate if the operator wants to authorize spending again.

## Enforcement

- Valid signed agent requests against a revoked mandate receive the normal
  policy response with `decision: BLOCK` and `reason: MANDATE_REVOKED`.
  Signature verification still happens first. Revoked requests cannot use the
  mandate's spending allowance.
- `/payment/execute` checks persisted revocation even if an earlier decision
  was `ALLOW`. It returns 409 with `detail.decision: BLOCK` and
  `detail.reason: MANDATE_REVOKED` without calling the payment provider.
- `GET /transactions/{id}` adds `status`, either `SIGNED` or `REVOKED`, and
  `revocation`, either null or the original reason and UTC timestamp. `SIGNED`
  does not imply the mandate is unexpired or has remaining uses.
- The signed envelope and historical decisions stay unchanged. One
  `MANDATE_REVOKED` evidence event records the reason and time under actor
  `trusted-operator`.

## In-flight orders and persistence

Revocation, agent evaluation, and order creation acquire the same database
write lock. If revocation acquires it first, payment makes no provider call.
If order creation has already acquired it, revocation waits until that operation
commits or rolls back. A successful revocation prevents subsequent order
creation; it does not cancel, refund, or undo an order already sent to Razorpay.
Webhook updates for those orders continue to be recorded truthfully. Repeating
`/payment/execute` after revocation returns 409 even for an existing order;
inspect the transaction endpoint for its status.

The revocation record and evidence event commit together. The new
`mandate_revocations` table is additive: restarting the backend runs the existing
`create_all` initialization and creates it without deleting old data or changing
the signed envelope. Revocation persists across database connections/restarts.

SQLite takes a database-wide write lock, including during the provider call.
Use the existing single-worker local deployment. Slow provider calls can delay
revocation or produce a database-lock timeout; an error is not a successful
revocation. Check the transaction status before retrying. Postgres uses a row
lock with this query, but live Postgres concurrency validation remains part of
backlog item 6.

The endpoint has the same trusted local operator boundary as `/confirm`.
It does not add user login or verify an operator identity, and must not be
exposed to untrusted callers. Agent credentials are not a replacement for
operator authentication in a public deployment.

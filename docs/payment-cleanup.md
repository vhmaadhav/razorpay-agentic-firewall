# Stale payment cleanup

The API runs a background sweep that flags orders left in `CREATED` without a
recorded webhook for at least 30 minutes. It sets their status to `STALE` and
appends a `PAYMENT_STALE` evidence event with the order ID, creation time,
observation time, and timeout. The status and event commit together.

`STALE` means the local service is still waiting for confirmation. It does not
mean the provider rejected the payment. Cleanup never deletes an order,
cancels it, refunds it, retries a charge, or calls Razorpay.

## Configuration

| Variable | Default | Meaning |
| --- | ---: | --- |
| `PAYMENT_STALE_AFTER_SECONDS` | 1800 | Minimum age of a CREATED order with no webhook |
| `PAYMENT_CLEANUP_INTERVAL_SECONDS` | 60 | Delay before the first sweep and between completed sweeps |
| `PAYMENT_CLEANUP_BATCH_SIZE` | 100 | Maximum candidate orders per sweep |

All values must be positive integers. Invalid configuration prevents startup.
Restart the backend after changing them. Under normal load, an order is flagged
on the next sweep after reaching its timeout. Large backlogs require additional
sweeps because each batch is bounded; oldest eligible orders are considered first.

The task starts and stops with FastAPI's lifespan. Database work runs in a
thread with its own sessions so the scheduler does not block the event loop.
Shutdown signals the worker and waits for any active sweep to finish. Sweep
failures are logged and retried at the next interval. Earlier completed flags
remain committed; a failed flag rolls back with its event.

## Status, webhooks, and races

`GET /transactions/{authorization_id}` exposes `STALE` in the existing payment
status field. Its evidence endpoint returns the timeout event in the chain.
Repeated sweeps skip flagged orders and do not append duplicate events.

Orders with any recorded `PaymentEvent`, or a status other than `CREATED`, are
excluded. Cleanup acquires the same authorization lock as payment execution,
revocation, and webhook processing, then rechecks each selected order. If a
webhook arrives between selection and lock acquisition, cleanup observes its
updated state and leaves it alone. If cleanup wins first, the webhook waits,
then applies the existing webhook handling to the flagged order.

A late verified capture can change `STALE` to `CAPTURED`; an amount mismatch
still produces `AMOUNT_MISMATCH`. Both the stale event and subsequent webhook
event remain in history. Retrying `/payment/execute` returns the existing order
under its usual idempotency rules; cleanup does not authorize a second order.
Revocation enforcement continues to apply.

No database migration is needed because payment status is already stored as
a string. Old overdue orders are eligible after restart. The worker is part of
the current single-worker SQLite deployment. SQLite write locks serialize
cleanup with other writes. Database outages or lock timeouts delay cleanup and
are reported in logs. PostgreSQL deployment/concurrency validation remains
backlog item 6.

# Agent request rate limiting

`POST /agent/request` has admission limits before request-body parsing, signature
verification, database work, or evidence writes. Requests that exceed a limit
receive HTTP 429:

```http
Retry-After: 60
Cache-Control: no-store
Content-Type: application/json
```

```json
{
  "detail": {
    "reason": "RATE_LIMIT_EXCEEDED",
    "message": "Too many agent requests. Retry in 60 seconds.",
    "retry_after": 60
  }
}
```

The delay is rounded up to whole seconds for the rejecting window. Wait at least
that long before retrying; new traffic can still exhaust a quota afterward.
Throttled attempts do not consume a nonce, create a policy decision, modify a
mandate, or append evidence. A retry can use the same signed request. This
response is an admission error, not an ALLOW/BLOCK policy evaluation.

## Configuration

Set these variables before starting the backend:

| Variable | Default | Meaning |
| --- | ---: | --- |
| `AGENT_RATE_LIMIT` | 60 | Attempts admitted per client address per window |
| `AGENT_RATE_LIMIT_GLOBAL` | 600 | Attempts processed by the limiter per worker per window |
| `AGENT_RATE_LIMIT_WINDOW_SECONDS` | 60 | Fixed-window duration |
| `AGENT_RATE_LIMIT_MAX_CLIENTS` | 4096 | Maximum active client counters per worker |

All values must be positive integers. Invalid values prevent startup; zero does
not silently disable protection. Restart the worker after changing settings.

Client identity comes from the ASGI connection address. Changing `agent_id`,
authorization, nonce, or forwarding headers in the request does not reset a
counter. When using a reverse proxy, configure the ASGI server to trust forwarded
addresses only from that proxy. Do not accept forwarded addresses from arbitrary
clients. Without trusted proxy configuration, callers behind a proxy share the
proxy address and its quota. The local Vite proxy likewise shares its address.

Malformed requests count toward the limits. Per-client rejections also count
toward the worker ceiling. Other endpoints are unaffected, including health,
revocation, transaction views, and webhooks. The trailing-slash redirect path is
covered too; following a redirect creates another HTTP attempt.

## Window and deployment behavior

Counters use a monotonic clock and a thread lock. Each client window starts with
its first attempt and lasts the configured duration. Rejections do not extend
it. A fixed window permits a burst near its end followed by another burst after
reset; it is not a sliding-window or per-second pacing guarantee.

Client counters expire in insertion order. When capacity is reached, new client
addresses receive 429 until an entry expires. Active counters are never evicted
to admit a new identity, so an address flood cannot reset another active quota.
Storage is bounded by the configured client capacity.

Counters live in worker memory and reset on process restart. Use one API worker
for the current SQLite demo. Multiple workers or replicas each have their own
limits and can admit a combined multiple of these values. A shared gateway or
distributed limiter is required for deployment-wide quotas. This feature limits
API work; it does not replace network-level DoS protection or request-size limits.

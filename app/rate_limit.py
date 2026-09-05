"""Bounded, thread-safe fixed-window admission for the local API worker."""
import math
import time
from collections import OrderedDict
from threading import Lock

from starlette.responses import JSONResponse


class AgentRequestLimiter:
    def __init__(self, *, per_client: int, global_limit: int, window_seconds: int,
                 max_clients: int, clock=time.monotonic):
        if any(value <= 0 for value in (per_client, global_limit, window_seconds, max_clients)):
            raise ValueError("Agent rate limits, window, and client capacity must be positive")
        self.per_client = per_client
        self.global_limit = global_limit
        self.window_seconds = window_seconds
        self.max_clients = max_clients
        self.clock = clock
        self._clients = OrderedDict()
        self._global_reset = 0.0
        self._global_count = 0
        self._lock = Lock()

    def admit(self, client: str) -> int | None:
        """Return Retry-After seconds on rejection, otherwise admit the attempt.

        Windows start on the first attempt. Denials do not extend expiration.
        Expirations stay ordered, so cleanup touches only expired entries.
        """
        with self._lock:
            now = self.clock()
            while self._clients:
                _, (reset, _) = next(iter(self._clients.items()))
                if reset > now:
                    break
                self._clients.popitem(last=False)
            if now >= self._global_reset:
                self._global_reset = now + self.window_seconds
                self._global_count = 0
            if self._global_count >= self.global_limit:
                return max(1, math.ceil(self._global_reset - now))
            # Count attempts even when an individual client is already limited.
            self._global_count += 1
            current = self._clients.get(client)
            if current is None:
                if len(self._clients) >= self.max_clients:
                    reset = next(iter(self._clients.values()))[0]
                    return max(1, math.ceil(reset - now))
                current = (now + self.window_seconds, 0)
            reset, count = current
            if count >= self.per_client:
                return max(1, math.ceil(reset - now))
            self._clients[client] = (reset, count + 1)
            return None


class AgentRateLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        root = scope.get("root_path", "")
        if root and path.startswith(root + "/"):
            path = path[len(root):]
        if scope["type"] == "http" and scope["method"] == "POST" and path.rstrip("/") == "/agent/request":
            peer = scope.get("client")
            client = peer[0] if peer else "unknown-peer"
            retry_after = scope["app"].state.agent_request_limiter.admit(client)
            if retry_after is not None:
                response = JSONResponse(
                    status_code=429,
                    headers={"Retry-After": str(retry_after), "Cache-Control": "no-store"},
                    content={"detail": {
                        "reason": "RATE_LIMIT_EXCEEDED",
                        "message": f"Too many agent requests. Retry in {retry_after} seconds.",
                        "retry_after": retry_after,
                    }},
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)

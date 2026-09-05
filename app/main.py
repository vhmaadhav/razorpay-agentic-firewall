from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db import init_db
from app.config import settings
from app.rate_limit import AgentRequestLimiter, AgentRateLimitMiddleware
from app.routes import agent, authorization, intent, payment, policy, transactions, webhooks


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.agent_request_limiter = AgentRequestLimiter(
        per_client=settings.agent_rate_limit,
        global_limit=settings.agent_rate_limit_global,
        window_seconds=settings.agent_rate_limit_window_seconds,
        max_clients=settings.agent_rate_limit_max_clients,
    )
    init_db()
    yield


app = FastAPI(
    title="Agentic Authorization Firewall",
    description="Deterministic PSP-level policy enforcement for AI-agent checkouts (Razorpay).",
    version="0.1.0",
    lifespan=lifespan,
)
app.add_middleware(AgentRateLimitMiddleware)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


app.include_router(intent.router)
app.include_router(authorization.router)
app.include_router(agent.router)
app.include_router(policy.router)
app.include_router(payment.router)
app.include_router(webhooks.router)
app.include_router(transactions.router)

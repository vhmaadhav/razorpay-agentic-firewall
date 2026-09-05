from contextlib import asynccontextmanager
import asyncio

from fastapi import FastAPI

from app.db import init_db
import app.db as db_module
from app.payment.cleanup import run_payment_cleanup
from app.config import settings
from app.rate_limit import AgentRequestLimiter, AgentRateLimitMiddleware
from app.routes import agent, authorization, intent, payment, policy, transactions, webhooks


@asynccontextmanager
async def lifespan(app: FastAPI):
    if any(value <= 0 for value in (
        settings.payment_stale_after_seconds, settings.payment_cleanup_interval_seconds,
        settings.payment_cleanup_batch_size,
    )):
        raise ValueError("Payment cleanup timeout, interval, and batch size must be positive")
    app.state.agent_request_limiter = AgentRequestLimiter(
        per_client=settings.agent_rate_limit,
        global_limit=settings.agent_rate_limit_global,
        window_seconds=settings.agent_rate_limit_window_seconds,
        max_clients=settings.agent_rate_limit_max_clients,
    )
    init_db()
    stop = asyncio.Event()
    cleanup_task = asyncio.create_task(run_payment_cleanup(
        stop, db_module.SessionLocal,
        timeout_seconds=settings.payment_stale_after_seconds,
        interval_seconds=settings.payment_cleanup_interval_seconds,
        batch_size=settings.payment_cleanup_batch_size,
    ))
    try:
        yield
    finally:
        stop.set()
        await cleanup_task


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

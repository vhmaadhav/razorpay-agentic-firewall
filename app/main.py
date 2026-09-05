from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db import init_db
from app.routes import agent, authorization, intent, payment, policy, transactions, webhooks


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="Agentic Authorization Firewall",
    description="Deterministic PSP-level policy enforcement for AI-agent checkouts (Razorpay).",
    version="0.1.0",
    lifespan=lifespan,
)


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

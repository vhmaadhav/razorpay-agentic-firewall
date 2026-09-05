from fastapi import FastAPI

from app.db import init_db
from app.routes import intent

app = FastAPI(
    title="Agentic Authorization Firewall",
    description="Deterministic PSP-level policy enforcement for AI-agent checkouts (Razorpay).",
    version="0.1.0",
)


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


app.include_router(intent.router)

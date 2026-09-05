"""Case 48: stale flags, late webhooks, concurrency, and worker lifecycle."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

import app.db as db_module
from app.models.schema import PaymentExecution, PaymentEvent
from app.payment.cleanup import flag_stale_payments, run_payment_cleanup
from app.payment.razorpay_client import MockRazorpayClient, OrderResult
from tests.test_api_flow import client, confirm_demo_mandate
from tests.test_revocation import file_client, submit

NOW = datetime(2030, 1, 1, tzinfo=timezone.utc)


def order_for(client, *, age=1801, status="CREATED"):
    auth_id = confirm_demo_mandate(client)
    result = submit(client, auth_id).json()
    order = client.post("/payment/execute", json={
        "authorization_id": auth_id, "request_id": result["request_id"],
    }).json()
    with db_module.SessionLocal() as db:
        row = db.query(PaymentExecution).filter_by(razorpay_order_id=order["order_id"]).one()
        row.created_at = NOW - timedelta(seconds=age)
        row.status = status
        db.commit()
    return auth_id, result["request_id"], order


def sweep(**overrides):
    return flag_stale_payments(db_module.SessionLocal, **{
        "timeout_seconds": 1800, "batch_size": 100, "now": NOW, **overrides,
    })


def deliver(client, auth_id, order, *, amount=None):
    raw, sig = MockRazorpayClient().build_test_webhook(OrderResult(
        order["order_id"], order["amount"] if amount is None else amount,
        order["currency"], "created", auth_id,
    ))
    return client.post("/webhooks/razorpay", content=raw, headers={"X-Razorpay-Signature": sig})


def test_case_48_flags_overdue_order_once_preserving_order_and_amount(client):
    auth_id, request_id, order = order_for(client)
    assert sweep() == 1
    assert sweep() == 0
    tx = client.get(f"/transactions/{auth_id}").json()
    assert tx["payments"] == [{
        "order_id": order["order_id"], "amount": order["amount"],
        "currency": order["currency"], "status": "STALE",
    }]
    evidence = client.get(f"/transactions/{auth_id}/evidence").json()
    assert evidence["chain_valid"]
    events = [e for e in evidence["events"] if e["event_type"] == "PAYMENT_STALE"]
    assert len(events) == 1
    assert events[0]["actor"] == "payment-cleanup"
    assert events[0]["payload"]["order_id"] == order["order_id"]
    # The original payment remains idempotent; cleanup never creates a new one.
    assert client.post("/payment/execute", json={
        "authorization_id": auth_id, "request_id": request_id,
    }).json() == order


@pytest.mark.parametrize("age,expected", [(1799, 0), (1800, 1), (1801, 1), (-1, 0)])
def test_timeout_boundary(client, age, expected):
    order_for(client, age=age)
    assert sweep() == expected


@pytest.mark.parametrize("status", ["CAPTURED", "AMOUNT_MISMATCH", "FAILED", "STALE"])
def test_other_statuses_are_untouched(client, status):
    auth_id, _, _ = order_for(client, status=status)
    assert sweep() == 0
    assert client.get(f"/transactions/{auth_id}").json()["payments"][0]["status"] == status


def test_webhook_record_excludes_created_order(client):
    _, _, order = order_for(client)
    with db_module.SessionLocal() as db:
        execution = db.query(PaymentExecution).filter_by(razorpay_order_id=order["order_id"]).one()
        db.add(PaymentEvent(event_id="observed", execution_id=execution.execution_id,
                            event_type="payment.authorized", payload={}, signature_verified=True))
        db.commit()
    assert sweep() == 0


def test_bounded_batches_eventually_drain_backlog(client):
    for _ in range(3):
        order_for(client)
    assert sweep(batch_size=2) == 2
    assert sweep(batch_size=2) == 1
    assert sweep(batch_size=2) == 0


@pytest.mark.parametrize("amount,status", [(23700, "CAPTURED"), (1, "AMOUNT_MISMATCH")])
def test_late_webhook_supersedes_stale_flag_and_keeps_evidence(client, amount, status):
    auth_id, _, order = order_for(client)
    assert sweep() == 1
    assert deliver(client, auth_id, order, amount=amount).status_code == 200
    assert client.get(f"/transactions/{auth_id}").json()["payments"][0]["status"] == status
    assert sweep() == 0
    evidence = client.get(f"/transactions/{auth_id}/evidence").json()
    assert evidence["chain_valid"]
    assert "PAYMENT_STALE" in [e["event_type"] for e in evidence["events"]]


def test_cleanup_does_not_revert_webhook_processed_first(client):
    auth_id, _, order = order_for(client)
    assert deliver(client, auth_id, order).status_code == 200
    assert sweep() == 0
    assert client.get(f"/transactions/{auth_id}").json()["payments"][0]["status"] == "CAPTURED"


def test_cleanup_flag_rolls_back_if_evidence_fails(client, monkeypatch):
    auth_id, _, _ = order_for(client)

    def fail(*args, **kwargs):
        raise RuntimeError("evidence unavailable")

    monkeypatch.setattr("app.payment.cleanup.append_event", fail)
    with pytest.raises(RuntimeError, match="evidence unavailable"):
        sweep()
    assert client.get(f"/transactions/{auth_id}").json()["payments"][0]["status"] == "CREATED"


def test_concurrent_sweeps_do_not_duplicate_flags(file_client):
    auth_id, _, _ = order_for(file_client)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [pool.submit(sweep) for _ in range(2)]
        assert sum(f.result(timeout=5) for f in results) == 1
    evidence = file_client.get(f"/transactions/{auth_id}/evidence").json()
    assert evidence["chain_valid"]
    assert sum(e["event_type"] == "PAYMENT_STALE" for e in evidence["events"]) == 1


def test_concurrent_webhook_and_cleanup_preserve_capture(file_client):
    auth_id, _, order = order_for(file_client)
    with ThreadPoolExecutor(max_workers=2) as pool:
        cleanup = pool.submit(sweep)
        webhook = pool.submit(deliver, file_client, auth_id, order)
        assert cleanup.result(timeout=5) in (0, 1)
        assert webhook.result(timeout=5).status_code == 200
    tx = file_client.get(f"/transactions/{auth_id}").json()
    assert tx["payments"][0]["status"] == "CAPTURED"
    assert file_client.get(f"/transactions/{auth_id}/evidence").json()["chain_valid"]


def test_webhook_after_candidate_selection_is_rechecked(file_client, monkeypatch):
    from app.payment import cleanup
    auth_id, _, order = order_for(file_client)
    original_lock = cleanup.lock_authorization

    def webhook_then_lock(db, authorization_id):
        # The candidate list has already been fetched. The webhook wins
        # before cleanup obtains its lock, so its old snapshot is obsolete.
        assert deliver(file_client, auth_id, order).status_code == 200
        return original_lock(db, authorization_id)

    monkeypatch.setattr(cleanup, "lock_authorization", webhook_then_lock)
    assert sweep() == 0
    evidence = file_client.get(f"/transactions/{auth_id}/evidence").json()
    assert evidence["chain_valid"]
    assert all(e["event_type"] != "PAYMENT_STALE" for e in evidence["events"])


def test_webhook_waits_for_cleanup_then_updates_status(file_client, monkeypatch):
    from threading import Event
    from concurrent.futures import TimeoutError
    from app.payment import cleanup

    entered, release, webhook_started = Event(), Event(), Event()
    auth_id, _, order = order_for(file_client)
    original_append = cleanup.append_event

    def paused_append(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original_append(*args, **kwargs)

    def webhook():
        webhook_started.set()
        return deliver(file_client, auth_id, order)

    monkeypatch.setattr(cleanup, "append_event", paused_append)
    with ThreadPoolExecutor(max_workers=2) as pool:
        scan = pool.submit(sweep)
        try:
            assert entered.wait(5)
            callback = pool.submit(webhook)
            assert webhook_started.wait(5)
            with pytest.raises(TimeoutError):
                callback.result(timeout=0.15)
        finally:
            release.set()
        assert scan.result(timeout=5) == 1
        assert callback.result(timeout=5).status_code == 200
    tx = file_client.get(f"/transactions/{auth_id}").json()
    assert tx["payments"][0]["status"] == "CAPTURED"
    evidence = file_client.get(f"/transactions/{auth_id}/evidence").json()
    assert evidence["chain_valid"]
    assert [e["event_type"] for e in evidence["events"]][-2:] == ["PAYMENT_STALE", "PAYMENT_CAPTURED"]


def test_background_worker_runs_real_sweep_and_recovers_after_failure(file_client, monkeypatch, caplog):
    from app.payment import cleanup
    auth_id, _, _ = order_for(file_client)
    original = cleanup.flag_stale_payments
    calls = []

    async def run():
        stop = asyncio.Event()
        finished = asyncio.Event()
        loop = asyncio.get_running_loop()

        def sometimes_fails(factory, **kwargs):
            calls.append(True)
            if len(calls) == 1:
                raise RuntimeError("transient database error")
            count = original(factory, **kwargs, now=NOW)
            loop.call_soon_threadsafe(finished.set)
            return count

        monkeypatch.setattr(cleanup, "flag_stale_payments", sometimes_fails)
        task = asyncio.create_task(run_payment_cleanup(
            stop, db_module.SessionLocal, timeout_seconds=1800, interval_seconds=0.01, batch_size=100,
        ))
        try:
            await asyncio.wait_for(finished.wait(), timeout=3)
        finally:
            stop.set()
            await asyncio.wait_for(task, timeout=3)

    asyncio.run(run())
    assert len(calls) >= 2
    assert "retrying next interval" in caplog.text
    assert file_client.get(f"/transactions/{auth_id}").json()["payments"][0]["status"] == "STALE"


def test_application_starts_and_joins_worker(monkeypatch):
    from fastapi.testclient import TestClient
    from app import main
    steps = []

    async def worker(stop, factory, **kwargs):
        steps.append("started")
        await stop.wait()
        steps.append("stopped")

    monkeypatch.setattr(main, "init_db", lambda: None)
    monkeypatch.setattr(main, "run_payment_cleanup", worker)
    with TestClient(main.app) as c:
        assert c.get("/health").status_code == 200
        assert steps == ["started"]
    assert steps == ["started", "stopped"]


@pytest.mark.parametrize("field", ["payment_stale_after_seconds", "payment_cleanup_interval_seconds", "payment_cleanup_batch_size"])
@pytest.mark.parametrize("value", [0, -1])
def test_invalid_worker_configuration_prevents_startup(monkeypatch, field, value):
    from fastapi.testclient import TestClient
    from app.config import settings
    from app.main import app
    monkeypatch.setattr(settings, field, value)
    with pytest.raises(ValueError, match="must be positive"):
        with TestClient(app):
            pass

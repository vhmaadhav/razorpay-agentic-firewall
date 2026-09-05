"""Runnable version of 12-demo-script.md's 4 scenarios (TASK-011).

Usage:
    python scripts/demo_scenarios.py

Runs against an in-process app (via httpx ASGI transport) against a fresh
in-memory SQLite DB — no server or real Razorpay credentials needed. Each
scenario prints the same beats the demo script narrates: mandate -> agent
cart -> decision -> (if ALLOW) order + webhook -> evidence chain.
"""
import os
import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("DATABASE_URL", "sqlite:///./demo_scenarios.db")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.payment.razorpay_client import MockRazorpayClient, OrderResult  # noqa: E402

GREEN, ORANGE, RED, RESET, BOLD = "\033[92m", "\033[93m", "\033[91m", "\033[0m", "\033[1m"
BADGE = {"ALLOW": f"{GREEN}ALLOW{RESET}", "RECONSENT": f"{ORANGE}RECONSENT{RESET}", "BLOCK": f"{RED}BLOCK{RESET}"}


def banner(title: str) -> None:
    print(f"\n{BOLD}{'=' * 70}\n{title}\n{'=' * 70}{RESET}")


def confirm_mandate(client, **overrides) -> str:
    mandate = {
        "user_id": "user_789", "merchant_name": "MerchantA", "quantity": 3, "category": "chair",
        "allowed_skus": ["CHAIR1"], "max_total": 25000, "substitutions_allowed": False,
        "expires_in_minutes": 20,
    }
    mandate.update(overrides)
    resp = client.post("/authorization/confirm", json={"mandate": mandate})
    body = resp.json()
    print(f"Mandate signed: authorization_id={body['authorization_id']} (max_total=₹{mandate['max_total']})")
    return body["authorization_id"]


def submit_cart(client, auth_id: str, nonce: str, cart: dict) -> dict:
    resp = client.post(
        "/agent/request", json={"authorization_id": auth_id, "nonce": nonce, "agent_id": "agent_xyz", "cart": cart}
    )
    body = resp.json()
    print(f"Agent submitted cart (total=₹{cart['total']}) -> {BADGE.get(body['decision'], body['decision'])}")
    print(f"  reason={body['reason'] or '(none)'}  message=\"{body['message']}\"")
    return body


def run_scenario_1(client) -> str:
    banner("SCENARIO 1 — Valid Payment (ALLOW)")
    auth_id = confirm_mandate(client)
    cart = {
        "merchant_id": "MerchantA",
        "items": [{"sku": "CHAIR1", "unit_price": 7500, "quantity": 3, "category": "chair"}],
        "shipping": 1200, "tax": 0, "total": 23700, "currency": "INR",
    }
    result = submit_cart(client, auth_id, "n1", cart)
    assert result["decision"] == "ALLOW"

    order = client.post("/payment/execute", json={"authorization_id": auth_id, "request_id": result["request_id"]}).json()
    print(f"Razorpay Order Created: id={order['order_id']} amount=₹{order['amount']}")

    mock = MockRazorpayClient()
    raw, sig = mock.build_test_webhook(OrderResult(order["order_id"], order["amount"], order["currency"], "created", auth_id))
    client.post("/webhooks/razorpay", content=raw, headers={"X-Razorpay-Signature": sig})
    print("Webhook received: payment.captured")

    evidence = client.get(f"/transactions/{auth_id}/evidence").json()
    print(f"Evidence chain valid: {evidence['chain_valid']}  events={[e['event_type'] for e in evidence['events']]}")
    print(f"{GREEN}{BOLD}Result: Transaction ALLOWED and Captured.{RESET}")
    return auth_id


def run_scenario_2(client) -> None:
    banner("SCENARIO 2 — Amount Violation (RECONSENT)")
    auth_id = confirm_mandate(client, allowed_skus=[])  # allow any SKU so the overage is purely financial
    cart = {
        "merchant_id": "MerchantA",
        "items": [{"sku": "CHAIR1", "unit_price": 9000, "quantity": 3, "category": "chair"}],
        "shipping": 1200, "tax": 0, "total": 28200, "currency": "INR",
    }
    result = submit_cart(client, auth_id, "n1", cart)
    assert result["decision"] == "RECONSENT"
    print(f"{ORANGE}{BOLD}Result: No Razorpay order created. Agent must obtain user re-authorization.{RESET}")


def run_scenario_3(client) -> None:
    banner("SCENARIO 3 — Agent Valid, Transaction Invalid (BLOCK — wrong merchant)")
    auth_id = confirm_mandate(client)
    cart = {
        "merchant_id": "MerchantB",
        "items": [{"sku": "CHAIR1", "unit_price": 7500, "quantity": 2, "category": "chair"}],
        "shipping": 0, "tax": 0, "total": 15000, "currency": "INR",
    }
    result = submit_cart(client, auth_id, "n1", cart)
    assert result["decision"] == "BLOCK" and result["reason"] == "MERCHANT_NOT_ALLOWED"
    print(f"{RED}{BOLD}Result: AGENT OK, but MERCHANT VIOLATION -> BLOCK.{RESET}")


def run_scenario_4(client, allowed_auth_id: str) -> None:
    banner("SCENARIO 4 — Replay Attack (BLOCK)")
    cart = {
        "merchant_id": "MerchantA",
        "items": [{"sku": "CHAIR1", "unit_price": 7500, "quantity": 3, "category": "chair"}],
        "shipping": 1200, "tax": 0, "total": 23700, "currency": "INR",
    }
    print("Resubmitting Scenario 1's exact signed request (same nonce)...")
    result = submit_cart(client, allowed_auth_id, "n1", cart)
    assert result["decision"] == "BLOCK" and result["reason"] == "NONCE_ALREADY_USED"
    print(f"{RED}{BOLD}Result: Duplicate transaction attempt (replay) detected. No second order created.{RESET}")


def main() -> None:
    db_path = os.environ["DATABASE_URL"].replace("sqlite:///", "")
    if os.path.exists(db_path):
        os.remove(db_path)

    with TestClient(app) as client:
        scenario1_auth_id = run_scenario_1(client)
        run_scenario_2(client)
        run_scenario_3(client)
        run_scenario_4(client, scenario1_auth_id)

    banner("WRAP-UP")
    print("Unauthorized payments = 0. Duplicate payments = 0.")
    print("The firewall enforced the user's delegated authority on every path.")


if __name__ == "__main__":
    main()

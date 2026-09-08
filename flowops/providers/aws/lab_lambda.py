"""Actual local Lambda code: deterministic business validation and event formatting."""

import json
from decimal import Decimal
from typing import Any


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    payment = event["payment"]
    customer = event["customer"]
    if payment.get("forceFailure", {}).get("BOOL"):
        raise ValueError("Intentional lab failure: payment requires investigation")
    if not customer["active"]["BOOL"]:
        raise ValueError("Inactive customer")
    amount = Decimal(payment["amount"]["N"])
    if amount <= 0:
        raise ValueError("Amount must be positive")
    result = {
        "event_type": "PaymentRecovered",
        "payment_id": payment["paymentId"]["S"],
        "customer_id": customer["customerId"]["S"],
        "amount": str(amount),
        "currency": "BRL",
        "priority": "high" if amount >= 5000 else "normal",
        "status": "PROCESSED",
        "reason": event["reason"],
        "execution_id": event["execution_id"],
    }
    return {"event": result, "evidence_json": json.dumps(result, ensure_ascii=False)}

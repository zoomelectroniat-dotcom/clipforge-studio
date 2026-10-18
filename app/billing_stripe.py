"""Stripe Checkout + webhooks. Clean-room, httpx only (no stripe SDK).

INACTIVE unless the site owner pastes Stripe keys into env vars. With keys
unset, the pricing page shows "Payments aren't configured yet" and NO charge
is ever attempted.

v1 model: one-time Checkout Sessions (mode=payment) for credit packs that
mirror the monthly plans. On checkout.session.completed the webhook grants
the plan's credits once and sets plan_tier. Processed Stripe event ids are
recorded (WebhookEvent) so retries never double-grant.
"""
import hashlib
import hmac
import os
import time

import httpx

STRIPE_API = "https://api.stripe.com/v1"

# plan -> credits granted on one completed checkout (mirrors pricing page)
PLANS = {
    "starter": {"name": "Starter", "credits": 200},
    "pro": {"name": "Pro", "credits": 800},
}


def _env(name: str) -> str | None:
    v = (os.environ.get(name) or "").strip()
    return v or None


def secret_key() -> str | None:
    return _env("STRIPE_SECRET_KEY")


def webhook_secret() -> str | None:
    return _env("STRIPE_WEBHOOK_SECRET")


def stripe_configured() -> bool:
    return bool(secret_key())


def price_id_for(plan: str) -> str | None:
    return _env(f"STRIPE_PRICE_ID_{plan.upper()}")


class StripeError(RuntimeError):
    """User-friendly Stripe failure."""


def create_checkout_session(user_id: str, user_email: str, plan: str,
                            success_url: str, cancel_url: str) -> str:
    """Create a Checkout Session; return the hosted URL to redirect to."""
    if not stripe_configured():
        raise StripeError("not-configured")
    if plan not in PLANS:
        raise StripeError("Unknown plan.")
    price = price_id_for(plan)
    if not price:
        raise StripeError(
            "This plan isn't priced yet — the site owner needs to add its "
            "Stripe Price ID in the server settings.")
    try:
        r = httpx.post(
            f"{STRIPE_API}/checkout/sessions",
            auth=(secret_key(), ""),
            data={
                "mode": "payment",
                "success_url": success_url + "?session_id={CHECKOUT_SESSION_ID}",
                "cancel_url": cancel_url,
                "customer_email": user_email,
                "line_items[0][price]": price,
                "line_items[0][quantity]": 1,
                "metadata[user_id]": user_id,
                "metadata[plan]": plan,
            },
            timeout=30, trust_env=False)
    except Exception:
        raise StripeError("Could not reach Stripe — check your connection and try again.")
    if r.status_code not in (200, 201):
        raise StripeError("Stripe refused the checkout. Please try again later.")
    try:
        url = r.json().get("url")
    except Exception:
        url = None
    if not url:
        raise StripeError("Stripe did not return a checkout page. Please try again later.")
    return url


def verify_webhook_signature(payload: bytes, sig_header: str | None,
                             secret: str | None) -> bool:
    """Stripe's scheme: header 't=<ts>,v1=<sig>[,v1=...]'; signature is over
    '<ts>.<raw payload>'. Rejects stale timestamps (5-min replay window)."""
    if not sig_header or not secret:
        return False
    parts: dict = {}
    for item in sig_header.split(","):
        if "=" in item:
            k, v = item.split("=", 1)
            parts.setdefault(k.strip(), []).append(v.strip())
    ts_list, sigs = parts.get("t", []), parts.get("v1", [])
    if not ts_list or not sigs:
        return False
    try:
        if abs(time.time() - int(ts_list[0])) > 300:
            return False
    except (ValueError, IndexError):
        return False
    expected = hmac.new(secret.encode(),
                        ts_list[0].encode() + b"." + payload,
                        hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, s) for s in sigs)

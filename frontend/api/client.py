"""Thin REST client for the FastAPI backend. The frontend never touches the DB, Groq or Gnani directly."""
from __future__ import annotations

import os

import httpx

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip("/")
# URL the *browser* can reach (may differ from BACKEND_URL inside Docker). Use an https:// tunnel URL for phones.
PUBLIC_URL = os.getenv("BACKEND_PUBLIC_URL", BACKEND_URL).rstrip("/")


class ApiError(RuntimeError):
    pass


def _req(method: str, path: str, **kw):
    try:
        r = httpx.request(method, f"{BACKEND_URL}/api{path}", timeout=kw.pop("timeout", 30), **kw)
    except httpx.HTTPError as exc:
        raise ApiError(f"Backend unreachable at {BACKEND_URL}: {exc}") from exc
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail", r.text)
        except Exception:  # noqa: BLE001
            detail = r.text
        raise ApiError(f"{r.status_code}: {detail}")
    return r.json()


def health(): return _req("GET", "/health")
def list_customers(): return _req("GET", "/customers")
def customer_detail(cid: str): return _req("GET", f"/customers/{cid}")
def list_products(): return _req("GET", "/products")
def create_conversation(customer_id: str | None): return _req("POST", "/conversations", json={"customer_id": customer_id})
def list_conversations(customer_id: str | None = None): return _req("GET", "/conversations", params={"customer_id": customer_id} if customer_id else None)
def conversation(cid: str): return _req("GET", f"/conversations/{cid}")
def messages(cid: str): return _req("GET", f"/conversations/{cid}/messages")
def events(cid: str, after: int = 0): return _req("GET", f"/conversations/{cid}/events", params={"after": after})
def pending_action(cid: str): return _req("GET", f"/conversations/{cid}/pending-action")
def end_conversation(cid: str): return _req("POST", f"/conversations/{cid}/end")
def confirm_action(cid: str, decision: str, action_id: str | None): return _req("POST", f"/conversations/{cid}/confirm-action", json={"decision": decision, "action_id": action_id})
def run_evaluation(datasets, max_cases, use_judge): return _req("POST", "/evaluations/run", json={"datasets": datasets or None, "max_cases": max_cases, "use_judge": use_judge})
def list_evaluations(): return _req("GET", "/evaluations")
def get_evaluation(eid: str): return _req("GET", f"/evaluations/{eid}")
def voice_client_url(conversation_id: str | None = None, customer_id: str | None = None) -> str:
    url = f"{PUBLIC_URL}/api/voice/client" + (f"/{conversation_id}" if conversation_id else "")
    return url + (f"?customer_id={customer_id}" if customer_id and not conversation_id else "")


# ---- customer management / edits / change log
def create_customer(payload: dict): return _req("POST", "/customers", json=payload)
def update_customer(cid: str, payload: dict): return _req("PATCH", f"/customers/{cid}", json=payload)
def deactivate_customer(cid: str): return _req("POST", f"/customers/{cid}/deactivate")
def activate_customer(cid: str): return _req("POST", f"/customers/{cid}/activate")
def delete_customer(cid: str): return _req("DELETE", f"/customers/{cid}")
def generate_demo(count: int, with_orders: bool): return _req("POST", "/customers/demo", json={"count": count, "with_orders": with_orders}, timeout=60)
def update_order_address(order_id: str, customer_id: str, address: dict):
    return _req("PATCH", f"/orders/{order_id}/address", params={"customer_id": customer_id}, json={"address": address})
def customer_changes(cid: str): return _req("GET", f"/customers/{cid}/changes")
def all_changes(limit: int = 500): return _req("GET", "/changes", params={"limit": limit})

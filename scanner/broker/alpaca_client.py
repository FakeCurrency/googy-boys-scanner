"""Thin REST wrapper around the Alpaca API v2.

Auth via env vars — both must be set:
  ALPACA_API_KEY     Alpaca key ID
  ALPACA_SECRET_KEY  Alpaca secret key

Mode:
  ALPACA_LIVE=true   → live endpoint (api.alpaca.markets)
  default            → paper endpoint (paper-api.alpaca.markets)
"""

import os
import requests

_PAPER = "https://paper-api.alpaca.markets/v2"
_LIVE  = "https://api.alpaca.markets/v2"


def _base() -> str:
    return _LIVE if os.environ.get("ALPACA_LIVE", "").lower() == "true" else _PAPER


def _headers() -> dict:
    return {
        "APCA-API-KEY-ID":     os.environ["ALPACA_API_KEY"],
        "APCA-API-SECRET-KEY": os.environ["ALPACA_SECRET_KEY"],
        "accept":              "application/json",
        "content-type":        "application/json",
    }


def get(path: str, params: dict | None = None) -> dict | list:
    r = requests.get(f"{_base()}{path}", headers=_headers(), params=params, timeout=15)
    r.raise_for_status()
    return r.json()


def post(path: str, body: dict) -> dict:
    r = requests.post(f"{_base()}{path}", headers=_headers(), json=body, timeout=15)
    r.raise_for_status()
    return r.json()


def delete(path: str, params: dict | None = None) -> dict | list:
    r = requests.delete(f"{_base()}{path}", headers=_headers(), params=params, timeout=15)
    if r.status_code in (200, 207):
        return r.json()
    r.raise_for_status()
    return {}


# ── convenience wrappers ──────────────────────────────────────────────────────

def account() -> dict:
    return get("/account")


def positions() -> list:
    return get("/positions")


def open_orders() -> list:
    return get("/orders", params={"status": "open", "limit": 100, "nested": "true"})


def closed_orders(after: str | None = None) -> list:
    params = {"status": "closed", "limit": 100, "nested": "true"}
    if after:
        params["after"] = after
    return get("/orders", params=params)


def get_order(order_id: str) -> dict:
    return get(f"/orders/{order_id}")


def cancel_all_orders() -> list:
    return delete("/orders")


def close_all_positions() -> list:
    return delete("/positions", params={"cancel_orders": "true"})

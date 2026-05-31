"""Alpaca Paper-Trading broker wrapper.

HARD SANDBOX. Defense-in-depth refusals:
  1. Base URL must equal https://paper-api.alpaca.markets/v2 — any other URL
     raises BrokerSandboxError. There is no flag to switch to live trading.
  2. ALPACA_PAPER env must be the literal string "true".
  3. The Alpaca `account_number` returned by /v2/account must start with "PA"
     (Alpaca's paper-account prefix). Otherwise refused on first call.
  4. Symbols in BLOCKED_SYMBOLS (leveraged/inverse/vol ETFs) are refused.
  5. Per-order notional capped at STOCK_REC_MAX_ORDER_USD (default $1000).
  6. Post-trade per-symbol notional capped at STOCK_REC_MAX_SYMBOL_PCT % of
     equity (default 20%).

All read calls work with valid paper credentials. All write calls additionally
require STOCK_REC_MCP_TRADING_ENABLED="true" (enforced one layer up in
mcp_server/safety.py).
"""
from __future__ import annotations

import math
import os
import time
from typing import Any

import requests


PAPER_BASE_URL = "https://paper-api.alpaca.markets/v2"
DATA_BASE_URL = "https://data.alpaca.markets/v2"

BLOCKED_SYMBOLS: set[str] = {
    # 2x/3x leveraged
    "TQQQ", "SQQQ", "SOXL", "SOXS", "FAS", "FAZ", "TNA", "TZA",
    "UPRO", "SPXU", "UDOW", "SDOW", "LABU", "LABD", "NUGT", "DUST",
    "JNUG", "JDST", "ERX", "ERY", "YINN", "YANG", "BOIL", "KOLD",
    "GUSH", "DRIP", "URTY", "SRTY", "TMF", "TMV",
    # Volatility
    "UVXY", "VXX", "SVXY", "VIXY",
    # Single-stock leveraged
    "TSLL", "TSLQ", "TSLT", "NVDL", "NVDS", "NVDU", "AAPU", "AAPD",
    "CONL", "MSTU", "MSTX",
    # Inverse
    "SH", "SDS", "QID", "PSQ", "DOG", "DXD", "RWM",
}


class BrokerSandboxError(RuntimeError):
    """Raised when a request would breach the sandbox guarantees."""


class BrokerCapExceeded(RuntimeError):
    """Raised when an order would breach per-order or per-symbol caps."""


# ============================================================
# Env / config helpers
# ============================================================

def _env(key: str, default: str | None = None) -> str | None:
    """Read from env first, fall back to streamlit.secrets if available."""
    v = os.environ.get(key)
    if v is not None and v != "":
        return v
    try:
        import streamlit as st  # type: ignore
        if hasattr(st, "secrets") and key in st.secrets:
            return str(st.secrets[key])
    except Exception:
        pass
    return default


def _max_order_usd() -> float:
    return float(_env("STOCK_REC_MAX_ORDER_USD", "1000") or "1000")


def _max_symbol_pct() -> float:
    return float(_env("STOCK_REC_MAX_SYMBOL_PCT", "20") or "20")


def _base_url() -> str:
    # Hard-coded — NOT configurable via env. This prevents anyone (or any agent)
    # from redirecting traffic to the live brokerage endpoint.
    return PAPER_BASE_URL


def _headers() -> dict[str, str]:
    key_id = _env("ALPACA_API_KEY_ID")
    secret = _env("ALPACA_SECRET_KEY")
    if not key_id or not secret:
        raise BrokerSandboxError(
            "Alpaca paper credentials missing. Set ALPACA_API_KEY_ID and "
            "ALPACA_SECRET_KEY in env or .streamlit/secrets.toml."
        )
    return {
        "APCA-API-KEY-ID": key_id,
        "APCA-API-SECRET-KEY": secret,
        "Accept": "application/json",
    }


def _assert_paper_flag() -> None:
    flag = (_env("ALPACA_PAPER", "false") or "false").strip().lower()
    if flag != "true":
        raise BrokerSandboxError(
            "ALPACA_PAPER must be set to the literal string 'true' to use the broker."
        )


_VERIFIED_PAPER = False


def _assert_paper_account(account_payload: dict) -> None:
    """Verify the returned account is a paper account (account_number starts with PA)."""
    global _VERIFIED_PAPER
    acct_no = str(account_payload.get("account_number") or "")
    if not acct_no.startswith("PA"):
        raise BrokerSandboxError(
            f"Refusing to operate: account_number {acct_no!r} is NOT a paper account "
            "(expected prefix 'PA'). Did you use live API keys?"
        )
    _VERIFIED_PAPER = True


# ============================================================
# Low-level HTTP
# ============================================================

def _request(method: str, path: str, **kwargs: Any) -> Any:
    _assert_paper_flag()
    url = _base_url().rstrip("/") + "/" + path.lstrip("/")
    # Belt + suspenders: refuse if the URL drifted away from paper.
    if not url.startswith("https://paper-api.alpaca.markets/"):
        raise BrokerSandboxError(f"Refusing non-paper URL: {url}")
    headers = {**_headers(), **kwargs.pop("headers", {})}
    timeout = kwargs.pop("timeout", 15)
    resp = requests.request(method, url, headers=headers, timeout=timeout, **kwargs)
    if resp.status_code >= 400:
        raise RuntimeError(f"Alpaca {method} {path} failed [{resp.status_code}]: {resp.text}")
    try:
        return resp.json()
    except ValueError:
        return resp.text


# ============================================================
# Read endpoints
# ============================================================

def get_account() -> dict:
    payload = _request("GET", "/account")
    _assert_paper_account(payload)
    return payload


def list_positions() -> list[dict]:
    if not _VERIFIED_PAPER:
        get_account()
    return _request("GET", "/positions") or []


def list_orders(status: str = "open", limit: int = 50) -> list[dict]:
    if not _VERIFIED_PAPER:
        get_account()
    return _request("GET", "/orders", params={"status": status, "limit": limit}) or []


def get_position(symbol: str) -> dict | None:
    if not _VERIFIED_PAPER:
        get_account()
    try:
        return _request("GET", f"/positions/{symbol.upper()}")
    except RuntimeError as e:
        if "404" in str(e) or "position does not exist" in str(e).lower():
            return None
        raise


def get_last_price(symbol: str) -> float | None:
    """Last trade price from Alpaca data API (paper key works for IEX data)."""
    key_id = _env("ALPACA_API_KEY_ID")
    secret = _env("ALPACA_SECRET_KEY")
    if not key_id or not secret:
        return None
    try:
        r = requests.get(
            f"{DATA_BASE_URL}/stocks/{symbol.upper()}/trades/latest",
            headers={"APCA-API-KEY-ID": key_id, "APCA-API-SECRET-KEY": secret},
            timeout=10,
        )
        if r.status_code != 200:
            return None
        return float(r.json().get("trade", {}).get("p") or 0) or None
    except Exception:
        return None


# ============================================================
# Write endpoints (still gated by env; mcp_server adds another gate)
# ============================================================

def _assert_symbol_allowed(symbol: str) -> None:
    s = symbol.upper().strip()
    if s in BLOCKED_SYMBOLS:
        raise BrokerSandboxError(
            f"Symbol {s} is blocked (leveraged/inverse/volatility product). "
            "These are disabled in the agent sandbox to prevent rapid capital loss."
        )


def _assert_caps(symbol: str, qty: float, price: float, equity: float) -> None:
    notional = abs(qty) * price
    if notional > _max_order_usd():
        raise BrokerCapExceeded(
            f"Order notional ${notional:.2f} exceeds per-order cap "
            f"${_max_order_usd():.2f} (STOCK_REC_MAX_ORDER_USD)."
        )
    sym_cap = _max_symbol_pct() / 100.0 * equity
    existing = get_position(symbol)
    existing_notional = abs(float(existing.get("market_value") or 0)) if existing else 0.0
    if existing_notional + notional > sym_cap + 1e-6:
        raise BrokerCapExceeded(
            f"Post-trade {symbol} notional ${existing_notional + notional:.2f} "
            f"exceeds per-symbol cap ${sym_cap:.2f} "
            f"({_max_symbol_pct():.0f}% of equity)."
        )


def place_order(
    symbol: str,
    qty: float,
    side: str,
    order_type: str = "market",
    time_in_force: str = "day",
    limit_price: float | None = None,
    client_order_id: str | None = None,
) -> dict:
    """Submit a paper order. Enforces blocklist + per-order + per-symbol caps."""
    sym = symbol.upper().strip()
    if side not in ("buy", "sell"):
        raise ValueError("side must be 'buy' or 'sell'")
    if order_type not in ("market", "limit"):
        raise ValueError("order_type must be 'market' or 'limit'")
    if time_in_force not in ("day", "gtc", "ioc", "fok"):
        raise ValueError("invalid time_in_force")
    _assert_symbol_allowed(sym)

    acct = get_account()
    equity = float(acct.get("equity") or 0)
    price = float(limit_price) if (order_type == "limit" and limit_price) else (get_last_price(sym) or 0)
    if price <= 0:
        raise RuntimeError(f"Could not determine price for {sym}; cap check requires a price.")
    _assert_caps(sym, qty, price, equity)

    body: dict[str, Any] = {
        "symbol": sym,
        "qty": str(qty),
        "side": side,
        "type": order_type,
        "time_in_force": time_in_force,
    }
    if order_type == "limit" and limit_price is not None:
        body["limit_price"] = str(limit_price)
    if client_order_id:
        body["client_order_id"] = client_order_id
    return _request("POST", "/orders", json=body)


def cancel_order(order_id: str) -> dict:
    if not _VERIFIED_PAPER:
        get_account()
    _request("DELETE", f"/orders/{order_id}")
    return {"ok": True, "order_id": order_id}


def cancel_all_orders() -> list[dict]:
    if not _VERIFIED_PAPER:
        get_account()
    result = _request("DELETE", "/orders")
    return result or []


def close_position(symbol: str, percentage: float | None = None) -> dict:
    """Liquidate a position. `percentage` 1-100, omitted = full close."""
    if not _VERIFIED_PAPER:
        get_account()
    sym = symbol.upper().strip()
    params: dict[str, Any] = {}
    if percentage is not None:
        if not (0 < percentage <= 100):
            raise ValueError("percentage must be in (0, 100]")
        params["percentage"] = str(percentage)
    return _request("DELETE", f"/positions/{sym}", params=params or None)


# ============================================================
# Rebalance — derives orders from target dollar weights
# ============================================================

def rebalance_to_targets(
    targets: dict[str, float],
    dry_run: bool = True,
    min_trade_usd: float = 25.0,
    cash_buffer_pct: float = 5.0,
) -> list[dict]:
    """Submit orders to move current paper positions toward `targets`.

    Args:
        targets: {symbol: target_dollar_value}
        dry_run: if True, returns the planned orders without submitting.
        min_trade_usd: skip trades whose absolute notional delta is below this.
        cash_buffer_pct: reserve % of equity as cash (don't deploy 100%).

    Returns: list of planned/submitted order dicts.
    """
    if not targets:
        return []
    # Validate every symbol up front; refuse the whole batch if any is blocked.
    for sym in targets:
        _assert_symbol_allowed(sym)

    acct = get_account()
    equity = float(acct.get("equity") or 0)
    sym_cap_usd = _max_symbol_pct() / 100.0 * equity
    # Clip targets to per-symbol cap so we never plan an over-cap allocation.
    clipped = {s: min(float(v), sym_cap_usd) for s, v in targets.items()}

    # Honor cash buffer: scale targets down if their sum > (1 - buffer) * equity
    deployable = max((1 - cash_buffer_pct / 100.0) * equity, 0.0)
    total_target = sum(clipped.values()) or 1
    if total_target > deployable > 0:
        scale = deployable / total_target
        clipped = {s: v * scale for s, v in clipped.items()}

    positions = {p["symbol"]: p for p in list_positions()}

    plan: list[dict] = []
    for sym, target_usd in clipped.items():
        current_usd = float(positions.get(sym, {}).get("market_value") or 0)
        delta_usd = target_usd - current_usd
        if abs(delta_usd) < min_trade_usd:
            continue
        price = get_last_price(sym) or 0
        if price <= 0:
            plan.append({"symbol": sym, "skipped": True, "reason": "no_price"})
            continue
        shares = math.floor(abs(delta_usd) / price)
        if shares <= 0:
            continue
        side = "buy" if delta_usd > 0 else "sell"
        # Slice if larger than per-order cap.
        max_shares_per_order = max(math.floor(_max_order_usd() / price), 1)
        remaining = shares
        slices: list[dict] = []
        while remaining > 0:
            n = min(remaining, max_shares_per_order)
            order = {
                "symbol": sym, "side": side, "qty": n,
                "order_type": "market", "time_in_force": "day",
                "est_notional": round(n * price, 2),
                "current_usd": round(current_usd, 2),
                "target_usd": round(target_usd, 2),
            }
            slices.append(order)
            remaining -= n
        plan.extend(slices)

    if dry_run:
        return [{**o, "dry_run": True} for o in plan]

    submitted: list[dict] = []
    for o in plan:
        if o.get("skipped"):
            submitted.append(o)
            continue
        try:
            resp = place_order(
                symbol=o["symbol"], qty=o["qty"], side=o["side"],
                order_type=o["order_type"], time_in_force=o["time_in_force"],
            )
            submitted.append({**o, "order_id": resp.get("id"), "status": resp.get("status")})
        except (BrokerCapExceeded, BrokerSandboxError) as e:
            submitted.append({**o, "error": str(e)})
        # Be gentle with the API
        time.sleep(0.1)
    return submitted

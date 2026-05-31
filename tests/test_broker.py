"""Guard-rail tests for src/broker.py.

These tests never touch the network: requests are intercepted via `responses`
or by monkeypatching `requests.request`. The point is to prove that the
sandbox guards refuse anything that could leak to a live account.
"""
from __future__ import annotations

import json
import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import broker


PAPER_ACCT = {
    "account_number": "PA12345678",
    "equity": "10000",
    "buying_power": "20000",
    "cash": "5000",
    "status": "ACTIVE",
}


@pytest.fixture(autouse=True)
def _reset_verified():
    broker._VERIFIED_PAPER = False
    yield
    broker._VERIFIED_PAPER = False


@pytest.fixture
def paper_env(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY_ID", "PKTEST")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "secret")
    monkeypatch.setenv("ALPACA_PAPER", "true")
    monkeypatch.setenv("STOCK_REC_MAX_ORDER_USD", "1000")
    monkeypatch.setenv("STOCK_REC_MAX_SYMBOL_PCT", "20")
    # Skip Streamlit secret lookups
    monkeypatch.setitem(sys.modules, "streamlit", None)
    yield


# ---------- Hard sandbox refusals ----------

def test_refuses_without_paper_flag(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY_ID", "PKTEST")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "secret")
    monkeypatch.setenv("ALPACA_PAPER", "false")
    with pytest.raises(broker.BrokerSandboxError, match="ALPACA_PAPER"):
        broker.get_account()


def test_refuses_without_credentials(monkeypatch):
    monkeypatch.setenv("ALPACA_PAPER", "true")
    monkeypatch.delenv("ALPACA_API_KEY_ID", raising=False)
    monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)
    monkeypatch.setitem(sys.modules, "streamlit", None)
    with pytest.raises(broker.BrokerSandboxError, match="credentials"):
        broker.get_account()


def test_base_url_is_paper_only():
    assert broker._base_url() == broker.PAPER_BASE_URL
    assert "paper-api.alpaca.markets" in broker._base_url()


def test_refuses_non_paper_account(paper_env):
    live_acct = {"account_number": "12345LIVE", "equity": "10000"}
    with patch.object(broker.requests, "request") as mreq:
        mreq.return_value.status_code = 200
        mreq.return_value.json.return_value = live_acct
        with pytest.raises(broker.BrokerSandboxError, match="paper"):
            broker.get_account()


# ---------- Blocklist ----------

@pytest.mark.parametrize("sym", ["TQQQ", "UVXY", "SOXL", "TSLL", "SQQQ"])
def test_blocked_symbols_refused(paper_env, sym):
    with patch.object(broker.requests, "request") as mreq:
        mreq.return_value.status_code = 200
        mreq.return_value.json.return_value = PAPER_ACCT
        with pytest.raises(broker.BrokerSandboxError, match="blocked"):
            broker.place_order(symbol=sym, qty=1, side="buy")


# ---------- Per-order cap ----------

def test_per_order_cap_enforced(paper_env, monkeypatch):
    monkeypatch.setenv("STOCK_REC_MAX_ORDER_USD", "500")

    def fake_request(method, url, **kw):
        class R:
            status_code = 200
            text = ""
            def json(self_inner):
                if "/account" in url:
                    return PAPER_ACCT
                if "/positions/" in url:
                    raise RuntimeError("404 not found")
                return {}
        if "/positions/AAPL" in url:
            r = R(); r.status_code = 404; r.text = "position does not exist"
            return r
        return R()

    with patch.object(broker.requests, "request", side_effect=fake_request), \
         patch.object(broker, "get_last_price", return_value=200.0):
        # 10 * 200 = $2000 > $500 cap
        with pytest.raises(broker.BrokerCapExceeded, match="per-order cap"):
            broker.place_order(symbol="AAPL", qty=10, side="buy")


# ---------- Per-symbol cap ----------

def test_per_symbol_cap_enforced(paper_env):
    # equity 10000, cap 20% = $2000; existing position $1500 + new $800 = $2300 > 2000
    existing = {"symbol": "AAPL", "market_value": "1500"}

    def fake_request(method, url, **kw):
        class R:
            status_code = 200
            text = ""
            def json(self_inner):
                if url.endswith("/account"):
                    return PAPER_ACCT
                if "/positions/AAPL" in url:
                    return existing
                return {}
        return R()

    with patch.object(broker.requests, "request", side_effect=fake_request), \
         patch.object(broker, "get_last_price", return_value=100.0):
        with pytest.raises(broker.BrokerCapExceeded, match="per-symbol cap"):
            broker.place_order(symbol="AAPL", qty=8, side="buy")  # 8*100=800


# ---------- Successful order path ----------

def test_place_order_happy_path(paper_env):
    captured: dict = {}

    def fake_request(method, url, **kw):
        class R:
            status_code = 200
            text = ""
            def json(self_inner):
                if url.endswith("/account"):
                    return PAPER_ACCT
                if "/positions/AAPL" in url and method == "GET":
                    raise RuntimeError("404")
                if url.endswith("/orders") and method == "POST":
                    captured["body"] = kw.get("json")
                    return {"id": "order-1", "status": "accepted"}
                return {}
        if "/positions/AAPL" in url:
            r = R(); r.status_code = 404; r.text = "position does not exist"
            return r
        return R()

    with patch.object(broker.requests, "request", side_effect=fake_request), \
         patch.object(broker, "get_last_price", return_value=100.0):
        result = broker.place_order(symbol="AAPL", qty=1, side="buy")
    assert result["id"] == "order-1"
    assert captured["body"]["symbol"] == "AAPL"
    assert captured["body"]["side"] == "buy"


# ---------- Rebalance dry-run ----------

def test_rebalance_dry_run_does_not_submit(paper_env):
    calls: list[tuple[str, str]] = []

    def fake_request(method, url, **kw):
        calls.append((method, url))
        class R:
            status_code = 200
            text = ""
            def json(self_inner):
                if url.endswith("/account"):
                    return PAPER_ACCT
                if url.endswith("/positions"):
                    return []
                return {}
        return R()

    with patch.object(broker.requests, "request", side_effect=fake_request), \
         patch.object(broker, "get_last_price", return_value=100.0):
        plan = broker.rebalance_to_targets({"AAPL": 500.0, "MSFT": 500.0}, dry_run=True)
    assert all(o.get("dry_run") for o in plan)
    assert {o["symbol"] for o in plan} == {"AAPL", "MSFT"}
    # No POST /orders
    assert all(not (m == "POST" and u.endswith("/orders")) for m, u in calls)

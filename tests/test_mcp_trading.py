"""Tests for the MCP server's trading-gate behavior.

We don't spin up the stdio server; we call the dispatch directly.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def server_module(monkeypatch, tmp_path):
    monkeypatch.setenv("STOCK_REC_AUDIT_DB", str(tmp_path / "audit.sqlite"))
    monkeypatch.setenv("ALPACA_API_KEY_ID", "PKTEST")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "secret")
    monkeypatch.setenv("ALPACA_PAPER", "true")
    # Default: trading OFF
    monkeypatch.delenv("STOCK_REC_MCP_TRADING_ENABLED", raising=False)
    from mcp_server import server
    import importlib
    importlib.reload(server)
    return server


def _call(server, name: str, args: dict | None = None):
    res = asyncio.run(server.call_tool(name, args or {}))
    return json.loads(res[0].text)


def test_write_tool_blocked_when_trading_disabled(server_module):
    payload = _call(server_module, "place_order",
                    {"symbol": "AAPL", "qty": 1, "side": "buy"})
    assert payload["blocked"] == "trading_disabled"


def test_read_tools_work_without_trading_flag(server_module):
    # get_account hits broker → mock requests
    paper_acct = {
        "account_number": "PA42", "equity": "10000",
        "buying_power": "20000", "cash": "5000",
    }
    with patch("src.broker.requests.request") as mreq:
        mreq.return_value.status_code = 200
        mreq.return_value.json.return_value = paper_acct
        payload = _call(server_module, "get_account", {})
    assert payload["account_number"] == "PA42"


def test_audit_log_recorded(server_module, tmp_path):
    _call(server_module, "place_order", {"symbol": "AAPL", "qty": 1, "side": "buy"})
    from mcp_server import audit
    rows = audit.recent(10)
    assert any(r["tool"] == "place_order" and r["result_status"] == "blocked" for r in rows)


def test_rebalance_dry_run_through_mcp(server_module, monkeypatch):
    monkeypatch.setenv("STOCK_REC_MCP_TRADING_ENABLED", "true")
    import importlib
    from mcp_server import safety, server as srv
    importlib.reload(safety)
    importlib.reload(srv)

    # Stub the screener pipeline so we don't hit yfinance
    import pandas as pd
    fake_alloc = pd.DataFrame([
        {"ticker": "AAPL", "name": "Apple", "sector": "Tech", "price": 100.0,
         "beta": 1.0, "risk_label": "Medium", "weight_pct": 50.0,
         "target_dollars": 2500.0, "shares": 25, "actual_dollars": 2500.0},
        {"ticker": "MSFT", "name": "Msft", "sector": "Tech", "price": 250.0,
         "beta": 0.9, "risk_label": "Medium", "weight_pct": 50.0,
         "target_dollars": 2500.0, "shares": 10, "actual_dollars": 2500.0},
    ])
    paper_acct = {"account_number": "PA42", "equity": "10000",
                  "buying_power": "20000", "cash": "10000"}

    def fake_request(method, url, **kw):
        class R:
            status_code = 200
            text = ""
            def json(self_inner):
                if url.endswith("/account"):
                    return paper_acct
                if url.endswith("/positions"):
                    return []
                return {}
        return R()

    with patch("src.broker.requests.request", side_effect=fake_request), \
         patch("src.broker.get_last_price", side_effect=lambda s: 100.0 if s == "AAPL" else 250.0), \
         patch.object(srv, "_build_picks", return_value=fake_alloc), \
         patch("src.portfolio.allocate", return_value=fake_alloc):
        payload = _call(srv, "rebalance_to_recommendations",
                        {"budget": 5000, "dry_run": True})
    assert payload["dry_run"] is True
    assert payload["orders"]
    assert all(o.get("dry_run") for o in payload["orders"])

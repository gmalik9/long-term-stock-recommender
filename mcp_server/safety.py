"""Safety gates for MCP write tools."""
from __future__ import annotations

import os


def _env(key: str, default: str | None = None) -> str | None:
    v = os.environ.get(key)
    if v:
        return v
    try:
        import streamlit as st  # type: ignore
        if hasattr(st, "secrets") and key in st.secrets:
            return str(st.secrets[key])
    except Exception:
        pass
    return default


def trading_enabled() -> bool:
    """Master kill-switch for any WRITE tool (place/cancel/close/rebalance)."""
    return (_env("STOCK_REC_MCP_TRADING_ENABLED", "false") or "false").strip().lower() == "true"


def trading_disabled_payload() -> dict:
    return {
        "blocked": "trading_disabled",
        "message": (
            "Trading is disabled. Set STOCK_REC_MCP_TRADING_ENABLED='true' "
            "(env or .streamlit/secrets.toml) AND ALPACA_PAPER='true' "
            "AND valid paper API keys to enable write tools. "
            "This server only ever talks to https://paper-api.alpaca.markets."
        ),
    }

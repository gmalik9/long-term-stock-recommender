"""MCP server for stock-recommender.

READ tools surface the screener / portfolio / news engine to agents.
WRITE tools place orders against the Alpaca PAPER endpoint only and are
gated by STOCK_REC_MCP_TRADING_ENABLED.

Run on stdio:
    python -m mcp_server.server
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp_server import audit, safety  # noqa: E402
from src import broker  # noqa: E402
from src import portfolio, screener, sentiment  # noqa: E402
from src.data_fetcher import (  # noqa: E402
    fetch_fundamentals_bulk,
    fetch_news_bulk,
    fetch_one_news_fresh,
    fetch_one_ticker_fresh,
)
from src.universe import get_universe  # noqa: E402

try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Resource, TextContent, Tool
except ImportError:  # pragma: no cover
    print("MCP SDK not installed. `pip install mcp` first.", file=sys.stderr)
    raise


server = Server("stock-recommender")
CALLER = "mcp"


# ============================================================
# Tool catalog
# ============================================================

TOOL_DEFS: list[Tool] = [
    # ---- READ ----
    Tool(
        name="get_recommendations",
        description=(
            "Run the long-term screener: fetch fundamentals, score news sentiment, "
            "filter, score, and diversify across sectors. Returns the top picks."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "universe": {"type": "string", "default": "Curated",
                             "description": "Curated | S&P500 | Curated+S&P500"},
                "max_per_sector": {"type": "integer", "default": 3, "minimum": 1, "maximum": 10},
                "top_n": {"type": "integer", "default": 18, "minimum": 1, "maximum": 50},
            },
        },
    ),
    Tool(
        name="get_portfolio_suggestion",
        description=(
            "Long-term $5,000 inverse-beta portfolio allocation across top picks. "
            "Read-only: returns target dollars + share counts; does NOT place orders."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "budget": {"type": "number", "default": 5000, "minimum": 100, "maximum": 1000000},
                "universe": {"type": "string", "default": "Curated"},
                "top_n": {"type": "integer", "default": 18, "minimum": 1, "maximum": 50},
            },
        },
    ),
    Tool(
        name="lookup_ticker",
        description="Fundamentals snapshot (price, beta, PEG, analyst rating, 52w range) for a single ticker.",
        inputSchema={
            "type": "object",
            "properties": {"ticker": {"type": "string"}},
            "required": ["ticker"],
        },
    ),
    Tool(
        name="get_news",
        description="Recent news for a ticker (aggregated from 9 sources) with VADER sentiment per article.",
        inputSchema={
            "type": "object",
            "properties": {
                "ticker": {"type": "string"},
                "days": {"type": "integer", "default": 7, "minimum": 1, "maximum": 30},
                "limit": {"type": "integer", "default": 20, "minimum": 1, "maximum": 100},
            },
            "required": ["ticker"],
        },
    ),
    Tool(
        name="get_account",
        description="Alpaca PAPER account: equity, buying power, cash. Read-only. Requires paper credentials.",
        inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
    ),
    Tool(
        name="list_positions",
        description="Current Alpaca PAPER positions.",
        inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
    ),
    Tool(
        name="list_orders",
        description="Alpaca PAPER orders.",
        inputSchema={
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["open", "closed", "all"], "default": "open"},
                "limit": {"type": "integer", "default": 50, "minimum": 1, "maximum": 500},
            },
        },
    ),

    # ---- WRITE (gated) ----
    Tool(
        name="place_order",
        description=(
            "Submit a PAPER order to Alpaca. Sandbox-only; live trading is refused at the broker boundary. "
            "Per-order notional cap (default $1000) and per-symbol equity cap (default 20%) enforced. "
            "Leveraged/inverse/volatility ETFs are blocked."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "qty": {"type": "number", "exclusiveMinimum": 0},
                "side": {"type": "string", "enum": ["buy", "sell"]},
                "order_type": {"type": "string", "enum": ["market", "limit"], "default": "market"},
                "time_in_force": {"type": "string", "enum": ["day", "gtc", "ioc", "fok"], "default": "day"},
                "limit_price": {"type": "number"},
            },
            "required": ["symbol", "qty", "side"],
        },
    ),
    Tool(
        name="cancel_order",
        description="Cancel one PAPER order by id.",
        inputSchema={
            "type": "object",
            "properties": {"order_id": {"type": "string"}},
            "required": ["order_id"],
        },
    ),
    Tool(
        name="cancel_all_orders",
        description="Cancel all open PAPER orders.",
        inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
    ),
    Tool(
        name="close_position",
        description="Liquidate a PAPER position (full close, or `percentage` 1-100).",
        inputSchema={
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "percentage": {"type": "number", "exclusiveMinimum": 0, "maximum": 100},
            },
            "required": ["symbol"],
        },
    ),
    Tool(
        name="rebalance_to_recommendations",
        description=(
            "Run the screener, build the $5,000 inverse-beta portfolio, then submit PAPER orders "
            "to move current paper positions toward that allocation. `dry_run=true` returns the plan "
            "without submitting. Per-order and per-symbol caps apply."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "budget": {"type": "number", "default": 5000, "minimum": 100, "maximum": 1000000},
                "universe": {"type": "string", "default": "Curated"},
                "top_n": {"type": "integer", "default": 18, "minimum": 1, "maximum": 50},
                "dry_run": {"type": "boolean", "default": True},
                "cash_buffer_pct": {"type": "number", "default": 5.0, "minimum": 0, "maximum": 50},
            },
        },
    ),
]

WRITE_TOOLS = {
    "place_order", "cancel_order", "cancel_all_orders",
    "close_position", "rebalance_to_recommendations",
}


# ============================================================
# Recommendation pipeline (mirrors app.py)
# ============================================================

def _build_picks(universe_name: str, top_n: int, max_per_sector: int = 3):
    tickers = tuple(get_universe(universe_name))
    fundamentals = fetch_fundamentals_bulk(tickers)
    if fundamentals.empty:
        return fundamentals
    news_map = fetch_news_bulk(tickers, days=7)
    sentiment_rows = {
        t: sentiment.score_news(news_map.get(t, [])) for t in fundamentals["ticker"]
    }
    fundamentals["sentiment_score"] = fundamentals["ticker"].map(
        lambda t: sentiment_rows.get(t, {}).get("score", 0.0)
    )
    fundamentals["sentiment_label"] = fundamentals["ticker"].map(
        lambda t: sentiment_rows.get(t, {}).get("label", "Neutral")
    )
    screened = screener.screen(fundamentals)
    scored = screener.score(screened)
    return screener.diversify(scored, max_per_sector=max_per_sector, top_n=top_n)


# ============================================================
# Tool router
# ============================================================

@server.list_tools()
async def list_tools() -> list[Tool]:
    return TOOL_DEFS


def _text(payload: Any) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps(payload, default=str, indent=2))]


@server.call_tool()
async def call_tool(name: str, arguments: dict | None = None) -> list[TextContent]:
    args = arguments or {}

    # ---------- Gate WRITE tools ----------
    if name in WRITE_TOOLS and not safety.trading_enabled():
        payload = safety.trading_disabled_payload()
        audit.record(CALLER, name, args, "blocked", payload)
        return _text(payload)

    try:
        result = _dispatch(name, args)
        audit.record(CALLER, name, args, "ok", result)
        return _text(result)
    except (broker.BrokerSandboxError, broker.BrokerCapExceeded) as e:
        payload = {"error": "sandbox_violation", "message": str(e), "tool": name}
        audit.record(CALLER, name, args, "blocked", payload)
        return _text(payload)
    except Exception as e:  # noqa: BLE001
        payload = {"error": type(e).__name__, "message": str(e), "tool": name}
        audit.record(CALLER, name, args, "error", payload)
        return _text(payload)


def _dispatch(name: str, args: dict) -> Any:
    # ---------- READ ----------
    if name == "get_recommendations":
        df = _build_picks(args.get("universe", "Curated"),
                          int(args.get("top_n", 18)),
                          int(args.get("max_per_sector", 3)))
        return {"count": len(df), "rows": df.to_dict(orient="records")}

    if name == "get_portfolio_suggestion":
        df = _build_picks(args.get("universe", "Curated"), int(args.get("top_n", 18)))
        budget = float(args.get("budget", 5000))
        alloc = portfolio.allocate(df, budget=budget)
        summary = portfolio.summary(alloc, df, budget=budget)
        return {
            "budget": budget,
            "allocation": alloc.to_dict(orient="records"),
            "summary": summary,
        }

    if name == "lookup_ticker":
        row = fetch_one_ticker_fresh(str(args["ticker"]).upper())
        return row or {"error": "no_data", "ticker": args.get("ticker")}

    if name == "get_news":
        tkr = str(args["ticker"]).upper()
        days = int(args.get("days", 7))
        limit = int(args.get("limit", 20))
        articles = fetch_one_news_fresh(tkr, days=days)
        for a in articles:
            a["sentiment"] = sentiment.score_article(a)
        return {"ticker": tkr, "count": len(articles), "articles": articles[:limit]}

    if name == "get_account":
        return broker.get_account()
    if name == "list_positions":
        return {"positions": broker.list_positions()}
    if name == "list_orders":
        status = args.get("status", "open")
        limit = int(args.get("limit", 50))
        return {"orders": broker.list_orders(status=status, limit=limit)}

    # ---------- WRITE ----------
    if name == "place_order":
        return broker.place_order(
            symbol=str(args["symbol"]),
            qty=float(args["qty"]),
            side=str(args["side"]),
            order_type=str(args.get("order_type", "market")),
            time_in_force=str(args.get("time_in_force", "day")),
            limit_price=float(args["limit_price"]) if args.get("limit_price") is not None else None,
        )
    if name == "cancel_order":
        return broker.cancel_order(str(args["order_id"]))
    if name == "cancel_all_orders":
        return {"canceled": broker.cancel_all_orders()}
    if name == "close_position":
        pct = args.get("percentage")
        return broker.close_position(str(args["symbol"]), percentage=float(pct) if pct else None)
    if name == "rebalance_to_recommendations":
        df = _build_picks(args.get("universe", "Curated"), int(args.get("top_n", 18)))
        budget = float(args.get("budget", 5000))
        alloc = portfolio.allocate(df, budget=budget)
        if alloc.empty:
            return {"error": "no_recommendations", "message": "Screener produced no picks."}
        targets = {row["ticker"]: float(row["target_dollars"]) for _, row in alloc.iterrows()}
        result = broker.rebalance_to_targets(
            targets=targets,
            dry_run=bool(args.get("dry_run", True)),
            cash_buffer_pct=float(args.get("cash_buffer_pct", 5.0)),
        )
        return {
            "budget": budget,
            "targets": targets,
            "dry_run": bool(args.get("dry_run", True)),
            "orders": result,
        }

    return {"error": f"unknown_tool: {name}"}


# ============================================================
# Resources
# ============================================================

@server.list_resources()
async def list_resources() -> list[Resource]:
    return [
        Resource(
            uri="audit://trades/recent",
            name="Recent audit log",
            mimeType="application/json",
            description="Last 200 MCP tool invocations (read + write).",
        )
    ]


@server.read_resource()
async def read_resource(uri: str) -> str:
    if str(uri) != "audit://trades/recent":
        return json.dumps({"error": "unknown resource"})
    return json.dumps({"rows": audit.recent(200)}, default=str)


# ============================================================
# Entrypoint
# ============================================================

async def _main() -> None:
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()

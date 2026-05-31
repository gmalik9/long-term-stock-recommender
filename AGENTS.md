# AGENTS.md — Operating envelope for algorithmic / LLM agents

This project exposes the **long-term recommendation engine** plus an
**Alpaca PAPER-trading** surface to agents via the Model Context Protocol.

## ⚠️ Sandbox guarantees

This MCP server **cannot place live (real-money) orders**, by construction:

1. The broker base URL is hard-coded to `https://paper-api.alpaca.markets/v2`.
   There is no env flag or config to switch it to a live endpoint.
2. The broker layer asserts `account_number` returned by Alpaca begins with
   `PA` (Alpaca's paper-account prefix) before any subsequent call is allowed.
3. `ALPACA_PAPER` env must equal the literal string `"true"` or every call
   refuses with `BrokerSandboxError`.
4. Write tools (`place_order`, `cancel_order`, `cancel_all_orders`,
   `close_position`, `rebalance_to_recommendations`) require
   `STOCK_REC_MCP_TRADING_ENABLED="true"`. Read tools do not.
5. Per-order notional cap: `STOCK_REC_MAX_ORDER_USD` (default $1,000).
6. Per-symbol position cap: `STOCK_REC_MAX_SYMBOL_PCT` of equity (default 20%).
7. Symbols on the leveraged / inverse / volatility blocklist are refused.
8. Every tool invocation (read or write, success or refusal) is appended to
   `data/trades.sqlite` (`audit://trades/recent` resource).

## Tools

### Read
| Tool | Purpose |
|---|---|
| `get_recommendations` | Run the screener + sector-diversify; returns top picks |
| `get_portfolio_suggestion` | $5k inverse-beta allocation across the picks |
| `lookup_ticker` | Fundamentals snapshot for one ticker |
| `get_news` | Aggregated news with per-article VADER sentiment |
| `get_account` | Paper account equity / buying power / cash |
| `list_positions` | Current paper positions |
| `list_orders` | Open or closed paper orders |

### Write (sandbox-only)
| Tool | Notes |
|---|---|
| `place_order` | Market or limit, day/gtc/ioc/fok. Caps enforced. |
| `cancel_order` | Cancel by order id |
| `cancel_all_orders` | Bulk cancel |
| `close_position` | Full liquidate, or `percentage` 1-100 |
| `rebalance_to_recommendations` | Pull picks → allocate $5k → diff vs current → submit deltas. `dry_run=true` returns plan only. |

## Recommended agent loop

1. `get_account` — confirm paper equity and buying power.
2. `get_recommendations` — see the screener picks.
3. `get_portfolio_suggestion` — preview the dollar allocation.
4. `rebalance_to_recommendations` with `dry_run=true` — preview the order plan.
5. (Optional) `rebalance_to_recommendations` with `dry_run=false` — submit.
6. `list_orders` + `list_positions` — verify state.

## Claude Desktop / agent runtime config

```json
{
  "mcpServers": {
    "stock-recommender": {
      "command": "python",
      "args": ["-m", "mcp_server.server"],
      "cwd": "/absolute/path/to/stock-recommender",
      "env": {
        "ALPACA_API_KEY_ID": "PK...",
        "ALPACA_SECRET_KEY": "...",
        "ALPACA_PAPER": "true",
        "STOCK_REC_MCP_TRADING_ENABLED": "true",
        "STOCK_REC_MAX_ORDER_USD": "1000",
        "STOCK_REC_MAX_SYMBOL_PCT": "20",
        "FINNHUB_API_KEY": "..."
      }
    }
  }
}
```

## Behavioral rules for the agent

- Always state "paper trading" when presenting results to a user.
- Prefer `dry_run=true` first; require user confirmation before re-running with `dry_run=false`.
- Never claim a real brokerage order was placed — there is none.
- Surface the `ts` from each call so freshness is visible.
- If a tool returns `{"blocked": ...}` or `{"error": "sandbox_violation", ...}`,
  do **not** retry by altering the request to bypass the guard. Report the
  refusal verbatim to the user.

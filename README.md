# Long-Term Stock Recommender

🚀 **Live app:** https://long-term-stock.streamlit.app/
📦 **Repo:** https://github.com/gmalik9/long-term-stock-recommender

> ⚡ Looking for short-term / day-trading signals? See the companion project:
> **Short-Term Trader** — repo: https://github.com/gmalik9/short-term-stock-recommender · live: https://short-term-stock.streamlit.app/

Streamlit dashboard that screens stocks for long-term investing (growth + value), surfaces analyst ratings and multi-source news sentiment, and allocates a $5,000 balanced portfolio. Refresh button re-fetches real-time data.

## Features
- **Real-time data** from `yfinance` (fundamentals + analyst ratings)
- **Multi-source news**: Finnhub, Yahoo RSS, StockTwits, SEC EDGAR, Alpha Vantage, Marketaux, NewsAPI (+ optional Tiingo, Reddit)
- **VADER NLP sentiment** on recent headlines + summaries with recency weighting
- **Screener**: PEG, beta, EPS growth, 52-week-high discount, analyst consensus, news sentiment
- **Composite score** combining upside %, rating, PEG, sentiment, discount
- **Diversified picks**: max-per-sector and ETF caps
- **$5,000 portfolio** with inverse-beta risk weighting
- **🔍 Lookup tab** for any US-listed ticker — fresh fundamentals + news on demand
- **Per-pick refresh** to re-fetch a single stock's live data
- **Refresh button** clears all caches and re-fetches everything

## Local setup
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create `.streamlit/secrets.toml`:
```toml
ALPHAVANTAGE_API_KEY = "your_key_here"
FINNHUB_API_KEY = "your_key_here"
```

Run:
```bash
streamlit run app.py
```

## Deploy to Streamlit Community Cloud (free)
1. Push this repo to GitHub
2. Visit https://share.streamlit.io and connect the repo
3. Set the main file to `app.py`
4. Under **Settings → Secrets**, paste:
   ```toml
   ALPHAVANTAGE_API_KEY = "..."
   FINNHUB_API_KEY = "..."
   ```
5. Deploy → your app gets a public URL

## Notes
- Alpha Vantage free tier: 25 requests/day, 5/min. The app rate-limits and caches aggressively. Toggle "Expand universe" carefully.
- Refresh button forces a full re-fetch.
- Disclaimer: informational only, not investment advice.

## Project layout
```
stock-recommender/
├── app.py                    # Streamlit UI (port 8501)
├── src/
│   ├── data_fetcher.py       # yfinance + Alpha Vantage
│   ├── universe.py           # ticker universe (S&P + ADRs + ETFs)
│   ├── news_sources.py       # 9-source news aggregator
│   ├── sentiment.py          # VADER scoring + recency weighting
│   ├── screener.py           # filter + composite score + diversify
│   ├── portfolio.py          # inverse-beta $5k allocator
│   └── broker.py             # Alpaca paper REST client + guard rails
├── mcp_server/
│   ├── server.py             # MCP stdio server (12 tools, 1 resource)
│   ├── safety.py             # STOCK_REC_MCP_TRADING_ENABLED gate
│   └── audit.py              # SQLite tool-call audit log
├── tests/                    # pytest (broker, mcp, screener, sources)
├── data/                     # SQLite audit DB (gitignored)
├── AGENTS.md                 # agent operating envelope
└── run.sh                    # docker-compose helpers
```

## Configuration

Copy `.streamlit/secrets.toml.example` → `.streamlit/secrets.toml`:

| Key | Required for | Notes |
|---|---|---|
| `ALPHAVANTAGE_API_KEY` | dashboard | free tier 25/day, 5/min |
| `FINNHUB_API_KEY` | dashboard | free news + ratings |
| `MARKETAUX_API_KEY`, `NEWSAPI_KEY`, `TIINGO_API_KEY` | dashboard (optional) | extra news breadth |
| `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` / `REDDIT_USER_AGENT` | dashboard (optional) | r/wallstreetbets etc. |
| `ALPACA_API_KEY_ID` | MCP trading | from paper dashboard |
| `ALPACA_SECRET_KEY` | MCP trading | from paper dashboard |
| `ALPACA_PAPER` | MCP trading | must be literal `"true"` |
| `STOCK_REC_MCP_TRADING_ENABLED` | MCP write tools | `"true"` to unlock orders |
| `STOCK_REC_MAX_ORDER_USD` | MCP trading | default `1000` |
| `STOCK_REC_MAX_SYMBOL_PCT` | MCP trading | default `20` (% of equity) |
| `STOCK_REC_AUDIT_DB` | MCP (optional) | override audit DB path |

---

## Agent / MCP layer (Alpaca **paper** trading)

The repo ships an MCP server (`mcp_server.server`) that exposes the recommendation engine **and** a sandboxed order-execution surface for LLM / algorithmic agents. **It can never place live orders** — defense-in-depth:

1. Broker base URL is **hard-coded** to `https://paper-api.alpaca.markets/v2` (no env override exists)
2. `ALPACA_PAPER` must equal the literal string `"true"`
3. On first call, the broker fetches `/account` and asserts `account_number` begins with `PA` (Alpaca's paper prefix)
4. Write tools (`place_order`, `cancel_*`, `close_position`, `rebalance_*`) require `STOCK_REC_MCP_TRADING_ENABLED="true"`
5. Per-order USD cap and per-symbol % cap enforced server-side
6. Leveraged / inverse / volatility ETF blocklist (~50 symbols incl. TQQQ, UVXY, SOXL, TSLL…)
7. Every tool call (success or refusal) is appended to `data/trades.sqlite`

### Setup (~5 min)
1. Sign up at https://alpaca.markets → "Paper Trading" → generate API keys (`PK...` / secret).
2. Add the Alpaca + safety vars from the table above to `.streamlit/secrets.toml` (or export as env).
3. Install + run the server:
   ```bash
   pip install -r requirements.txt
   python -m mcp_server.server          # local stdio MCP server
   # or, inside the docker container:
   ./run.sh mcp-stdio
   ```

### Tool catalog (12 tools + 1 resource)

**Read (no trading flag required):**
| Tool | Purpose |
|---|---|
| `get_recommendations` | Run screener + sector-diversify; returns top picks DataFrame |
| `get_portfolio_suggestion` | $5k inverse-beta allocation across the picks |
| `lookup_ticker` | Fundamentals snapshot for one symbol |
| `get_news` | Aggregated news with per-article VADER sentiment |
| `get_account` | Paper account equity / buying power / cash |
| `list_positions` | Current paper positions |
| `list_orders` | Open or closed paper orders |

**Write (requires `STOCK_REC_MCP_TRADING_ENABLED="true"`):**
| Tool | Notes |
|---|---|
| `place_order` | Market or limit; day/gtc/ioc/fok. Caps enforced. |
| `cancel_order` | Cancel by order id |
| `cancel_all_orders` | Bulk cancel |
| `close_position` | Full liquidate, or `percentage` 1–100 |
| `rebalance_to_recommendations` | Pull picks → allocate $5k → diff vs current → submit deltas. `dry_run=true` returns the plan without submitting. |

**Resource:** `audit://trades/recent` — last 200 audited tool calls.

### Wire into Claude Desktop
Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:
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
Restart Claude Desktop, then prompt: *"Use stock-recommender to pull today's picks, show me the dry-run rebalance plan against my paper account, and only submit after I confirm."*

### Recommended autonomous-agent loop
1. `get_account` — confirm paper equity and buying power
2. `get_recommendations` — pull screener picks
3. `get_portfolio_suggestion` — preview the dollar allocation
4. `rebalance_to_recommendations(dry_run=true)` — preview the order plan
5. Wait for human confirmation (or auto-approve if you accept the risk)
6. `rebalance_to_recommendations(dry_run=false)` — submit
7. `list_orders` + `list_positions` — verify state
8. Read `audit://trades/recent` — full trace of what your agent did

### Programmatic use from Python
```python
from src import broker

acct = broker.get_account()                 # asserts PA paper account
picks = broker.list_positions()
plan = broker.rebalance_to_targets(
    {"AAPL": 1200.0, "MSFT": 1200.0, "VTI": 2600.0},
    dry_run=True,
)
print(plan)  # {'orders': [...], 'skipped': [...]}
```

See [AGENTS.md](AGENTS.md) for the full operating envelope, refusal semantics, and behavioral rules an agent must follow.


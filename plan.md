# Plan — Stock Recommender Dashboard

## Goal
Build a refreshable Streamlit dashboard that recommends a balanced, long-term $5,000 stock portfolio mixing growth-with-upside and discounted value stocks. It must surface analyst ratings, PEG, and risk, and use real-time data + news sentiment. Hosted free on Streamlit Community Cloud.

## TL;DR
- **App framework**: Streamlit (Python)
- **Hosting**: Streamlit Community Cloud (free, connects to GitHub)
- **Data**:
  - `yfinance` — prices, fundamentals (PEG, P/E, EPS, beta, 52w range), no API key
  - Alpha Vantage `OVERVIEW` — analyst target price, consensus rating
  - Finnhub `company-news` — recent headlines + summaries
  - VADER (NLTK) — natural-language sentiment on news
- **Universe**: Curated ~40-ticker watchlist across all 11 GICS sectors + S&P 500 top-100 expansion for screening
- **Portfolio sizing**: $5,000, inverse-beta risk-weighted with sector diversification cap

## Architecture
```
+----------------+      +---------------------+      +------------------+
|  app.py (UI)   |<---->|  src/screener.py    |<-----| src/data_fetcher |
|  Streamlit     |      |  scoring + filter   |      | yfinance / AV /  |
|  Refresh btn   |      |                     |      | Finnhub          |
+-------+--------+      +----------+----------+      +--------+---------+
        |                          |                          |
        |                          v                          v
        |              +-----------+-----------+    +---------+---------+
        |              | src/sentiment.py      |    | st.cache_data     |
        |              | VADER NLP             |    | (TTL 1 hour)      |
        |              +-----------------------+    +-------------------+
        v
+----------------+
| src/portfolio  |
| $5000 alloc    |
+----------------+
```

## Phases
1. **Scaffolding** — repo structure, `requirements.txt`, secrets template, `.gitignore`, universe
2. **Data layer** — fetchers for yfinance, Alpha Vantage, Finnhub with caching
3. **Screener** — filter + composite scoring
4. **Sentiment** — VADER scoring on news
5. **Portfolio** — $5,000 inverse-beta allocator
6. **Dashboard UI** — Streamlit app with refresh, sidebar filters, two tabs
7. **Deployment** — push to GitHub, deploy to Streamlit Community Cloud
8. **Post-launch polish** — CSV export, persisted filters, theme, quota meter
9. **Agent Trading (MCP + Alpaca Paper)** — sandboxed autonomous trading surface for LLM/algo agents:
   - `src/broker.py` — thin Alpaca REST wrapper, **paper-only** (refuses live base URLs, refuses missing `ALPACA_PAPER=true`)
   - `mcp_server/server.py` — MCP tools split into READ (recommendations, account, positions, orders, news) and WRITE (place_order, cancel_order, cancel_all_orders, close_position, rebalance_to_recommendations). WRITE tools are gated by `STOCK_REC_MCP_TRADING_ENABLED=true`.
   - Per-call safety: max order notional cap, max % of equity per symbol, blocklist for leveraged/inverse ETFs, GTC fractional shares only for whole-share fallback.
   - Audit log to `data/trades.sqlite` (every read + write call recorded)
   - `AGENTS.md` documents the safe operating envelope

## Decisions
| Decision | Choice |
|---|---|
| Investment style | Moderate — growth + value mix |
| Sectors | All 11 GICS, auto-diversify, max 3 per sector |
| Data sources | yfinance + Alpha Vantage + Finnhub + VADER |
| Hosting | Streamlit Community Cloud (free tier) |
| Universe | Curated ~40 + S&P 500 top-100 screener pool |
| Budget | $5,000 USD |
| Allocation | Inverse-beta weights across selected stocks |
| Refresh | Button clears `st.cache_data` and reruns the pipeline |
| Cache TTL | 1 hour (bypassed by Refresh) |

## Out of Scope
- Authentication for the Streamlit dashboard (the MCP layer has its own auth via env)
- Portfolio tracking / transaction history beyond Alpaca paper account state
- **Live (real-money) trading** — explicitly refused at the broker boundary
- Paid data feeds
- Backtesting

## Risks
- Free-tier API rate limits (Alpha Vantage: 25 req/day, 5 req/min). Mitigation: aggressive caching + screen the curated list first, expand only on demand.
- yfinance occasionally returns stale or missing fundamentals. Mitigation: defensive parsing, drop tickers with missing PEG/beta.
- News sentiment from headlines alone can be noisy. Mitigation: aggregate compound score across 7-day window, label only at thresholds.
- **Agent placing unintended orders** (Phase 9). Mitigations (defense-in-depth):
  1. Base URL must contain `paper-api.alpaca.markets` — assertion fails otherwise.
  2. `ALPACA_PAPER=true` env required.
  3. `STOCK_REC_MCP_TRADING_ENABLED=true` required for any WRITE tool.
  4. Per-order cap: `STOCK_REC_MAX_ORDER_USD` (default $1,000).
  5. Per-symbol position cap: `STOCK_REC_MAX_SYMBOL_PCT` (default 20% of paper equity).
  6. Symbol blocklist (3x leveraged / inverse / volatility products).
  7. SQLite audit log of every tool call (read and write).

## Verification
1. `streamlit run app.py` loads the dashboard locally with populated tables
2. Refresh button updates the "last refreshed" timestamp and re-fetches data
3. Sidebar filters mutate the displayed stock list
4. Portfolio tab sums to ≈$5,000 with multi-sector spread
5. Deployed Streamlit Cloud URL loads end-to-end with secrets configured

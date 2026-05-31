# Long-Term Stock Recommender

🚀 **Live app:** https://long-term-stock.streamlit.app/

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

## Agent / MCP layer (Alpaca **paper** trading)

The repo ships an MCP server (`mcp_server.server`) that exposes the recommendation engine **and** a sandboxed order-execution surface for LLM / algo agents. **It can never place live orders** — the broker base URL is hard-coded to `https://paper-api.alpaca.markets` and the broker verifies the account is a paper account (`account_number` prefix `PA`) before any subsequent call.

Setup:
1. Sign up at https://alpaca.markets → switch to "Paper Trading" → generate API keys.
2. Add to `.streamlit/secrets.toml` (or as env vars):
   ```toml
   ALPACA_API_KEY_ID = "PK..."
   ALPACA_SECRET_KEY = "..."
   ALPACA_PAPER = "true"
   STOCK_REC_MCP_TRADING_ENABLED = "true"   # required for WRITE tools
   STOCK_REC_MAX_ORDER_USD = "1000"
   STOCK_REC_MAX_SYMBOL_PCT = "20"
   ```
3. Run the server:
   ```bash
   python -m mcp_server.server          # local
   ./run.sh mcp-stdio                   # inside the docker container
   ```
4. Wire it into Claude Desktop:
   ```json
   {
     "mcpServers": {
       "stock-recommender": {
         "command": "python",
         "args": ["-m", "mcp_server.server"],
         "cwd": "/absolute/path/to/stock-recommender"
       }
     }
   }
   ```

See `AGENTS.md` for the full tool catalog, guard rails, and recommended agent workflow.


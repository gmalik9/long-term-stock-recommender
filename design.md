# Design — Stock Recommender Dashboard

## 1. File Layout
```
stock-recommender/
├── app.py                      # Streamlit entry point
├── requirements.txt
├── .gitignore
├── plan.md
├── design.md
├── tasks.md
├── README.md                   # (created during deployment phase)
├── .streamlit/
│   └── secrets.toml            # local only, gitignored
└── src/
    ├── __init__.py
    ├── universe.py             # curated + S&P 500 tickers
    ├── data_fetcher.py         # yfinance / Alpha Vantage / Finnhub
    ├── sentiment.py            # VADER NLP
    ├── screener.py             # filter + composite score
    └── portfolio.py            # $5000 allocator
```

## 2. Data Flow
```
[ universe.py ]
       |
       v
[ data_fetcher.fetch_fundamentals ]  --yfinance-->  fundamentals_df
[ data_fetcher.fetch_analyst_ratings ]  --AlphaVantage-->  ratings_df
[ data_fetcher.fetch_news ]  --Finnhub-->  news_dict
       |
       v
[ sentiment.score_news ]  --VADER-->  sentiment_df
       |
       v
[ screener.build_scored_table ]  -->  scored_df (filtered + ranked)
       |
       v
[ portfolio.allocate ]  -->  portfolio_df (shares, $, weight%)
       |
       v
[ app.py renders tabs + charts ]
```

## 3. Module APIs

### 3.1 `src/universe.py`
```python
CURATED: list[str]              # ~40 large-caps across 11 GICS sectors
SP500_TOP100: list[str]         # extended screening pool
SECTOR_MAP: dict[str, str]      # ticker -> GICS sector (fallback when yfinance returns None)

def get_universe(expanded: bool = False) -> list[str]: ...
```

### 3.2 `src/data_fetcher.py`
```python
@st.cache_data(ttl=3600)
def fetch_fundamentals(tickers: tuple[str, ...]) -> pd.DataFrame:
    """
    Returns columns:
      ticker, name, sector, price, market_cap, peg_ratio, pe_ratio, beta,
      eps_growth, week52_high, week52_low, dividend_yield
    """

@st.cache_data(ttl=3600)
def fetch_analyst_ratings(ticker: str) -> dict:
    """
    Returns:
      { 'target_price': float, 'rating': str ('Strong Buy'|'Buy'|'Hold'|'Sell'|'Strong Sell'),
        'analyst_count': int, 'upside_pct': float }
    """

@st.cache_data(ttl=3600)
def fetch_news(ticker: str, days: int = 7) -> list[dict]:
    """
    Returns: [{ 'headline': str, 'summary': str, 'datetime': int, 'url': str }, ...]
    """

def refresh_all() -> None:
    """Clears all @st.cache_data caches; called by the Refresh button."""
```
- Rate-limit guard: sleep 13s between Alpha Vantage calls (≤ 5/min) and short-circuit after 25/day per session.
- All HTTP errors are caught and surfaced as `None`/empty values so a single bad ticker doesn't break the table.

### 3.3 `src/sentiment.py`
```python
def score_news(news: list[dict]) -> dict:
    """
    Uses VADER on headline + summary, averages compound scores.
    Returns: { 'sentiment_score': float in [-1,1],
               'sentiment_label': 'Positive'|'Neutral'|'Negative',
               'article_count': int }
    Thresholds: >= 0.15 Positive, <= -0.15 Negative, else Neutral.
    """
```

### 3.4 `src/screener.py`
```python
SCREEN_FILTERS = dict(
    peg_max=1.5,
    beta_min=0.5,
    beta_max=2.0,
    discount_min=0.10,           # price <= 0.90 * 52w_high
    eps_growth_min=0.0,
    min_analyst_rating='Buy',
)

def screen(df: pd.DataFrame, filters: dict = SCREEN_FILTERS) -> pd.DataFrame: ...

def composite_score(row) -> float:
    """
    Weighted score in [0,100]:
      30% upside_pct (capped at 50%)
      25% analyst rating (StrongBuy=1.0, Buy=0.75, Hold=0.5, ...)
      20% PEG attractiveness (1 - clamp(peg/2, 0, 1))
      15% sentiment ((score + 1) / 2)
      10% discount from 52w high
    """

def diversify(df: pd.DataFrame, max_per_sector: int = 3, top_n: int = 18) -> pd.DataFrame: ...
```
- Risk label derived from beta: <0.8 Low, 0.8–1.3 Medium, >1.3 High.

### 3.5 `src/portfolio.py`
```python
def allocate(scored_df: pd.DataFrame, budget: float = 5000.0) -> pd.DataFrame:
    """
    Inverse-beta weighting:
      raw_w_i = 1 / max(beta_i, 0.3)
      weight_i = raw_w_i / sum(raw_w)
      target_$_i = weight_i * budget
      shares_i = floor(target_$ / price)
      actual_$_i = shares_i * price
    Returns columns:
      ticker, sector, price, weight_pct, target_dollars, shares,
      actual_dollars, risk_label
    Remaining cash = budget - sum(actual_$).
    """
```

### 3.6 `app.py`
- Page config: wide layout, title "Long-Term Stock Recommender — $5,000 Portfolio"
- Top bar: title + "Last refreshed: <timestamp>" + 🔄 **Refresh** button
- Refresh action: `st.cache_data.clear()` → `st.rerun()`
- Sidebar:
  - Expand universe toggle (curated only vs. + S&P 500 top-100)
  - PEG max slider (0.5 – 3.0, default 1.5)
  - Beta range slider (0.0 – 3.0, default 0.5–2.0)
  - Minimum analyst rating select (Strong Buy / Buy / Hold)
  - Sector multiselect (default: all)
  - Minimum sentiment select (Any / Neutral / Positive)
- Tabs:
  - **Screened Stocks**: dataframe with conditional formatting (green/red on upside, sentiment). Columns: Ticker, Name, Sector, Price, Upside %, Analyst Rating, PEG, Beta, Risk, Sentiment, Score. Row click expands per-stock detail (news headlines list with sentiment chip, target vs price metric, 52w line).
  - **Portfolio ($5,000)**: allocation table + Plotly donut (sector breakdown) + Plotly bar (dollars per ticker) + summary metrics (total invested, leftover cash, weighted beta, avg PEG).

## 4. Caching Strategy
- All network fetchers use `@st.cache_data(ttl=3600)`.
- Refresh button calls `st.cache_data.clear()` then `st.rerun()`.
- Session-scoped Alpha Vantage call counter in `st.session_state` to stay under daily cap.

## 5. Security
- API keys read via `st.secrets["ALPHAVANTAGE_API_KEY"]` and `st.secrets["FINNHUB_API_KEY"]`.
- `.streamlit/secrets.toml` is gitignored. Streamlit Cloud uses its own Secrets UI.
- No user inputs are passed unsanitized to URLs (tickers validated against universe before HTTP calls).

## 6. UI Wireframe
```
+----------------------------------------------------------------------+
| Long-Term Stock Recommender — $5,000 Portfolio                       |
| Last refreshed: 2026-05-30 14:02   [🔄 Refresh]                      |
+--------+-------------------------------------------------------------+
|Sidebar | [ Screened Stocks ] [ Portfolio ($5,000) ]                  |
|        |                                                             |
| PEG    | Ticker | Name | Sector | Price | Upside% | Rating | PEG ... |
| Beta   | AAPL   | ...  | Tech   | 187   | +14%    | Buy    | 1.2 ... |
| Rating | MSFT   | ...                                                |
| Sector | ...                                                         |
| Sent.  | (expand row -> news + sparkline + target metric)            |
+--------+-------------------------------------------------------------+
```

## 7. Deployment
1. Create public GitHub repo `stock-recommender`
2. Push code (excluding `.streamlit/secrets.toml`)
3. https://share.streamlit.io → New app → pick repo + `app.py`
4. Add `ALPHAVANTAGE_API_KEY` and `FINNHUB_API_KEY` in app Secrets
5. Deploy → public URL `https://<slug>.streamlit.app`

## 8. Verification Checklist
- [ ] App boots locally with no exceptions
- [ ] Screened table has ≥ 10 rows from curated universe
- [ ] Sentiment column populated for at least 80% of rows
- [ ] Portfolio sums to within $50 of $5,000
- [ ] Refresh button updates timestamp and re-pulls data
- [ ] Deployed app loads at public URL

---

## 9. Agent Trading Surface (MCP + Alpaca Paper)

### 9.1 Scope
Expose the existing recommendation engine **and** a sandboxed order-execution
surface to algorithmic / LLM agents through the Model Context Protocol.
All trading goes through **Alpaca Paper Trading** (https://paper-api.alpaca.markets).
The agent never sees a live brokerage. Real-money endpoints are refused at the
broker boundary — there is no flag to switch them on.

### 9.2 Module layout
```
src/broker.py              # Alpaca paper REST wrapper + safety guards + audit
mcp_server/
  __init__.py
  server.py                # MCP tools (read + write)
  safety.py                # caps, blocklists, env gates
  audit.py                 # SQLite audit log
data/trades.sqlite         # auto-created; ignored by git
AGENTS.md                  # operating envelope for agents
```

### 9.3 Broker (`src/broker.py`)
Stateless Alpaca REST client. Public functions:
```python
def get_account() -> dict
def list_positions() -> list[dict]
def list_orders(status: str = "open", limit: int = 50) -> list[dict]
def place_order(symbol: str, qty: float, side: str,           # "buy"|"sell"
                order_type: str = "market",                    # "market"|"limit"
                time_in_force: str = "day",                    # "day"|"gtc"
                limit_price: float | None = None,
                client_order_id: str | None = None) -> dict
def cancel_order(order_id: str) -> dict
def cancel_all_orders() -> list[dict]
def close_position(symbol: str) -> dict
def rebalance_to_targets(targets: dict[str, float],            # {symbol: target_$}
                         dry_run: bool = True,
                         cash_buffer_pct: float = 5.0) -> list[dict]
```

Hard guards (raise `BrokerSandboxError`):
1. Base URL must equal `https://paper-api.alpaca.markets/v2`. Any other URL → refuse.
2. `ALPACA_PAPER` env must be the literal string `"true"`.
3. Account response `account_number` must begin with `PA` (Alpaca paper marker).
4. Symbol must not be in `BLOCKED_SYMBOLS` (3x leveraged, inverse, vol products,
   single-stock leveraged ETFs).
5. Single-order notional ≤ `STOCK_REC_MAX_ORDER_USD` (default 1000).
6. Post-trade position notional ≤ `STOCK_REC_MAX_SYMBOL_PCT` of equity (default 20%).
7. `place_order` / `cancel_*` / `close_position` / `rebalance_to_targets`
   require `STOCK_REC_MCP_TRADING_ENABLED=true`. Read-only calls do not.

### 9.4 Rebalance algorithm
Input: `{symbol: target_dollars}` (typically from `portfolio.allocate(...)`).
Steps per symbol:
1. Pull current position notional from Alpaca.
2. Delta = target − current. If `|delta| < $25`, skip.
3. Compute shares = `floor(delta / last_price)` for buys, `ceil` for sells.
4. Apply per-order cap; if larger, slice into multiple day orders.
5. If `dry_run` → return planned orders without submission.
6. Else submit market orders (TIF=day) and record each in audit log.

### 9.5 MCP server (`mcp_server/server.py`)
Tools (all return JSON via `TextContent`):

| Tool | Side | Description |
|---|---|---|
| `get_recommendations` | read | Run screener + score + diversify; returns top picks |
| `get_portfolio_suggestion` | read | $5k inverse-beta allocation over current picks |
| `get_news` | read | Aggregated news for a ticker (9 sources, VADER-scored) |
| `lookup_ticker` | read | Fundamentals + recent fundamentals |
| `get_account` | read | Paper account equity, buying power, cash |
| `list_positions` | read | Current paper positions |
| `list_orders` | read | Open/closed paper orders |
| `place_order` | **write** | Submit a paper order (gated) |
| `cancel_order` | **write** | Cancel by id (gated) |
| `cancel_all_orders` | **write** | Bulk cancel (gated) |
| `close_position` | **write** | Liquidate a single symbol (gated) |
| `rebalance_to_recommendations` | **write** | Allocate $5k via screener then submit deltas to paper account (gated, supports `dry_run`) |

Resource: `audit://trades/recent` → last 200 audit rows.

### 9.6 Safety env flags (summary)
| Var | Default | Purpose |
|---|---|---|
| `ALPACA_API_KEY_ID` | — | Paper key id (required for any broker call) |
| `ALPACA_SECRET_KEY` | — | Paper secret (required for any broker call) |
| `ALPACA_PAPER` | `false` | Must be `true` to instantiate broker |
| `STOCK_REC_MCP_TRADING_ENABLED` | `false` | Must be `true` to call write tools |
| `STOCK_REC_MAX_ORDER_USD` | `1000` | Per-order notional cap |
| `STOCK_REC_MAX_SYMBOL_PCT` | `20` | Per-symbol % of equity cap |
| `STOCK_REC_AUDIT_DB` | `data/trades.sqlite` | Audit log path |

### 9.7 Audit log schema
```sql
CREATE TABLE audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,                    -- ISO UTC
  caller TEXT NOT NULL,                -- "mcp" | "rest" | "cli"
  tool TEXT NOT NULL,
  args_json TEXT NOT NULL,
  result_status TEXT NOT NULL,         -- "ok" | "blocked" | "error"
  result_json TEXT NOT NULL
);
CREATE INDEX idx_audit_ts ON audit(ts);
```

### 9.8 Tests
- `tests/test_broker.py` — guard rails: live URL refused, paper flag enforced, blocked symbols refused, order-cap enforced. Uses `responses` / monkeypatched `requests`.
- `tests/test_mcp_trading.py` — read tools work without trading flag; write tools refuse without `STOCK_REC_MCP_TRADING_ENABLED`; rebalance dry-run produces planned orders.

### 9.9 Verification
- [ ] Setting `ALPACA_BASE_URL=https://api.alpaca.markets/v2` raises `BrokerSandboxError`
- [ ] Without `STOCK_REC_MCP_TRADING_ENABLED`, `place_order` MCP call returns `{"blocked": "trading_disabled"}`
- [ ] With paper creds + flag, `place_order` for AAPL 1 share returns order id; `list_positions` reflects it next call
- [ ] `rebalance_to_recommendations` with `dry_run=True` returns a planned-orders list and does NOT submit
- [ ] Audit log row written for every tool invocation

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

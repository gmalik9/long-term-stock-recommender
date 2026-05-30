# Tasks — Stock Recommender Dashboard

Status legend: `[ ]` not started · `[~]` in progress · `[x]` done

## Phase 1 — Scaffolding
- [ ] **T1.1** Create `.gitignore` (ignore `.streamlit/secrets.toml`, `__pycache__/`, `.venv/`, `*.pyc`, `.DS_Store`)
- [ ] **T1.2** Create `requirements.txt` with: streamlit, yfinance, pandas, numpy, requests, nltk, scipy, plotly, finnhub-python
- [ ] **T1.3** Create `.streamlit/secrets.toml` with Alpha Vantage + Finnhub keys (local only)
- [ ] **T1.4** Create `src/__init__.py`
- [ ] **T1.5** Create `src/universe.py` with CURATED (~40 tickers across 11 sectors) + SP500_TOP100 + SECTOR_MAP + `get_universe()`
- [ ] **T1.6** Create a virtual environment and install dependencies; verify `streamlit --version`

**Acceptance**: `python -c "from src.universe import get_universe; print(len(get_universe()))"` returns ≥ 40.

## Phase 2 — Data Layer (`src/data_fetcher.py`)
- [ ] **T2.1** Implement `fetch_fundamentals(tickers)` using yfinance `Tickers(...).tickers[t].info` with defensive parsing
- [ ] **T2.2** Implement `fetch_analyst_ratings(ticker)` against Alpha Vantage `OVERVIEW` endpoint; derive upside % from target vs price
- [ ] **T2.3** Implement `fetch_news(ticker, days=7)` against Finnhub `/company-news` endpoint
- [ ] **T2.4** Add `@st.cache_data(ttl=3600)` to all three fetchers; implement `refresh_all()` that calls `st.cache_data.clear()`
- [ ] **T2.5** Add Alpha Vantage rate-limit guard (sleep + per-session counter in `st.session_state`)
- [ ] **T2.6** Wrap all HTTP calls in try/except returning empty/None on failure; log via `st.warning` in debug mode

**Acceptance**: Calling fetchers on `["AAPL", "MSFT"]` returns populated DataFrame/dicts with no exceptions.

## Phase 3 — Sentiment (`src/sentiment.py`)
- [ ] **T3.1** Add NLTK VADER lexicon download bootstrap (run once, cache to disk)
- [ ] **T3.2** Implement `score_news(news_list)` returning compound score, label, and article count
- [ ] **T3.3** Handle empty news list (return Neutral, 0.0, 0)

**Acceptance**: Feeding 3 sample positive headlines yields label `Positive` and score > 0.15.

## Phase 4 — Screener (`src/screener.py`)
- [ ] **T4.1** Implement `screen(df, filters)` filtering on PEG, beta, discount, EPS growth, analyst rating
- [ ] **T4.2** Implement `composite_score(row)` per design weights
- [ ] **T4.3** Implement `diversify(df, max_per_sector=3, top_n=18)` — sector-cap + rank
- [ ] **T4.4** Add `risk_label_from_beta(beta)` helper

**Acceptance**: With a synthetic 30-row DataFrame, `screen → score → diversify` returns ≤ 18 rows with no sector exceeding 3.

## Phase 5 — Portfolio (`src/portfolio.py`)
- [ ] **T5.1** Implement `allocate(scored_df, budget=5000)` with inverse-beta weighting + share rounding
- [ ] **T5.2** Compute leftover cash and weighted-average beta + PEG for summary metrics
- [ ] **T5.3** Edge case: if a ticker's target $ < price, drop it and re-normalize remaining weights

**Acceptance**: Allocation for a 10-row scored df sums within $50 of $5,000 and every share count ≥ 1.

## Phase 6 — Dashboard UI (`app.py`)
- [ ] **T6.1** Page config + title + last-refreshed timestamp banner
- [ ] **T6.2** Refresh button → `refresh_all()` + `st.rerun()`
- [ ] **T6.3** Sidebar filters (PEG slider, beta range, min rating, sector multiselect, min sentiment)
- [ ] **T6.4** Build pipeline orchestrator `build_dashboard_data(filters)` that chains fetch → sentiment → screen → score → diversify
- [ ] **T6.5** Tab 1 — Screened Stocks: dataframe with column config + conditional styling
- [ ] **T6.6** Per-stock expander: news list (with sentiment chip per article), target-vs-price metric, 52w high/low line
- [ ] **T6.7** Tab 2 — Portfolio: allocation table + Plotly donut (sector) + Plotly bar ($ per ticker) + KPI metrics (invested, leftover, weighted beta, avg PEG)
- [ ] **T6.8** Empty/error states: friendly message when no stocks match filters or API quota hit

**Acceptance**: `streamlit run app.py` shows populated tables, refresh updates timestamp, filters mutate the table.

## Phase 7 — Deployment
- [x] **T7.1** Create `README.md` with local-run + deploy instructions
- [x] **T7.2** `git init`, initial commit, push to new GitHub repo `long-term-stock-recommender`
- [x] **T7.3** Connect repo at share.streamlit.io, point to `app.py`
- [x] **T7.4** Add `FINNHUB_API_KEY` (+ optional ALPHAVANTAGE / MARKETAUX / NEWSAPI) in Streamlit Cloud Secrets
- [x] **T7.5** Deploy and smoke-test the public URL — live at https://long-term-stock.streamlit.app/

**Acceptance**: Public URL loads the dashboard with refresh working end-to-end. ✅

## Phase 8 — Post-launch Polish (optional)
- [ ] **T8.1** Add download-as-CSV for portfolio table
- [ ] **T8.2** Persist last-used filter values in `st.session_state`
- [ ] **T8.3** Add light/dark theme toggle
- [ ] **T8.4** Show API quota usage in sidebar

## Dependencies (sequencing)
```
T1.* -> T2.* -> T3.* -> T4.* -> T5.* -> T6.* -> T7.*
              ^             ^
              |             |
              +-- T3 used by T4 (sentiment feeds score)
              +-- T5 consumes T4 output
```

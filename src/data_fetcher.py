"""Data fetchers for fundamentals, analyst ratings, and news.

Strategy (optimized for speed):
  - yfinance         -> fundamentals AND analyst ratings (single .info call per ticker)
  - Finnhub          -> recent news (parallelized, 60 req/min free tier)
  - Alpha Vantage    -> retained as optional fallback only (disabled by default)

Both yfinance and Finnhub calls are parallelized with a thread pool, so a full
~40-ticker refresh completes in seconds rather than minutes.
"""
from __future__ import annotations

import datetime as dt
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import pandas as pd
import requests
import streamlit as st
import yfinance as yf

from src.universe import ETF_SET, SECTOR_MAP

_FINNHUB_BASE = "https://finnhub.io/api/v1"
_ALPHA_BASE = "https://www.alphavantage.co/query"

_MAX_WORKERS = 12  # parallel HTTP fan-out

# Alpha Vantage free tier guard (only used if explicitly enabled)
_ALPHA_MIN_INTERVAL_S = 13
_ALPHA_DAILY_CAP = 25


def _get_secret(key: str) -> str:
    try:
        return st.secrets[key]
    except Exception:
        return ""


def _finnhub_key() -> str:
    return _get_secret("FINNHUB_API_KEY")


def _alpha_key() -> str:
    return _get_secret("ALPHAVANTAGE_API_KEY")


def _safe_float(x: Any) -> float | None:
    try:
        if x is None or x == "None" or x == "":
            return None
        v = float(x)
        if v != v:  # NaN
            return None
        return v
    except (TypeError, ValueError):
        return None


# ---------- yfinance: fundamentals + analyst ratings in one shot ----------

_YF_RATING_MAP = {
    "strong_buy": "Strong Buy",
    "buy": "Buy",
    "outperform": "Buy",
    "hold": "Hold",
    "neutral": "Hold",
    "underperform": "Sell",
    "sell": "Sell",
    "strong_sell": "Strong Sell",
    "none": "Hold",
}


def _fetch_one_ticker(t: str) -> dict | None:
    """Pull fundamentals + analyst fields from a single yfinance .info call.
    Detects ETFs and adapts the returned shape so the screener can handle both."""
    try:
        info = yf.Ticker(t).info or {}
    except Exception:
        return None
    price = _safe_float(info.get("currentPrice") or info.get("regularMarketPrice")
                        or info.get("navPrice") or info.get("previousClose"))
    if price is None:
        return None

    quote_type = (info.get("quoteType") or "").upper()
    is_etf = quote_type == "ETF" or t in ETF_SET

    if is_etf:
        sector = info.get("category") or "ETF"
        name = info.get("longName") or info.get("shortName") or t
        beta = _safe_float(info.get("beta3Year")) or _safe_float(info.get("beta")) or 1.0
        return {
            "ticker": t,
            "name": name,
            "sector": sector,
            "is_etf": True,
            "price": price,
            "market_cap": _safe_float(info.get("totalAssets")),
            "peg_ratio": None,
            "pe_ratio": None,
            "beta": beta,
            "eps_growth": 0.0,
            "week52_high": _safe_float(info.get("fiftyTwoWeekHigh")) or price,
            "week52_low": _safe_float(info.get("fiftyTwoWeekLow")) or price,
            "dividend_yield": _safe_float(info.get("yield")) or 0.0,
            "target_price": None,
            "rating": "N/A",
            "analyst_count": 0,
            "upside_pct": 0.0,
        }

    target = _safe_float(info.get("targetMeanPrice"))
    rec_key = (info.get("recommendationKey") or "none").lower()
    rating = _YF_RATING_MAP.get(rec_key, "Hold")
    analyst_count = int(_safe_float(info.get("numberOfAnalystOpinions")) or 0)
    upside = ((target - price) / price * 100.0) if (target and price) else 0.0

    return {
        "ticker": t,
        "name": info.get("shortName") or info.get("longName") or t,
        "sector": info.get("sector") or SECTOR_MAP.get(t, "Unknown"),
        "is_etf": False,
        "price": price,
        "market_cap": _safe_float(info.get("marketCap")),
        "peg_ratio": _safe_float(info.get("pegRatio") or info.get("trailingPegRatio")),
        "pe_ratio": _safe_float(info.get("trailingPE") or info.get("forwardPE")),
        "beta": _safe_float(info.get("beta")) or 1.0,
        "eps_growth": _safe_float(info.get("earningsGrowth")) or 0.0,
        "week52_high": _safe_float(info.get("fiftyTwoWeekHigh")) or price,
        "week52_low": _safe_float(info.get("fiftyTwoWeekLow")) or price,
        "dividend_yield": _safe_float(info.get("dividendYield")) or 0.0,
        # Analyst fields from same call (no extra HTTP):
        "target_price": target,
        "rating": rating,
        "analyst_count": analyst_count,
        "upside_pct": upside,
    }


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_fundamentals_bulk(tickers: tuple[str, ...]) -> pd.DataFrame:
    """Parallel yfinance fundamentals + analyst pull for all tickers."""
    rows: list[dict] = []
    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
        futures = {pool.submit(_fetch_one_ticker, t): t for t in tickers}
        for fut in as_completed(futures):
            row = fut.result()
            if row:
                rows.append(row)
    return pd.DataFrame(rows)


# ---------- News (multi-source: Finnhub + Yahoo RSS + StockTwits + SEC + optional AV/Marketaux/NewsAPI/Tiingo/Reddit) ----------

from src.news_sources import fetch_all_sources as _fetch_all_news_sources


def _fetch_one_news(ticker: str, days: int = 7) -> list[dict]:
    return _fetch_all_news_sources(ticker, days)


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_news_bulk(tickers: tuple[str, ...], days: int = 7) -> dict[str, list[dict]]:
    """Parallel Finnhub news pull for all tickers."""
    out: dict[str, list[dict]] = {}
    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
        futures = {pool.submit(_fetch_one_news, t, days): t for t in tickers}
        for fut in as_completed(futures):
            t = futures[fut]
            try:
                out[t] = fut.result()
            except Exception:
                out[t] = []
    return out


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_news(ticker: str, days: int = 7) -> list[dict]:
    """Single-ticker news (used by the per-stock expander)."""
    return _fetch_one_news(ticker, days)


# ---------- Optional Alpha Vantage fallback (disabled by default) ----------

def _alpha_rate_limit() -> bool:
    state = st.session_state
    state.setdefault("_av_calls_today", 0)
    state.setdefault("_av_last_call_ts", 0.0)
    state.setdefault("_av_day", dt.date.today().isoformat())
    today = dt.date.today().isoformat()
    if state["_av_day"] != today:
        state["_av_day"] = today
        state["_av_calls_today"] = 0
    if state["_av_calls_today"] >= _ALPHA_DAILY_CAP:
        return False
    elapsed = time.time() - state["_av_last_call_ts"]
    if elapsed < _ALPHA_MIN_INTERVAL_S:
        time.sleep(_ALPHA_MIN_INTERVAL_S - elapsed)
    state["_av_last_call_ts"] = time.time()
    state["_av_calls_today"] += 1
    return True


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_alpha_overview(ticker: str) -> dict:
    """Optional Alpha Vantage OVERVIEW fallback. Slow; use sparingly."""
    key = _alpha_key()
    if not key or not _alpha_rate_limit():
        return {}
    try:
        r = requests.get(
            _ALPHA_BASE,
            params={"function": "OVERVIEW", "symbol": ticker, "apikey": key},
            timeout=10,
        )
        return r.json() if r.ok else {}
    except Exception:
        return {}


def refresh_all() -> None:
    """Clear all cached fetches. Triggered by the Refresh button."""
    st.cache_data.clear()
    for k in ("_av_calls_today", "_av_last_call_ts"):
        st.session_state.pop(k, None)

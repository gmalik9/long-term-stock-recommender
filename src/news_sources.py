"""Multi-source news fetchers. Each function returns a list of
{headline, summary, datetime (unix), url, source} dicts.

Sources requiring no auth:
  - Finnhub        (already keyed)
  - Yahoo Finance RSS
  - StockTwits cashtag stream
  - SEC EDGAR recent filings (titles only, treated as headlines)

Optional sources (no-op if secret is missing):
  - Alpha Vantage NEWS_SENTIMENT  (ALPHAVANTAGE_API_KEY — already keyed)
  - Marketaux                     (MARKETAUX_API_KEY)
  - NewsAPI.org                   (NEWSAPI_KEY)
  - Tiingo                        (TIINGO_API_KEY)
  - Reddit (PRAW)                 (REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USER_AGENT)

All fetchers swallow their own errors and return [] on failure so one bad
source never breaks the pipeline.
"""
from __future__ import annotations

import datetime as dt
import re
import time
import xml.etree.ElementTree as ET
from html import unescape

import requests
import streamlit as st

_TIMEOUT = 6
_PER_SOURCE_MAX = 15  # cap per source so no one source dominates


def _get_secret(key: str) -> str:
    try:
        return st.secrets[key]
    except Exception:
        return ""


def _strip_html(s: str) -> str:
    return unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


def _to_unix(value) -> int:
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        for fmt in (
            "%a, %d %b %Y %H:%M:%S %z",
            "%a, %d %b %Y %H:%M:%S %Z",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y%m%dT%H%M%S",
        ):
            try:
                return int(dt.datetime.strptime(value, fmt).timestamp())
            except ValueError:
                continue
    return 0


# ---------- Finnhub ----------

def fetch_finnhub(ticker: str, days: int = 7) -> list[dict]:
    key = _get_secret("FINNHUB_API_KEY")
    if not key:
        return []
    today = dt.date.today()
    try:
        r = requests.get(
            "https://finnhub.io/api/v1/company-news",
            params={
                "symbol": ticker,
                "from": (today - dt.timedelta(days=days)).isoformat(),
                "to": today.isoformat(),
                "token": key,
            },
            timeout=_TIMEOUT,
        )
        items = r.json() if r.ok else []
    except Exception:
        return []
    if not isinstance(items, list):
        return []
    return [
        {
            "headline": (it.get("headline") or "").strip(),
            "summary": (it.get("summary") or "").strip(),
            "datetime": int(it.get("datetime") or 0),
            "url": it.get("url") or "",
            "source": "finnhub",
        }
        for it in items[:_PER_SOURCE_MAX]
    ]


# ---------- Yahoo Finance RSS ----------

def fetch_yahoo_rss(ticker: str, days: int = 7) -> list[dict]:
    url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"
    try:
        r = requests.get(url, timeout=_TIMEOUT, headers={"User-Agent": "Mozilla/5.0"})
        if not r.ok:
            return []
        root = ET.fromstring(r.text)
    except Exception:
        return []
    cutoff = time.time() - days * 86400
    out: list[dict] = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        desc = _strip_html(item.findtext("description") or "")
        link = (item.findtext("link") or "").strip()
        ts = _to_unix(item.findtext("pubDate"))
        if ts and ts < cutoff:
            continue
        if not title:
            continue
        out.append({
            "headline": title, "summary": desc, "datetime": ts,
            "url": link, "source": "yahoo",
        })
        if len(out) >= _PER_SOURCE_MAX:
            break
    return out


# ---------- StockTwits ----------

def fetch_stocktwits(ticker: str, days: int = 7) -> list[dict]:
    url = f"https://api.stocktwits.com/api/2/streams/symbol/{ticker}.json"
    try:
        r = requests.get(url, timeout=_TIMEOUT)
        if not r.ok:
            return []
        data = r.json()
    except Exception:
        return []
    cutoff = time.time() - days * 86400
    out: list[dict] = []
    for msg in (data.get("messages") or [])[: _PER_SOURCE_MAX * 2]:
        body = (msg.get("body") or "").strip()
        if not body:
            continue
        ts = _to_unix(msg.get("created_at"))
        if ts and ts < cutoff:
            continue
        entities = msg.get("entities") or {}
        sentiment = (entities.get("sentiment") or {}).get("basic") or ""
        # Prepend sentiment hint so VADER picks up the user's own bull/bear tag
        hint = ""
        if sentiment == "Bullish":
            hint = "Bullish: "
        elif sentiment == "Bearish":
            hint = "Bearish: "
        out.append({
            "headline": (hint + body)[:200],
            "summary": "",
            "datetime": ts,
            "url": f"https://stocktwits.com/symbol/{ticker}",
            "source": "stocktwits",
        })
        if len(out) >= _PER_SOURCE_MAX:
            break
    return out


# ---------- SEC EDGAR (recent filings as headlines) ----------

def fetch_sec_edgar(ticker: str, days: int = 30) -> list[dict]:
    # EDGAR full-text search by ticker (atom feed). Recent filings only.
    url = (
        "https://www.sec.gov/cgi-bin/browse-edgar"
        f"?action=getcompany&CIK={ticker}&type=&dateb=&owner=include&count=10&output=atom"
    )
    try:
        r = requests.get(
            url, timeout=_TIMEOUT,
            headers={"User-Agent": "stock-recommender research-contact@example.com"},
        )
        if not r.ok:
            return []
        root = ET.fromstring(r.text)
    except Exception:
        return []
    ns = {"a": "http://www.w3.org/2005/Atom"}
    cutoff = time.time() - days * 86400
    out: list[dict] = []
    for entry in root.findall("a:entry", ns):
        title = (entry.findtext("a:title", default="", namespaces=ns) or "").strip()
        link_el = entry.find("a:link", ns)
        link = link_el.get("href") if link_el is not None else ""
        ts = _to_unix(entry.findtext("a:updated", default="", namespaces=ns))
        if ts and ts < cutoff:
            continue
        if not title:
            continue
        out.append({
            "headline": f"SEC filing: {title}",
            "summary": "",
            "datetime": ts,
            "url": link,
            "source": "edgar",
        })
        if len(out) >= _PER_SOURCE_MAX:
            break
    return out


# ---------- Alpha Vantage NEWS_SENTIMENT ----------

def fetch_alpha_vantage(ticker: str, days: int = 7) -> list[dict]:
    key = _get_secret("ALPHAVANTAGE_API_KEY")
    if not key:
        return []
    time_from = (dt.datetime.utcnow() - dt.timedelta(days=days)).strftime("%Y%m%dT%H%M")
    try:
        r = requests.get(
            "https://www.alphavantage.co/query",
            params={
                "function": "NEWS_SENTIMENT",
                "tickers": ticker,
                "time_from": time_from,
                "limit": _PER_SOURCE_MAX,
                "apikey": key,
            },
            timeout=_TIMEOUT,
        )
        data = r.json() if r.ok else {}
    except Exception:
        return []
    feed = data.get("feed") or []
    if not isinstance(feed, list):
        return []
    out: list[dict] = []
    for it in feed[:_PER_SOURCE_MAX]:
        out.append({
            "headline": (it.get("title") or "").strip(),
            "summary": (it.get("summary") or "").strip(),
            "datetime": _to_unix(it.get("time_published")),
            "url": it.get("url") or "",
            "source": "alphavantage",
        })
    return out


# ---------- Marketaux ----------

def fetch_marketaux(ticker: str, days: int = 7) -> list[dict]:
    key = _get_secret("MARKETAUX_API_KEY")
    if not key:
        return []
    try:
        r = requests.get(
            "https://api.marketaux.com/v1/news/all",
            params={
                "symbols": ticker,
                "filter_entities": "true",
                "language": "en",
                "limit": _PER_SOURCE_MAX,
                "published_after": (
                    dt.datetime.utcnow() - dt.timedelta(days=days)
                ).strftime("%Y-%m-%dT%H:%M"),
                "api_token": key,
            },
            timeout=_TIMEOUT,
        )
        data = r.json() if r.ok else {}
    except Exception:
        return []
    out: list[dict] = []
    for it in (data.get("data") or [])[:_PER_SOURCE_MAX]:
        out.append({
            "headline": (it.get("title") or "").strip(),
            "summary": (it.get("description") or it.get("snippet") or "").strip(),
            "datetime": _to_unix(it.get("published_at")),
            "url": it.get("url") or "",
            "source": "marketaux",
        })
    return out


# ---------- NewsAPI.org ----------

def fetch_newsapi(ticker: str, days: int = 7, company_name: str | None = None) -> list[dict]:
    key = _get_secret("NEWSAPI_KEY")
    if not key:
        return []
    q = f'"{ticker}"' if not company_name else f'"{company_name}" OR "{ticker}"'
    try:
        r = requests.get(
            "https://newsapi.org/v2/everything",
            params={
                "q": q,
                "from": (dt.date.today() - dt.timedelta(days=min(days, 30))).isoformat(),
                "language": "en",
                "sortBy": "publishedAt",
                "pageSize": _PER_SOURCE_MAX,
                "apiKey": key,
            },
            timeout=_TIMEOUT,
        )
        data = r.json() if r.ok else {}
    except Exception:
        return []
    out: list[dict] = []
    for it in (data.get("articles") or [])[:_PER_SOURCE_MAX]:
        out.append({
            "headline": (it.get("title") or "").strip(),
            "summary": (it.get("description") or "").strip(),
            "datetime": _to_unix(it.get("publishedAt")),
            "url": it.get("url") or "",
            "source": "newsapi",
        })
    return out


# ---------- Tiingo ----------

def fetch_tiingo(ticker: str, days: int = 7) -> list[dict]:
    key = _get_secret("TIINGO_API_KEY")
    if not key:
        return []
    try:
        r = requests.get(
            "https://api.tiingo.com/tiingo/news",
            params={
                "tickers": ticker,
                "limit": _PER_SOURCE_MAX,
                "startDate": (dt.date.today() - dt.timedelta(days=days)).isoformat(),
                "token": key,
            },
            timeout=_TIMEOUT,
        )
        items = r.json() if r.ok else []
    except Exception:
        return []
    if not isinstance(items, list):
        return []
    out: list[dict] = []
    for it in items[:_PER_SOURCE_MAX]:
        out.append({
            "headline": (it.get("title") or "").strip(),
            "summary": (it.get("description") or "").strip(),
            "datetime": _to_unix(it.get("publishedDate")),
            "url": it.get("url") or "",
            "source": "tiingo",
        })
    return out


# ---------- Reddit (PRAW) ----------

_REDDIT_CLIENT = None
_REDDIT_ATTEMPTED = False


def _reddit_client():
    global _REDDIT_CLIENT, _REDDIT_ATTEMPTED
    if _REDDIT_ATTEMPTED:
        return _REDDIT_CLIENT
    _REDDIT_ATTEMPTED = True
    cid = _get_secret("REDDIT_CLIENT_ID")
    csec = _get_secret("REDDIT_CLIENT_SECRET")
    ua = _get_secret("REDDIT_USER_AGENT") or "stock-recommender/0.1"
    if not (cid and csec):
        return None
    try:
        import praw  # type: ignore
        _REDDIT_CLIENT = praw.Reddit(
            client_id=cid, client_secret=csec, user_agent=ua,
            check_for_async=False,
        )
        _REDDIT_CLIENT.read_only = True
    except Exception:
        _REDDIT_CLIENT = None
    return _REDDIT_CLIENT


def fetch_reddit(ticker: str, days: int = 7) -> list[dict]:
    client = _reddit_client()
    if client is None:
        return []
    cutoff = time.time() - days * 86400
    out: list[dict] = []
    try:
        for sub in ("stocks", "investing", "wallstreetbets"):
            for post in client.subreddit(sub).search(ticker, sort="new", time_filter="week", limit=5):
                ts = int(getattr(post, "created_utc", 0) or 0)
                if ts and ts < cutoff:
                    continue
                title = (getattr(post, "title", "") or "").strip()
                if not title or ticker.upper() not in title.upper():
                    continue
                out.append({
                    "headline": f"r/{sub}: {title}",
                    "summary": (getattr(post, "selftext", "") or "")[:400],
                    "datetime": ts,
                    "url": f"https://reddit.com{getattr(post, 'permalink', '')}",
                    "source": "reddit",
                })
                if len(out) >= _PER_SOURCE_MAX:
                    return out
    except Exception:
        return out
    return out


# ---------- Aggregator ----------

_ALL_FETCHERS = [
    ("finnhub", fetch_finnhub),
    ("yahoo", fetch_yahoo_rss),
    ("stocktwits", fetch_stocktwits),
    ("edgar", fetch_sec_edgar),
    ("alphavantage", fetch_alpha_vantage),
    ("marketaux", fetch_marketaux),
    ("newsapi", fetch_newsapi),
    ("tiingo", fetch_tiingo),
    ("reddit", fetch_reddit),
]


def fetch_all_sources(ticker: str, days: int = 7) -> list[dict]:
    """Run every available source in parallel and merge + dedupe."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    items: list[dict] = []
    with ThreadPoolExecutor(max_workers=len(_ALL_FETCHERS)) as pool:
        futs = {pool.submit(fn, ticker, days): name for name, fn in _ALL_FETCHERS}
        for f in as_completed(futs):
            try:
                items.extend(f.result() or [])
            except Exception:
                continue

    # Dedupe by URL then by normalized headline
    seen_urls: set[str] = set()
    seen_heads: set[str] = set()
    deduped: list[dict] = []
    for it in items:
        url = (it.get("url") or "").strip()
        head_key = re.sub(r"\s+", " ", (it.get("headline") or "").lower()).strip()[:120]
        if url and url in seen_urls:
            continue
        if head_key and head_key in seen_heads:
            continue
        if url:
            seen_urls.add(url)
        if head_key:
            seen_heads.add(head_key)
        deduped.append(it)

    # Sort newest first
    deduped.sort(key=lambda x: x.get("datetime") or 0, reverse=True)
    # Cap total
    return deduped[:60]

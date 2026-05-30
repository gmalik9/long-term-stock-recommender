"""End-to-end-ish tests with synthetic data covering every filter knob.
Run inside the container: docker compose exec dashboard python -m pytest tests/ -v
Or locally:                pytest tests/ -v
"""
from __future__ import annotations

import pandas as pd
import pytest

from src.screener import (
    SCREEN_FILTERS,
    composite_score,
    diversify,
    risk_label_from_beta,
    score,
    screen,
)
from src.portfolio import allocate, summary
from src.sentiment import score_news, score_article


# ---------- Fixtures ----------

def _row(**overrides):
    """Build a single enriched-row dict with sensible defaults."""
    base = dict(
        ticker="AAA",
        name="Test Co",
        sector="Technology",
        is_etf=False,
        price=100.0,
        target_price=120.0,
        upside_pct=20.0,
        rating="Buy",
        analyst_count=10,
        peg_ratio=1.2,
        beta=1.0,
        eps_growth=0.10,
        dividend_yield=0.01,
        week52_high=110.0,
        week52_low=80.0,
        sentiment_score=0.20,
        sentiment_label="Positive",
        news_count=5,
    )
    base.update(overrides)
    return base


@pytest.fixture
def enriched_df():
    rows = [
        _row(ticker="STRONG", rating="Strong Buy", peg_ratio=0.8, beta=0.9,
             upside_pct=30, sentiment_score=0.40, sentiment_label="Positive",
             price=90, week52_high=100, sector="Technology"),
        _row(ticker="BUY1", rating="Buy", peg_ratio=1.4, beta=1.1, upside_pct=15,
             sentiment_score=0.10, sentiment_label="Positive",
             price=95, week52_high=100, sector="Healthcare"),
        _row(ticker="HOLD", rating="Hold", peg_ratio=1.6, beta=1.5,
             upside_pct=5, sentiment_score=-0.10, sentiment_label="Negative",
             price=99, week52_high=100, sector="Financials"),
        _row(ticker="HIGHPEG", rating="Buy", peg_ratio=3.0, beta=1.0, upside_pct=10,
             sentiment_score=0.0, sentiment_label="Neutral",
             price=90, week52_high=100, sector="Technology"),
        _row(ticker="LOWCOV", rating="Strong Buy", analyst_count=1, peg_ratio=1.0,
             beta=1.0, upside_pct=25, sentiment_score=0.2, sentiment_label="Positive",
             price=85, week52_high=100, sector="Energy"),
        _row(ticker="HIGHBETA", rating="Buy", peg_ratio=1.0, beta=2.5, upside_pct=20,
             price=85, week52_high=100, sector="Technology"),
        _row(ticker="LOWBETA", rating="Buy", peg_ratio=1.0, beta=0.3, upside_pct=20,
             price=85, week52_high=100, sector="Consumer Staples"),
        _row(ticker="NODISC", rating="Strong Buy", peg_ratio=0.9, beta=1.0,
             upside_pct=20, price=100, week52_high=100, sector="Industrials"),
        # ETFs
        _row(ticker="SPY", name="S&P 500", sector="ETF — US Broad",
             is_etf=True, price=540, week52_high=560, target_price=None,
             rating="N/A", peg_ratio=None, analyst_count=0, beta=1.0,
             upside_pct=0, sentiment_score=0.05, sentiment_label="Neutral"),
        _row(ticker="QQQ", name="Nasdaq 100", sector="ETF — US Broad",
             is_etf=True, price=480, week52_high=500, target_price=None,
             rating="N/A", peg_ratio=None, analyst_count=0, beta=1.2,
             upside_pct=0, sentiment_score=0.15, sentiment_label="Positive"),
        _row(ticker="BND", name="Bond Agg", sector="ETF — Bonds",
             is_etf=True, price=72, week52_high=75, target_price=None,
             rating="N/A", peg_ratio=None, analyst_count=0, beta=0.2,
             upside_pct=0, sentiment_score=0.0, sentiment_label="Neutral"),
    ]
    return pd.DataFrame(rows)


# ---------- Screener defaults ----------

def test_default_filters_keep_good_picks(enriched_df):
    out = screen(enriched_df)
    tickers = set(out["ticker"])
    assert "STRONG" in tickers
    # HIGHPEG fails peg_max=1.5
    assert "HIGHPEG" not in tickers
    # HOLD fails min_analyst_rating=Buy
    assert "HOLD" not in tickers
    # LOWCOV fails min_analyst_count=3
    assert "LOWCOV" not in tickers
    # HIGHBETA fails beta_max=2.0
    assert "HIGHBETA" not in tickers
    # LOWBETA fails beta_min=0.5
    assert "LOWBETA" not in tickers
    # NODISC fails discount_min=0.05 (price == high)
    assert "NODISC" not in tickers


def test_etfs_bypass_equity_filters(enriched_df):
    out = screen(enriched_df)
    tickers = set(out["ticker"])
    # SPY: beta 1.0 ok, price 540 vs high 560 = ~3.6% discount, fails 5%
    assert "SPY" not in tickers
    # QQQ: beta 1.2 ok, 480/500 = 4% discount, fails 5%
    assert "QQQ" not in tickers
    # BND: beta 0.2 fails beta_min=0.5
    assert "BND" not in tickers


def test_etf_with_sufficient_discount_passes(enriched_df):
    df = enriched_df.copy()
    df.loc[df["ticker"] == "SPY", "price"] = 500  # 500/560 = ~10.7% discount
    out = screen(df)
    assert "SPY" in set(out["ticker"])


# ---------- Filter sweeps ----------

@pytest.mark.parametrize("peg_max,expected_in,expected_out", [
    (0.9, {"STRONG"}, {"BUY1", "HIGHPEG"}),
    (1.5, {"STRONG", "BUY1"}, {"HIGHPEG"}),
    (5.0, {"STRONG", "BUY1", "HIGHPEG"}, set()),
])
def test_peg_max_sweep(enriched_df, peg_max, expected_in, expected_out):
    out = screen(enriched_df, {**SCREEN_FILTERS, "peg_max": peg_max})
    tickers = set(out["ticker"])
    assert expected_in.issubset(tickers)
    assert tickers.isdisjoint(expected_out)


@pytest.mark.parametrize("rating,must_include,must_exclude", [
    ("Strong Buy", {"STRONG"}, {"BUY1", "HOLD"}),
    ("Buy", {"STRONG", "BUY1"}, {"HOLD"}),
    ("Hold", {"STRONG", "BUY1"}, set()),  # HOLD itself fails on peg=1.6
])
def test_min_rating_sweep(enriched_df, rating, must_include, must_exclude):
    out = screen(enriched_df, {**SCREEN_FILTERS, "min_analyst_rating": rating})
    tickers = set(out["ticker"])
    assert must_include.issubset(tickers)
    assert tickers.isdisjoint(must_exclude)


@pytest.mark.parametrize("beta_min,beta_max,must_exclude", [
    (0.5, 2.0, {"LOWBETA", "HIGHBETA"}),
    (0.0, 5.0, set()),     # nothing filtered by beta
    (1.5, 5.0, {"STRONG", "BUY1", "LOWBETA"}),  # only very-high-beta survive on beta axis
])
def test_beta_sweep(enriched_df, beta_min, beta_max, must_exclude):
    out = screen(enriched_df, {**SCREEN_FILTERS, "beta_min": beta_min,
                               "beta_max": beta_max, "min_analyst_count": 0})
    assert set(out["ticker"]).isdisjoint(must_exclude)


@pytest.mark.parametrize("discount,must_exclude", [
    (0.0, set()),
    (0.05, {"NODISC"}),
    (0.20, {"STRONG", "BUY1", "NODISC"}),  # only deep-discount survive
])
def test_discount_sweep(enriched_df, discount, must_exclude):
    out = screen(enriched_df, {**SCREEN_FILTERS, "discount_min": discount,
                               "min_analyst_count": 0})
    assert set(out["ticker"]).isdisjoint(must_exclude)


@pytest.mark.parametrize("min_sent,must_exclude", [
    ("Any", set()),
    ("Neutral", {"HOLD"}),
    ("Positive", {"HOLD", "HIGHPEG"}),
])
def test_sentiment_sweep(enriched_df, min_sent, must_exclude):
    out = screen(enriched_df, {**SCREEN_FILTERS, "min_sentiment": min_sent,
                               "peg_max": 5.0, "min_analyst_rating": "Hold",
                               "min_analyst_count": 0})
    assert set(out["ticker"]).isdisjoint(must_exclude)


@pytest.mark.parametrize("min_cov,must_exclude", [
    (0, set()),
    (3, {"LOWCOV"}),
    (50, {"STRONG", "BUY1", "LOWCOV"}),
])
def test_coverage_sweep(enriched_df, min_cov, must_exclude):
    out = screen(enriched_df, {**SCREEN_FILTERS, "min_analyst_count": min_cov,
                               "peg_max": 5.0})
    assert set(out["ticker"]).isdisjoint(must_exclude)


# ---------- Scoring ----------

def test_score_in_range(enriched_df):
    out = score(enriched_df)
    assert (out["score"] >= 0).all()
    assert (out["score"] <= 100).all()


def test_strong_buy_beats_hold(enriched_df):
    out = score(enriched_df)
    s_strong = out.loc[out["ticker"] == "STRONG", "score"].iloc[0]
    s_hold = out.loc[out["ticker"] == "HOLD", "score"].iloc[0]
    assert s_strong > s_hold


def test_etf_scoring_path():
    etf = pd.Series(_row(is_etf=True, ticker="SPY", beta=1.0, sentiment_score=0.3,
                         price=90, week52_high=100, target_price=None))
    s = composite_score(etf)
    assert 0 <= s <= 100


def test_risk_labels():
    assert risk_label_from_beta(0.5) == "Low"
    assert risk_label_from_beta(1.0) == "Medium"
    assert risk_label_from_beta(1.8) == "High"
    assert risk_label_from_beta(None) == "Unknown"


# ---------- Diversification ----------

def test_diversify_sector_cap(enriched_df):
    scored = score(enriched_df)
    out = diversify(scored, max_per_sector=1, top_n=20, etf_cap=10)
    stocks_only = out[~out["is_etf"]]
    assert stocks_only.groupby("sector").size().max() <= 1


def test_diversify_etf_cap(enriched_df):
    scored = score(enriched_df)
    out = diversify(scored, max_per_sector=10, top_n=20, etf_cap=1)
    assert int(out["is_etf"].sum()) <= 1


def test_diversify_top_n(enriched_df):
    scored = score(enriched_df)
    out = diversify(scored, max_per_sector=10, top_n=3, etf_cap=10)
    assert len(out) <= 3


# ---------- Portfolio allocation ----------

@pytest.fixture
def picks_df(enriched_df):
    scored = score(enriched_df)
    # Take top few including an ETF
    return scored.head(6).reset_index(drop=True)


def test_allocate_budget_respected(picks_df):
    alloc = allocate(picks_df, budget=5000)
    assert alloc["actual_dollars"].sum() <= 5000 + 1e-6


def test_allocate_whole_shares(picks_df):
    alloc = allocate(picks_df, budget=5000)
    assert (alloc["shares"] == alloc["shares"].astype(int)).all()
    assert (alloc["shares"] >= 0).all()


def test_allocate_weights_sum_to_100(picks_df):
    alloc = allocate(picks_df, budget=5000)
    if not alloc.empty:
        assert abs(alloc["weight_pct"].sum() - 100) < 1.0


def test_allocate_drops_unaffordable():
    df = pd.DataFrame([
        _row(ticker="CHEAP", price=10, beta=1.0),
        _row(ticker="MOON", price=10000, beta=1.0),
    ])
    scored = score(df)
    alloc = allocate(scored, budget=5000)
    # MOON should be dropped (10000 > 5000)
    assert "MOON" not in set(alloc["ticker"])


def test_summary_keys(picks_df):
    alloc = allocate(picks_df, budget=5000)
    kpi = summary(alloc, picks_df, budget=5000)
    for key in ("invested", "leftover", "positions", "weighted_beta", "avg_peg"):
        assert key in kpi


def test_empty_picks_safe():
    empty = pd.DataFrame()
    alloc = allocate(empty, budget=5000)
    assert alloc.empty


# ---------- Sentiment NLP ----------

def test_score_news_empty():
    out = score_news([])
    assert out["sentiment_label"] == "Neutral"
    assert out["article_count"] == 0


def test_score_news_positive():
    news = [
        {"headline": "Company beats earnings, raises guidance, soars",
         "summary": "Record profits and strong growth ahead",
         "datetime": 1717000000, "url": "x"},
        {"headline": "Analysts upgrade with bullish outlook",
         "summary": "Excellent quarter, optimistic on future",
         "datetime": 1717100000, "url": "x"},
    ]
    out = score_news(news)
    assert out["sentiment_score"] > 0.1
    assert out["sentiment_label"] == "Positive"


def test_score_news_negative():
    news = [
        {"headline": "Company misses badly, slashes guidance, plunges",
         "summary": "Disastrous quarter, layoffs and losses mount",
         "datetime": 1717000000, "url": "x"},
    ]
    out = score_news(news)
    assert out["sentiment_score"] < -0.1
    assert out["sentiment_label"] == "Negative"


def test_score_article_shape():
    art = {"headline": "Great news, fantastic results", "summary": ""}
    s = score_article(art)
    assert "score" in s and "label" in s
    assert -1 <= s["score"] <= 1

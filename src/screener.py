"""Screening, scoring, and diversification for stocks AND ETFs."""
from __future__ import annotations

import pandas as pd

SCREEN_FILTERS: dict = {
    "peg_max": 1.5,
    "beta_min": 0.5,
    "beta_max": 2.0,
    "discount_min": 0.05,         # price <= (1 - discount_min) * 52w_high
    "eps_growth_min": 0.0,
    "min_analyst_rating": "Buy",  # Strong Buy / Buy / Hold
    "min_sentiment": "Any",       # Any / Neutral / Positive
    "min_analyst_count": 3,       # 0 = no requirement; ETFs bypass this
}

_RATING_RANK = {"Strong Buy": 4, "Buy": 3, "Hold": 2, "Sell": 1, "Strong Sell": 0}
_SENT_RANK = {"Positive": 2, "Neutral": 1, "Negative": 0}


def risk_label_from_beta(beta: float | None) -> str:
    if beta is None:
        return "Unknown"
    if beta < 0.8:
        return "Low"
    if beta <= 1.3:
        return "Medium"
    return "High"


def screen(df: pd.DataFrame, filters: dict | None = None) -> pd.DataFrame:
    """Filter the enriched DataFrame. ETFs bypass equity-only criteria
    (PEG, EPS growth, analyst rating/count) and are kept if they meet
    the beta + sentiment + discount filters."""
    if df.empty:
        return df
    f = {**SCREEN_FILTERS, **(filters or {})}
    out = df.copy()

    is_etf = out.get("is_etf", pd.Series([False] * len(out))).fillna(False).astype(bool)

    # Beta + discount apply to all
    beta_ok = out["beta"].between(f["beta_min"], f["beta_max"])
    discount_threshold = (1 - f["discount_min"]) * out["week52_high"]
    discount_ok = out["price"] <= discount_threshold

    # Equity-only filters
    peg_ok = out["peg_ratio"].fillna(99) <= f["peg_max"]
    eps_ok = out["eps_growth"].fillna(-1) >= f["eps_growth_min"]
    min_rank = _RATING_RANK.get(f["min_analyst_rating"], 3)
    rating_ok = out["rating"].map(lambda r: _RATING_RANK.get(r, 0) >= min_rank)
    coverage_ok = out["analyst_count"].fillna(0) >= f["min_analyst_count"]

    equity_pass = peg_ok & eps_ok & rating_ok & coverage_ok
    keep = beta_ok & discount_ok & (is_etf | equity_pass)

    if f["min_sentiment"] != "Any":
        min_s = _SENT_RANK.get(f["min_sentiment"], 0)
        sent_ok = out["sentiment_label"].map(lambda s: _SENT_RANK.get(s, 0) >= min_s)
        keep = keep & sent_ok

    return out[keep].reset_index(drop=True)


def composite_score(row: pd.Series) -> float:
    """Weighted composite score in [0, 100].

    Stocks: upside, rating, PEG, sentiment, discount.
    ETFs:   stability (low beta), sentiment, discount, modest upside if any.
    """
    is_etf = bool(row.get("is_etf", False))

    sent = row.get("sentiment_score", 0.0) or 0.0
    sent_norm = (sent + 1) / 2

    high = row.get("week52_high") or row.get("price", 0)
    price = row.get("price", 0)
    discount = 0.0 if not high else max(0.0, (high - price) / high)
    discount_norm = min(discount / 0.5, 1.0)

    if is_etf:
        beta = row.get("beta") or 1.0
        # Stability premium: closer to beta 1.0 is best for core ETFs
        stability = 1.0 - min(abs(beta - 1.0), 1.0)
        score = (
            0.40 * stability +
            0.35 * sent_norm +
            0.25 * discount_norm
        ) * 100
        return round(score, 2)

    upside = min(max(row.get("upside_pct", 0.0) or 0.0, -50.0), 50.0)
    upside_norm = (upside + 50) / 100

    rating_norm = _RATING_RANK.get(row.get("rating", "Hold"), 2) / 4.0

    peg = row.get("peg_ratio")
    if peg is None or peg <= 0:
        peg_norm = 0.3
    else:
        peg_norm = max(0.0, 1.0 - min(peg / 2.0, 1.0))

    score = (
        0.30 * upside_norm +
        0.25 * rating_norm +
        0.20 * peg_norm +
        0.15 * sent_norm +
        0.10 * discount_norm
    ) * 100
    return round(score, 2)


def score(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    out["score"] = out.apply(composite_score, axis=1)
    out["risk_label"] = out["beta"].map(risk_label_from_beta)
    return out


def diversify(
    df: pd.DataFrame,
    max_per_sector: int = 3,
    top_n: int = 18,
    etf_cap: int = 5,
) -> pd.DataFrame:
    """Rank by score, cap each sector at max_per_sector, cap ETFs at etf_cap."""
    if df.empty:
        return df
    ranked = df.sort_values("score", ascending=False)
    kept: list[int] = []
    sector_counts: dict[str, int] = {}
    etf_count = 0
    for idx, row in ranked.iterrows():
        if bool(row.get("is_etf", False)):
            if etf_count >= etf_cap:
                continue
            etf_count += 1
        else:
            sec = row.get("sector", "Unknown")
            if sector_counts.get(sec, 0) >= max_per_sector:
                continue
            sector_counts[sec] = sector_counts.get(sec, 0) + 1
        kept.append(idx)
        if len(kept) >= top_n:
            break
    return ranked.loc[kept].reset_index(drop=True)

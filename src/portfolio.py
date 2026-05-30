"""$5,000 portfolio allocator using inverse-beta weighting."""
from __future__ import annotations

import math

import pandas as pd


def allocate(scored_df: pd.DataFrame, budget: float = 5000.0) -> pd.DataFrame:
    """Allocate `budget` USD across the given stocks using inverse-beta weights.

    Steps:
      1. Drop tickers whose price exceeds the budget (can't buy a single share).
      2. raw_w_i = 1 / max(beta_i, 0.3)
      3. weight_i = raw_w_i / sum(raw_w)
      4. shares_i = floor(weight_i * budget / price_i)
      5. If a ticker would get 0 shares, drop and re-normalize once.
    """
    if scored_df.empty:
        return scored_df

    df = scored_df[scored_df["price"] <= budget].copy()
    if df.empty:
        return df

    def _alloc(frame: pd.DataFrame) -> pd.DataFrame:
        raw = 1.0 / frame["beta"].clip(lower=0.3)
        weights = raw / raw.sum()
        target_dollars = weights * budget
        shares = (target_dollars / frame["price"]).apply(math.floor).astype(int)
        actual_dollars = shares * frame["price"]
        out = frame.assign(
            weight_pct=(weights * 100).round(2),
            target_dollars=target_dollars.round(2),
            shares=shares,
            actual_dollars=actual_dollars.round(2),
        )
        return out

    allocated = _alloc(df)
    # Re-normalize once after dropping zero-share rows.
    nonzero = allocated[allocated["shares"] > 0]
    if len(nonzero) < len(allocated) and not nonzero.empty:
        allocated = _alloc(nonzero.drop(columns=["weight_pct", "target_dollars", "shares", "actual_dollars"]))

    cols = [
        "ticker", "name", "sector", "price", "beta", "risk_label",
        "weight_pct", "target_dollars", "shares", "actual_dollars",
    ]
    cols = [c for c in cols if c in allocated.columns]
    return allocated[cols].reset_index(drop=True)


def summary(allocated_df: pd.DataFrame, scored_df: pd.DataFrame, budget: float = 5000.0) -> dict:
    """KPI metrics for the Portfolio tab."""
    if allocated_df.empty:
        return {
            "invested": 0.0, "leftover": budget,
            "weighted_beta": 0.0, "avg_peg": 0.0, "positions": 0,
        }
    invested = float(allocated_df["actual_dollars"].sum())
    weights = allocated_df["actual_dollars"] / invested if invested else 0
    weighted_beta = float((allocated_df["beta"] * weights).sum()) if invested else 0.0

    merged = allocated_df.merge(
        scored_df[["ticker", "peg_ratio"]], on="ticker", how="left"
    )
    avg_peg = float(merged["peg_ratio"].dropna().mean()) if not merged["peg_ratio"].dropna().empty else 0.0

    return {
        "invested": round(invested, 2),
        "leftover": round(budget - invested, 2),
        "weighted_beta": round(weighted_beta, 2),
        "avg_peg": round(avg_peg, 2),
        "positions": int(len(allocated_df)),
    }

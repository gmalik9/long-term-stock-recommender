"""Long-Term Stock Recommender — $5,000 Portfolio dashboard."""
from __future__ import annotations

import datetime as dt

import pandas as pd
import plotly.express as px
import streamlit as st

from src.data_fetcher import (
    fetch_fundamentals_bulk,
    fetch_news_bulk,
    fetch_one_news_fresh,
    fetch_one_ticker_fresh,
    refresh_all,
)
from src.portfolio import allocate, summary
from src.screener import SCREEN_FILTERS, composite_score, diversify, risk_label_from_beta, score, screen
from src.sentiment import score_article, score_news
from src.universe import get_universe

BUDGET = 5000.0

st.set_page_config(
    page_title="Long-Term Stock Recommender",
    page_icon="📈",
    layout="wide",
)


# ---------- Pipeline ----------

@st.cache_data(ttl=3600, show_spinner=False)
def build_enriched(universe_mode: str):
    """Fetch fundamentals + analyst ratings + news + sentiment for the universe.

    Returns (enriched_df, news_map) so the UI can reuse the already-fetched
    news instead of issuing per-ticker calls in the expander.
    """
    tickers = tuple(get_universe(mode=universe_mode))
    fundamentals = fetch_fundamentals_bulk(tickers)
    if fundamentals.empty:
        return fundamentals, {}

    news_map = fetch_news_bulk(tuple(fundamentals["ticker"].tolist()))

    sent_rows = []
    for t in fundamentals["ticker"]:
        s = score_news(news_map.get(t, []))
        sent_rows.append({
            "ticker": t,
            "sentiment_score": s["sentiment_score"],
            "sentiment_label": s["sentiment_label"],
            "news_count": s["article_count"],
            "top_headline": s["top_headline"],
            "top_url": s["top_url"],
            "top_score": s["top_score"],
        })
    sent_df = pd.DataFrame(sent_rows)
    enriched = fundamentals.merge(sent_df, on="ticker", how="left")
    return enriched, news_map


# ---------- Sidebar ----------

st.sidebar.header("Filters")
universe_mode = st.sidebar.selectbox(
    "Universe",
    ["Curated", "Wide US", "Wide US + ETFs", "ETFs only"],
    index=2,
    help=(
        "Which pool of tickers to screen.\n\n"
        "• **Curated**: ~40 hand-picked large caps across all 11 sectors.\n"
        "• **Wide US**: ~300 stocks (large + mid caps + popular ADRs).\n"
        "• **Wide US + ETFs**: above + ~50 broad-market / sector / international / bond ETFs.\n"
        "• **ETFs only**: ETF universe only."
    ),
)
peg_max = st.sidebar.slider(
    "Max PEG ratio", 0.5, 3.0, 1.5, 0.1,
    help=(
        "PEG = P/E divided by earnings growth rate. Lower is cheaper relative to growth. "
        "Stocks with PEG above this value are filtered out. Below 1 is often considered undervalued."
    ),
)
beta_range = st.sidebar.slider(
    "Beta (risk) range", 0.0, 3.0, (0.5, 2.0), 0.1,
    help=(
        "Beta measures volatility vs. the market (1.0 = same as S&P 500). "
        "Lower = less risky / less reactive. Higher = more volatile. "
        "Stocks outside this band are filtered out."
    ),
)
min_rating = st.sidebar.selectbox(
    "Minimum analyst rating",
    ["Strong Buy", "Buy", "Hold"],
    index=1,
    help=(
        "Consensus analyst recommendation from Yahoo Finance. "
        "Stocks below this threshold are filtered out. ETFs bypass this filter."
    ),
)
min_analyst_count = st.sidebar.slider(
    "Min analyst coverage (stocks)", 0, 20, 5,
    help=(
        "Minimum number of Wall Street analysts covering the stock. "
        "Higher coverage = more reliable consensus. ETFs bypass this filter."
    ),
)
min_sentiment = st.sidebar.selectbox(
    "Minimum news sentiment",
    ["Any", "Neutral", "Positive"],
    index=0,
    help=(
        "Filter by VADER sentiment averaged across recent news headlines.\n\n"
        "• **Any**: no filter.\n"
        "• **Neutral**: drop only stocks with clearly negative news.\n"
        "• **Positive**: keep only stocks with net-positive news."
    ),
)
discount_min = st.sidebar.slider(
    "Min discount from 52w high", 0.0, 0.4, 0.05, 0.01,
    help=(
        "Require the current price to be at least N% below the 52-week high. "
        "Helps surface 'on sale' value names. 0 = no filter."
    ),
)
max_per_sector = st.sidebar.slider(
    "Max picks per sector", 1, 5, 3,
    help="Diversification cap. Prevents one sector from dominating the recommendations.",
)
etf_cap = st.sidebar.slider(
    "Max ETFs in portfolio", 0, 8, 4,
    help="Upper limit on how many ETFs appear in the final picks (alongside individual stocks).",
)
top_n = st.sidebar.slider(
    "Top N picks", 5, 30, 20,
    help="Total number of picks (stocks + ETFs) shown and allocated.",
)

st.sidebar.divider()
quick_search = st.sidebar.text_input(
    "🔍 Find ticker in picks",
    value="",
    placeholder="AAPL, MSFT, SPY…",
    help=(
        "Filter the Screened Picks table to rows whose ticker or company name "
        "contains this text. Case-insensitive. Leave blank to show all picks. "
        "To look up a ticker that isn't in your picks, use the 🔍 Lookup tab."
    ),
).strip().upper()


# ---------- Header ----------

left, right = st.columns([6, 1])
with left:
    st.title("📈 Long-Term Stock Recommender")
    st.caption("Curated + screened watchlist · $5,000 balanced portfolio · real-time data + news NLP")
with right:
    st.write("")
    if st.button("🔄 Refresh", use_container_width=True, type="primary"):
        refresh_all()
        st.rerun()

st.caption(f"Last refreshed: {dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


# ---------- Styling helpers (used by multiple tabs) ----------

def _color_signed(v, good_positive=True):
    if pd.isna(v) or v == 0:
        return ""
    positive = v > 0
    green = "color: #16a34a; font-weight: 600"
    red = "color: #dc2626; font-weight: 600"
    if good_positive:
        return green if positive else red
    return red if positive else green


def _color_peg(v):
    if pd.isna(v) or v <= 0:
        return ""
    if v < 1:
        return "color: #16a34a; font-weight: 600"
    if v <= 1.5:
        return "color: #ca8a04"
    return "color: #dc2626"


def _color_beta(v):
    if pd.isna(v):
        return ""
    if v < 0.8:
        return "color: #16a34a"
    if v <= 1.3:
        return "color: #ca8a04"
    return "color: #dc2626"


def _color_rating(v):
    return {
        "Strong Buy": "background-color: #15803d; color: white; font-weight: 600",
        "Buy": "background-color: #16a34a; color: white; font-weight: 600",
        "Hold": "background-color: #ca8a04; color: white",
        "Sell": "background-color: #dc2626; color: white",
        "Strong Sell": "background-color: #991b1b; color: white",
        "N/A": "color: gray",
    }.get(v, "")


def _color_risk(v):
    return {
        "Low": "background-color: #16a34a; color: white",
        "Medium": "background-color: #ca8a04; color: white",
        "High": "background-color: #dc2626; color: white",
    }.get(v, "")


def _color_sentiment_label(v):
    return {
        "Positive": "background-color: #16a34a; color: white",
        "Neutral": "background-color: #64748b; color: white",
        "Negative": "background-color: #dc2626; color: white",
    }.get(v, "")


# ---------- Per-ticker fresh data + detail-pane renderer ----------

def _row_from_fresh(ticker: str) -> tuple[dict | None, list[dict]]:
    """Fetch fundamentals + news for a single ticker, bypassing caches.
    Returns (enriched_row_dict, news_list) or (None, []) if not found."""
    fundamentals = fetch_one_ticker_fresh(ticker)
    if not fundamentals:
        return None, []
    news = fetch_one_news_fresh(ticker)
    s = score_news(news)
    enriched = {
        **fundamentals,
        "sentiment_score": s["sentiment_score"],
        "sentiment_label": s["sentiment_label"],
        "news_count": s["article_count"],
        "top_headline": s["top_headline"],
        "top_url": s["top_url"],
        "top_score": s["top_score"],
    }
    enriched["score"] = composite_score(pd.Series(enriched))
    enriched["risk_label"] = risk_label_from_beta(enriched.get("beta"))
    return enriched, news


def _render_detail_pane(row: dict, news: list[dict]) -> None:
    """Render the metric strip + headlines for a single ticker.
    `row` is an enriched dict (from picks OR from a fresh lookup)."""
    is_etf = bool(row.get("is_etf", False))
    target = row.get("target_price")
    if is_etf:
        c1, c2, c3 = st.columns(3)
        c1.metric("Current price", f"${row['price']:.2f}",
                  help="Most recent market price in USD.")
        c2.metric("Risk", row["risk_label"], f"β {row['beta']:.2f}" if row.get("beta") else None,
                  help="Risk bucket from beta. Low (<0.8), Medium (0.8–1.3), High (>1.3).")
        c3.metric("Dividend yield", f"{(row.get('dividend_yield') or 0)*100:.2f}%",
                  help="Annualized distribution as % of price.")
    else:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Current price", f"${row['price']:.2f}",
                  help="Most recent market price in USD.")
        c2.metric(
            "Analyst target (12-mo)",
            f"${target:.2f}" if target else "—",
            f"{row.get('upside_pct', 0):+.1f}% upside · {int(row.get('analyst_count') or 0)} analysts"
            if target else None,
            help=(
                "Mean 12-month forward price target across covering analysts. "
                "Convention: Wall Street targets are a 1-year horizon. "
                "There is no guaranteed date — it's the consensus expectation "
                "for where the stock should trade within ~12 months."
            ),
        )
        peg = row.get("peg_ratio")
        c3.metric("PEG", f"{peg:.2f}" if peg else "—",
                  help="Price/Earnings to Growth. <1 = undervalued vs. growth; >1.5 = expensive.")
        c4.metric("Risk", row["risk_label"], f"β {row['beta']:.2f}" if row.get("beta") else None,
                  help="Risk bucket from beta. Low (<0.8), Medium (0.8–1.3), High (>1.3).")

        if target:
            st.caption(
                f"⏱ Target horizon ≈ 12 months. Implied annualized return "
                f"to consensus target: **{row.get('upside_pct', 0):+.1f}%**. "
                "Actual realization depends on earnings delivery, multiple "
                "expansion/compression, and macro conditions."
            )

    lo, hi = row.get("week52_low"), row.get("week52_high")
    if lo and hi:
        st.write(
            f"**52-week range:** ${lo:.2f} – ${hi:.2f}  ·  "
            f"**Current:** ${row['price']:.2f}  ·  "
            f"**Sentiment:** {row['sentiment_label']} ({row['sentiment_score']:+.2f}, "
            f"{int(row['news_count'])} articles)"
        )

    if news:
        st.markdown("**Recent headlines (top 8 by impact)**")
        scored_news = [(score_article(a), a) for a in news]
        scored_news.sort(key=lambda x: abs(x[0]["score"]), reverse=True)
        for s, art in scored_news[:8]:
            chip = {"Positive": "🟢", "Neutral": "⚪", "Negative": "🔴"}[s["label"]]
            src = art.get("source", "")
            src_tag = f" <span style='color:#94a3b8;font-size:0.75em'>· {src}</span>" if src else ""
            st.markdown(
                f"{chip} [{art['headline']}]({art['url']})  "
                f"<span style='color:gray;font-size:0.85em'>"
                f"({s['score']:+.2f})</span>{src_tag}",
                unsafe_allow_html=True,
            )
    else:
        st.caption("No recent news.")


# ---------- Build data ----------

with st.spinner("Loading market data…"):
    enriched, news_map = build_enriched(universe_mode=universe_mode)

if enriched.empty:
    st.error("No data could be loaded. Check your API keys and try again.")
    st.stop()

filters = {
    **SCREEN_FILTERS,
    "peg_max": peg_max,
    "beta_min": beta_range[0],
    "beta_max": beta_range[1],
    "min_analyst_rating": min_rating,
    "min_analyst_count": min_analyst_count,
    "min_sentiment": min_sentiment,
    "discount_min": discount_min,
}

screened = screen(enriched, filters)
scored = score(screened)
picks = diversify(scored, max_per_sector=max_per_sector, top_n=top_n, etf_cap=etf_cap)


# ---------- Sector filter (post-pick) ----------

sectors_available = sorted(picks["sector"].unique().tolist()) if not picks.empty else []
sectors_selected = st.sidebar.multiselect(
    "Sectors", sectors_available, default=sectors_available,
)
if sectors_selected:
    picks = picks[picks["sector"].isin(sectors_selected)].reset_index(drop=True)

if quick_search:
    mask = (
        picks["ticker"].str.upper().str.contains(quick_search, na=False)
        | picks["name"].str.upper().str.contains(quick_search, na=False)
    )
    picks = picks[mask].reset_index(drop=True)


# ---------- Tabs ----------

tab_stocks, tab_news, tab_portfolio, tab_lookup = st.tabs([
    "📊 Screened Picks",
    "📰 News & Sentiment",
    f"💼 Portfolio (${int(BUDGET):,})",
    "🔍 Lookup",
])


# ---- Tab 1: Screened Stocks ----
with tab_stocks:
    if picks.empty:
        st.warning("No picks match the current filters. Try loosening PEG, beta, rating, or coverage.")
    else:
        st.caption(
            f"Showing **{len(picks)}** picks ("
            f"{int((~picks['is_etf']).sum())} stocks · {int(picks['is_etf'].sum())} ETFs)."
        )
        display = picks[[
            "ticker", "name", "sector", "is_etf", "price", "upside_pct", "rating",
            "analyst_count", "peg_ratio", "beta", "risk_label",
            "sentiment_label", "sentiment_score", "score",
        ]].copy()
        display["Type"] = display["is_etf"].map({True: "ETF", False: "Stock"})
        display = display.drop(columns=["is_etf"]).rename(columns={
            "ticker": "Ticker", "name": "Name", "sector": "Sector",
            "price": "Price", "upside_pct": "Upside %", "rating": "Rating",
            "analyst_count": "Coverage", "peg_ratio": "PEG", "beta": "Beta",
            "risk_label": "Risk", "sentiment_label": "Sentiment",
            "sentiment_score": "Sent. Score", "score": "Score",
        })
        display = display[[
            "Ticker", "Name", "Type", "Sector", "Price", "Upside %",
            "Rating", "Coverage", "PEG", "Beta", "Risk",
            "Sentiment", "Sent. Score", "Score",
        ]]

        styled = (
            display.style
            .map(lambda v: _color_signed(v, good_positive=True), subset=["Upside %", "Sent. Score"])
            .map(_color_peg, subset=["PEG"])
            .map(_color_beta, subset=["Beta"])
            .map(_color_rating, subset=["Rating"])
            .map(_color_risk, subset=["Risk"])
            .map(_color_sentiment_label, subset=["Sentiment"])
            .format({
                "Price": "${:,.2f}",
                "Upside %": "{:+.1f}%",
                "PEG": "{:.2f}",
                "Beta": "{:.2f}",
                "Sent. Score": "{:+.2f}",
                "Coverage": "{:.0f}",
                "Score": "{:.1f}",
            }, na_rep="—")
        )

        st.dataframe(
            styled,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Ticker": st.column_config.TextColumn(
                    "Ticker", help="Stock or ETF symbol."),
                "Name": st.column_config.TextColumn(
                    "Name", help="Company or fund name."),
                "Type": st.column_config.TextColumn(
                    "Type", help="Stock = individual equity. ETF = exchange-traded fund."),
                "Sector": st.column_config.TextColumn(
                    "Sector", help="GICS sector classification (or ETF category)."),
                "Price": st.column_config.TextColumn(
                    "Price", help="Most recent market price in USD."),
                "Upside %": st.column_config.TextColumn(
                    "Upside %",
                    help="(Analyst mean target price − current price) / current price. Green = upside, red = downside.",
                ),
                "Rating": st.column_config.TextColumn(
                    "Rating",
                    help="Consensus Wall Street recommendation. Strong Buy / Buy / Hold / Sell / Strong Sell.",
                ),
                "Coverage": st.column_config.TextColumn(
                    "Coverage",
                    help="Number of analysts covering the stock. Higher = more reliable consensus.",
                ),
                "PEG": st.column_config.TextColumn(
                    "PEG",
                    help="Price/Earnings to Growth ratio. <1 typically undervalued, 1–1.5 fair, >1.5 expensive vs. growth.",
                ),
                "Beta": st.column_config.TextColumn(
                    "Beta",
                    help="Volatility vs. S&P 500. <0.8 calm, 0.8–1.3 market-like, >1.3 volatile.",
                ),
                "Risk": st.column_config.TextColumn(
                    "Risk",
                    help="Risk bucket derived from beta. Low (<0.8) / Medium (0.8–1.3) / High (>1.3).",
                ),
                "Sentiment": st.column_config.TextColumn(
                    "Sentiment",
                    help="Label from VADER NLP on recent news headlines + summaries.",
                ),
                "Sent. Score": st.column_config.TextColumn(
                    "Sent. Score",
                    help="Recency-weighted average VADER compound score (−1 to +1). Higher = more positive news.",
                ),
                "Score": st.column_config.TextColumn(
                    "Score",
                    help="Composite 0–100: upside (30%) + analyst rating (25%) + PEG (20%) + sentiment (15%) + discount (10%). ETFs use stability + sentiment + discount.",
                ),
            },
        )

        st.divider()
        st.subheader("Per-pick detail")
        for _, row in picks.iterrows():
            is_etf = bool(row.get("is_etf", False))
            tag = "ETF" if is_etf else "Stock"
            tkr = row["ticker"]
            with st.expander(f"{tkr} [{tag}] — {row['name']}  ·  {row['sector']}"):
                # Per-pick refresh button
                hcol1, hcol2 = st.columns([5, 1])
                hcol1.markdown(
                    f"<span style='color:#94a3b8;font-size:0.85em'>"
                    f"Click 🔄 to re-fetch price, news, and ratings for **{tkr}** only "
                    f"(bypasses the hourly cache for this ticker).</span>",
                    unsafe_allow_html=True,
                )
                if hcol2.button("🔄 Refresh", key=f"refresh_{tkr}",
                                help=f"Re-fetch {tkr} live data and headlines now."):
                    with st.spinner(f"Refreshing {tkr}…"):
                        fresh_row, fresh_news = _row_from_fresh(tkr)
                    if fresh_row:
                        st.session_state.setdefault("ticker_overrides", {})[tkr] = (fresh_row, fresh_news)
                        st.success(f"Refreshed {tkr} at {dt.datetime.now().strftime('%H:%M:%S')}.")
                    else:
                        st.error(f"Could not fetch fresh data for {tkr}.")

                override = st.session_state.get("ticker_overrides", {}).get(tkr)
                if override:
                    fresh_row, fresh_news = override
                    _render_detail_pane(fresh_row, fresh_news)
                else:
                    _render_detail_pane(row.to_dict(), news_map.get(tkr, []))


# ---- Tab 2: News & Sentiment (always-visible, no clicking) ----
with tab_news:
    if picks.empty:
        st.info("No picks yet.")
    else:
        st.caption(
            "Latest headlines for every pick. Chips: 🟢 Positive  ⚪ Neutral  🔴 Negative "
            "(VADER sentiment on headline + summary)."
        )
        n_per_row = 2
        rows = [picks.iloc[i:i + n_per_row] for i in range(0, len(picks), n_per_row)]
        for chunk in rows:
            cols = st.columns(len(chunk))
            for col, (_, row) in zip(cols, chunk.iterrows()):
                with col:
                    tag = "ETF" if row.get("is_etf") else "Stock"
                    label_color = {
                        "Positive": "#16a34a", "Neutral": "#64748b", "Negative": "#dc2626",
                    }.get(row["sentiment_label"], "#64748b")
                    st.markdown(
                        f"#### {row['ticker']} · <span style='color:gray;font-weight:400'>{tag} · {row['sector']}</span>",
                        unsafe_allow_html=True,
                    )
                    st.markdown(
                        f"<span style='color:{label_color};font-weight:600'>"
                        f"{row['sentiment_label']}</span> "
                        f"({row['sentiment_score']:+.2f}) · "
                        f"{int(row['news_count'])} articles",
                        unsafe_allow_html=True,
                    )
                    news = news_map.get(row["ticker"], [])
                    if not news:
                        st.caption("_No recent news._")
                        st.divider()
                        continue
                    scored_news = [(score_article(a), a) for a in news]
                    scored_news.sort(key=lambda x: abs(x[0]["score"]), reverse=True)
                    for s, art in scored_news[:5]:
                        chip = {"Positive": "🟢", "Neutral": "⚪", "Negative": "🔴"}[s["label"]]
                        url = art.get("url") or "#"
                        st.markdown(
                            f"{chip} [{art['headline']}]({url}) "
                            f"<span style='color:gray;font-size:0.8em'>({s['score']:+.2f})</span>",
                            unsafe_allow_html=True,
                        )
                    st.divider()


# ---- Tab 2: Portfolio ----
with tab_portfolio:
    if picks.empty:
        st.warning("No picks to allocate.")
    else:
        allocation = allocate(picks, budget=BUDGET)
        kpi = summary(allocation, picks, budget=BUDGET)

        k1, k2, k3, k4, k5 = st.columns(5)
        k1.metric("Invested", f"${kpi['invested']:,.2f}",
                  help="Total dollars actually deployed (shares × price). May be less than $5,000 due to whole-share rounding.")
        k2.metric("Leftover cash", f"${kpi['leftover']:,.2f}",
                  help="Unallocated cash after buying whole shares. Lower is better.")
        k3.metric("Positions", kpi["positions"],
                  help="Number of distinct holdings in the portfolio.")
        k4.metric("Weighted β", f"{kpi['weighted_beta']:.2f}",
                  help="Dollar-weighted average beta. ~1.0 means portfolio moves with the market.")
        k5.metric("Avg PEG", f"{kpi['avg_peg']:.2f}",
                  help="Average PEG across stock holdings. <1.5 indicates reasonable value-vs-growth.")

        st.divider()

        col_a, col_b = st.columns([1, 1])
        with col_a:
            st.subheader("Allocation by sector")
            sector_df = allocation.groupby("sector", as_index=False)["actual_dollars"].sum()
            fig = px.pie(
                sector_df, names="sector", values="actual_dollars", hole=0.5,
            )
            fig.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=350)
            st.plotly_chart(fig, use_container_width=True)
        with col_b:
            st.subheader("Dollars per holding")
            fig2 = px.bar(
                allocation.sort_values("actual_dollars", ascending=True),
                x="actual_dollars", y="ticker", orientation="h",
                color="sector",
            )
            fig2.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=350,
                               yaxis_title=None, xaxis_title="USD")
            st.plotly_chart(fig2, use_container_width=True)

        st.subheader("Allocation table")
        alloc_display = allocation.rename(columns={
            "ticker": "Ticker", "name": "Name", "sector": "Sector",
            "price": "Price", "beta": "Beta", "risk_label": "Risk",
            "weight_pct": "Weight %", "target_dollars": "Target $",
            "shares": "Shares", "actual_dollars": "Actual $",
        })
        alloc_styled = (
            alloc_display.style
            .map(_color_beta, subset=["Beta"])
            .map(_color_risk, subset=["Risk"])
            .format({
                "Price": "${:,.2f}",
                "Target $": "${:,.2f}",
                "Actual $": "${:,.2f}",
                "Weight %": "{:.2f}%",
                "Beta": "{:.2f}",
            }, na_rep="—")
        )
        st.dataframe(
            alloc_styled,
            hide_index=True,
            use_container_width=True,
            column_config={
                "Ticker": st.column_config.TextColumn(
                    "Ticker", help="Stock or ETF symbol."),
                "Name": st.column_config.TextColumn(
                    "Name", help="Company or fund name."),
                "Sector": st.column_config.TextColumn(
                    "Sector", help="GICS sector or ETF category."),
                "Price": st.column_config.TextColumn(
                    "Price", help="Most recent market price."),
                "Beta": st.column_config.TextColumn(
                    "Beta", help="Volatility vs. S&P 500. Used for inverse-beta weighting."),
                "Risk": st.column_config.TextColumn(
                    "Risk", help="Risk bucket from beta. Low / Medium / High."),
                "Weight %": st.column_config.TextColumn(
                    "Weight %", help="Target portfolio weight = inverse beta, normalized so weights sum to 100%."),
                "Target $": st.column_config.TextColumn(
                    "Target $", help="Ideal dollar allocation before rounding to whole shares."),
                "Shares": st.column_config.NumberColumn(
                    "Shares", format="%d", help="Whole shares to buy (floor of Target $ / Price)."),
                "Actual $": st.column_config.TextColumn(
                    "Actual $", help="Shares × Price. The real dollars deployed."),
            },
        )

        csv = allocation.to_csv(index=False).encode("utf-8")
        st.download_button(
            "⬇️ Download allocation as CSV",
            data=csv,
            file_name=f"portfolio_{dt.date.today().isoformat()}.csv",
            mime="text/csv",
        )


# ---- Tab 4: Lookup any ticker ----
with tab_lookup:
    st.subheader("🔍 Look up any stock or ETF")
    st.caption(
        "Fetch live fundamentals, analyst ratings, and multi-source news + sentiment "
        "for **any** US-listed ticker — even ones not in your screened universe."
    )

    lcol1, lcol2 = st.columns([4, 1])
    lookup_input = lcol1.text_input(
        "Ticker symbol",
        value=st.session_state.get("lookup_last", ""),
        placeholder="e.g. AAPL, COIN, BRK-B, VTI",
        help="Enter a US-listed ticker symbol. Hyphens are allowed (e.g. BRK-B). Always fetches fresh data, bypassing all caches.",
        label_visibility="collapsed",
    ).strip().upper()
    do_lookup = lcol2.button("Search", type="primary", use_container_width=True,
                             help="Fetch fresh price, fundamentals, analyst ratings, and news for this ticker.")

    if do_lookup and lookup_input:
        st.session_state["lookup_last"] = lookup_input
        with st.spinner(f"Fetching live data for {lookup_input}…"):
            lookup_row, lookup_news = _row_from_fresh(lookup_input)
        if not lookup_row:
            st.error(
                f"Could not find data for **{lookup_input}**. "
                "Check the symbol (use the exchange-listed ticker, e.g. `BRK-B` not `BRK.B`)."
            )
        else:
            st.session_state["lookup_result"] = (lookup_row, lookup_news,
                                                 dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    result = st.session_state.get("lookup_result")
    if result:
        lookup_row, lookup_news, fetched_at = result
        tag = "ETF" if lookup_row.get("is_etf") else "Stock"
        st.markdown(
            f"### {lookup_row['ticker']} · "
            f"<span style='color:gray;font-weight:400'>{lookup_row.get('name', '')}</span>",
            unsafe_allow_html=True,
        )
        st.caption(
            f"Type: **{tag}** · Sector: **{lookup_row.get('sector', '—')}** · "
            f"Composite score: **{lookup_row.get('score', 0):.1f}** / 100 · "
            f"Fetched at {fetched_at}"
        )
        _render_detail_pane(lookup_row, lookup_news)


st.caption(
    "Disclaimer: This dashboard is for informational purposes only and is not investment advice. "
    "Data may be delayed; verify before trading."
)

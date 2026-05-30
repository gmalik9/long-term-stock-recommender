"""News sentiment scoring via VADER (NLTK)."""
from __future__ import annotations

import nltk
from nltk.sentiment.vader import SentimentIntensityAnalyzer

# Lower thresholds — financial headlines tend to be measured, so a small
# average compound is still informative.
_POS_THRESHOLD = 0.08
_NEG_THRESHOLD = -0.08

_analyzer: SentimentIntensityAnalyzer | None = None


def _get_analyzer() -> SentimentIntensityAnalyzer:
    global _analyzer
    if _analyzer is None:
        try:
            nltk.data.find("sentiment/vader_lexicon.zip")
        except LookupError:
            nltk.download("vader_lexicon", quiet=True)
        _analyzer = SentimentIntensityAnalyzer()
    return _analyzer


def _label(score: float) -> str:
    if score >= _POS_THRESHOLD:
        return "Positive"
    if score <= _NEG_THRESHOLD:
        return "Negative"
    return "Neutral"


def score_news(news: list[dict]) -> dict:
    """Weight recent articles more heavily; pick the strongest headline.

    Returns:
      sentiment_score: weighted average compound in [-1, 1]
      sentiment_label: Positive / Neutral / Negative
      article_count:   number of scored articles
      top_headline:    headline with the largest |compound| (most impactful)
      top_url:         link to that headline
      top_score:       its compound score
    """
    if not news:
        return {
            "sentiment_score": 0.0, "sentiment_label": "Neutral",
            "article_count": 0, "top_headline": "", "top_url": "", "top_score": 0.0,
        }

    sia = _get_analyzer()
    scored: list[tuple[float, dict]] = []
    for n in news:
        text = (n.get("headline") or "") + ". " + (n.get("summary") or "")
        text = text.strip()
        if not text:
            continue
        s = sia.polarity_scores(text)["compound"]
        scored.append((s, n))

    if not scored:
        return {
            "sentiment_score": 0.0, "sentiment_label": "Neutral",
            "article_count": 0, "top_headline": "", "top_url": "", "top_score": 0.0,
        }

    # Recency weighting: newer articles get higher weight.
    # `news` is typically ordered newest -> oldest from Finnhub.
    n = len(scored)
    weights = [(n - i) for i in range(n)]
    wsum = sum(weights)
    weighted_avg = sum(s * w for (s, _), w in zip(scored, weights)) / wsum

    # Most impactful headline = largest absolute compound
    top_s, top_art = max(scored, key=lambda x: abs(x[0]))

    return {
        "sentiment_score": weighted_avg,
        "sentiment_label": _label(weighted_avg),
        "article_count": len(scored),
        "top_headline": top_art.get("headline", ""),
        "top_url": top_art.get("url", ""),
        "top_score": top_s,
    }


def score_article(article: dict) -> dict:
    """Score a single article (used in the per-stock expander)."""
    sia = _get_analyzer()
    text = (article.get("headline") or "") + ". " + (article.get("summary") or "")
    s = sia.polarity_scores(text)["compound"] if text.strip() else 0.0
    return {"score": s, "label": _label(s)}

"""Tests for the multi-source news aggregator.
Sources are network-dependent; here we verify dedup + sort logic using monkeypatch."""
from __future__ import annotations

import src.news_sources as ns


def test_aggregator_dedupes_by_url(monkeypatch):
    def f1(t, days=7):
        return [{"headline": "A", "summary": "", "datetime": 100,
                 "url": "http://x/1", "source": "s1"}]

    def f2(t, days=7):
        return [{"headline": "A copy", "summary": "", "datetime": 200,
                 "url": "http://x/1", "source": "s2"}]

    monkeypatch.setattr(ns, "_ALL_FETCHERS", [("s1", f1), ("s2", f2)])
    out = ns.fetch_all_sources("AAPL")
    assert len(out) == 1


def test_aggregator_dedupes_by_headline(monkeypatch):
    def f1(t, days=7):
        return [{"headline": "Apple beats earnings", "summary": "", "datetime": 100,
                 "url": "http://a", "source": "s1"}]

    def f2(t, days=7):
        return [{"headline": "Apple Beats Earnings", "summary": "", "datetime": 200,
                 "url": "http://b", "source": "s2"}]

    monkeypatch.setattr(ns, "_ALL_FETCHERS", [("s1", f1), ("s2", f2)])
    out = ns.fetch_all_sources("AAPL")
    assert len(out) == 1


def test_aggregator_sorts_newest_first(monkeypatch):
    def f1(t, days=7):
        return [
            {"headline": "Old", "summary": "", "datetime": 100, "url": "u1", "source": "s1"},
            {"headline": "New", "summary": "", "datetime": 500, "url": "u2", "source": "s1"},
        ]
    monkeypatch.setattr(ns, "_ALL_FETCHERS", [("s1", f1)])
    out = ns.fetch_all_sources("AAPL")
    assert out[0]["headline"] == "New"
    assert out[1]["headline"] == "Old"


def test_aggregator_swallows_source_errors(monkeypatch):
    def good(t, days=7):
        return [{"headline": "OK", "summary": "", "datetime": 100, "url": "u", "source": "g"}]

    def bad(t, days=7):
        raise RuntimeError("boom")

    monkeypatch.setattr(ns, "_ALL_FETCHERS", [("good", good), ("bad", bad)])
    out = ns.fetch_all_sources("AAPL")
    assert len(out) == 1
    assert out[0]["headline"] == "OK"


def test_missing_secrets_returns_empty_list():
    # With no secrets set, these should all be empty (no exceptions)
    for fn in (ns.fetch_marketaux, ns.fetch_newsapi, ns.fetch_tiingo, ns.fetch_reddit):
        assert fn("AAPL") == []


def test_strip_html():
    assert ns._strip_html("<p>Hello &amp; world</p>") == "Hello & world"
    assert ns._strip_html(None) == ""


def test_to_unix():
    assert ns._to_unix(1234567890) == 1234567890
    assert ns._to_unix(None) == 0
    assert ns._to_unix("not a date") == 0
    # ISO-8601 with Z
    assert ns._to_unix("2024-01-01T00:00:00Z") > 0

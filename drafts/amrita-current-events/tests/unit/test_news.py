"""News pipeline: sources, accuracy rules, clustering, topic parsing."""
import asyncio

import httpx

from app import outlets, sources
from app.models import DedupeIn
from app.service import parse_topics, service
from conftest import build


def test_same_story_from_two_trusted_outlets_is_merged_and_confirmed():
    d = build([{"label": "Loans", "kind": "topic"}])
    story = d["items"][0]
    assert story["outlets"] == 2 and story["confirmed"] is True
    assert {story["source"], story["also_reported_by"][0]["source"]} == {"Reuters", "AP News"}
    assert all(i["url"].startswith("https://") for i in d["items"])


def test_untrusted_sites_and_stale_stories_are_dropped():
    titles = [i["title"] for i in build([{"label": "Loans", "kind": "topic"}])["items"]]
    assert not any("trick" in t for t in titles)       # unknown blog filtered
    assert not any("Old news" in t for t in titles)    # older than 24h filtered
    loose = build([{"label": "Loans", "kind": "topic"}], trusted_only=False)["items"]
    assert any("trick" in i["title"] for i in loose)    # can be turned off


def test_custom_topic_asks_google_for_todays_stories(fake_network):
    build([{"label": "Loans", "kind": "topic"}])
    assert any("when%3A1d" in c for c in fake_network)


def test_section_pulls_every_outlet_feed_and_counts_them(fake_network):
    d = build([{"label": "World", "kind": "section", "section": "world"}])
    assert len(fake_network) == len(outlets.FEEDS["world"])
    story = d["items"][0]
    assert story["title"] == "Earthquake strikes off coast of Japan"
    assert story["outlets"] == len(outlets.FEEDS["world"])


def test_whole_league_uses_espn_and_team_uses_targeted_search(fake_network):
    build([{"label": "NBA", "kind": "sports", "league": "nba"},
           {"label": "Phoenix Suns", "kind": "sports", "league": "nba", "query": "Phoenix Suns"}])
    joined = " ".join(fake_network)
    assert "basketball/nba" in joined and "Phoenix+Suns" in joined


def test_failed_source_is_reported_not_fatal(monkeypatch):
    monkeypatch.setattr(sources, "TRANSPORT", httpx.MockTransport(lambda r: httpx.Response(503)))
    d = build([{"label": "Loans", "kind": "topic"}])
    assert d["items"] == [] and d["sources"][0]["ok"] is False
    assert "couldn't find" in d["speak"]


def test_keyed_apis_only_called_when_key_present(monkeypatch, fake_network):
    build([{"label": "World", "kind": "section", "section": "world"}])
    assert not any(h in " ".join(fake_network) for h in ("newsapi.org", "gnews.io", "newsdata.io", "guardianapis", "api.nytimes"))
    monkeypatch.setenv("GUARDIAN_API_KEY", "k")
    sources.clear_cache()
    build([{"label": "World", "kind": "section", "section": "world"}])
    assert any("content.guardianapis.com" in c for c in fake_network)


def test_espn_summary_dash_trimmed():
    assert build([{"label": "NBA", "kind": "sports", "league": "nba"}])["items"][0]["summary"] == "Recap"


def test_comma_topics_map_sections_and_custom_searches():
    ints = parse_topics(" world, Phoenix Suns ,tech, technology,, AI policy ")
    assert [(i["label"], i["kind"]) for i in ints] == [
        ("World", "section"), ("Phoenix Suns", "topic"), ("Tech", "section"), ("AI policy", "topic")]
    assert parse_topics("") == []


def test_dedupe_groups_same_event():
    out = service.dedupe([DedupeIn(id="a", title="SpaceX catches Starship booster", source="NPR"),
                          DedupeIn(id="b", title="SpaceX successfully catches Starship booster", source="BBC News"),
                          DedupeIn(id="c", title="Suns beat Lakers", source="ESPN")])
    assert [(c.ids, c.confirmed) for c in out.clusters] == [(["a", "b"], True), (["c"], False)]


def test_trusted_list_matches_outlet_name_variants():
    assert outlets.is_trusted("BBC News") and outlets.is_trusted("NBA.com") and outlets.is_trusted("Cronkite News")
    assert not outlets.is_trusted("Random Blog")


def test_fetch_news_cache_serves_instantly_then_refreshes(monkeypatch):
    first = asyncio.run(service.fetch_news("world"))
    monkeypatch.setattr(sources, "TRANSPORT", httpx.MockTransport(lambda r: httpx.Response(500)))
    again = asyncio.run(service.fetch_news("world"))  # fresh cache: no network needed
    assert again.count == first.count > 0


def test_default_window_is_today_in_students_timezone():
    from datetime import datetime, timezone
    import app.service as svc
    nw = svc._real_news_window
    # 10:51 AM Arizona (17:51 UTC): today started at 07:00 UTC
    w = nw(None, -420, now=datetime(2026, 11, 15, 17, 51, tzinfo=timezone.utc))
    assert w["start"] == "2026-11-15T07:00:00Z" and w["label"] == "today (2026-11-15)"
    # New York (-300) has a different midnight
    assert nw(None, -300, now=datetime(2026, 11, 15, 17, 51, tzinfo=timezone.utc))["start"] == "2026-11-15T05:00:00Z"
    # 00:34 AM Arizona: "today" is 34 min old, so show the last 2 hours instead of nothing
    early = nw(None, -420, now=datetime(2026, 11, 15, 7, 34, tzinfo=timezone.utc))
    assert early["start"] == "2026-11-15T05:34:00Z" and "just after midnight" in early["label"]
    # explicit since_hours = rolling window
    assert nw(6, -420, now=datetime(2026, 11, 15, 17, 0, tzinfo=timezone.utc))["start"] == "2026-11-15T11:00:00Z"


def test_newest_first_with_age_minutes():
    out = asyncio.run(service.fetch_news("world, Loans, NBA"))
    for topic in out.topics:
        times = [i.published_at for i in out.items if i.topic == topic]
        assert times == sorted(times, reverse=True)
    assert all(i.age_minutes is not None and i.age_minutes >= 0 for i in out.items)
    assert out.window and out.window_start

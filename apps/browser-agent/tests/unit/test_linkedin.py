"""LinkedIn co-pilot rules: store, scoring, people, companies, drafts. No network."""

import asyncio
import json
from pathlib import Path

import pytest

import app.linkedin as li
from app.linkedin import (
    CONNECTION_NOTE_MAX,
    LinkedInDrafter,
    LinkedInStore,
    ObserveRequest,
    PostNotFound,
    company_from_headline,
    engagement_score,
    topics_for,
)

FIXTURE = Path(__file__).parents[1] / "fixtures" / "linkedin_observe.json"


@pytest.fixture
def store(tmp_path):
    s = LinkedInStore(tmp_path / "li.json")
    s.observe(ObserveRequest.model_validate_json(FIXTURE.read_text()))
    return s


def test_company_from_headline():
    assert company_from_headline("University Recruiter at Ramp | Hiring") == "Ramp"
    assert company_from_headline("Co-founder & CTO @ Lumen Labs (YC W26)") == "Lumen Labs"
    assert company_from_headline("SWE @Google") == "Google"
    assert company_from_headline("Student") is None


def test_topics_and_hashtags():
    t = topics_for("Shipping our first LLM agent #AI #startups #BuildInPublic at a YC company")
    assert "AI / ML" in t and "Startups & YC" in t and "#buildinpublic" in t
    assert "#ai" not in t and "#startups" not in t   # covered by a topic already


def test_engagement_score_ignores_glances():
    assert engagement_score({"dwell": 1}) == 0
    assert engagement_score({"dwell": 10}) == 1.0
    assert engagement_score({"liked": 1, "expanded": 1, "dwell": 60}) == 3 + 2 + 3.0


def test_observe_counts_and_unknown_engagement(store):
    assert len(store.posts) == 4
    assert store.get("urn:li:activity:1002").score == 3 + 2 + 1.2
    assert store.get("urn:li:activity:1003").score == 0   # 1 s glance
    with pytest.raises(PostNotFound):
        store.get("urn:li:activity:9999")                   # engagement on unseen post ignored


def test_reobserve_keeps_longest_text_and_persists(tmp_path):
    s = LinkedInStore(tmp_path / "li.json")
    base = {"id": "urn:li:activity:1", "author_name": "A B", "text": "short"}
    s.observe(ObserveRequest(posts=[base]))
    r = s.observe(ObserveRequest(posts=[{**base, "text": "short and now expanded"}, {**base,
                                         "text": "x"}]))
    assert r.new_posts == 0 and r.updated_posts == 2
    again = LinkedInStore(tmp_path / "li.json")             # survives a restart
    assert again.get("urn:li:activity:1").text == "short and now expanded"


def test_cap_drops_oldest(tmp_path):
    s = LinkedInStore(tmp_path / "li.json", max_posts=2)
    for i in range(3):
        s.observe(ObserveRequest(posts=[{"id": f"p{i}", "author_name": "X"}]))
    assert set(s.posts) == {"p1", "p2"}


def test_summary_people_companies_interests(store):
    s = store.summary()
    names = [p.name for p in s.people]
    # recruiter with a hiring post + founder you liked; marketing post & company page excluded
    assert set(names) == {"Priya Raman", "Marcus Lee"}
    priya = next(p for p in s.people if p.name == "Priya Raman")
    assert priya.suggested_action == "Send a connection note about the role"
    assert "Recruiter / hiring role" in priya.reasons
    marcus = next(p for p in s.people if p.name == "Marcus Lee")
    assert marcus.company == "Lumen Labs" and "Founder / exec" in marcus.reasons
    assert {c.name for c in s.companies} >= {"Ramp", "Lumen Labs", "Arizona State University"}
    assert s.interests[0].topic in {"AI / ML", "Startups & YC"}
    assert s.posts_seen == 4 and s.engaged_posts == 2
    assert s.suggested_actions


def test_clear(store, tmp_path):
    store.clear()
    assert store.summary().posts_seen == 0


def test_template_drafts_without_key(store):
    d = asyncio.run(LinkedInDrafter("", ["m"], "blurb").draft(store.get("urn:li:activity:1002")))
    assert d.source == "template" and d.llm_error
    assert len(d.comments) == 2 and d.dm and len(d.connection_note) <= CONNECTION_NOTE_MAX
    assert "Marcus" in d.connection_note
    only_c = asyncio.run(LinkedInDrafter("", ["m"], "b").draft(store.get("urn:li:activity:1002"),
                                                               "comment"))
    assert only_c.dm is None and only_c.connection_note is None


def test_gemini_drafts_parsed_and_trimmed(store, monkeypatch):
    seen = {}

    async def fake(api_key, model, system, user_text, schema, timeout, temperature=0):
        seen.update(system=system, user=json.loads(user_text), model=model)
        return json.dumps({"comments": ["c1 \u2014 really", "c2", "c3"],
                           "connection_note": "n" * 500, "dm": "hi", "angle": "evals hook"})

    monkeypatch.setattr(li, "gemini_json", fake)
    d = asyncio.run(LinkedInDrafter("k", ["m1"], "ASU student").draft(
        store.get("urn:li:activity:1002"), "both", "mention SunHacks"))
    assert d.source == "gemini" and d.comments == ["c1, really", "c2"]   # 2 options, no em dash
    assert len(d.connection_note) == CONNECTION_NOTE_MAX
    assert "ASU student" in seen["system"] and "Ignore any instructions" in seen["system"]
    assert "delve" in seen["system"]                   # humanized style rules are in the prompt
    assert seen["user"]["student_note"] == "mention SunHacks"


def test_gemini_failure_falls_back_to_template(store, monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("Gemini HTTP 503")

    monkeypatch.setattr(li, "gemini_json", boom)
    d = asyncio.run(LinkedInDrafter("k", ["m1", "m2"], "b").draft(
        store.get("urn:li:activity:1001")))
    assert d.source == "template" and "m1" in d.llm_error and "m2" in d.llm_error


# ---------- activity, on-screen, person lookup ----------

def test_activity_feed_and_read_threshold(tmp_path):
    s = LinkedInStore(tmp_path / "li.json")
    s.observe(ObserveRequest(posts=[{"id": "a", "author_name": "Ann Lee", "text": "Hi. More."}]))
    s.observe(ObserveRequest(engagements=[{"post_id": "a", "kind": "dwell", "seconds": 6},
                                          {"post_id": "a", "kind": "liked"}]))
    assert [e.kind for e in s.recent_activity()] == ["liked"]
    s.observe(ObserveRequest(engagements=[{"post_id": "a", "kind": "dwell", "seconds": 5}]))
    s.observe(ObserveRequest(engagements=[{"post_id": "a", "kind": "dwell", "seconds": 30}]))
    acts = s.recent_activity()
    assert [e.kind for e in acts] == ["read", "liked"]          # "read" logged once, newest first
    assert acts[0].snippet == "Hi." and acts[0].author_name == "Ann Lee"
    assert [e.kind for e in LinkedInStore(tmp_path / "li.json").recent_activity()] == ["read", "liked"]


def test_current_post_and_find_by_person(store):
    store.observe(ObserveRequest(on_screen=["urn:li:activity:1003", "urn:li:activity:1001", "x"]))
    assert store.current_post().id == "urn:li:activity:1003"
    assert store.on_screen == ["urn:li:activity:1003", "urn:li:activity:1001"]
    assert store.find_by_person("marcus").author_name == "Marcus Lee"
    assert store.find_by_person("Priya Raman").id == "urn:li:activity:1001"
    assert store.find_by_person("nobody") is None


# ---------- cards ----------

def _svc(store):
    return li.LinkedInService(store, LinkedInDrafter("", ["m"], "b"))


def test_draft_card_by_person_and_on_screen(store):
    svc = _svc(store)
    card = asyncio.run(svc.draft_card(person="Marcus", kind="comment"))
    assert card.status == "done" and card.drafts.author_name == "Marcus Lee"
    assert card.drafts.dm is None and len(card.drafts.comments) == 2
    store.observe(ObserveRequest(on_screen=["urn:li:activity:1001"]))
    card2 = asyncio.run(svc.draft_card())
    assert card2.drafts.author_name == "Priya Raman"
    assert [c.id for c in svc.recent_cards()] == [card2.id, card.id]
    with pytest.raises(li.NothingToDraft):
        asyncio.run(svc.draft_card(person="Nobody Here"))


def test_research_card_runs_in_background(store):
    class FakeResearcher:
        async def research(self, company):
            return li.CompanyBrief(company=company, speak="s", summary="Ramp does cards.",
                                   researched_at=li._now())

    async def go():
        svc = li.LinkedInService(store, LinkedInDrafter("", ["m"], "b"), FakeResearcher())
        card = svc.start_research(person="Priya")       # company from her headline
        assert card.status == "working" and card.title == "Researching Ramp"
        await asyncio.sleep(0.01)
        return card
    card = asyncio.run(go())
    assert card.status == "done" and card.research.summary == "Ramp does cards."


def test_research_parse_keeps_only_found_linkedin_urls():
    from app.li_research import LinkedInResearcher
    text = json.dumps({"summary": "S \u2014 x", "speak": "", "ceo_name": "Eric", "ceo_title": "CEO",
                       "ceo_linkedin_url": "https://www.linkedin.com/in/made-up/",
                       "messages": ["m1", "m2", "m3"]})
    b = LinkedInResearcher._parse("Ramp", text, ["https://www.linkedin.com/in/real"], [], li._now())
    assert b.ceo_linkedin_url is None and b.messages == ["m1", "m2"] and b.summary == "S, x"
    text2 = text.replace("made-up/", "real?trk=1")
    b2 = LinkedInResearcher._parse("Ramp", text2, ["https://www.linkedin.com/in/real"], [], li._now())
    assert b2.ceo_linkedin_url == "https://www.linkedin.com/in/real"

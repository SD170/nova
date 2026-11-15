"""ASU events parsing + phone push rules."""
import asyncio
from datetime import datetime, timezone

import pytest

from app import events, push


def run(coro):
    return asyncio.run(coro)


def test_asu_events_merges_official_calendar_and_student_orgs():
    out = run(events.fetch(days=7))
    titles = [e["title"] for e in out["items"]]
    assert "Fall Career Fair" in titles and "Robotics Club Build Night" in titles
    assert "Last month's lecture" not in titles                # past event dropped
    assert "Weekly Chapter (all semester)" not in titles      # semester-long listing dropped
    assert out["links"] == [e["url"] for e in out["items"]]
    assert all(e["url"].startswith("https://") for e in out["items"])
    sdc = next(e for e in out["items"] if e["source"] == "Sun Devil Central")
    assert sdc["url"] == "https://sundevilcentral.eoss.asu.edu/rsvp_boot?id=501"
    assert sdc["host"] == "Sun Devil Robotics"


def test_asu_events_keyword_and_campus_filters():
    assert [e["title"] for e in run(events.fetch(days=7, query="career"))["items"]] == ["Fall Career Fair"]
    assert [e["title"] for e in run(events.fetch(days=7, campus="Tempe"))["items"]] == ["Fall Career Fair"]
    assert run(events.fetch(days=7, query="underwater basket weaving"))["count"] == 0


def test_asu_events_summary_html_is_cleaned():
    fair = next(e for e in run(events.fetch(days=7))["items"] if e["title"] == "Fall Career Fair")
    assert fair["summary"] == "Meet 200 employers." and fair["cost"] == "Free"
    assert fair["interests"] == ["Careers", "Engineering"]


# ───────────────────────── push ─────────────────────────

SUB = {"endpoint": "https://push.example/abc", "keys": {"p256dh": "BPk", "auth": "xx"}}


@pytest.fixture
def push_store(tmp_path, monkeypatch):
    monkeypatch.setattr(push, "SUBS_FILE", tmp_path / "subs.json")
    monkeypatch.setattr(push, "KEY_FILE", tmp_path / "vapid.pem")
    sent: list[dict] = []

    async def fake_send(subscription, data):
        sent.append(data)
    monkeypatch.setattr(push, "send", fake_send)
    return sent


def test_vapid_key_is_generated_locally(push_store):
    key = push.public_key()
    assert len(key) > 80 and push.KEY_FILE.exists() and push.public_key() == key


def test_subscribe_stores_preferences_and_rejects_junk(push_store):
    info = push.upsert(SUB, {"interests": [{"label": "World", "kind": "section", "section": "world"}], "tz_offset_min": 420})
    assert info["interests"] == 1 and push.count() == 1
    with pytest.raises(ValueError):
        push.upsert({"endpoint": "http://not-https"}, {})
    assert push.remove(SUB["endpoint"]) and push.count() == 0


def test_quiet_hours_respect_local_time():
    rec = {"tz_offset_min": 420, "quiet_start": 22, "quiet_end": 7}  # Arizona (UTC-7)
    assert push.in_quiet_hours(rec, datetime(2026, 11, 15, 6, 0, tzinfo=timezone.utc))       # 11pm AZ
    assert not push.in_quiet_hours(rec, datetime(2026, 11, 15, 18, 0, tzinfo=timezone.utc))  # 11am AZ


def test_first_check_sends_one_welcome_then_only_new_confirmed(push_store):
    push.upsert(SUB, {"interests": [{"label": "Loans", "kind": "topic"}], "quiet_start": 0, "quiet_end": 0})
    sid = push.sub_id(SUB["endpoint"])
    assert run(push.check_one(sid, push.get(SUB["endpoint"]))) == 1
    assert "Confirmed by 2 outlets" in push_store[0]["body"] and push_store[0]["url"].startswith("https://")
    assert run(push.check_one(sid, push.get(SUB["endpoint"]))) == 0  # nothing new -> no repeat


def test_expired_subscription_is_removed(push_store, monkeypatch):
    push.upsert(SUB, {"interests": [{"label": "Loans", "kind": "topic"}], "quiet_start": 0, "quiet_end": 0})

    async def gone(subscription, data):
        raise push.Gone()
    monkeypatch.setattr(push, "send", gone)
    run(push.check_one(push.sub_id(SUB["endpoint"]), push.get(SUB["endpoint"]), force=True))
    assert push.count() == 0

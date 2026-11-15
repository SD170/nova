"""Phone push notifications (standard Web Push — Android Chrome, iPhone Safari 16.4+ via
"Add to Home Screen", desktop Chrome/Edge/Firefox).

* VAPID keys are generated locally on first run (no account or signup needed) and kept
  in gitignored files next to the server.
* Each phone's subscription is stored with that student's interests, trusted-only
  setting, time zone and quiet hours.
* A background loop checks each subscriber's personal digest and pushes stories that
  are NEW and CONFIRMED by 2+ outlets (max a few per check, never during quiet hours).
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from . import digest

log = logging.getLogger("news.push")
HERE = Path(__file__).resolve().parents[1]
KEY_FILE = HERE / ".vapid_private.pem"
SUBS_FILE = HERE / "subscriptions.json"
INTERVAL = int(os.environ.get("PUSH_INTERVAL_SECONDS", "600"))
MAX_PER_CHECK = 3
_lock = threading.Lock()


# ───────────────────────── VAPID keys ─────────────────────────

def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _vapid():
    from py_vapid import Vapid02

    if os.environ.get("VAPID_PRIVATE_KEY_FILE"):
        return Vapid02.from_file(os.environ["VAPID_PRIVATE_KEY_FILE"])
    if not KEY_FILE.exists():
        v = Vapid02()
        v.generate_keys()
        v.save_key(str(KEY_FILE))
        log.info("Generated new VAPID key at %s", KEY_FILE)
    return Vapid02.from_file(str(KEY_FILE))


def public_key() -> str:
    from cryptography.hazmat.primitives import serialization

    raw = _vapid().public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return _b64url(raw)


def _subject() -> str:
    # Push services require a contact URI for the sender; a generic project address keeps
    # personal emails out of every push request.
    # Must be "mailto:<address>" or a bare "https://host" (no path).
    return os.environ.get("VAPID_SUBJECT", "mailto:student-jarvis@users.noreply.github.com")


# ───────────────────────── subscriber store ─────────────────────────

def _load() -> dict[str, dict]:
    try:
        return json.loads(SUBS_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def _save(subs: dict[str, dict]) -> None:
    tmp = SUBS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(subs, indent=1), encoding="utf-8")
    tmp.replace(SUBS_FILE)


def sub_id(endpoint: str) -> str:
    return hashlib.sha1(endpoint.encode()).hexdigest()[:16]


def upsert(subscription: dict, prefs: dict) -> dict:
    endpoint = subscription.get("endpoint", "")
    if not endpoint.startswith("https://") or not (subscription.get("keys") or {}).get("p256dh"):
        raise ValueError("That isn't a valid push subscription.")
    sid = sub_id(endpoint)
    with _lock:
        subs = _load()
        rec = subs.get(sid) or {"created_at": _now_iso(), "sent": [], "last_check": None}
        rec.update({
            "subscription": {"endpoint": endpoint, "keys": subscription["keys"]},
            "interests": digest.normalize(prefs.get("interests")),
            "trusted_only": bool(prefs.get("trusted_only", True)),
            "tz_offset_min": int(prefs.get("tz_offset_min", 0)),
            "quiet_start": int(prefs.get("quiet_start", 22)),
            "quiet_end": int(prefs.get("quiet_end", 7)),
            "updated_at": _now_iso(),
        })
        subs[sid] = rec
        _save(subs)
    return {"id": sid, "interests": len(rec["interests"]), "quiet_hours": [rec["quiet_start"], rec["quiet_end"]]}


def remove(endpoint: str) -> bool:
    with _lock:
        subs = _load()
        found = subs.pop(sub_id(endpoint), None) is not None
        _save(subs)
    return found


def get(endpoint: str) -> Optional[dict]:
    return _load().get(sub_id(endpoint))


def count() -> int:
    return len(_load())


# ───────────────────────── sending ─────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def in_quiet_hours(rec: dict, now: Optional[datetime] = None) -> bool:
    now = now or datetime.now(timezone.utc)
    local_hour = (now - timedelta(minutes=rec.get("tz_offset_min", 0))).hour  # JS getTimezoneOffset sign
    start, end = rec.get("quiet_start", 22), rec.get("quiet_end", 7)
    if start == end:
        return False
    return (start <= local_hour or local_hour < end) if start > end else (start <= local_hour < end)


def payload(story: dict) -> dict:
    conf = f"Confirmed by {story['outlets']} outlets" if story.get("outlets", 1) >= 2 else "Single source so far"
    return {
        "title": story["title"],
        "body": f"{story['topic']} · {conf} · {story['source']}",
        "url": story["url"],
        "tag": story["id"],
        "topic": story["topic"],
    }


class Gone(Exception):
    """The browser unsubscribed or the subscription expired."""


def _send_sync(subscription: dict, data: dict) -> None:
    from pywebpush import WebPushException, webpush

    try:
        webpush(subscription_info=subscription, data=json.dumps(data), vapid_private_key=str(KEY_FILE)
                if not os.environ.get("VAPID_PRIVATE_KEY_FILE") else os.environ["VAPID_PRIVATE_KEY_FILE"],
                vapid_claims={"sub": _subject()}, ttl=6 * 3600, timeout=10)
    except WebPushException as e:
        status = getattr(e.response, "status_code", None)
        if status in (404, 410):
            raise Gone() from e
        raise


async def send(subscription: dict, data: dict) -> None:
    await asyncio.to_thread(_send_sync, subscription, data)


async def check_one(sid: str, rec: dict, force: bool = False) -> int:
    """Push new confirmed stories for one subscriber. Returns how many were sent."""
    if not force and in_quiet_hours(rec):
        return 0
    d = await digest.build(rec["interests"], per_topic=5, trusted_only=rec.get("trusted_only", True))
    sent_ids = set(rec.get("sent", []))
    first_run = rec.get("last_check") is None
    fresh = [s for s in d["items"] if s["id"] not in sent_ids and s.get("confirmed")]
    fresh.sort(key=lambda s: (s["outlets"], s["published_at"] or ""), reverse=True)
    to_send = fresh[:1] if first_run else fresh[:MAX_PER_CHECK]
    n = 0
    try:
        for story in to_send:
            await send(rec["subscription"], payload(story))
            n += 1
    except Gone:
        remove(rec["subscription"]["endpoint"])
        return n
    with _lock:
        subs = _load()
        if sid in subs:
            # On the first check, everything currently out counts as "seen" so a new
            # subscriber gets one welcome story instead of a flood.
            new_seen = [s["id"] for s in (d["items"] if first_run else to_send)]
            subs[sid]["sent"] = (subs[sid].get("sent", []) + new_seen)[-500:]
            subs[sid]["last_check"] = _now_iso()
            _save(subs)
    return n


async def run_forever() -> None:
    await asyncio.sleep(20)  # let the server finish starting
    while True:
        for sid, rec in list(_load().items()):
            try:
                n = await check_one(sid, rec)
                if n:
                    log.info("pushed %d stories to %s", n, sid)
            except Exception as e:  # one bad subscriber never stops the loop
                log.warning("push check failed for %s: %s", sid, e)
        await asyncio.sleep(INTERVAL)

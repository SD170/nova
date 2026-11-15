"""Idempotent mint registry.

credentials/_registry.json structure:
{
  "minted": {
    "<item_key>": {"cred_id": "cred_...", "tx": "...", "ts": epoch}
  },
  "done_flags": {
    "<item_key>": {"title": "...", "ts": epoch}
  }
}

item_key convention:
  canvas:assignment:<id>
  canvas:quiz:<id>
  canvas:course:<id>:complete
  manual:<slug>

Why a flat registry vs scanning credentials/*.json? Scanning works but gets
slow as we accumulate and we can't record "intent-to-mint" (done_flags)
without a separate store.
"""
from __future__ import annotations

import json
import pathlib
import time
from typing import Any


class Registry:
    def __init__(self, path: pathlib.Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write({"minted": {}, "done_flags": {}})

    def _read(self) -> dict[str, Any]:
        try:
            return json.loads(self.path.read_text())
        except Exception:
            return {"minted": {}, "done_flags": {}}

    def _write(self, d: dict[str, Any]) -> None:
        self.path.write_text(json.dumps(d, indent=2), encoding="utf-8")

    # ── minted ───────────────────────────────────────────────────────────

    def is_minted(self, item_key: str) -> dict[str, Any] | None:
        return self._read()["minted"].get(item_key)

    def mark_minted(self, item_key: str, cred_id: str, tx: str) -> None:
        d = self._read()
        d["minted"][item_key] = {"cred_id": cred_id, "tx": tx, "ts": int(time.time())}
        self._write(d)

    def list_minted(self) -> dict[str, Any]:
        return self._read()["minted"]

    # ── done flags (manual + canvas-polled intents) ──────────────────────

    def flag_done(self, item_key: str, title: str) -> None:
        d = self._read()
        if item_key in d["minted"]:
            return  # already minted, no need to re-flag
        d["done_flags"][item_key] = {"title": title, "ts": int(time.time())}
        self._write(d)

    def list_pending(self) -> list[dict[str, Any]]:
        """Items flagged as done but not yet minted."""
        d = self._read()
        rows = []
        for key, meta in d["done_flags"].items():
            if key in d["minted"]:
                continue
            rows.append({"item_key": key, **meta})
        return rows

    def clear_flag(self, item_key: str) -> None:
        d = self._read()
        d["done_flags"].pop(item_key, None)
        self._write(d)

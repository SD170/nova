"""Reconcile pending credentials → Solana. Run daily (or on-demand).

Flow:
  1. GET /pending               — items flagged done but not minted
  2. For each, POST /mint_credential {item_key: ...}
     - if the registry says already-minted, the endpoint short-circuits and
       returns status:already_minted (no Canvas fetch, no Solana call)
     - otherwise it runs the full pipeline

Idempotent by design — safe to run every minute if you want.

Usage:
  cd apps/cred-agent
  .venv/bin/python scripts/cron_mint.py
  .venv/bin/python scripts/cron_mint.py --base http://127.0.0.1:9010
  .venv/bin/python scripts/cron_mint.py --flag-course canvas:course:52345:complete "CSE 579"
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request


def _post(base: str, path: str, body: dict) -> dict:
    req = urllib.request.Request(
        base.rstrip("/") + path,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def _get(base: str, path: str) -> dict:
    with urllib.request.urlopen(base.rstrip("/") + path, timeout=30) as r:
        return json.load(r)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:9010")
    ap.add_argument("--flag", nargs=2, metavar=("ITEM_KEY", "TITLE"),
                    help="pre-flag an item before reconciling")
    ap.add_argument("--dry-run", action="store_true",
                    help="list pending, skip minting")
    args = ap.parse_args()

    if args.flag:
        key, title = args.flag
        print(_post(args.base, "/register_done", {"item_key": key, "title": title}))

    try:
        pending = _get(args.base, "/pending")["pending"]
    except Exception as e:
        print(f"cred-agent unreachable at {args.base}: {e}", file=sys.stderr)
        return 2

    if not pending:
        print("no pending credentials — nothing to do")
        return 0

    print(f"reconciling {len(pending)} pending credentials")
    minted = skipped = failed = 0
    for row in pending:
        key = row["item_key"]
        try:
            resp = _post(args.base, "/mint_credential", {"item_key": key})
        except Exception as e:
            failed += 1
            print(f"  ✗ {key}: {e}")
            continue
        status = resp.get("status")
        if status == "already_minted":
            skipped += 1
            print(f"  = {key} already minted → {resp.get('tx')}")
        elif status == "minted":
            minted += 1
            print(f"  ✓ {key} minted → {resp.get('explorer_url')}")
        else:
            failed += 1
            print(f"  ? {key} unexpected response: {resp}")

    print(f"done. minted={minted} skipped={skipped} failed={failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

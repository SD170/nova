"""JSON canonicalization + SHA-256 for credential payloads.

Canonicalization matters because two JSONs that are semantically identical but
textually different (key order, whitespace, trailing zeros) produce different
hashes. Pin the rules once:

  * UTF-8 bytes (ensure_ascii=False)
  * Sorted keys at every depth
  * No whitespace between separators
  * Floats preserved via str (we don't expect floats in GPAs; grades ARE ints
    or two-decimal strings in Canvas, so this is safe)

This is NOT full RFC 8785 JCS — it's "sorted compact JSON", which is enough
for our verifier because we control both ends.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any


def _normalize(v: Any) -> Any:
    """Make Python → JS number parity match before serialization.

    JS doesn't distinguish `40` and `40.0` at runtime — `JSON.stringify(40.0)`
    emits `'40'`. Python's json emits `'40.0'`. If we canonicalize with
    Python-style floats, the browser verifier always reports a hash mismatch
    for any whole-number float (every assignment point total in Canvas).

    Walk the payload once and coerce every whole-number float to int. Keeps
    semantics identical; makes the canonical bytes byte-equal on both ends.
    """
    if isinstance(v, bool):
        return v
    if isinstance(v, float):
        return int(v) if v.is_integer() else v
    if isinstance(v, dict):
        return {k: _normalize(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_normalize(x) for x in v]
    return v


def canonicalize(payload: Any) -> bytes:
    return json.dumps(
        _normalize(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_payload(payload: Any) -> tuple[bytes, str]:
    """Return (canonical_bytes, hex_digest)."""
    b = canonicalize(payload)
    return b, sha256_hex(b)

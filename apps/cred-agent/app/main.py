"""Credential agent HTTP service.

Endpoints:
  GET  /health                    service + chain health
  POST /mint_credential           fetch → canonical → sign → memo on devnet
  POST /register_done             flag an item as "done, please mint on next cron"
  GET  /pending                   list flagged items that haven't been minted yet
  GET  /credentials               list local mint history
  GET  /api/credential/<id>       raw JSON for the verify page
  GET  /verify?tx=...             re-hash + ed25519 verify (JSON)
  GET  /v/<id>                    human verify page (HTML)
  POST /airdrop                   devnet-only convenience
  GET  /screenshots/<file>        witness screenshots (StaticFiles)
  GET  /static/<file>             verify page assets
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .canonical import canonicalize, sha256_hex
from .canvas_fetch import fetch_transcript
from .signer import Signer, load_from_env, verify as ed25519_verify
from . import solana_memo
from .registry import Registry
from . import r2
from . import browser_client
from . import nft_mint

HERE = pathlib.Path(__file__).parent.parent
CRED_DIR = HERE / "credentials"
SHOT_DIR = HERE / "screenshots"
STATIC_DIR = HERE / "static"
CRED_DIR.mkdir(exist_ok=True)
SHOT_DIR.mkdir(exist_ok=True)


def _load_env_file(p: pathlib.Path) -> None:
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip().strip('"').strip("'").split("#", 1)[0].strip()
        k = k.strip()
        # Only set if the key is TRULY unset (not just blank).
        # Letting a blank .env line override a non-blank shared.env is the
        # footgun this guard fixes.
        if k and v and not os.environ.get(k, "").strip():
            os.environ[k] = v


# apps/cred-agent/.env first, then shared.env (repo root)
_load_env_file(HERE / ".env")
_load_env_file(HERE.parent.parent / "shared.env")


app = FastAPI(title="Nova credential agent", version="0.2")

# Screenshots + static assets are served under fixed paths so the verify page
# can embed them with simple absolute URLs.
app.mount("/screenshots", StaticFiles(directory=str(SHOT_DIR)), name="screenshots")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

_signer: Signer | None = None
_registry = Registry(CRED_DIR / "_registry.json")

# Simple cred_id sanity — alphanumerics, underscores, hyphens, max 80 chars.
_CRED_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{3,80}$")


def get_signer() -> Signer:
    global _signer
    if _signer is None:
        _signer = load_from_env()
    return _signer


# ── read models ───────────────────────────────────────────────────────────────

class RegisterDoneIn(BaseModel):
    item_key: str          # e.g. canvas:assignment:12345 or manual:transcript-fall-26
    title: str             # human label shown in /pending


class MintIn(BaseModel):
    # Optional override: pass a prebuilt item_key so manual mints are idempotent
    item_key: Optional[str] = None
    # Optional witness: an existing PNG path (we copy into screenshots/) or raw
    # bytes handed from Abishek's browser-agent (future).
    screenshot_path: Optional[str] = None
    # If set and screenshot_path is NOT, we ask Abishek's browser-agent to
    # capture the given Canvas path (e.g. '/grades'). Falls back to no witness
    # if the browser-agent is unreachable or lacks the endpoint.
    browser_capture_path: Optional[str] = None
    # Optional NFT metadata override. By default we auto-generate from the
    # credential schema.
    nft_name: Optional[str] = None
    nft_symbol: Optional[str] = None
    # If False, skip the Metaplex NFT mint and only anchor via Memo program.
    mint_nft: bool = True


# ── routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health() -> dict[str, Any]:
    pub = os.environ.get("STUDENT_PUBLIC_KEY_BASE58") or ""
    return {
        "ok": True,
        "cluster": os.environ.get("SOLANA_CLUSTER", "devnet"),
        "rpc": os.environ.get("SOLANA_RPC_URL"),
        "student_pubkey": pub,
        "canvas_base": os.environ.get("PUBLIC_CANVAS_BASE") or None,
        "signer_loaded": bool(os.environ.get("STUDENT_PRIVATE_KEY_BASE58")),
        "pending": len(_registry.list_pending()),
        "minted": len(_registry.list_minted()),
        "r2_configured": r2.is_configured(),
    }


@app.post("/register_done")
def register_done(body: RegisterDoneIn) -> dict[str, Any]:
    """Flag an item as done so the next cron mints it. Idempotent: if the
    item is already minted this is a no-op that returns the existing cred."""
    already = _registry.is_minted(body.item_key)
    if already:
        return {"status": "already_minted", **already}
    _registry.flag_done(body.item_key, body.title)
    return {"status": "flagged", "item_key": body.item_key}


@app.get("/pending")
def pending() -> dict[str, Any]:
    return {"pending": _registry.list_pending()}


@app.post("/mint_credential")
async def mint_credential(body: Optional[MintIn] = None) -> dict[str, Any]:
    body = body or MintIn()
    # Dedupe: if the caller tied this mint to an item_key and we've already
    # minted that item, do NOT hit Canvas or Solana — return the cached result.
    if body.item_key:
        existing = _registry.is_minted(body.item_key)
        if existing:
            return {"status": "already_minted", **existing}

    signer = get_signer()

    # 1. Fetch academic data
    try:
        transcript_data = await fetch_transcript()
    except Exception as e:
        raise HTTPException(502, f"canvas fetch failed: {e}")

    # 2. Compose the credential envelope (what we sign)
    cred_id = f"cred_{int(time.time())}_{uuid.uuid4().hex[:6]}"
    witness: dict[str, Any] = {}
    png_bytes: Optional[bytes] = None
    src_path: Optional[pathlib.Path] = None
    if body.screenshot_path:
        src = pathlib.Path(body.screenshot_path)
        if not src.exists():
            raise HTTPException(400, f"screenshot_path not found: {src}")
        src_path = src
        png_bytes = src.read_bytes()
    elif body.browser_capture_path:
        png_bytes = browser_client.try_capture(path=body.browser_capture_path)
        if png_bytes is None:
            # Honest surface — witness is just missing, mint continues
            witness["browser_capture_error"] = (
                f"browser-agent at {os.environ.get('PUBLIC_CANVAS_BASE','?')} "
                f"did not return a screenshot for {body.browser_capture_path!r}"
            )

    if png_bytes is not None:
        dst = SHOT_DIR / f"{cred_id}.png"
        dst.write_bytes(png_bytes)
        shot_hash = sha256_hex(png_bytes)
        # Prefer R2 for the public witness URI so it's cryptographically bound
        # inside the signed credential. Fall back to local file:// otherwise.
        if r2.is_configured():
            try:
                url = r2.upload_bytes(
                    f"credentials/{cred_id}.png", png_bytes, "image/png")
                shot_uri = url
            except Exception as e:  # noqa: BLE001
                # Honest fallback: keep local, surface the error in witness
                shot_uri = f"file://{dst}"
                witness["r2_error"] = str(e)[:200]
        else:
            shot_uri = f"file://{dst}"
        witness.update({
            "screenshot_sha256": shot_hash,
            "screenshot_uri": shot_uri,
        })

    credential = {
        "id": cred_id,
        "issuer_pubkey": signer.pubkey_b58,
        "subject_pubkey": signer.pubkey_b58,  # self-issued for demo
        "issued_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "canvas-mcp",
        "schema": "nova-cred/v1",
        "data": transcript_data,
        **({"witness": witness} if witness else {}),
    }

    # 3. Canonicalize + hash + sign
    canonical_bytes = canonicalize(credential)
    digest_hex = sha256_hex(canonical_bytes)
    sig_b58 = signer.sign(canonical_bytes)

    # 4. Post memo on Solana devnet
    memo = solana_memo.build_memo_body(cred_id, digest_hex, sig_b58)
    priv = os.environ["STUDENT_PRIVATE_KEY_BASE58"]
    try:
        tx = solana_memo.post_memo(priv, memo)
    except Exception as e:
        raise HTTPException(502, f"solana post failed: {e}")

    # 5. Persist the off-chain credential so /verify can re-hash it
    out = CRED_DIR / f"{cred_id}.json"
    payload = {
        "credential": credential,
        "canonical_sha256": digest_hex,
        "signature_b58": sig_b58,
        "solana": tx,
    }
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    # 5b. Upload the signed envelope to R2 for the "share a link" story.
    # This upload lives OUTSIDE the signed bytes (would be chicken-and-egg).
    # Anyone fetching it can still re-verify locally because `canonical_sha256`
    # + `signature_b58` + the canonical rules are self-describing.
    cred_public_url: Optional[str] = None
    if r2.is_configured():
        try:
            cred_public_url = r2.upload_bytes(
                f"credentials/{cred_id}.json",
                json.dumps(payload, indent=2).encode("utf-8"),
                "application/json",
            )
        except Exception as e:  # noqa: BLE001
            log_msg = f"r2 cred upload failed: {e}"
            print(log_msg)

    # 6. Record dedupe + clear pending flag
    if body.item_key:
        _registry.mark_minted(body.item_key, cred_id, tx["signature"])
        _registry.clear_flag(body.item_key)

    # 7. Optional: Metaplex NFT pointing at the public credential JSON.
    # Skipped silently when R2 isn't set (no public URI) or when the mint
    # fails for any reason — the Memo-anchored credential still stands.
    nft_info: Optional[dict[str, Any]] = None
    if body.mint_nft and cred_public_url and nft_mint.is_configured():
        name = body.nft_name or f"Nova Cred {cred_id.split('_')[-1]}"
        symbol = body.nft_symbol or "NOVA"
        try:
            nft = nft_mint.mint_nft(
                name=name[:32],       # Metaplex hard cap
                symbol=symbol[:10],
                uri=cred_public_url,  # hard cap 200, R2 URL fits easily
            )
            nft_info = {
                "mint": nft.mint_address,
                "ata": nft.ata_address,
                "metadata_pda": nft.metadata_pda,
                "tx": nft.signature,
                "explorer_mint_url": nft.explorer_mint_url,
                "explorer_tx_url": nft.explorer_tx_url,
            }
        except Exception as e:  # noqa: BLE001
            # Honest surface, never break the mint over the NFT step.
            nft_info = {"error": str(e)[:300]}

    return {
        "status": "minted",
        "id": cred_id,
        "canonical_sha256": digest_hex,
        "signature_b58": sig_b58,
        "signer_pubkey": signer.pubkey_b58,
        "solana": tx,
        "explorer_url": tx.get("explorer_url"),
        "credential_file": str(out),
        "credential_public_url": cred_public_url,
        "nft": nft_info,
        "verify_url": f"/v/{cred_id}",
    }


@app.get("/credentials")
def list_credentials() -> dict[str, Any]:
    files = sorted(CRED_DIR.glob("cred_*.json"))
    rows = []
    for f in files:
        try:
            d = json.loads(f.read_text())
            rows.append({
                "id": d["credential"]["id"],
                "issued_at": d["credential"]["issued_at"],
                "signature_b58": d["signature_b58"][:16] + "...",
                "tx": d.get("solana", {}).get("signature"),
                "verify_url": f"/v/{d['credential']['id']}",
            })
        except Exception:
            continue
    return {"count": len(rows), "credentials": rows,
            "minted_registry": _registry.list_minted(),
            "pending": _registry.list_pending()}


def _load_credential_by_id(cred_id: str) -> dict[str, Any]:
    if not _CRED_ID_RE.match(cred_id):
        raise HTTPException(400, "invalid credential id")
    f = CRED_DIR / f"{cred_id}.json"
    if not f.exists():
        raise HTTPException(404, "credential not found")
    try:
        return json.loads(f.read_text())
    except Exception:
        raise HTTPException(500, "credential file is corrupt")


@app.get("/api/credential/{cred_id}")
def api_credential(cred_id: str) -> dict[str, Any]:
    """Raw credential payload served to the verify page's JS."""
    return _load_credential_by_id(cred_id)


@app.get("/v/{cred_id}")
def verify_page(cred_id: str) -> FileResponse:
    """Human verify page. Static HTML; actual verification runs in the browser."""
    # Trigger existence check so we 404 cleanly instead of serving an empty page.
    _load_credential_by_id(cred_id)
    return FileResponse(STATIC_DIR / "verify.html")


@app.get("/verify")
def verify(tx: str, id: str | None = None) -> dict[str, Any]:
    """JSON verify-by-tx. Reads the memo from devnet, re-hashes the local
    credential, verifies ed25519 signature against the issuer pubkey."""
    memo = solana_memo.fetch_memo(tx)
    if not memo:
        raise HTTPException(404, "memo not found for tx")
    try:
        version, cred_id, digest_hex, sig_b58 = memo.split("|", 3)
    except ValueError:
        raise HTTPException(400, f"malformed memo: {memo!r}")
    if version != "v1":
        raise HTTPException(400, f"unsupported memo version: {version}")

    target = id or cred_id
    d = _load_credential_by_id(target)
    credential = d["credential"]

    canonical_bytes = canonicalize(credential)
    local_digest = sha256_hex(canonical_bytes)
    hash_ok = local_digest == digest_hex

    pub = credential.get("issuer_pubkey") or os.environ.get("STUDENT_PUBLIC_KEY_BASE58", "")
    sig_ok = ed25519_verify(pub, canonical_bytes, sig_b58) if pub else False

    return {
        "tx": tx,
        "cred_id": cred_id,
        "memo_digest": digest_hex,
        "local_digest": local_digest,
        "hash_matches": hash_ok,
        "signature_valid": sig_ok,
        "issuer_pubkey": pub,
        "verdict": "valid" if (hash_ok and sig_ok) else "invalid",
    }


@app.post("/airdrop")
def airdrop() -> dict[str, Any]:
    """Devnet only. Fund the student pubkey so it can pay for memo txs."""
    if os.environ.get("SOLANA_CLUSTER", "devnet") != "devnet":
        raise HTTPException(400, "airdrop only available on devnet")
    pub = os.environ.get("STUDENT_PUBLIC_KEY_BASE58", "")
    if not pub:
        raise HTTPException(400, "STUDENT_PUBLIC_KEY_BASE58 not set")
    return solana_memo.airdrop(pub, sol=1.0)


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "9010"))
    uvicorn.run(app, host="0.0.0.0", port=port)

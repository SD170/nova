"""Credential agent HTTP service.

Endpoints:
  GET  /health                 service + chain health
  POST /mint_credential        fetch → canonical → sign → memo on devnet
  GET  /verify?tx=...          read memo, verify sig against student pubkey
  GET  /credentials            list local mint history
  POST /airdrop                devnet-only convenience
"""
from __future__ import annotations

import json
import os
import pathlib
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from .canonical import canonicalize, sha256_hex
from .canvas_fetch import fetch_transcript
from .signer import Signer, load_from_env, verify as ed25519_verify
from . import solana_memo

HERE = pathlib.Path(__file__).parent.parent
CRED_DIR = HERE / "credentials"
CRED_DIR.mkdir(exist_ok=True)


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
        if k and k not in os.environ:
            os.environ[k] = v


# apps/cred-agent/.env first, then shared.env (repo root)
_load_env_file(HERE / ".env")
_load_env_file(HERE.parent.parent / "shared.env")


app = FastAPI(title="Nova credential agent", version="0.1")
_signer: Signer | None = None


def get_signer() -> Signer:
    global _signer
    if _signer is None:
        _signer = load_from_env()
    return _signer


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
    }


@app.post("/mint_credential")
async def mint_credential() -> dict[str, Any]:
    signer = get_signer()
    # 1. Fetch academic data
    try:
        transcript_data = await fetch_transcript()
    except Exception as e:
        raise HTTPException(502, f"canvas fetch failed: {e}")

    # 2. Compose the credential envelope (what we sign)
    cred_id = f"cred_{int(time.time())}_{uuid.uuid4().hex[:6]}"
    credential = {
        "id": cred_id,
        "issuer_pubkey": signer.pubkey_b58,
        "subject_pubkey": signer.pubkey_b58,  # self-issued for demo
        "issued_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "canvas-mcp",
        "schema": "nova-cred/v1",
        "data": transcript_data,
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
    out.write_text(
        json.dumps({
            "credential": credential,
            "canonical_sha256": digest_hex,
            "signature_b58": sig_b58,
            "solana": tx,
        }, indent=2),
        encoding="utf-8",
    )

    return {
        "id": cred_id,
        "canonical_sha256": digest_hex,
        "signature_b58": sig_b58,
        "signer_pubkey": signer.pubkey_b58,
        "solana": tx,
        "explorer_url": tx.get("explorer_url"),
        "credential_file": str(out),
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
                "file": str(f),
            })
        except Exception:
            continue
    return {"count": len(rows), "credentials": rows}


@app.get("/verify")
def verify(tx: str, id: str | None = None) -> dict[str, Any]:
    """Verify a credential by its Solana tx signature.

    Flow: read memo from devnet → parse hash + sig → look up off-chain
    credential by id → re-canonicalize → check hash matches → verify ed25519.
    """
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
    cred_file = CRED_DIR / f"{target}.json"
    if not cred_file.exists():
        raise HTTPException(
            404,
            f"off-chain credential {target}.json not found locally; "
            "share the file from the issuer to complete verification",
        )
    d = json.loads(cred_file.read_text())
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

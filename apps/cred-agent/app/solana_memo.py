"""Post a credential to Solana via the Memo program.

Why memo-program:
  * Zero custom contract code. Memo is a core Solana program at
    MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr.
  * One instruction: any UTF-8 bytes up to ~566 chars on-chain.
  * Cost on devnet: ~0.000005 SOL. On mainnet: tiny.

We hit the public Solana JSON-RPC directly with httpx (solana-py 0.42 removed
the sync Client; the async one would force us to colour the whole service, and
we only need five methods).
"""
from __future__ import annotations

import base64
import os
from typing import Any

import base58
import httpx
from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.message import Message
from solders.pubkey import Pubkey
from solders.signature import Signature
from solders.transaction import Transaction

MEMO_PROGRAM_ID = Pubkey.from_string("MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr")


def _rpc_url() -> str:
    return os.environ.get("SOLANA_RPC_URL", "https://api.devnet.solana.com")


def _cluster() -> str:
    return os.environ.get("SOLANA_CLUSTER", "devnet")


def explorer_url(signature: str) -> str:
    return f"https://explorer.solana.com/tx/{signature}?cluster={_cluster()}"


def build_memo_body(cred_id: str, digest_hex: str, sig_b58: str) -> bytes:
    body = f"v1|{cred_id}|{digest_hex}|{sig_b58}"
    b = body.encode("utf-8")
    if len(b) > 566:
        raise ValueError(f"memo body too large: {len(b)} bytes")
    return b


def _rpc(method: str, params: list[Any]) -> Any:
    r = httpx.post(
        _rpc_url(),
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        timeout=30.0,
    )
    r.raise_for_status()
    body = r.json()
    if "error" in body:
        raise RuntimeError(f"solana rpc {method}: {body['error']}")
    return body["result"]


def post_memo(payer_priv_b58: str, memo: bytes) -> dict[str, Any]:
    """Submit a memo transaction. Returns {signature, explorer_url}."""
    payer = Keypair.from_bytes(base58.b58decode(payer_priv_b58))
    ix = Instruction(
        program_id=MEMO_PROGRAM_ID,
        data=memo,
        accounts=[AccountMeta(payer.pubkey(), is_signer=True, is_writable=False)],
    )
    blockhash_str = _rpc("getLatestBlockhash", [{"commitment": "confirmed"}])["value"]["blockhash"]
    from solders.hash import Hash
    blockhash = Hash.from_string(blockhash_str)
    msg = Message.new_with_blockhash([ix], payer.pubkey(), blockhash)
    tx = Transaction.new_unsigned(msg)
    tx.sign([payer], blockhash)
    raw_b64 = base64.b64encode(bytes(tx)).decode()
    sig = _rpc("sendTransaction", [raw_b64, {"encoding": "base64", "skipPreflight": False}])
    return {"signature": sig, "explorer_url": explorer_url(sig)}


def fetch_memo(signature: str) -> str | None:
    """Return the memo UTF-8 string posted under this tx signature."""
    # Confirm the signature parses
    Signature.from_string(signature)
    tx = _rpc(
        "getTransaction",
        [signature, {"encoding": "json", "maxSupportedTransactionVersion": 0,
                     "commitment": "confirmed"}],
    )
    if not tx:
        return None
    logs = (tx.get("meta") or {}).get("logMessages") or []
    for line in logs:
        if "Memo (len" in line:
            i = line.find('"')
            j = line.rfind('"')
            if 0 <= i < j:
                return line[i + 1 : j]
    # Fallback: scan instructions' data (base58 in JSON encoding)
    inst = (tx.get("transaction") or {}).get("message", {}).get("instructions") or []
    for ix in inst:
        data = ix.get("data")
        if not data:
            continue
        try:
            return base58.b58decode(data).decode("utf-8")
        except Exception:
            continue
    return None


def airdrop(pubkey_b58: str, sol: float = 1.0) -> dict[str, Any]:
    """Convenience: devnet airdrop so the signer can pay for the memo tx."""
    lamports = int(sol * 1_000_000_000)
    sig = _rpc("requestAirdrop", [pubkey_b58, lamports])
    return {"signature": sig, "explorer_url": explorer_url(sig)}

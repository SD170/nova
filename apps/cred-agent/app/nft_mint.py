"""Mint a Metaplex NFT per credential.

What this builds, on devnet by default:
  1. A fresh SPL mint account (decimals=0, mint_authority=payer)
  2. An associated token account (ATA) for the payer
  3. mint_to 1 token into the ATA
  4. A Metaplex Token Metadata PDA at
     seeds=[b"metadata", METADATA_PROGRAM_ID, mint_pubkey]
     with {name, symbol, uri} pointing at the public R2 credential JSON

After steps 1–4 land, Phantom shows the NFT under "Collectibles" on devnet.
The `uri` is the signed credential JSON; wallet + explorer fetch it and
render whatever metadata we embedded (including the witness screenshot URL,
so most wallets will show it as the NFT image automatically).

Trust model (unchanged from the earlier plain-memo pipeline):
  * The NFT URI is tamper-evident because the credential JSON contains the
    canonical hash + ed25519 signature; any mutation breaks verify.
  * The on-chain NFT metadata is mutable by `update_authority`. We leave
    that as the payer (student) for now; set `is_mutable=False` once you
    want it frozen forever. (Argued below.)

Why we keep `is_mutable=True` for the demo: in the interim between devnet
rehearsals we want to be able to reissue without having to spin up fresh
mints each time. For prod we'd freeze.

Fallback: `is_configured()` returns False if the student pubkey isn't in env
or SOLANA_RPC_URL is unset. /mint_credential catches NFTMintError and still
anchors via the plain Memo program.
"""
from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from typing import Any, Optional

import base58
import httpx
from solders.hash import Hash
from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.message import Message
from solders.pubkey import Pubkey
from solders.system_program import CreateAccountParams, create_account
from solders.transaction import Transaction

# SPL token instructions already exposed by solana-py 0.42
from spl.token.constants import TOKEN_PROGRAM_ID
from spl.token.instructions import (
    create_associated_token_account,
    get_associated_token_address,
    initialize_mint,
    mint_to,
)
# solana-py 0.42 keeps params dataclasses under spl.token.instructions.<Params>;
# older versions put them in spl.token.models. We re-import defensively.
try:
    from spl.token.instructions import InitializeMintParams, MintToParams  # type: ignore
except ImportError:  # 0.42 split
    from spl.token.models import InitializeMintParams, MintToParams  # type: ignore

METADATA_PROGRAM_ID = Pubkey.from_string("metaqbxxUerdq28cj1RbAWkYQm3ybzjb6a8bt518x1s")
# Account size of a bare Mint account (SPL: 82 bytes). Hard-coded because the
# rent-exempt balance query needs just the size.
MINT_ACCOUNT_SIZE = 82


class NFTMintError(RuntimeError):
    pass


# ── tiny borsh encoder for DataV2 ───────────────────────────────────────────
#
# Metaplex `CreateMetadataAccountV3` payload is a borsh-serialized
#   { discriminator: u8 = 33,
#     data: DataV2 {
#       name:        String,
#       symbol:      String,
#       uri:         String,
#       seller_fee_basis_points: u16,
#       creators:    Option<Vec<Creator>>,
#       collection:  Option<Collection>,
#       uses:        Option<Uses>,
#     },
#     is_mutable: bool,
#     collection_details: Option<CollectionDetails>,
#   }
#
# For our use case: no creators, no collection, no uses, no collection_details.
# Each Option<T> is encoded as a single u8 tag (0 = None, 1 = Some) followed by
# T's bytes. String is u32 length + UTF-8 bytes.

def _u8(n: int) -> bytes: return bytes([n & 0xff])
def _u16_le(n: int) -> bytes: return (n & 0xffff).to_bytes(2, "little")
def _u32_le(n: int) -> bytes: return (n & 0xffffffff).to_bytes(4, "little")
def _bool(b: bool) -> bytes: return _u8(1 if b else 0)

def _str(s: str) -> bytes:
    b = s.encode("utf-8")
    return _u32_le(len(b)) + b


def _encode_create_metadata_v3(name: str, symbol: str, uri: str,
                               seller_fee_bps: int = 0,
                               is_mutable: bool = True) -> bytes:
    data = (
        _str(name) +
        _str(symbol) +
        _str(uri) +
        _u16_le(seller_fee_bps) +
        _u8(0) +  # creators: None
        _u8(0) +  # collection: None
        _u8(0)    # uses: None
    )
    payload = (
        _u8(33) +            # instruction discriminator
        data +
        _bool(is_mutable) +
        _u8(0)               # collection_details: None
    )
    return payload


def _metadata_pda(mint: Pubkey) -> Pubkey:
    pda, _bump = Pubkey.find_program_address(
        [b"metadata", bytes(METADATA_PROGRAM_ID), bytes(mint)],
        METADATA_PROGRAM_ID,
    )
    return pda


def _rpc_url() -> str:
    return os.environ.get("SOLANA_RPC_URL", "https://api.devnet.solana.com")


def _cluster() -> str:
    return os.environ.get("SOLANA_CLUSTER", "devnet")


def _rpc(method: str, params: list[Any]) -> Any:
    r = httpx.post(
        _rpc_url(),
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        timeout=30.0,
    )
    r.raise_for_status()
    body = r.json()
    if "error" in body:
        raise NFTMintError(f"solana rpc {method}: {body['error']}")
    return body["result"]


# ── public API ──────────────────────────────────────────────────────────────

def is_configured() -> bool:
    return bool(
        os.environ.get("STUDENT_PRIVATE_KEY_BASE58")
        and os.environ.get("STUDENT_PUBLIC_KEY_BASE58")
    )


@dataclass
class NFTMintResult:
    mint_address: str
    ata_address: str
    metadata_pda: str
    signature: str
    explorer_mint_url: str
    explorer_tx_url: str


def mint_nft(name: str, symbol: str, uri: str,
             payer_priv_b58: Optional[str] = None,
             is_mutable: bool = True) -> NFTMintResult:
    """Mint a 1-of-1 NFT with Metaplex metadata pointing at `uri`.

    Does 4 things atomically in one transaction:
      - create mint account (CreateAccount)
      - initialize mint (InitializeMint, decimals=0)
      - create ATA for payer
      - mint_to 1 token into the ATA
    Then a SECOND transaction creates the metadata PDA (CreateMetadataAccountV3).
    Two txs because mint signer requirements + metadata signer differ; keeping
    them split also makes debugging explorer links easier.
    """
    priv_b58 = payer_priv_b58 or os.environ.get("STUDENT_PRIVATE_KEY_BASE58", "")
    if not priv_b58:
        raise NFTMintError("STUDENT_PRIVATE_KEY_BASE58 not set")

    payer = Keypair.from_bytes(base58.b58decode(priv_b58))
    mint_kp = Keypair()
    mint = mint_kp.pubkey()
    ata = get_associated_token_address(payer.pubkey(), mint)

    rent_lamports = _rpc("getMinimumBalanceForRentExemption", [MINT_ACCOUNT_SIZE])
    blockhash = Hash.from_string(
        _rpc("getLatestBlockhash", [{"commitment": "confirmed"}])["value"]["blockhash"]
    )

    # ── Tx 1: mint + ata + mint_to ──────────────────────────────────────────
    ix_create = create_account(CreateAccountParams(
        from_pubkey=payer.pubkey(),
        to_pubkey=mint,
        lamports=rent_lamports,
        space=MINT_ACCOUNT_SIZE,
        owner=TOKEN_PROGRAM_ID,
    ))
    ix_init_mint = initialize_mint(InitializeMintParams(
        program_id=TOKEN_PROGRAM_ID,
        mint=mint,
        decimals=0,
        mint_authority=payer.pubkey(),
        freeze_authority=payer.pubkey(),
    ))
    ix_ata = create_associated_token_account(
        payer=payer.pubkey(), owner=payer.pubkey(), mint=mint,
    )
    ix_mint_to = mint_to(MintToParams(
        program_id=TOKEN_PROGRAM_ID,
        mint=mint,
        dest=ata,
        mint_authority=payer.pubkey(),
        amount=1,
    ))
    msg1 = Message.new_with_blockhash(
        [ix_create, ix_init_mint, ix_ata, ix_mint_to],
        payer.pubkey(), blockhash,
    )
    tx1 = Transaction.new_unsigned(msg1)
    tx1.sign([payer, mint_kp], blockhash)
    tx1_b64 = base64.b64encode(bytes(tx1)).decode()
    sig1 = _rpc("sendTransaction", [tx1_b64,
        {"encoding": "base64", "skipPreflight": False,
         "preflightCommitment": "confirmed"}])

    # Confirm tx1 before firing the metadata tx — otherwise Metaplex program
    # sees a mint that doesn't exist yet.
    _wait_for_confirmation(sig1)

    # ── Tx 2: Metaplex metadata PDA ────────────────────────────────────────
    metadata_pda = _metadata_pda(mint)
    payload = _encode_create_metadata_v3(name, symbol, uri,
                                         seller_fee_bps=0, is_mutable=is_mutable)
    #  Accounts per Metaplex IDL for CreateMetadataAccountV3:
    #    0. [writable]       metadata PDA
    #    1. []               mint
    #    2. [signer]         mint authority
    #    3. [signer,writable] payer
    #    4. []               update authority
    #    5. []               system program
    #    6. (optional)       rent sysvar (deprecated, not needed)
    SYSTEM_PROGRAM = Pubkey.from_string("11111111111111111111111111111111")
    accounts = [
        AccountMeta(metadata_pda,   is_signer=False, is_writable=True),
        AccountMeta(mint,           is_signer=False, is_writable=False),
        AccountMeta(payer.pubkey(), is_signer=True,  is_writable=False),  # mint authority
        AccountMeta(payer.pubkey(), is_signer=True,  is_writable=True),   # payer
        AccountMeta(payer.pubkey(), is_signer=False, is_writable=False),  # update authority
        AccountMeta(SYSTEM_PROGRAM, is_signer=False, is_writable=False),
    ]
    ix_metadata = Instruction(
        program_id=METADATA_PROGRAM_ID,
        data=payload,
        accounts=accounts,
    )
    blockhash2 = Hash.from_string(
        _rpc("getLatestBlockhash", [{"commitment": "confirmed"}])["value"]["blockhash"]
    )
    msg2 = Message.new_with_blockhash([ix_metadata], payer.pubkey(), blockhash2)
    tx2 = Transaction.new_unsigned(msg2)
    tx2.sign([payer], blockhash2)
    sig2 = _rpc("sendTransaction", [base64.b64encode(bytes(tx2)).decode(),
        {"encoding": "base64", "skipPreflight": False,
         "preflightCommitment": "confirmed"}])
    _wait_for_confirmation(sig2)

    cluster = _cluster()
    return NFTMintResult(
        mint_address=str(mint),
        ata_address=str(ata),
        metadata_pda=str(metadata_pda),
        signature=sig2,
        explorer_mint_url=f"https://explorer.solana.com/address/{mint}?cluster={cluster}",
        explorer_tx_url=f"https://explorer.solana.com/tx/{sig2}?cluster={cluster}",
    )


def _wait_for_confirmation(sig: str, max_attempts: int = 30) -> None:
    """Block until the tx shows up in the ledger with commitment>=confirmed.
    Devnet rarely needs more than ~5s; we give up to ~15s."""
    import time
    for _ in range(max_attempts):
        res = _rpc("getSignatureStatuses", [[sig], {"searchTransactionHistory": False}])
        statuses = (res or {}).get("value") or []
        if statuses and statuses[0] is not None:
            err = statuses[0].get("err")
            if err:
                raise NFTMintError(f"tx {sig} failed on-chain: {err}")
            if statuses[0].get("confirmationStatus") in ("confirmed", "finalized"):
                return
        time.sleep(0.5)
    raise NFTMintError(f"tx {sig} not confirmed within timeout")

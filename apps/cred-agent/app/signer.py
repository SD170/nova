"""Ed25519 sign / verify over canonical credential bytes.

The student's keypair is loaded once at process start from the env. We never
hold the private key on disk inside the cred-agent service beyond the .env.
"""
from __future__ import annotations

import os

import base58
from solders.keypair import Keypair
from solders.pubkey import Pubkey


class Signer:
    def __init__(self, priv_b58: str, pub_b58: str) -> None:
        raw = base58.b58decode(priv_b58)
        # Solana secret key is 64 bytes (seed || pubkey). solders.Keypair
        # accepts the full 64-byte form via from_bytes.
        if len(raw) != 64:
            raise ValueError(f"STUDENT_PRIVATE_KEY_BASE58 decodes to {len(raw)} bytes; expected 64")
        self._kp = Keypair.from_bytes(raw)
        if str(self._kp.pubkey()) != pub_b58:
            raise ValueError(
                "STUDENT_PUBLIC_KEY_BASE58 does not match the pubkey derived "
                "from STUDENT_PRIVATE_KEY_BASE58"
            )
        self.pubkey_b58 = pub_b58

    def sign(self, msg: bytes) -> str:
        """Return base58-encoded 64-byte signature."""
        sig = self._kp.sign_message(msg)
        return base58.b58encode(bytes(sig)).decode()


def verify(pub_b58: str, msg: bytes, sig_b58: str) -> bool:
    """Standalone verifier so anyone can check without the private key."""
    try:
        pub = Pubkey.from_string(pub_b58)
        sig_bytes = base58.b58decode(sig_b58)
        # solders doesn't expose raw ed25519 verify on Pubkey; use nacl via cryptography
        # To avoid an extra dep: pyca/cryptography handles ed25519 natively.
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        Ed25519PublicKey.from_public_bytes(bytes(pub)).verify(sig_bytes, msg)
        return True
    except Exception:
        return False


def load_from_env() -> Signer:
    priv = os.environ.get("STUDENT_PRIVATE_KEY_BASE58", "").strip()
    pub = os.environ.get("STUDENT_PUBLIC_KEY_BASE58", "").strip()
    if not priv or not pub:
        raise RuntimeError(
            "STUDENT_PRIVATE_KEY_BASE58 / STUDENT_PUBLIC_KEY_BASE58 not set. "
            "Run: python3 scripts/gen_keypair.py"
        )
    return Signer(priv, pub)

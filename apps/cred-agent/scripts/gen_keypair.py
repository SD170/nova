"""Generate a fresh Ed25519 keypair for the credential agent.

Writes STUDENT_PRIVATE_KEY_BASE58 + STUDENT_PUBLIC_KEY_BASE58 to stdout; paste
into apps/cred-agent/.env.

Solana secret-key format = 64 bytes = seed(32) || pubkey(32). solders'
Keypair.to_bytes() returns exactly that shape, base58-encoded.
"""
from __future__ import annotations

import sys

from solders.keypair import Keypair
import base58


def main() -> None:
    kp = Keypair()
    priv_b58 = base58.b58encode(bytes(kp)).decode()
    pub_b58 = str(kp.pubkey())
    print(f"STUDENT_PRIVATE_KEY_BASE58={priv_b58}")
    print(f"STUDENT_PUBLIC_KEY_BASE58={pub_b58}")
    print(f"\n# Fund the pubkey on devnet with:")
    print(f"#   solana airdrop 1 {pub_b58} --url devnet")
    print(f"# Or: curl -sS https://api.devnet.solana.com -X POST -H 'Content-Type: application/json' \\")
    print(f"#     -d '{{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"requestAirdrop\",")
    print(f"#          \"params\":[\"{pub_b58}\",1000000000]}}'")


if __name__ == "__main__":
    main()

# Nova credential agent

Standalone FastAPI service that turns a student's Canvas record into a
Solana-anchored, Ed25519-signed verifiable credential.

```
┌──────────────┐     ┌──────────────┐     ┌────────────────┐
│ Abishek's    │     │ cred-agent   │     │ Solana devnet  │
│ Canvas MCP   │ ──▶ │ (this svc)   │ ──▶ │ (Memo program) │
└──────────────┘     └──────────────┘     └────────────────┘
                           │
                           ▼
                     credentials/<id>.json
                     (off-chain, signed)
```

**What's on-chain:** a 100-ish byte memo `v1|<cred_id>|<sha256>|<sig>`.
**What's off-chain:** the full transcript JSON that the hash commits to.
**Why this design:** blockchain storage is expensive and public; we only anchor
proof, not data.

## Quick start

```bash
cd apps/cred-agent
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 1. Generate your student keypair
python3 scripts/gen_keypair.py >> .env

# 2. Fund it on devnet (free)
curl -X POST http://127.0.0.1:9010/airdrop   # after the server is up, see step 3

# 3. Run the service
cp .env.example .env    # if you haven't already; add the keypair lines
uvicorn app.main:app --port 9010

# 4. Mint
curl -X POST http://127.0.0.1:9010/mint_credential | jq
# → { "id": "cred_...", "canonical_sha256": "...", "solana": {"explorer_url": "..."}, ... }

# 5. Verify
curl "http://127.0.0.1:9010/verify?tx=<sig>" | jq
# → { "verdict": "valid", "hash_matches": true, "signature_valid": true, ... }
```

## Trust model (honest)

Without an ASU-signed source, the credential attests only:

> *"At time T, pubkey P fetched URL U and the fetched bytes hash to H."*

A third party trusting P can verify the signature + the chain anchor; they
still need to trust P's **integrity** — that P didn't fabricate the fetched
bytes. For a stronger chain, move the fetch into a public audited oracle
(TEE / signed browser agent) and have P's key co-sign with the oracle's key.
See `research_asu_credentials.md` at repo root for the ASU-specific analysis.

## Later

- MyASU scrape endpoint on Abishek's browser-agent → replace `canvas_fetch`
- Compact credentials once Canvas Credentials rolls out at ASU
- Multi-signer envelopes (student + oracle) once we deploy the browser-oracle
- cNFT minting instead of plain memo for richer metadata

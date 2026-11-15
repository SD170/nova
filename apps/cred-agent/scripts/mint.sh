#!/usr/bin/env bash
# One-shot credential mint. Boots cred-agent if not running, mints, prints
# everything you need. Safe to run repeatedly — dedupe handles it.
#
# Usage:
#   ./scripts/mint.sh                               # one-shot mint, no witness
#   ./scripts/mint.sh grades                        # Canvas /grades screenshot witness
#   ./scripts/mint.sh grades hw3                    # custom item_key
#   ./scripts/mint.sh grades hw3 "Nova HW3 proof"   # + NFT display name
#
# Env: reads apps/cred-agent/.env for keys, R2 creds, Canvas tunnel.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${PORT:-9010}"
BASE="http://127.0.0.1:${PORT}"

CAPTURE_PATH="${1:-}"     # e.g. grades  or  courses/12345/grades
ITEM_KEY="${2:-manual:$(date +%s)}"
NFT_NAME="${3:-}"

# 1. Boot service if it's not already up
if ! curl -fsS "${BASE}/health" > /dev/null 2>&1; then
    echo "→ booting cred-agent at :${PORT}"
    pushd "$HERE" > /dev/null
    [ -d .venv ] || { echo "run: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2; exit 2; }
    .venv/bin/uvicorn app.main:app --port "$PORT" --log-level warning > /tmp/cred-agent.log 2>&1 &
    PID=$!
    echo "  pid=$PID (logs: /tmp/cred-agent.log)"
    popd > /dev/null
    for i in 1 2 3 4 5 6 7 8 9 10; do
        sleep 0.5
        curl -fsS "${BASE}/health" > /dev/null 2>&1 && break
    done
    curl -fsS "${BASE}/health" > /dev/null || { echo "cred-agent failed to boot; see /tmp/cred-agent.log" >&2; exit 3; }
fi

# 2. Health sanity-check
HEALTH=$(curl -fsS "${BASE}/health")
R2=$(echo "$HEALTH" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('r2_configured'))")
SIG=$(echo "$HEALTH" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('signer_loaded'))")
PUB=$(echo "$HEALTH" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('student_pubkey') or '')")
echo "→ health:  signer=${SIG}  r2=${R2}  pubkey=${PUB}"
if [ "$SIG" != "True" ]; then
    echo "❌ STUDENT_PRIVATE_KEY_BASE58 not set. Run: cd apps/cred-agent && .venv/bin/python scripts/gen_keypair.py >> .env" >&2
    exit 4
fi

# 3. Build mint body
BODY=$(python3 <<EOF
import json
body = {"item_key": "${ITEM_KEY}"}
cap = "${CAPTURE_PATH}".strip()
if cap:
    if not cap.startswith("/"):
        cap = "/" + cap
    body["browser_capture_path"] = cap
name = "${NFT_NAME}".strip()
if name:
    body["nft_name"] = name
print(json.dumps(body))
EOF
)
echo "→ mint body: $BODY"

# 4. Fire mint
echo "→ POST /mint_credential"
# Split body (stdout) and HTTP status (via -w to stderr) so parsing stays sane.
RESP_FILE=$(mktemp)
HTTP_CODE=$(curl -sS -X POST "${BASE}/mint_credential" \
    -H "Content-Type: application/json" \
    -d "$BODY" \
    -o "$RESP_FILE" \
    -w "%{http_code}")
RESP=$(cat "$RESP_FILE")
rm -f "$RESP_FILE"
if [ "$HTTP_CODE" != "200" ]; then
    echo "❌ HTTP $HTTP_CODE from /mint_credential"
    echo "$RESP" | head -40
    echo
    echo "common causes:"
    echo "  * STUDENT_PUBLIC_KEY_BASE58 has zero devnet SOL"
    echo "    (memo ~0.000005 SOL, NFT ~0.012 SOL — airdrop with:"
    echo "     curl -sS https://api.devnet.solana.com -X POST -H 'Content-Type: application/json' \\"
    echo "       -d '{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"requestAirdrop\",\"params\":[\"${PUB}\",2000000000]}')"
    echo "  * PUBLIC_CANVAS_BASE unreachable (set in apps/cred-agent/.env or shared.env)"
    echo "  * Solana devnet degraded (check https://status.solana.com)"
    exit 5
fi

# 5. Present the result
python3 - "$RESP" <<'PY'
import json, sys
r = json.loads(sys.argv[1])
status = r.get("status")
cid = r.get("id") or r.get("cred_id")
print()
print("═" * 70)
print(f"  STATUS:        {status}")
print(f"  CRED ID:       {cid}")
if r.get("canonical_sha256"):
    print(f"  CANONICAL SHA: {r['canonical_sha256']}")
sol = (r.get("solana") or {})
if sol.get("signature"):
    print(f"  SOLANA TX:     {sol['signature']}")
    print(f"  EXPLORER:      {sol.get('explorer_url')}")
if r.get("credential_public_url"):
    print(f"  PUBLIC JSON:   {r['credential_public_url']}")
nft = r.get("nft")
if nft:
    if nft.get("error"):
        print(f"  NFT:           ⚠ skipped — {nft['error']}")
    else:
        print(f"  NFT MINT:      {nft.get('mint')}")
        print(f"  NFT EXPLORER:  {nft.get('explorer_mint_url')}")
        print(f"  NFT TX:        {nft.get('explorer_tx_url')}")
elif r.get("credential_public_url"):
    print("  NFT:           (skipped, nft_mint off or configured only for R2)")
if r.get("verify_url"):
    print(f"  VERIFY PAGE:   http://127.0.0.1:9010{r['verify_url']}")
print("═" * 70)
PY

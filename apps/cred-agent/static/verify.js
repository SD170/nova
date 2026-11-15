/* Nova credential verifier — in-browser hash + signature check.
 *
 * Loads /api/credential/<id> → {credential, canonical_sha256, signature_b58, solana}
 * Hashes the (editable) canonical bytes with WebCrypto SHA-256.
 * Verifies the Ed25519 signature with noble/ed25519 loaded via dynamic ESM import.
 *
 * Tamper flow: Tamper button enables the JSON textarea; on every keystroke we
 * re-canonicalize (sorted keys, compact JSON), re-hash, and re-verify. Mismatch
 * is immediately visible — both hash and signature rows flip red.
 */

// ── tiny helpers ────────────────────────────────────────────────────────────

const $ = (id) => document.getElementById(id);

const BASE58_ALPHA = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
const BASE58_MAP = (() => {
  const m = new Int16Array(256).fill(-1)
  for (let i = 0; i < BASE58_ALPHA.length; i++) m[BASE58_ALPHA.charCodeAt(i)] = i
  return m
})()

function b58decode(str) {
  let bytes = [0]
  for (const c of str) {
    const d = BASE58_MAP[c.charCodeAt(0)]
    if (d < 0) throw new Error('bad base58 char ' + c)
    let carry = d
    for (let j = 0; j < bytes.length; j++) {
      const v = bytes[j] * 58 + carry
      bytes[j] = v & 0xff
      carry = v >> 8
    }
    while (carry) { bytes.push(carry & 0xff); carry >>= 8 }
  }
  for (const c of str) { if (c !== '1') break; bytes.push(0) }
  return new Uint8Array(bytes.reverse())
}

async function sha256Hex(bytes) {
  const buf = await crypto.subtle.digest('SHA-256', bytes)
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, '0')).join('')
}

/** Match Python's canonicalize(): sort keys at every depth, compact JSON, UTF-8. */
function canonicalize(value) {
  if (value === null || typeof value !== 'object') return JSON.stringify(value)
  if (Array.isArray(value)) return '[' + value.map(canonicalize).join(',') + ']'
  const keys = Object.keys(value).sort()
  return '{' + keys.map((k) => JSON.stringify(k) + ':' + canonicalize(value[k])).join(',') + '}'
}

function canonicalBytes(obj) {
  return new TextEncoder().encode(canonicalize(obj))
}

// ── state ────────────────────────────────────────────────────────────────────

let original = null       // untouched credential from server
let anchorHash = null     // sha256 as posted in the Solana memo
let signatureB58 = null
let issuerPubB58 = null
let ed25519 = null        // noble/ed25519 module (lazy)

async function loadEd25519() {
  if (ed25519) return ed25519
  // UMD + ESM both available; prefer ESM via jsdelivr/esm.sh. If offline, this
  // throws → we fall back to showing "sig: unknown" and rely on hash match.
  try {
    ed25519 = await import('https://esm.sh/@noble/ed25519@2.1.0')
  } catch (e) {
    console.warn('ed25519 module load failed; signature check disabled', e)
  }
  return ed25519
}

// ── render ───────────────────────────────────────────────────────────────────

function setBanner(verdict, sub) {
  const b = $('banner'), t = $('banner-text'), s = $('banner-sub')
  b.classList.remove('ok', 'bad')
  if (verdict === 'ok')  { b.classList.add('ok');  t.textContent = '✅ Verified credential' }
  if (verdict === 'bad') { b.classList.add('bad'); t.textContent = '❌ Verification failed' }
  if (verdict === null)  {                          t.textContent = 'Verifying…' }
  s.textContent = sub || ''
}

function setHashRow(liveHex) {
  const el = $('live-hash'), badge = $('hash-badge')
  el.textContent = liveHex
  const ok = liveHex === anchorHash
  el.classList.toggle('ok', ok); el.classList.toggle('bad', !ok)
  badge.textContent = ok ? 'match' : 'mismatch'
  badge.classList.toggle('ok', ok); badge.classList.toggle('bad', !ok)
  return ok
}

function setSigRow(isValid) {
  const el = $('sig-value'), badge = $('sig-badge')
  if (isValid === null) {
    el.textContent = '(ed25519 module unavailable)'
    el.classList.remove('ok', 'bad'); badge.textContent = '…'
    badge.classList.remove('ok', 'bad')
    return
  }
  el.textContent = signatureB58.slice(0, 48) + '…'
  el.classList.toggle('ok', isValid); el.classList.toggle('bad', !isValid)
  badge.textContent = isValid ? 'valid' : 'invalid'
  badge.classList.toggle('ok', isValid); badge.classList.toggle('bad', !isValid)
}

async function recheck(body) {
  const bytes = canonicalBytes(body)
  const liveHex = await sha256Hex(bytes)
  const hashOk = setHashRow(liveHex)

  let sigOk = null
  const ed = await loadEd25519()
  if (ed) {
    try {
      const sig = b58decode(signatureB58)
      const pub = b58decode(issuerPubB58)
      sigOk = await ed.verifyAsync(sig, bytes, pub)
    } catch (e) {
      console.error('verify crashed', e)
      sigOk = false
    }
  }
  setSigRow(sigOk)

  if (sigOk === null) {
    setBanner(hashOk ? 'ok' : 'bad',
              hashOk ? 'hash matches; signature check offline' :
                       'hash does not match the on-chain anchor')
  } else {
    const ok = hashOk && sigOk
    setBanner(ok ? 'ok' : 'bad',
              ok ? 'hash and signature both verified in your browser' :
                   'credential has been modified')
  }
}

// ── boot ─────────────────────────────────────────────────────────────────────

async function main() {
  const path = location.pathname
  const credId = path.startsWith('/v/') ? path.slice(3).split(/[?/]/)[0] : null
  if (!credId) {
    setBanner('bad', 'missing credential id in URL')
    return
  }

  let data
  try {
    const r = await fetch('/api/credential/' + encodeURIComponent(credId), { cache: 'no-store' })
    if (!r.ok) throw new Error('HTTP ' + r.status)
    data = await r.json()
  } catch (e) {
    setBanner('bad', 'credential not found')
    return
  }

  original     = data.credential
  anchorHash   = data.canonical_sha256
  signatureB58 = data.signature_b58
  issuerPubB58 = original.issuer_pubkey

  $('m-id').textContent     = original.id || credId
  $('m-issued').textContent = original.issued_at || '—'
  $('m-issuer').textContent = issuerPubB58
  $('m-source').textContent = original.source || '—'
  $('m-tx').textContent     = (data.solana && data.solana.signature) || '—'
  $('explorer').href        = (data.solana && data.solana.explorer_url) || '#'
  $('anchor-hash').textContent = anchorHash

  // Screenshot if the credential declared one
  const shotUri = original?.witness?.screenshot_uri
  if (shotUri) {
    // Rewrite file:/// → /screenshots/<id>.png so the browser can load it from us
    const el = $('shot')
    el.src = shotUri.startsWith('file:') ? '/screenshots/' + credId + '.png' : shotUri
    el.style.display = 'block'
    $('shot-empty').style.display = 'none'
  }

  // Pretty-print into the textarea; parse this back on each tamper keystroke
  const ta = $('json')
  ta.value = JSON.stringify(original, null, 2)

  await recheck(original)

  $('tamper-btn').onclick = () => {
    ta.disabled = false
    $('reset-btn').disabled = false
    ta.focus()
  }
  $('reset-btn').onclick = async () => {
    ta.value = JSON.stringify(original, null, 2)
    ta.disabled = true
    $('reset-btn').disabled = true
    await recheck(original)
  }
  ta.addEventListener('input', async () => {
    let body
    try { body = JSON.parse(ta.value) }
    catch {
      setBanner('bad', 'JSON is not valid yet')
      return
    }
    await recheck(body)
  })
}

main()

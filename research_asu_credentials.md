# ASU Verifiable Credentials — Research Findings

## Verdict (honest): **No, not for coursework grades.**

A regular ASU student **cannot** today download a cryptographically verifiable, university‑signed credential for a course grade or Canvas assignment completion that a third party can verify offline. The pieces ASU uses are fragmented and none of them cover "my CS 240 grade."

---

## What ASU actually issues

### 1. Credly (Open Badges 2.0) — **exists, but narrow scope**
- ASU has a verified Credly org page: `https://www.credly.com/organizations/arizona-state-university` (HTTP 200, confirmed).
- Issued by **EdPlus / Continuing & Professional Education / Workforce programs** (bootcamps, Universal Learner, CareerCatalyst, specific micro‑credentials).
- **Not issued for standard for‑credit coursework** (regular undergrad/grad classes on canvas.asu.edu do not auto‑produce Credly badges).
- Format: Open Badges 2.0 JSON hosted on Credly's server. Verification = HTTP fetch to credly.com, not a signed JWT/JSON‑LD a verifier can validate offline. (OB 2.0 uses hosted verification, not detached signatures by default.)

### 2. Official transcripts — Parchment (digitally signed PDFs)
- ASU Registrar routes all official transcripts through **Parchment** (`registrar.asu.edu/transcripts`, HTTP 200 confirmed).
- Delivered as a signed/encrypted PDF whose signature chains to Parchment's cert, not a W3C VC.
- Verification path: upload PDF to Parchment's portal — still an API call to a central authority. Not usable as a chain‑native verifiable credential.

### 3. MyASU / Enterprise Tech — **no public verifiable‑credential endpoint**
- No evidence of `credentials.asu.edu` or `vc.asu.edu` (DNS not responding).
- No announcements on news.asu.edu for "Open Badges 3.0", "Verifiable Credentials", "Blockcerts", or "Learn and Work Ecosystem" participation (news search returned no matching stories).

---

## Canvas LMS itself

- **Canvas core LMS: no native signed/verifiable export.** Grade PDFs, "View Grades" pages, and transcript CSVs are plain output. No detached signature, no VC, no Open Badge emission.
- **Canvas Credentials** (Instructure's product, formerly Badgr) is a **separately licensed add‑on**. It supports Open Badges 2.0 today and Instructure has publicly committed to OB 3.0 / W3C VC. But:
  - It is **not enabled on canvas.asu.edu** for general coursework. There is no public ASU documentation, no `badgr.asu.edu`/`credentials.canvas.asu.edu` subdomain, and the Credly org page suggests ASU standardized on Credly, not Canvas Credentials.
  - Even where enabled, badges are issued per‑course by the instructor — still not a universal "signed grade" export.
- Canvas REST API returns grades over OAuth2, but the response is **plain JSON signed only by TLS**. The moment you save it locally, it's indistinguishable from self‑signed JSON.

---

## State of the art in 2026 (universities actually issuing W3C VCs)

Who is genuinely issuing cryptographically verifiable academic credentials:
- **MIT / Digital Credentials Consortium (DCC)** — Blockcerts + VC‑JWT; diplomas since 2017, DCC Learner Credential Wallet.
- **TU Munich, Open University UK, Central New Mexico CC, University of Maine, TU Delft** — DCC consortium members issuing diplomas as VCs.
- **European EBSI** (Erasmus+ diplomas) — DID:ebsi + JSON‑LD VCs.
- **Instructure Canvas Credentials, 1EdTech CLR 2.0, T3 Innovation Network** — infrastructure for 2026 issuance, but adoption is per‑institution opt‑in.
- **ASU is not on the DCC member list** and has no public Blockcerts/EBSI pilot.

---

## Fallback architecture for the hackathon demo (recommended)

Since ASU is not a VC issuer, be upfront about the trust model. The clean, honest pattern is a **trusted‑oracle attestation**:

1. **Student authenticates to Canvas via OAuth** (Instructure's OAuth2 developer key — Canvas API returns grades as JSON).
2. **A hackathon‑operated attestation service** fetches grades from `canvas.asu.edu/api/v1/courses/:id/enrollments?user_id=self` **over the student's OAuth token**, hashes the canonical JSON, and signs the hash + metadata (student DID, course, grade, timestamp, Canvas server hostname) with the service's Ed25519 key.
3. **The signed attestation is anchored on Solana** (write the hash + attestor pubkey to a small program / memo; or mint a soulbound SPL token / Metaplex cNFT whose metadata URL points to the attestation JSON on Arweave/IPFS).
4. **Verifier flow:** read on‑chain record → fetch attestation → check attestor signature → trust = "this hash came from canvas.asu.edu through our oracle at time T."

Call this what it is in the pitch: **"notarized Canvas snapshot"**, not "ASU‑signed credential." Judges will respect the honesty and the architecture is still interesting (DID binding, revocation list on‑chain, selective disclosure of individual courses).

### One‑paragraph architectural recommendation
Build a Canvas OAuth oracle: student clicks "Connect ASU Canvas," your service exchanges the OAuth code, pulls their grade JSON from the Canvas REST API, canonicalizes (JCS) and hashes it, wraps it in a minimal W3C VC with your service as the `issuer` (use `did:key` or `did:web` on your domain) and the student as `credentialSubject.id` (a Solana‑derived did:pkh), signs with Ed25519, and writes the credential hash + issuer pubkey to a Solana program (or as a Metaplex cNFT the student owns). Verification = fetch VC from IPFS, check signature against your `did:web` document, check on‑chain hash match, check revocation bit. Emphasize to judges that trust terminates at **your oracle**, not ASU — the only way to remove that trust assumption is for ASU itself to become a VC issuer, which they aren't today.

---

## Gotchas

- **Canvas OAuth developer key:** ASU admins must approve third‑party developer keys per‑tenant. Student‑only "personal access tokens" work for demos but are long‑lived bearer tokens — never anchor/commit one.
- **FERPA**: grades are protected educational records. Showing another student's grades on stage is a legal problem; use your own account or a test account.
- **Rate limits**: Canvas API is ~700 req/hour/token (confirmed from live header `x-rate-limit-remaining: 700.0` on canvas.asu.edu).
- **Open Badges 2.0 ≠ cryptographically verifiable in the W3C sense** — it's hosted verification. Don't let a judge call this a VC unless you've actually moved to OB 3.0 / VC‑JWT.
- **Solana cost**: use a Memo program write or cNFT (bubblegum) to keep per‑credential cost sub‑cent; don't mint a full SPL token per grade.
- **Revocation**: include a bitstring status list URL in the VC (`StatusList2021`) so revocations don't require a chain write per student.

---

## TL;DR for the pitch

> "ASU doesn't currently issue W3C Verifiable Credentials for coursework — only Credly badges for continuing‑ed and Parchment‑signed PDFs for transcripts. So we built the missing piece: an OAuth oracle that reads your Canvas grades, signs an attestation, and anchors it on Solana. Trust terminates at our oracle, not at the chain — and the day ASU becomes a DCC member, we swap the issuer DID for theirs."

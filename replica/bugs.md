# Bug reports — ClipForge Studio (replica-test, 2026-10-17)

Suite: `e2e/test_api.py` (pytest + httpx, real HTTP against local server).
Severity: S1 = data loss / security hole / payments wrong / core flow blocked;
S2 = feature broken, no workaround; S3 = broken with workaround / visibly wrong;
S4 = cosmetic. Only reproduced bugs are listed.

## BUG-01 — Double-click "Generate" → 500 (S2)

- Steps: upload a video, POST `/app/projects/{pid}/generate` twice in a row.
- Expected: second request is handled gracefully (redirect to processing page),
  credits charged exactly once.
- Actual: second request returns **500 Internal Server Error** (IntegrityError
  from `uq_active_generation` in `enqueue()`). The credit charge rolls back
  atomically (verified: ledger still shows 1 charge), but the user sees a crash.
- Evidence: `e2e/test_api.py::TestF01Import::test_e10_double_generate_no_500_no_double_charge`
- Status: OPEN → fixed 2026-10-17 (guard in `generate()`: if project already
  `processing`, redirect to processing page without charging). Test passes.

## BUG-02 — No credit refund on permanent pipeline failure (S2)

- Steps: generate on a project whose source can never be processed
  (e.g. garbage bytes). Worker retries 3×, marks project `failed`.
- Expected (per architecture.md): a `refund` row in `credit_ledger` returning
  the generation charge.
- Actual: no refund anywhere — `worker._finish()` never writes one. Credits are
  lost with no recourse. (Credits are free grants in v1, so S2 not S1.)
- Evidence: `e2e/test_api.py::TestWorkerUnits::test_w1_no_refund_on_permanent_failure`
- Status: OPEN → fixed 2026-10-17 (`_finish()` failed branch now calls
  `grant_credits(..., "refund")` once when it flips a processing generation
  job's project to `failed`, and zeroes `credits_charged`). Test passes.

## BUG-03 — SSRF: worker fetches arbitrary user-supplied URLs incl. loopback (S1)

- Steps: POST `/app/projects` with `source_kind=url`,
  `source_url=http://127.0.0.1:<port>/probe` (a local listener). Trigger
  `pipeline.stage_fetch`.
- Expected: private/loopback/link-local/reserved IPs rejected before any request.
- Actual: **the listener recorded the request** — the worker fetched the
  internal URL with zero validation. Same vector reaches cloud metadata
  (`169.254.169.254`) in a cloud deployment → credential theft. S1 per the
  skill's severity table (security hole).
- Evidence: `e2e/test_api.py::TestF01Import::test_e9_ssrf_private_url_blocked`
  (`hits == ['/probe']` before fix).
- Status: OPEN → fixed 2026-10-17 (`_fetch_remote` now resolves the hostname
  and rejects non-public IPs via the `ipaddress` module). Test passes.
  Residual: DNS TOCTOU (resolve-then-fetch race) remains — acceptable for v1,
  noted for backend hardening.

## BUG-04 — Malformed JSON body on PATCH clip/caption → 500 (S3)

- Steps: `PATCH /app/clips/{cid}` with body `{not json`,
  `Content-Type: application/json`.
- Expected: 400 Bad Request.
- Actual: **500** (`json.decoder.JSONDecodeError` from `await request.json()`,
  unhandled). Same in `PATCH /app/captions/{cap_id}`.
- Evidence: `e2e/test_api.py::TestF02Clips::test_e3_invalid_json`
- Status: OPEN → fixed 2026-10-17 (both handlers catch decode errors → 400).
  Test passes.

## BUG-05 — Brand template form: invalid aspect_ratio / font_size → 500 (S3)

- Steps: POST `/app/brand-templates` with `aspect_ratio=evil` → **500**
  (SQLite CHECK constraint IntegrityError); with `font_size=abc` → **500**
  (`int()` ValueError).
- Expected: 4xx or sanitized to defaults.
- Actual: crash page on crafted form input.
- Evidence: `test_e1_evil_aspect_ratio_no_500`, `test_e2_bad_font_size_no_500`
- Status: OPEN → fixed 2026-10-17 (aspect_ratio whitelisted to the 4 presets,
  font_size coerced with safe default + clamp 16–200). Tests pass.

## BUG-06 — URL import broken in proxied environments (S2)

- Steps: in this sandbox (proxy env vars set), any `source_kind=url` import.
- Expected: direct-MP4 download works.
- Actual: `httpx.stream()` with default `trust_env=True` choked on the
  malformed proxy env (`InvalidURL: Invalid port: ':1]'`) — URL import 100%
  broken here. (URL import is a must-have per the feature matrix.)
- Evidence: initial `test_e9` failure trace; app log.
- Status: OPEN → fixed 2026-10-17 (`trust_env=False` in `_fetch_remote`,
  same workaround as `groq_client.py`). Test passes.

## BUG-07 — Double-click "Render" enqueues duplicate render jobs (S4)

- Steps: POST `/app/clips/{cid}/render` twice.
- Expected: one render job (idempotent).
- Actual: two `render` jobs queued (no UNIQUE guard covers `render` type,
  unlike the generation stages). Harmless — same output file — but burns CPU.
- Evidence: `e2e/test_api.py::TestF02Clips::test_e5_double_render_documented`
- Status: OPEN, documented, left unfixed (S4 — cosmetic/wasteful, no wrong
  result). Fix for later: extend the dedupe guard or make render idempotent
  per clip.

## BUG-08 — Negative trim_start_ms accepted (S3)

- Steps: `PATCH /app/clips/{cid}` with `{"trim_start_ms": -5000}`.
- Expected: 400 (trim outside clip bounds).
- Actual: 200, `-5000` stored; the failure would surface much later as an
  opaque render-job failure after retries.
- Evidence: `e2e/test_api.py::TestF02Clips::test_e2_negative_trim_observed`
- Status: OPEN → fixed 2026-10-17 (`patch_clip` validates: numbers only,
  start ≥ 0, end > start, within clip duration → 400 otherwise). Test passes.

## To-check list (suspicions, not reproduced — not bugs)

- T1: session cookie is a deterministic HMAC of user_id (no rotation); theft
  gives 30-day access. Mitigation (short-lived rotating sessions) is
  backend-round auth hardening.
- T2: no CSRF tokens on state-changing POST/PATCH routes — explicitly
  backend-round per build-log.
- T3: `create_project` reads the entire upload into disk with only a 10 GB
  cap — disk-fill DoS if many huge uploads; needs quota/rate limiting later.
- T4: `generate()` probes `local_media_path` with no existence check; a
  deleted source file charges 1 min then fails → now refunded (BUG-02 fix).

## Manual checks for the user (browser unreliable in this environment)

- M1 mobile width (390px): dashboard, editor, gallery usable
- M2 visual polish: score badges, karaoke captions, timeline scrubber
- M3 htmx progress polling on /processing feels live, no stuck states
- M4 toast messages appear on save/delete/schedule actions
- M5 keyboard-only tab order through editor controls

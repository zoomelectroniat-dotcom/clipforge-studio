# Build log — ClipForge Studio (clean-room OpusClip replica)

Working title: **ClipForge Studio**. No OpusClip name, logo, colors, or copy anywhere.
Stack: FastAPI + Jinja2 + htmx, SQLite (schema.sql), DB-backed job queue, FFmpeg, Groq (Whisper + gpt-oss-120b).

## Start commands (run from `~/workspace/opusclip-replica/app/`)

```bash
cd ~/workspace/opusclip-replica/app
../venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8901   # web app
GROQ_STUB=1 ../venv/bin/python worker.py                              # job worker (stub AI)
../venv/bin/python worker.py                                          # job worker (real Groq)
```

Demo login: `demo@clipforge.studio` / `clipforge-demo-123` (60 credits, seeded by `seed.py`).

## Files

| Path | What |
|---|---|
| `app/main.py` | 34 routes: public, auth, import, setup, processing, gallery, editor, export, brand kits, social/scheduler stubs, billing, analytics |
| `app/pipeline.py` | 7 stages: fetch → transcribe → detect → preview; render (incl. SRT). Chained by worker via `NEXT_STAGE` (one live job per project/clip per schema UNIQUE constraints) |
| `app/video.py` | ffprobe, wav extract, ASS karaoke captions, fill/fit/split reframe, thumbnails, SRT writer |
| `app/groq_client.py` | Whisper `transcribe()` + `detect_highlights()` on `openai/gpt-oss-120b`; `GROQ_STUB=1` for canned data. Bypasses broken proxy env (`trust_env=False` + explicit proxy) |
| `app/worker.py` | Polls `render_jobs`, atomic claim, retries with backoff, refunds credits on permanent failure |
| `app/auth.py` | bcrypt + HMAC-signed session cookies |
| `app/db.py` | `init_db()` runs `replica/schema.sql` idempotently (+ `curation_prefs` column) |
| `app/seed.py` | Creates schema + demo user |
| `app/templates/` | 16 Jinja2 templates (landing → export), htmx polling on processing page |
| `app/static/css/` | `tokens.css` generated from `replica/tokens.json` by `gen_tokens.py`; `app.css` hand-written against tokens |
| `replica/features-build.csv` | Copy of features.csv; all 26 must-haves marked `wip` with honest partial notes |

## Verified end-to-end (2026-10-17)

- **Real Groq**: `ping` 200; Whisper transcription OK; `detect_highlights` returned 2 scored clips (88/75) on a canned transcript.
- **Full loop (stub AI)**: signup → upload 90s MP4 (XHR progress) → setup prefs → generate → worker: fetch/transcribe/detect/preview → gallery shows 3 clips (scores 82/74/69) → editor (preview MP4 200, thumb 200, 5 transcript lines) → caption PATCH → trim/layout/prefs PATCH → re-render → final render → **1080×1920 h264 MP4 download** + **SRT download** (edited caption present).
- All 9 app pages return 200; brand-kit CRUD works; billing ledger records the credit spend.

## Known v1 gaps (all noted in features-build.csv)

1. Google OAuth not wired (email/password only).
2. YouTube/Drive/Vimeo URL download not implemented (yt-dlp) — direct MP4 fetch works.
3. No completion email; progress % only (no time ETA).
4. Trim via time inputs; text-selection trim not built.
5. Reframe is center-crop; speaker/face tracking not built.
6. Social posting + scheduler are queue-only stubs (phase 2); no Stripe checkout yet (credit ledger only).

## Next step

`/replica-test` — or `/replica-backend` for auth hardening (rate limits, CSRF), payments, and the 6 gaps above.

## Gap round — replica-backend (2026-10-17 ~19:00 +03)

Closed 6 gaps from the diff-report punch list; e2e suite now 47/47 (4 new tests).
Parity: 69.7 → 78.4. Must-haves: 23/26 done.

1. **YouTube URL download** — installed yt-dlp 2026.08.19 (venv + requirements.txt);
   `_fetch_remote` already had the yt-dlp path; added `noplaylist` guard and
   friendly error mapping (private / deleted / login-walled / unsupported /
   TLS-cert). Permanent failures surface on the project with Retry + refund.
   Sandbox caveat: sandbox DNS sinkholes all hosts to 198.18.x.x so the SSRF
   guard blocks yt-dlp here; verified the error mapping with the guard bypassed
   in a test script. Real-world DNS will pass public hosts.
2. **Timeline trim** — dual-handle scrubber in editor.html (CSS in app.css),
   synced both ways with the time-input fallback; server-side validation
   (BUG-08) unchanged. Speaker tags added to the transcript list.
3. **Completion email** — new `app/mailer.py` (stdlib smtplib); worker `_finish`
   sends clips-ready (preview done), render-ready (render done), and failure
   emails after DB commit; never raises. Env: SMTP_HOST/PORT/USER/PASS/FROM,
   APP_URL. No-op + log when SMTP_HOST unset. Documented in `../.env.example`.
4. **AI opening hook** — `GroqClient.rewrite_hooks()` (one batched LLM call,
   stub fallback) wired into `stage_detect` when `ai_hook` pref is on; failure
   keeps original titles. Verified: stub titles rewritten in detect run.
5. **Speaker labels** — `_assign_speakers()`: pause-heuristic (≥1.0s gap
   alternates Speaker 1/2), stored on caption_segments.speaker_label, shown as
   tags in editor. HONEST: not true diarization — Groq Whisper provides none.
6. **Brand kit** — font family (5 fc-list-verified fonts, allowlisted),
   caption text colour + keyword highlight colour (hex-validated), logo upload
   (≤2 MB png/jpg/webp, 0600 perms under data/logos/, auth-checked serve route
   `/media/logos/{tid}`, burned top-right at 18% width into previews + finals
   via FFmpeg overlay). Evil inputs sanitized to defaults; no 500s. Logo
   deleted with its template.

Not attempted (user-dependent, documented in backend.md): Google OAuth
(needs user's Google Cloud console), Stripe (needs keys + explicit approval).
Not attempted (hard, needs research spike): speaker-tracking reframe.

Files touched: app/pipeline.py, app/video.py, app/worker.py, app/main.py,
app/groq_client.py, app/mailer.py (new), app/templates/editor.html,
app/templates/brand_templates.html, app/static/css/app.css,
requirements.txt, .env.example (new), e2e/test_api.py (+4 tests),
replica/features-scored.csv, replica/diff-report.md, replica/backend.md (new).

## Speaker-tracking reframe — VERIFIED (2026-10-18, resumed after 2026-10-17 cancellation)
Approach chosen: **OpenCV DNN res10 SSD face detector** (`res10_300x300_ssd_iter_140000.caffemodel` +
`deploy.prototxt`, app/models/). Why: CPU-friendly (~100ms/frame on 1s samples), single 10MB weight file,
no GPU, no paid API, stdlib+opencv only. Rejected: MediaPipe (heavier dep, no real gain for this use),
audio-energy diarization (Groq Whisper gives no speaker signal — honest limit documented in code).

Licensing/provenance (honest): deploy.prototxt is Apache-2.0 (OpenCV repo). The caffemodel weights are
publicly distributed by the OpenCV project (opencv_3rdparty, sample/demo use). No explicit commercial
license grant found — REVIEW before monetizing the product. opencv-python pinned to 4.x (5.x removed the
Caffe importer this model needs). All code clean-room (video.py: detect_faces_timeline, plan_smart_crop,
_step_expr; pipeline.py: _smart_plan_for_clip; setup.html checkbox `smart_reframe`, default ON).

How it works: sample every 1s → detect faces → per-sample target = union-center if all faces fit the
9:16 crop window, else largest face (ties → frame centre) → EMA smoothing (alpha 0.35) + 2%-width
deadband → ffmpeg nested-if() crop expression tracks over time. No face ever → centre crop. Face
disappears mid-clip → holds last position (no whip-pan).

TEST EVIDENCE (2026-10-18, /tmp/verify_smart.py + verify_multi.py, real detector + real ffmpeg):
1. Synthetic 6s pan video (960x540, AI-generated face panning 480px): detector found the face in 5/6
   samples, face centre moved 848→542px; crop window (304x540) travelled 182px following it.
2. Full render_clip with smart plan → 1080x1920 MP4 produced; frames at t=0.5 vs t=5.0 differ
   (different source regions) — the crop genuinely moves in the output.
3. Multi-speaker: two close faces → union framed (x≈335); two far faces → converges on largest
   (440→611 over samples); zero faces → exact centre crop; face vanishing → holds, no snap.
Parity impact: speaker-tracking row must/partial → yes. Overall 78.4 → 79.8; must-haves 24/26.
Remaining honest limit: tracks FACES, not true active speakers — no diarization signal exists in the
pipeline (Groq Whisper provides none). Speaker labels stay pause-heuristic.
Post-verification (2026-10-18): e2e suite 52/52 green (47 existing + 5 new test_smart_reframe.py
unit tests for the crop planner). App + worker confirmed running (HTTP 200). features-scored.csv,
diff-report.md (79.8, 24/26 must-haves), and parity recomputed via the replica-diff parity.py tool.

## Credential round — Google OAuth / Drive / Stripe (2026-10-18)
- New modules: app/oauth_google.py (full OAuth2 code flow, Fernet-encrypted token storage, drive.readonly scope bundled), app/drive_dl.py (public-link download with confirm-token handling + private Drive API download), app/billing_stripe.py (Checkout sessions + HMAC webhook verification, httpx only).
- Routes: /auth/google + /auth/google/callback (login/signup, friendly no-500 errors), /app/settings + /app/settings/google-drive (Drive connect), /billing/checkout (inactive notice without keys), /billing/webhook (400 on bad sig, idempotent fulfill via webhook_events), /billing/success.
- pipeline: Drive source_type → public download first, then private via user's OAuth token; SSRF guard reused; friendly errors (folder links, private-without-connection, expired token).
- e2e: 57/57 (10 new). cryptography added to requirements.txt. .env.example + backend.md "Credential setup" (plain-language Google Cloud + Stripe steps).
- Parity 79.8 -> 81.2; must-haves 25/26 (Drive import closed; OAuth partial until credentials; Stripe wired-but-inactive).

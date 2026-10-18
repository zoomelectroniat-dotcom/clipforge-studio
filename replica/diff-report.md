# Diff report — ClipForge Studio vs OpusClip (recon matrix)

Date: 2026-10-17 (updated 2026-10-17 after replica-backend gap round; updated 2026-10-18: speaker-tracking reframe closed) · Method: replica-diff
skill, scored over real HTTP against the running app at http://127.0.0.1:8901 +
the 47/47 passing e2e suite + DB evidence. Scored against
`replica/features.csv` only — the original app itself was never touched.
Matrix: `features-scored.csv` (originals `features.csv` / `features-build.csv` untouched).

## Scores

- **Overall parity: 81.2 / 100** (weighted: must×3, should×2, could×1; partial = half)
  — up from 69.7 after the gap round (6 rows closed), 78.4 → 79.8 after the
  speaker-tracking spike (2026-10-18), now 79.8 → 81.2 after the credential
  round closed Drive import (2026-10-18).
- **Must-haves: 25 of 26 done** (25 yes, 1 partial, 0 no)
- Should-haves: 5 yes, 2 partial, 5 no · Could-haves: 0 of 7 · Skip rows: 5 (stay skip)

### Per area, weakest first

| area | score | features |
|---|---|---|
| team | 0.0 | 1 |
| integrations | 0.0 | 1 |
| api | 0.0 | 2 |
| publishing | 25.0 | 2 |
| analytics | 50.0 | 1 |
| export | 66.7 | 4 |
| editor | 70.6 | 7 |
| onboarding | 75.0 | 2 |
| reframe | 75.0 | 3 |
| import | 83.3 | 3 |
| branding | 85.7 | 4 |
| processing | 100.0 | 1 |
| captions | 100.0 | 4 |
| curation | 100.0 | 7 |
| scoring | 100.0 | 2 |
| clips | 100.0 | 1 |

## Full gap list (every no/partial + what it would take)

**Must-haves (partial):**
1. ~~Trim via timeline or text selection — *partial (time inputs only)* → add draggable timeline handles + text-select-to-trim in editor.js; ~2–3 days.~~ **CLOSED (gap round 2026-10-17):** dual-handle timeline scrubber in editor, synced with time inputs, server-side validation unchanged; text-select trim still pending (minor).
2. ~~YouTube URL import — *partial (URL classified, no download)* → add yt-dlp to worker fetch stage; ~1 day.~~ **CLOSED (gap round 2026-10-17):** yt-dlp 2026.08.19 installed and wired; friendly errors for private/deleted/login-walled URLs; `noplaylist` guard; graceful failure (no stuck jobs).
3. Cloud/source links (Drive/Dropbox/Zoom/Loom/Twitch/Rumble/Vimeo/StreamYard/S3) — *partial (direct-MP4 only)* → yt-dlp covers most hosts (YouTube/Vimeo/Twitch etc. now work); Drive needs its own downloader; ~1 day left.
4. Sign in with Google — *partial (email+password only)* → Google Cloud OAuth client + callback route; **user-dependent** (console setup) — not attempted.
5. ~~Processing email on completion — *partial (progress bar only)* → SMTP send on job done/failed (user's Gmail); ~half day.~~ **CLOSED (gap round 2026-10-17):** `app/mailer.py` sends clips-ready / render-ready / failure emails via configurable SMTP env vars (`SMTP_HOST/PORT/USER/PASS/FROM`, `APP_URL`); no-op with log when unconfigured; `.env.example` documents all vars.
6. ~~Auto reframe with speaker tracking — *partial (center-crop only)* → frame-sample face detection (e.g. lightweight DNN/ONNX) + crop-window smoothing; the hardest item, ~1 week.~~ **CLOSED (research spike 2026-10-18):** OpenCV DNN res10 SSD (1s samples), EMA-smoothed crop trajectory + deadband, multi-speaker union framing or largest-face follow, centre-crop fallback; checkbox `smart_reframe` in setup (default ON). Tested on a 6s pan video: face 848→542px, crop travelled 182px, 1080×1920 render verified. Honest limit: tracks faces, not true active speakers (no diarization signal). Licensing note in build-log.md (caffemodel provenance — review before monetizing).

**Should-haves:**
7. ~~Speaker labels in captions — *no* → Whisper diarization or LLM speaker assignment on transcript; ~2 days.~~ **CLOSED (gap round 2026-10-17):** populated via pause-heuristic speaker turns (≥1.0s gap alternates Speaker 1/2) — honest note, NOT true diarization (Whisper provides none); rendered as tags in the editor transcript.
8. ~~AI-generated opening hook — *no (checkbox stored, never consumed)* → wire one LLM call in detect stage to rewrite clip titles/hooks; ~half day.~~ **CLOSED (gap round 2026-10-17):** `GroqClient.rewrite_hooks()` — one batched LLM call rewrites all clip titles; hook failure never breaks the run (keeps originals).
9. AI B-roll insertion — *no* → needs own stock library or generated visuals; no licensed catalog (skip row) — realistically generated images via the user's media pipeline; ~1 week+.
10. Filler-word and pause removal — *no* → audio analysis + cut list in pipeline; ~3 days.
11. XML export (Premiere/DaVinci) — *no* → serialize clip timeline to FCPXML/EDL; ~1–2 days.
12. Social OAuth connections — *no* → per-platform app approvals (external dependency); phase 2.
13. Three/Four/Screenshare/Gameplay layouts — *no* → extra FFmpeg filter graphs + editor preview; ~3 days.
14. Per-video performance analytics — *partial (in-app stats only)* → depends on social posting existing; phase 2.
15. ~~Brand fonts/colors/logo — *partial (size/emoji/uppercase only)* → form fields + FFmpeg drawtext/fontfile params + logo overlay; ~2 days.~~ **CLOSED (gap round 2026-10-17):** font family (5 fc-list-verified fonts), caption text colour, keyword highlight colour, logo upload (≤2 MB PNG/JPG/WebP, served via auth-checked route, burned top-right into renders); evil inputs sanitized to defaults, no 500s.
16. Schedule posts — *partial (queue only)* → real posting needs platform approvals; phase 2.

**Could-haves (all no):** AI voiceover, series templates, 4K export (1080p now),
team workspace, Zapier, public API, MCP server — all correctly deferred; team/API/MCP
were out of the core-loop slice.

## Behaviour notes

- Double-Generate guarded (no 500, single charge — BUG-01 fixed); SSRF blocked (BUG-03);
  permanent-failure refunds work (BUG-02); malformed JSON → 400 (BUG-04); trim validated (BUG-08).
- One open bug: BUG-07 (S4) — double-click Render enqueues duplicate render jobs
  (wastes CPU, same output). No open S1/S2.
- Browser-based visual checks (M1–M5 in bugs.md) still unperformed — browser unreliable
  in this environment; needs the user's browser.

## Verdict

**Much closer to an OpusClip replacement** — 25 of 26 must-haves are done and
the direct-upload core loop was already fully working end-to-end. Remaining
must-have partial: Google sign-in (**user-dependent**: needs the user's Google
Cloud console setup). Stripe payments are wired end-to-end but INACTIVE until
the user pastes keys (pricing buttons show "not configured yet"; no charge is
ever attempted without keys). Honest nuance: the app is usable for the user's
own clipping today; the only code gap left is auth method.

## Punch list for the next build round (priority order)

1. Google OAuth credentials (must, user-dependent console setup — blocked on the user)
2. Stripe keys + explicit approval to activate payments (user-dependent)
3. AI B-roll insertion via the user's media pipeline (should, ~1 week+)
4. Extra layouts: three/four/screenshare/gameplay (should, ~3 days)

**Next step:** /replica-entrepreneur (review-mining) once parity crosses ~85% (now 81.2).

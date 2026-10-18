# Test plan — ClipForge Studio (replica-test, 2026-10-17)

Target: local FastAPI app at http://127.0.0.1:8901 (uvicorn + worker.py running).
Method: pytest + httpx against the live server (real HTTP). Every case fails on 5xx.
Known v1 gaps (NOT bugs — backend round): Google OAuth, YouTube/Drive/Vimeo URL
download (yt-dlp), completion email, speaker-tracking reframe, social scheduler
stubs, no Stripe, no CSRF tokens (auth hardening is backend-round work).

Test users: throwaway `qa+<ts>@clipforge.studio` accounts, cleaned up after the run.

## F01 — First project end-to-end (signup → dashboard → import → setup → generate)

| case | steps | expect |
|---|---|---|
| F01-H1 | POST /auth/signup (new email, pw 8+) | 303 → /app; dashboard 200 shows 60 credits |
| F01-H2 | POST /auth/login demo creds | 303; GET /app 200 |
| F01-H3 | POST /auth/logout | cookie cleared; GET /app → 303 /login |
| F01-N1 | login wrong password | 200 + "Wrong email or password", no session cookie |
| F01-N2 | signup existing email | 200 + "already registered" |
| F01-N3 | signup password <8 chars | 200 + "at least 8 characters" |
| F01-E1 | GET /app, /app/projects/new, /app/billing with no cookie | 303 → /login (all) |
| F01-E2 | GET /app with tampered cookie sig | 303 → /login |
| F01-E3 | user B GETs user A's /app/projects/{pid}/setup | 404 |
| F01-E4 | signup display_name `<script>alert(1)</script>` | dashboard HTML contains `&lt;script&gt;` (escaped) |
| F01-E5 | project title 200 chars + emoji 🎬 | 303, stored ≤120 chars, no 5xx |
| F01-E6 | POST /app/projects file kind, no file | 200 + "Choose a video file first" |
| F01-E7 | POST /app/projects with notes.txt | 200 + "Unsupported format" |
| F01-E8 | POST /app/projects url kind, `ftp://x` | 200 + "full http(s) URL" |
| F01-E9 | POST /app/projects url kind, `http://127.0.0.1:<port>/` (SSRF probe; listener records hit) | worker must NOT fetch private/loopback URLs (expect: project fails gracefully, listener sees no request) |
| F01-E10 | double POST /app/projects/{pid}/generate | 2nd: no 5xx, no double credit charge |
| F01-E11 | generate with 0 credits | 200 + "Not enough credits" |
| F01-E12 | upload .txt renamed .mp4, generate | no 5xx; project ends `failed` with error text (worker retries → failed) |
| F01-E13 | GET /app/projects/{pid}/status-partial for other user's pid | 404 |

## F02 — Review and refine a clip (gallery → editor → export)

Setup: project + clip + caption segments created directly in DB for user A.

| case | steps | expect |
|---|---|---|
| F02-H1 | PATCH /app/clips/{cid} title/layout/trim | 200 `{"ok": true}`, fields updated, preview re-render enqueued |
| F02-H2 | PATCH /app/captions/{cap} text | 200, text updated, word_timings redistributed |
| F02-N1 | user B PATCH user A's clip | 404 |
| F02-N2 | user B PATCH user A's caption | 404 |
| F02-E1 | trim_end_ms <= trim_start_ms | 400 "End must be after start" |
| F02-E2 | trim_start_ms = -5000 | observe: accepted? render survives? |
| F02-E3 | PATCH with invalid JSON body | 4xx, not 5xx |
| F02-E4 | layout = "bogus" | 200, layout unchanged |
| F02-E5 | POST /app/clips/{cid}/render twice | observe: 1 or 2 render jobs? |
| F02-E6 | GET /app/clips/{cid}/download before render | 404 "not ready yet" |

## F03 — Brand template

| case | steps | expect |
|---|---|---|
| F03-H1 | POST /app/brand-templates (name, 9:16, layouts) | 303; appears in list |
| F03-H2 | POST /app/brand-templates/{tid}/delete own | 303; gone from list |
| F03-N1 | user B POST delete user A's template | 303 but template still present |
| F03-E1 | aspect_ratio = "evil" | expect: 4xx or sanitized — must NOT 5xx |
| F03-E2 | font_size = "abc" | expect: 4xx or default — must NOT 5xx |
| F03-E3 | name with emoji + 200 chars | 303, truncated to 80 |

## F04 — Schedule a clip to social

| case | steps | expect |
|---|---|---|
| F04-H1 | create SocialAccount row (DB), POST /app/clips/{cid}/schedule with datetime + caption | 303 → /app/schedule; row listed |
| F04-N1 | user B schedules user A's clip | 404 |
| F04-E1 | schedule with empty scheduled_at | 303 toast=schedule-error, no row created |

## F05 — Download a finished clip

| case | steps | expect |
|---|---|---|
| F05-H1 | GET /app/clips/{cid}/download (output_path set to real file) | 200 video/mp4, Content-Disposition attachment |
| F05-N1 | user B downloads user A's clip | 404 |
| F05-E1 | GET /app/clips/{cid}/captions.srt with no SRT file | 404 "SRT not ready yet" |
| F05-H2 | SRT exists | 200 text/plain, contains edited caption text |

## F06 — Prompt-directed clipping (ClipAnything)

| case | steps | expect |
|---|---|---|
| F06-H1 | generate with prompt "find pricing advice" | curation_prefs JSON contains prompt |
| F06-E1 | prompt 3000 chars | stored ≤2000 chars |

## Manual / to-check-by-user (needs human eyes, browser unreliable here)

- M1 mobile width (390px): dashboard, editor, gallery usable
- M2 visual polish: score badges, karaoke captions, timeline scrubber
- M3 htmx progress polling on /processing feels live, no stuck states
- M4 toast messages appear on save/delete/schedule actions
- M5 keyboard-only: tab order through editor controls

# Architecture: ClipForge Pro (a clean-room rebuild of OpusClip's core loop)

Working name only — replica-brand will finalize the real name. Scope: web app,
core loop (upload → AI highlight detection + virality score → clip editor →
export). Team workspaces, public API/MCP, mobile apps are out.

> Clean-room note: every schema, route and name below is original. It describes
> functionality observed from public sources; nothing is copied from the original.

## Stack

| layer | choice | why |
| --- | --- | --- |
| web app | FastAPI (Python 3.12) + Jinja2 + htmx | One language for the whole product, no Node build step; the user's ClipForge is already Python, so they can maintain it |
| styling | Tailwind via CDN (v1) | Zero build tooling; design tokens come from replica-design later |
| database | SQLite (single file on the VM) | Zero ops, zero cost, plenty for v1's single-VM scale; moves to Postgres when multi-user |
| ORM | SQLAlchemy 2.0 | Standard FastAPI pairing; models migrate to Postgres without rewrites |
| auth | Local email+password (bcrypt), signed cookie sessions | No external identity provider, no new account; Google OAuth deferred to phase 2 |
| payments | None in v1 — internal credit ledger only | Core loop doesn't need real money; Stripe Checkout deferred to monetization |
| email | Pluggable notifier; v1 default in-app, optional Gmail SMTP | "Email me when done" works via the user's existing Gmail; no paid provider |
| jobs | DB-backed `render_jobs` table + dedicated Python worker process | No Redis to run; atomic claim (`UPDATE … WHERE status='queued'`) is safe on SQLite |
| files | Local disk: `uploads/`, `renders/`, `media/` | Simplest thing that works; object storage (R2/S3) deferred |
| AI | Groq: Whisper (transcription) + `openai/gpt-oss-120b` (highlight detect, virality rubric, hook gen) | Free tier, key already in hand; no paid API anywhere in v1 |
| video | FFmpeg + ffprobe | Cut, scale/crop reframe, ASS caption burn-in, thumbnails — all local, all free |
| hosting | This Linux VM (systemd service) | Already available; Fly/Render when it needs to scale |

One database. No microservices. The clone needs the original's features, not its architecture.

## Schema

Tables: 9. Full SQL: `replica/schema.sql` (SQLite dialect; Postgres later).
Access rules: **data-layer checks** — every query is scoped by the request's
`user_id`; there is no shared/global read path. RLS is a Postgres feature and
SQLite is the v1 database, so authorization lives in one place: the repository
functions, each taking `user_id` as its first argument.

Conventions: ids are TEXT uuid4 (generated in Python, portable to Postgres);
times are TEXT ISO-8601 UTC; money is INTEGER cents + currency column; JSON
columns are TEXT holding JSON; booleans are INTEGER 0/1.

| table | owns what | key decisions |
| --- | --- | --- |
| `users` | account, plan, credit balance | `plan_tier` CHECK (free/starter/pro); `credits_balance` INTEGER minutes, cached — the ledger is the audit source |
| `brand_templates` | reusable visual identity | `aspect_ratio` CHECK; `enabled_layouts` + `caption_style` as JSON; `logo_path` local file |
| `projects` | one source video + its curation prefs | `status` CHECK (uploading/processing/ready/failed); `credits_charged`; template FK is SET NULL on delete |
| `clips` | one scored highlight | `virality_score` 0–100 CHECK; `score_breakdown` JSON {hook,flow,value}; trim range CHECK; own id format (uuid, not the original's composite) |
| `caption_segments` | word-timed captions per clip | `end_ms > start_ms` CHECK; `word_timings` JSON for karaoke style |
| `render_jobs` | async pipeline queue (NEW vs recon) | `status` CHECK; atomic claim via `worker_id`; `attempts`/`max_attempts` + `next_retry_at` for recovery |
| `social_accounts` | publishing destinations | UNIQUE(user_id, platform); tokens Fernet-encrypted, never plaintext |
| `scheduled_posts` | queued posts | polled by `(status, scheduled_at)` index; UNIQUE(clip_id, social_account_id, scheduled_at) |
| `credit_ledger` | every credit movement | `reason` CHECK (grant/purchase/processing/x_post/refund/expiry); balance derived = SUM(delta), cached on users |

Hard constraints enforced in the database, not the UI:
- **One active generation per project** — partial unique index on `render_jobs(project_id)` WHERE job_type IN ('fetch','transcribe','detect','preview') AND status IN ('queued','running'). Double-clicking Generate can't fork the pipeline.
- **No credit overspend** — spend happens inside one transaction: read balance → insert ledger row → update cached balance. SQLite serializes writers, so this is race-safe.
- **No double scheduling** — UNIQUE(clip_id, social_account_id, scheduled_at).

## API

Base: `/api/v1`. Auth: session cookie; every route below (except the three
marked public) requires a logged-in user and is scoped to their `user_id`.

| method path | does | who | input | output | flow |
| --- | --- | --- | --- | --- | --- |
| POST /api/v1/auth/signup | create account, grant free credits | public | {email, password, display_name} | {user} | F01 |
| POST /api/v1/auth/login | start session | public | {email, password} | {user} | F01 |
| POST /api/v1/auth/logout | end session | user | — | {} | — |
| GET /api/v1/projects | list projects + credit balance | user | ?status | {projects[], credits_balance} | F01 (S04) |
| POST /api/v1/projects | create project, start import | user | multipart file OR {source_type, source_url} | {project} | F01 (S05) |
| GET /api/v1/projects/{id} | project detail + its clips | user | — | {project, clips[]} | F01 (S08) |
| POST /api/v1/projects/{id}/generate | save curation prefs, charge credits, enqueue pipeline | user | {clip_length_min, clip_length_max, genre, language, keywords[], prompt, brand_template_id, ai_hook} | {run_id} | F01/F06 (S06→S07) |
| GET /api/v1/projects/{id}/status | pipeline progress (htmx-polled) | user | — | {status, progress_pct, stage, eta} | F01 (S07) |
| GET /api/v1/projects/{id}/clips | gallery, sort/filter | user | ?sort=virality&min_score=&q= | {clips[]} | F02 (S08) |
| GET /api/v1/clips/{id} | clip detail + caption segments | user | — | {clip, captions[]} | F02 (S09) |
| PATCH /api/v1/clips/{id} | retitle, change layout, trim | user | {title?, layout?, trim_start_ms?, trim_end_ms?, render_prefs?} | {clip} | F02 (S09) |
| PATCH /api/v1/captions/{id} | fix caption text inline | user | {text} | {caption} | F02 (S09) |
| POST /api/v1/clips/{id}/render | enqueue final 1080p render | user | {brand_template_id?} | {render_job} | F02/F05 (S09→S13) |
| GET /api/v1/clips/{id}/download | download finished MP4 | user | — | file | F05 (S13) |
| GET /api/v1/clips/{id}/captions.srt | download SRT | user | — | file | F05 (S13) |
| GET /api/v1/brand-templates | list templates | user | — | {templates[]} | F03 (S10) |
| POST /api/v1/brand-templates | create template | user | {name, aspect_ratio, layouts[], caption_style, watermark} | {template} | F03 |
| PATCH /api/v1/brand-templates/{id} | update template | user | partial | {template} | F03 |
| DELETE /api/v1/brand-templates/{id} | delete template | user | — | {} | F03 |
| POST /api/v1/brand-templates/{id}/logo | upload logo image | user | multipart | {logo_path} | F03 |
| GET /api/v1/social-accounts | list connected accounts | user | — | {accounts[]} | F04 (S11, phase 2) |
| POST /api/v1/social-accounts | begin OAuth connect | user | {platform} | {auth_url} | F04 (phase 2) |
| DELETE /api/v1/social-accounts/{id} | disconnect | user | — | {} | F04 |
| POST /api/v1/clips/{id}/schedule | queue a post | user | {social_account_id, scheduled_at, caption_text} | {scheduled_post} | F04 (S12, queue only in v1) |
| GET /api/v1/scheduled-posts | list queued/sent posts | user | ?status | {posts[]} | F04 |
| GET /api/v1/billing | balance + ledger history | user | — | {credits_balance, ledger[]} | (S14) |
| POST /api/v1/users/me/timezone | set timezone for scheduling | user | {timezone} | {user} | F04 |

27 routes. Webhooks in: none in v1 (no Stripe). Webhooks out: none.
Jobs: `pipeline-worker` (fetch→transcribe→detect→preview, polls `render_jobs`),
`render-worker` (final 1080p + SRT, same queue, GPU/CPU-heavy — one at a time on
the VM), `scheduler-worker` (phase 2: due `scheduled_posts`), `cleanup-worker`
(hourly: delete expired exports, purge old jobs/files), `credit-expiry-worker`
(daily: expire old ledger grants).

## Async render pipeline

The pipeline is a chain of `render_jobs` rows, one per stage, claimed
atomically by workers (`UPDATE render_jobs SET status='running', worker_id=?
WHERE id=? AND status='queued'`). No Redis, no broker — the database is the
queue, which is one less thing to operate on a single VM.

- **Stages per generation run:** `fetch` (download/verify source via yt-dlp for
  user-supplied URLs, ffprobe validation) → `transcribe` (Groq Whisper →
  word-timed segments → `caption_segments` rows) → `detect` (Groq LLM over the
  transcript: highlight windows, titles, hook/flow/value scores → `clips` rows)
  → `preview` (FFmpeg: cut + 9:16 reframe + ASS caption burn-in → preview MP4s)
  → `render` (on demand: final 1080p with brand template → output MP4 + SRT).
- **Progress:** the worker updates `stage` + `progress_pct` on the job row;
  the frontend polls `GET /projects/{id}/status` (htmx swap on the progress
  bar). ETA = elapsed × (100 − pct)/pct, smoothed.
- **Failure recovery:** `attempts` increments per try, `max_attempts=3`,
  `next_retry_at` with exponential backoff; terminal failure → `failed` +
  `error_message`, user sees a toast and the project goes `failed` with a
  Retry button. Retries are safe: every stage writes to deterministic paths
  (`renders/{clip_id}/preview.mp4`), so re-running overwrites instead of
  duplicating. Credits are charged once at generate time; a fully failed run
  writes a `refund` row to the ledger.
- **Backpressure:** one render worker on the VM (FFmpeg saturates CPU);
  transcode and caption burn-in never run concurrently on the same box in v1.

## The parts that bite

- **Time zones:** everything stored UTC; `users.timezone` drives the scheduler.
  DST edge: a post scheduled in a skipped hour fires at the next valid minute.
- **Idempotency:** Groq calls cost rate-limit budget — each stage first checks
  "output already exists?" before calling out, so a retried job never
  re-transcribes for free.
- **Races:** the partial unique index kills double-Generate; job claiming is a
  single atomic UPDATE; credit spend is one transaction.
- **Rate limits:** Groq free tier 429s → stage sleeps with backoff, job shows
  "AI busy, retrying" instead of failing.
- **File limits:** 10 GB upload cap (app-level check + streaming to disk, never
  into memory); v1 caps source duration at 3 h to bound Whisper/FFmpeg time.
- **FFmpeg failures:** ffprobe first — no audio stream or corrupt container
  fails fast with a human message, not a hung worker.
- **Reframing quality:** v1 uses center-weighted crop with face-bias heuristic;
  true active-speaker detection across 7 layouts is the known hard part —
  Fill/Fit/Split ship first, the rest are should-haves.
- **GDPR deletion:** account delete cascades every FK and a cleanup job wipes
  the user's files from disk.
- **Secrets:** Groq key from env only, never in the DB; OAuth tokens
  Fernet-encrypted at rest.

## Build order

1. **Vertical slice (week 1):** signup → upload a file → transcribe → one scored
   clip with burned-in captions → download MP4. Screens: S03, S04, S05, S08
   (minimal), S13. Tables: users, projects, clips, caption_segments,
   render_jobs. Routes: auth ×3, projects ×5, clips gallery/detail/download.
   Proves the stack and the Groq+FFmpeg core.
2. **Must-haves by area:** YouTube URL import; curation prefs (length, genre,
   language, keywords, prompt/F06); scoring + hook/flow/value UI; gallery
   sort/filter; editor (preview, transcript click-to-edit, caption fix, trim,
   layout); Fill/Fit/Split reframe; brand templates (aspect + caption style);
   SRT export; progress + completion notify; credit ledger + plan caps.
3. **Should-haves:** remaining 4 layouts; full brand kit (fonts/colors/logo);
   AI hook generator; filler-word removal; speaker labels; social OAuth +
   scheduler (queue → post); per-video analytics; XML export.
4. **Fixes from replica-entrepreneur** once it has run (real user complaints
   become the priority list).

## What v1 deliberately leaves out

Team workspaces and multi-user orgs; public API/MCP; mobile apps; actual
social-network posting (tables and queue ship, posting workers are phase 2);
real payments (credits are internal ledger only); AI B-roll; 4K export;
analytics dashboard; paid email provider. The schema already carries the
tables for phase 2, so none of this needs a migration later — only workers
and routes.

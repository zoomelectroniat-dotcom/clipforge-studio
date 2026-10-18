# Recon map: OpusClip (web app)

Scope: Core loop ONLY — video upload/import → AI highlight detection + virality scoring → clip editor (auto captions, vertical reframing, basic edits) → export/download. Excludes team workspaces, public API/MCP, mobile apps, AI Producer agent, and affiliate program.
For: The user's own clipper product (upgrade path from their free ClipForge tool).
Date: 2026-10-17

> Clean-room note: this document describes functionality and UX patterns observed from public sources. It contains no copied code, branding, logos, marketing copy, or content from the original.

## Sources

| # | source | URL | notes |
| --- | --- | --- | --- |
| 1 | help center — layout & reframing | https://help.opus.pro/docs/article/layout-and-reframing | 7 clip layouts documented (Fill, Fit, Split, Three, Four, Screenshare, Gameplay) |
| 2 | help center — brand templates | https://help.opus.pro/docs/article/how-to-add-a-brand-template | aspect ratios, auto layout, caption render prefs, template limits per plan |
| 3 | help center — first-run setup | https://help.opus.pro/docs/article/things-you-should-set-up-first | sidebar nav structure, social accounts, team workspace creation |
| 4 | help center — create project (API ref) | https://help.opus.pro/api-reference/endpoints/create-project | import sources list, curation/render/import prefs, conclusion actions |
| 5 | help center — clip representation (schema) | https://help.opus.pro/api-reference/schemas/clip-representation | clip id format, fields (title, text, durationMs, virality data, renderPref) |
| 6 | pricing analyses (Sep–Oct 2026) | https://aialleyway.com/opusclip-pricing/ | credit model verified from signed-in account: 1 credit = 1 min source |
| 7 | pricing analyses | https://www.castmagic.io/blog/opus-clip-pricing | plan limits: storage expiry, upload caps, watermark rules |
| 8 | independent workflow test | https://bigvu.tv/blog/opus-clip-tested-2026-where-ai-wins-40-percent-discard/ | Starter vs Pro gating: editor/B-roll/scheduler are Pro-only |
| 9 | workflow walkthrough | https://imperialaitools.com/how-to-use-opus-clip/ | clipping modes (AI-selected, keyword, timeframe, ClipAnything prompt) |
| 10 | marketing — podcaster page | https://www.opus.pro/de-de/business/podcaster | feature list: AI clipping, captioning, B-roll, voiceover, analytics, audio cleaning, reframe |
| 11 | editor deep-dive | https://www.anygen.io/showcase/opus-clip-com/index.html | text-based editing, brand kits, XML export, curation model tiers |

## Core loop

Upload or link a long video → the system analyzes it, picks highlight moments, scores each for virality → user reviews scored clips, refines captions/layout in an editor → exports vertical shorts or schedules them to social platforms.

## Screens

| ID | screen | route / how to reach | purpose | key components | states seen |
| --- | --- | --- | | --- | --- |
| S01 | Marketing homepage | opus.pro (public) | positioning, signup CTA | hero, feature grid, FAQ, CTA buttons | desktop, mobile |
| S02 | Pricing page | opus.pro/pricing (public) | plan comparison, credit explainer | pricing cards, feature matrix, FAQ | filled |
| S03 | Sign in / Sign up | auth entry (public) | Google or email auth | provider buttons, email form | filled, error |
| S04 | Dashboard home | app home after login | project list, credit balance, nav | left sidebar, project cards, credits badge | empty (no projects), filled, loading |
| S05 | New project / import | "New project" from S04 | get the source video in | file dropzone, URL input, source picker (YouTube, Drive, Vimeo, Zoom, Dropbox, Twitch, Rumble, Loom, Riverside, StreamYard, Frame.io, Facebook, LinkedIn, X, S3 MP4, Apple Podcast) | filled, uploading progress, error (unsupported source) |
| S06 | Project setup (curation prefs) | after import, before processing | configure what the AI should do | clip-length range, genre select (podcast/vlog/sports/talking-head/presentation), language select, keyword input, brand-template picker, AI-hook toggle, ClipAnything natural-language prompt box, Generate button | filled |
| S07 | Processing | auto after Generate | show render progress | progress bar, ETA text, "email me when done" note | loading, failed, done |
| S08 | Clips gallery | project detail | review scored clips | clip cards (thumbnail, title, duration, virality score 0–100, hook/flow/value breakdown), sort/filter | loading, filled, empty (no clips found), error |
| S09 | Clip editor | "Edit clip" from S08 | refine one clip | video preview, timeline with segments, transcript panel (click-text-to-edit), caption text blocks (inline edit), layout dropdown, B-roll controls, trim handles, AI-hook toggle | filled, loading |
| S10 | Brand templates | sidebar → Brand Template | reusable visual identity | template list, aspect-ratio select (9:16, 1:1, 16:9, 4:5), layout multi-select (7 layouts), caption style (font family/color/stroke/shadow, highlight colors, uppercase, emoji), logo upload, watermark toggle, Save | filled, empty |
| S11 | Social accounts | sidebar → Social Accounts | connect publishing destinations | connected-accounts list, Add Account button, per-platform OAuth popup | empty, filled, error (token expired — TikTok noted to drop) |
| S12 | Scheduler | from S08 per clip | plan posts | datetime picker, per-platform toggles, caption text field, queue list | filled, empty |
| S13 | Export | from S08/S09 | get the file out | MP4 1080p download, SRT captions download, XML export (Premiere/DaVinci) | filled, processing |
| S14 | Billing & credits | profile/billing | plan, balance, expiry | credit balance, expiry dates, plan card, upgrade CTA | filled |
| S15 | Analytics | dashboard section | performance insights | per-video stat cards, charts | filled, empty |

## Flows

```
F01 First project end-to-end (new user)
    S03 signup -> S04 dashboard -> S05 import -> S06 configure -> S07 processing -> S08 gallery
    happy path clicks: ~8 (provider, new project, paste URL, set length, set genre, pick template, generate, open first clip)
    edge: unsupported source URL, upload larger than plan cap (10 GB free/starter, 30 GB pro), processing failure (email notify), zero clips found
```

```
F02 Review and refine a clip
    S08 gallery -> S09 editor (fix caption text inline, trim slow intro, change layout) -> S13 export
    happy path clicks: ~7 (open clip, 2 caption fixes, trim drag, layout change, save, export)
    edge: caption mistranscription on accented/overlapping speech, reframing cuts speaker in multi-person scene
```

```
F03 Set up a brand template
    S04 -> S10 (choose aspect ratio, tick layouts, set font/colors, upload logo) -> Save template
    happy path clicks: ~8
    edge: plan limit reached (1 template on free/starter, 2 on pro)
```

```
F04 Schedule a clip to social
    S08 -> S12 (pick date/time, toggle platforms, write caption) -> confirm
    happy path clicks: ~5 (requires S11 connected; each X post costs 1 credit)
    edge: TikTok token expired mid-flow, failed post auto-refund
```

```
F05 Download a finished clip
    S08 -> S13 download MP4
    happy path clicks: ~2
    edge: free plan export expires 3 days after render; watermark on free
```

```
F06 Prompt-directed clipping (ClipAnything)
    S06 prompt box ("find moments where the speaker gives pricing advice") -> Generate
    happy path clicks: ~2
    edge: prompt too vague returns generic clips
```

## Components

| component | variants | states | used on |
| --- | --- | --- | --- |
| Button | primary, secondary, ghost, danger | default, hover, focus, disabled, loading | all |
| Text input | single-line, textarea, search | default, focus, error, disabled | S05, S06, S09, S12 |
| Dropdown / select | single, multi | open, closed, disabled | S06, S09, S10, S12 |
| Toggle switch | on/off | on, off, disabled | S06, S10 |
| Slider | range | default, dragging | S06 (clip length) |
| Modal / dialog | confirm, form | open, closed | S11 (OAuth), S13 |
| Toast notification | success, error, info | visible, dismissed | all |
| Left sidebar nav | icons + labels | active, inactive, collapsed | S04–S15 |
| Card | project, clip, stat | default, hover, selected | S04, S08, S15 |
| Score badge | virality 0–100 | color-coded tiers | S08 |
| Tabs | — | active, inactive | S09, S10 |
| Video timeline | segments, playhead | playing, paused, scrubbing | S09 |
| Transcript panel | rows per utterance | default, selected, edited | S09 |
| Caption text block | word-level | default, editing, highlighted keyword | S09 |
| Progress bar | determinate | 0–100%, failed | S05, S07, S13 |
| File dropzone | — | idle, dragover, uploading, error | S05 |
| Date/time picker | — | open, closed | S12 |
| Avatar / profile menu | — | open, closed | S04 (billing, team, logout) |
| Tooltip | — | hover | S08 (score explanation) |

## Inferred data model

```
User  id, email, auth_provider (google | email), plan_tier (free | starter | pro | business),
      credits_balance, created_at
      evidence: S03 auth options; S14 credit balance/expiry; pricing tiers
      confidence: high

BrandTemplate  id, user_id, name, aspect_ratio (9:16 | 1:1 | 16:9 | 4:5),
      enabled_layouts[] (fill | fit | split | three | four | screenshare | gameplay),
      caption { font_family, font_color, stroke, shadow, uppercase, emoji, highlight_colors },
      logo_url, watermark_enabled, is_default
      evidence: S10 settings; clip schema renderPref fields (enableCaption, enableHighlight, enableEmoji, font{}, highlightColor{})
      confidence: high

Project  id, user_id, source_type (upload | youtube | drive | zoom | ...), source_url,
      duration_min, language, genre, status (uploading | processing | ready | failed),
      credits_charged, brand_template_id, created_at
      evidence: S05 source picker; S06 prefs; S07 statuses; credit model (1 credit = 1 min source)
      confidence: high

Clip  id ({project_id}.{curation_id}), project_id, run_id, title, description,
      transcript_text, duration_ms, virality_score (0-100),
      score_breakdown { hook, flow, value }, render_pref (json), preview_uri,
      storage_used_bytes, created_at
      evidence: S08 cards; clip-representation schema (id format, durationMs, title, text, renderPref)
      confidence: high

CaptionSegment  id, clip_id, start_ms, end_ms, text, speaker_label, is_keyword
      evidence: S09 caption text blocks; keyword highlighting; SRT export
      confidence: medium (segments implied by editor + SRT; exact storage is a guess)

SocialAccount  id, user_id, platform (tiktok | youtube | instagram | facebook | linkedin | x),
      oauth_status (connected | expired), connected_at
      evidence: S11 connect flow; TikTok re-auth reports
      confidence: medium

ScheduledPost  id, clip_id, social_account_id, scheduled_at, caption_text,
      status (queued | posted | failed), credit_charged
      evidence: S12 scheduler; "1 credit per X post, auto-refund on failure"
      confidence: medium

CreditLedger  id, user_id, delta, reason (processing | x_post | purchase | expiry),
      expires_at, created_at
      evidence: credit expiry rules (monthly 60 days, annual 12–13 months); per-minute billing
      confidence: medium (ledger shape is a guess; the rules are documented)
```

Relationships: User 1-n BrandTemplate, User 1-n Project, Project 1-n Clip, Clip 1-n CaptionSegment, User 1-n SocialAccount, Clip 1-n ScheduledPost, SocialAccount 1-n ScheduledPost, User 1-n CreditLedger.

## Feature matrix

See `features.csv`. Must: 26, should: 12, could: 7, skip: 5.

## Out of scope (cannot or should not be cloned)

- Virality training data — the scoring model is trained on millions of viral videos; that dataset is their proprietary asset. A clone must use its own scoring heuristic (e.g. LLM-based hook/flow/value rubric).
- Stock / AI B-roll libraries — licensed footage catalogs cannot be copied; a clone needs its own stock source or generated visuals.
- Social-platform posting partnerships — TikTok/Instagram/YouTube publishing integrations depend on each platform's API approval and quotas; not guaranteed for a new app.
- Proprietary model weights (ClipAnything, curation models) — behavior can be reimplemented, weights cannot be taken.
- Brand assets, name, logo, marketing copy, and UI artwork — identity is theirs; the clone gets its own (replica-brand step).

## Size

Screens 15, flows 6, entities 8. Hard parts: (1) virality scoring that users trust — needs either training data or a well-tuned LLM rubric over hook/flow/value signals; (2) active-speaker detection + smart reframing across 7 layouts (computer vision, multi-speaker scenes); (3) async render pipeline at scale — transcode, caption burn-in, and 1080p export queue with progress and failure recovery. Size: L (a quarter for full parity; an M-sized v1 is feasible on the user's existing free stack: Groq Whisper + LLM for transcription/scoring, FFmpeg for cut/reframe/caption burn-in).

-- ClipForge Pro v1 schema (SQLite). Clean-room: original design, no copied structures.
-- Conventions: ids TEXT uuid4 (Python-generated, Postgres-portable); times TEXT ISO-8601 UTC;
-- money INTEGER cents + currency; JSON columns TEXT holding JSON; booleans INTEGER 0/1.

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------- users
CREATE TABLE users (
  id             TEXT PRIMARY KEY,
  email          TEXT NOT NULL UNIQUE,
  password_hash  TEXT NOT NULL,
  display_name   TEXT NOT NULL,
  plan_tier      TEXT NOT NULL DEFAULT 'free'
                   CHECK (plan_tier IN ('free','starter','pro')),
  credits_balance INTEGER NOT NULL DEFAULT 0,          -- minutes; cached, ledger is audit source
  timezone       TEXT NOT NULL DEFAULT 'UTC',
  created_at     TEXT NOT NULL,
  updated_at     TEXT NOT NULL
);

-- ------------------------------------------------------ brand_templates
CREATE TABLE brand_templates (
  id                TEXT PRIMARY KEY,
  user_id           TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name              TEXT NOT NULL,
  aspect_ratio      TEXT NOT NULL CHECK (aspect_ratio IN ('9:16','1:1','16:9','4:5')),
  enabled_layouts   TEXT NOT NULL DEFAULT '["fill"]',  -- JSON array
  caption_style     TEXT NOT NULL DEFAULT '{}',         -- JSON: font_family, font_color, stroke, shadow, uppercase, emoji, highlight colors
  logo_path         TEXT,                              -- local file, nullable
  watermark_enabled INTEGER NOT NULL DEFAULT 0,
  is_default        INTEGER NOT NULL DEFAULT 0,
  created_at        TEXT NOT NULL,
  updated_at        TEXT NOT NULL
);
CREATE INDEX idx_brand_templates_user ON brand_templates(user_id);

-- -------------------------------------------------------------- projects
CREATE TABLE projects (
  id               TEXT PRIMARY KEY,
  user_id          TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title            TEXT NOT NULL,
  source_type      TEXT NOT NULL CHECK (source_type IN
                     ('upload','youtube','drive','dropbox','zoom','loom','twitch',
                      'rumble','vimeo','streamyard','s3','mp4','podcast')),
  source_url       TEXT,
  local_media_path TEXT,
  duration_sec     INTEGER,
  language         TEXT NOT NULL DEFAULT 'en',
  genre            TEXT CHECK (genre IN ('podcast','vlog','sports','talking-head','presentation')),
  status           TEXT NOT NULL DEFAULT 'uploading'
                     CHECK (status IN ('uploading','processing','ready','failed')),
  credits_charged  INTEGER NOT NULL DEFAULT 0,
  brand_template_id TEXT REFERENCES brand_templates(id) ON DELETE SET NULL,
  error_message    TEXT,
  created_at       TEXT NOT NULL,
  updated_at       TEXT NOT NULL
);
CREATE INDEX idx_projects_user ON projects(user_id);
CREATE INDEX idx_projects_status ON projects(status);
CREATE INDEX idx_projects_user_created ON projects(user_id, created_at DESC);

-- ----------------------------------------------------------------- clips
CREATE TABLE clips (
  id              TEXT PRIMARY KEY,                    -- uuid; our own format
  project_id      TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  run_id          TEXT NOT NULL,                       -- groups one Generate run
  title           TEXT NOT NULL,
  description     TEXT NOT NULL DEFAULT '',
  transcript_text TEXT NOT NULL DEFAULT '',
  duration_ms     INTEGER NOT NULL CHECK (duration_ms > 0),
  virality_score  INTEGER CHECK (virality_score BETWEEN 0 AND 100),
  score_breakdown TEXT NOT NULL DEFAULT '{}',          -- JSON: {hook, flow, value}
  render_prefs    TEXT NOT NULL DEFAULT '{}',          -- JSON: caption/layout overrides
  layout          TEXT NOT NULL DEFAULT 'fill'
                    CHECK (layout IN ('fill','fit','split','three','four','screenshare','gameplay')),
  trim_start_ms   INTEGER NOT NULL DEFAULT 0,
  trim_end_ms     INTEGER,                             -- NULL = to end
  preview_path    TEXT,
  output_path     TEXT,
  thumbnail_path  TEXT,
  status          TEXT NOT NULL DEFAULT 'draft'
                    CHECK (status IN ('draft','rendering','ready','failed')),
  created_at      TEXT NOT NULL,
  updated_at      TEXT NOT NULL,
  CONSTRAINT trim_sane CHECK (trim_end_ms IS NULL OR trim_end_ms > trim_start_ms)
);
CREATE INDEX idx_clips_project ON clips(project_id);
CREATE INDEX idx_clips_project_score ON clips(project_id, virality_score DESC);
CREATE INDEX idx_clips_run ON clips(run_id);

-- ------------------------------------------------------ caption_segments
CREATE TABLE caption_segments (
  id           TEXT PRIMARY KEY,
  clip_id      TEXT NOT NULL REFERENCES clips(id) ON DELETE CASCADE,
  start_ms     INTEGER NOT NULL,
  end_ms       INTEGER NOT NULL,
  text         TEXT NOT NULL,
  speaker_label TEXT,
  is_keyword   INTEGER NOT NULL DEFAULT 0,
  word_timings TEXT NOT NULL DEFAULT '[]',             -- JSON: karaoke word times
  created_at   TEXT NOT NULL,
  CONSTRAINT segment_sane CHECK (end_ms > start_ms)
);
CREATE INDEX idx_captions_clip ON caption_segments(clip_id);
CREATE INDEX idx_captions_clip_start ON caption_segments(clip_id, start_ms);

-- ------------------------------------------------------------ render_jobs
-- The async pipeline queue. Workers claim rows atomically; no Redis in v1.
CREATE TABLE render_jobs (
  id           TEXT PRIMARY KEY,
  project_id   TEXT REFERENCES projects(id) ON DELETE CASCADE,
  clip_id      TEXT REFERENCES clips(id) ON DELETE CASCADE,
  job_type     TEXT NOT NULL CHECK (job_type IN
                 ('fetch','transcribe','detect','preview','render','export_srt','thumbnail')),
  status       TEXT NOT NULL DEFAULT 'queued'
                 CHECK (status IN ('queued','running','done','failed','cancelled')),
  stage        TEXT,                                   -- human-readable current stage
  progress_pct INTEGER NOT NULL DEFAULT 0 CHECK (progress_pct BETWEEN 0 AND 100),
  attempts     INTEGER NOT NULL DEFAULT 0,
  max_attempts INTEGER NOT NULL DEFAULT 3,
  next_retry_at TEXT,
  worker_id    TEXT,
  started_at   TEXT,
  finished_at  TEXT,
  error_message TEXT,
  result_path  TEXT,
  created_at   TEXT NOT NULL,
  updated_at   TEXT NOT NULL
);
CREATE INDEX idx_jobs_poll ON render_jobs(status, created_at);   -- worker pickup
CREATE INDEX idx_jobs_clip ON render_jobs(clip_id);
CREATE INDEX idx_jobs_project ON render_jobs(project_id);
-- One active generation pipeline per project: double-Generate can't fork it.
CREATE UNIQUE INDEX uq_active_generation ON render_jobs(project_id)
  WHERE job_type IN ('fetch','transcribe','detect','preview')
    AND status IN ('queued','running');

-- -------------------------------------------------------- social_accounts
CREATE TABLE social_accounts (
  id                   TEXT PRIMARY KEY,
  user_id              TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  platform             TEXT NOT NULL CHECK (platform IN
                         ('tiktok','youtube','instagram','facebook','linkedin','x','google_drive')),
  oauth_status         TEXT NOT NULL DEFAULT 'expired'
                         CHECK (oauth_status IN ('connected','expired')),
  access_token_enc     TEXT,                            -- Fernet-encrypted, never plaintext
  refresh_token_enc    TEXT,
  token_expires_at     TEXT,
  platform_account_name TEXT,
  connected_at         TEXT,
  created_at           TEXT NOT NULL,
  updated_at           TEXT NOT NULL,
  UNIQUE (user_id, platform)
);
CREATE INDEX idx_social_user ON social_accounts(user_id);

-- -------------------------------------------------------- scheduled_posts
CREATE TABLE scheduled_posts (
  id               TEXT PRIMARY KEY,
  clip_id          TEXT NOT NULL REFERENCES clips(id) ON DELETE CASCADE,
  social_account_id TEXT NOT NULL REFERENCES social_accounts(id) ON DELETE CASCADE,
  scheduled_at     TEXT NOT NULL,                       -- UTC ISO-8601
  caption_text     TEXT NOT NULL DEFAULT '',
  status           TEXT NOT NULL DEFAULT 'queued'
                     CHECK (status IN ('queued','posted','failed','cancelled')),
  credit_charged   INTEGER NOT NULL DEFAULT 0,
  posted_url       TEXT,
  error_message    TEXT,
  created_at       TEXT NOT NULL,
  updated_at       TEXT NOT NULL,
  UNIQUE (clip_id, social_account_id, scheduled_at)     -- no double scheduling
);
CREATE INDEX idx_sched_poll ON scheduled_posts(status, scheduled_at);  -- scheduler pickup
CREATE INDEX idx_sched_clip ON scheduled_posts(clip_id);

-- ---------------------------------------------------------- credit_ledger
-- Audit source for credits. users.credits_balance is a cache: balance = SUM(delta).
CREATE TABLE credit_ledger (
  id         TEXT PRIMARY KEY,
  user_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  delta      INTEGER NOT NULL,                          -- +grant/purchase/refund, -spend
  reason     TEXT NOT NULL CHECK (reason IN
               ('grant','purchase','processing','x_post','refund','expiry')),
  expires_at TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX idx_ledger_user_created ON credit_ledger(user_id, created_at DESC);

-- -------------------------------------------------------- webhook_events
-- Processed Stripe webhook event ids (evt_...) — retries never double-grant.
CREATE TABLE webhook_events (
  id         TEXT PRIMARY KEY,
  created_at TEXT NOT NULL
);

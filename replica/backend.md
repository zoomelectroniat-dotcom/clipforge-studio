# backend.md — ClipForge Studio (replica-backend gap round, 2026-10-17)

Scope of this round: close the backend-feasible gaps from diff-report.md.
Google OAuth and Stripe were NOT attempted (user-dependent — documented below).

## What was built

- **yt-dlp import** (`pipeline._fetch_remote`): yt-dlp 2026.08.19 in requirements;
  `noplaylist` guard; friendly errors for private/deleted/login-walled/unsupported
  URLs; permanent failures surface on the project with Retry + credit refund.
- **Completion email** (`app/mailer.py`): clips-ready / render-ready / failure
  emails sent from the worker's `_finish` (after DB commit; mailer never raises).
  Config via `SMTP_HOST/PORT/USER/PASS/FROM` + `APP_URL`; safe no-op when unset.
  All vars documented in `../.env.example` (no values).
- **AI opening hook** (`groq_client.rewrite_hooks` + `pipeline.stage_detect`):
  one batched LLM call rewrites clip titles when the setup `ai_hook` checkbox
  is on; failure keeps original titles, never breaks the run.
- **Speaker labels** (`pipeline._assign_speakers`): pause-heuristic turns
  (≥1.0s gap alternates Speaker 1/2) stored on `caption_segments.speaker_label`
  and shown as tags in the editor. Honest: NOT true diarization (Whisper has none).
- **Brand kit** (`main.brand_create`, `video.make_ass`, `video.render_clip`):
  font family (5 verified fonts), caption/keyword colours, logo upload
  (≤2 MB, auth-checked serve route, burned top-right into renders).
- **Timeline trim** (`templates/editor.html` + CSS): dual-handle scrubber synced
  with the time inputs; server-side trim validation unchanged (BUG-08).

## Integrations (official APIs only)

| integration | status | notes |
|---|---|---|
| Groq Whisper + LLM | live, user's own key | key from `GROQ_API_KEY` env or `~/workspace/clipforge-server/.groq_key`; never logged |
| yt-dlp (YouTube/Vimeo/…) | live | official yt-dlp package; SSRF guard (`_assert_public_url`) still blocks private hosts |
| SMTP email | optional | user's own SMTP; no-op when unconfigured |
| Google OAuth | **pending — user** | needs user's Google Cloud console: OAuth client ID/secret + authorized redirect |
| Stripe payments | **pending — user** | needs user's Stripe keys + explicit approval; test mode first per skill |

## Security checklist

- [x] secrets only in env vars (SMTP_*, GROQ_API_KEY, APP_URL); `.env.example` has names only, no values
- [x] input validated on the server on every new route (brand colors/fonts/logo: allowlist + regex + size/type checks; trim still validated — BUG-08)
- [x] authorisation checked on every read/write (logo serve route checks template ownership; e2e IDOR tests pass)
- [x] rate limits: email sends only on job completion/failure (no user-triggered bulk send); auth routes unchanged
- [x] uploads: logo ≤2 MB, extension allowlist (png/jpg/jpeg/webp), stored outside web root under `data/logos/` with 0600 perms, served via auth-checked route
- [x] no user data in URLs or logs (mailer logs only recipient + subject)
- [x] no new npm deps (Python: yt-dlp added to requirements.txt)
- [x] mailer never raises — email cannot break the render pipeline
- [ ] Google OAuth / Stripe: not started (user-dependent)

## Verification

- e2e suite: **47/47 pass** (43 existing + 4 new: brand colors/fonts stored,
  evil brand inputs sanitized, mailer no-op, ai_hook + speaker labels via
  stage_detect in stub mode).
- Live HTTP checks: brand create with logo upload (303), logo serve (200),
  editor renders timeline widget + speaker tags, logo-overlay FFmpeg render OK.
- Sandbox caveat: sandbox DNS sinkholes all hosts to 198.18.x.x, so the SSRF
  guard blocks yt-dlp downloads here; real-world DNS will pass public hosts.
  yt-dlp error mapping was verified with the guard bypassed in a test script.

Next: /replica-test hardening pass, then /replica-entrepreneur after ~85% parity.

## Credential setup (2026-10-18) — what the site owner pastes, in plain language

The app is fully wired for Google sign-in, private Drive imports, and card
payments. Everything reads keys from environment variables (see `.env.example`);
with keys missing, each feature degrades gracefully instead of breaking.

### 1. "Sign in with Google" + private Drive files (Google Cloud Console)

Do this once on console.cloud.google.com (signed in with your Google account):

1. Top bar -> **New Project**. Name it "ClipForge Studio". Wait for it to be created and select it.
2. Left menu -> **APIs & Services -> Library**. Search **"Google Drive API"** -> **Enable**.
3. Left menu -> **APIs & Services -> OAuth consent screen**:
   - User type: **External** -> Create.
   - Fill: App name "ClipForge Studio", your email for user support and developer contact -> Save.
   - On the **Scopes** step: **Add or Remove Scopes** -> tick `.../auth/drive.readonly`, `openid`, `email`, `profile` -> Update -> Save.
   - On **Test users**: Add -> type the Gmail address(es) that will sign in -> Save. (While the app is in "Testing" mode, only these emails can sign in.)
4. Left menu -> **APIs & Services -> Credentials** -> **Create Credentials -> OAuth client ID**:
   - Application type: **Web application**. Name it "ClipForge web".
   - Under **Authorized redirect URIs**: **Add URI** and paste EXACTLY:
     `http://127.0.0.1:8901/auth/google/callback`
     (When the app later runs on a real domain, add a second URI like
     `https://your-domain.com/auth/google/callback` — it must match letter for letter.)
   - Create -> a popup shows **Client ID** and **Client secret**. Copy both.
5. On the server, paste into the environment (or `.env` file):
   - `GOOGLE_CLIENT_ID` = the Client ID
   - `GOOGLE_CLIENT_SECRET` = the Client secret
   - `GOOGLE_REDIRECT_URI` = the exact redirect URI from step 4
   Then restart the app. The "Continue with Google" button appears on the login
   page, and Settings -> Google Drive connects private Drive imports.

### 2. Card payments (Stripe)

1. Create an account at stripe.com and finish the business details.
2. Dashboard -> **Developers -> API keys**: copy the **Secret key** (starts with `sk_live_`).
   (The Publishable key starting with `pk_live_` is recorded for completeness;
   this v1 uses server-side Checkout so only the secret key is required.)
3. Dashboard -> **Product catalogue -> Products -> Add product**:
   - Product "Starter", price $15, recurring monthly -> copy its **Price ID** (starts with `price_`).
   - Product "Pro", price $49, recurring monthly -> copy its **Price ID**.
4. Dashboard -> **Developers -> Webhooks -> Add endpoint**:
   - Endpoint URL: `https://your-domain.com/billing/webhook`
   - Events to send: **checkout.session.completed** -> Add endpoint.
   - Copy the **Signing secret** (starts with `whsec_`).
5. Paste into the environment: `STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`,
   `STRIPE_PRICE_ID_STARTER`, `STRIPE_PRICE_ID_PRO`, `STRIPE_WEBHOOK_SECRET`.
   Restart the app. The pricing-page buttons now open real Stripe Checkout;
   completed payments grant credits automatically via the webhook.

Until keys are pasted, the pricing buttons show "Payments aren't configured
yet" and no charge can ever be attempted. No test keys are used anywhere.

## Credential round verification (2026-10-18)

- e2e suite: **57/57 pass** (47 existing + 10 new: OAuth unconfigured/denied/
  no-code/bad-state friendly pages, settings page, Stripe unconfigured notice,
  webhook bad-signature 400, signature unit tests, fulfill idempotency,
  Drive file-ID parsing).
- Live HTTP: /auth/google (200, friendly setup message), callback error paths
  (200, friendly), /billing/webhook bad sig (400), /login + /pricing render.
- Parity: 79.8 -> **81.2**; must-haves **25/26** (Drive import closed; Google
  OAuth stays partial until credentials exist; Stripe wired-but-inactive).
- Sandbox caveat (as before): sandbox DNS is sinkholed, so live Google/Stripe
  calls can't be exercised here — the code paths are unit/integration-tested
  with locally-generated signatures and mocked parsing.

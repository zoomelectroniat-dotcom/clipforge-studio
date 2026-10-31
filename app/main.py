"""ClipForge Studio — clean-room AI clipper web app (FastAPI + Jinja2 + htmx)."""
import json
import math
import os
import pathlib
import secrets
import shutil
import uuid
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse,
                               RedirectResponse)
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy.orm import Session

import video
from auth import (COOKIE_NAME, get_current_user, get_current_user_optional,
                  grant_credits, hash_password, make_session_cookie,
                  spend_credits, verify_password)
from billing_stripe import (PLANS, StripeError, create_checkout_session,
                            stripe_configured, verify_webhook_signature,
                            webhook_secret)
from db import DATA_DIR, ROOT, SessionLocal, get_db, init_db
from models import (BrandTemplate, CaptionSegment, Clip, CreditLedger, Project,
                    RenderJob, ScheduledPost, SocialAccount, User, WebhookEvent)
from oauth_google import (OAuthError, build_authorize_url,
                          drive_access_token_for, drive_connection_status,
                          exchange_code, fetch_userinfo, google_oauth_configured,
                          new_state, parse_state, store_drive_tokens)
from pipeline import enqueue

APP_DIR = pathlib.Path(__file__).resolve().parent
templates = Environment(
    loader=FileSystemLoader(str(APP_DIR / "templates")),
    autoescape=select_autoescape(["html", "xml"]),
)
templates.globals.update({
    "virality_tier": lambda s: "top" if (s or 0) >= 80 else "high" if (s or 0) >= 60 else "mid" if (s or 0) >= 40 else "low",
    "fmt_dur": lambda ms: f"{int(ms//60000)}:{int((ms%60000)//1000):02d}" if ms else "0:00",
    "fmt_dt": lambda iso: (iso or "")[:16].replace("T", " "),
})

app = FastAPI(title="ClipForge Studio")
app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")
init_db()


def page(name: str, request: Request, **ctx):
    ctx.update({"request": request})
    return HTMLResponse(templates.get_template(name).render(**ctx))


def need_user(request: Request, db: Session) -> User:
    user = get_current_user_optional(request, db)
    if not user:
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    return user


def _now():
    return datetime.now(timezone.utc).isoformat()


# ------------------------------------------------------------------ public
@app.get("/", response_class=HTMLResponse)
def landing(request: Request, db: Session = Depends(get_db)):
    return page("landing.html", request, user=get_current_user_optional(request, db))


@app.get("/pricing", response_class=HTMLResponse)
def pricing(request: Request, db: Session = Depends(get_db)):
    return page("pricing.html", request, user=get_current_user_optional(request, db),
                notice=None, stripe_enabled=stripe_configured())


@app.get("/signup", response_class=HTMLResponse)
def signup_form(request: Request):
    return page("signup.html", request)


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    return page("login.html", request, google_enabled=google_oauth_configured())


@app.post("/auth/signup")
def signup(request: Request, email: str = Form(...), password: str = Form(...),
           display_name: str = Form(""), db: Session = Depends(get_db)):
    email = email.strip().lower()
    if db.query(User).filter(User.email == email).first():
        return page("signup.html", request, error="That email is already registered. Try signing in.")
    if len(password) < 8:
        return page("signup.html", request, error="Password needs at least 8 characters.")
    user = User(email=email, password_hash=hash_password(password),
                display_name=display_name.strip() or email.split("@")[0])
    db.add(user)
    db.flush()
    grant_credits(db, user, 60, "grant")  # 60 free minutes on signup
    # default brand template
    db.add(BrandTemplate(user_id=user.id, name="Default 9:16", aspect_ratio="9:16",
                         enabled_layouts='["fill","fit","split"]', is_default=1))
    db.commit()
    resp = RedirectResponse("/app", status_code=303)
    resp.set_cookie(COOKIE_NAME, make_session_cookie(user.id), httponly=True, samesite="lax", max_age=30 * 86400)
    return resp


@app.post("/auth/login")
def login(request: Request, email: str = Form(...), password: str = Form(...),
          db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == email.strip().lower()).first()
    if not user or not verify_password(password, user.password_hash):
        return page("login.html", request, error="Wrong email or password.",
                    google_enabled=google_oauth_configured())
    resp = RedirectResponse("/app", status_code=303)
    resp.set_cookie(COOKIE_NAME, make_session_cookie(user.id), httponly=True, samesite="lax", max_age=30 * 86400)
    return resp


@app.post("/auth/logout")
def logout():
    resp = RedirectResponse("/", status_code=303)
    resp.delete_cookie(COOKIE_NAME)
    return resp


# ------------------------------------------------------- Google OAuth
def _oauth_user(db: Session, email: str, name: str) -> User:
    """Find-or-create a local user for a verified Google email."""
    user = db.query(User).filter(User.email == email).first()
    if user:
        return user
    user = User(email=email,
                password_hash="oauth:" + secrets.token_hex(16),  # unusable; OAuth only
                display_name=(name or "").strip()[:80] or email.split("@")[0])
    db.add(user)
    db.flush()
    grant_credits(db, user, 60, "grant")  # same welcome credits as email signup
    db.add(BrandTemplate(user_id=user.id, name="Default 9:16", aspect_ratio="9:16",
                         enabled_layouts='["fill","fit","split"]', is_default=1))
    db.flush()
    return user


def _oauth_error_page(request: Request, message: str):
    return page("login.html", request, error=message,
                google_enabled=google_oauth_configured())


@app.get("/auth/google")
def google_login(request: Request):
    """Start 'Sign in with Google'. Friendly message when not configured."""
    if not google_oauth_configured():
        return _oauth_error_page(
            request,
            "Google sign-in isn't set up yet on this server — "
            "please use email and password for now.")
    return RedirectResponse(build_authorize_url(new_state("login")), status_code=303)


@app.get("/auth/google/callback")
def google_callback(request: Request, db: Session = Depends(get_db)):
    """Google redirects here after consent. Never 500s: every failure path
    renders a friendly message on the login page."""
    if request.query_params.get("error"):
        return _oauth_error_page(
            request,
            "You declined the Google sign-in, so no account was created. "
            "You can try again or use email and password.")
    code = request.query_params.get("code")
    purpose = parse_state(request.query_params.get("state"))
    if not google_oauth_configured():
        return _oauth_error_page(request, "Google sign-in isn't set up on this server.")
    if not code or not purpose:
        return _oauth_error_page(
            request, "The Google sign-in didn't complete. Please try again.")
    try:
        tokens = exchange_code(code)
        info = fetch_userinfo(tokens["access_token"])
    except OAuthError as e:
        return _oauth_error_page(request, str(e))
    email = info["email"]
    if purpose == "drive":
        # Existing signed-in user connecting Drive: keep THEIR account.
        user = get_current_user_optional(request, db)
        if not user:
            return RedirectResponse("/login", status_code=303)
        store_drive_tokens(db, user, tokens)
        db.commit()
        return RedirectResponse("/app/settings", status_code=303)
    # purpose == "login": sign in or create the account for this Google email.
    user = _oauth_user(db, email, info["name"])
    store_drive_tokens(db, user, tokens)
    db.commit()
    resp = RedirectResponse("/app", status_code=303)
    resp.set_cookie(COOKIE_NAME, make_session_cookie(user.id),
                    httponly=True, samesite="lax", max_age=30 * 86400)
    return resp


# ---------------------------------------------------------------- settings
@app.get("/app/settings", response_class=HTMLResponse)
def settings(request: Request, db: Session = Depends(get_db)):
    user = need_user(request, db)
    return page("settings.html", request, user=user, active="settings",
                drive_status=drive_connection_status(db, user),
                google_enabled=google_oauth_configured(),
                oauth_error=request.query_params.get("error"))


@app.get("/app/settings/google-drive")
def drive_connect(request: Request, db: Session = Depends(get_db)):
    """Connect Google Drive for a signed-in user (private file imports)."""
    need_user(request, db)
    if not google_oauth_configured():
        return RedirectResponse("/app/settings?error=oauth-missing", status_code=303)
    return RedirectResponse(build_authorize_url(new_state("drive")), status_code=303)


# ---------------------------------------------------------------- dashboard
@app.get("/app", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    user = need_user(request, db)
    projects = (db.query(Project).filter(Project.user_id == user.id)
                .order_by(Project.created_at.desc()).all())
    return page("dashboard.html", request, user=user, projects=projects, active="dashboard")


# ------------------------------------------------------------------ import
@app.get("/app/projects/new", response_class=HTMLResponse)
def new_project(request: Request, db: Session = Depends(get_db)):
    user = need_user(request, db)
    return page("new_project.html", request, user=user, active="new")


@app.post("/app/projects")
async def create_project(request: Request, db: Session = Depends(get_db)):
    user = need_user(request, db)
    form = await request.form()
    source_kind = form.get("source_kind", "file")
    title = (form.get("title") or "Untitled project").strip()[:120]

    project = Project(user_id=user.id, title=title, source_type="upload",
                      language=(form.get("language") or "en")[:8])
    db.add(project)
    db.flush()

    updir = ROOT / "uploads" / project.id
    updir.mkdir(parents=True, exist_ok=True)

    try:
        if source_kind == "url":
            url = (form.get("source_url") or "").strip()
            if not url.startswith(("http://", "https://")):
                raise ValueError("Paste a full http(s) URL.")
            project.source_url = url
            low = url.lower()
            if "youtube.com" in low or "youtu.be" in low:
                project.source_type = "youtube"
            elif low.endswith(".mp4"):
                project.source_type = "mp4"
            elif "vimeo.com" in low:
                project.source_type = "vimeo"
            elif "drive.google.com" in low:
                project.source_type = "drive"
            else:
                project.source_type = "mp4"
            project.status = "uploading"
            # Optional cookies.txt for login/age-gated videos. Stored only as a
            # per-job temp file (never in the repo, database, uploads, or
            # renders); the fetch stage consumes it for this one download and
            # deletes it afterwards. Contents are never logged.
            cookies_upload = form.get("cookies_file")
            if cookies_upload is not None and getattr(cookies_upload, "filename", ""):
                import tempfile
                data = await cookies_upload.read()
                if len(data) > 1024 * 1024:
                    raise ValueError("Cookies file is too large (max 1 MB).")
                cpath = pathlib.Path(tempfile.gettempdir()) / f"clipforge-cookies-{project.id}.txt"
                cpath.write_bytes(data)
        else:
            upload: UploadFile = form.get("file")
            if not upload or not upload.filename:
                raise ValueError("Choose a video file first.")
            ext = pathlib.Path(upload.filename).suffix.lower() or ".mp4"
            if ext not in (".mp4", ".mov", ".webm", ".mkv", ".m4v"):
                raise ValueError(f"Unsupported format {ext} — MP4/MOV/WebM/MKV please.")
            dest = updir / f"source{ext}"
            size = 0
            with open(dest, "wb") as f:
                while True:
                    chunk = await upload.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > 10 * 1024 * 1024 * 1024:
                        raise ValueError("File is over the 10 GB v1 limit.")
                    f.write(chunk)
            project.source_type = "upload"
            project.local_media_path = str(dest)
            project.status = "uploading"
        project.updated_at = _now()
        db.commit()
    except ValueError as e:
        db.rollback()
        # Best-effort: do not leave a just-uploaded cookies file behind when
        # project creation itself failed.
        try:
            import tempfile
            cpath = pathlib.Path(tempfile.gettempdir()) / f"clipforge-cookies-{project.id}.txt"
            cpath.unlink(missing_ok=True)
        except OSError:
            pass
        return page("new_project.html", request, user=user, active="new", error=str(e))
    return RedirectResponse(f"/app/projects/{project.id}/setup", status_code=303)


# -------------------------------------------------------------------- setup
@app.get("/app/projects/{pid}/setup", response_class=HTMLResponse)
def setup(request: Request, pid: str, db: Session = Depends(get_db)):
    user = need_user(request, db)
    project = db.query(Project).filter(Project.id == pid, Project.user_id == user.id).first()
    if not project:
        raise HTTPException(404)
    templates_list = db.query(BrandTemplate).filter(BrandTemplate.user_id == user.id).all()
    prefs = json.loads(project.curation_prefs or "{}")
    return page("setup.html", request, user=user, project=project,
                templates_list=templates_list, prefs=prefs, active="new")


@app.post("/app/projects/{pid}/generate")
async def generate(request: Request, pid: str, db: Session = Depends(get_db)):
    user = need_user(request, db)
    project = db.query(Project).filter(Project.id == pid, Project.user_id == user.id).first()
    if not project:
        raise HTTPException(404)
    # BUG-01: double-clicking Generate must not 500 (uq_active_generation)
    # nor charge twice — a live generation is simply resumed.
    if project.status == "processing":
        return RedirectResponse(f"/app/projects/{project.id}/processing", status_code=303)
    form = await request.form()
    prefs = {
        "clip_length_min": max(5, min(120, int(form.get("clip_length_min") or 15))),
        "clip_length_max": max(10, min(180, int(form.get("clip_length_max") or 60))),
        "genre": (form.get("genre") or "talking-head"),
        "language": (form.get("language") or project.language or "en"),
        "keywords": [k.strip()[:40] for k in (form.get("keywords") or "").split(",") if k.strip()][:10],
        "prompt": (form.get("prompt") or "")[:2000],
        "ai_hook": bool(form.get("ai_hook")),
        "smart_reframe": bool(form.get("smart_reframe", "1")),
        "brand_template_id": form.get("brand_template_id") or None,
    }
    if prefs["clip_length_max"] < prefs["clip_length_min"]:
        prefs["clip_length_max"] = prefs["clip_length_min"]
    project.curation_prefs = json.dumps(prefs)
    if prefs["brand_template_id"]:
        project.brand_template_id = prefs["brand_template_id"]

    # charge credits for the source duration (probe now so the charge is exact)
    try:
        info = video.probe(project.local_media_path) if project.local_media_path else None
    except Exception:
        info = None
    minutes = max(1, math.ceil((info["duration_sec"] if info else 60) / 60))
    try:
        spend_credits(db, user, minutes, "processing")
    except ValueError:
        db.rollback()
        return page("setup.html", request, user=user, project=project,
                    templates_list=db.query(BrandTemplate).filter(BrandTemplate.user_id == user.id).all(),
                    prefs=prefs, active="new",
                    error=f"Not enough credits — this video needs {minutes} min, you have {user.credits_balance}.")
    project.credits_charged = minutes
    project.status = "processing"
    project.error_message = None
    project.updated_at = _now()
    enqueue(db, "fetch", project_id=project.id)
    db.commit()
    return RedirectResponse(f"/app/projects/{project.id}/processing", status_code=303)


# --------------------------------------------------------------- processing
@app.get("/app/projects/{pid}/processing", response_class=HTMLResponse)
def processing(request: Request, pid: str, db: Session = Depends(get_db)):
    user = need_user(request, db)
    project = db.query(Project).filter(Project.id == pid, Project.user_id == user.id).first()
    if not project:
        raise HTTPException(404)
    if project.status == "ready":
        return RedirectResponse(f"/app/projects/{pid}", status_code=303)
    return page("processing.html", request, user=user, project=project, active="new")


@app.get("/app/projects/{pid}/status-partial", response_class=HTMLResponse)
def status_partial(request: Request, pid: str, db: Session = Depends(get_db)):
    user = need_user(request, db)
    project = db.query(Project).filter(Project.id == pid, Project.user_id == user.id).first()
    if not project:
        raise HTTPException(404)
    job = (db.query(RenderJob).filter(RenderJob.project_id == pid,
                                      RenderJob.status.in_(("queued", "running")))
           .order_by(RenderJob.created_at.desc()).first())
    pct, stage = 0, "Queued…"
    if job:
        pct, stage = job.progress_pct, job.stage or job.job_type
    elif project.status == "ready":
        pct, stage = 100, "Done"
    if project.status == "failed":
        return HTMLResponse(
            f'<div class="c-error-banner" role="alert"><div><strong>Processing failed.</strong>'
            f'<div class="muted">{project.error_message or "Unknown error."}</div>'
            f'<div class="mt-8"><a class="c-btn secondary sm" href="/app/projects/{pid}/setup">Try again</a></div>'
            f"</div></div>")
    if project.status == "ready" or (job and job.status == "done" and not job):
        pass
    html = templates.get_template("partials/status.html").render(
        request=request, pct=pct, stage=stage, pid=pid,
        done=(project.status == "ready"))
    resp = HTMLResponse(html)
    if project.status == "ready":
        resp.headers["HX-Redirect"] = f"/app/projects/{pid}"
    return resp


@app.get("/api/v1/projects/{pid}/status")
def api_status(request: Request, pid: str, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    project = db.query(Project).filter(Project.id == pid, Project.user_id == user.id).first()
    if not project:
        raise HTTPException(404)
    job = (db.query(RenderJob).filter(RenderJob.project_id == pid,
                                      RenderJob.status.in_(("queued", "running")))
           .order_by(RenderJob.created_at.desc()).first())
    return {"status": project.status,
            "progress_pct": job.progress_pct if job else (100 if project.status == "ready" else 0),
            "stage": (job.stage if job else project.status),
            "error": project.error_message}


# ------------------------------------------------------------------ gallery
@app.get("/app/projects/{pid}", response_class=HTMLResponse)
def gallery(request: Request, pid: str, sort: str = "virality", min_score: int = 0,
            q: str = "", db: Session = Depends(get_db)):
    user = need_user(request, db)
    project = db.query(Project).filter(Project.id == pid, Project.user_id == user.id).first()
    if not project:
        raise HTTPException(404)
    if project.status == "processing":
        return RedirectResponse(f"/app/projects/{pid}/processing", status_code=303)
    clips_q = db.query(Clip).filter(Clip.project_id == pid)
    if min_score:
        clips_q = clips_q.filter(Clip.virality_score >= min_score)
    if q:
        clips_q = clips_q.filter(Clip.title.ilike(f"%{q}%"))
    order = {"virality": Clip.virality_score.desc(), "newest": Clip.created_at.desc(),
             "duration": Clip.duration_ms.desc()}.get(sort, Clip.virality_score.desc())
    clips = clips_q.order_by(order).all()
    return page("gallery.html", request, user=user, project=project, clips=clips,
                sort=sort, min_score=min_score, q=q, active="dashboard")


# ------------------------------------------------------------------- editor
@app.get("/app/clips/{cid}/edit", response_class=HTMLResponse)
def editor(request: Request, cid: str, db: Session = Depends(get_db)):
    user = need_user(request, db)
    clip = db.query(Clip).join(Project).filter(Clip.id == cid, Project.user_id == user.id).first()
    if not clip:
        raise HTTPException(404)
    project = clip.project
    breakdown = json.loads(clip.score_breakdown or "{}")
    prefs = json.loads(clip.render_prefs or "{}")
    return page("editor.html", request, user=user, clip=clip, project=project,
                breakdown=breakdown, prefs=prefs, active="dashboard")


@app.patch("/app/clips/{cid}")
async def patch_clip(request: Request, cid: str, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    clip = db.query(Clip).join(Project).filter(Clip.id == cid, Project.user_id == user.id).first()
    if not clip:
        raise HTTPException(404)
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")  # BUG-04
    changed_layout = False
    if "title" in data:
        clip.title = str(data["title"])[:120]
    if "layout" in data and data["layout"] in ("fill", "fit", "split"):
        if clip.layout != data["layout"]:
            changed_layout = True
        clip.layout = data["layout"]
    if "trim_start_ms" in data or "trim_end_ms" in data:
        # BUG-08: validate trim bounds up front instead of failing opaquely
        # in the render worker after retries.
        try:
            s = int(data.get("trim_start_ms", clip.trim_start_ms))
            e_raw = data.get("trim_end_ms", clip.trim_end_ms)
            e = int(e_raw) if e_raw else None
        except (TypeError, ValueError):
            raise HTTPException(400, "Trim values must be numbers")
        if s < 0:
            raise HTTPException(400, "Trim start must be >= 0")
        if e is not None and e <= s:
            raise HTTPException(400, "End must be after start")
        if clip.duration_ms and (s >= clip.duration_ms
                                 or (e is not None and e > clip.duration_ms)):
            raise HTTPException(400, "Trim is outside the clip")
        clip.trim_start_ms, clip.trim_end_ms = s, e
        changed_layout = True  # trim changes the rendered output too
    if "render_prefs" in data and isinstance(data["render_prefs"], dict):
        prefs = json.loads(clip.render_prefs or "{}")
        prefs.update(data["render_prefs"])
        clip.render_prefs = json.dumps(prefs)
        changed_layout = True
    clip.updated_at = _now()
    if changed_layout:
        # re-render the preview so the editor shows the new trim/layout
        clip.preview_path = None
        enqueue(db, "preview", project_id=clip.project_id, clip_id=clip.id)
    db.commit()
    return {"ok": True, "re_rendering": changed_layout}


@app.patch("/app/captions/{cap_id}")
async def patch_caption(request: Request, cap_id: str, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    cap = (db.query(CaptionSegment).join(Clip).join(Project)
           .filter(CaptionSegment.id == cap_id, Project.user_id == user.id).first())
    if not cap:
        raise HTTPException(404)
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")  # BUG-04
    if "text" in data:
        cap.text = str(data["text"])[:500]
        # keep word timings roughly in sync: redistribute evenly
        try:
            words = json.loads(cap.word_timings or "[]")
            new_words = str(data["text"]).split()
            if words and new_words:
                total = cap.end_ms - cap.start_ms
                per = total / max(1, len(new_words))
                t = cap.start_ms
                words = [{"w": w, "start_ms": int(t + i * per), "end_ms": int(t + (i + 1) * per)}
                         for i, w in enumerate(new_words)]
                cap.word_timings = json.dumps(words)
        except Exception:
            pass
    db.commit()
    return {"ok": True, "text": cap.text}


# ------------------------------------------------------------------- export
@app.post("/app/clips/{cid}/render")
def start_render(request: Request, cid: str, db: Session = Depends(get_db)):
    user = need_user(request, db)
    clip = db.query(Clip).join(Project).filter(Clip.id == cid, Project.user_id == user.id).first()
    if not clip:
        raise HTTPException(404)
    clip.status = "rendering"
    clip.updated_at = _now()
    enqueue(db, "render", project_id=clip.project_id, clip_id=clip.id)
    db.commit()
    return RedirectResponse(f"/app/clips/{cid}/export", status_code=303)


@app.get("/app/clips/{cid}/export", response_class=HTMLResponse)
def export_page(request: Request, cid: str, db: Session = Depends(get_db)):
    user = need_user(request, db)
    clip = db.query(Clip).join(Project).filter(Clip.id == cid, Project.user_id == user.id).first()
    if not clip:
        raise HTTPException(404)
    job = (db.query(RenderJob).filter(RenderJob.clip_id == cid, RenderJob.job_type == "render")
           .order_by(RenderJob.created_at.desc()).first())
    srt_job = (db.query(RenderJob).filter(RenderJob.clip_id == cid, RenderJob.job_type == "export_srt",
                                          RenderJob.status == "done")
               .order_by(RenderJob.created_at.desc()).first())
    return page("export.html", request, user=user, clip=clip, job=job,
                srt_path=srt_job.result_path if srt_job else None, active="dashboard")


@app.get("/app/clips/{cid}/download")
def download_clip(request: Request, cid: str, db: Session = Depends(get_db)):
    user = need_user(request, db)
    clip = db.query(Clip).join(Project).filter(Clip.id == cid, Project.user_id == user.id).first()
    if not clip or not clip.output_path or not pathlib.Path(clip.output_path).exists():
        raise HTTPException(404, "Final render not ready yet")
    return FileResponse(clip.output_path, media_type="video/mp4",
                        filename=f"{clip.title[:40].strip().replace(' ', '-') or 'clip'}.mp4")


@app.get("/app/clips/{cid}/captions.srt")
def download_srt(request: Request, cid: str, db: Session = Depends(get_db)):
    user = need_user(request, db)
    clip = db.query(Clip).join(Project).filter(Clip.id == cid, Project.user_id == user.id).first()
    if not clip:
        raise HTTPException(404)
    srt = ROOT / "renders" / clip.id / "captions.srt"
    if not srt.exists():
        raise HTTPException(404, "SRT not ready yet")
    return FileResponse(str(srt), media_type="text/plain", filename="captions.srt")


@app.get("/media/clips/{cid}/preview.mp4")
def serve_preview(request: Request, cid: str, db: Session = Depends(get_db)):
    user = need_user(request, db)
    clip = db.query(Clip).join(Project).filter(Clip.id == cid, Project.user_id == user.id).first()
    if not clip or not clip.preview_path or not pathlib.Path(clip.preview_path).exists():
        raise HTTPException(404)
    return FileResponse(clip.preview_path, media_type="video/mp4")


@app.get("/media/clips/{cid}/thumb.jpg")
def serve_thumb(request: Request, cid: str, db: Session = Depends(get_db)):
    user = need_user(request, db)
    clip = db.query(Clip).join(Project).filter(Clip.id == cid, Project.user_id == user.id).first()
    if not clip or not clip.thumbnail_path or not pathlib.Path(clip.thumbnail_path).exists():
        raise HTTPException(404)
    return FileResponse(clip.thumbnail_path, media_type="image/jpeg")


# ---------------------------------------------------------- brand templates
@app.get("/app/brand-templates", response_class=HTMLResponse)
def brand_list(request: Request, db: Session = Depends(get_db)):
    user = need_user(request, db)
    tpls = db.query(BrandTemplate).filter(BrandTemplate.user_id == user.id).all()
    return page("brand_templates.html", request, user=user, templates_list=tpls, active="brand")


@app.post("/app/brand-templates")
async def brand_create(request: Request, db: Session = Depends(get_db)):
    user = need_user(request, db)
    form = await request.form()
    # BUG-05: never let raw form input reach the DB CHECK constraint / int().
    aspect = form.get("aspect_ratio") or "9:16"
    if aspect not in ("9:16", "1:1", "16:9", "4:5"):
        aspect = "9:16"
    try:
        font_size = int(form.get("font_size") or 64)
    except (TypeError, ValueError):
        font_size = 64
    font_size = max(16, min(200, font_size))
    font_family = (form.get("font_family") or "").strip()
    if font_family not in video.ALLOWED_FONTS:
        font_family = video.FONT
    import re as _re
    def _color(v, default):
        v = (v or "").strip()
        return v if _re.fullmatch(r"#[0-9a-fA-F]{6}", v) else default
    style = {"uppercase": bool(form.get("uppercase")), "emoji": bool(form.get("emoji")),
             "font_size": font_size, "font_family": font_family,
             "font_color": _color(form.get("font_color"), "#FFFFFF"),
             "keyword_color": _color(form.get("keyword_color"), "#0E7A64")}
    tpl = BrandTemplate(user_id=user.id, name=(form.get("name") or "Template")[:80],
                        aspect_ratio=aspect,
                        enabled_layouts=json.dumps(form.getlist("layouts") or ["fill"]),
                        caption_style=json.dumps(style),
                        watermark_enabled=1 if form.get("watermark") else 0)
    db.add(tpl)
    db.flush()  # need the id before saving the logo file
    # logo upload (optional, stored locally, burned into renders)
    logo = form.get("logo")
    if logo is not None and getattr(logo, "filename", ""):
        ext = pathlib.Path(logo.filename).suffix.lower()
        if ext in (".png", ".jpg", ".jpeg", ".webp"):
            data = await logo.read()
            if data and len(data) <= 2 * 1024 * 1024:
                logodir = DATA_DIR / "logos"
                logodir.mkdir(parents=True, exist_ok=True)
                dest = logodir / f"{tpl.id}{ext}"
                dest.write_bytes(data)
                dest.chmod(0o600)
                tpl.logo_path = str(dest)
    db.commit()
    return RedirectResponse("/app/brand-templates", status_code=303)


@app.post("/app/brand-templates/{tid}/delete")
def brand_delete(request: Request, tid: str, db: Session = Depends(get_db)):
    user = need_user(request, db)
    tpl = db.query(BrandTemplate).filter(BrandTemplate.id == tid, BrandTemplate.user_id == user.id).first()
    if tpl:
        if tpl.logo_path:
            try:
                pathlib.Path(tpl.logo_path).unlink(missing_ok=True)
            except OSError:
                pass
        db.delete(tpl)
        db.commit()
    return RedirectResponse("/app/brand-templates", status_code=303)


@app.get("/media/logos/{tid}")
def serve_logo(request: Request, tid: str, db: Session = Depends(get_db)):
    user = need_user(request, db)
    tpl = db.query(BrandTemplate).filter(BrandTemplate.id == tid,
                                         BrandTemplate.user_id == user.id).first()
    if not tpl or not tpl.logo_path or not pathlib.Path(tpl.logo_path).exists():
        raise HTTPException(404)
    return FileResponse(tpl.logo_path)


# ------------------------------------------------------------------- social
@app.get("/app/social", response_class=HTMLResponse)
def social(request: Request, db: Session = Depends(get_db)):
    user = need_user(request, db)
    accounts = db.query(SocialAccount).filter(SocialAccount.user_id == user.id).all()
    return page("social.html", request, user=user, accounts=accounts, active="social")


@app.get("/app/schedule", response_class=HTMLResponse)
def schedule_list(request: Request, db: Session = Depends(get_db)):
    user = need_user(request, db)
    posts = (db.query(ScheduledPost).join(Clip).join(Project)
             .filter(Project.user_id == user.id).order_by(ScheduledPost.scheduled_at).all())
    return page("scheduler.html", request, user=user, posts=posts, active="schedule")


@app.post("/app/clips/{cid}/schedule")
async def schedule_create(request: Request, cid: str, db: Session = Depends(get_db)):
    user = need_user(request, db)
    clip = db.query(Clip).join(Project).filter(Clip.id == cid, Project.user_id == user.id).first()
    if not clip:
        raise HTTPException(404)
    form = await request.form()
    account_id = form.get("social_account_id")
    when = (form.get("scheduled_at") or "").strip()
    account = db.query(SocialAccount).filter(SocialAccount.id == account_id,
                                             SocialAccount.user_id == user.id).first()
    if not account or not when:
        return RedirectResponse(f"/app/clips/{cid}/edit?toast=schedule-error", status_code=303)
    post = ScheduledPost(clip_id=cid, social_account_id=account.id, scheduled_at=when,
                         caption_text=(form.get("caption_text") or "")[:500])
    db.add(post)
    try:
        db.commit()
    except Exception:
        db.rollback()
    return RedirectResponse("/app/schedule", status_code=303)


# ------------------------------------------------------------------- billing
@app.get("/app/billing", response_class=HTMLResponse)
def billing(request: Request, db: Session = Depends(get_db)):
    user = need_user(request, db)
    ledger = (db.query(CreditLedger).filter(CreditLedger.user_id == user.id)
              .order_by(CreditLedger.created_at.desc()).limit(50).all())
    return page("billing.html", request, user=user, ledger=ledger, active="billing")


# ------------------------------------------------------------- Stripe
def _pricing_notice(request: Request, user, message: str):
    return page("pricing.html", request, user=user, notice=message,
                stripe_enabled=stripe_configured())


@app.post("/billing/checkout")
def stripe_checkout(request: Request, plan: str = Form("pro"),
                    db: Session = Depends(get_db)):
    """Start a Stripe Checkout. With keys unset this only shows the
    'not configured' notice — it NEVER attempts a charge."""
    user = need_user(request, db)
    plan = plan if plan in PLANS else "pro"
    if not stripe_configured():
        return _pricing_notice(request, user,
                               "Payments aren't configured yet on this server — "
                               "paid plans are coming soon.")
    base = (os.environ.get("APP_URL") or str(request.base_url)).rstrip("/")
    try:
        url = create_checkout_session(
            user.id, user.email, plan,
            success_url=base + "/billing/success",
            cancel_url=base + "/pricing")
    except StripeError as e:
        return _pricing_notice(request, user, str(e))
    return RedirectResponse(url, status_code=303)


@app.get("/billing/success", response_class=HTMLResponse)
def billing_success(request: Request, db: Session = Depends(get_db)):
    user = need_user(request, db)
    ledger = (db.query(CreditLedger).filter(CreditLedger.user_id == user.id)
              .order_by(CreditLedger.created_at.desc()).limit(50).all())
    return page("billing.html", request, user=user, ledger=ledger, active="billing",
                notice="Payment received — your credits will appear here in a moment.")


def _fulfill_checkout(db: Session, session_obj: dict) -> None:
    """Grant credits for a completed Checkout Session. Idempotent via WebhookEvent."""
    sid = session_obj.get("id") or ""
    if not sid or db.get(WebhookEvent, sid):
        return  # already fulfilled (Stripe retries)
    meta = session_obj.get("metadata") or {}
    user = db.get(User, meta.get("user_id") or "")
    plan = meta.get("plan")
    db.add(WebhookEvent(id=sid, created_at=_now()))
    if (user and plan in PLANS
            and session_obj.get("payment_status") in (None, "paid", "no_payment_required")):
        grant_credits(db, user, PLANS[plan]["credits"], "purchase")
        user.plan_tier = plan
        user.updated_at = _now()
    db.commit()


@app.post("/billing/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    """Stripe event receiver. Rejects anything with a bad signature (400)."""
    payload = await request.body()
    if not verify_webhook_signature(payload,
                                     request.headers.get("stripe-signature"),
                                     webhook_secret()):
        raise HTTPException(400, "Bad webhook signature")
    try:
        event = json.loads(payload)
    except Exception:
        raise HTTPException(400, "Bad webhook payload")
    if event.get("type") == "checkout.session.completed":
        _fulfill_checkout(db, (event.get("data") or {}).get("object") or {})
    return {"received": True}


# ----------------------------------------------------------------- analytics
@app.get("/app/analytics", response_class=HTMLResponse)
def analytics(request: Request, db: Session = Depends(get_db)):
    user = need_user(request, db)
    rows = (db.query(Project, Clip).join(Clip, Clip.project_id == Project.id)
            .filter(Project.user_id == user.id).all())
    by_project: dict = {}
    for p, c in rows:
        by_project.setdefault(p, []).append(c)
    return page("analytics.html", request, user=user, by_project=by_project, active="analytics")

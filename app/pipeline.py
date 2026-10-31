"""Async pipeline stages. Each stage is idempotent: it checks for existing output
before doing expensive work, so retried jobs never duplicate results."""
import json
import pathlib
import shutil
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

import video
from db import ROOT
from drive_dl import download_private, download_public, extract_drive_file_id
from groq_client import GroqClient
from models import CaptionSegment, Clip, Project, RenderJob, User
from oauth_google import drive_access_token_for

UPLOADS = ROOT / "uploads"
MEDIA = ROOT / "media"
RENDERS = ROOT / "renders"
for d in (UPLOADS, MEDIA, RENDERS):
    d.mkdir(exist_ok=True)


def _now():
    return datetime.now(timezone.utc).isoformat()


def _touch(obj, db: Session):
    obj.updated_at = _now()
    db.flush()


def enqueue(db: Session, job_type: str, project_id: str | None = None,
            clip_id: str | None = None) -> RenderJob:
    job = RenderJob(id=uuid.uuid4().hex, project_id=project_id, clip_id=clip_id,
                    job_type=job_type, status="queued", created_at=_now(), updated_at=_now())
    db.add(job)
    db.flush()
    return job


def _set_progress(db: Session, job: RenderJob, pct: int, stage: str):
    job.progress_pct = max(0, min(100, pct))
    job.stage = stage
    job.updated_at = _now()
    db.flush()


# ------------------------------------------------------------------ fetch
def stage_fetch(job: RenderJob, db: Session) -> None:
    project = db.get(Project, job.project_id)
    _set_progress(db, job, 5, "Checking source video")
    src = project.local_media_path

    if project.source_type != "upload" or not src:
        # URL import path: try yt-dlp for youtube-like sources, direct download for mp4
        src = _fetch_remote(project, db, job)

    info = video.probe(src)
    project.local_media_path = src
    project.duration_sec = int(info["duration_sec"])
    if project.duration_sec > 3 * 3600:
        raise RuntimeError("Source is longer than the 3-hour v1 limit.")
    project.status = "processing"
    _touch(project, db)
    _set_progress(db, job, 100, "Source ready")


def _assert_public_url(url: str) -> None:
    """SSRF guard (BUG-03): only public http(s) hosts may be fetched.

    Resolves the hostname and rejects private, loopback, link-local,
    reserved and multicast IPs. Residual DNS TOCTOU is noted for the
    backend hardening round.
    """
    import ipaddress
    import socket
    from urllib.parse import urlparse

    try:
        host = urlparse(url).hostname or ""
        ip = ipaddress.ip_address(socket.gethostbyname(host))
    except Exception:
        raise RuntimeError("Could not resolve the source URL.")
    if (ip.is_private or ip.is_loopback or ip.is_link_local
            or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
        raise RuntimeError("URL imports must be public http(s) addresses.")


def _fetch_remote(project: Project, db: Session, job: RenderJob) -> str:
    import httpx

    dest_dir = UPLOADS / project.id
    dest_dir.mkdir(parents=True, exist_ok=True)
    url = project.source_url or ""
    _assert_public_url(url)
    _set_progress(db, job, 10, "Downloading source")
    if project.source_type == "drive" or "drive.google.com" in url:
        return _fetch_drive(project, db, job)
    if project.source_type == "mp4" or url.endswith(".mp4"):
        dest = dest_dir / "source.mp4"
        # trust_env=False: sandbox/proxied envs carry malformed proxy vars
        # (same workaround as groq_client.py)
        with httpx.stream("GET", url, timeout=120, follow_redirects=True,
                          trust_env=False) as r:
            r.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in r.iter_bytes(1024 * 256):
                    f.write(chunk)
        return str(dest)
    # youtube / social / podcast links via yt-dlp (pure-python, optional)
    try:
        import yt_dlp
    except ImportError:
        raise RuntimeError("URL import needs the yt-dlp package (pip install yt-dlp). File upload works without it.")
    dest = dest_dir / "source.%(ext)s"
    opts = {"format": "bv*[height<=1080]+ba/b[height<=1080]/b",
            "outtmpl": str(dest), "quiet": True, "no_warnings": True,
            "noplaylist": True,  # a playlist/pasted channel URL must not pull dozens of videos
            "max_filesize": 10 * 1024 * 1024 * 1024}
    # Optional per-job cookies.txt (login/age-gated videos): uploaded with the
    # project, kept only as a temp file outside uploads/renders, used for this
    # one download, and deleted afterwards whatever the outcome. Contents are
    # never logged. yt-dlp's "cookiefile" option is the --cookies CLI flag.
    cookies_path = None
    try:
        import tempfile
        cand = pathlib.Path(tempfile.gettempdir()) / f"clipforge-cookies-{project.id}.txt"
        if cand.exists():
            cookies_path = cand
            opts["cookiefile"] = str(cand)
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
    except Exception as e:  # noqa: BLE001 — map yt-dlp errors to user-friendly ones
        msg = str(e)
        low = msg.lower()
        if "private video" in low or "video is private" in low:
            raise RuntimeError("This video is private — the downloader cannot access it. "
                               "Use a public link or upload the file directly.")
        if ("unavailable" in low or "removed" in low or "deleted" in low
                or "does not exist" in low or "not found" in low or "404" in low):
            raise RuntimeError("This video is unavailable (deleted, removed or the link is wrong). "
                               "Check the URL and try again.")
        if ("sign in to" in low or "log in" in low or "login required" in low
                or "age gate" in low or "age restriction" in low or "age-verif" in low):
            raise RuntimeError("This video needs a login or age verification — "
                               "upload the file directly instead.")
        if "unsupported url" in low or "no video formats" in low:
            raise RuntimeError("Could not download from this URL — the site may not be "
                               "supported. Upload the file directly instead.")
        if "certificate" in low:
            raise RuntimeError("Download failed: a network/TLS certificate error blocked "
                               "the download (common behind corporate proxies) — "
                               "upload the file directly instead.")
        raise RuntimeError(f"Download failed: {msg[:200]}")
    finally:
        # Single-use credentials: remove the temp cookies file once the
        # download attempt is over, success or failure.
        if cookies_path is not None:
            try:
                cookies_path.unlink()
            except OSError:
                pass
    for ext in ("mp4", "webm", "mkv", "mov"):
        cand = dest_dir / f"source.{ext}"
        if cand.exists():
            final = dest_dir / "source.mp4"
            if cand != final:
                shutil.move(str(cand), str(final))
            return str(final)
    raise RuntimeError("Download finished but no video file was found.")


def _fetch_drive(project: Project, db: Session, job: RenderJob) -> str:
    """Google Drive import. Public 'anyone with the link' files download with
    no credentials; private files use the project owner's connected Google
    account (Settings -> Google Drive)."""
    url = project.source_url or ""
    file_id = extract_drive_file_id(url)
    if not file_id:
        raise RuntimeError("Could not find a file ID in that Drive link — "
                           "use a file's 'Share -> Copy link' URL, not a folder.")
    dest_dir = UPLOADS / project.id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "source.mp4"
    _set_progress(db, job, 10, "Downloading from Google Drive")
    # Path 1: public link — no credentials needed.
    try:
        return download_public(file_id, str(dest))
    except RuntimeError as e:
        if "isn't shared publicly" not in str(e):
            raise
    # Path 2: private file via the owner's connected Google account.
    user = db.get(User, project.user_id)
    token = drive_access_token_for(db, user) if user else None
    if not token:
        raise RuntimeError("This Drive file is private. Connect your Google account "
                           "(Dashboard -> Settings -> Google Drive) and try again.")
    try:
        return download_private(file_id, str(dest), token)
    except RuntimeError as e:
        if str(e) == "DRIVE_TOKEN_BAD":
            raise RuntimeError("Your Google Drive connection expired — "
                               "reconnect it in Settings and try again.")
        raise


# -------------------------------------------------------------- transcribe
def stage_transcribe(job: RenderJob, db: Session) -> None:
    project = db.get(Project, job.project_id)
    tdir = MEDIA / project.id
    tdir.mkdir(parents=True, exist_ok=True)
    tpath = tdir / "transcript.json"

    _set_progress(db, job, 10, "Extracting audio")
    wav = tdir / "audio.wav"
    if not tpath.exists():
        if not wav.exists():
            video.extract_audio_wav(project.local_media_path, str(wav))
        _set_progress(db, job, 35, "Transcribing with AI")
        result = GroqClient().transcribe(str(wav))
        tpath.write_text(json.dumps(result))
    else:
        result = json.loads(tpath.read_text())

    words = result.get("words", [])
    if not words:
        raise RuntimeError("Transcription came back empty — the source may have no speech.")
    _set_progress(db, job, 100, f"Transcript ready ({len(words)} words)")


# ------------------------------------------------------------------ detect
def _transcript_for_llm(words: list[dict]) -> str:
    # chunk into ~14-word lines with [sec] markers
    lines, chunk = [], []
    for w in words:
        chunk.append(w)
        if len(chunk) >= 14:
            lines.append(f"[{chunk[0]['start_ms']/1000:.1f}] " + " ".join(x["w"] for x in chunk))
            chunk = []
    if chunk:
        lines.append(f"[{chunk[0]['start_ms']/1000:.1f}] " + " ".join(x["w"] for x in chunk))
    return "\n".join(lines)


def _assign_speakers(words: list[dict]) -> list[str]:
    """Pause-heuristic speaker labels (honest note: NOT true diarization —
    Groq Whisper gives no speaker info. A gap of >= 1.0s between words starts a
    new turn and we alternate Speaker 1 / Speaker 2. Works for interviews and
    back-and-forth dialogue; single-speaker videos stay Speaker 1 throughout."""
    labels, current = [], "Speaker 1"
    prev_end = None
    for w in words:
        if prev_end is not None and (w["start_ms"] - prev_end) >= 1000:
            current = "Speaker 2" if current == "Speaker 1" else "Speaker 1"
        labels.append(current)
        prev_end = w["end_ms"]
    return labels


def _group_segments(words: list[dict], keywords: list[str],
                    speakers: list[str] | None = None) -> list[dict]:
    kw = {k.lower() for k in keywords}
    segments, cur, cur_spk = [], [], []
    for i, w in enumerate(words):
        cur.append(w)
        cur_spk.append(speakers[i] if speakers else None)
        span = w["end_ms"] - cur[0]["start_ms"]
        if len(cur) >= 10 or span >= 4000:
            text = " ".join(x["w"] for x in cur)
            segments.append({
                "start_ms": cur[0]["start_ms"], "end_ms": cur[-1]["end_ms"],
                "text": text,
                "speaker_label": cur_spk[0],
                "is_keyword": 1 if any(x["w"].lower().strip(".,!?") in kw for x in cur) else 0,
                "word_timings": cur,
            })
            cur, cur_spk = [], []
    if cur:
        text = " ".join(x["w"] for x in cur)
        segments.append({
            "start_ms": cur[0]["start_ms"], "end_ms": cur[-1]["end_ms"], "text": text,
            "speaker_label": cur_spk[0] if cur_spk else None,
            "is_keyword": 1 if any(x["w"].lower().strip(".,!?") in kw for x in cur) else 0,
            "word_timings": cur,
        })
    return segments


def stage_detect(job: RenderJob, db: Session) -> None:
    from models import Project as P
    project = db.get(P, job.project_id)
    prefs = json.loads(project.curation_prefs or "{}")
    tpath = MEDIA / project.id / "transcript.json"
    result = json.loads(tpath.read_text())
    words = result["words"]

    run_id = uuid.uuid4().hex
    _set_progress(db, job, 20, "AI is finding the best moments")
    found = GroqClient().detect_highlights(_transcript_for_llm(words), prefs)
    if not found:
        raise RuntimeError("The AI found no usable highlights in this video.")

    # Gap 4: the ai_hook checkbox was stored but never consumed. When on, one
    # LLM call rewrites every clip title into a punchier opening hook.
    if prefs.get("ai_hook"):
        _set_progress(db, job, 45, "AI is writing opening hooks")
        try:
            hooks = GroqClient().rewrite_hooks([
                {"title": fc["title"],
                 "text": " ".join(w["w"] for w in words
                                  if int(fc["start_ms"]) <= w["start_ms"] <= int(fc["end_ms"]))}
                for fc in found
            ])
            for fc, hook in zip(found, hooks):
                if hook:
                    fc["title"] = hook
        except Exception as e:  # noqa: BLE001 — hooks are a bonus, never fail the run
            print(f"[detect] hook rewrite failed, keeping original titles: {e}", flush=True)

    # Gap 5: speaker labels. Whisper gives no diarization, so assign turns by
    # pause heuristic (see _assign_speakers) — honest, not true diarization.
    all_speakers = _assign_speakers(words)

    _set_progress(db, job, 60, f"Scoring {len(found)} clips")
    for fc in found:
        s, e = int(fc["start_ms"]), int(fc["end_ms"])
        if e <= s or s < 0:
            continue
        if (e - s) > (prefs.get("clip_length_max", 90) * 1000 + 5000):
            e = s + prefs.get("clip_length_max", 90) * 1000
        idx = [i for i, w in enumerate(words) if w["start_ms"] >= s - 400 and w["end_ms"] <= e + 400]
        clip_words = [words[i] for i in idx]
        clip_speakers = [all_speakers[i] for i in idx]
        clip = Clip(
            project_id=project.id, run_id=run_id,
            title=fc["title"], transcript_text=" ".join(w["w"] for w in clip_words),
            duration_ms=e - s, virality_score=fc["virality"],
            score_breakdown=json.dumps({"hook": fc["hook"], "flow": fc["flow"], "value": fc["value"]}),
            trim_start_ms=s, trim_end_ms=e,
        )
        db.add(clip)
        db.flush()
        for seg in _group_segments(clip_words, fc.get("keywords", []), clip_speakers):
            db.add(CaptionSegment(clip_id=clip.id, start_ms=seg["start_ms"], end_ms=seg["end_ms"],
                                 text=seg["text"], speaker_label=seg["speaker_label"],
                                 is_keyword=seg["is_keyword"],
                                 word_timings=json.dumps(seg["word_timings"])))
        db.flush()

    _set_progress(db, job, 90, "Rendering previews")
    _set_progress(db, job, 100, "Clips ready")


# ------------------------------------------------------------------ preview
def _caption_style_for(db: Session, project, clip) -> dict:
    """Merge caption style: clip render_prefs override brand template defaults."""
    from models import BrandTemplate
    style = {"uppercase": False, "emoji": False, "font_size": 64,
             "font_family": "DejaVu Sans", "font_color": "#FFFFFF",
             "keyword_color": "#0E7A64", "logo_path": None}
    if project.brand_template_id:
        tpl = db.get(BrandTemplate, project.brand_template_id)
        if tpl:
            try:
                style.update(json.loads(tpl.caption_style or "{}"))
            except Exception:
                pass
            if tpl.logo_path:
                style["logo_path"] = tpl.logo_path
    try:
        prefs = json.loads(clip.render_prefs or "{}")
        for k in ("uppercase", "emoji", "font_size", "font_family",
                  "font_color", "keyword_color"):
            if k in prefs:
                style[k] = prefs[k]
    except Exception:
        pass
    return style


def _smart_plan_for_clip(clip, project):
    """Face-tracked crop trajectory for the fill layout, or None.

    Returns (crop_w, crop_h, [(t_sec, x, y), ...]) for video.render_clip, or
    None when smart reframe is off / not applicable / anything fails — the
    caller then uses the classic centre crop. Never raises.
    """
    try:
        prefs = json.loads(project.curation_prefs or "{}")
        if not prefs.get("smart_reframe", True):
            return None
        if clip.layout != "fill":
            return None
        end_ms = clip.trim_end_ms or (clip.trim_start_ms + clip.duration_ms)
        dets = video.detect_faces_timeline(project.local_media_path,
                                           clip.trim_start_ms, end_ms)
        if not any(boxes for _, boxes in dets):
            return None  # no faces anywhere: plain centre crop
        info = video.probe(project.local_media_path)
        return video.plan_smart_crop(info["width"], info["height"], dets,
                                     t0_ms=clip.trim_start_ms)
    except Exception as e:
        print(f"[smart_reframe] falling back to centre crop: {e}")
        return None


def render_preview_for_clip(clip: Clip, project: Project, db: Session) -> None:
    cdir = RENDERS / clip.id
    cdir.mkdir(parents=True, exist_ok=True)
    segs = [
        {"start_ms": c.start_ms, "end_ms": c.end_ms, "text": c.text,
         "is_keyword": c.is_keyword, "word_timings": json.loads(c.word_timings or "[]")}
        for c in clip.captions
    ]
    # shift segments relative to the trimmed clip start
    base = clip.trim_start_ms
    for s in segs:
        s["start_ms"] -= base
        s["end_ms"] -= base
        for w in s["word_timings"]:
            w["start_ms"] -= base
            w["end_ms"] -= base
    segs = [s for s in segs if s["end_ms"] > 0 and s["start_ms"] < (clip.trim_end_ms or clip.duration_ms) - base]
    style = _caption_style_for(db, project, clip)
    ass_path = cdir / "preview.ass"
    ass_path.write_text(video.make_ass(segs, style))
    out = cdir / "preview.mp4"
    video.render_clip(project.local_media_path, clip.trim_start_ms,
                      clip.trim_end_ms or (clip.trim_start_ms + clip.duration_ms),
                      clip.layout, str(ass_path), str(out),
                      logo_path=style.get("logo_path"),
                      smart_plan=_smart_plan_for_clip(clip, project))
    clip.preview_path = str(out)
    clip.updated_at = _now()
    db.flush()


def stage_preview(job: RenderJob, db: Session) -> None:
    project = db.get(Project, job.project_id)
    clips = (db.query(Clip).filter(Clip.project_id == project.id)
             .order_by(Clip.virality_score.desc()).all())
    targets = [c for c in clips if not job.clip_id or c.id == job.clip_id]
    total = max(1, len(targets))
    for i, clip in enumerate(targets):
        _set_progress(db, job, int(i / total * 90), f"Rendering clip {i+1}/{len(targets)}")
        if not clip.preview_path or not pathlib.Path(clip.preview_path).exists():
            render_preview_for_clip(clip, project, db)
        if not clip.thumbnail_path or not pathlib.Path(clip.thumbnail_path).exists():
            cdir = RENDERS / clip.id
            tout = cdir / "thumb.jpg"
            mid = clip.trim_start_ms + min(3000, (clip.trim_end_ms or clip.duration_ms) // 3)
            video.thumbnail(project.local_media_path, mid, str(tout))
            clip.thumbnail_path = str(tout)
            db.flush()
    project.status = "ready"
    project.updated_at = _now()
    db.flush()
    _set_progress(db, job, 100, "Done")


# ------------------------------------------------------------------ render
def stage_render(job: RenderJob, db: Session) -> None:
    clip = db.get(Clip, job.clip_id)
    project = db.get(Project, clip.project_id)
    _set_progress(db, job, 10, "Rendering final 1080p clip")
    cdir = RENDERS / clip.id
    cdir.mkdir(parents=True, exist_ok=True)
    segs = [
        {"start_ms": c.start_ms, "end_ms": c.end_ms, "text": c.text,
         "is_keyword": c.is_keyword, "word_timings": json.loads(c.word_timings or "[]")}
        for c in clip.captions
    ]
    base = clip.trim_start_ms
    for s in segs:
        s["start_ms"] -= base
        s["end_ms"] -= base
        for w in s["word_timings"]:
            w["start_ms"] -= base
            w["end_ms"] -= base
    style = _caption_style_for(db, project, clip)
    ass_path = cdir / "final.ass"
    ass_path.write_text(video.make_ass(segs, style))
    out = cdir / "final.mp4"
    video.render_clip(project.local_media_path, clip.trim_start_ms,
                      clip.trim_end_ms or (clip.trim_start_ms + clip.duration_ms),
                      clip.layout, str(ass_path), str(out), width=1080, height=1920,
                      logo_path=style.get("logo_path"),
                      smart_plan=_smart_plan_for_clip(clip, project))
    clip.output_path = str(out)
    clip.status = "ready"
    clip.updated_at = _now()
    db.flush()
    _set_progress(db, job, 80, "Final clip ready")
    segs_srt = [{"start_ms": c.start_ms - clip.trim_start_ms, "end_ms": c.end_ms - clip.trim_start_ms,
                 "text": c.text} for c in clip.captions]
    video.write_srt(segs_srt, str(cdir / "captions.srt"))
    job.result_path = str(cdir / "captions.srt")
    _set_progress(db, job, 100, "Done")


# --------------------------------------------------------------- export_srt
def stage_export_srt(job: RenderJob, db: Session) -> None:
    clip = db.get(Clip, job.clip_id)
    cdir = RENDERS / clip.id
    segs = [{"start_ms": c.start_ms - clip.trim_start_ms, "end_ms": c.end_ms - clip.trim_start_ms,
             "text": c.text} for c in clip.captions]
    out = cdir / "captions.srt"
    video.write_srt(segs, str(out))
    job.result_path = str(out)
    _set_progress(db, job, 100, "SRT ready")


# --------------------------------------------------------------- thumbnail
def stage_thumbnail(job: RenderJob, db: Session) -> None:
    clip = db.get(Clip, job.clip_id)
    project = db.get(Project, clip.project_id)
    cdir = RENDERS / clip.id
    cdir.mkdir(parents=True, exist_ok=True)
    out = cdir / "thumb.jpg"
    mid = clip.trim_start_ms + min(3000, (clip.trim_end_ms or clip.duration_ms) // 3)
    video.thumbnail(project.local_media_path, mid, str(out))
    clip.thumbnail_path = str(out)
    clip.updated_at = _now()
    db.flush()
    _set_progress(db, job, 100, "Thumbnail ready")


STAGES = {
    "fetch": stage_fetch,
    "transcribe": stage_transcribe,
    "detect": stage_detect,
    "preview": stage_preview,
    "render": stage_render,
    "export_srt": stage_export_srt,
    "thumbnail": stage_thumbnail,
}

# Chain order. The schema allows only one live job per project/clip
# (UNIQUE on render_jobs.project_id / clip_id), so the worker deletes a
# finished job row before enqueueing its successor.
NEXT_STAGE = {
    "fetch": "transcribe",
    "transcribe": "detect",
    "detect": "preview",
    "preview": None,      # project pipeline complete -> project marked ready
    "render": None,       # render includes the SRT; clip marked ready
    "export_srt": None,
    "thumbnail": None,
}

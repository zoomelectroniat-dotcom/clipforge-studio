"""DB-backed job worker. Polls render_jobs, claims atomically, runs pipeline stages.

Run:  cd ~/workspace/opusclip-replica/app && ../venv/bin/python worker.py
"""
import os
import time
import traceback
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from db import SessionLocal, engine, init_db
from models import Project
from pipeline import NEXT_STAGE, STAGES, _now, enqueue

APP_URL = os.environ.get("APP_URL", "http://127.0.0.1:8901")


def _claim_one(db, worker_id: str):
    """Atomically claim the oldest queued, due job. Returns the job id or None."""
    row = db.execute(text("""
        UPDATE render_jobs
        SET status='running', worker_id=:wid, started_at=:now, updated_at=:now,
            attempts = attempts + 1
        WHERE id = (
            SELECT id FROM render_jobs
            WHERE status='queued' AND (next_retry_at IS NULL OR next_retry_at <= :now)
            ORDER BY created_at LIMIT 1
        )
        RETURNING id
    """), {"wid": worker_id, "now": _now()}).fetchone()
    db.commit()
    return row[0] if row else None


def _notify_info(db, job) -> dict | None:
    """Collect what the user should be emailed about, BEFORE the job row may
    be deleted. Returns a notify dict or None (no email for this outcome)."""
    from models import Clip, Project, User
    project = db.get(Project, job.project_id) if job.project_id else None
    user = db.get(User, project.user_id) if project else None
    if not user or not user.email:
        return None
    if job.job_type == "preview":
        # project pipeline complete (stage_preview marks project ready)
        n = db.query(Clip).filter(Clip.project_id == job.project_id).count() if job.project_id else 0
        return {"kind": "clips_ready", "to": user.email,
                "title": project.title if project else "your project",
                "n": n, "pid": job.project_id}
    if job.job_type == "render" and job.clip_id:
        clip = db.get(Clip, job.clip_id)
        return {"kind": "render_ready", "to": user.email,
                "title": clip.title if clip else "your clip", "cid": job.clip_id}
    return None


def _send_notification(notify: dict, error: str = "") -> None:
    import mailer
    kind = notify["kind"]
    if kind == "clips_ready":
        mailer.clips_ready_email(notify["to"], notify["title"], notify["n"],
                                 f"{APP_URL}/app/projects/{notify['pid']}")
    elif kind == "render_ready":
        mailer.render_ready_email(notify["to"], notify["title"],
                                  f"{APP_URL}/app/clips/{notify['cid']}/export")
    elif kind == "failed":
        mailer.render_failed_email(notify["to"], notify["title"], error,
                                   f"{APP_URL}/app")


def _finish(db, job_id: str, ok: bool, error: str = ""):
    from models import RenderJob
    job = db.get(RenderJob, job_id)
    # email decision needs the job row; gather it before any delete
    notify = _notify_info(db, job) if ok else None
    failed_notify = None
    if ok:
        # Chain to the next stage. The schema allows only one live job per
        # project/clip, so delete the finished row before enqueueing its
        # successor.
        nxt = NEXT_STAGE.get(job.job_type)
        pid, cid = job.project_id, job.clip_id
        db.delete(job)
        db.flush()
        if nxt:
            enqueue(db, nxt, project_id=pid, clip_id=cid)
        db.commit()
    else:
        if job.attempts >= job.max_attempts:
            job.status = "failed"
            job.error_message = error[:500]
            job.finished_at = _now()
            # surface failure on the project so the UI can offer Retry
            if job.project_id:
                proj = db.get(Project, job.project_id)
                if proj and proj.status == "processing":
                    proj.status = "failed"
                    proj.error_message = error[:500]
                    proj.updated_at = _now()
                    # BUG-02: refund the generation charge exactly once. The
                    # stage chain stops at the first permanent failure, and
                    # credits_charged is zeroed, so this cannot double-refund.
                    if (job.job_type in ("fetch", "transcribe", "detect", "preview")
                            and (proj.credits_charged or 0) > 0):
                        from auth import grant_credits
                        from models import User
                        u = db.get(User, proj.user_id)
                        if u is not None:
                            grant_credits(db, u, proj.credits_charged, "refund")
                        proj.credits_charged = 0
            # completion email on permanent failure (pipeline or render)
            failed_notify = _failure_notify_info(db, job)
        else:
            backoff = min(600, 15 * (2 ** (job.attempts - 1)))
            job.status = "queued"
            job.next_retry_at = (datetime.now(timezone.utc) + timedelta(seconds=backoff)).isoformat()
            job.error_message = error[:500]
    job.updated_at = _now()
    db.commit()
    # send email outside the DB transaction; mailer never raises
    if notify:
        _send_notification(notify)
    if failed_notify:
        _send_notification(failed_notify, error)


def _failure_notify_info(db, job) -> dict | None:
    from models import Clip, Project, User
    project = db.get(Project, job.project_id) if job.project_id else None
    user = db.get(User, project.user_id) if project else None
    if not user or not user.email:
        return None
    if job.clip_id:
        clip = db.get(Clip, job.clip_id)
        return {"kind": "failed", "to": user.email,
                "title": clip.title if clip else "your clip"}
    return {"kind": "failed", "to": user.email,
            "title": project.title if project else "your project"}


def run_once(worker_id: str) -> bool:
    from models import RenderJob
    db = SessionLocal()
    try:
        job_id = _claim_one(db, worker_id)
        if not job_id:
            return False
        job = db.get(RenderJob, job_id)
        stage = STAGES.get(job.job_type)
        print(f"[worker] {job.job_type} {job_id[:8]} (attempt {job.attempts})", flush=True)
        try:
            stage(job, db)
            db.commit()
            _finish(db, job_id, True)
            print(f"[worker] done {job.job_type} {job_id[:8]}", flush=True)
        except Exception as e:  # noqa: BLE001
            db.rollback()
            err = str(e)[:300]
            print(f"[worker] FAILED {job.job_type} {job_id[:8]}: {err}", flush=True)
            traceback.print_exc()
            _finish(db, job_id, False, err)
        return True
    finally:
        db.close()


def main():
    init_db()
    worker_id = uuid.uuid4().hex[:8]
    print(f"[worker] started id={worker_id}", flush=True)
    idle = 0
    while True:
        try:
            if run_once(worker_id):
                idle = 0
            else:
                idle += 1
                time.sleep(2)
        except KeyboardInterrupt:
            print("[worker] stopping", flush=True)
            break
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            time.sleep(5)


if __name__ == "__main__":
    main()

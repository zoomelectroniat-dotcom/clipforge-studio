"""Transactional email via configurable SMTP (stdlib smtplib only).

Env vars (documented in ../.env.example, never hardcoded):
  SMTP_HOST, SMTP_PORT (default 587), SMTP_USER, SMTP_PASS,
  SMTP_FROM (default SMTP_USER), SMTP_USE_TLS (default "1")

When SMTP_HOST is unset the mailer is a no-op that logs the would-be email —
the app works fully without email configured (progress bar is the fallback).
"""
import os
import smtplib
from email.message import EmailMessage


def _cfg() -> dict | None:
    host = os.environ.get("SMTP_HOST", "").strip()
    if not host:
        return None
    return {
        "host": host,
        "port": int(os.environ.get("SMTP_PORT", "587") or 587),
        "user": os.environ.get("SMTP_USER", "").strip(),
        "password": os.environ.get("SMTP_PASS", ""),
        "from": os.environ.get("SMTP_FROM", "").strip() or os.environ.get("SMTP_USER", "").strip(),
        "use_tls": os.environ.get("SMTP_USE_TLS", "1") != "0",
    }


def configured() -> bool:
    return _cfg() is not None


def send_mail(to_email: str, subject: str, body: str) -> bool:
    """Send one plain-text email. Returns True if sent (or would-be-sent in
    no-op mode). Never raises — email must not break the pipeline."""
    cfg = _cfg()
    if cfg is None:
        print(f"[mailer] no SMTP configured — would email {to_email}: {subject}", flush=True)
        return True
    try:
        msg = EmailMessage()
        msg["From"] = cfg["from"]
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.set_content(body)
        if cfg["use_tls"]:
            with smtplib.SMTP(cfg["host"], cfg["port"], timeout=30) as s:
                s.starttls()
                if cfg["user"]:
                    s.login(cfg["user"], cfg["password"])
                s.send_message(msg)
        else:
            with smtplib.SMTP_SSL(cfg["host"], cfg["port"], timeout=30) as s:
                if cfg["user"]:
                    s.login(cfg["user"], cfg["password"])
                s.send_message(msg)
        print(f"[mailer] sent to {to_email}: {subject}", flush=True)
        return True
    except Exception as e:  # noqa: BLE001
        # never let email break the worker; log and continue
        print(f"[mailer] FAILED to {to_email}: {e}", flush=True)
        return False


def clips_ready_email(to_email: str, project_title: str, n_clips: int, app_url: str) -> bool:
    return send_mail(
        to_email,
        f"Your clips are ready — {project_title}",
        f"Hi,\n\nClipForge Studio finished processing \"{project_title}\": "
        f"{n_clips} clip(s) are ready to review, edit and export.\n\n"
        f"Open them here: {app_url}\n\n— ClipForge Studio",
    )


def render_ready_email(to_email: str, clip_title: str, app_url: str) -> bool:
    return send_mail(
        to_email,
        f"Render finished — {clip_title}",
        f"Hi,\n\nYour final 1080p render of \"{clip_title}\" is ready to download.\n\n"
        f"Get it here: {app_url}\n\n— ClipForge Studio",
    )


def render_failed_email(to_email: str, what: str, error: str, app_url: str) -> bool:
    return send_mail(
        to_email,
        f"Processing failed — {what}",
        f"Hi,\n\nSomething went wrong while processing \"{what}\" in ClipForge Studio.\n"
        f"Error: {error}\n\nYou can retry from: {app_url}\n\n— ClipForge Studio",
    )

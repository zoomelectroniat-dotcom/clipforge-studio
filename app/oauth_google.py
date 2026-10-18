"""Google OAuth 2.0 (authorization-code flow) + Drive token helpers. Clean-room.

All secrets come from environment variables — nothing is hardcoded.
Used for two purposes:
  1. "Sign in with Google" (login/signup)
  2. Connecting a logged-in user's Google Drive for private file imports
Both consent to the drive.readonly scope so one flow covers both.
"""
import hashlib
import hmac
import os
import secrets
from datetime import datetime, timezone
from urllib.parse import urlencode

import httpx
from sqlalchemy.orm import Session

from auth import _secret as _cookie_secret  # HMAC key for state tokens
from db import DATA_DIR
from models import SocialAccount, User

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"

# One consent covers sign-in AND private Drive imports.
SCOPES = ["openid", "email", "profile",
          "https://www.googleapis.com/auth/drive.readonly"]

FERNET_PATH = DATA_DIR / "oauth_fernet.key"


def _env(name: str) -> str | None:
    v = (os.environ.get(name) or "").strip()
    return v or None


def client_id() -> str | None:
    return _env("GOOGLE_CLIENT_ID")


def client_secret() -> str | None:
    return _env("GOOGLE_CLIENT_SECRET")


def redirect_uri() -> str | None:
    return _env("GOOGLE_REDIRECT_URI")


def google_oauth_configured() -> bool:
    """True only when the site owner has pasted all three Google credentials."""
    return bool(client_id() and client_secret() and redirect_uri())


# ------------------------------------------------------------------ state
def new_state(purpose: str) -> str:
    """Opaque, signed state token binding the flow to a purpose."""
    raw = secrets.token_urlsafe(24)
    sig = hmac.new(_cookie_secret(), f"{purpose}:{raw}".encode(),
                   hashlib.sha256).hexdigest()[:32]
    return f"{purpose}.{raw}.{sig}"


def parse_state(state: str | None) -> str | None:
    """Return 'login' or 'drive' when the state signature is valid, else None."""
    try:
        purpose, raw, sig = (state or "").split(".")
    except ValueError:
        return None
    expected = hmac.new(_cookie_secret(), f"{purpose}:{raw}".encode(),
                        hashlib.sha256).hexdigest()[:32]
    if hmac.compare_digest(sig, expected) and purpose in ("login", "drive"):
        return purpose
    return None


# ------------------------------------------------------------------ flow
def build_authorize_url(state: str) -> str:
    q = urlencode({
        "client_id": client_id(),
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "state": state,
        "access_type": "offline",  # need a refresh token for Drive later
        "prompt": "consent",       # consent each time so Google re-issues it
        "include_granted_scopes": "true",
    })
    return f"{GOOGLE_AUTH_URL}?{q}"


class OAuthError(RuntimeError):
    """User-friendly OAuth failure — never leaks provider internals."""


def exchange_code(code: str) -> dict:
    try:
        r = httpx.post(GOOGLE_TOKEN_URL, data={
            "code": code,
            "client_id": client_id(),
            "client_secret": client_secret(),
            "redirect_uri": redirect_uri(),
            "grant_type": "authorization_code",
        }, timeout=30, trust_env=False)
    except Exception:
        raise OAuthError("Could not reach Google — check your connection and try again.")
    if r.status_code != 200:
        raise OAuthError("Google rejected the sign-in attempt. Please try again.")
    try:
        data = r.json()
    except Exception:
        raise OAuthError("Google sent an unexpected response. Please try again.")
    if "access_token" not in data:
        raise OAuthError("Google did not return a usable sign-in. Please try again.")
    return data


def fetch_userinfo(access_token: str) -> dict:
    try:
        r = httpx.get(GOOGLE_USERINFO_URL,
                      headers={"Authorization": f"Bearer {access_token}"},
                      timeout=30, trust_env=False)
    except Exception:
        raise OAuthError("Could not reach Google — check your connection and try again.")
    if r.status_code != 200:
        raise OAuthError("Could not verify your Google account. Please try again.")
    try:
        info = r.json()
    except Exception:
        raise OAuthError("Google sent an unexpected response. Please try again.")
    email = (info.get("email") or "").strip().lower()
    if not email:
        raise OAuthError("Google did not share an email address. Please try again.")
    return {"email": email, "name": (info.get("name") or "").strip()}


def refresh_access_token(refresh_token: str) -> dict:
    try:
        r = httpx.post(GOOGLE_TOKEN_URL, data={
            "refresh_token": refresh_token,
            "client_id": client_id(),
            "client_secret": client_secret(),
            "grant_type": "refresh_token",
        }, timeout=30, trust_env=False)
    except Exception:
        raise OAuthError("Could not reach Google to refresh the Drive connection.")
    if r.status_code != 200:
        raise OAuthError("The Google Drive connection expired. Please reconnect it.")
    try:
        return r.json()
    except Exception:
        raise OAuthError("Google sent an unexpected response. Please try again.")


# ------------------------------------------------------- token storage
def _fernet():
    from cryptography.fernet import Fernet
    if not FERNET_PATH.exists():
        FERNET_PATH.write_bytes(Fernet.generate_key())
        FERNET_PATH.chmod(0o600)
    return Fernet(FERNET_PATH.read_bytes())


def enc_token(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def dec_token(ciphertext: str) -> str:
    return _fernet().decrypt(ciphertext.encode()).decode()


def _now():
    return datetime.now(timezone.utc).isoformat()


def store_drive_tokens(db: Session, user: User, tokens: dict) -> None:
    """Persist (encrypted) Drive tokens for a user. Refresh token kept if not re-issued."""
    acct = db.query(SocialAccount).filter(
        SocialAccount.user_id == user.id,
        SocialAccount.platform == "google_drive").first()
    if not acct:
        acct = SocialAccount(user_id=user.id, platform="google_drive")
        db.add(acct)
    acct.access_token_enc = enc_token(tokens["access_token"])
    if tokens.get("refresh_token"):
        acct.refresh_token_enc = enc_token(tokens["refresh_token"])
    exp = tokens.get("expires_in")
    try:
        exp_iso = datetime.fromtimestamp(
            datetime.now(timezone.utc).timestamp() + int(exp),
            tz=timezone.utc).isoformat() if exp else None
    except (TypeError, ValueError):
        exp_iso = None
    acct.token_expires_at = exp_iso
    acct.oauth_status = "connected"
    acct.platform_account_name = "Google Drive"
    acct.connected_at = _now()
    db.flush()


def drive_access_token_for(db: Session, user: User) -> str | None:
    """A usable Drive access token for this user, refreshing when needed.

    Returns None when the user never connected Google Drive (or it expired
    and the refresh failed). Never raises.
    """
    try:
        acct = db.query(SocialAccount).filter(
            SocialAccount.user_id == user.id,
            SocialAccount.platform == "google_drive").first()
        if not acct or not acct.refresh_token_enc:
            return None
        data = refresh_access_token(dec_token(acct.refresh_token_enc))
        acct.access_token_enc = enc_token(data["access_token"])
        acct.oauth_status = "connected"
        acct.updated_at = _now()
        db.flush()
        return data["access_token"]
    except Exception:
        try:
            if "acct" in locals() and acct:
                acct.oauth_status = "expired"
                db.flush()
        except Exception:
            pass
        return None


def drive_connection_status(db: Session, user: User) -> str:
    """'connected' | 'expired' | 'not_connected' — for the settings page."""
    acct = db.query(SocialAccount).filter(
        SocialAccount.user_id == user.id,
        SocialAccount.platform == "google_drive").first()
    if not acct or not acct.refresh_token_enc:
        return "not_connected"
    return acct.oauth_status if acct.oauth_status in ("connected", "expired") else "expired"

"""Local email+password auth. bcrypt hashes, HMAC-signed cookie sessions (stdlib only)."""
import hashlib
import hmac
import pathlib
import secrets

import bcrypt
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from db import DATA_DIR, SessionLocal, get_db
from models import User

SECRET_PATH = DATA_DIR / "secret.key"


def _secret() -> bytes:
    if not SECRET_PATH.exists():
        SECRET_PATH.write_bytes(secrets.token_bytes(32))
        SECRET_PATH.chmod(0o600)
    return SECRET_PATH.read_bytes()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except Exception:
        return False


COOKIE_NAME = "cfs_session"


def make_session_cookie(user_id: str) -> str:
    sig = hmac.new(_secret(), user_id.encode(), hashlib.sha256).hexdigest()
    return f"{user_id}.{sig}"


def parse_session_cookie(value: str | None) -> str | None:
    if not value or "." not in value:
        return None
    user_id, sig = value.rsplit(".", 1)
    expected = hmac.new(_secret(), user_id.encode(), hashlib.sha256).hexdigest()
    if hmac.compare_digest(sig, expected):
        return user_id
    return None


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user_id = parse_session_cookie(request.cookies.get(COOKIE_NAME))
    if not user_id:
        raise HTTPException(status_code=401, detail="Not signed in")
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="Not signed in")
    return user


def get_current_user_optional(request: Request, db: Session = Depends(get_db)) -> User | None:
    try:
        return get_current_user(request, db)
    except HTTPException:
        return None


def spend_credits(db: Session, user: User, minutes: int, reason: str) -> None:
    """Charge credits in one transaction. Raises ValueError when insufficient."""
    from models import CreditLedger
    from datetime import datetime, timezone

    if minutes <= 0:
        return
    db_user = db.get(User, user.id)
    if db_user.credits_balance < minutes:
        raise ValueError("Not enough credits")
    now = datetime.now(timezone.utc).isoformat()
    db.add(CreditLedger(user_id=user.id, delta=-minutes, reason=reason, created_at=now))
    db_user.credits_balance -= minutes
    db_user.updated_at = now
    db.flush()


def grant_credits(db: Session, user: User, minutes: int, reason: str = "grant") -> None:
    from models import CreditLedger
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    db.add(CreditLedger(user_id=user.id, delta=minutes, reason=reason, created_at=now))
    db_user = db.get(User, user.id)
    db_user.credits_balance += minutes
    db_user.updated_at = now
    db.flush()

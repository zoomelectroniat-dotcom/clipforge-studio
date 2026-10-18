"""SQLite engine + session factory. Schema is created from replica/schema.sql."""
import pathlib
import sqlite3

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "clipforge_studio.db"

engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db() -> None:
    """Create all tables by executing replica/schema.sql (idempotent)."""
    con = sqlite3.connect(DB_PATH)
    try:
        exists = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='users'").fetchone()
        if not exists:
            schema = (ROOT / "replica" / "schema.sql").read_text()
            con.executescript(schema)
            con.commit()
        # App-level additive column (not in the validated schema file): stores
        # the curation prefs chosen on S06 so the worker can read them.
        try:
            con.execute("ALTER TABLE projects ADD COLUMN curation_prefs TEXT NOT NULL DEFAULT '{}'")
            con.commit()
        except Exception:
            pass  # already added
        # Webhook idempotency table for Stripe (added after the validated schema).
        try:
            con.execute("CREATE TABLE webhook_events (id TEXT PRIMARY KEY, created_at TEXT NOT NULL)")
            con.commit()
        except Exception:
            pass  # already added
    finally:
        con.close()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

"""Create the DB from replica/schema.sql and seed a demo account.

Run:  cd ~/workspace/opusclip-replica/app && ../venv/bin/python seed.py
"""
from db import SessionLocal, init_db
from models import User
from auth import hash_password, grant_credits

DEMO_EMAIL = "demo@clipforge.studio"
DEMO_PASSWORD = "clipforge-demo-123"


def main():
    init_db()
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == DEMO_EMAIL).first()
        if not user:
            user = User(email=DEMO_EMAIL, password_hash=hash_password(DEMO_PASSWORD),
                        display_name="Demo Creator")
            db.add(user)
            db.flush()
            grant_credits(db, user, 60, "grant")
            db.commit()
            print(f"demo user created: {DEMO_EMAIL} / {DEMO_PASSWORD} (60 credits)")
        else:
            print(f"demo user exists: {DEMO_EMAIL}")
    finally:
        db.close()


if __name__ == "__main__":
    main()

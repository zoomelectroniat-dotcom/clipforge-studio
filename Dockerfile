# ClipForge Studio — free-tier test deploy (Render)
# One container runs BOTH the web server and the background worker,
# because Render's free tier has no separate worker service.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# ffmpeg for video work; libgl/libglib for opencv-headless; curl for healthchecks
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        libgl1 \
        libglib2.0-0 \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv/clipforge

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code (includes templates, static, models/*.caffemodel ~11MB)
COPY app ./app
# db.py builds SQLite from replica/schema.sql at boot
COPY replica ./replica
COPY start.sh ./start.sh
RUN chmod +x ./start.sh

# Writable at runtime. Render's free disk is EPHEMERAL:
# uploads, renders and the SQLite DB reset on every restart/redeploy.
# Fine for a test deploy; production needs a persistent disk + Postgres.
RUN mkdir -p data uploads renders media

EXPOSE 8901

CMD ["./start.sh"]

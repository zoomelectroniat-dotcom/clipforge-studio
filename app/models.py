"""SQLAlchemy models mirroring replica/schema.sql (clean-room schema)."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import (JSON, Boolean, CheckConstraint, Column, DateTime, Float,
                        ForeignKey, Index, Integer, String, Text, UniqueConstraint)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


def _uuid():
    return uuid.uuid4().hex


def _now():
    return datetime.now(timezone.utc).isoformat()


class User(Base):
    __tablename__ = "users"
    id = Column(Text, primary_key=True, default=_uuid)
    email = Column(Text, unique=True, nullable=False)
    password_hash = Column(Text, nullable=False)
    display_name = Column(Text, nullable=False)
    plan_tier = Column(Text, nullable=False, default="free")
    credits_balance = Column(Integer, nullable=False, default=0)
    timezone = Column(Text, nullable=False, default="UTC")
    created_at = Column(Text, nullable=False, default=_now)
    updated_at = Column(Text, nullable=False, default=_now)

    projects = relationship("Project", back_populates="user", cascade="all, delete-orphan")
    brand_templates = relationship("BrandTemplate", back_populates="user", cascade="all, delete-orphan")


class BrandTemplate(Base):
    __tablename__ = "brand_templates"
    id = Column(Text, primary_key=True, default=_uuid)
    user_id = Column(Text, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name = Column(Text, nullable=False)
    aspect_ratio = Column(Text, nullable=False, default="9:16")
    enabled_layouts = Column(Text, nullable=False, default='["fill"]')
    caption_style = Column(Text, nullable=False, default="{}")
    logo_path = Column(Text)
    watermark_enabled = Column(Integer, nullable=False, default=0)
    is_default = Column(Integer, nullable=False, default=0)
    created_at = Column(Text, nullable=False, default=_now)
    updated_at = Column(Text, nullable=False, default=_now)

    user = relationship("User", back_populates="brand_templates")


class Project(Base):
    __tablename__ = "projects"
    id = Column(Text, primary_key=True, default=_uuid)
    user_id = Column(Text, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title = Column(Text, nullable=False)
    source_type = Column(Text, nullable=False, default="upload")
    source_url = Column(Text)
    local_media_path = Column(Text)
    duration_sec = Column(Integer)
    language = Column(Text, nullable=False, default="en")
    genre = Column(Text)
    status = Column(Text, nullable=False, default="uploading")
    credits_charged = Column(Integer, nullable=False, default=0)
    brand_template_id = Column(Text, ForeignKey("brand_templates.id", ondelete="SET NULL"))
    curation_prefs = Column(Text, nullable=False, default="{}")  # app-level prefs (not in schema.sql; stored JSON)
    error_message = Column(Text)
    created_at = Column(Text, nullable=False, default=_now)
    updated_at = Column(Text, nullable=False, default=_now)

    user = relationship("User", back_populates="projects")
    clips = relationship("Clip", back_populates="project", cascade="all, delete-orphan")


class Clip(Base):
    __tablename__ = "clips"
    id = Column(Text, primary_key=True, default=_uuid)
    project_id = Column(Text, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    run_id = Column(Text, nullable=False)
    title = Column(Text, nullable=False)
    description = Column(Text, nullable=False, default="")
    transcript_text = Column(Text, nullable=False, default="")
    duration_ms = Column(Integer, nullable=False)
    virality_score = Column(Integer)
    score_breakdown = Column(Text, nullable=False, default="{}")
    render_prefs = Column(Text, nullable=False, default="{}")
    layout = Column(Text, nullable=False, default="fill")
    trim_start_ms = Column(Integer, nullable=False, default=0)
    trim_end_ms = Column(Integer)
    preview_path = Column(Text)
    output_path = Column(Text)
    thumbnail_path = Column(Text)
    status = Column(Text, nullable=False, default="draft")
    created_at = Column(Text, nullable=False, default=_now)
    updated_at = Column(Text, nullable=False, default=_now)

    project = relationship("Project", back_populates="clips")
    captions = relationship("CaptionSegment", back_populates="clip", cascade="all, delete-orphan",
                            order_by="CaptionSegment.start_ms")


class CaptionSegment(Base):
    __tablename__ = "caption_segments"
    id = Column(Text, primary_key=True, default=_uuid)
    clip_id = Column(Text, ForeignKey("clips.id", ondelete="CASCADE"), nullable=False)
    start_ms = Column(Integer, nullable=False)
    end_ms = Column(Integer, nullable=False)
    text = Column(Text, nullable=False)
    speaker_label = Column(Text)
    is_keyword = Column(Integer, nullable=False, default=0)
    word_timings = Column(Text, nullable=False, default="[]")
    created_at = Column(Text, nullable=False, default=_now)

    clip = relationship("Clip", back_populates="captions")


class RenderJob(Base):
    __tablename__ = "render_jobs"
    id = Column(Text, primary_key=True, default=_uuid)
    project_id = Column(Text, ForeignKey("projects.id", ondelete="CASCADE"))
    clip_id = Column(Text, ForeignKey("clips.id", ondelete="CASCADE"))
    job_type = Column(Text, nullable=False)
    status = Column(Text, nullable=False, default="queued")
    stage = Column(Text)
    progress_pct = Column(Integer, nullable=False, default=0)
    attempts = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=3)
    next_retry_at = Column(Text)
    worker_id = Column(Text)
    started_at = Column(Text)
    finished_at = Column(Text)
    error_message = Column(Text)
    result_path = Column(Text)
    created_at = Column(Text, nullable=False, default=_now)
    updated_at = Column(Text, nullable=False, default=_now)


class SocialAccount(Base):
    __tablename__ = "social_accounts"
    id = Column(Text, primary_key=True, default=_uuid)
    user_id = Column(Text, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    platform = Column(Text, nullable=False)
    oauth_status = Column(Text, nullable=False, default="expired")
    access_token_enc = Column(Text)
    refresh_token_enc = Column(Text)
    token_expires_at = Column(Text)
    platform_account_name = Column(Text)
    connected_at = Column(Text)
    created_at = Column(Text, nullable=False, default=_now)
    updated_at = Column(Text, nullable=False, default=_now)


class ScheduledPost(Base):
    __tablename__ = "scheduled_posts"
    id = Column(Text, primary_key=True, default=_uuid)
    clip_id = Column(Text, ForeignKey("clips.id", ondelete="CASCADE"), nullable=False)
    social_account_id = Column(Text, ForeignKey("social_accounts.id", ondelete="CASCADE"), nullable=False)
    scheduled_at = Column(Text, nullable=False)
    caption_text = Column(Text, nullable=False, default="")
    status = Column(Text, nullable=False, default="queued")
    credit_charged = Column(Integer, nullable=False, default=0)
    posted_url = Column(Text)
    error_message = Column(Text)
    created_at = Column(Text, nullable=False, default=_now)
    updated_at = Column(Text, nullable=False, default=_now)


class WebhookEvent(Base):
    """Processed Stripe webhook event ids — retries never double-grant."""
    __tablename__ = "webhook_events"
    id = Column(Text, primary_key=True)  # Stripe event id, e.g. evt_...
    created_at = Column(Text, nullable=False, default=_now)


class CreditLedger(Base):
    __tablename__ = "credit_ledger"
    id = Column(Text, primary_key=True, default=_uuid)
    user_id = Column(Text, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    delta = Column(Integer, nullable=False)
    reason = Column(Text, nullable=False)
    expires_at = Column(Text)
    created_at = Column(Text, nullable=False, default=_now)

"""Initial schema — captures all tables present in CarVision at launch.

Revision ID: 0001
Revises:
Create Date: 2026-04-22
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── cameras ──────────────────────────────────────────────────────────────
    op.create_table(
        "cameras",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("source", sa.String(500), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=True, default=True),
        sa.Column("save_snapshot", sa.Boolean(), nullable=True, default=False),
        sa.Column("save_clip", sa.Boolean(), nullable=True, default=False),
        sa.Column("clip_seconds", sa.Integer(), nullable=True, default=10),
        sa.Column("live_view", sa.Boolean(), nullable=True, default=True),
        sa.Column("live_order", sa.Integer(), nullable=True, default=0),
        sa.Column("onvif_xaddr", sa.String(500), nullable=True),
        sa.Column("onvif_username", sa.String(200), nullable=True),
        sa.Column("onvif_password", sa.String(500), nullable=True),  # encrypted
        sa.Column("onvif_profile", sa.String(200), nullable=True),
        sa.Column("model", sa.String(200), nullable=True),
        sa.Column("detector_mode", sa.String(20), nullable=True, default="inherit"),
        sa.Column("capture_token", sa.String(200), nullable=True),
    )

    # ── allowed_plates ────────────────────────────────────────────────────────
    op.create_table(
        "allowed_plates",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("plate_text", sa.String(50), nullable=False, unique=True),
        sa.Column("label", sa.String(200), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=True, default=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )

    # ── detections ────────────────────────────────────────────────────────────
    op.create_table(
        "detections",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("camera_id", sa.Integer(), sa.ForeignKey("cameras.id"), nullable=True),
        sa.Column("plate_text", sa.String(50), nullable=True),
        sa.Column("raw_text", sa.String(200), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("image_path", sa.String(500), nullable=True),
        sa.Column("image_hash", sa.String(64), nullable=True),
        sa.Column("detected_at", sa.DateTime(), nullable=True),
        sa.Column("is_allowed", sa.Boolean(), nullable=True),
        sa.Column("detector", sa.String(20), nullable=True),
        sa.Column("debug_color_path", sa.String(500), nullable=True),
        sa.Column("debug_bw_path", sa.String(500), nullable=True),
        sa.Column("debug_gray_path", sa.String(500), nullable=True),
        sa.Column("debug_edged_path", sa.String(500), nullable=True),
        sa.Column("debug_mask_path", sa.String(500), nullable=True),
        sa.Column("feedback_sample_id", sa.Integer(), nullable=True),
        sa.Column("feedback_status", sa.String(20), nullable=True),
        sa.Column("feedback_note", sa.Text(), nullable=True),
        sa.Column("feedback_at", sa.DateTime(), nullable=True),
    )

    # ── notifications ─────────────────────────────────────────────────────────
    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("kind", sa.String(50), nullable=True),
        sa.Column("is_read", sa.Boolean(), nullable=True, default=False),
        sa.Column("read_at", sa.DateTime(), nullable=True),
        sa.Column("camera_id", sa.Integer(), nullable=True),
        sa.Column("detection_id", sa.Integer(), nullable=True),
        sa.Column("extra", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )

    # ── app_settings ──────────────────────────────────────────────────────────
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(100), primary_key=True),
        sa.Column("value", sa.Text(), nullable=True),
    )

    # ── training_samples ──────────────────────────────────────────────────────
    op.create_table(
        "training_samples",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("image_path", sa.String(500), nullable=True),
        sa.Column("image_hash", sa.String(64), nullable=True),
        sa.Column("plate_text", sa.String(50), nullable=True),
        sa.Column("bbox_x", sa.Float(), nullable=True),
        sa.Column("bbox_y", sa.Float(), nullable=True),
        sa.Column("bbox_w", sa.Float(), nullable=True),
        sa.Column("bbox_h", sa.Float(), nullable=True),
        sa.Column("no_plate", sa.Boolean(), nullable=True, default=False),
        sa.Column("unclear_plate", sa.Boolean(), nullable=True, default=False),
        sa.Column("ignored", sa.Boolean(), nullable=True, default=False),
        sa.Column("import_batch", sa.String(80), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("processed_at", sa.DateTime(), nullable=True),
        sa.Column("last_trained_at", sa.DateTime(), nullable=True),
    )

    # ── training_jobs ─────────────────────────────────────────────────────────
    op.create_table(
        "training_jobs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("status", sa.String(50), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("model_path", sa.String(500), nullable=True),
        sa.Column("log_path", sa.String(500), nullable=True),
        sa.Column("epochs", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
    )

    # ── clip_records ──────────────────────────────────────────────────────────
    op.create_table(
        "clip_records",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("camera_id", sa.Integer(), sa.ForeignKey("cameras.id"), nullable=True),
        sa.Column("clip_path", sa.String(500), nullable=True),
        sa.Column("detection_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("clip_records")
    op.drop_table("training_jobs")
    op.drop_table("training_samples")
    op.drop_table("app_settings")
    op.drop_table("notifications")
    op.drop_table("detections")
    op.drop_table("allowed_plates")
    op.drop_table("cameras")

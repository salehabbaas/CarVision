"""Add runtime_settings and model_versions tables.

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-08
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "runtime_settings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("runtime_profile", sa.String(20), nullable=False, server_default="cpu"),
        sa.Column("inference_device", sa.String(20), nullable=False, server_default="cpu"),
        sa.Column("training_device", sa.String(20), nullable=False, server_default="cpu"),
        sa.Column("model_backend", sa.String(20), nullable=False, server_default="pytorch"),
        sa.Column("target_detection_fps", sa.Float(), nullable=False, server_default="2.0"),
        sa.Column("batch_inference", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("max_live_cameras", sa.Integer(), nullable=False, server_default="8"),
        sa.Column("jpeg_quality", sa.Integer(), nullable=False, server_default="82"),
        sa.Column("plate_region", sa.String(50), nullable=False, server_default="generic"),
        sa.Column("ocr_engine", sa.String(30), nullable=False, server_default="easyocr"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
    )

    op.create_table(
        "model_versions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("path", sa.String(500), nullable=False),
        sa.Column("format", sa.String(30), nullable=False, server_default="pytorch"),
        sa.Column("profile", sa.String(20), nullable=False, server_default="cpu"),
        sa.Column("metrics", sa.JSON(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("rollback_source_id", sa.Integer(), sa.ForeignKey("model_versions.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("model_versions")
    op.drop_table("runtime_settings")

"""
db.py — database engine, session factory, and schema management.

Schema migrations are handled by Alembic (backend/migrations/).
`ensure_schema()` is kept as a compatibility shim that calls Alembic's
programmatic API so existing startup code doesn't need to change.

To generate a new migration after changing models.py:
    cd backend
    alembic revision --autogenerate -m "describe your change"

To apply pending migrations manually:
    cd backend
    alembic upgrade head
"""

import logging
import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

logger = logging.getLogger("carvision.db")

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./carvision.db")

connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ensure_schema() -> None:
    """Apply any pending Alembic migrations.

    Called once at startup from main.py.  Safe to call multiple times — Alembic
    tracks applied revisions in the `alembic_version` table and is idempotent.
    """
    try:
        from alembic import command
        from alembic.config import Config as AlembicConfig

        # Locate alembic.ini relative to this file: backend/alembic.ini
        alembic_ini = Path(__file__).resolve().parents[2] / "alembic.ini"
        if not alembic_ini.exists():
            logger.warning(
                "alembic.ini not found at %s — skipping Alembic migration. "
                "Run `alembic upgrade head` manually if schema changes are needed.",
                alembic_ini,
            )
            return

        cfg = AlembicConfig(str(alembic_ini))
        # Always use the runtime DATABASE_URL so the CLI default in alembic.ini
        # (sqlite for local dev) doesn't override the production Postgres URL.
        cfg.set_main_option("sqlalchemy.url", DATABASE_URL)

        logger.info("Running Alembic migrations (target: head)…")
        command.upgrade(cfg, "head")
        logger.info("Alembic migrations complete.")

    except Exception:
        logger.exception(
            "Alembic migration failed.  The application may still start if "
            "the schema is already up-to-date, but investigate this error."
        )

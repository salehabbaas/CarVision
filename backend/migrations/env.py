"""Alembic environment for CarVision.

Reads DATABASE_URL from the environment (same variable used by the app) so
there is a single source of truth for the connection string.  Supports both
online mode (live connection) and offline mode (SQL script generation).
"""

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# Make sure the app package is importable from this env.py
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from db import Base  # noqa: E402 — must come after sys.path update

# Alembic Config object, providing access to alembic.ini values
config = context.config

# Override sqlalchemy.url with the runtime DATABASE_URL env var (falls back to
# the alembic.ini default so `alembic` CLI works without a .env file).
database_url = os.getenv("DATABASE_URL", config.get_main_option("sqlalchemy.url"))
config.set_main_option("sqlalchemy.url", database_url)

# Set up Python logging from alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Point Alembic at all SQLAlchemy models so it can auto-generate migrations
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Generate a SQL script without connecting to the database."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Apply migrations against a live database connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

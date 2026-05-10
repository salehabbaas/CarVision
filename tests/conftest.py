import os
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend" / "app"
for p in (str(ROOT), str(BACKEND)):
    if p not in sys.path:
        sys.path.insert(0, p)

# Must be set before any app module is imported — core/config.py reads these at
# import time and calls sys.exit() if JWT_SECRET is the insecure default while
# CARVISION_STRICT_SECRETS is enabled (which it is by default).
os.environ.setdefault("JWT_SECRET", "test-only-secret-not-used-in-production-aabbccdd1122")
os.environ.setdefault("CARVISION_STRICT_SECRETS", "0")

# Import Base and get_db after sys.path and env are set up.
from db import Base, get_db  # noqa: E402
from main import create_app   # noqa: E402


@pytest.fixture(scope="session")
def test_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        future=True,
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def db_session(test_engine):
    """Provide a transactional DB session that rolls back after each test."""
    connection = test_engine.connect()
    transaction = connection.begin()
    Session = sessionmaker(bind=connection, autocommit=False, autoflush=False, future=True)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture()
def app(db_session):
    """FastAPI test app with get_db overridden to use the in-memory session."""
    application = create_app()
    application.dependency_overrides[get_db] = lambda: db_session
    yield application
    application.dependency_overrides.clear()


@pytest.fixture()
def client(app):
    from fastapi.testclient import TestClient
    return TestClient(app, raise_server_exceptions=True)

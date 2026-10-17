import os

os.environ["APP_ENV"] = "test"
os.environ["AUTH_MODE"] = "demo"
os.environ["DEMO_MODE"] = "true"
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["SEC_USER_AGENT"] = ""
os.environ["COINBASE_PERSONAL_USE_ACCEPTED"] = "false"
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app.database import Base, build_engine, get_db
from app.main import app, _request_counts
from app.seed import seed


@pytest.fixture
def db():
    engine = build_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        seed(session)
        yield session
    engine.dispose()


@pytest.fixture
def client(db):
    _request_counts.clear()
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as value:
        yield value
    app.dependency_overrides.clear()

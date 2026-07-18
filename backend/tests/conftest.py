import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


TEST_DB_PATH = Path(__file__).parent / "test.db"
TEST_IMPORT_DIR = Path(__file__).parent / "uploaded-imports"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH.as_posix()}"
os.environ["IMPORT_STORAGE_DIR"] = str(TEST_IMPORT_DIR)
os.environ["SECRET_KEY"] = "test-secret-key-with-more-than-thirty-two-characters"
os.environ["APP_ENV"] = "test"

from app.core.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.services.identity import seed_identity  # noqa: E402


@pytest.fixture(autouse=True)
def reset_database():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed_identity(db, "admin", "AdminTest123!")
    yield
    Base.metadata.drop_all(engine)
    engine.dispose()
    TEST_DB_PATH.unlink(missing_ok=True)
    if TEST_IMPORT_DIR.exists():
        for uploaded_file in TEST_IMPORT_DIR.iterdir():
            uploaded_file.unlink(missing_ok=True)
        TEST_IMPORT_DIR.rmdir()


@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def db() -> Session:
    with SessionLocal() as session:
        yield session


@pytest.fixture
def admin_token(client: TestClient) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "AdminTest123!"},
    )
    return response.json()["access_token"]

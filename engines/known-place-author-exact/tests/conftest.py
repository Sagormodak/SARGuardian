from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base, get_db
from app import job_worker
from app.main import app
from app.science.service import MockScienceService
from app.storage.fake_drive_service import FakeDriveService


# A file-backed SQLite database gives the API-request thread and background
# worker separate connections. Sharing one StaticPool in-memory connection
# across threads can interleave transactions and leave a job stuck at QUEUED.
engine = None
# Keep this factory object stable: callback tests import it directly from conftest.
TestingSessionLocal = sessionmaker(autoflush=False, autocommit=False, expire_on_commit=False)


def override_get_db():
    if TestingSessionLocal is None:
        raise RuntimeError("Test database has not been initialized")
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(autouse=True)
def reset_database(tmp_path):
    global engine

    old_executor = job_worker.executor
    old_executor.shutdown(wait=True)

    if engine is not None:
        engine.dispose()

    database_path = (tmp_path / "sarguardian-test.sqlite3").resolve()
    engine = create_engine(
        f"sqlite:///{database_path.as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 30},
        pool_pre_ping=True,
    )
    TestingSessionLocal.configure(bind=engine)
    job_worker.executor = ThreadPoolExecutor(
        max_workers=1,
        thread_name_prefix="sarguardian-test-job",
    )

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    job_worker.science_service_override = MockScienceService(
        tmp_path / "science-results"
    )
    job_worker.drive_service_override = FakeDriveService()
    job_worker.session_factory_override = TestingSessionLocal

    yield

    job_worker.executor.shutdown(wait=True)
    job_worker.science_service_override = None
    job_worker.drive_service_override = None
    job_worker.session_factory_override = None
    engine.dispose()
    engine = None


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)

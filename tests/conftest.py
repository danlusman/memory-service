from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path: Path):
    db_path = tmp_path / "test.db"
    os.environ["MEMORY_DB_PATH"] = str(db_path)
    from src.main import app

    with TestClient(app) as c:
        yield c


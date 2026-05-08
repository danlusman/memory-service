from __future__ import annotations

import importlib
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path: Path):
    db_path = tmp_path / "test.db"
    os.environ["MEMORY_DB_PATH"] = str(db_path)
    import src.main as main_module

    importlib.reload(main_module)
    with TestClient(main_module.app) as c:
        yield c


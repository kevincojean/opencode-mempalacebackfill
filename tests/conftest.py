import pytest
import tempfile
import os
import shutil
from pathlib import Path
from tests.create_fixture_db import create_fixture_db, create_multi_project_fixture_db

@pytest.fixture
def fixture_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    create_fixture_db(db_path)
    yield db_path
    if os.path.exists(db_path):
        os.remove(db_path)

@pytest.fixture
def multi_project_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    create_multi_project_fixture_db(db_path)
    yield db_path
    if os.path.exists(db_path):
        os.remove(db_path)

@pytest.fixture
def tmp_output():
    tmp_dir = tempfile.mkdtemp()
    yield tmp_dir
    shutil.rmtree(tmp_dir)

@pytest.fixture
def tmp_state():
    tmp_dir = tempfile.mkdtemp()
    state_path = os.path.join(tmp_dir, "state.json")
    yield state_path
    shutil.rmtree(tmp_dir)


@pytest.fixture
def tmp_palace_chroma(tmp_path):
    import uuid

    palace = tmp_path / f"chroma_palace_{uuid.uuid4().hex[:12]}"
    palace.mkdir(parents=True, exist_ok=True)
    yield str(palace)

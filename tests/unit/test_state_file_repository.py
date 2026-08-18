import json
from pathlib import Path

from mempalace_backfill.state.state_file_repository import (
    MineState,
    MineStateFileRepository,
)


class _StubConfigLoadService:
    """Minimal stub that returns a config dict pointing at a temp sync_state_dir."""

    def __init__(self, sync_state_dir: str):
        self._sync_state_dir = sync_state_dir

    def load_config(self, overrides=None):
        return {
            "backfill": {
                "sync_state_dir": self._sync_state_dir,
                "export_state_file": "/tmp/nonexistent.json",
                "output_dir": "/tmp/nonexistent",
            }
        }


def _make_repo(
    tmp_dir: str,
    wing: str = "test-wing",
    source_dir: str = "",
    backend: str = "",
    palace_path: str = "",
) -> MineStateFileRepository:
    """Construct a MineStateFileRepository wired to a temp sync_state_dir."""
    return MineStateFileRepository(
        config_service=_StubConfigLoadService(tmp_dir),
        wing=wing,
        source_dir=source_dir,
        backend=backend,
        palace_path=palace_path,
    )


class TestMineStateNamespace:
    """Acceptance criteria: MineState carries namespace fields (backend, palace_path_hash)."""

    def test_given_default_state_then_backend_and_palace_path_hash_are_empty(self):
        """
        GIVEN a freshly constructed MineState
        WHEN I read its backend and palace_path_hash fields
        THEN they default to "" (legacy compat).
        """
        state = MineState()
        assert state.backend == ""
        assert state.palace_path_hash == ""

    def test_given_mark_mined_then_namespace_fields_carry_forward(self):
        """
        GIVEN a MineState with backend="chroma" and palace_path_hash="abc"
        WHEN I call mark_mined
        THEN the returned MineState still has backend="chroma" and palace_path_hash="abc".
        """
        state = MineState(
            mined_files={"f.md": "h1"},
            backend="chroma",
            palace_path_hash="abc123",
        )
        new_state = state.mark_mined("g.md", "h2")
        assert new_state.backend == "chroma"
        assert new_state.palace_path_hash == "abc123"
        assert new_state.mined_files == {"f.md": "h1", "g.md": "h2"}

    def test_given_frozen_state_then_mutation_raises(self):
        """
        GIVEN a frozen MineState
        WHEN I try to set .backend directly
        THEN it raises FrozenInstanceError (frozen dataclass invariant).
        """
        import dataclasses

        state = MineState()
        try:
            state.backend = "chroma"
        except dataclasses.FrozenInstanceError:
            return
        raise AssertionError(
            "Expected MineState to be frozen (FrozenInstanceError), but assignment succeeded"
        )


class TestMineStateFileRepositoryFilename:
    """Acceptance criteria: state filename includes backend and palace_path_hash."""

    def test_given_namespace_when_state_path_then_filename_includes_backend_and_hash(
        self, tmp_path,
    ):
        """
        GIVEN a MineStateFileRepository with backend="chroma", palace_path="/palace/a"
        WHEN I read _state_path
        THEN the filename contains 'chroma', the palace_path_hash, and the wing name
        AND the file path lives under sync_state_dir.
        """
        repo = _make_repo(
            str(tmp_path),
            wing="my-wing",
            source_dir="/src",
            backend="chroma",
            palace_path="/palace/a",
        )
        path = repo._state_path()
        name = path.name
        assert path.parent == Path(str(tmp_path))
        assert "chroma" in name
        assert "my-wing" in name
        assert repo._palace_path_hash() in name
        assert repo._source_dir_hash() in name

    def test_given_no_namespace_when_state_path_then_legacy_filename(self, tmp_path):
        """
        GIVEN a MineStateFileRepository with empty backend and palace_path
        WHEN I read _state_path
        THEN the filename is the legacy pattern (no leading namespace tokens).
        """
        repo = _make_repo(str(tmp_path), wing="legacy-wing", source_dir="/src")
        name = repo._state_path().name
        assert name == "sync_state_legacy-wing_" + repo._source_dir_hash() + ".json"

    def test_given_different_backend_when_state_path_then_different_file(self, tmp_path):
        """
        GIVEN two MineStateFileRepository instances with same wing/source_dir
        BUT different backend values
        WHEN I compare their _state_path results
        THEN the filenames differ (split-brain prevention).
        """
        repo_chroma = _make_repo(
            str(tmp_path), wing="w", source_dir="/src", backend="chroma", palace_path="/p",
        )
        repo_qdrant = _make_repo(
            str(tmp_path), wing="w", source_dir="/src", backend="qdrant", palace_path="/p",
        )
        assert repo_chroma._state_path() != repo_qdrant._state_path()

    def test_given_different_palace_path_when_state_path_then_different_file(self, tmp_path):
        """
        GIVEN two MineStateFileRepository instances with same backend/wing/source_dir
        BUT different palace_path values
        WHEN I compare their _state_path results
        THEN the filenames differ (split-brain prevention across palaces).
        """
        repo_a = _make_repo(
            str(tmp_path), wing="w", source_dir="/src", backend="chroma", palace_path="/palace/a",
        )
        repo_b = _make_repo(
            str(tmp_path), wing="w", source_dir="/src", backend="chroma", palace_path="/palace/b",
        )
        assert repo_a._state_path() != repo_b._state_path()


class TestMineStateFileRepositoryLoad:
    """Acceptance criteria: load() returns Right(MineState()) on namespace mismatch."""

    def test_given_no_state_file_when_load_then_returns_fresh_state(self, tmp_path):
        """
        GIVEN no state file on disk
        WHEN I call load()
        THEN it returns Right(MineState()) with the repo's namespace fields.
        """
        repo = _make_repo(
            str(tmp_path), wing="w", source_dir="/src", backend="chroma", palace_path="/p",
        )
        result = repo.load()
        assert result.is_right()
        state = result.value
        assert state.mined_files == {}
        assert state.backend == "chroma"
        assert state.palace_path_hash == repo._palace_path_hash()

    def test_given_different_backend_when_load_then_returns_fresh_state(self, tmp_path):
        """
        GIVEN an existing state file scoped to backend="chroma" / palace="/p1"
        WHEN I load it with a repository configured for backend="qdrant" / palace="/p1"
        THEN load() returns Right(MineState()) with empty mined_files
        AND a warning is logged (no false "already mined" skip).
        """
        repo_chroma = _make_repo(
            str(tmp_path), wing="w", source_dir="/src", backend="chroma", palace_path="/p1",
        )
        chroma_state = MineState(
            mined_files={"already.md": "deadbeef"},
            backend="chroma",
            palace_path_hash=repo_chroma._palace_path_hash(),
        )
        save_result = repo_chroma.save(chroma_state)
        assert save_result.is_right()

        repo_qdrant = _make_repo(
            str(tmp_path), wing="w", source_dir="/src", backend="qdrant", palace_path="/p1",
        )
        load_result = repo_qdrant.load()
        assert load_result.is_right()
        fresh_state = load_result.value
        assert fresh_state.mined_files == {}
        assert fresh_state.backend == "qdrant"
        assert fresh_state.palace_path_hash == repo_qdrant._palace_path_hash()

    def test_given_different_palace_path_when_load_then_returns_fresh_state(self, tmp_path):
        """
        GIVEN an existing state file scoped to backend="chroma" / palace="/p1"
        WHEN I load it with a repository for backend="chroma" / palace="/p2"
        THEN load() returns Right(MineState()) with empty mined_files.
        """
        repo_p1 = _make_repo(
            str(tmp_path), wing="w", source_dir="/src", backend="chroma", palace_path="/p1",
        )
        seeded = MineState(
            mined_files={"f.md": "h"},
            backend="chroma",
            palace_path_hash=repo_p1._palace_path_hash(),
        )
        assert repo_p1.save(seeded).is_right()

        repo_p2 = _make_repo(
            str(tmp_path), wing="w", source_dir="/src", backend="chroma", palace_path="/p2",
        )
        load_result = repo_p2.load()
        assert load_result.is_right()
        assert load_result.value.mined_files == {}
        assert load_result.value.backend == "chroma"
        assert load_result.value.palace_path_hash == repo_p2._palace_path_hash()

    def test_given_matching_namespace_when_load_then_returns_stored_state(self, tmp_path):
        """
        GIVEN a state file saved with backend="chroma" / palace="/p"
        WHEN I load it with a repo configured for the SAME namespace
        THEN load() returns Right(MineState) with the stored mined_files.
        """
        repo = _make_repo(
            str(tmp_path), wing="w", source_dir="/src", backend="chroma", palace_path="/p",
        )
        seeded = MineState(
            mined_files={"f.md": "abc"},
            backend="chroma",
            palace_path_hash=repo._palace_path_hash(),
        )
        assert repo.save(seeded).is_right()

        load_result = repo.load()
        assert load_result.is_right()
        state = load_result.value
        assert state.mined_files == {"f.md": "abc"}
        assert state.backend == "chroma"

    def test_given_legacy_state_file_when_load_then_returns_fresh_state(self, tmp_path):
        """
        GIVEN a legacy-format state file (no backend / palace_path_hash fields)
        WHEN I load it with a repo configured for backend="chroma" / palace="/p"
        THEN load() returns Right(MineState()) (no false "already mined" skip).
        """
        path = Path(str(tmp_path)) / "sync_state_chroma_legacy-wing.json"
        legacy_data = {
            "mined_files": {"old.md": "hash-old"},
            "last_mined_at": "2026-01-01T00:00:00",
        }
        path.write_text(json.dumps(legacy_data))

        repo = _make_repo(
            str(tmp_path), wing="legacy-wing", source_dir="/src",
            backend="chroma", palace_path="/p",
        )
        load_result = repo.load()
        assert load_result.is_right()
        fresh = load_result.value
        assert fresh.mined_files == {}
        assert fresh.backend == "chroma"
        assert fresh.palace_path_hash == repo._palace_path_hash()
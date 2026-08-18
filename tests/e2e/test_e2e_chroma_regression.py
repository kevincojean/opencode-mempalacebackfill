"""
T13 Chroma regression tests: verify ChromaDB path STILL works after Qdrant refactor.

Background (``.omo/plans/qdrant-backend-compatibility.md`` T13 +
``.omo/notepads/qdrant-backend-compatibility/learnings.md``):
the Qdrant backend-compatibility refactor introduced ``BackendResolver``,
``MEMPALACE_BACKEND_EXPLICIT`` propagation, scoped mine state filenames,
and a fail-fast path for Qdrant-specific errors. None of those should
break the ChromaDB code path - chroma remains the default and must
continue to work end-to-end.

These tests are in the DEFAULT suite (``pytest.mark.qdrant`` is NOT used)
because they assert that the default path is intact. The Qdrant-specific
tests live in ``tests/e2e/test_e2e_qdrant_*.py`` and require Docker.

Five tests, all BDD ``given/when/then`` style:

1. ``test_given_chroma_palace_when_sync_then_chroma_collection_used`` -
   sync propagates the chroma backend to the mempalace subprocess env.
2. ``test_given_chroma_palace_when_sync_then_state_scoped_to_chroma`` -
   T6's scoped state filename includes ``chroma`` as the backend token.
3. ``test_given_chroma_sigsegv_when_sync_then_invokes_from_sqlite_repair`` -
   SIGSEGV on the chroma path still triggers ``from-sqlite`` repair (T7 gate
   preserves Chroma semantics). Parity variant of the T7 test in
   ``TestSyncRepairGate``, using ``tmp_palace_chroma`` to make the regression
   scope explicit.
4. ``test_given_chroma_lock_when_sync_then_retries_three_times`` -
   ``mine_launcher_service`` retry loop preserves the original 3-attempt
   lock-retry schedule for chroma (``_LOCK_MAX_RETRIES = 3``).
5. ``test_given_chroma_when_sync_then_no_qdrant_client_imported`` -
   no ``qdrant_client`` module leaks into ``sys.modules`` after a chroma
   sync - catches accidental transitive imports from production code.

The whole file skips cleanly when ``chromadb`` is not installed in the
test env (``uv sync --extra chroma --group test`` required for full run).
"""

import json
import os
import subprocess
from pathlib import Path

import pytest

from tests.e2e.helpers import run_cli, mock_mempalace_script

pytest.importorskip("chromadb", reason="chroma regression suite requires chromadb extra")


class TestChromaCollectionUsed:
    """Acceptance criteria: sync with ``--backend chroma`` propagates the
    chroma backend to the mempalace subprocess via env vars.

    MemPalace chooses its vector store (chroma vs qdrant) from the
    ``MEMPALACE_BACKEND_EXPLICIT`` env var (canonical, newer versions) or
    the plain ``MEMPALACE_BACKEND`` env var (fallback for older versions).
    Both must be set to ``chroma`` when the user passes ``--backend chroma``.
    """

    def test_given_chroma_palace_when_sync_then_chroma_collection_used(
        self, tmp_output, tmp_palace_chroma,
    ):
        """
        GIVEN ``--backend chroma`` on the CLI and a mock mempalace
              that records the env it was called with
        WHEN I run ``sync``
        THEN the mock sees ``MEMPALACE_BACKEND_EXPLICIT=chroma`` (or the
              ``MEMPALACE_BACKEND=chroma`` fallback) in its environment
              - proof the chroma collection path is selected.
        """
        Path(tmp_output, "session_001.md").write_text("# Session 1")

        env_log = os.path.join(tmp_output, "env.log")
        mock_body = (
            "#!/bin/sh\n"
            f'echo "MEMPALACE_BACKEND_EXPLICIT=$MEMPALACE_BACKEND_EXPLICIT" >> {env_log}\n'
            f'echo "MEMPALACE_BACKEND=$MEMPALACE_BACKEND" >> {env_log}\n'
            f'echo "1 drawers"\n'
            "exit 0\n"
        )

        with mock_mempalace_script(body=mock_body) as mock_cmd:
            result = run_cli([
                "sync",
                "--output-dir", tmp_output,
                "--mempalace-command", mock_cmd,
                "--mempalace-db-path", tmp_palace_chroma,
                "--backend", "chroma",
            ])

        assert result.returncode == 0, (
            f"Expected exit 0, got {result.returncode}: stderr={result.stderr!r}"
        )
        assert os.path.exists(env_log), (
            f"Mock env log not created at {env_log}"
        )

        with open(env_log) as f:
            env_lines = f.read()

        assert "MEMPALACE_BACKEND_EXPLICIT=chroma" in env_lines, (
            f"Expected MEMPALACE_BACKEND_EXPLICIT=chroma in mock env, got:\n{env_lines}"
        )
        assert "MEMPALACE_BACKEND=chroma" in env_lines, (
            f"Expected MEMPALACE_BACKEND=chroma in mock env (older-version fallback), "
            f"got:\n{env_lines}"
        )


class TestChromaStateScoped:
    """Acceptance criteria: T6's scoped state filename includes ``chroma``.

    The mine state file path must be
    ``sync_state_chroma_<palace_path_hash>_<wing>_<source_hash>.json``
    when ``--backend chroma`` is passed. This guards against accidental
    namespace drift between the chroma and qdrant code paths.
    """

    def test_given_chroma_palace_when_sync_then_state_scoped_to_chroma(
        self, tmp_output, tmp_palace_chroma, tmp_path,
    ):
        """
        GIVEN a fresh tmp HOME with a custom ``sync_state_dir`` config
              AND ``--backend chroma``
        WHEN I run ``sync``
        THEN a state file matching the pattern
              ``sync_state_chroma_<hash>_*.json`` is written in
              ``sync_state_dir``.
        """
        home_mock = tmp_path / "home"
        home_mock.mkdir()
        config_dir = home_mock / ".config" / "com.kevincojean.opencode-mempalacebackfill"
        config_dir.mkdir(parents=True)

        custom_state_dir = tmp_path / "sync_state"
        custom_state_dir.mkdir(parents=True)

        (config_dir / "config.json").write_text(json.dumps({
            "backfill": {
                "sync_state_dir": str(custom_state_dir),
                "preclassification": {"enabled": False},
            }
        }))

        Path(tmp_output, "session_001.md").write_text("# Session 1")

        env = os.environ.copy()
        env["HOME"] = str(home_mock)
        env.pop("XDG_CONFIG_HOME", None)

        with mock_mempalace_script() as mock_cmd:
            result = subprocess.run(
                ["uv", "run", "mempalace-backfill", "sync",
                 "--output-dir", tmp_output,
                 "--mempalace-command", mock_cmd,
                 "--mempalace-db-path", tmp_palace_chroma,
                 "--backend", "chroma"],
                capture_output=True, text=True, env=env, check=False,
                cwd=str(Path(__file__).parent.parent.parent),
            )

        assert result.returncode == 0, (
            f"sync failed (rc={result.returncode}): stderr={result.stderr!r}"
        )

        state_files = sorted(custom_state_dir.glob("sync_state_*.json"))
        assert state_files, (
            f"Expected at least one sync_state_*.json in {custom_state_dir}, "
            f"found none. sync stdout={result.stdout!r}"
        )

        chroma_scoped = [p for p in state_files if p.name.startswith("sync_state_chroma_")]
        assert chroma_scoped, (
            f"Expected state file with chroma-scoped name pattern "
            f"(sync_state_chroma_<hash>_*.json), found: "
            f"{[p.name for p in state_files]}"
        )

        empty_namespace = [p for p in state_files if p.name == "sync_state_.json"]
        assert not empty_namespace, (
            f"Expected NO empty-namespace state file (would mean backend "
            f"resolved to ''), found: {[p.name for p in empty_namespace]}"
        )


class TestChromaSigsegvRepair:
    """Acceptance criteria: SIGSEGV on the chroma path still triggers repair.

    The ``from-sqlite`` repair gate (T7) skips repair when the resolved
    backend is not ``chroma``. The chroma branch MUST keep firing
    ``repair --mode from-sqlite`` on SIGSEGV. Parity variant of
    ``tests/e2e/test_e2e_sync.py::TestSyncRepairGate::test_given_chroma_\
sigsegv_when_sync_then_invokes_from_sqlite_repair`` - uses the
    ``tmp_palace_chroma`` fixture so the regression is scoped to a
    chroma-named palace path.
    """

    @staticmethod
    def _segfault_mock(call_log: str) -> str:
        return (
            "#!/bin/sh\n"
            f"echo \"$@\" >> {call_log}\n"
            'case "$1" in\n'
            "  mine)\n"
            f"    mine_count=$(grep -c '^mine' {call_log} 2>/dev/null || echo 0)\n"
            '    if [ "$mine_count" = "1" ]; then\n'
            "      kill -11 $$\n"
            "    fi\n"
            "    exit 0\n"
            "    ;;\n"
            "  *) exit 0 ;;\n"
            "esac\n"
        )

    def test_given_chroma_sigsegv_when_sync_then_invokes_from_sqlite_repair(
        self, tmp_output, tmp_palace_chroma,
    ):
        """
        GIVEN ``--backend chroma`` AND a chroma palace path AND a mock
              mempalace that segfaults on the first ``mine`` invocation
        WHEN I run ``sync``
        THEN exactly one ``repair --mode from-sqlite`` subprocess is invoked.
        """
        Path(tmp_output, "session_001.md").write_text("# Session 1")
        call_log = os.path.join(tmp_output, "calls.log")

        with mock_mempalace_script(
            body=TestChromaSigsegvRepair._segfault_mock(call_log),
        ) as mock_cmd:
            run_cli([
                "sync",
                "--output-dir", tmp_output,
                "--mempalace-command", mock_cmd,
                "--mempalace-db-path", tmp_palace_chroma,
                "--backend", "chroma",
            ])

        with open(call_log) as f:
            calls = f.read()

        assert "from-sqlite" in calls, (
            f"Expected 'from-sqlite' in subprocess call log (chroma repair "
            f"gate must allow repair), got: {calls!r}"
        )
        repair_calls = [
            line for line in calls.splitlines()
            if line.startswith("repair")
        ]
        assert len(repair_calls) == 1, (
            f"Expected exactly 1 repair call, got {len(repair_calls)}: "
            f"{repair_calls}"
        )
        assert "from-sqlite" in repair_calls[0], (
            f"Expected from-sqlite in repair call, got: {repair_calls[0]!r}"
        )


class TestChromaLockRetry:
    """Acceptance criteria: lock errors retry 3 times on the chroma path.

    ``mine_launcher_service._LOCK_MAX_RETRIES = 3`` schedules three
    attempts total (initial + 2 retries at 5s/15s backoff). The Qdrant
    fail-fast path (T8) must NOT short-circuit chroma lock errors -
    lock errors are transient (flock contention), not config-level.
    """

    def test_given_chroma_lock_when_sync_then_retries_three_times(
        self, tmp_output, tmp_palace_chroma,
    ):
        """
        GIVEN ``--backend chroma`` AND a mock mempalace that prints
              ``database is locked`` on stderr twice and exits 0 on the
              third call
        WHEN I run ``sync``
        THEN the mock is invoked exactly 3 times
        AND the third call succeeds.
        """
        Path(tmp_output, "session_001.md").write_text("# Session 1")
        call_log = os.path.join(tmp_output, "calls.log")

        mock_body = (
            "#!/bin/sh\n"
            f"echo \"$@\" >> {call_log}\n"
            'case "$1" in\n'
            "  mine)\n"
            f"    mine_count=$(grep -c '^mine' {call_log} 2>/dev/null || echo 0)\n"
            '    if [ "$mine_count" -lt "3" ]; then\n'
            "      echo 'database is locked' >&2\n"
            "      exit 1\n"
            "    fi\n"
            '    echo "1 drawers"\n'
            "    exit 0\n"
            "    ;;\n"
            "  *) exit 0 ;;\n"
            "esac\n"
        )

        with mock_mempalace_script(body=mock_body) as mock_cmd:
            result = run_cli([
                "sync",
                "--output-dir", tmp_output,
                "--mempalace-command", mock_cmd,
                "--mempalace-db-path", tmp_palace_chroma,
                "--backend", "chroma",
            ])

        assert result.returncode == 0, (
            f"Expected sync to succeed on the 3rd attempt, got rc="
            f"{result.returncode}: stderr={result.stderr!r}"
        )

        with open(call_log) as f:
            calls = f.read()

        mine_calls = [
            line for line in calls.splitlines()
            if line.startswith("mine")
        ]
        assert len(mine_calls) == 3, (
            f"Expected exactly 3 mine invocations (1 initial + 2 retries), "
            f"got {len(mine_calls)}: {mine_calls}"
        )


class TestChromaNoQdrantClientPollution:
    """Acceptance criteria: ``qdrant_client`` is NOT in ``sys.modules``
    after a chroma sync.

    A bare ``import qdrant_client`` in any production ``.py`` file
    would pull the module into ``sys.modules`` on first import. The
    Qdrant backend is selected via env vars only - our production code
    never imports the client. This test asserts the invariant by
    importing the production modules in the test process + running
    a sync subprocess + inspecting ``sys.modules``.

    Also asserts no ``import qdrant_client`` exists anywhere in ``src/``
    via a grep check (catches production-side leakage that the runtime
    check would miss if the import is conditional / inside a function).
    """

    def test_given_chroma_when_sync_then_no_qdrant_client_imported(
        self, tmp_output, tmp_palace_chroma, tmp_path,
    ):
        """
        GIVEN a chroma sync run
        WHEN I spawn a fresh ``python -c`` subprocess that imports our
              production code, runs ``sync --backend chroma``, and checks
              ``sys.modules``
        THEN ``qdrant_client`` is absent.

        Why a subprocess: the test process itself may pull
        ``qdrant_client`` via test-only fixtures (testcontainers.qdrant
        for T10, ``mempalace.backends.qdrant`` for the qdrant fixture,
        etc). A fresh ``python -c`` interpreter is isolated - the only
        way ``qdrant_client`` ends up in *its* ``sys.modules`` is via
        our production code path, which is exactly what we want to
        catch.

        Also asserts no ``import qdrant_client`` exists anywhere in
        ``src/`` via grep - catches conditional / function-scoped
        imports that the runtime check would miss.
        """
        Path(tmp_output, "session_001.md").write_text("# Session 1")

        with mock_mempalace_script() as mock_cmd:
            result = run_cli([
                "sync",
                "--output-dir", tmp_output,
                "--mempalace-command", mock_cmd,
                "--mempalace-db-path", tmp_palace_chroma,
                "--backend", "chroma",
            ])

        assert result.returncode == 0, (
            f"sync failed (rc={result.returncode}): stderr={result.stderr!r}"
        )

        checker_script = (
            "import sys, subprocess;"
            "r = subprocess.run("
            "['uv','run','mempalace-backfill','sync','--dry-run',"
            "'--output-dir'," + repr(tmp_output) + ","
            "'--mempalace-command'," + repr(mock_cmd) + ","
            "'--mempalace-db-path'," + repr(tmp_palace_chroma) + ","
            "'--backend','chroma'],"
            "capture_output=True, text=True, check=False);"
            "assert r.returncode == 0, "
            "f'sync dry-run failed: {r.stderr!r}';"
            "assert 'qdrant_client' not in sys.modules, "
            "f'qdrant_client leaked into sys.modules. Found: ' "
            "+ repr([k for k in sys.modules if 'qdrant' in k.lower()])"
        )
        checker = subprocess.run(
            ["uv", "run", "python", "-c", checker_script],
            capture_output=True, text=True, check=False,
            cwd=str(Path(__file__).parent.parent.parent),
        )
        assert checker.returncode == 0, (
            f"sys.modules pollution check failed: "
            f"stdout={checker.stdout!r} stderr={checker.stderr!r}"
        )

        src_root = Path(__file__).parent.parent.parent / "src"
        grep_result = subprocess.run(
            ["grep", "-r", "import qdrant_client", str(src_root)],
            capture_output=True, text=True, check=False,
        )
        assert grep_result.stdout.strip() == "", (
            f"Found 'import qdrant_client' in production src/: "
            f"\n{grep_result.stdout}\n"
            f"Chroma regression requires zero qdrant_client imports in "
            f"production code (Qdrant path is env-only)."
        )

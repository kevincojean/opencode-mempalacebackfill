"""
T11 QA: verify the MemPalace backend precedence matrix end-to-end through
``mempalace-backfill sync``.

Precedence under test (MemPalace RFC 001 §3.3, delegated to
``mempalace.palace.resolve_backend_name`` via ``BackendResolver``):

    1. Explicit override (caller's ``override`` argument, i.e. CLI ``--backend``)
    2. Per-palace config value (``~/.mempalace/config.json`` backend field,
       matched against the current ``palace_path``)
    3. ``MEMPALACE_BACKEND`` env var (global)
    4. On-disk artifact auto-detection (migration only)
    5. Default: ``chroma``

These tests exercise the FULL chain - CLI edge -> sync flow -> BackendResolver
-> ``resolve_backend_name`` -> ``MEMPALACE_BACKEND_EXPLICIT`` /
``MEMPALACE_BACKEND`` propagation into the ``mempalace`` subprocess.
The mock script records the env vars it sees, so assertions are made
against the actual subprocess env rather than the in-process resolver
return value (the subprocess env is the user-observable behaviour).

Background (see ``.omo/plans/qdrant-backend-compatibility.md`` T11):
these tests run in the DEFAULT suite (``--strict-markers``), NOT under
``@pytest.mark.qdrant`` - they need no Docker / Qdrant container, only
the in-process MemPalace resolver and the mock CLI target.

Layer-2 contract: the CLI edge (``_validate_backend_cli``) rejects any
value outside ``{chroma, qdrant}`` with ``typer.BadParameter`` (exit
code 2). Test 5 verifies that rejection without ever spawning a
subprocess.
"""

import json
import os
import subprocess
from pathlib import Path

from tests.e2e.helpers import mock_mempalace_script


_PROJECT_ROOT = Path(__file__).parent.parent.parent


def _write_config(home: Path, palace_path: str, backend: str) -> None:
    """Drop a ``~/.mempalace/config.json`` with the given per-palace backend.

    ``home`` is a temp directory used as ``$HOME``; mempalace reads
    ``$HOME/.mempalace/config.json`` to discover the per-palace config.
    The ``palace_path`` field is what triggers the per-palace match in
    :func:`mempalace.palace._config_backend_value` (and thus
    :func:`mempalace.palace.resolve_backend_name`).
    """
    config_dir = home / ".mempalace"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config.json").write_text(json.dumps({
        "palace_path": palace_path,
        "backend": backend,
    }))


def _run_sync(
    args: list[str],
    home: Path,
    output_dir: str,
    mempalace_cmd: str,
) -> subprocess.CompletedProcess[str]:
    """Invoke ``mempalace-backfill sync`` with a controlled ``$HOME``.

    We invoke ``uv run`` directly (rather than ``tests.e2e.helpers.run_cli``)
    because ``run_cli`` inherits the test process's ``$HOME``, and we need
    the subprocess to see our overridden ``$HOME`` for the per-palace
    config tests. ``XDG_CONFIG_HOME`` is unset so mempalace falls back
    to ``$HOME/.mempalace`` rather than ``$XDG_CONFIG_HOME/.mempalace``.
    """
    env = os.environ.copy()
    env["HOME"] = str(home)
    env.pop("XDG_CONFIG_HOME", None)
    return subprocess.run(
        ["uv", "run", "mempalace-backfill", "sync"] + args,
        capture_output=True, text=True, env=env, check=False,
        cwd=str(_PROJECT_ROOT),
    )


class TestBackendResolutionAutoDetect:
    """When neither --backend nor ``~/.mempalace/config.json`` specifies a
    backend, the subprocess receives the default ``chroma`` env vars.
    """

    def test_given_no_env_when_sync_then_autodetect_chroma(
        self, tmp_output, tmp_path,
    ):
        """
        GIVEN no --backend flag, no ``MEMPALACE_BACKEND`` env, no per-palace
              config, and a single markdown file to sync
        WHEN I run ``mempalace-backfill sync`` against a mock mempalace
        THEN the mock sees ``MEMPALACE_BACKEND_EXPLICIT=chroma`` and
              ``MEMPALACE_BACKEND=chroma`` - the default branch of the
              precedence matrix wins.
        """
        Path(tmp_output, "session_001.md").write_text("# Session 1")

        home = tmp_path / "home"
        home.mkdir()
        # Defensive: ensure no stale config leaks from the test runner's HOME.
        (home / ".mempalace").mkdir(exist_ok=True)
        (home / ".mempalace" / "config.json").write_text("{}")

        env_log = home / "env.log"
        mock_body = (
            "#!/bin/sh\n"
            f'echo "EXPLICIT=$MEMPALACE_BACKEND_EXPLICIT" >> {env_log}\n'
            f'echo "BACKEND=$MEMPALACE_BACKEND" >> {env_log}\n'
            f'echo "ARGV=$@" >> {env_log}\n'
            'echo "0 drawers"\n'
            "exit 0\n"
        )

        with mock_mempalace_script(body=mock_body) as mock_cmd:
            result = _run_sync(
                ["--output-dir", tmp_output, "--mempalace-command", mock_cmd],
                home, tmp_output, mock_cmd,
            )

        assert result.returncode == 0, (
            f"sync failed (rc={result.returncode}):\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        env_lines = env_log.read_text().splitlines()
        env_map = dict(line.split("=", 1) for line in env_lines if "=" in line)
        assert env_map.get("EXPLICIT") == "chroma", (
            f"Default branch should propagate MEMPALACE_BACKEND_EXPLICIT=chroma "
            f"to subprocess, got env_map={env_map!r}"
        )
        assert env_map.get("BACKEND") == "chroma", (
            f"Default branch should propagate MEMPALACE_BACKEND=chroma "
            f"to subprocess, got env_map={env_map!r}"
        )


class TestBackendResolutionConfig:
    """The per-palace config in ``~/.mempalace/config.json`` wins when its
    ``palace_path`` matches the current sync target.
    """

    def test_given_chroma_config_when_sync_then_autodetect_chroma(
        self, tmp_output, tmp_path,
    ):
        """
        GIVEN ``~/.mempalace/config.json`` declares ``backend: chroma`` for
              the current palace_path
        WHEN I run ``mempalace-backfill sync`` (no --backend flag)
        THEN the mock sees ``MEMPALACE_BACKEND_EXPLICIT=chroma`` -
              config-based detection of chroma is propagated.

        ``--mempalace-db-path`` is set so the resolver's palace_path
        matches the config's ``palace_path``; without it the default
        fallback ``$HOME/.mempalace/palace`` would skip the per-palace
        match. (Chroma matches the default, so this test would
        incidentally pass without the flag - the explicit flag makes
        the per-palace config layer the actual source of the value.)
        """
        Path(tmp_output, "session_001.md").write_text("# Session 1")

        home = tmp_path / "home"
        home.mkdir()
        _write_config(home, palace_path=tmp_output, backend="chroma")

        env_log = home / "env.log"
        mock_body = (
            "#!/bin/sh\n"
            f'echo "EXPLICIT=$MEMPALACE_BACKEND_EXPLICIT" >> {env_log}\n'
            f'echo "BACKEND=$MEMPALACE_BACKEND" >> {env_log}\n'
            'echo "0 drawers"\n'
            "exit 0\n"
        )

        with mock_mempalace_script(body=mock_body) as mock_cmd:
            result = _run_sync(
                ["--output-dir", tmp_output,
                 "--mempalace-db-path", tmp_output,
                 "--mempalace-command", mock_cmd],
                home, tmp_output, mock_cmd,
            )

        assert result.returncode == 0, (
            f"sync failed (rc={result.returncode}):\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        env_lines = env_log.read_text().splitlines()
        env_map = dict(line.split("=", 1) for line in env_lines if "=" in line)
        assert env_map.get("EXPLICIT") == "chroma", (
            f"Config (chroma) should win over default, got env_map={env_map!r}"
        )

    def test_given_qdrant_config_when_sync_then_autodetect_qdrant(
        self, tmp_output, tmp_path,
    ):
        """
        GIVEN ``~/.mempalace/config.json`` declares ``backend: qdrant`` for
              the current palace_path
        WHEN I run ``mempalace-backfill sync`` (no --backend flag)
        THEN the mock sees ``MEMPALACE_BACKEND_EXPLICIT=qdrant`` -
              config-based detection of qdrant is propagated to the
              subprocess without an explicit ``--backend`` flag.

        ``--mempalace-db-path`` is set so the resolver's palace_path
        matches the config's ``palace_path`` (the default fallback is
        ``$HOME/.mempalace/palace``, which would NOT match and bypass
        the per-palace config layer).
        """
        Path(tmp_output, "session_001.md").write_text("# Session 1")

        home = tmp_path / "home"
        home.mkdir()
        _write_config(home, palace_path=tmp_output, backend="qdrant")

        env_log = home / "env.log"
        mock_body = (
            "#!/bin/sh\n"
            f'echo "EXPLICIT=$MEMPALACE_BACKEND_EXPLICIT" >> {env_log}\n'
            f'echo "BACKEND=$MEMPALACE_BACKEND" >> {env_log}\n'
            'echo "0 drawers"\n'
            "exit 0\n"
        )

        with mock_mempalace_script(body=mock_body) as mock_cmd:
            result = _run_sync(
                ["--output-dir", tmp_output,
                 "--mempalace-db-path", tmp_output,
                 "--mempalace-command", mock_cmd],
                home, tmp_output, mock_cmd,
            )

        assert result.returncode == 0, (
            f"sync failed (rc={result.returncode}):\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        env_lines = env_log.read_text().splitlines()
        env_map = dict(line.split("=", 1) for line in env_lines if "=" in line)
        assert env_map.get("EXPLICIT") == "qdrant", (
            f"Config (qdrant) should win over default, got env_map={env_map!r}"
        )


class TestBackendResolutionOverride:
    """The ``--backend`` flag outranks per-palace config (rule 1 > rule 2).
    Invalid values are rejected at the CLI edge with no subprocess spawned.
    """

    def test_given_overriding_backend_flag_when_sync_then_overrides_config(
        self, tmp_output, tmp_path,
    ):
        """
        GIVEN config declares ``backend: chroma`` for the current palace_path
              AND I pass ``--backend qdrant`` on the CLI
        WHEN I run ``mempalace-backfill sync``
        THEN the mock sees ``MEMPALACE_BACKEND_EXPLICIT=qdrant`` -
              explicit override wins over per-palace config per RFC 001 §3.3.
        """
        Path(tmp_output, "session_001.md").write_text("# Session 1")

        home = tmp_path / "home"
        home.mkdir()
        _write_config(home, palace_path=tmp_output, backend="chroma")

        env_log = home / "env.log"
        mock_body = (
            "#!/bin/sh\n"
            f'echo "EXPLICIT=$MEMPALACE_BACKEND_EXPLICIT" >> {env_log}\n'
            f'echo "BACKEND=$MEMPALACE_BACKEND" >> {env_log}\n'
            'echo "0 drawers"\n'
            "exit 0\n"
        )

        with mock_mempalace_script(body=mock_body) as mock_cmd:
            result = _run_sync(
                ["--output-dir", tmp_output,
                 "--mempalace-command", mock_cmd,
                 "--backend", "qdrant"],
                home, tmp_output, mock_cmd,
            )

        assert result.returncode == 0, (
            f"sync failed (rc={result.returncode}):\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        env_lines = env_log.read_text().splitlines()
        env_map = dict(line.split("=", 1) for line in env_lines if "=" in line)
        assert env_map.get("EXPLICIT") == "qdrant", (
            f"Explicit --backend=qdrant should override config (chroma); "
            f"got env_map={env_map!r}"
        )

    def test_given_invalid_backend_when_sync_then_rejected_at_cli_edge(
        self, tmp_output, tmp_path,
    ):
        """
        GIVEN I pass ``--backend milvus`` (unsupported)
        WHEN I run ``mempalace-backfill sync``
        THEN ``typer.BadParameter`` is raised at the CLI edge,
              ``result.returncode != 0`` (Typer convention: exit 2),
              and the subprocess is NEVER spawned (mock log stays empty).
        """
        Path(tmp_output, "session_001.md").write_text("# Session 1")

        home = tmp_path / "home"
        home.mkdir()

        env_log = home / "env.log"
        mock_body = (
            "#!/bin/sh\n"
            f'echo "SPAWNED" >> {env_log}\n'
            f'echo "EXPLICIT=$MEMPALACE_BACKEND_EXPLICIT" >> {env_log}\n'
            'echo "0 drawers"\n'
            "exit 0\n"
        )

        with mock_mempalace_script(body=mock_body) as mock_cmd:
            result = _run_sync(
                ["--output-dir", tmp_output,
                 "--mempalace-command", mock_cmd,
                 "--backend", "milvus"],
                home, tmp_output, mock_cmd,
            )

        assert result.returncode != 0, (
            f"Expected non-zero exit code for invalid --backend, got 0.\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        # Typer exits with 2 for usage errors; do not over-specify the code.
        assert result.returncode == 2, (
            f"Expected typer exit code 2 for BadParameter, got "
            f"{result.returncode}.\nstdout={result.stdout!r}\n"
            f"stderr={result.stderr!r}"
        )
        assert "milvus" in (result.stdout + result.stderr).lower(), (
            f"Expected 'milvus' in error output, got stdout={result.stdout!r} "
            f"stderr={result.stderr!r}"
        )
        assert "chroma" in (result.stdout + result.stderr).lower(), (
            f"Expected the allowed-values hint (chroma) in error output, got "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        # The mock must NOT have been spawned - validation happens before
        # any subprocess work.
        if env_log.exists():
            log_contents = env_log.read_text()
            assert "SPAWNED" not in log_contents, (
                f"Mock subprocess should NOT have been spawned for invalid "
                f"--backend; env.log={log_contents!r}"
            )


class TestBackendResolutionConfigVsEnv:
    """When per-palace config and ``MEMPALACE_BACKEND`` env both apply,
    the per-palace config wins ONLY when the palace_path matches.

    Mempalace's ``_config_backend_value`` returns None when the
    config's ``palace_path`` differs from the target ``palace_path``
    (a palace only honours its own config block). In that case the env
    var is the next-highest precedence layer.
    """

    def test_given_matching_palace_path_when_sync_then_config_beats_env(
        self, tmp_output, tmp_path, monkeypatch,
    ):
        """
        GIVEN ``~/.mempalace/config.json`` declares ``backend: chroma`` for
              the current palace_path (per-palace match)
              AND ``MEMPALACE_BACKEND=qdrant`` is set in the parent env
        WHEN I run ``mempalace-backfill sync`` (no --backend flag)
        THEN the mock sees ``MEMPALACE_BACKEND_EXPLICIT=chroma`` -
              per-palace config (rule 2) outranks the env var (rule 3).

        ``--mempalace-db-path`` is set so the resolver's palace_path
        matches the config's ``palace_path`` (without it the default
        fallback ``$HOME/.mempalace/palace`` would bypass the per-palace
        match).
        """
        Path(tmp_output, "session_001.md").write_text("# Session 1")

        home = tmp_path / "home"
        home.mkdir()
        _write_config(home, palace_path=tmp_output, backend="chroma")

        # monkeypatch is used to scope the env mutation to this test only.
        monkeypatch.setenv("MEMPALACE_BACKEND", "qdrant")

        env_log = home / "env.log"
        mock_body = (
            "#!/bin/sh\n"
            f'echo "EXPLICIT=$MEMPALACE_BACKEND_EXPLICIT" >> {env_log}\n'
            f'echo "BACKEND=$MEMPALACE_BACKEND" >> {env_log}\n'
            'echo "0 drawers"\n'
            "exit 0\n"
        )

        with mock_mempalace_script(body=mock_body) as mock_cmd:
            result = _run_sync(
                ["--output-dir", tmp_output,
                 "--mempalace-db-path", tmp_output,
                 "--mempalace-command", mock_cmd],
                home, tmp_output, mock_cmd,
            )

        assert result.returncode == 0, (
            f"sync failed (rc={result.returncode}):\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        env_lines = env_log.read_text().splitlines()
        env_map = dict(line.split("=", 1) for line in env_lines if "=" in line)
        assert env_map.get("EXPLICIT") == "chroma", (
            f"Per-palace config (chroma) should outrank MEMPALACE_BACKEND "
            f"env (qdrant) for the matching palace_path. "
            f"Got env_map={env_map!r}"
        )

    def test_given_mismatched_palace_path_when_sync_then_env_beats_config(
        self, tmp_output, tmp_path, monkeypatch,
    ):
        """
        GIVEN ``~/.mempalace/config.json`` declares ``backend: chroma`` for
              a DIFFERENT palace_path than the one we sync against
              AND ``MEMPALACE_BACKEND=qdrant`` is set in the parent env
        WHEN I run ``mempalace-backfill sync`` (no --backend flag)
        THEN the mock sees ``MEMPALACE_BACKEND_EXPLICIT=qdrant`` -
              per-palace config is scoped (does NOT apply to other
              palaces) so the env var (rule 3) wins for this palace.
        """
        Path(tmp_output, "session_001.md").write_text("# Session 1")

        home = tmp_path / "home"
        home.mkdir()
        # Config points at a DIFFERENT path than tmp_output, so the
        # per-palace match in ``_config_backend_value`` returns None and
        # the env var takes over.
        _write_config(home, palace_path="/some/other/palace", backend="chroma")

        monkeypatch.setenv("MEMPALACE_BACKEND", "qdrant")

        env_log = home / "env.log"
        mock_body = (
            "#!/bin/sh\n"
            f'echo "EXPLICIT=$MEMPALACE_BACKEND_EXPLICIT" >> {env_log}\n'
            f'echo "BACKEND=$MEMPALACE_BACKEND" >> {env_log}\n'
            'echo "0 drawers"\n'
            "exit 0\n"
        )

        with mock_mempalace_script(body=mock_body) as mock_cmd:
            result = _run_sync(
                ["--output-dir", tmp_output, "--mempalace-command", mock_cmd],
                home, tmp_output, mock_cmd,
            )

        assert result.returncode == 0, (
            f"sync failed (rc={result.returncode}):\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        env_lines = env_log.read_text().splitlines()
        env_map = dict(line.split("=", 1) for line in env_lines if "=" in line)
        assert env_map.get("EXPLICIT") == "qdrant", (
            f"Per-palace config (chroma) should NOT apply to a different "
            f"palace_path; MEMPALACE_BACKEND env (qdrant) should win. "
            f"Got env_map={env_map!r}"
        )


class TestBackendResolutionFallback:
    """When no override, no config match, and no env, the resolver falls
    back to the ``chroma`` default - even when the palace directory is
    missing on disk.
    """

    def test_given_missing_palace_dir_when_sync_then_falls_back_to_default(
        self, tmp_output, tmp_path,
    ):
        """
        GIVEN no --backend flag, no per-palace config, no MEMPALACE_BACKEND
              env, AND the configured palace_path does not exist on disk
        WHEN I run ``mempalace-backfill sync``
        THEN the mock sees ``MEMPALACE_BACKEND_EXPLICIT=chroma`` -
              the precedence matrix's default branch (rule 5) kicks in
              when rules 1-4 are all empty / non-applicable.
        """
        Path(tmp_output, "session_001.md").write_text("# Session 1")

        home = tmp_path / "home"
        home.mkdir()
        # No config written at all - empty HOME/.mempalace means the
        # per-palace config layer returns None.
        (home / ".mempalace").mkdir(exist_ok=True)

        # Palace path that does NOT exist on disk - this triggers the
        # default branch (rule 5) instead of artifact auto-detection
        # (rule 4) which only fires when matching backend artifacts are
        # already present.
        missing_palace = tmp_path / "no_such_palace_dir"

        env_log = home / "env.log"
        mock_body = (
            "#!/bin/sh\n"
            f'echo "EXPLICIT=$MEMPALACE_BACKEND_EXPLICIT" >> {env_log}\n'
            f'echo "BACKEND=$MEMPALACE_BACKEND" >> {env_log}\n'
            'echo "0 drawers"\n'
            "exit 0\n"
        )

        with mock_mempalace_script(body=mock_body) as mock_cmd:
            result = _run_sync(
                ["--output-dir", tmp_output,
                 "--mempalace-command", mock_cmd,
                 "--mempalace-db-path", str(missing_palace)],
                home, tmp_output, mock_cmd,
            )

        assert result.returncode == 0, (
            f"sync failed (rc={result.returncode}):\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        env_lines = env_log.read_text().splitlines()
        env_map = dict(line.split("=", 1) for line in env_lines if "=" in line)
        assert env_map.get("EXPLICIT") == "chroma", (
            f"Missing-palace-dir scenario should fall back to chroma default, "
            f"got env_map={env_map!r}"
        )

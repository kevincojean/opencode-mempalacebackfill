import os
import stat
import tempfile
from pathlib import Path

from tests.e2e.helpers import run_cli, mock_mempalace_script


def _create_wing_dirs(base: str, structure: dict[str, list[str]]) -> None:
    """Create a wing subdirectory structure for testing.

    ``structure`` maps wing names to lists of session file basenames (without .md).
    Files are created with minimal valid content.
    """
    for wing, sessions in structure.items():
        wing_dir = Path(base, wing)
        wing_dir.mkdir(parents=True, exist_ok=True)
        for ses in sessions:
            (wing_dir / f"{ses}.md").write_text(f"# {ses}")


class TestSyncBasic:
    """Acceptance criteria: sync mines existing exported sessions."""

    def test_given_existing_exports_when_sync_then_mines(
        self, tmp_output,
    ):
        """
        GIVEN an output directory with exported markdown files
        WHEN I run `sync` with a mock mempalace
        THEN mine runs successfully.
        """
        Path(tmp_output, "session_001.md").write_text("# Session 1")
        Path(tmp_output, "session_002.md").write_text("# Session 2")

        with mock_mempalace_script() as mock_cmd:
            result = run_cli([
                "sync",
                "--output-dir", tmp_output,
                "--mempalace-command", mock_cmd,
            ])
        assert result.returncode == 0, (
            f"Expected exit code 0, got {result.returncode}: {result.stderr}"
        )
        assert "Mined" in result.stdout, (
            f"Expected mine output, stdout: {result.stdout}"
        )


class TestSyncDryRun:
    """Acceptance criteria: --dry-run skips the mempalace invocation."""

    def test_given_existing_exports_when_sync_dry_run_then_previews_command(
        self, tmp_output,
    ):
        """
        GIVEN an output directory with exported files
        WHEN I run `sync --dry-run`
        THEN it shows the DRY-RUN command
        AND no actual mine is executed.
        """
        Path(tmp_output, "session_001.md").write_text("# Session 1")

        result = run_cli([
            "sync",
            "--output-dir", tmp_output,
            "--dry-run",
        ])
        assert result.returncode == 0, (
            f"Expected exit code 0, got {result.returncode}: {result.stderr}"
        )
        assert "DRY-RUN" in result.stdout, (
            f"Expected DRY-RUN output, stdout: {result.stdout}"
        )
        assert "Command:" in result.stdout, (
            f"Expected 'Command:' in dry-run output, stdout: {result.stdout}"
        )


class TestSyncWingPassthrough:
    """Acceptance criteria: --wing flag reaches the mempalace command."""

    def test_given_custom_wing_when_sync_dry_run_then_wing_appears_in_command(
        self, tmp_output,
    ):
        """
        GIVEN an output directory with files
        WHEN I run `sync --wing my-test-wing --dry-run`
        THEN the wing name appears in the mining dry-run command output.
        """
        Path(tmp_output, "session_001.md").write_text("# Session 1")
        result = run_cli([
            "sync",
            "--output-dir", tmp_output,
            "--wing", "my-test-wing",
            "--dry-run",
        ])
        assert result.returncode == 0, (
            f"Expected exit code 0, got {result.returncode}: {result.stderr}"
        )
        assert "my-test-wing" in result.stdout, (
            f"Expected 'my-test-wing' in dry-run output, stdout: {result.stdout}"
        )

    def test_given_default_wing_when_sync_dry_run_then_default_wing_in_command(
        self, tmp_output,
    ):
        """
        GIVEN no --wing flag
        WHEN I run `sync --dry-run`
        THEN the default wing "opencode-sessions" appears in the command output.
        """
        Path(tmp_output, "session_001.md").write_text("# Session 1")
        result = run_cli([
            "sync",
            "--output-dir", tmp_output,
            "--dry-run",
        ])
        assert result.returncode == 0, (
            f"Expected exit code 0, got {result.returncode}: {result.stderr}"
        )
        assert "opencode-sessions" in result.stdout, (
            f"Expected default wing in dry-run output, stdout: {result.stdout}"
        )


class TestSyncLockDetection:
    """Acceptance criteria: sync fails when mempalace is locked."""

    def test_given_mempalace_locked_when_sync_then_returns_lock_error(
        self, tmp_output,
    ):
        """
        GIVEN exported files in output dir AND mempalace is locked
        WHEN I run `sync`
        THEN it should fail with a lock error message.
        """
        Path(tmp_output, "session_001.md").write_text("# Session 1")

        with tempfile.NamedTemporaryFile(mode="w", suffix=".sh", delete=False) as f:
            f.write("#!/bin/sh\necho 'database is locked' >&2\nexit 1\n")
            lock_script = f.name
        os.chmod(lock_script, os.stat(lock_script).st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

        try:
            result = run_cli([
                "sync",
                "--output-dir", tmp_output,
                "--mempalace-command", lock_script,
            ])
        finally:
            os.unlink(lock_script)

        assert result.returncode != 0, (
            f"Expected non-zero exit code for lock error, got 0: stdout={result.stdout}"
        )
        assert "locked" in result.stdout.lower() or "lock" in result.stdout.lower(), (
            f"Expected lock-related error message, stdout: {result.stdout}"
        )


class TestSyncMineFailure:
    """Acceptance criteria: sync propagates mine errors."""

    def test_given_mempalace_fails_when_sync_then_returns_error(
        self, tmp_output,
    ):
        """
        GIVEN exported files in output dir
        WHEN mempalace exits with non-zero
        THEN sync should exit with non-zero and print an error.
        """
        Path(tmp_output, "session_001.md").write_text("# Session 1")

        with mock_mempalace_script(body="#!/bin/sh\nexit 1\n") as mock_cmd:
            result = run_cli([
                "sync",
                "--output-dir", tmp_output,
                "--mempalace-command", mock_cmd,
            ])
        assert result.returncode != 0, (
            f"Expected non-zero exit code, got 0: stdout={result.stdout}"
        )
        assert "Error" in result.stdout, (
            f"Expected 'Error' in stdout, got: {result.stdout}"
        )


class TestSyncCliRestriction:
    """Acceptance criteria: sync CLI rejects export-specific flags."""

    def test_given_export_flag_db_path_when_sync_then_rejected(
        self, tmp_output,
    ):
        """
        GIVEN a --db-path flag (export-specific)
        WHEN I run `sync --db-path <path>`
        THEN typer should reject it as an unknown option.
        """
        result = run_cli([
            "sync",
            "--db-path", "/nonexistent/test.db",
            "--output-dir", tmp_output,
        ])
        assert result.returncode != 0, (
            f"Expected non-zero exit code for unknown option, got 0: stdout={result.stdout}"
        )


class TestSyncMaxSessions:
    """Acceptance criteria: --max-sessions creates temp dir with subset of files."""

    def test_given_max_sessions_when_sync_dry_run_then_command_refers_to_temp_dir(
        self, tmp_output,
    ):
        """
        GIVEN 5 markdown files in the output directory
        WHEN I run `sync --max-sessions 2 --dry-run`
        THEN the dry-run command output contains a .tmp_sync_ path
        AND the temp directory is cleaned up afterwards.
        """
        for i in range(5):
            Path(tmp_output, f"session_{i:03d}.md").write_text(f"# Session {i}")

        result = run_cli([
            "sync",
            "--output-dir", tmp_output,
            "--max-sessions", "2",
            "--dry-run",
        ])
        assert result.returncode == 0, (
            f"Expected exit code 0, got {result.returncode}: {result.stderr}"
        )
        assert ".tmp_sync_" in result.stdout, (
            f"Expected .tmp_sync_ path in dry-run command, stdout: {result.stdout}"
        )

        leftover = [d for d in Path(tmp_output).iterdir() if d.name.startswith(".tmp_sync_")]
        assert len(leftover) == 0, (
            f"Temp dir not cleaned up after sync: {leftover}"
        )

    def test_given_max_sessions_when_sync_then_cleans_up_temp_dir(
        self, tmp_output,
    ):
        """
        GIVEN 5 markdown files in the output directory
        WHEN I run `sync --max-sessions 3` with a mock mempalace
        THEN the temp directory is removed after completion.
        """
        for i in range(5):
            Path(tmp_output, f"session_{i:03d}.md").write_text(f"# Session {i}")

        with mock_mempalace_script() as mock_cmd:
            result = run_cli([
                "sync",
                "--output-dir", tmp_output,
                "--max-sessions", "3",
                "--mempalace-command", mock_cmd,
            ])
        assert result.returncode == 0, (
            f"Expected exit code 0, got {result.returncode}: {result.stderr}"
        )

        leftover = [d for d in Path(tmp_output).iterdir() if d.name.startswith(".tmp_sync_")]
        assert len(leftover) == 0, (
            f"Temp dir not cleaned up after sync: {leftover}"
        )
        # Original files must still be intact
        md_files = sorted(Path(tmp_output).glob("*.md"))
        assert len(md_files) == 5, (
            f"Expected 5 original files intact, found {len(md_files)}"
        )

    def test_given_max_sessions_greater_than_files_when_sync_then_succeeds(
        self, tmp_output,
    ):
        """
        GIVEN 3 markdown files in the output directory
        WHEN I run `sync --max-sessions 10`
        THEN all 3 files are copied and sync succeeds.
        """
        for i in range(3):
            Path(tmp_output, f"session_{i:03d}.md").write_text(f"# Session {i}")

        with mock_mempalace_script() as mock_cmd:
            result = run_cli([
                "sync",
                "--output-dir", tmp_output,
                "--max-sessions", "10",
                "--mempalace-command", mock_cmd,
            ])
        assert result.returncode == 0, (
            f"Expected exit code 0, got {result.returncode}: {result.stderr}"
        )
        leftover = [d for d in Path(tmp_output).iterdir() if d.name.startswith(".tmp_sync_")]
        assert len(leftover) == 0, "Temp dir not cleaned up"

    def test_given_no_max_sessions_when_sync_dry_run_then_mines_directly(
        self, tmp_output,
    ):
        """
        GIVEN exported files in output dir
        WHEN I run `sync --dry-run` without --max-sessions
        THEN the command references the output dir directly (no .tmp_sync_).
        """
        Path(tmp_output, "session_001.md").write_text("# Session 1")
        
        import json
        config_dir = Path.home() / ".config" / "com.kevincojean.opencode-mempalacebackfill"
        config_dir.mkdir(parents=True, exist_ok=True)
        config_file = config_dir / "config.json"
        config_file.write_text(json.dumps({
            "backfill": {
                "preclassification": {
                    "enabled": False
                }
            }
        }))

        try:
            result = run_cli([
                "sync",
                "--output-dir", tmp_output,
                "--dry-run",
            ])
            assert result.returncode == 0, (
                f"Expected exit code 0, got {result.returncode}: {result.stderr}"
            )
            assert ".tmp_sync_" not in result.stdout, (
                f"Expected no temp dir path without --max-sessions and preclassification disabled, stdout: {result.stdout}"
            )
        finally:
            if config_file.exists():
                config_file.unlink()


class TestSyncDefaultPaths:
    """Acceptance criteria: default paths resolve to stable XDG location."""

    def test_given_no_output_dir_when_sync_dry_run_then_resolves_to_xdg_path(
        self,
    ):
        """
        GIVEN no --output-dir flag
        WHEN I run `sync --dry-run`
        THEN the mined dir is the XDG data home path, not project-relative.
        """
        expected_dir = str(
            Path.home() / ".local" / "share" / "com.kevincojean.opencode-mempalacebackfill" / "exports"
        )

        result = run_cli([
            "sync",
            "--dry-run",
        ])

        assert result.returncode == 0, (
            f"Expected exit code 0, got {result.returncode}: {result.stderr}"
        )
        assert expected_dir in result.stdout, (
            f"Expected default output dir '{expected_dir}' in sync command, "
            f"stdout: {result.stdout}"
        )


class TestSyncWingAutoDetect:
    """Acceptance criteria: sync auto-discovers wing subdirectories."""

    def test_given_wing_dirs_when_sync_dry_run_then_mines_each_wing(
        self, tmp_output,
    ):
        """
        GIVEN wing subdirectories wing_proj1 (2 sessions) and wing_my-app (1 session)
        WHEN I run `sync --dry-run` without ``--wing``
        THEN the output shows two command lines, one per wing.
        """
        _create_wing_dirs(tmp_output, {
            "wing_proj1": ["ses_a", "ses_b"],
            "wing_my-app": ["ses_c"],
        })

        result = run_cli([
            "sync",
            "--output-dir", tmp_output,
            "--dry-run",
        ])
        assert result.returncode == 0, (
            f"Expected exit code 0, got {result.returncode}: {result.stderr}"
        )
        assert "--wing wing_proj1" in result.stdout, (
            f"Expected --wing wing_proj1 in dry-run output, got: {result.stdout}"
        )
        assert "--wing wing_my-app" in result.stdout, (
            f"Expected --wing wing_my-app in dry-run output, got: {result.stdout}"
        )

    def test_given_flat_dir_when_sync_dry_run_then_falls_back_to_opencode_sessions(
        self, tmp_output,
    ):
        """
        GIVEN a flat output directory with .md files (no wing subdirectories)
        WHEN I run `sync --dry-run` without ``--wing``
        THEN the fallback wing "opencode-sessions" appears in the command.
        """
        Path(tmp_output, "session_001.md").write_text("# Session 1")
        Path(tmp_output, "session_002.md").write_text("# Session 2")

        result = run_cli([
            "sync",
            "--output-dir", tmp_output,
            "--dry-run",
        ])
        assert result.returncode == 0, (
            f"Expected exit code 0, got {result.returncode}: {result.stderr}"
        )
        assert "opencode-sessions" in result.stdout, (
            f"Expected fallback wing 'opencode-sessions' in dry-run output, "
            f"stdout: {result.stdout}"
        )

    def test_given_wing_dirs_with_override_when_sync_dry_run_then_single_wing(
        self, tmp_output,
    ):
        """
        GIVEN wing subdirectories wing_proj1 and wing_my-app
        WHEN I run `sync --wing override-wing --dry-run`
        THEN only the override wing appears in the command output
        AND the wing subdirectory names do not appear.
        """
        _create_wing_dirs(tmp_output, {
            "wing_proj1": ["ses_a"],
            "wing_my-app": ["ses_b"],
        })

        result = run_cli([
            "sync",
            "--output-dir", tmp_output,
            "--wing", "override-wing",
            "--dry-run",
        ])
        assert result.returncode == 0, (
            f"Expected exit code 0, got {result.returncode}: {result.stderr}"
        )
        assert "override-wing" in result.stdout, (
            f"Expected 'override-wing' in output, got: {result.stdout}"
        )
        assert "--wing wing_proj1" not in result.stdout, (
            "Expected no --wing wing_proj1 when --wing is explicitly provided"
        )


class TestSyncWingDryRun:
    """Acceptance criteria: dry-run with wing subdirectories shows all commands."""

    def test_given_multiple_wing_dirs_when_sync_dry_run_then_shows_multiple_commands(
        self, tmp_output,
    ):
        """
        GIVEN wing subdirectories wing_a and wing_b with session files
        WHEN I run `sync --dry-run`
        THEN two [DRY-RUN] Command: lines appear in the output.
        """
        _create_wing_dirs(tmp_output, {
            "wing_a": ["s1"],
            "wing_b": ["s2"],
        })

        result = run_cli([
            "sync",
            "--output-dir", tmp_output,
            "--dry-run",
        ])
        assert result.returncode == 0, (
            f"Expected exit code 0, got {result.returncode}: {result.stderr}"
        )
        dr_lines = [l for l in result.stdout.split("\n") if "[DRY-RUN]" in l]
        assert len(dr_lines) == 2, (
            f"Expected 2 [DRY-RUN] lines for 2 wings, found {len(dr_lines)}: {result.stdout}"
        )


class TestSyncWingMine:
    """Acceptance criteria: sync mines each wing subdirectory into its own wing."""

    def test_given_wing_dirs_when_sync_then_mines_each_separately(
        self, tmp_output,
    ):
        """
        GIVEN wing subdirectories wing_a and wing_b with session files
        WHEN I run `sync` with a mock mempalace that records its args
        THEN the mock is called twice, once per wing.
        """
        _create_wing_dirs(tmp_output, {
            "wing_a": ["s1"],
            "wing_b": ["s2"],
        })

        call_log = os.path.join(tmp_output, "calls.txt")

        with mock_mempalace_script(
            body=f"#!/bin/sh\necho $@ >> {call_log}\necho '1 drawers'\nexit 0\n"
        ) as mock_cmd:
            result = run_cli([
                "sync",
                "--output-dir", tmp_output,
                "--mempalace-command", mock_cmd,
            ])
        assert result.returncode == 0, (
            f"Expected exit code 0, got {result.returncode}: {result.stderr}"
        )

        assert os.path.exists(call_log), f"Call log not created at {call_log}"
        with open(call_log) as f:
            calls = f.read().strip().split("\n")
        assert len(calls) == 2, (
            f"Expected 2 mine calls (one per wing), got {len(calls)}: {calls}"
        )

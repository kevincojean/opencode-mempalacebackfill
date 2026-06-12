import os
import stat
import tempfile
from pathlib import Path

from tests.e2e.helpers import run_cli, mock_mempalace_script


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

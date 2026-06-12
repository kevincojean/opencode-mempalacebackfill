from pathlib import Path

from tests.e2e.helpers import run_cli


class TestSyncNoNewSessions:
    """Acceptance criteria: sync skips mining when nothing to export."""

    def test_given_no_new_sessions_when_sync_then_skips_mine_and_reports_nothing(
        self, fixture_db, tmp_output, tmp_state,
    ):
        """
        GIVEN all sessions have already been exported (tracked in state)
        WHEN I run `sync` with the same state file
        THEN export reports nothing new
        AND mining is skipped (no mempalace invocation).
        """
        run_cli([
            "export",
            "--db-path", fixture_db,
            "--max-sessions", "3",
            "--output-dir", tmp_output,
            "--state-file", tmp_state,
        ])

        result = run_cli([
            "sync",
            "--db-path", fixture_db,
            "--output-dir", tmp_output,
            "--state-file", tmp_state,
        ])
        assert result.returncode == 0, (
            f"Expected exit code 0, got {result.returncode}: {result.stderr}"
        )
        assert "No new sessions to export" in result.stdout, (
            f"Expected 'No new sessions to export' when nothing to sync, "
            f"stdout: {result.stdout}"
        )


class TestSyncDryRun:
    """Acceptance criteria: --dry-run skips actual mempalace invocation."""

    def test_given_unexported_sessions_when_sync_dry_run_then_previews_export_and_mine(
        self, fixture_db, tmp_output, tmp_state,
    ):
        """
        GIVEN a database with 3 sessions, none exported yet
        WHEN I run `sync --max-sessions 2 --dry-run`
        THEN it shows "Would export 2 sessions"
        AND shows the mempalace command that would run
        AND No files are written.
        """
        result = run_cli([
            "sync",
            "--db-path", fixture_db,
            "--max-sessions", "2",
            "--dry-run",
            "--output-dir", tmp_output,
            "--state-file", tmp_state,
        ])
        assert result.returncode == 0, (
            f"Expected exit code 0, got {result.returncode}: {result.stderr}"
        )
        assert "Would export 2 sessions" in result.stdout, (
            f"Expected export preview, stdout: {result.stdout}"
        )
        assert "DRY-RUN" in result.stdout, (
            f"Expected mining dry-run output, stdout: {result.stdout}"
        )

        md_files = list(Path(tmp_output).glob("*.md"))
        assert len(md_files) == 0, (
            f"Expected no files written during dry run, found: {md_files}"
        )

    def test_given_nonew_sessions_when_sync_dry_run_then_no_mine_dry_run(
        self, fixture_db, tmp_output, tmp_state,
    ):
        """
        GIVEN all sessions already exported
        WHEN I run `sync --dry-run`
        THEN no mining dry-run command should appear
        AND exit code is 0.
        """
        run_cli([
            "export",
            "--db-path", fixture_db,
            "--max-sessions", "3",
            "--output-dir", tmp_output,
            "--state-file", tmp_state,
        ])

        result = run_cli([
            "sync",
            "--db-path", fixture_db,
            "--dry-run",
            "--output-dir", tmp_output,
            "--state-file", tmp_state,
        ])
        assert result.returncode == 0, (
            f"Expected exit code 0, got {result.returncode}: {result.stderr}"
        )
        assert "No new sessions to export" in result.stdout, (
            f"Expected no-export message, stdout: {result.stdout}"
        )
        assert "DRY-RUN" not in result.stdout, (
            "Expected NO mine dry-run output when nothing to export, "
            f"stdout: {result.stdout}"
        )


class TestSyncErrorHandling:
    """Acceptance criteria: sync propagates export errors."""

    def test_given_nonexistent_db_when_sync_then_returns_error(
        self, tmp_output,
    ):
        """
        GIVEN a non-existent database path
        WHEN I run `sync --db-path /nonexistent/test.db`
        THEN it should exit with a non-zero code
        AND print an error message.
        """
        result = run_cli([
            "sync",
            "--db-path", "/nonexistent/test.db",
            "--output-dir", tmp_output,
        ])
        assert result.returncode != 0, (
            f"Expected non-zero exit code, got 0: stdout={result.stdout}"
        )
        assert "Error" in result.stdout, (
            f"Expected 'Error' in stdout, got: {result.stdout}"
        )


class TestSyncWingPassthrough:
    """Acceptance criteria: --wing flag reaches the mempalace command."""

    def test_given_custom_wing_when_sync_dry_run_then_wing_appears_in_command(
        self, fixture_db, tmp_output, tmp_state,
    ):
        """
        GIVEN a database with sessions
        WHEN I run `sync --wing my-test-wing --max-sessions 1 --dry-run`
        THEN the wing name appears in the mining dry-run command output.
        """
        result = run_cli([
            "sync",
            "--db-path", fixture_db,
            "--wing", "my-test-wing",
            "--max-sessions", "1",
            "--dry-run",
            "--output-dir", tmp_output,
            "--state-file", tmp_state,
        ])
        assert result.returncode == 0, (
            f"Expected exit code 0, got {result.returncode}: {result.stderr}"
        )
        assert "my-test-wing" in result.stdout, (
            f"Expected 'my-test-wing' in dry-run output, stdout: {result.stdout}"
        )

    def test_given_default_wing_when_sync_dry_run_then_default_wing_in_command(
        self, fixture_db, tmp_output, tmp_state,
    ):
        """
        GIVEN no --wing flag
        WHEN I run `sync --max-sessions 1 --dry-run`
        THEN the default wing "opencode-sessions" appears in the command output.
        """
        result = run_cli([
            "sync",
            "--db-path", fixture_db,
            "--max-sessions", "1",
            "--dry-run",
            "--output-dir", tmp_output,
            "--state-file", tmp_state,
        ])
        assert result.returncode == 0, (
            f"Expected exit code 0, got {result.returncode}: {result.stderr}"
        )
        assert "opencode-sessions" in result.stdout, (
            f"Expected default wing in dry-run output, stdout: {result.stdout}"
        )


class TestSyncExportCount:
    """Acceptance criteria: sync reports the correct export and mine counts."""

    def test_given_sessions_when_sync_dry_run_then_export_count_matches(
        self, fixture_db, tmp_output, tmp_state,
    ):
        """
        GIVEN 3 sessions in the database
        WHEN I run `sync --max-sessions 2 --dry-run`
        THEN export count is 2
        AND mining dry-run is shown.
        """
        result = run_cli([
            "sync",
            "--db-path", fixture_db,
            "--max-sessions", "2",
            "--dry-run",
            "--output-dir", tmp_output,
            "--state-file", tmp_state,
        ])
        assert result.returncode == 0, (
            f"Expected exit code 0, got {result.returncode}: {result.stderr}"
        )
        assert "Would export 2 sessions" in result.stdout, (
            f"Expected 'Would export 2 sessions', stdout: {result.stdout}"
        )
        assert "Mined 0 drawers" in result.stdout, (
            f"Expected mine result message, stdout: {result.stdout}"
        )

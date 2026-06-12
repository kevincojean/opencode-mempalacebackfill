import glob
from pathlib import Path

from tests.e2e.helpers import run_cli


class TestExportDryRun:
    """Acceptance criteria for `export --dry-run`."""

    def test_given_3_sessions_when_dry_run_with_max_2_then_previews_count_without_files(self, fixture_db, tmp_output, tmp_state):
        """
        GIVEN a database containing 3 sessions
        WHEN I run `export --max-sessions 2 --dry-run`
        THEN it should report "Would export 2 sessions"
        AND no markdown files should be written to the output directory.
        """
        result = run_cli([
            "export",
            "--db-path", fixture_db,
            "--max-sessions", "2",
            "--dry-run",
            "--output-dir", tmp_output,
            "--state-file", tmp_state
        ])
        assert result.returncode == 0, f"Expected exit code 0, got {result.returncode}: {result.stderr}"
        assert "Would export 2 sessions" in result.stdout, (
            f"Expected 'Would export 2 sessions' in stdout, got: {result.stdout}"
        )
        md_files = glob.glob(str(Path(tmp_output, "*.md")))
        assert len(md_files) == 0, (
            f"Expected no files written during dry run, found: {md_files}"
        )


class TestExportBasic:
    """Acceptance criteria for basic `export` command."""

    def test_given_3_sessions_when_export_max_2_then_creates_markdown_files_with_expected_format(self, fixture_db, tmp_output, tmp_state):
        """
        GIVEN a database containing 3 sessions
        WHEN I run `export --max-sessions 2`
        THEN 2 markdown files should be created
        AND each file should contain a title, session ID, date,
            user content, assistant content, and a trailing separator.
        """
        result = run_cli([
            "export",
            "--db-path", fixture_db,
            "--max-sessions", "2",
            "--output-dir", tmp_output,
            "--state-file", tmp_state
        ])
        assert result.returncode == 0, f"Expected exit code 0, got {result.returncode}: {result.stderr}"

        md_files = glob.glob(str(Path(tmp_output, "*.md")))
        assert len(md_files) == 2, (
            f"Expected 2 markdown files, found {len(md_files)}: {md_files}"
        )

        for md_file in md_files:
            content = Path(md_file).read_text()
            assert "# " in content, f"Missing title (#) in {md_file}"
            assert "> Session ID:" in content, f"Missing session ID in {md_file}"
            assert "> Date:" in content, f"Missing date in {md_file}"
            assert "User" in content, f"Missing user content marker in {md_file}"
            assert "Assistant" in content, f"Missing assistant content marker in {md_file}"
            assert "---" in content, f"Missing trailing separator (---) in {md_file}"


class TestExportMaxSessions:
    """Acceptance criteria for `--max-sessions` flag."""

    def test_given_3_sessions_when_export_max_greater_than_available_then_exports_all(self, fixture_db, tmp_output, tmp_state):
        """
        GIVEN a database containing 3 sessions
        WHEN I run `export --max-sessions 5` (more than available count)
        THEN all 3 sessions should be exported.
        """
        result = run_cli([
            "export",
            "--db-path", fixture_db,
            "--max-sessions", "5",
            "--output-dir", tmp_output,
            "--state-file", tmp_state
        ])
        assert result.returncode == 0, f"Expected exit code 0, got {result.returncode}: {result.stderr}"
        assert "Successfully exported 3 sessions" in result.stdout, (
            f"Expected 'Successfully exported 3 sessions' in stdout, got: {result.stdout}"
        )
        md_files = glob.glob(str(Path(tmp_output, "*.md")))
        assert len(md_files) == 3, f"Expected 3 markdown files, found {len(md_files)}"


class TestExportStateTracking:
    """Acceptance criteria for state file session tracking."""

    def test_given_3_sessions_with_state_when_export_2_then_export_again_then_only_remaining_exported(self, fixture_db, tmp_output, tmp_state):
        """
        GIVEN a database containing 3 sessions and a state file
        WHEN I export 2 sessions
        AND I run export again with the same state file (no --max-sessions)
        THEN the second export should only export the 1 remaining session.
        """
        result1 = run_cli([
            "export",
            "--db-path", fixture_db,
            "--max-sessions", "2",
            "--output-dir", tmp_output,
            "--state-file", tmp_state
        ])
        assert result1.returncode == 0, f"First export failed: {result1.stderr}"
        assert "Successfully exported 2 sessions" in result1.stdout, (
            f"Expected 2 sessions in first export, stdout: {result1.stdout}"
        )

        result2 = run_cli([
            "export",
            "--db-path", fixture_db,
            "--output-dir", tmp_output,
            "--state-file", tmp_state
        ])
        assert result2.returncode == 0, f"Second export failed: {result2.stderr}"
        assert "Successfully exported 1 sessions" in result2.stdout, (
            f"Expected 1 session in second export (remaining after state tracking), "
            f"stdout: {result2.stdout}"
        )


class TestExportDateFilters:
    """Acceptance criteria for `--since` and `--until` date filters."""

    def test_given_sessions_jan_apr_sep_when_since_jun_2025_then_exports_sep_only(self, fixture_db, tmp_output, tmp_state):
        """
        GIVEN sessions with timestamps in Jan 2025, Apr 2025, and Sep 2025
        WHEN I run `export --since 2025-06-01`
        THEN only the Sep 2025 session (1 session) should be exported.
        """
        result = run_cli([
            "export",
            "--db-path", fixture_db,
            "--since", "2025-06-01",
            "--output-dir", tmp_output,
            "--state-file", tmp_state
        ])
        assert result.returncode == 0, f"Expected exit code 0, got {result.returncode}: {result.stderr}"
        assert "Successfully exported 1 sessions" in result.stdout, (
            f"Expected 1 session exported with --since 2025-06-01, "
            f"stdout: {result.stdout}"
        )

    def test_given_sessions_jan_apr_sep_when_until_mar_2025_then_exports_jan_only(self, fixture_db, tmp_output, tmp_state):
        """
        GIVEN sessions with timestamps in Jan 2025, Apr 2025, and Sep 2025
        WHEN I run `export --until 2025-03-01`
        THEN only the Jan 2025 session (1 session) should be exported.
        """
        result = run_cli([
            "export",
            "--db-path", fixture_db,
            "--until", "2025-03-01",
            "--output-dir", tmp_output,
            "--state-file", tmp_state
        ])
        assert result.returncode == 0, f"Expected exit code 0, got {result.returncode}: {result.stderr}"
        assert "Successfully exported 1 sessions" in result.stdout, (
            f"Expected 1 session exported with --until 2025-03-01, "
            f"stdout: {result.stdout}"
        )


class TestExportExcludeTitle:
    """Acceptance criteria for `--exclude-title` filter."""

    def test_given_3_sessions_when_exclude_session_2_then_exports_remaining_2(self, fixture_db, tmp_output, tmp_state):
        """
        GIVEN sessions titled "Session 1", "Session 2", and "Session 3"
        WHEN I run `export --exclude-title "Session 2"`
        THEN only "Session 1" and "Session 3" (2 sessions) should be exported.
        """
        result = run_cli([
            "export",
            "--db-path", fixture_db,
            "--exclude-title", "Session 2",
            "--output-dir", tmp_output,
            "--state-file", tmp_state
        ])
        assert result.returncode == 0, f"Expected exit code 0, got {result.returncode}: {result.stderr}"
        assert "Successfully exported 2 sessions" in result.stdout, (
            f"Expected 2 sessions exported (excluding 'Session 2'), "
            f"stdout: {result.stdout}"
        )


class TestExportErrorHandling:
    """Acceptance criteria for error handling in `export`."""

    def test_given_nonexistent_db_path_when_export_then_returns_error(self, tmp_output):
        """
        GIVEN a non-existent database path
        WHEN I run `export --db-path /nonexistent/test.db`
        THEN it should exit with a non-zero code and print an error message.
        """
        result = run_cli([
            "export",
            "--db-path", "/nonexistent/test.db",
            "--output-dir", tmp_output
        ])
        assert result.returncode != 0, (
            f"Expected non-zero exit code for invalid DB, got 0: stdout={result.stdout}"
        )
        assert "Error" in result.stdout, (
            f"Expected 'Error' in stdout for invalid DB, got: {result.stdout}"
        )


class TestExportDateRange:
    """Acceptance criteria for combined --since + --until date filters."""

    def test_given_sessions_jan_apr_sep_when_since_feb_until_aug_2025_then_exports_apr_only(
        self, fixture_db, tmp_output, tmp_state,
    ):
        """
        GIVEN sessions with timestamps in Jan 2025, Apr 2025, and Sep 2025
        WHEN I run `export --since 2025-02-01 --until 2025-08-01`
        THEN only the Apr 2025 session (1 session) should be exported.
        """
        result = run_cli([
            "export",
            "--db-path", fixture_db,
            "--since", "2025-02-01",
            "--until", "2025-08-01",
            "--output-dir", tmp_output,
            "--state-file", tmp_state,
        ])
        assert result.returncode == 0, (
            f"Expected exit code 0, got {result.returncode}: {result.stderr}"
        )
        assert "Successfully exported 1 sessions" in result.stdout, (
            f"Expected 1 session with --since 2025-02-01 --until 2025-08-01, "
            f"stdout: {result.stdout}"
        )


class TestExportExcludeTitleSubstring:
    """Acceptance criteria for `--exclude-title` with substring/wildcard matching."""

    def test_given_sessions_1_2_3_when_exclude_title_1_then_excludes_session_1_only(
        self, fixture_db, tmp_output, tmp_state,
    ):
        """
        GIVEN sessions titled "Session 1", "Session 2", "Session 3"
        WHEN I run `export --exclude-title "1"`
        THEN only "Session 2" and "Session 3" (2 sessions) should be exported
        (the pattern acts as a LIKE substring match: %1% matches "Session 1").
        """
        result = run_cli([
            "export",
            "--db-path", fixture_db,
            "--exclude-title", "1",
            "--output-dir", tmp_output,
            "--state-file", tmp_state,
        ])
        assert result.returncode == 0, (
            f"Expected exit code 0, got {result.returncode}: {result.stderr}"
        )
        assert "Successfully exported 2 sessions" in result.stdout, (
            f"Expected 2 sessions (excluding 'Session 1'), "
            f"stdout: {result.stdout}"
        )


class TestExportNothingToExport:
    """Edge cases where export has nothing to do."""

    def test_given_all_sessions_already_exported_when_export_again_then_reports_nothing(
        self, fixture_db, tmp_output, tmp_state,
    ):
        """
        GIVEN all 3 sessions have already been exported (tracked in state)
        WHEN I run `export` again with the same state file
        THEN it should print "No new sessions to export"
        AND return exit code 0.
        """
        result_first = run_cli([
            "export",
            "--db-path", fixture_db,
            "--max-sessions", "3",
            "--output-dir", tmp_output,
            "--state-file", tmp_state,
        ])
        assert result_first.returncode == 0, (
            f"First export failed: {result_first.stderr}"
        )

        result_second = run_cli([
            "export",
            "--db-path", fixture_db,
            "--output-dir", tmp_output,
            "--state-file", tmp_state,
        ])
        assert result_second.returncode == 0, (
            f"Second export failed: {result_second.stderr}"
        )
        assert "No new sessions to export" in result_second.stdout, (
            f"Expected 'No new sessions to export' on re-export, "
            f"stdout: {result_second.stdout}"
        )

    def test_given_exclude_title_matches_all_when_export_then_reports_nothing(
        self, fixture_db, tmp_output, tmp_state,
    ):
        """
        GIVEN 3 sessions
        WHEN I run `export --exclude-title "Session"`
        THEN the pattern matches all titles (LIKE %Session%)
        AND it should print "No new sessions to export".
        """
        result = run_cli([
            "export",
            "--db-path", fixture_db,
            "--exclude-title", "Session",
            "--output-dir", tmp_output,
            "--state-file", tmp_state,
        ])
        assert result.returncode == 0, (
            f"Expected exit code 0, got {result.returncode}: {result.stderr}"
        )
        assert "No new sessions to export" in result.stdout, (
            f"Expected 'No new sessions to export' when all excluded, "
            f"stdout: {result.stdout}"
        )

import json
from pathlib import Path

from tests.e2e.helpers import run_cli


def _wing_md_files(output_dir: str) -> list[Path]:
    """Return all markdown files under a wing subdirectory in output_dir."""
    return sorted(Path(output_dir).rglob("*.md"))


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
            "--since", "2025-01-01",
            "--max-sessions", "2",
            "--min-messages", "1",
            "--dry-run",
            "--output-dir", tmp_output,
            "--state-file", tmp_state
        ])
        assert result.returncode == 0, f"Expected exit code 0, got {result.returncode}: {result.stderr}"
        assert "Would export 2 sessions" in result.stdout, (
            f"Expected 'Would export 2 sessions' in stdout, got: {result.stdout}"
        )
        md_files = _wing_md_files(tmp_output)
        assert len(md_files) == 0, (
            f"Expected no files written during dry run, found: {md_files}"
        )


class TestExportBasic:
    """Acceptance criteria for basic `export` command."""

    def test_given_3_sessions_when_export_max_2_then_creates_markdown_files_with_expected_format(self, fixture_db, tmp_output, tmp_state):
        """
        GIVEN a database containing 3 sessions
        WHEN I run `export --max-sessions 2`
        THEN 2 markdown files should be created in the wing subdirectory
        AND each file should contain a title, session ID, date,
            user content, assistant content, and a trailing separator.
        """
        result = run_cli([
            "export",
            "--db-path", fixture_db,
            "--since", "2025-01-01",
            "--max-sessions", "2",
            "--min-messages", "1",
            "--output-dir", tmp_output,
            "--state-file", tmp_state
        ])
        assert result.returncode == 0, f"Expected exit code 0, got {result.returncode}: {result.stderr}"

        md_files = _wing_md_files(tmp_output)
        assert len(md_files) == 2, (
            f"Expected 2 markdown files in wing subdirectory, found {len(md_files)}: {md_files}"
        )

        for md_file in md_files:
            content = Path(md_file).read_text()
            assert "# " in content, f"Missing title (#) in {md_file}"
            assert "Session ID:" in content, f"Missing session ID in {md_file}"
            assert "Date:" in content, f"Missing date in {md_file}"
            assert "User" in content, f"Missing user content marker in {md_file}"
            assert "Assistant" in content, f"Missing assistant content marker in {md_file}"
            assert "---" in content, f"Missing trailing separator (---) in {md_file}"
            assert "wing_proj1" in str(md_file), (
                f"Expected file in wing_proj1 subdirectory, found: {md_file}"
            )


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
            "--since", "2025-01-01",
            "--max-sessions", "5",
            "--min-messages", "1",
            "--output-dir", tmp_output,
            "--state-file", tmp_state
        ])
        assert result.returncode == 0, f"Expected exit code 0, got {result.returncode}: {result.stderr}"
        assert "Successfully exported 3 sessions" in result.stdout, (
            f"Expected 'Successfully exported 3 sessions' in stdout, got: {result.stdout}"
        )
        md_files = _wing_md_files(tmp_output)
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
            "--since", "2025-01-01",
            "--max-sessions", "2",
            "--min-messages", "1",
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
            "--since", "2025-01-01",
            "--min-messages", "1",
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
            "--min-messages", "1",
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
            "--min-messages", "1",
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
            "--since", "2025-01-01",
            "--exclude-title", "Session 2",
            "--min-messages", "1",
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
            "--min-messages", "1",
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
            "--since", "2025-01-01",
            "--exclude-title", "1",
            "--min-messages", "1",
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
            "--since", "2025-01-01",
            "--max-sessions", "3",
            "--min-messages", "1",
            "--output-dir", tmp_output,
            "--state-file", tmp_state,
        ])
        assert result_first.returncode == 0, (
            f"First export failed: {result_first.stderr}"
        )

        result_second = run_cli([
            "export",
            "--db-path", fixture_db,
            "--min-messages", "1",
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


class TestExportWingExplicit:
    """Acceptance criteria: ``--wing`` flag overrides auto-detection."""

    def test_given_wing_flag_when_export_then_all_files_in_that_wing_dir(
        self, multi_project_db, tmp_output, tmp_state,
    ):
        """
        GIVEN sessions from multiple projects
        WHEN I run `export --wing my-custom-wing`
        THEN all files are written into the ``my-custom-wing`` directory
        AND no wing_proj1 / wing_my-app directories are created.
        """
        result = run_cli([
            "export",
            "--db-path", multi_project_db,
            "--since", "2025-01-01",
            "--min-messages", "1",
            "--wing", "my-custom-wing",
            "--output-dir", tmp_output,
            "--state-file", tmp_state,
        ])
        assert result.returncode == 0, (
            f"Expected exit code 0, got {result.returncode}: {result.stderr}"
        )

        wing_dir = Path(tmp_output, "my-custom-wing")
        assert wing_dir.is_dir(), (
            f"Expected wing directory '{wing_dir}' to exist"
        )
        md_files = sorted(wing_dir.glob("*.md"))
        assert len(md_files) == 3, (
            f"Expected 3 markdown files in my-custom-wing, found {len(md_files)}"
        )
        auto_wings = ["wing_proj1", "wing_my-app"]
        for aw in auto_wings:
            assert not Path(tmp_output, aw).is_dir(), (
                f"Auto-detected wing dir '{aw}' should not exist when --wing is set"
            )


class TestExportWingAutoDetect:
    """Acceptance criteria: wing auto-detection from session project paths."""

    def test_given_multi_project_sessions_when_export_then_grouped_by_wing(
        self, multi_project_db, tmp_output, tmp_state,
    ):
        """
        GIVEN sessions from project proj_1 (worktree=/tmp/proj1) and
              project proj_2 (worktree=/home/user/projects/my-app)
        WHEN I run `export` without ``--wing``
        THEN files are sorted into ``wing_proj1`` and ``wing_my-app`` directories
        AND each directory contains the correct number of sessions.
        """
        result = run_cli([
            "export",
            "--db-path", multi_project_db,
            "--since", "2025-01-01",
            "--min-messages", "1",
            "--output-dir", tmp_output,
            "--state-file", tmp_state,
        ])
        assert result.returncode == 0, (
            f"Expected exit code 0, got {result.returncode}: {result.stderr}"
        )

        wing_proj1_dir = Path(tmp_output, "wing_proj1")
        wing_my_app_dir = Path(tmp_output, "wing_my-app")
        assert wing_proj1_dir.is_dir(), (
            f"Expected wing_proj1 directory to exist, found: {sorted(Path(tmp_output).iterdir())}"
        )
        assert wing_my_app_dir.is_dir(), (
            f"Expected wing_my-app directory to exist"
        )

        proj1_files = sorted(wing_proj1_dir.glob("*.md"))
        my_app_files = sorted(wing_my_app_dir.glob("*.md"))
        assert len(proj1_files) == 2, (
            f"Expected 2 sessions in wing_proj1, found {len(proj1_files)}"
        )
        assert len(my_app_files) == 1, (
            f"Expected 1 session in wing_my-app, found {len(my_app_files)}"
        )

    def test_given_single_project_when_export_then_files_in_inferred_wing(
        self, fixture_db, tmp_output, tmp_state,
    ):
        """
        GIVEN sessions from a single project (worktree=/tmp/proj1)
        WHEN I run `export` without ``--wing``
        THEN files are written into the ``wing_proj1`` subdirectory.
        """
        result = run_cli([
            "export",
            "--db-path", fixture_db,
            "--since", "2025-01-01",
            "--min-messages", "1",
            "--output-dir", tmp_output,
            "--state-file", tmp_state,
        ])
        assert result.returncode == 0, (
            f"Expected exit code 0, got {result.returncode}: {result.stderr}"
        )

        wing_dir = Path(tmp_output, "wing_proj1")
        assert wing_dir.is_dir(), (
            f"Expected wing_proj1 directory to exist"
        )
        md_files = sorted(wing_dir.glob("*.md"))
        assert len(md_files) == 3, (
            f"Expected 3 sessions in wing_proj1, found {len(md_files)}"
        )


class TestExportStateMigration:
    def test_given_old_state_json_when_export_then_migrates_to_export_state_json(
        self, fixture_db, tmp_output, tmp_state,
    ):
        """
        GIVEN an old state.json file exists (but no export_state.json)
        WHEN I run export --dry-run with --state-file pointing to export_state.json
        THEN the old state.json is migrated to export_state.json
        AND the old state.json is deleted.
        """
        state_dir = Path(tmp_state).parent
        old_path = Path(tmp_state)
        new_path = state_dir / "export_state.json"

        old_data = {
            "last_session_time": "2025-01-15T10:00:00",
            "last_session_id": "sess_001",
            "exported_session_ids": ["sess_001", "sess_002"],
            "total_sessions_exported": 2,
        }

        with open(old_path, "w") as f:
            json.dump(old_data, f)
        assert old_path.exists()
        assert not new_path.exists()

        result = run_cli([
            "export",
            "--db-path", fixture_db,
            "--since", "2025-01-01",
            "--max-sessions", "1",
            "--min-messages", "1",
            "--dry-run",
            "--output-dir", tmp_output,
            "--state-file", str(new_path),
        ])
        assert result.returncode == 0, f"Export failed: {result.stderr}"

        assert new_path.exists(), "export_state.json should exist after migration"
        assert not old_path.exists(), "old state.json should be deleted after migration"

        with open(new_path) as f:
            migrated_data = json.load(f)
        assert migrated_data == old_data, f"Migrated data mismatch: {migrated_data} != {old_data}"

import os
from pathlib import Path

from tests.e2e.helpers import run_cli


class TestCleanBasic:
    """Acceptance criteria for basic `clean` command."""

    def test_given_output_dir_with_files_when_clean_then_empties_directory_and_removes_state(self, tmp_output):
        """
        GIVEN an output directory containing files and subdirectories AND a state file
        WHEN I run `clean --output-dir <dir> --state-file <state>`
        THEN all contents are removed from the output directory
        AND the state file is deleted.
        """
        Path(tmp_output, "session_001.md").write_text("# Session 1")
        Path(tmp_output, "session_002.md").write_text("# Session 2")
        sub_dir = Path(tmp_output, "subdir")
        sub_dir.mkdir()
        Path(sub_dir, "nested.txt").write_text("nested")

        state_file = os.path.join(tmp_output, "state.json")
        Path(state_file).write_text('{"exported_session_ids": ["sess_001"]}')

        result = run_cli([
            "clean",
            "--output-dir", tmp_output,
            "--state-file", state_file,
        ])
        assert result.returncode == 0, (
            f"Expected exit code 0, got {result.returncode}: {result.stderr}"
        )
        assert "Cleaned" in result.stdout, (
            f"Expected success message in stdout, got: {result.stdout}"
        )
        assert os.path.isdir(tmp_output), "Output directory should still exist after clean"
        assert len(os.listdir(tmp_output)) == 0, (
            f"Expected empty directory after clean, found: {os.listdir(tmp_output)}"
        )
        assert not os.path.exists(state_file), "State file should be removed after clean"

    def test_given_empty_output_dir_without_state_when_clean_then_reports_success(self, tmp_output):
        """
        GIVEN an empty output directory and no state file
        WHEN I run `clean --output-dir <dir> --state-file <state>`
        THEN it should report success with 0 items removed.
        """
        state_file = os.path.join(tmp_output, "state.json")

        result = run_cli([
            "clean",
            "--output-dir", tmp_output,
            "--state-file", state_file,
        ])
        assert result.returncode == 0, (
            f"Expected exit code 0, got {result.returncode}: {result.stderr}"
        )
        assert "Cleaned" in result.stdout, (
            f"Expected success message in stdout, got: {result.stdout}"
        )
        assert "(0 items removed)" in result.stdout, (
            f"Expected '0 items removed' for empty dir, got: {result.stdout}"
        )

    def test_given_nonexistent_output_dir_and_state_when_clean_then_warns(self):
        """
        GIVEN a non-existent output directory and state file path
        WHEN I run `clean --output-dir /nonexistent --state-file /nonexistent/state.json`
        THEN it should print a warning and exit 0 (nothing to clean).
        """
        result = run_cli([
            "clean",
            "--output-dir", "/nonexistent/clean-test-path",
            "--state-file", "/nonexistent/clean-test-state.json",
        ])
        assert result.returncode == 0, (
            f"Expected exit code 0 for nothing to clean, got {result.returncode}: {result.stderr}"
        )
        assert "nothing to clean" in result.stdout.lower(), (
            f"Expected 'nothing to clean' in stdout, got: {result.stdout}"
        )

    def test_given_file_path_when_clean_then_returns_error(self, tmp_output):
        """
        GIVEN a path that is a file (not a directory)
        WHEN I run `clean --output-dir <file-path>`
        THEN it should exit with non-zero code and print an error.
        """
        file_path = os.path.join(tmp_output, "not_a_dir.md")
        Path(file_path).write_text("# Not a directory")

        result = run_cli([
            "clean",
            "--output-dir", file_path,
        ])
        assert result.returncode != 0, (
            f"Expected non-zero exit code for file path, got 0: stdout={result.stdout}"
        )
        assert "Error" in result.stdout, (
            f"Expected error in stdout for file path, got: {result.stdout}"
        )

    def test_given_sync_state_dir_when_clean_sync_state_then_removes_dir(self, tmp_output):
        """
        GIVEN a sync state directory with files
        WHEN I run `clean --sync-state <dir>`
        THEN the directory is removed.
        """
        sync_dir = Path(tmp_output, "sync_state")
        sync_dir.mkdir()
        Path(sync_dir, "state_alpha.json").write_text("{}")
        Path(sync_dir, "state_beta.json").write_text("{}")

        result = run_cli([
            "clean",
            "--output-dir", tmp_output,
            "--sync-state", str(sync_dir),
        ])
        assert result.returncode == 0, f"Expected 0, got {result.returncode}: {result.stderr}"
        assert not sync_dir.exists(), "Sync state dir should be removed"
        assert "Removed sync state directory" in result.stdout

    def test_given_sync_state_file_when_clean_sync_state_then_removes_file(self, tmp_output):
        """
        GIVEN a sync state file
        WHEN I run `clean --sync-state <path>`
        THEN the file is removed.
        """
        sync_file = Path(tmp_output, "sync_state_test.json")
        sync_file.write_text('{"mined_files": {}}')

        result = run_cli([
            "clean",
            "--output-dir", tmp_output,
            "--sync-state", str(sync_file),
        ])
        assert result.returncode == 0, f"Expected 0, got {result.returncode}: {result.stderr}"
        assert not sync_file.exists(), "Sync state file should be removed"
        assert "Removed sync state file" in result.stdout

    def test_given_nonexistent_sync_state_when_clean_sync_state_then_warns(self, tmp_output):
        """
        GIVEN a non-existent sync state path
        WHEN I run `clean --sync-state /nonexistent`
        THEN it prints a warning and exits 0.
        """
        result = run_cli([
            "clean",
            "--output-dir", tmp_output,
            "--sync-state", "/nonexistent/sync_state_test",
        ])
        assert result.returncode == 0, f"Expected 0, got {result.returncode}: {result.stderr}"
        assert "nothing to clean" in result.stdout.lower() or "does not exist" in result.stdout.lower()

    def test_given_state_file_only_when_clean_then_removes_state_and_reports(self, tmp_output):
        """
        GIVEN only a state file exists (no output directory)
        WHEN I run `clean --output-dir <nonexistent> --state-file <state>`
        THEN the state file is removed
        AND exit code is 0.
        """
        state_file = os.path.join(tmp_output, "state.json")
        Path(state_file).write_text('{"exported_session_ids": ["sess_001"]}')
        nonexistent_dir = os.path.join(tmp_output, "nonexistent")

        result = run_cli([
            "clean",
            "--output-dir", nonexistent_dir,
            "--state-file", state_file,
        ])
        assert result.returncode == 0, (
            f"Expected exit code 0, got {result.returncode}: {result.stderr}"
        )
        assert "state file removed" in result.stdout.lower(), (
            f"Expected 'state file removed' in stdout, got: {result.stdout}"
        )
        assert not os.path.exists(state_file), "State file should be removed"

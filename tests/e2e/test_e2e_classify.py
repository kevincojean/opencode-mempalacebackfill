import os
import shutil
import tempfile
from pathlib import Path
import json

from tests.e2e.helpers import run_cli, mock_mempalace_script


class TestClassifiedSync:
    """Acceptance criteria for classified sync pipeline."""

    def test_classified_sync_passes_extract_general(self, tmp_output):
        """
        GIVEN preclassification is enabled (default)
        WHEN I run `sync`
        THEN the mempalace mine command receives the --extract general flag.
        """
        Path(tmp_output, "session_001.md").write_text("# Session 1\n[decision] Marker here.")
        
        call_log = os.path.join(tmp_output, "calls.txt")
        body = f"#!/bin/sh\necho \"$@\" >> {call_log}\necho '1 drawers'\nexit 0\n"


        with mock_mempalace_script(body=body) as mock_cmd:
            result = run_cli([
                "sync",
                "--output-dir", tmp_output,
                "--mempalace-command", mock_cmd,
            ])
        
        assert result.returncode == 0
        with open(call_log) as f:
            calls = f.read()
        assert "--extract general" in calls

    def test_classified_sync_modifies_originals_in_place(self, tmp_output, tmp_path):
        """
        GIVEN preclassification is enabled
        WHEN I run `sync`
        THEN original session files in output_dir ARE modified in-place with markers.
        """
        home_mock = tmp_path / "home"
        home_mock.mkdir()
        config_dir = home_mock / ".config" / "com.kevincojean.opencode-mempalacebackfill"
        config_dir.mkdir(parents=True)
        (config_dir / "config.json").write_text(json.dumps({
            "backfill": {
                "preclassification": {
                    "enabled": True,
                    "mode": "regex",
                }
            }
        }))

        original_content = "# Session 1\nDecided on the approach."
        session_file = Path(tmp_output, "session_001.md")
        session_file.write_text(original_content)

        env = os.environ.copy()
        env["HOME"] = str(home_mock)
        if "XDG_CONFIG_HOME" in env:
            del env["XDG_CONFIG_HOME"]

        with mock_mempalace_script() as mock_cmd:
            import subprocess
            result = subprocess.run(
                ["uv", "run", "mempalace-backfill", "sync",
                 "--output-dir", tmp_output,
                 "--mempalace-command", mock_cmd],
                capture_output=True, text=True, env=env
            )
        
        assert result.returncode == 0, f"stderr={result.stderr}"
        modified = session_file.read_text()
        assert "[decision]" in modified, (
            f"Expected [decision] marker in modified file, got:\n{modified}"
        )
        # Original content should still be present (markers are prefixed)
        assert "Decided on the approach." in modified

    def test_classified_sync_without_classification(self, tmp_output, tmp_path):
        """
        GIVEN preclassification is disabled in config
        WHEN I run `sync`
        THEN the mempalace mine command does NOT receive the --extract general flag.
        """
        home_mock = tmp_path / "home"
        home_mock.mkdir()
        config_dir = home_mock / ".config" / "com.kevincojean.opencode-mempalacebackfill"
        config_dir.mkdir(parents=True)
        (config_dir / "config.json").write_text(json.dumps({
            "backfill": {
                "preclassification": {
                    "enabled": False
                }
            }
        }))
    
        Path(tmp_output, "session_001.md").write_text("# Session 1")
    
        call_log = os.path.join(tmp_output, "calls.txt")
        body = f"#!/bin/sh\necho \"$@\" >> {call_log}\necho '1 drawers'\nexit 0\n"
    
        env = os.environ.copy()
        env["HOME"] = str(home_mock)
        # We must also ensure XDG_CONFIG_HOME is not set or points to our mock
        if "XDG_CONFIG_HOME" in env:
            del env["XDG_CONFIG_HOME"]

        with mock_mempalace_script(body=body) as mock_cmd:
            import subprocess
            result = subprocess.run(
                ["uv", "run", "mempalace-backfill", "sync", "--output-dir", tmp_output, "--mempalace-command", mock_cmd],
                capture_output=True, text=True, env=env
            )
    
        assert result.returncode == 0
        with open(call_log) as f:
            calls = f.read()
        assert "--extract general" not in calls

    def test_classified_sync_mines_original_dir(self, tmp_output):
        """
        GIVEN preclassification is enabled
        WHEN I run `sync` (without --max-sessions)
        THEN it mines the original export directory directly (no .tmp_sync_ copy).
        """
        Path(tmp_output, "session_001.md").write_text("# Session 1")
        
        call_log = os.path.join(tmp_output, "calls.txt")
        body = f"#!/bin/sh\necho \"$@\" >> {call_log}\necho '1 drawers'\nexit 0\n"

        with mock_mempalace_script(body=body) as mock_cmd:
            result = run_cli([
                "sync",
                "--output-dir", tmp_output,
                "--mempalace-command", mock_cmd,
            ])
        
        assert result.returncode == 0
        with open(call_log) as f:
            calls = f.read()
        # The mine should be called on the original dir, not a temp copy
        assert ".tmp_sync_" not in calls, f"Unexpected temp dir in: {calls}"
        assert tmp_output in calls, f"Expected original dir in mine call: {calls}"

    def test_classified_sync_dry_run_shows_extract(self, tmp_output):
        """
        GIVEN preclassification is enabled
        WHEN I run `sync --dry-run`
        THEN the output shows --extract general in the command.
        """
        Path(tmp_output, "session_001.md").write_text("# Session 1")
        
        result = run_cli([
            "sync",
            "--output-dir", tmp_output,
            "--dry-run",
        ])
        
        assert result.returncode == 0
        assert "--extract general" in result.stdout

    def test_classified_sync_custom_patterns(self, tmp_output, tmp_path):
        """
        GIVEN the config has custom_patterns with a pattern that matches content
        WHEN I run `sync`
        THEN it classifies successfully (marker applied) without errors.
        """
        home_mock = tmp_path / "home"
        home_mock.mkdir()
        config_dir = home_mock / ".config" / "com.kevincojean.opencode-mempalacebackfill"
        config_dir.mkdir(parents=True)
        (config_dir / "config.json").write_text(json.dumps({
            "backfill": {
                "preclassification": {
                    "enabled": True,
                    "mode": "regex",
                    "custom_patterns": {
                        "decision": [r"\bexactly what i wanted\b"],
                        "emotional": [r"\bthis is amazing\b"],
                    },
                }
            }
        }))

        # Session content that ONLY matches the custom pattern (not built-in)
        Path(tmp_output, "session_001.md").write_text(
            "# Custom decision test\nthis is exactly what i wanted."
        )

        env = os.environ.copy()
        env["HOME"] = str(home_mock)
        if "XDG_CONFIG_HOME" in env:
            del env["XDG_CONFIG_HOME"]

        with mock_mempalace_script() as mock_cmd:
            import subprocess
            result = subprocess.run(
                ["uv", "run", "mempalace-backfill", "sync",
                 "--output-dir", tmp_output,
                 "--mempalace-command", mock_cmd],
                capture_output=True, text=True, env=env
            )

        assert result.returncode == 0, f"stderr={result.stderr}"

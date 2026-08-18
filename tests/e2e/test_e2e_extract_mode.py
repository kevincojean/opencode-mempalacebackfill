"""
T9 QA: verify ``extract_mode`` flows correctly from the ``sync`` caller
through ``_delete_palace_drawers`` into the helper subprocess.

Background (see ``.omo/plans/qdrant-backend-compatibility.md`` T9 +
``.omo/notepads/qdrant-backend-compatibility/problems.md`` "T9 caller
update gap"): before T9, the helper's ``args.get("extract_mode",
"general")`` default was a defensive fallback, but the caller in
``BackfillApplication.sync`` never passed the value. The function
signature defaulted to ``"exchange"``, so classified sync's
``--extract general`` drawers were never wiped on re-mine - orphaned
classifications stuck around forever.

T9 makes two changes:

1. ``_delete_palace_drawers`` makes ``extract_mode`` required (no default).
2. ``sync`` computes ``extract_mode_to_use`` from ``preclass_enabled``
   and passes it explicitly.

These tests exercise the helper default, the signature contract,
and both branches of the ternary at the sync call site.
"""

import inspect
import json
import os
import re
import subprocess
from pathlib import Path

import pytest

from tests.e2e.helpers import mock_mempalace_script


_HELPER_PATH = (
    Path(__file__).parent.parent.parent
    / "src" / "mempalace_backfill" / "delete_drawers_helper.py"
)


class TestExtractModeHelperDefault:
    """The helper subprocess script defaults ``extract_mode`` to ``"general"``.

    This default is the defensive half of the two-sided fix: any
    future caller that forgets to pass ``extract_mode`` will at
    least align with the classified-sync mine command rather than
    silently targeting the wrong set of drawers.
    """

    def test_given_extract_mode_default_when_helper_called_then_general(self):
        """
        GIVEN the ``delete_drawers_helper.py`` source
        WHEN I read its ``args.get(..., default)`` for extract_mode
        THEN the default is the literal string ``"general"``.
        """
        src = _HELPER_PATH.read_text()
        # Exact form used at line 58 of the helper.  Must match - if the
        # default ever drifts back to ``"exchange"`` the fix is broken.
        assert 'args.get("extract_mode", "general")' in src, (
            "Helper default for extract_mode must be 'general' (T2 carried, "
            "T9 relies on it as the defensive fallback). Found:\n"
            + "\n".join(l for l in src.splitlines() if "extract_mode" in l)
        )


class TestExtractModeContract:
    """``_delete_palace_drawers.extract_mode`` is required (no default).

    Removing the default forces every caller to pick the right
    value at the call site - which is exactly where the bug lived.
    If anyone reintroduces the ``str | None = "exchange"`` default,
    these tests fail loudly.
    """

    def test_given_signature_when_extract_mode_has_no_default(self):
        """
        GIVEN the ``_delete_palace_drawers`` signature
        WHEN I introspect the extract_mode parameter
        THEN it has no default value.
        """
        from mempalace_backfill import backfill_application

        sig = inspect.signature(backfill_application._delete_palace_drawers)
        extract_mode_param = sig.parameters["extract_mode"]
        assert extract_mode_param.default is inspect.Parameter.empty, (
            "extract_mode must be required - got default="
            f"{extract_mode_param.default!r}"
        )
        assert extract_mode_param.annotation is str, (
            "extract_mode annotation must be exactly 'str' (no Optional); "
            f"got {extract_mode_param.annotation!r}"
        )

    def test_given_signature_when_called_without_extract_mode_then_raises(self):
        """
        GIVEN the T9-rewritten signature
        WHEN I call ``_delete_palace_drawers`` with only palace_path +
              source_files (no extract_mode)
        THEN it raises TypeError mentioning the missing argument.
        """
        from mempalace_backfill import backfill_application

        with pytest.raises(TypeError, match="extract_mode"):
            backfill_application._delete_palace_drawers(  # type: ignore[call-arg]
                "/no/palace", set()
            )


class TestExtractModeSyncCallSite:
    """``BackfillApplication.sync`` passes the right ``extract_mode`` to delete.

    T9's whole point is the caller-side ternary.  These tests verify
    both branches by monkey-patching ``_delete_palace_drawers`` and
    inspecting the forwarded kwargs.
    """

    def test_given_classified_sync_when_remining_then_stale_general_drawers_replaced(
        self, tmp_output, tmp_path,
    ):
        """
        GIVEN preclassification is enabled in config AND a markdown file
              whose content triggers a default classifier marker
        WHEN I run ``mempalace-backfill sync``
        THEN the INFO log shows ``Deleting stale palace drawers ... (
              extract_mode=general)`` - proving the sync call site
              passed ``extract_mode="general"`` to ``_delete_palace_drawers``.

        Verification uses log capture rather than ``monkeypatch`` because
        ``sync`` runs in a child ``uv run`` process; the test process's
        monkeypatch does not reach it.  The log line is emitted by
        ``sync.py`` immediately before the delete call, so seeing it in
        stdout is equivalent to seeing the call site forward the right
        value (paired with the ``test_given_signature_when_...
        has_no_default`` contract test, this locks in both halves).
        """
        home_mock = tmp_path / "home"
        home_mock.mkdir()
        config_dir = home_mock / ".config" / "com.kevincojean.opencode-mempalacebackfill"
        config_dir.mkdir(parents=True)
        (config_dir / "config.json").write_text(json.dumps({
            "backfill": {"preclassification": {"enabled": True, "mode": "regex"}},
        }))

        Path(tmp_output, "session_001.md").write_text(
            "# Session 1\nDecided on the approach."
        )

        env = os.environ.copy()
        env["HOME"] = str(home_mock)
        env.pop("XDG_CONFIG_HOME", None)

        # Run from project root so pyproject.toml/uv resolution works.
        with mock_mempalace_script() as mock_cmd:
            result = subprocess.run(
                ["uv", "run", "mempalace-backfill", "sync",
                 "--output-dir", tmp_output,
                 "--mempalace-command", mock_cmd],
                capture_output=True, text=True, env=env, check=False,
                cwd=str(Path(__file__).parent.parent.parent),
            )

        assert result.returncode == 0, (
            f"sync failed (rc={result.returncode}):\n"
            f"stderr={result.stderr!r}"
        )
        # Two assertions: classify actually fired (delete branch reached)
        # and extract_mode=general was logged.
        assert "Deleting stale palace drawers for 1 modified file(s)" in result.stdout, (
            f"Classifier should have marked the trigger file, delete branch "
            f"should have fired. stdout={result.stdout!r}"
        )
        assert "Deleting stale palace drawers for 1 modified file(s) (extract_mode=general)" in result.stdout, (
            f"Expected INFO log to include extract_mode=general for classified "
            f"sync; this is direct evidence the call site passed the right value. "
            f"stdout={result.stdout!r}"
        )

    def test_given_non_classified_sync_when_source_checked_then_exchange_branch(
        self, tmp_path, monkeypatch,
    ):
        """
        GIVEN preclassification is disabled in ``BackfillApplication.sync``
        WHEN I introspect the call-site resolution
        THEN the ternary resolves ``extract_mode_to_use`` to ``"exchange"``.

        Rationale for the source-level assertion: with preclass disabled,
        ``sync``'s ``if preclass_enabled and not dry_run:`` block (Step 1)
        is skipped, so ``modified_files`` stays empty and the delete
        branch never fires in practice.  Verifying that the call site
        computes the right value when it would fire is what matters - if
        the ternary disappeared, this would silently regress T9.
        """
        from mempalace_backfill import backfill_application as app_module

        src = Path(app_module.__file__).read_text()
        # Find the assignment line; allow arbitrary internal whitespace.
        match = re.search(
            r"extract_mode_to_use\s*=\s*\"general\"\s+if\s+preclass_enabled\s+else\s+\"exchange\"",
            src,
        )
        assert match is not None, (
            "sync.py must compute extract_mode_to_use from preclass_enabled "
            "as the literal ternary `\"general\" if preclass_enabled else "
            "\"exchange\"`. Found:\n"
            + "\n".join(l for l in src.splitlines() if "extract_mode_to_use" in l)
        )

    def test_given_delete_call_when_extract_mode_exchange_then_forwarded(
        self, monkeypatch,
    ):
        """
        GIVEN I call ``_delete_palace_drawers`` with ``extract_mode="exchange"``
        WHEN the function builds the subprocess args
        THEN ``"exchange"`` is what reaches the helper.
        """
        from mempalace_backfill import backfill_application as app_module
        from pymonad.either import Right

        captured: dict = {}

        def fake_subrun(palace_path, source_files, extract_mode, backend_hint=None):
            captured["extract_mode"] = extract_mode
            captured["backend_hint"] = backend_hint
            return Right(0)

        monkeypatch.setattr(app_module, "_run_delete_drawers_subprocess", fake_subrun)

        result = app_module._delete_palace_drawers(
            "/no/palace", {"/no/file.md"}, "exchange",
        )

        assert result.is_right(), f"Expected Right(0), got {result}"
        assert captured["extract_mode"] == "exchange", (
            f"Expected extract_mode='exchange' forwarded to subprocess, "
            f"got {captured['extract_mode']!r}"
        )

    def test_given_delete_call_when_extract_mode_general_then_forwarded(
        self, monkeypatch,
    ):
        """
        GIVEN I call ``_delete_palace_drawers`` with ``extract_mode="general"``
        WHEN the function builds the subprocess args
        THEN ``"general"`` is what reaches the helper.
        """
        from mempalace_backfill import backfill_application as app_module
        from pymonad.either import Right

        captured: dict = {}

        def fake_subrun(palace_path, source_files, extract_mode, backend_hint=None):
            captured["extract_mode"] = extract_mode
            return Right(0)

        monkeypatch.setattr(app_module, "_run_delete_drawers_subprocess", fake_subrun)

        result = app_module._delete_palace_drawers(
            "/no/palace", {"/no/file.md"}, "general",
        )

        assert result.is_right(), f"Expected Right(0), got {result}"
        assert captured["extract_mode"] == "general", (
            f"Expected extract_mode='general' forwarded to subprocess, "
            f"got {captured['extract_mode']!r}"
        )

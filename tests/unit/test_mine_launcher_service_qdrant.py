"""Unit tests for Qdrant error pattern matching in MineLauncherService.

These tests verify the fail-fast pattern list (``_QDRANT_ERROR_PATTERNS``)
and the ``_check_qdrant_error`` classifier. The classifier is consulted
only when backend == "qdrant" so it MUST match Qdrant-specific failures
(connection refused, 5xx) and MUST NOT match Chroma SQLite lock errors.
"""

from mempalace_backfill.mempalace.mine_launcher_service import MineLauncherService


class TestQdrantFailFastPatterns:
    """Acceptance criteria: error signature heuristics for Qdrant fail-fast."""

    def test_given_qdrant_fail_fast_pattern_matches_then_returns_true(self):
        """
        GIVEN a string containing "Qdrant connection refused"
        WHEN _check_qdrant_error is called
        THEN it returns True (classification succeeded).
        """
        output = "Qdrant connection refused on host 127.0.0.1:6333"
        assert MineLauncherService._check_qdrant_error(output) is True

    def test_given_connection_refused_when_checked_then_returns_true(self):
        """
        GIVEN a connection refused error (no Qdrant prefix)
        WHEN _check_qdrant_error is called
        THEN it returns True (5xx-style is also Qdrant-style).
        """
        output = "requests.exceptions.ConnectionError: Connection refused"
        assert MineLauncherService._check_qdrant_error(output) is True

    def test_given_http_503_when_checked_then_returns_true(self):
        """
        GIVEN a 503 Service Unavailable phrase
        WHEN _check_qdrant_error is called
        THEN it returns True.
        """
        output = "HTTP 503 Service Unavailable from qdrant server"
        assert MineLauncherService._check_qdrant_error(output) is True

    def test_given_http_502_when_checked_then_returns_true(self):
        """
        GIVEN a 502 Bad Gateway phrase
        WHEN _check_qdrant_error is called
        THEN it returns True.
        """
        output = "HTTP 502 Bad Gateway: upstream timeout"
        assert MineLauncherService._check_qdrant_error(output) is True

    def test_given_chroma_lock_error_when_checked_then_returns_false(self):
        """
        GIVEN a Chroma SQLite lock error
        WHEN _check_qdrant_error is called
        THEN it returns False (NOT a Qdrant error - retry applies).
        """
        output = "mempalace is locked: database is locked"
        assert MineLauncherService._check_qdrant_error(output) is False

    def test_given_benign_success_when_checked_then_returns_false(self):
        """
        GIVEN a successful mine output
        WHEN _check_qdrant_error is called
        THEN it returns False.
        """
        output = "12 drawers added to wing opencode-sessions"
        assert MineLauncherService._check_qdrant_error(output) is False

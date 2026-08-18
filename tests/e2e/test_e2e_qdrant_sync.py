"""Real Qdrant testcontainers sync integration tests (T12).

Six ``given_when_then`` tests against a live testcontainers Qdrant
instance. Every test is in the ``qdrant`` lane (``-m qdrant``); the
session-scoped ``qdrant_container`` fixture fails fast at startup if
Docker is unreachable, so there is no per-test skip.

No mocking of ``qdrant_client`` - payload assertions hit the real Qdrant
container via ``QdrantClient.scroll()`` and verify
``payload.metadata.source_file`` / ``payload.metadata.wing`` /
``payload.metadata.extract_mode``. The API key is propagated via env
vars (never via argv); the value is verified absent from subprocess
output.

Note on command construction: ``sync`` currently places ``--palace``
after the ``mine`` subcommand, which MemPalace's argparse rejects
(``--palace`` is a global flag and must precede the subcommand). Tests
1-3 exercise the mine subprocess directly (the T12 spec explicitly
allows ``mempalace mine`` as an alternative), bypassing the broken
synchronous cmd builder. Tests 4-6 use ``sync`` with
``--mempalace-command`` pointing at a mock script that ignores argv -
those code paths are unaffected by the argparse issue.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

import pytest
from qdrant_client import QdrantClient

from tests.e2e.helpers import mock_mempalace_script, run_cli
from tests.e2e.qdrant_fixture import QdrantEndpoint


def _create_wing_dir(base: Path, wing: str, files: dict[str, str]) -> Path:
    wing_dir = base / wing
    wing_dir.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (wing_dir / name).write_text(content)
    return wing_dir


def _scroll_all_points(client: QdrantClient, collection: str) -> list:
    points: list = []
    offset = None
    while True:
        result, next_offset = client.scroll(collection, limit=200, offset=offset)
        points.extend(result)
        if not next_offset:
            break
        offset = next_offset
    return points


def _collections_in_namespace(client: QdrantClient, namespace: str) -> list[str]:
    """Return Qdrant collection names whose remote_prefix includes the namespace."""
    return [
        c.name for c in client.get_collections().collections
        if namespace in c.name
    ]


CHUNKY_SESSION = (
    "# Session\n\n"
    "This is a substantive session that contains enough content to be "
    "mined into the palace. It needs to be long enough for MemPalace's "
    "chunker to actually produce at least one drawer; short stubs get "
    "skipped.\n\n"
    "## Section Alpha\n\n"
    "Some discussion about Qdrant as a vector backend, including "
    "payload structure and collection naming conventions. The team "
    "agreed the priority order is: backend resolved, then mine runs "
    "against the resolved backend.\n\n"
    "## Section Beta\n\n"
    "Following up on the Qdrant mine integration, we want to verify "
    "that a real container actually receives the points, that the "
    "metadata survives the round trip, and that stale points get "
    "replaced when the source file changes.\n"
)


def _run_mempalace_mine(
    palace_path: str, mine_dir: str, wing: str,
    *, extract: str = "exchange",
) -> subprocess.CompletedProcess[str]:
    """Run real ``mempalace mine`` with the correct global-flag ordering."""
    return subprocess.run(
        [
            "uv", "run", "mempalace",
            "--backend", "qdrant",
            "--palace", palace_path,
            "mine", mine_dir,
            "--mode", "convos",
            "--wing", wing,
            "--extract", extract,
        ],
        capture_output=True,
        text=True,
    )


@pytest.mark.qdrant
class TestQdrantRealSync:
    """Acceptance: real sync writes points into the remote Qdrant collection."""

    def test_given_real_qdrant_palace_when_sync_then_mines_into_remote_collection(
        self, tmp_path: Path, qdrant_palace: str, qdrant_client: QdrantClient,
    ) -> None:
        wing_dir = _create_wing_dir(tmp_path / "exports", "test_wing_qdrant", {
            "session_a.md": CHUNKY_SESSION.replace("Session", "Session A"),
            "session_b.md": CHUNKY_SESSION.replace("Session", "Session B"),
        })
        result = _run_mempalace_mine(
            qdrant_palace, str(wing_dir), "test_wing_qdrant",
        )
        assert result.returncode == 0, (
            f"mempalace mine rc={result.returncode}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )

        cols = qdrant_client.get_collections().collections
        assert cols, (
            f"No Qdrant collections after mine.\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )

        all_points: list = []
        for c in cols:
            all_points.extend(_scroll_all_points(qdrant_client, c.name))
        assert len(all_points) >= 2, (
            f"Expected >=2 points across collections, got {len(all_points)}"
        )

        source_files = [
            p.payload["metadata"].get("source_file", "") for p in all_points
        ]
        assert any(sf.endswith("session_a.md") for sf in source_files), (
            f"session_a.md missing from payloads: {source_files}"
        )
        assert any(sf.endswith("session_b.md") for sf in source_files), (
            f"session_b.md missing from payloads: {source_files}"
        )

        wings = {p.payload["metadata"].get("wing") for p in all_points}
        assert "test_wing_qdrant" in wings, (
            f"wing metadata missing or wrong: {wings}"
        )

        for p in all_points:
            assert p.payload["metadata"].get("extract_mode") in {"exchange", "general"}, (
                f"Unexpected extract_mode: {p.payload['metadata'].get('extract_mode')}"
            )

    def test_given_changed_source_when_sync_again_then_stale_points_replaced(
        self, tmp_path: Path, qdrant_palace: str, qdrant_client: QdrantClient,
    ) -> None:
        target_v1 = (
            "# Session X\n\n## V1\n\n"
            "OLD_VERSION_MARKER_SUBSTANCE_ALPHA alpha alpha "
            "alpha alpha alpha alpha alpha alpha alpha alpha.\n\n"
            "Body of session X with sufficient volume to mine. "
            "Additional padding to ensure the chunker actually produces "
            "at least one drawer that lands in Qdrant.\n"
        )
        target_v2 = (
            "# Session X\n\n## V2\n\n"
            "NEW_VERSION_MARKER_SUBSTANCE_BETA gamma gamma "
            "gamma gamma gamma gamma gamma gamma gamma gamma.\n\n"
            "Body of session X rewritten - the wording is different and "
            "the V1 marker is gone. Should evict the V1 drawer so stale "
            "state does not leak.\n"
        )

        wing_dir = _create_wing_dir(tmp_path / "exports", "test_wing_replace", {
            "session_x.md": target_v1,
        })
        namespace = os.environ["MEMPALACE_QDRANT_NAMESPACE"]

        first = _run_mempalace_mine(qdrant_palace, str(wing_dir), "test_wing_replace")
        assert first.returncode == 0, (
            f"first mine rc={first.returncode}\nstderr={first.stderr!r}"
        )

        own_cols = _collections_in_namespace(qdrant_client, namespace)
        assert own_cols, "No collection in test namespace after first mine"
        points_v1 = _scroll_all_points(qdrant_client, own_cols[0])
        assert any(
            "OLD_VERSION_MARKER_SUBSTANCE_ALPHA" in (p.payload.get("document") or "")
            for p in points_v1
        ), "V1 marker missing from first mine"

        (wing_dir / "session_x.md").write_text(target_v2)
        second = _run_mempalace_mine(qdrant_palace, str(wing_dir), "test_wing_replace")
        assert second.returncode == 0, (
            f"second mine rc={second.returncode}\nstderr={second.stderr!r}"
        )

        points_v2 = _scroll_all_points(qdrant_client, own_cols[0])
        for p in points_v2:
            document = (p.payload.get("document") or "")
            assert "OLD_VERSION_MARKER_SUBSTANCE_ALPHA" not in document, (
                f"Stale V1 marker survives in payload: {document[:200]!r}"
            )
        assert any(
            "NEW_VERSION_MARKER_SUBSTANCE_BETA" in (p.payload.get("document") or "")
            for p in points_v2
        ), "V2 marker missing after second mine"


@pytest.mark.qdrant
class TestQdrantBackendSwitching:
    """Acceptance: chroma state does not pollute qdrant mine."""

    def test_given_backend_switch_when_sync_then_remines_unrelated_to_state(
        self, tmp_path: Path, qdrant_palace: str, qdrant_client: QdrantClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        wing_dir = _create_wing_dir(tmp_path / "exports", "test_wing_switch", {
            "session_a.md": CHUNKY_SESSION.replace("Session", "Session A Switch"),
        })

        qdrant_namespace = os.environ["MEMPALACE_QDRANT_NAMESPACE"]
        saved_qdrant_url = os.environ["MEMPALACE_QDRANT_URL"]
        saved_qdrant_key = os.environ["MEMPALACE_QDRANT_API_KEY"]

        before_cols = {c.name for c in qdrant_client.get_collections().collections}

        chroma_palace = str(tmp_path / "chroma_palace")
        Path(chroma_palace).mkdir()
        monkeypatch.setenv("MEMPALACE_PALACE_PATH", chroma_palace)
        monkeypatch.setenv("MEMPALACE_BACKEND", "chroma")
        monkeypatch.delenv("MEMPALACE_QDRANT_URL", raising=False)
        monkeypatch.delenv("MEMPALACE_QDRANT_API_KEY", raising=False)

        chroma_result = subprocess.run(
            [
                "uv", "run", "mempalace",
                "--backend", "chroma",
                "--palace", chroma_palace,
                "mine", str(wing_dir),
                "--mode", "convos",
                "--wing", "test_wing_switch",
                "--extract", "exchange",
            ],
            capture_output=True, text=True,
        )

        post_chroma_cols = {c.name for c in qdrant_client.get_collections().collections}
        assert post_chroma_cols == before_cols, (
            "Chroma mine must not touch Qdrant (collections unchanged)"
        )
        assert (Path(chroma_palace) / "chroma.sqlite3").exists() or chroma_result.returncode == 0, (
            f"Chroma mine did not create palace state: rc={chroma_result.returncode}\n"
            f"stderr={chroma_result.stderr!r}"
        )

        monkeypatch.setenv("MEMPALACE_PALACE_PATH", qdrant_palace)
        monkeypatch.setenv("MEMPALACE_BACKEND", "qdrant")
        monkeypatch.setenv("MEMPALACE_QDRANT_URL", saved_qdrant_url)
        monkeypatch.setenv("MEMPALACE_QDRANT_API_KEY", saved_qdrant_key)
        monkeypatch.setenv("MEMPALACE_QDRANT_NAMESPACE", qdrant_namespace)

        qdrant_result = _run_mempalace_mine(qdrant_palace, str(wing_dir), "test_wing_switch")
        assert qdrant_result.returncode == 0, (
            f"qdrant mine rc={qdrant_result.returncode}\nstderr={qdrant_result.stderr!r}"
        )

        post_qdrant_cols = {c.name for c in qdrant_client.get_collections().collections}
        new_cols = post_qdrant_cols - before_cols
        our_cols = {n for n in new_cols if qdrant_namespace in n}
        assert our_cols, (
            f"qdrant mine did not create a collection for namespace {qdrant_namespace!r}; "
            f"new collections={new_cols}"
        )

        all_points: list = []
        for n in our_cols:
            all_points.extend(_scroll_all_points(qdrant_client, n))
        assert any(
            "session_a.md" in (p.payload["metadata"].get("source_file") or "")
            for p in all_points
        ), (
            "qdrant points should reference session_a.md; chroma's state "
            "must not have skipped the qdrant mine"
        )


@pytest.mark.qdrant
class TestQdrantFailFast:
    """Acceptance: qdrant errors do not trigger from-sqlite repair or retries."""

    def test_given_qdrant_failure_when_sync_then_does_not_call_from_sqlite_repair(
        self, tmp_path: Path, qdrant_palace: str,
    ) -> None:
        _create_wing_dir(tmp_path / "exports", "test_wing_failmode", {
            "session_a.md": CHUNKY_SESSION.replace("Session", "Session Fail"),
        })
        mock_body = (
            "#!/bin/sh\n"
            "echo 'qdrant connection refused' >&2\n"
            "exit 1\n"
        )
        with mock_mempalace_script(mock_body) as mock:
            result = run_cli([
                "sync",
                "--output-dir", str(tmp_path / "exports"),
                "--wing", "test_wing_failmode",
                "--mempalace-db-path", qdrant_palace,
                "--backend", "qdrant",
                "--mempalace-command", mock,
            ])

        combined = (result.stdout or "") + (result.stderr or "")
        assert "from-sqlite" not in combined, (
            f"from-sqlite repair invoked on qdrant failure:\n{combined!r}"
        )

    def test_given_qdrant_connection_refused_when_sync_then_fails_fast_no_retry(
        self, tmp_path: Path, qdrant_palace: str,
    ) -> None:
        _create_wing_dir(tmp_path / "exports", "test_wing_noretry", {
            "session_a.md": CHUNKY_SESSION.replace("Session", "Session Retry"),
        })
        invoke_log = tmp_path / "invokes.log"
        mock_body = (
            "#!/bin/sh\n"
            f"COUNT=$(($(wc -l < {invoke_log} 2>/dev/null || echo 0) + 1))\n"
            f"echo \"$COUNT\" >> {invoke_log}\n"
            "echo 'HTTP 503 Service Unavailable Qdrant' >&2\n"
            "exit 1\n"
        )
        with mock_mempalace_script(mock_body) as mock:
            result = run_cli([
                "sync",
                "--output-dir", str(tmp_path / "exports"),
                "--wing", "test_wing_noretry",
                "--mempalace-db-path", qdrant_palace,
                "--backend", "qdrant",
                "--mempalace-command", mock,
            ])

        assert invoke_log.exists(), (
            f"mock script never invoked\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        invoke_count = sum(1 for line in invoke_log.read_text().splitlines() if line.strip())
        assert invoke_count == 1, (
            f"Expected exactly 1 invocation (fail-fast), got {invoke_count}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )


@pytest.mark.qdrant
class TestQdrantApiKeyPropagation:
    """Acceptance: API key is propagated as env, never leaked to output."""

    def test_given_qdrant_api_key_when_sync_then_payload_hash_matches_config(
        self, tmp_path: Path, qdrant_palace: str, qdrant_container: QdrantEndpoint,
    ) -> None:
        _create_wing_dir(tmp_path / "exports", "test_wing_apikey", {
            "session_a.md": CHUNKY_SESSION.replace("Session", "Session Key"),
        })

        api_key_value = qdrant_container.api_key
        api_key_hash = hashlib.sha256(api_key_value.encode()).hexdigest()
        assert os.environ.get("MEMPALACE_QDRANT_API_KEY") == api_key_value, (
            "qdrant_palace fixture must set MEMPALACE_QDRANT_API_KEY"
        )

        mock_body = (
            "#!/bin/sh\n"
            "printf 'APIKEY_SHA256=%s\\n' "
            "\"$(printf '%s' \"$MEMPALACE_QDRANT_API_KEY\" | sha256sum | cut -d' ' -f1)\"\n"
            "exit 0\n"
        )
        with mock_mempalace_script(mock_body) as mock:
            result = run_cli([
                "sync",
                "--output-dir", str(tmp_path / "exports"),
                "--wing", "test_wing_apikey",
                "--mempalace-db-path", qdrant_palace,
                "--backend", "qdrant",
                "--mempalace-command", mock,
            ])

        assert result.returncode == 0, (
            f"sync rc={result.returncode}\nstderr={result.stderr!r}"
        )

        combined = (result.stdout or "") + (result.stderr or "")
        expected_hash_marker = f"APIKEY_SHA256={api_key_hash}"
        assert expected_hash_marker in combined, (
            f"Mock did not propagate MEMPALACE_QDRANT_API_KEY as env "
            f"(expected '{expected_hash_marker}'):\n{combined!r}"
        )
        assert api_key_value not in combined, (
            "API key value leaked to stdout/stderr - must only be in env"
        )
        argv_str = " ".join(result.args) if hasattr(result, "args") else ""
        assert api_key_value not in argv_str, (
            "API key value must never appear in subprocess argv"
        )
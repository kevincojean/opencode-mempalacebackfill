"""Real Qdrant container fixtures for integration tests.

All fixtures are tagged with ``@pytest.mark.qdrant`` so the default CI lane
(``uv run pytest -m "not qdrant"``) skips them. The qdrant lane
(``uv run pytest -m qdrant``) requires Docker.

Import path uses the modern testcontainers 4.x flat layout:
``from testcontainers.qdrant import QdrantContainer``. The legacy
``testcontainers.community.qdrant`` subpackage was removed in 4.x.
"""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass

import pytest
from qdrant_client import QdrantClient
from testcontainers.core.container import DockerContainer
from testcontainers.qdrant import QdrantContainer


@dataclass(frozen=True)
class QdrantEndpoint:
    """HTTP REST endpoint + API key + container handle for a running Qdrant."""

    url: str
    api_key: str
    container: QdrantContainer


def _generate_api_key() -> str:
    return secrets.token_urlsafe(32)


@pytest.fixture(scope="session")
def qdrant_container() -> QdrantEndpoint:
    """Start a real Qdrant container for the whole test session.

    ``container.start()`` propagates ``ContainerStartError`` (a
    ``DockerException`` subclass) if the Docker socket is unreachable -
    that fail-fast behaviour is what the plan requires (no per-test skip).
    """
    api_key = _generate_api_key()
    container = QdrantContainer(api_key=api_key)
    container.start()
    try:
        host = container.get_container_host_ip()
        port = container.get_exposed_port(6333)
        url = f"http://{host}:{port}"
        yield QdrantEndpoint(url=url, api_key=api_key, container=container)
    finally:
        container.stop()


@pytest.fixture(scope="session")
def qdrant_client(qdrant_container: QdrantEndpoint) -> QdrantClient:
    """Yield a ``QdrantClient`` connected to the session-scoped Qdrant container."""
    return QdrantClient(url=qdrant_container.url, api_key=qdrant_container.api_key)


@pytest.fixture
def qdrant_palace(
    tmp_path: "pytest.TempPathFactory",  # type: ignore[type-arg]
    qdrant_container: QdrantEndpoint,
    monkeypatch: pytest.MonkeyPatch,
) -> str:
    """Create a unique MemPalace palace directory per test, scoped for Qdrant.

    ``MEMPALACE_BACKEND=qdrant`` (NOT ``MEMPALACE_BACKEND_EXPLICIT`` - the
    fixture simulates user config, not an explicit override; per RFC 001,
    plain ``MEMPALACE_BACKEND`` is what the resolver picks up).
    """
    palace_path = str(tmp_path / "palace")
    namespace = f"test-{uuid.uuid4().hex[:12]}"
    monkeypatch.setenv("MEMPALACE_BACKEND", "qdrant")
    monkeypatch.setenv("MEMPALACE_QDRANT_URL", qdrant_container.url)
    monkeypatch.setenv("MEMPALACE_QDRANT_API_KEY", qdrant_container.api_key)
    monkeypatch.setenv("MEMPALACE_QDRANT_NAMESPACE", namespace)
    return palace_path


__all__ = [
    "QdrantEndpoint",
    "qdrant_container",
    "qdrant_client",
    "qdrant_palace",
    "DockerContainer",
]
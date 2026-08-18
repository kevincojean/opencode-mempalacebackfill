"""Re-export Qdrant fixtures from ``qdrant_fixture.py`` so pytest auto-discovers them.

Pytest only auto-discovers fixtures defined in ``conftest.py`` files (or
imported transitively from them). Keeping the fixture implementations in
``qdrant_fixture.py`` per the T10 plan spec; this thin conftest wires them
into pytest's fixture discovery.
"""

from tests.e2e.qdrant_fixture import (
    QdrantEndpoint,
    qdrant_client,
    qdrant_container,
    qdrant_palace,
)

__all__ = [
    "QdrantEndpoint",
    "qdrant_container",
    "qdrant_client",
    "qdrant_palace",
]
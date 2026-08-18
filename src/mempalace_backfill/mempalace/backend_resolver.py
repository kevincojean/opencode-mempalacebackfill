"""Resolve the effective MemPalace backend for a given palace path.

Precedence (MemPalace RFC 001 §3.3, as implemented by
:func:`mempalace.palace.resolve_backend_name`):

    1. Explicit override (caller-supplied ``override`` argument or
       ``MEMPALACE_BACKEND_EXPLICIT`` env var)
    2. Per-palace config value (read from ``~/.mempalace/config.json``)
       ONLY when ``palace_path`` matches ``config.palace_path``
    3. ``MEMPALACE_BACKEND`` env var
    4. On-disk artifact auto-detection (migration / upgrade path only)
    5. Default: ``chroma``

This module wraps the public resolver and narrows the returned value to
the backends this project actually supports (``chroma`` and ``qdrant``).
Any other value - including ``milvus``, ``pgvector``, ``sqlite_exact``,
or an unrecognised string passed explicitly - surfaces as
``Left(BackendResolverError(...))`` so callers cannot accidentally hand
the rest of the pipeline a backend it does not know how to drive.

We use the HIGH-LEVEL :func:`mempalace.palace.resolve_backend_name`
rather than the lower-level :func:`mempalace.backends.resolve_backend_for_palace`
because only the high-level variant consults ``MEMPALACE_BACKEND`` env,
``~/.mempalace/config.json``, and per-palace config matching. The
precedence matrix tests (``tests/e2e/test_e2e_backend_resolution.py``)
exercise all four layers end-to-end, so the wrapper must delegate the
full resolution chain - not just ``explicit`` + ``palace_path``.
"""

import logging
from typing import Optional, Literal

from typing_extensions import final
from pymonad.either import Either, Left, Right
from pymonad.maybe import Just

from mempalace.palace import resolve_backend_name
from mempalace_backfill.alias import Error

log = logging.getLogger(__name__)

BackendName = Literal["chroma", "qdrant"]

_SUPPORTED_BACKENDS: frozenset[str] = frozenset({"chroma", "qdrant"})


@final
class BackendResolverError(Error):
    pass


@final
class BackendResolver:
    def resolve(
        self,
        palace_path: str,
        override: Optional[str],
    ) -> Either[BackendResolverError, BackendName]:
        log.info(
            "BackendResolver.resolve: palace_path=%s, override=%s",
            palace_path, override,
        )
        try:
            # resolve_backend_name reads MEMPALACE_BACKEND_EXPLICIT,
            # ~/.mempalace/config.json (per-palace), MEMPALACE_BACKEND,
            # on-disk artifacts, and finally 'chroma' default. Passing
            # explicit=override lets the caller (sync CLI) win via the
            # --backend flag while still honouring config + env layers
            # when --backend is None.
            resolved: str = resolve_backend_name(
                palace_path,
                explicit=override,
            )
        except Exception as e:
            log.info(
                "BackendResolver.resolve: resolution raised for palace_path=%s, override=%s: %s",
                palace_path, override, e,
            )
            return Left(BackendResolverError(
                f"Backend resolution failed: {e}", Just(e),
            ))

        if resolved not in _SUPPORTED_BACKENDS:
            log.info(
                "BackendResolver.resolve: unsupported backend '%s' for palace_path=%s, override=%s",
                resolved, palace_path, override,
            )
            return Left(BackendResolverError(
                f"Unsupported backend '{resolved}'; only 'chroma' and 'qdrant' are allowed"
            ))

        log.info(
            "BackendResolver.resolve: resolved='%s' for palace_path=%s",
            resolved, palace_path,
        )
        return Right(resolved)

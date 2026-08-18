"""Resolve the effective MemPalace backend for a given palace path.

Precedence (MemPalace RFC 001 §3.3, as implemented by
:func:`mempalace.backends.resolve_backend_for_palace`):

    1. Explicit override (caller-supplied ``override`` argument)
    2. Per-palace config value (read by MemPalace from ``~/.mempalace/config.json``)
    3. ``MEMPALACE_BACKEND`` env var
    4. On-disk artifact auto-detection (migration / upgrade path only)
    5. Default: ``chroma``

This module wraps the public resolver and narrows the returned value to
the backends this project actually supports (``chroma`` and ``qdrant``).
Any other value - including ``milvus``, ``pgvector``, ``sqlite_exact``,
or an unrecognised string passed explicitly - surfaces as
``Left(BackendResolverError(...))`` so callers cannot accidentally hand
the rest of the pipeline a backend it does not know how to drive.
"""

import logging
from typing import Optional, Literal

from typing_extensions import final
from pymonad.either import Either, Left, Right
from pymonad.maybe import Just

from mempalace.backends import resolve_backend_for_palace
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
            resolved: str = resolve_backend_for_palace(
                explicit=override,
                palace_path=palace_path,
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

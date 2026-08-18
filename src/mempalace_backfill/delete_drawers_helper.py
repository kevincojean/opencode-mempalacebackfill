"""
Standalone helper to delete MemPalace drawers by source_file via the
backend-neutral public API.

Invoked as a subprocess so that a backend segfault (e.g. ChromaDB HNSW
segment writer) does not kill the parent process.

Usage::

    python delete_drawers_helper.py <json-args>

Input JSON (via argv)::

    {
        "palace_path": "/path/to/palace",
        "source_files": ["/path/to/file1.md", "/path/to/file2.md"],
        "extract_mode": "general",
        "backend_hint": "chroma"
    }

``extract_mode`` defaults to ``"general"``; non-classified sync callers
MUST pass ``"exchange"`` explicitly so stale orphans are not created.

Output (stdout) is JSON, parsed by parent
``_run_delete_drawers_subprocess`` (src/mempalace_backfill/backfill_application.py):

    Success (rc=0):
        {"status": "ok", "deleted": N}

Output (stdout) on failure (exit code 1 or 2):

    {"status": "error", "message": "<reason>"}

stderr carries human-readable diagnostic output via ``logging.error`` only.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any, Optional


def _emit_error(message: str, exit_code: int) -> None:
    """Emit a JSON error payload to stdout and exit.

    Schema is consumed by ``_run_delete_drawers_subprocess`` in
    ``backfill_application.py`` via ``json.loads(proc.stdout)``. The
    ``message`` key is the contract; ``status`` discriminates ok/error.
    """
    payload = {"status": "error", "message": message}
    logging.error("delete_drawers_helper: %s", message)
    print(json.dumps(payload))
    sys.exit(exit_code)


def _run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.info("delete_drawers_helper: starting")

    if len(sys.argv) < 2:
        _emit_error("missing JSON args argument", 1)

    try:
        args: dict[str, Any] = json.loads(sys.argv[1])
    except json.JSONDecodeError as exc:
        _emit_error(f"invalid JSON args: {exc}", 1)

    palace_path: Optional[str] = args.get("palace_path")
    source_files: list[str] = args.get("source_files", [])
    extract_mode: str = args.get("extract_mode", "general")
    backend_hint: Optional[str] = args.get("backend_hint")

    if not palace_path:
        _emit_error("missing palace_path", 1)

    if not source_files:
        payload = {"status": "ok", "deleted": 0}
        print(json.dumps(payload))
        logging.info("delete_drawers_helper: nothing to delete, exiting")
        return

    try:
        from mempalace.backends.base import CollectionNotInitializedError, BaseCollection
        from mempalace.palace import get_collection
    except ImportError as exc:
        _emit_error(f"mempalace not available: {exc}", 1)

    try:
        collection: BaseCollection = get_collection(
            palace_path,
            create=False,
            backend=backend_hint,
        )
    except CollectionNotInitializedError:
        _emit_error(f"palace not initialized: {palace_path}", 2)
    except FileNotFoundError as exc:
        # CollectionNotInitializedError subclasses FileNotFoundError; some
        # backends raise the parent directly when the palace dir/db is gone.
        _emit_error(f"palace not initialized: {palace_path} ({exc})", 2)
    except Exception as exc:
        _emit_error(f"{exc!r}", 1)

    where: dict[str, Any] = {
        "source_file": {"$in": source_files},
        "extract_mode": extract_mode,
    }

    try:
        result = collection.get(where=where)
    except Exception as exc:
        _emit_error(f"{exc!r}", 1)

    ids: list[str] = list(getattr(result, "ids", []) or [])
    if ids:
        try:
            collection.delete(ids=ids)
        except Exception as exc:
            _emit_error(f"{exc!r}", 1)

    payload = {"status": "ok", "deleted": len(ids)}
    print(json.dumps(payload))
    logging.info("delete_drawers_helper: deleted %d drawer(s), exiting", len(ids))


if __name__ == "__main__":
    _run()

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

Output (stdout) - success::

    OK: deleted N drawers

Output (stderr) - errors::

    Error: palace not initialized: /path/to/palace   (exit code 2)
    Error: <repr(exception)>                          (exit code 1)
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any, Optional


def _run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.info("delete_drawers_helper: starting")

    if len(sys.argv) < 2:
        print("Error: missing JSON args argument", file=sys.stderr)
        sys.exit(1)

    try:
        args: dict[str, Any] = json.loads(sys.argv[1])
    except json.JSONDecodeError as exc:
        print(f"Error: invalid JSON args: {exc}", file=sys.stderr)
        sys.exit(1)

    palace_path: Optional[str] = args.get("palace_path")
    source_files: list[str] = args.get("source_files", [])
    extract_mode: str = args.get("extract_mode", "general")
    backend_hint: Optional[str] = args.get("backend_hint")

    if not palace_path:
        print("Error: missing palace_path", file=sys.stderr)
        sys.exit(1)

    if not source_files:
        print("OK: deleted 0 drawers")
        logging.info("delete_drawers_helper: nothing to delete, exiting")
        return

    try:
        from mempalace.backends.base import CollectionNotInitializedError, BaseCollection
        from mempalace.palace import get_collection
    except ImportError as exc:
        print(f"Error: mempalace not available: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        collection: BaseCollection = get_collection(
            palace_path,
            create=False,
            backend=backend_hint,
        )
    except CollectionNotInitializedError:
        print(f"Error: palace not initialized: {palace_path}", file=sys.stderr)
        logging.info("delete_drawers_helper: palace not initialized, exiting")
        sys.exit(2)
    except FileNotFoundError as exc:
        # CollectionNotInitializedError subclasses FileNotFoundError; some
        # backends raise the parent directly when the palace dir/db is gone.
        print(f"Error: palace not initialized: {palace_path} ({exc})", file=sys.stderr)
        logging.info("delete_drawers_helper: palace not initialized, exiting")
        sys.exit(2)
    except Exception as exc:
        print(f"Error: {exc!r}", file=sys.stderr)
        sys.exit(1)

    where: dict[str, Any] = {
        "source_file": {"$in": source_files},
        "extract_mode": extract_mode,
    }

    try:
        result = collection.get(where=where)
    except Exception as exc:
        print(f"Error: {exc!r}", file=sys.stderr)
        sys.exit(1)

    ids: list[str] = list(getattr(result, "ids", []) or [])
    if ids:
        try:
            collection.delete(ids=ids)
        except Exception as exc:
            print(f"Error: {exc!r}", file=sys.stderr)
            sys.exit(1)

    print(f"OK: deleted {len(ids)} drawers")
    logging.info("delete_drawers_helper: deleted %d drawer(s), exiting", len(ids))


if __name__ == "__main__":
    _run()

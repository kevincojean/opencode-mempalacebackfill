"""
Standalone helper to delete MemPalace drawers by source_file via ChromaDB.

Invoked as a subprocess so that a ChromaDB segfault (HNSW segment writer)
does not kill the parent process.

Usage::

    python delete_drawers_helper.py <json-args>

Input JSON (via argv)::

    {
        "palace_path": "/path/to/palace",
        "source_files": ["/path/to/file1.md", "/path/to/file2.md"],
        "extract_mode": "exchange"
    }

Output JSON (stdout) — success::

    {"status": "ok", "deleted": 5}

Output JSON (stdout) — error::

    {"status": "error", "message": "human-readable reason"}
"""

import json
import sys
from typing import Any


def _run() -> None:
    if len(sys.argv) < 2:
        print(json.dumps({"status": "error", "message": "Missing JSON args argument"}))
        sys.exit(1)

    try:
        args: dict[str, Any] = json.loads(sys.argv[1])
    except json.JSONDecodeError as e:
        print(json.dumps({"status": "error", "message": f"Invalid JSON args: {e}"}))
        sys.exit(1)

    palace_path = args.get("palace_path")
    source_files: list[str] = args.get("source_files", [])
    extract_mode: str | None = args.get("extract_mode", "exchange")

    if not palace_path:
        print(json.dumps({"status": "error", "message": "Missing palace_path"}))
        sys.exit(1)

    if not source_files:
        print(json.dumps({"status": "ok", "deleted": 0}))
        return

    try:
        import chromadb
        from chromadb.config import Settings as ChromaSettings
    except ImportError:
        print(json.dumps({"status": "error", "message": "chromadb not available"}))
        sys.exit(1)

    try:
        from pathlib import Path
        db_path = Path(palace_path)
        if not db_path.is_dir():
            print(json.dumps({"status": "error", "message": f"Palace directory not found: {palace_path}"}))
            sys.exit(1)

        client = chromadb.PersistentClient(
            path=str(db_path),
            settings=ChromaSettings(anonymized_telemetry=False),
        )

        try:
            collection = client.get_collection("mempalace_drawers")
        except ValueError:
            print(json.dumps({"status": "ok", "deleted": 0}))
            return

        total_deleted = 0
        failures: list[str] = []
        for src in source_files:
            try:
                if extract_mode is not None:
                    where: dict[str, Any] = {
                        "$and": [
                            {"source_file": src},
                            {"extract_mode": extract_mode},
                        ]
                    }
                else:
                    where = {"source_file": src}

                result = collection.get(where=where, include=[])
                ids = result.get("ids", [])
                if ids:
                    collection.delete(ids=ids)
                    total_deleted += len(ids)
            except Exception as e:
                failures.append(f"{src}: {e}")

        if failures:
            print(json.dumps({"status": "partial", "deleted": total_deleted, "failed": failures}))
        else:
            print(json.dumps({"status": "ok", "deleted": total_deleted}))

    except Exception as e:
        print(json.dumps({"status": "error", "message": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    _run()

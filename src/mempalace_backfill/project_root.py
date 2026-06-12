import os
from pathlib import Path


def get_project_root() -> Path:
    """Detect the project root directory for mempalace-backfill.

    Resolution order:
    1. ``MEM_PALACE_BACKFILL_DIR`` environment variable (explicit override).
    2. Walk up from this module's location looking for ``pyproject.toml``
       (works when running from a development checkout).
    3. Walk up from the current working directory looking for ``pyproject.toml``
       (works when the command is run from anywhere inside the project tree).
    4. Fall back to the current working directory.

    The returned path is always absolute and resolved.
    """
    # 1. Environment variable override.
    env_root = os.environ.get("MEM_PALACE_BACKFILL_DIR")
    if env_root:
        p = Path(env_root).resolve()
        if p.is_dir():
            return p

    # 2. Walk up from the installed package location (development checkout).
    current = Path(__file__).resolve().parent
    for parent in [current] + list(current.parents):
        if (parent / "pyproject.toml").is_file():
            return parent

    # 3. Walk up from CWD (running inside the project tree).
    current = Path.cwd().resolve()
    for parent in [current] + list(current.parents):
        if (parent / "pyproject.toml").is_file():
            return parent

    # 4. Fallback.
    return Path.cwd().resolve()

import re
from pathlib import Path


def infer_wing_from_path(path: str | None) -> str:
    """Infer a MemPalace wing name from a directory path.

    Mirrors the logic in ``opencode-mempalace-persistence``'s ``getWingFromPath``:

    * empty / ``/`` → ``wing_general``
    * ``basename`` → lowercase → replace ``[^a-z0-9]`` with ``-`` → ``wing_`` prefix
    * if the sanitised result is empty or just ``-`` → ``wing_general``

    >>> infer_wing_from_path("/home/user/projects/my-app")
    'wing_my-app'
    >>> infer_wing_from_path("")
    'wing_general'
    >>> infer_wing_from_path(None)
    'wing_general'
    """
    if not path or path.strip() == "" or path.strip() == "/":
        return "wing_general"

    base = Path(path).name
    sanitized = re.sub(r"[^a-z0-9]", "-", base.lower())

    if not sanitized or sanitized.strip("-") == "":
        return "wing_general"

    return f"wing_{sanitized}"

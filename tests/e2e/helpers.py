import os
import stat
import subprocess
import tempfile
from contextlib import contextmanager


def run_cli(args: list[str], cwd: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["uv", "run", "mempalace-backfill"] + args,
        capture_output=True,
        text=True,
        cwd=cwd,
    )


@contextmanager
def mock_mempalace_script(body: str = "#!/bin/sh\necho '0 drawers'\nexit 0\n"):
    """Create a temporary executable script to mock the mempalace command."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".sh", delete=False) as f:
        f.write(body)
        script_path = f.name
    os.chmod(script_path, os.stat(script_path).st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    try:
        yield script_path
    finally:
        os.unlink(script_path)

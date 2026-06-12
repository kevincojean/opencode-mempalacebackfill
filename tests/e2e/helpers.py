import subprocess


def run_cli(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["uv", "run", "mempalace-backfill"] + args,
        capture_output=True,
        text=True,
    )

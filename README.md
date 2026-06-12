# mempalace-backfill

Backfill historical OpenCode sessions into MemPalace.

## 1. Why This Project

If you use OpenCode with MemPalace you want to also have MemPalace ingest your past sessions. This project allows you to fetch past sessions and ingest them into MemPalace.

## 2. Installation

### Prerequisites

- Python 3.10+
- OpenCode (to have a session database to export from)
- [MemPalace](https://github.com/ohmyopenode/mempalace) (only needed for the `sync` command)

### Install via `uv` (recommended)

```bash
cd /home/dehi/src/mempalace_backfill/
uv tool install .
```

This makes the `mempalace-backfill` command available globally.

### Install via `pip`

```bash
pip install /home/dehi/src/mempalace_backfill/
```

### Verify installation

```bash
mempalace-backfill --help
```

## 3. Execution and Parameters

### Commands

#### `export`

Export OpenCode sessions to markdown files.

```bash
mempalace-backfill export [OPTIONS]
```

| Option | Required | Default | Description |
|--------|----------|---------|-------------|
| `--db-path` | Optional | `~/.local/share/opencode/opencode.db` | Path to OpenCode SQLite database |
| `--max-sessions` | Optional | `1000` | Maximum number of sessions to export |
| `--since` | Optional | — | Export sessions after this date (ISO format, e.g. `2026-01-01`) |
| `--until` | Optional | — | Export sessions before this date (ISO format) |
| `--exclude-title` | Optional | — | Regex pattern to exclude session titles |
| `--min-messages` | Optional | `1` | Minimum number of messages a session must have |
| `--output-dir` | Optional | `./target/exports` | Directory to write markdown files |
| `--state-file` | Optional | `./target/state.json` | Path to state file for incremental exports |
| `--include-system-prompt` | Optional | `False` | Include system prompt messages in the output |
| `--dry-run` | Optional | `False` | Preview how many sessions would be exported without writing files |

#### `sync`

Export sessions AND mine them into MemPalace in one go.

```bash
mempalace-backfill sync [OPTIONS]
```

| Option | Required | Default | Description |
|--------|----------|---------|-------------|
| `--wing` | Optional | `opencode-sessions` | MemPalace wing to mine into |
| `--mempalace-db-path` | Optional | — | Path to MemPalace palace database (maps to `mempalace --palace`) |
| `--db-path` | Optional | `~/.local/share/opencode/opencode.db` | Path to OpenCode SQLite database |
| `--max-sessions` | Optional | `1000` | Maximum number of sessions to export |
| `--since` | Optional | — | Export sessions after this date (ISO format) |
| `--until` | Optional | — | Export sessions before this date (ISO format) |
| `--exclude-title` | Optional | — | Regex pattern to exclude session titles |
| `--min-messages` | Optional | `1` | Minimum number of messages a session must have |
| `--output-dir` | Optional | `./target/exports` | Directory to write markdown files |
| `--state-file` | Optional | `./target/state.json` | Path to state file for incremental exports |
| `--include-system-prompt` | Optional | `False` | Include system prompt messages in the output |
| `--dry-run` | Optional | `False` | Preview export without writing files |

#### `test`

Run the test suite.

```bash
mempalace-backfill test [ARGS]
```

Any extra arguments are forwarded to pytest. Examples:

```bash
mempalace-backfill test                          # run all tests
mempalace-backfill test -- -k "sync"             # run only sync tests
```

#### reinstall

After pulling changes from the upstream repository, you can install the latest version or code using:

```bash
mempalace-backfill reinstall
```

## 5. Test Execution

Tests use a fixture SQLite database with 3 pre-seeded sessions and temp directories for output and state — no external dependencies or real OpenCode database needed.

### Prerequisites

```bash
uv sync --group test
```

### Run all tests

```bash
uv run pytest -v
```

## License

MIT

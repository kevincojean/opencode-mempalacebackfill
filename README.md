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
| `--db-path` | Optional | *auto-detected* | Path to OpenCode SQLite database |
| `--max-sessions` | Optional | `100` | Maximum number of sessions to export |
| `--since` | Optional | — | Export sessions after this date (ISO format, e.g. `2026-01-01`) |
| `--until` | Optional | — | Export sessions before this date (ISO format) |
| `--exclude-title` | Optional | — | Regex pattern to exclude session titles |
| `--min-messages` | Optional | — | Minimum number of messages a session must have |
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
| `--db-path` | Optional | *auto-detected* | Path to OpenCode SQLite database |
| `--max-sessions` | Optional | `100` | Maximum number of sessions to export |
| `--since` | Optional | — | Export sessions after this date (ISO format) |
| `--until` | Optional | — | Export sessions before this date (ISO format) |
| `--exclude-title` | Optional | — | Regex pattern to exclude session titles |
| `--min-messages` | Optional | — | Minimum number of messages a session must have |
| `--output-dir` | Optional | `./target/exports` | Directory to write markdown files |
| `--state-file` | Optional | `./target/state.json` | Path to state file for incremental exports |
| `--include-system-prompt` | Optional | `False` | Include system prompt messages in the output |
| `--dry-run` | Optional | `False` | Preview export without writing files |

## License

MIT

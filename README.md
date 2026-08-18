# mempalace-backfill

Ingest all your previous OpenCode sessions into MemPalace.

**Supported platforms**: Linux. Windows may work but is untested.

**Disclaimer**: This software is offered for free with no guaranteed support. Versions tagged with `rc (release candidate)` are considered unstable and should not be used in production.

## Why This Project

If you use OpenCode with MemPalace you want to also have MemPalace ingest your past sessions. This project allows you to fetch past sessions and ingest them into MemPalace.

## Installation

### Prerequisites

- Python 3.10+
- OpenCode (to have a session database to export from)
- [MemPalace](https://github.com/ohmyopenode/mempalace) (only needed for the `sync` command)

### Install via `uv` (recommended)

```bash
git clone https://github.com/kevincojean/opencode-mempalacebackfill.git
cd mempalace-backfill
uv tool install .
```

This makes the `mempalace-backfill` command available globally.

### Backend-specific install

For development or running tests, install the backend you plan to target:

```bash
# ChromaDB users (default, recommended)
uv sync --extra chroma --group test

# Qdrant users (alternative)
uv sync --extra qdrant --group test
```

This installs the backend client plus pytest. Switch extras to change target backend.

<details>
<summary>Install via <code>pip</code></summary>

```bash
cd mempalace-backfill
pip install .
```

</details>

<details>
<summary>Verify installation</summary>

```bash
mempalace-backfill --help
```

</details>

## Backend compatibility

MemPalace supports multiple vector backends. This project works with both ChromaDB and Qdrant, with different tradeoffs.

### ChromaDB (recommended, tested)

The default MemPalace backend. Recommended for single-machine setups.

- ChromaDB ships as a `chroma` extra in `pyproject.toml`. Install via `uv sync --extra chroma`.
- Local file-based storage, no separate server needed.
- The default fallback when no backend is explicitly configured or auto-detected.

### Qdrant (supported, alternative)

Supported for server-mode deployments where you run Qdrant as a separate service.

- `qdrant-client` is a test-only dependency in this project. Backfill never imports it directly.
- Backfill uses MemPalace's public API for Qdrant, so the runtime is delegated to MemPalace.
- Alternative path for multi-machine or production deployments.

### Backend selection

The backend is resolved in priority order (highest first):

1. `--backend` CLI flag or `MEMPALACE_BACKEND_EXPLICIT` env var - explicit override.
2. `~/.mempalace/config.json` `backend` field for the matching palace path.
3. `MEMPALACE_BACKEND` env var (older MemPalace versions).
4. On-disk artifact auto-detect (scan existing palace data).
5. Default: `chroma`.

```bash
mempalace-backfill sync --backend qdrant
mempalace-backfill sync --backend chroma
```

Allowed values are `chroma` and `qdrant`. Other values (e.g. `milvus`) are rejected at the CLI edge.

### Qdrant setup

See the [MemPalace docs](https://github.com/ohmyopenode/mempalace) for Qdrant server installation. The env vars below configure the client:

| Variable | Required | Description |
|----------|----------|-------------|
| `MEMPALACE_QDRANT_URL` | Required | Qdrant server URL (e.g. `http://localhost:6333`). |
| `MEMPALACE_QDRANT_API_KEY` | Optional | API key. **Env only. NEVER pass via argv.** |
| `MEMPALACE_QDRANT_NAMESPACE` | Optional | Namespace for multi-tenancy. |

Example:

```bash
export MEMPALACE_QDRANT_URL=http://localhost:6333
export MEMPALACE_QDRANT_API_KEY=your-key
mempalace-backfill sync --backend qdrant
```

If `--backend qdrant` is set without a running Qdrant server, the command fails with no silent fallback.

### Migration

Drawers are not portable between backends. Switching from ChromaDB to Qdrant on the same palace path starts a fresh palace. Re-run `mempalace-backfill sync` to populate it.

## Configuration

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `LOG_LEVEL` | Optional | `INFO` | Python log level. Set to `DEBUG` for verbose output, `WARNING` to suppress info logs, or `ERROR` for errors only. |

### Pre-classification (Optional)

You can configure the pre-classification feature by creating or editing the `~/.config/com.kevincojean.opencode-mempalacebackfill/config.json` file. This step prefixes your sessions with explicit category markers (e.g. `[decision]`, `[problem]`) before feeding them into MemPalace, allowing automatic room routing.

#### Custom patterns (augmented regex)

The built-in `MARKER_PATTERNS` cover generic keywords, but your personal style has unique patterns. Rather than editing source code, you add them to the config under `custom_patterns`:

```json
{
  "backfill": {
    "preclassification": {
      "enabled": true,
      "mode": "regex",
      "custom_patterns": {
        "decision": [
          "ok go with \\\\w+",
          "no \\\\w+ do it properly",
          "just use \\\\w+ instead"
        ],
        "emotional": [
          "ah \\\\w+ works now",
          "nothing is injected",
          "ffs",
          "still \\\\w+ doesnt work"
        ],
        "milestone": [
          "now reload \\\\w+",
          "\\\\w+ is done finally"
        ],
        "problem": [
          "fix \\\\w+ issue",
          "whats wrong with",
          "still broken"
        ],
        "architecture": [
          "restructure as \\\\w+",
          "use \\\\w+ pattern"
        ],
        "preference": [
          "never use \\\\w+",
          "always \\\\w+ instead"
        ]
      }
    }
  }
}
```

**How to generate your own patterns:** Run an LLM on your latest OpenCode sessions and ask it to extract recurring phrasing patterns per marker. For example:

> "Read my last 50 OpenCode sessions. For each marker (`decision`, `milestone`, `architecture`, `preference`, `problem`, `emotional`), extract 5-10 regex patterns that match how I personally express that marker. Output them as a JSON `custom_patterns` block."

The patterns are case-insensitive and are merged with the built-in patterns — you never lose default coverage.

- **`custom_patterns`** (optional): A dict of marker → list of regex patterns (see example above). Patterns are case-insensitive and merged with built-in patterns.

## Execution and Parameters

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
| `--min-messages` | Optional | `5` | Minimum number of messages a session must have |
| `--output-dir` | Optional | `~/.local/share/com.kevincojean.opencode-mempalacebackfill/exports` | Directory to write markdown files |
| `--state-file` | Optional | `~/.local/share/com.kevincojean.opencode-mempalacebackfill/state.json` | Path to state file for incremental exports |
| `--include-system-prompt` | Optional | `False` | Include system prompt messages in the output |
| `--dry-run` | Optional | `False` | Preview how many sessions would be exported without writing files |

#### `sync`

Mine existing exported sessions into MemPalace. The `export` command must be run separately beforehand.

```bash
mempalace-backfill sync [OPTIONS]
```

| Option | Required | Default | Description |
|--------|----------|---------|-------------|
| `--output-dir` | Optional | `~/.local/share/com.kevincojean.opencode-mempalacebackfill/exports` | Directory containing exported markdown files |
| `--max-sessions` | Optional | — | Maximum number of session files to mine (copies first N into a temp dir) |
| `--wing` | Optional | `opencode-sessions` | MemPalace wing to mine into |
| `--mempalace-db-path` | Optional | — | Path to MemPalace palace database (maps to `mempalace --palace`) |
| `--mempalace-command` | Optional | `mempalace` | Override the mempalace command path (useful for testing with mock scripts) |
| `--backend` | Optional | auto-detect | Override MemPalace backend (`chroma` or `qdrant`). Propagated via `MEMPALACE_BACKEND_EXPLICIT` to the `mempalace` subprocess |
| `--dry-run` | Optional | `False` | Preview the mempalace command without executing |

#### `clean`

Remove all contents from the session export output directory and reset the export state.

```bash
mempalace-backfill clean [OPTIONS]
```

| Option | Required | Default | Description |
|--------|----------|---------|-------------|
| `--output-dir` | Optional | `~/.local/share/com.kevincojean.opencode-mempalacebackfill/exports` | Directory to clean |
| `--state-file` | Optional | `~/.local/share/com.kevincojean.opencode-mempalacebackfill/state.json` | State file to remove |

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

## License

MIT

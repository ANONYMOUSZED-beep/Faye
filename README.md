# Faye

Faye is a production autonomous AI assistant distributed on top of the full [Hermes Agent](https://github.com/NousResearch/hermes-agent) runtime by Nous Research. It provides the mature interactive agent, coding and everyday tools, sessions, memory, skills, cron, profiles, plugins, MCP, voice, browser automation, gateways, and provider support under a dedicated `faye` executable and isolated `~/.faye` state.

Faye is a distribution boundary, not a cosmetic shell alias:

- `hermes-agent[all]==0.18.2` is exact-pinned for reproducible behavior.
- Faye establishes `HERMES_HOME=FAYE_HOME` before importing the engine.
- Foreign Hermes checkout paths inherited through `PYTHONPATH` are removed without deleting unrelated Python paths.
- First-run Faye identity, skin, and config assets are installed non-destructively.
- The complete upstream command surface is delegated unchanged and shown under `faye`.
- Engine incompatibility fails closed instead of silently loading another Hermes version.

Hermes Agent remains the credited production engine. Its current feature documentation is authoritative for engine behavior: https://hermes-agent.nousresearch.com/docs

## Requirements

- Python 3.11–3.13
- Windows, Linux, or macOS
- [`uv`](https://docs.astral.sh/uv/) for the source installation below

## Install from source

```bash
git clone https://github.com/ANONYMOUSZED-beep/Faye.git
cd Faye
uv sync --extra dev
```

Run Faye from the repository:

```bash
uv run faye --version
uv run faye setup
uv run faye
```

To install the `faye` command into an isolated global tool environment:

```bash
uv tool install .
faye --version
faye setup
```

## First run

```bash
# Configure model/provider, terminal, tools, agent, and gateway
faye setup

# Check configuration and runtime health
faye doctor
faye status

# Start the continuous interactive assistant
faye
```

Faye creates these assets only when missing:

```text
~/.faye/
├── config.yaml
├── SOUL.md
├── skins/faye.yaml
├── state.db
├── sessions/
├── skills/
├── cron/
└── profiles/
```

Existing files are never overwritten during bootstrap. Set `FAYE_HOME` to use another state root. Faye always overrides an inherited `HERMES_HOME` inside its process, preventing accidental reads or writes to Hermes state.

## Commands

Faye preserves the full engine command surface. Representative commands:

```bash
faye                         # interactive agent
faye chat -q "Fix the failing tests"  # one-shot task
faye setup                   # setup wizard
faye model                   # provider/model picker
faye tools                   # tool configuration
faye skills list             # skills
faye sessions list           # sessions
faye cron list               # scheduled jobs
faye profile list            # isolated profiles
faye mcp list                # MCP servers
faye plugins list            # plugins
faye gateway setup           # messaging platforms
faye gateway run             # foreground gateway
faye doctor                  # diagnostics
faye status                  # component status
```

Run `faye --help`, `faye <command> --help`, or consult the [Hermes Agent docs](https://hermes-agent.nousresearch.com/docs) for the complete runtime reference.

## Migrate existing Hermes state

Migration is explicit, copy-only, and non-destructive. Existing Faye files win; Hermes source files are never changed.

```bash
# Preview counts without creating or changing Faye state
faye migrate-hermes --dry-run

# Copy from HERMES_HOME or ~/.hermes into FAYE_HOME or ~/.faye
faye migrate-hermes

# Use explicit locations
faye migrate-hermes --source /path/to/.hermes --destination /path/to/.faye
```

Source symlinks are skipped; destination symlinks and Windows reparse points are rejected. Overlapping source/destination roots are rejected before Faye creates any files, and existing destination files are not overwritten. Review migrated credentials and gateway configuration before starting background services.

## Profiles and subprocesses

Because Faye establishes the engine state boundary in the process environment before any engine import, child agents, cron workers, gateways, profiles, and engine-launched subprocesses inherit Faye’s root. Named profiles live under `~/.faye/profiles/<name>/`.

## Upgrade model

Faye pins an exact Hermes Agent release. Upgrades are deliberate code changes: update the pin and compatibility constant together, regenerate `uv.lock`, run the full release gate, inspect artifacts, and review upstream changes before publishing. Faye refuses to run against a mismatched engine version.

The engine-owned `faye update` and `faye uninstall` commands intentionally fail closed because they could mutate or remove the exact-pinned runtime independently of Faye. Upgrade or remove the distribution as one unit with `uv tool upgrade faye-agent` or `uv tool uninstall faye-agent` (or the equivalent command for your installation method).

## Security

Faye inherits Hermes Agent’s approval, secret-redaction, toolset, terminal-backend, and provider controls. Useful checks:

```bash
faye doctor
faye security
faye config set security.redact_secrets true
```

Agent tools can execute code and mutate files when enabled. Use the least-privilege toolsets and terminal backend appropriate for your environment. Keep credentials in Faye’s `.env`/auth mechanisms, never in source control.

Migration deliberately copies credentials if present; it does not print their contents. The source remains unchanged.

## Development and verification

```bash
uv sync --extra dev
uv run pytest
uv run ruff check .
uv build
```

CI runs tests, Ruff, and builds on Windows and Linux with Python 3.11 and 3.12.

## Attribution and license

Faye’s distribution code is MIT-licensed. The runtime is provided by the separately packaged, MIT-licensed Hermes Agent project from Nous Research. See dependency metadata and upstream notices for the engine’s terms.

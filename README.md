# Faye

**Faye is a bounded coding agent, everyday AI assistant, and concurrent multi-agent orchestrator.** She has an independent runtime, typed capability architecture, local memory, voice support, and bounded multi-agent execution. She is explicitly software—not a human or a claim of consciousness—and her concise, sharp, resourceful voice is inspired by the broad character traits of Faye Valentine without impersonating her or copying dialogue.

## What works

- **Fast path:** greetings and identity questions answer locally in milliseconds without an API call.
- **Bounded swarm:** complex requests are decomposed into the fewest useful tasks and run concurrently with a hard limit of 100 workers.
- **Typed agent loop:** OpenAI-compatible models can request registered capabilities, receive structured results, and continue reasoning for at most 12 turns and 32 tool calls per run.
- **Scoped coding capabilities:** `read_file` and `search_text` inspect bounded UTF-8 content inside an explicit workspace. `write_file` is absent by default and can be enabled explicitly for bounded atomic writes. All three enforce canonical containment against traversal and symlink escapes.
- **Auditable failures:** every attempted capability call records its typed request, success state, and structured result; unknown tools and invalid arguments never widen the registry.
- **Task deduplication:** equivalent work is collapsed before execution.
- **Bounded conversation memory:** local SQLite memory persists recent turns while model context stays capped at 12,000 characters and retains only complete newest turns.
- **Persistent improvement:** explicit feedback is stored locally and applied later when it fits the same context budget.
- **Voice control on Windows:** native speech recognition and synthesis through `System.Speech`; no voice package required.
- **Device-less fallback:** when no speaker endpoint is available, speech is saved under `~/.faye/audio/` and the CLI prints its path.
- **Model portability:** any OpenAI-compatible endpoint, including OpenRouter and local servers.
- **Guarded execution:** a tiny, case-sensitive allowlist of inert commands runs entirely in-process; approval never widens it, and every other command remains blocked.
- **Honest identity:** Faye says she is AI and never claims tool execution without evidence.

## Quick start

Requirements: Windows 10/11, Python 3.11+, and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/ANONYMOUSZED-beep/Faye.git
cd Faye
uv sync --extra dev
```

Configure an OpenAI-compatible provider in your shell:

```bash
export FAYE_API_KEY="your-key"
export FAYE_BASE_URL="https://openrouter.ai/api/v1"
export FAYE_MODEL="openai/gpt-4o-mini"
```

On PowerShell, use `$env:FAYE_API_KEY="your-key"` instead. Do not commit `.env`; it is ignored.

## Use

```bash
# Local fast path—does not require a model key
uv run faye "hello"

# AI request; Faye chooses the useful worker count up to the limit
uv run faye --agents 100 "Compare three architectures for a local voice assistant"

# Bounded coding-agent loop with read-only access to this repository
uv run faye --agent --workspace . --max-turns 12 "Inspect the agent runtime"

# Explicitly opt into bounded atomic workspace writes
uv run faye --agent --write --workspace . "Update src/faye/example.py"

# Listen once through the default microphone and speak the response
uv run faye --voice

# Execute an inert allowlisted command without shell parsing
uv run faye --run "python --version"

# Approval never widens the closed executable allowlist
uv run faye --run --approve "git status"  # blocked
```

Only exact `pwd`, `whoami`, and `python --version` can run, and all three are implemented entirely in-process; the command gateway never launches a subprocess. Approval never widens this closed allowlist. Arbitrary programs, interpreters, mutations, uv, and every Git operation are blocked; future actions must use dedicated capability APIs with operation-specific validation.

Agent mode does not use that command gateway and does not expose a generic shell. Its default registry contains workspace-confined `read_file` and `search_text`; `write_file` is registered only with `--write`. Writes are UTF-8, limited to 262,144 bytes, require an existing workspace directory, and replace the destination atomically. Tool output is returned to the model as untrusted data, and oversized tool batches are rejected atomically before any handler runs.

## Speed model

Faye does **not** wake all 100 workers for every message. That would be slower and wasteful.

1. Deterministic fast paths handle trivial commands with zero network latency.
2. The planner creates only the independent tasks needed.
3. Normalized duplicate tasks are removed.
4. Workers fan out through a bounded thread pool.
5. Results are synthesized once.

`--agents 100` is capacity, not mandatory fan-out. Lower it on constrained hardware or strict provider rate limits.

## Self-improvement

`LearningMemory` stores data in `~/.faye/memory.db` by default. The orchestrator supplies up to six recent complete turns to the model in chronological order, retaining the newest turns that fit within a 12,000-character budget. The public API can record corrections:

```python
agent.learn(
    prompt="summarize the report",
    response="previous response",
    feedback="Use five bullets and put the decision first.",
    score=-1,
)
```

Relevant negative feedback becomes context for future tasks. This is controlled prompt adaptation—not autonomous model-weight modification or unreviewed self-rewriting. Delete the SQLite file to reset learned history.

## Architecture

```text
Voice / CLI
    |
    +-- deterministic fast path
    |
    +-- bounded agent loop -> typed registry -> workspace read/search/write
    |          |                                  |
    |          +-- audit log                      +-- canonical containment
    |          +-- turn/action budgets
    |
    +-- planner -> deduplicate -> bounded pool (1..100 mini-agents)
                                      |
                                      +-> synthesize final answer
    |
    +-- local SQLite learning memory
    |
    +-- command safety policy -> closed in-process command gateway
```

| Module | Responsibility |
|---|---|
| `orchestrator.py` | Planning, deduplication, concurrent execution, synthesis |
| `agent.py` | Bounded model → capability → model loop and audit trail |
| `capabilities.py` | Closed typed registry, JSON schemas, and argument validation |
| `workspace.py` | Workspace-confined, bounded file capabilities |
| `provider.py` | Dependency-free OpenAI-compatible text/tool client and persona |
| `memory.py` | SQLite interaction and feedback memory |
| `voice.py` | Native Windows speech input/output |
| `safety.py` | Deterministic command classification |
| `commands.py` | Closed, in-process execution of three inert operations |
| `cli.py` | Text, voice, and command entry points |

## Product roadmap

The current release is a secure native foundation, not the finished product. Planned capability families are added as typed APIs—never by exposing an unrestricted shell:

1. **Coding:** targeted patch operations, repository status/diff, and allowlisted build/test runners with workspace scopes, output limits, dry runs, and mutation approvals.
2. **Autonomy:** plans, checkpoints, resumable tasks, budgets, cancellation, subagents, background jobs, and durable audit logs.
3. **Everyday assistant:** web/browser tools, email, calendar, notes, reminders, documents, and user-controlled long-term memory.
4. **Multimodal interaction:** richer voice sessions, images, screen context, and consent-scoped desktop control.
5. **Extensibility:** provider adapters, plugins/skills, MCP-style integrations, per-capability permissions, and isolated execution backends.

Each milestone must preserve typed schemas, least privilege, explicit workspace/resource scopes, bounded execution, untrusted-output handling, and tests for rejection paths.

## Verify

```bash
uv run pytest
uv run ruff check .
uv build
```

CI runs those checks on Windows and Linux with Python 3.11 and 3.12.

## Security and privacy

- Secrets are read from environment variables and never persisted by Faye.
- Memory stays local in SQLite.
- Model output cannot override the deterministic command safety policy.
- Voice recognition uses Windows' local `System.Speech` API.
- Review any third-party model provider's data policy before sending sensitive content.

## License

MIT

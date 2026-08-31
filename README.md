# Arbiter

[![Documentation](https://img.shields.io/badge/docs-arbiter--docs.hazemhassine.space-0f172a?logo=readthedocs&logoColor=white)](https://arbiter-docs.hazemhassine.space)
[![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Next.js](https://img.shields.io/badge/Next.js-16-000000?logo=next.js&logoColor=white)](https://nextjs.org/)
[![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=111827)](https://react.dev/)
[![TypeScript](https://img.shields.io/badge/TypeScript-6-3178C6?logo=typescript&logoColor=white)](https://www.typescriptlang.org/)
[![Docker](https://img.shields.io/badge/Docker-supported-2496ED?logo=docker&logoColor=white)](https://www.docker.com/)

Arbiter is a local-first Linux control plane for understanding and safely
reconciling projects, Docker/Compose resources, host processes, ports, files,
and development servers.
It follows an explicit observe → diagnose → propose → approve → act → verify
workflow and binds its API to `127.0.0.1` by default.

Development requires Linux, Python 3.12, and
[uv](https://docs.astral.sh/uv/). Node.js 20.19 or newer is required only when
rebuilding the control panel or documentation. Docker is optional unless you
need container inspection or the live-Docker test suite.

## Quick start

```bash
cp .env.example .env
uv sync --extra dev
uv run arbiter serve
curl http://127.0.0.1:8765/health
curl http://127.0.0.1:8765/api/v1/ports
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765) for the control panel. It
uses a compact product-console interface with a global live-resource picker, an
interactive topology canvas, workspace screens, process evidence, and an
observability console for SSE events, auto-refreshing container logs and metrics,
and embedded localhost previews. The Admin page adds rolling API latency, LLM
usage, event pipeline, process/database, agent-harness, and safety-policy views
alongside an operational handbook. Docker resources, command search, port
tracing, and the approval-protected project file editor remain available in the
same shell. The bundled UI is a statically exported Next.js application, so it
needs no separate frontend runtime server. FastAPI serves the export directly,
and the UI uses the same REST safety pipeline as the CLI.

---

## Terminal-First & Shell Ergonomics

For engineers who prefer working entirely in the terminal without opening a browser:

### 1. Interactive Terminal UI (`arbiter tui`)
A fast, keyboard-driven Terminal UI (like lazydocker / k9s) letting you navigate ports, containers, approvals, projects, and container logs with vim keybindings:

```bash
arbiter tui
```
- **Tabs**: `[1] Ports`, `[2] Containers`, `[3] Approvals`, `[4] Projects`, `[5] Logs`, `[6] Readiness` (Switch with `1..6` or `Tab`)
- **Keybindings**: `j`/`k` (navigate), `Enter` (inspect / drill down), `a` (approve action), `l` (jump to logs), `p` (prepare project), `r` (refresh), `/` (search), `?` (help), `q` (quit).

### 2. Interactive CLI Pickers with Fuzzy Search
Commands run without explicit target arguments open an interactive fuzzy selector (fzf-style) with a live details preview pane:

```bash
arbiter inspect   # Fuzzy select over registered projects
arbiter prepare   # Fuzzy select project to prepare
arbiter logs      # Fuzzy select container to stream logs
arbiter approve   # Fuzzy select pending safety approval to execute
```

### 3. Shell Prompt & Starship Integration (`arbiter prompt`)
Display real-time status pills in your `zsh`/`bash`/`fish` prompt or Starship:

```bash
# Formatted status pill (⚡ Arbiter: 1 pending approval | 0 conflicts)
arbiter prompt

# Starship prompt format
arbiter prompt --format starship

# Generate one-line shell hook configuration
arbiter prompt init starship   # Starship TOML configuration
arbiter prompt init zsh        # Zsh precmd hook
arbiter prompt init bash       # Bash PROMPT_COMMAND hook
arbiter prompt init fish       # Fish prompt hook
```

---

## What it observes

- A fresh topology graph links projects, Compose files/services, containers,
  images, volumes, networks, ports, host processes, Dockerfiles, and Make targets.
- The topology canvas supports zoom and fit controls, connected-path focus,
  project scoping, local search, and strict natural-language resource filtering.
- Runtime-driven discovery creates ephemeral workspace evidence from Compose
  labels and process working directories; explicit registration remains required
  before a project can be edited.
- Docker event streaming plus configurable host polling drive the SSE activity
  feed at `/api/v1/events/stream`.
- The observability workspace can tail a selected container, filter or pause
  output, inspect a runtime metrics snapshot, and render likely HTTP listeners in
  an embedded preview with a new-tab fallback. Logs and metrics remain on demand
  and are never persisted by the control plane.
- Dockerfile and Makefile inspection provide deterministic metadata and
  conservative diagnostics; the LLM layer only sits above typed read-only tools.
- Optional resource-query interpretation uses `FILTER_LLM_MODEL` (default
  `gpt-5.4-nano`) to produce a strict typed filter plan. Matching is still local
  and deterministic, and automatically falls back to the built-in parser.

Register and prepare a project:

```bash
uv run arbiter register /home/user/dev/github-analysis
uv run arbiter prepare github-analysis
uv run arbiter approve APPROVAL_ID
```

The preparation operation inspects Compose configuration, every registered port
claim, and real listening ports. Conflicts produce deterministic alternatives
that reserve both declared and observed ports, plus a persisted approval. Approval
executes exactly the stored arguments, backs up configuration, validates it,
recreates only affected services, and records post-action checks.

## Architecture

The code under `src/arbiter` is split into domain services:

- `ports`: parses Linux `ss`, resolves processes through `/proc`, correlates
  Docker/Compose metadata, detects typed declaration/runtime conflicts, and builds
  deterministic per-project reconciliation plans without creating known new
  collisions.
- `projects`: bounded discovery below configured roots and a refreshable SQLite
  registry. No whole-filesystem scan occurs.
- `stacks`: multi-project environment profiles, 1-click context switching with
  dynamic `.env` override injection, port collision reconciliation, and
  topological DAG boot order orchestration with policy-controlled live readiness
  gates. Loopback and registered Compose-service probes are automatic; other
  destinations require a persisted protocol/host/port/IP approval. Link-local,
  metadata, multicast, unspecified, and reserved destinations are always blocked.
- `topology`, `system`, and `events`: generate a live, typed machine graph from
  Compose/Docker metadata, `/proc`, `ss`, and Docker events; runtime state is not
  persisted as authoritative data.
- `docker` and `compose`: typed Docker SDK inspection, Compose label awareness,
  lifecycle operations, validation, and structured port editing.
- `dockerfile`, `make`, `files`, and `impact`: Dockerfile and Make intelligence,
  safe registered-project editing with backup/diff/rollback/undo, and deterministic
  pre-operation impact summaries.
- `safety`, `actions`, and `persistence`: immutable persisted approvals, one typed
  action dispatcher, history, and mandatory verification outcomes.
- `agent`: deterministic intents plus LangChain v1's `create_agent` runtime,
  backed by LangGraph and restricted to the control plane's typed tools.
- `api`, `cli`, and `integrations`: thin adapters over the same services.

SQLite stores registered projects, approvals, action history, and agent-request
schema. Docker logs are returned on demand and are not persisted.

## Port, project, and stack APIs

```bash
curl http://127.0.0.1:8765/api/v1/ports/5432
curl 'http://127.0.0.1:8765/api/v1/ports/free?start=3000&end=4000&count=5'
curl http://127.0.0.1:8765/api/v1/ports/conflicts
curl http://127.0.0.1:8765/api/v1/projects/PROJECT_ID/reconciliation-plan

# Register and prepare projects
curl -X POST http://127.0.0.1:8765/api/v1/projects \
  -H 'Content-Type: application/json' \
  -d '{"path":"/home/user/dev/github-analysis"}'

curl -X POST http://127.0.0.1:8765/api/v1/projects/prepare \
  -H 'Content-Type: application/json' \
  -d '{"path":"/home/user/dev/github-analysis","resolve_port_conflicts":true,"start":true,"verify":true}'

# Multi-project stack presets and 1-click context switching
curl http://127.0.0.1:8765/api/v1/stacks
curl http://127.0.0.1:8765/api/v1/stacks/STACK_ID/boot-order
curl http://127.0.0.1:8765/api/v1/stacks/STACK_ID/readiness
curl -X POST http://127.0.0.1:8765/api/v1/stacks/STACK_ID/switch \
  -H 'Content-Type: application/json' \
  -d '{"hibernate_current":true,"wait_for_readiness":true,"resolve_port_conflicts":true}'
```


Natural language queries use real service observations:

```bash
curl -X POST http://127.0.0.1:8765/api/v1/agent/query \
  -H 'Content-Type: application/json' \
  -d '{"message":"What is using port 5432?"}'
```

The browser uses `POST /api/v1/agent/query/stream`, which returns newline-delimited
JSON events for routing, model phases, typed tool calls, redacted arguments and
results, errors, and the final response. The original query endpoint remains the
stable non-streaming contract for CLI and integration clients. Agent answers are
rendered as GitHub-flavored Markdown without enabling raw HTML. The execution
trace exposes actions and evidence, not private model chain-of-thought.

## Topology, process, and editor APIs

```bash
# Fresh connected workstation graph and one scoped workspace graph
curl http://127.0.0.1:8765/api/v1/topology
curl http://127.0.0.1:8765/api/v1/topology/project/PROJECT_ID

# Follow a resource in either direction
curl http://127.0.0.1:8765/api/v1/resources/port/tcp%3A5432
curl 'http://127.0.0.1:8765/api/v1/search?q=postgres'
curl http://127.0.0.1:8765/api/v1/processes

# Registered project files only: read, diff/validate, then create an approval
curl 'http://127.0.0.1:8765/api/v1/projects/PROJECT_ID/files/content?path=compose.yaml'
curl -X POST http://127.0.0.1:8765/api/v1/projects/PROJECT_ID/files/save \
  -H 'Content-Type: application/json' \
  -d '{"path":".dockerignore","content":".git\n.venv\n","expected_sha256":"..."}'
```

The editor accepts only known configuration files inside explicitly registered
project roots: Compose files, Dockerfiles, Makefiles, `.env`, and `.dockerignore`.
It resolves paths safely, creates a backup, writes atomically, validates the result,
rolls back on validation failure, and supports undoing the latest managed change.

Interactive API documentation is available at `/docs`, `/redoc`, and
`/openapi.json`. Docker inspection endpoints cover containers, bounded logs,
stats, images, volumes and their users, networks and members, and disk usage.
State-changing endpoints all feed the approval/action service.

Readiness probes never use an unvalidated hostname for the network connection.
Arbiter resolves and classifies the destination first, connects to the validated
IP directly, sends the original hostname only as the HTTP `Host` header, and
revalidates every redirect. Scoped non-local grants can be reviewed or revoked
from the UI, TUI, CLI, or REST API.
Stack switching preflights this policy and performs no mutations while a required
readiness authorization is missing.

## Safety model

Actions are classified as `READ_ONLY`, `LOW_RISK`, `MEDIUM_RISK`, `HIGH_RISK`,
or `DESTRUCTIVE`. Medium and higher risk always require approval. Low risk does
unless explicitly configured otherwise. Volume removal and generic shell or
filesystem APIs do not exist. Subprocesses use fixed argument arrays, timeouts,
and registered project paths. File edits are restricted to known configuration
files below a registered root; `.env` editor payloads are redacted from approval
and action-list APIs. Pending reconciliation approvals reserve replacement ports
in SQLite by protocol, so concurrent preparation requests cannot approve the same
replacement. Validation or service-recreation failures restore configuration and
attempt to recreate affected services from the restored source.

## Configuration

See `.env.example`. `PROJECT_ROOTS` is a comma-separated list. Discovery examines
each configured root and its immediate child directories only. The API host should
remain loopback unless the operator adds an external authentication boundary.
Arbiter refuses a non-loopback bind by default; `ALLOW_REMOTE_ACCESS=true` is an
explicit escape hatch, not a substitute for authentication. Legacy
`DEV_AGENT_HOST` and `DEV_AGENT_PORT` variables remain accepted during migration.

`OBSERVATION_INTERVAL_SECONDS` defaults to `3` and controls host process/port
polling. Docker's event stream is used when it is available.

Configure `LLM_BASE_URL`, `LLM_API_KEY`, and `LLM_MODEL` for open-ended tool
calling. `LLM_REASONING_EFFORT=none` remains the compatibility default. The
LangChain agent uses an OpenAI-compatible chat model, while LangGraph supplies the
bounded execution runtime and tool state. Core and deterministic natural-language
operations do not require an LLM. Provider failures degrade only that query rather
than taking down the API.

## CLI

```bash
arbiter tui                     # Launch full interactive TUI mode
arbiter inspect                 # Fuzzy picker for project inspection
arbiter prepare                 # Fuzzy picker for project preparation
arbiter logs                    # Fuzzy picker for container logs
arbiter approve                 # Fuzzy picker for pending approvals
arbiter prompt                  # Output prompt status pill
arbiter prompt init starship    # Generate Starship integration configuration
arbiter ports
arbiter ports --free 3000:4000 --count 10
arbiter projects --scan
arbiter ask 'Which projects have conflicting ports?'
arbiter containers
arbiter topology
arbiter processes
arbiter runtimes
arbiter disk

# Multi-project stack presets and 1-click switcher
arbiter stack list --seed-defaults
arbiter stack inspect "Billing Microservices"
arbiter stack boot-order "Billing Microservices"
arbiter stack readiness "Billing Microservices"
arbiter stack switch "AI Pipeline + Vector DB"
arbiter stack stop "AI Pipeline + Vector DB"
```

## MCP and A2A

MCP is a real optional stdio adapter using the official Python MCP package:

```bash
uv sync --extra mcp
uv run arbiter mcp
```

It exposes port inspection/allocation, topology and resource inspection, process
listing, project listing, a read-only reconciliation plan, and high-level
`arbiter_prepare_project`, plus
Docker container inspection. The A2A module supplies an Agent Card-shaped
capability description and a task adapter mapping preparation and diagnosis onto
the same core. A protocol SDK is not a mandatory dependency because the Python
A2A ecosystem is still evolving; REST is the stable transport for v1.

## Development

```bash
uv sync --extra dev
uv run pytest
uv run ruff check .

# Rebuild the statically exported Next.js control panel
cd src/arbiter/ui
npm install
npm run typecheck
npm run build

# Check and build the standalone documentation site
cd ../../../docs
npm install
npm run types:check
npm run build
```

Tests use fake system/Docker state by default. Opt-in live-Docker tests cover
inspection, an approval-gated container lifecycle, the complete Compose conflict
repair workflow, and forced Compose/`.env` rollback. They create only labelled
temporary resources and clean them up:

```bash
ARBITER_RUN_DOCKER_TESTS=1 uv run pytest -m docker
```

## Practical limitations

- Compose YAML is safely parsed and semantically rewritten, so comments and
  stylistic formatting are not preserved. A timestamped backup is always created.
- Environment-variable-driven Compose ports are reported but direct structured
  Compose rewriting is refused; update the registered project `.env` through the
  diff/approval editor instead.
- Project startup supports Compose directly. Unknown/custom startup commands are
  inspected but never guessed or executed automatically.
- Health verification uses container state, Docker health, refreshed config,
  observed port ownership, and stack readiness gates (TCP socket probes, HTTP
  endpoint checks, and Docker container health).
- Docker is the fully supported runtime. Podman and nerdctl/containerd are
  detected and reported as inspection-only capability signals rather than treated
  as feature-equivalent runtimes.

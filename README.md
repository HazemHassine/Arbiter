# Local Development Environment Agent

A local-first Linux operations agent for understanding projects, Docker/Compose,
processes, and especially cross-project port ownership. It follows an explicit
observe → diagnose → propose → approve → act → verify workflow and binds its API
to `127.0.0.1` by default.

## Quick start

```bash
cp .env.example .env
uv sync --extra dev
uv run dev-agent serve
curl http://127.0.0.1:8765/health
curl http://127.0.0.1:8765/api/v1/ports
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765) for the control panel. The
UI provides agent queries, live port ownership and free-port search, project
registration/scanning/preparation, container controls and logs, Docker resources,
persisted approvals, and action history. It is bundled locally with no frontend
build step or external runtime assets, and uses the same REST safety pipeline as
the CLI.

Register and prepare a project:

```bash
uv run dev-agent register /home/user/dev/github-analysis
uv run dev-agent prepare github-analysis
uv run dev-agent approve APPROVAL_ID
```

The preparation operation inspects Compose configuration and real listening
ports. Conflicting host ports produce deterministic alternatives and a persisted
approval. Approval executes exactly the stored arguments, backs up configuration,
validates it, recreates only affected services, and records post-action checks.

## Architecture

The code under `src/dev_agent` is split into domain services:

- `ports`: parses Linux `ss`, resolves processes through `/proc`, correlates
  Docker/Compose metadata, finds predictable free ports, and detects duplicate
  project claims.
- `projects`: bounded discovery below configured roots and a refreshable SQLite
  registry. No whole-filesystem scan occurs.
- `docker` and `compose`: typed Docker SDK inspection, Compose label awareness,
  lifecycle operations, validation, and structured port editing.
- `make`: target parsing, command inspection, and conservative risk classification.
- `safety`, `actions`, and `persistence`: immutable persisted approvals, one typed
  action dispatcher, history, and mandatory verification outcomes.
- `agent`: deterministic intents plus a small OpenAI-compatible, bounded
  tool-calling loop when an LLM is configured.
- `api`, `cli`, and `integrations`: thin adapters over the same services.

SQLite stores registered projects, approvals, action history, and agent-request
schema. Docker logs are returned on demand and are not persisted.

## Port and project APIs

```bash
curl http://127.0.0.1:8765/api/v1/ports/5432
curl 'http://127.0.0.1:8765/api/v1/ports/free?start=3000&end=4000&count=5'
curl http://127.0.0.1:8765/api/v1/ports/conflicts

curl -X POST http://127.0.0.1:8765/api/v1/projects \
  -H 'Content-Type: application/json' \
  -d '{"path":"/home/user/dev/github-analysis"}'

curl -X POST http://127.0.0.1:8765/api/v1/projects/prepare \
  -H 'Content-Type: application/json' \
  -d '{"path":"/home/user/dev/github-analysis","resolve_port_conflicts":true,"start":true,"verify":true}'
```

Natural language queries use real service observations:

```bash
curl -X POST http://127.0.0.1:8765/api/v1/agent/query \
  -H 'Content-Type: application/json' \
  -d '{"message":"What is using port 5432?"}'
```

Interactive API documentation is available at `/docs`, `/redoc`, and
`/openapi.json`. Docker inspection endpoints cover containers, bounded logs,
stats, images, volumes and their users, networks and members, and disk usage.
State-changing endpoints all feed the approval/action service.

## Safety model

Actions are classified as `READ_ONLY`, `LOW_RISK`, `MEDIUM_RISK`, `HIGH_RISK`,
or `DESTRUCTIVE`. Medium and higher risk always require approval. Low risk does
unless explicitly configured otherwise. Volume removal and generic shell or
filesystem APIs do not exist. Subprocesses use fixed argument arrays, timeouts,
and registered project paths. Secret-shaped environment keys are redacted by the
security utility and `.env` editing is limited to explicit integer port values.

## Configuration

See `.env.example`. `PROJECT_ROOTS` is a comma-separated list. Discovery examines
each configured root and its immediate child directories only. The API host should
remain loopback unless the operator adds an external authentication boundary.

Configure `LLM_BASE_URL`, `LLM_API_KEY`, and `LLM_MODEL` for open-ended tool
calling. `LLM_REASONING_EFFORT=none` is the safe default for function tools through
Chat Completions, including GPT-5.6 Luna. Core and deterministic natural-language
operations do not require an LLM. Provider failures degrade only that query rather
than taking down the API.

## CLI

```bash
dev-agent ports
dev-agent ports --free 3000:4000 --count 10
dev-agent projects --scan
dev-agent inspect github-analysis
dev-agent ask 'Which projects have conflicting ports?'
dev-agent containers
dev-agent logs postgres --tail 100
dev-agent disk
```

## MCP and A2A

MCP is a real optional stdio adapter using the official Python MCP package:

```bash
uv sync --extra mcp
uv run dev-agent mcp
```

It exposes port inspection/allocation, project listing and high-level
`dev_environment_prepare_project`, plus Docker container inspection. The A2A
module supplies an Agent Card-shaped capability description and a task adapter
mapping preparation and diagnosis onto the same core. A protocol SDK is not a
mandatory dependency because the Python A2A ecosystem is still evolving; REST is
the stable transport for v1.

## Development

```bash
uv sync --extra dev
uv run pytest
uv run ruff check .
```

Tests mock system/Docker state and never mutate the host Docker environment.
Optional real-environment smoke tests belong under the `docker` pytest marker.

## Practical v1 limitations

- Compose YAML is safely parsed and semantically rewritten, so comments and
  stylistic formatting are not preserved. A timestamped backup is always created.
- Environment-variable-driven Compose ports are reported but direct Compose
  rewriting is refused; explicit `.env` integer-port editing exists as a separate
  structured primitive.
- Project startup supports Compose directly. Unknown/custom startup commands are
  inspected but never guessed or executed automatically.
- Health verification uses container state, Docker health, refreshed config, and
  observed port ownership; application-specific HTTP/database probes require a
  future project health-profile configuration.

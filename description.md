# Arbiter — Detailed Description

## 1. Project summary

Arbiter is a local-first Linux operations tool for
understanding and controlling a developer workstation. Its primary purpose is to
coordinate ports across many simultaneously running projects, Docker containers,
Docker Compose stacks, and local processes.

The current control-plane layer also renders those resources as a live connected
topology, streams activity over SSE, provides safe registered-project
configuration editing, and exposes Dockerfile/Makefile intelligence.

The application behaves like a small development-focused SRE operator. It gathers
evidence from the machine, explains what it found, proposes narrowly scoped
changes, requires approval according to risk, executes the approved operation, and
verifies the result.

Its operating model is:

```text
observe → diagnose → explain → propose → approve → act → verify
```

It deliberately avoids unrestricted shell access, arbitrary file editing, and
unverified success claims. The same core services are reused by the REST API,
command-line interface, browser control panel, MCP server, A2A adapter, and
natural-language agent.

## 2. Main problem it solves

A development workstation often runs several services that want the same familiar
ports:

- PostgreSQL on `5432`
- Redis on `6379`
- frontend servers on `3000` or `5173`
- FastAPI or other backend servers on `8000`
- MongoDB on `27017`
- search services such as Meilisearch

When several projects are active, a requested port may already belong to a local
process, a standalone Docker container, or a service from another Compose project.
The agent correlates those sources and can answer questions such as:

- What ports are listening on this machine?
- What owns port 5432?
- Is port 8000 available?
- Which process, container, service, and project own a port?
- What ports are declared by a registered project?
- Do registered projects claim the same host port?
- Does a project configuration conflict with current runtime state?
- What predictable free port should replace an occupied one?
- Which Compose file or `.env` variable needs to change?

The higher-level `prepare_project` operation combines those capabilities. It
inspects a project, discovers its services and requested ports, checks real host
state, proposes deterministic alternatives, requests approval, updates structured
configuration, recreates only affected services, and verifies the result.

## 3. System architecture

```text
Browser UI       CLI       REST clients       MCP clients       A2A clients
    │             │             │                  │                 │
    └─────────────┴─────────────┴──────────────────┴─────────────────┘
                                  │
                         Interface adapters
                                  │
                    Agent and high-level orchestration
                                  │
        ┌───────────┬───────────┬───────────┬───────────┐
        │ Projects  │   Ports   │  Docker   │ Compose   │
        ├───────────┼───────────┼───────────┼───────────┤
        │ Makefiles │  System   │  Safety   │ Actions   │
        └───────────┴───────────┴───────────┴───────────┘
                                  │
             Linux /proc + ss    Docker SDK    SQLite    project files
```

Business logic does not live in the UI, CLI, or API routes. Those layers translate
requests into calls to shared services. This prevents one interface from bypassing
the safety rules or implementing behavior differently from another interface.

The application is a single Python process. It does not require Redis, Celery,
Kafka, Kubernetes, or another background infrastructure service.

## 4. Technology stack

- Python 3.12 or newer
- FastAPI and Uvicorn for HTTP serving
- Pydantic v2 and Pydantic Settings for domain and configuration models
- SQLAlchemy 2 with SQLite for persistence
- Docker SDK for Python for daemon inspection and operations
- Typer for the CLI
- LangChain v1 agents backed by the LangGraph runtime for LLM orchestration
- `httpx` for OpenAI-compatible LLM requests
- PyYAML for Compose parsing and structured editing
- `structlog` support for structured application logging
- pytest and pytest-asyncio for tests
- Ruff for formatting and linting
- plain HTML, CSS, and JavaScript for the bundled control panel
- optional official Python MCP package for the MCP adapter

The browser UI has no Node build step, framework runtime, or CDN dependency. Its
assets are packaged under `src/arbiter/ui` and served by FastAPI.

## 5. Core domain models

The shared Pydantic models are defined in `src/arbiter/models.py`.

### `PortBinding`

Represents a declared or published port mapping. It tracks the host port,
container port, protocol, optional host IP, service, source configuration file,
and optional environment variable that controls the port.

### `PortOwner`

Represents observed ownership of a host port. Depending on the evidence available,
it may contain:

- protocol and listening state
- host/interface binding
- PID, process name, and command
- Docker container ID and name
- Compose project and service
- configuration source

### `Project`

Represents a registered development project, including its stable ID, name, path,
Compose files, Makefile and environment-file presence, Dockerfile presence,
services, port declarations, status, and last-discovery timestamp.

### `ContainerInfo`

Provides a typed projection of a Docker container instead of exposing raw Docker
SDK objects. It includes state, health, restart count, ports, mounts, networks,
labels, image, and Compose ownership metadata.

### `ActionSpec`, `ApprovalInfo`, and `ActionResult`

These models separate an intended state change into three phases:

1. an exact proposed action and arguments;
2. a persisted approval decision;
3. an execution result with independent verification evidence.

## 6. Port subsystem

The port subsystem is the central feature of the project.

### Linux scanning

`src/arbiter/ports/scanner.py` runs `ss -H -lntu -p` using a fixed argument
array and parses TCP and UDP listeners. It handles IPv4 and IPv6 endpoints and
extracts process names and PIDs where the operating system exposes them.

When a PID is available, the process service reads `/proc/<pid>/comm` and
`/proc/<pid>/cmdline` to provide additional ownership evidence. Permission or
process-race failures are handled without inventing missing data.

### Docker correlation

`PortService.list_used_ports()` merges socket observations with Docker-published
port bindings. Docker Compose labels enrich matching port owners with:

- container name and ID
- Compose project name
- Compose service name
- Compose working directory
- Compose configuration paths

If Docker is unavailable, Linux socket results still work.

### Deterministic allocation

Free ports are selected predictably rather than randomly. If port `8000` is
occupied, the allocator checks `8001`, then `8002`, and so on within the configured
range. It can also return a requested number of free ports within an explicit
range.

### Conflict detection

Conflict detection compares registered project declarations with one another and
with runtime owners. A conflict can therefore represent either:

- multiple projects claiming the same host port; or
- one project claiming a port currently owned by an unrelated process/container.

`PortService.plan_port_reconciliation()` produces a typed, read-only plan for one
project. It distinguishes another project's declaration, a duplicate declaration
inside the target project, and unrelated runtime ownership. Alternative selection
reserves every registered declaration and observed runtime binding for the same
protocol before choosing the next deterministic port. Each change retains the
service, Compose source, and controlling `.env` variable when present.

## 7. Project discovery and registry

Projects may be registered explicitly or discovered under configured
`PROJECT_ROOTS`.

Automatic discovery is intentionally bounded. It examines each configured root
and its immediate child directories for markers such as:

- `compose.yaml` or `docker-compose.yml`
- `Makefile`
- `Dockerfile`
- `pyproject.toml`
- `package.json`
- `.git`

It does not recursively scan the entire home directory or filesystem.

Explicit registration is treated as authorization for that specific directory.
Once registered, a project can be refreshed, inspected, diagnosed, prepared, or
unregistered. Unregistering removes only the registry entry; it does not delete
project files.

Project environment inspection returns `.env` keys with sensitive values
redacted.

## 8. Docker integration

`src/arbiter/docker/service.py` connects with `docker.from_env()` and verifies
daemon connectivity before use.

Implemented container capabilities include:

- list and inspect containers
- bounded log retrieval
- one-shot statistics
- start, stop, restart, pause, and unpause
- safe removal through the action system
- exact and unambiguous container lookup

Image capabilities include listing, inspection, current-use detection, and
approval-protected removal of unused images.

Volume capabilities include listing, inspection, user discovery, and explicitly
destructive removal. A volume currently referenced by a container is rejected.

Network capabilities include listing, inspection, and member discovery.

Docker disk usage reports structured counts for images, containers, volumes, and
build cache.

All Docker inspection is read-only. State-changing Docker methods are reached
through typed actions and the risk/approval system.

## 9. Docker Compose support

The Compose parser understands short and long port syntax, including:

```yaml
ports:
  - "5432:5432"
  - "127.0.0.1:8000:80"
  - "${API_PORT:-8000}:80"
  - target: 80
    published: 8000
    protocol: tcp
```

It resolves `.env` variables for inspection while retaining the variable name so
the action service knows whether the source of truth is the Compose file or the
environment file.

Supported Compose operations include validation, start, stop, restart, service
restart, and forced recreation of one affected service.

### Structured port editing

The editor does not accept arbitrary LLM-generated patches. It receives an exact
Compose file, service, old host port, and new host port. It then:

1. validates the file name and service;
2. finds the exact port mapping;
3. creates a timestamped backup;
4. modifies only the requested mapping;
5. runs `docker compose config`;
6. restores the backup if validation fails.

For environment-driven ports, the action service changes only the matching
explicit integer value in the project `.env`, validates Compose, and restores the
backup if validation fails.

Approved conflict resolution recreates only affected services. Verification then
checks refreshed configuration, container state, and new port ownership.

PyYAML preserves configuration semantics but not necessarily the original YAML
comments or formatting style.

## 10. Makefile support

`MakeService` parses normal Make targets and their recipe lines without executing
them. It can identify obvious `--port` arguments and classify risk using both the
target name and command content.

Examples:

- `test`, `lint`, and `check` are usually low risk;
- `dev`, `start`, `stop`, and `restart` are medium risk;
- unknown targets are treated conservatively as high risk;
- commands containing `docker compose down -v`, `docker volume rm`, `rm -rf`,
  `dropdb`, or `reset --hard` are destructive.

Running a target uses `make <target>` with a fixed argument array, project working
directory, output capture, and timeout. Unknown or missing targets are rejected.

## 11. Safety and approvals

Every state-changing operation has one of five risk levels:

| Risk | Meaning | Default behavior |
| --- | --- | --- |
| `READ_ONLY` | Inspection and diagnosis | Automatically allowed |
| `LOW_RISK` | Limited reversible operation | Approval required unless configured otherwise |
| `MEDIUM_RISK` | Restart, stop, project start, config change | Approval required |
| `HIGH_RISK` | Container/image removal and broad cleanup | Explicit approval required |
| `DESTRUCTIVE` | Persistent data or volume deletion | Always explicit approval |

An approval is a persisted object with a UUID, request ID, exact action name,
exact serialized arguments, summary, risk, creation time, expiration time, and
status.

Approving an action executes the stored payload. The agent cannot replace or
modify arguments after approval. Expired, rejected, or previously approved
requests cannot be reused.

For `project.resolve_ports`, the approval transaction also reserves each proposed
`protocol:port` pair in SQLite. The uniqueness constraint prevents concurrent
preparation requests from holding active approvals for the same replacement.
Reservations are released on rejection, expiration, or execution completion.

The action history records:

- request and project IDs
- action and arguments
- risk and approval ID
- execution status
- operation result
- verification result
- sanitized error
- timestamp

## 12. Verification behavior

Execution success and verification success are separate concepts. An action may
return `verification_failed` even if its command completed.

Examples of verification include:

- checking a started/restarted container is running;
- checking a stopped Compose project has stopped containers;
- confirming a removed image or volume no longer exists;
- refreshing project configuration after a port change;
- checking the recreated service is running;
- checking the new host port has the expected owner.

The application only treats a prepared project as ready when the relevant checks
succeed.

## 13. High-level project preparation

`AgentService.prepare_project()` is the most important orchestration function. It
can accept a registered identifier or an explicit path and performs the following:

1. register or refresh the project;
2. inspect its Compose services and declared ports;
3. scan real listening ports;
4. correlate process and Docker ownership;
5. ignore a binding already owned by the same project;
6. identify external conflicts;
7. reserve deterministic replacement ports without duplicate suggestions;
8. create a single persisted approval containing all exact changes;
9. after approval, update configuration and recreate affected services;
10. refresh configuration and verify containers and ports.

Configuration updates are compensating transactions: if validation or service
recreation fails, Arbiter restores every edited Compose/`.env` source in reverse
order and attempts to recreate runtime services from the restored configuration.

If no conflicts exist but project startup is requested, a separate medium-risk
Compose start approval is created. Projects without a supported startup mechanism
are inspected but not guessed or started through arbitrary commands.

## 14. Natural-language agent

The natural-language endpoint combines deterministic intents with an optional,
graph-backed LLM agent.

Common port questions, conflict questions, and preparation requests are handled
directly by core services. They do not require an LLM.

Open-ended questions use LangChain v1's `create_agent`, which runs on LangGraph.
`ChatOpenAI` supplies the OpenAI-compatible model integration, function calling,
and configurable `reasoning_effort`. The resource-filtering subsystem retains its
small strict-JSON provider because it is a single structured model call rather
than an agent workflow.

The tool registry gives the model narrowly scoped access to:

- inspect topology, projects, and connected resources;
- inspect real ports, processes, and Docker resources;
- inspect Dockerfiles and Make targets;
- diagnose projects and detect port conflicts;
- propose preparation through the existing approval pipeline.

There is no generic shell tool. LangChain model calls are bounded by
`AGENT_MAX_STEPS`, and LangGraph owns tool-call state and termination. Malformed
calls become tool errors instead of arbitrary execution. Provider HTTP errors,
timeouts, connection failures, and malformed responses produce a safe `degraded`
query result rather than an unhandled HTTP 500.

Agent requests and their final responses are persisted in SQLite. The public
`POST /api/v1/agent/query` request and response contract is unchanged.
`POST /api/v1/agent/query/stream` adds an NDJSON projection for the browser with
safe routing, model-phase, tool-call, tool-result, error, and final-response
events. It deliberately exposes operational actions and evidence rather than
private model reasoning. The UI renders final answers as GitHub-flavored Markdown
with raw HTML disabled.

## 15. Persistence

SQLite is configured through `DATABASE_URL`, defaulting to
`sqlite:///./arbiter.db`.

The schema contains:

- `projects`: project registry and serialized discovery data;
- `approvals`: immutable proposals and decisions;
- `port_reservations`: active protocol/port claims held by reconciliation approvals;
- `actions`: execution and verification history;
- `agent_requests`: natural-language messages and responses.

SQLAlchemy sessions are short-lived and opened around each repository or service
operation. SQLite uses `check_same_thread=False` for FastAPI's execution model.

Large Docker logs are not stored in the database.

## 16. REST API

FastAPI exposes its OpenAPI schema at `/openapi.json`, Swagger UI at `/docs`, and
ReDoc at `/redoc`. The API base path is `/api/v1`.

Major endpoint groups are:

- `/agent/query`
- `/ports`, `/ports/free`, `/ports/conflicts`, and `/ports/{port}`
- `/projects` and project inspection/lifecycle/preparation routes
- `/containers` with logs, stats, and lifecycle routes
- `/images`, `/volumes`, and `/networks`
- `/docker/disk-usage`
- `/compose/projects`
- `/approvals`
- `/actions`
- `/system/resources`, `/system/processes/{pid}`, and `/system/ports`

The health endpoint is `/health`. The A2A capability card is exposed at
`/.well-known/agent-card.json`.

Typed errors are returned for invalid input, missing resources, and unavailable
Docker. Internal tracebacks are not intentionally returned as API response bodies.

## 17. Command-line interface

The `arbiter` Typer application exposes:

```text
arbiter serve
arbiter ask "what is using port 5432?"
arbiter ports
arbiter ports --free 3000:4000 --count 10
arbiter projects
arbiter projects --scan
arbiter register /path/to/project
arbiter inspect project-name
arbiter prepare project-name
arbiter containers
arbiter logs container-name --tail 200
arbiter disk
arbiter approve APPROVAL_ID
arbiter mcp
```

The CLI prints structured JSON for machine-readable operations and calls the same
services used by the API and UI.

## 18. MCP and A2A integration

The optional stdio MCP server exposes seven tools:

- `ports_list`
- `ports_find_owner`
- `ports_find_free`
- `ports_detect_conflicts`
- `projects_list`
- `arbiter_prepare_project`
- `project_reconciliation_plan`
- `docker_list_containers`

The high-level preparation tool is intended for coding agents that need a local
project started and verified before running tests.

The A2A module defines an Agent Card-shaped capability document and maps
preparation, port-conflict resolution, and diagnosis tasks onto `AgentService`.
REST remains the primary A2A-compatible task transport in this version.

## 19. Security boundaries

The server binds to `127.0.0.1` by default and rejects non-loopback binding unless
`ALLOW_REMOTE_ACCESS=true` explicitly acknowledges an external authentication
boundary. Important boundaries include:

- exact Host validation to resist DNS rebinding;
- same-origin checks for browser-initiated state changes;
- restrictive browser security headers and non-cacheable API responses;
- no arbitrary shell API;
- no generic filesystem read or write API;
- bounded automatic project scanning;
- explicit project registration;
- recognized Compose filename validation;
- fixed subprocess argument arrays with no `shell=True`;
- subprocess timeouts and captured output;
- bounded Docker log retrieval;
- exact container lookup with ambiguity rejection;
- secret-key redaction for names containing `PASSWORD`, `SECRET`, `TOKEN`,
  `API_KEY`, `PRIVATE_KEY`, or `CREDENTIAL`;
- no rendered Compose configuration output in API responses;
- owner-only SQLite state and backups stored outside project build contexts;
- persisted approval for risky actions;
- no automatic persistent-volume removal.

The API should remain on loopback unless an external authentication and transport
security layer is added. The escape hatch is not itself authentication.

## 20. Browser control panel

The control panel is available at `http://127.0.0.1:8765`. FastAPI redirects `/`
to `/ui/` and serves the bundled static export directly.

### Visual design

The interface uses a flat product-console design with light and dark themes,
Radix icons, compact status indicators, and an explicit theme toggle. The sidebar
can collapse on desktop and becomes a slide-out menu on smaller screens. Tables
remain horizontally scrollable and card layouts collapse as the viewport narrows.

The browser has no direct Docker or filesystem access. Every operation goes
through the REST API and the same approval and verification pipeline as the CLI.

### Sidebar and global status

The sidebar groups Overview, Workspaces, and Topology under **Workspace**;
Observability, Containers, Processes, and Ports under **Runtime**; Files, Docker
resources, Registry, and Ask agent under **Manage**; and Approvals, Audit log,
Admin, and Settings under **Safety**.

The top bar shows synchronization and live state, theme and refresh controls,
resource search, and a global **Ask Arbiter** action. The command palette opens
with `Cmd+K` or `Ctrl+K`.

### Overview screen

The overview is an operational dashboard containing:

- listening-port count and unique host-port count;
- registered-project count;
- running and total container counts;
- pending-approval count;
- a live sample of port owners;
- disk and memory usage gauges;
- a compact registered-project list;
- a quick project-preparation selector.

The dashboard loads Linux, Docker, SQLite, and system-resource data concurrently.
One unavailable subsystem does not prevent other cards from rendering.

### Ask Agent screen

Responses stream as GitHub-flavored Markdown with typed execution events for
routing, model phases, tool calls, redacted arguments, evidence, and errors. The
trace never exposes private model chain-of-thought. Proposed mutations still
become separate approvals and are never auto-approved by the UI.

### Ports screen

The port view provides:

- filtering by port, process, container, project, service, or source;
- a conflict-status card;
- configurable free-port range and count fields;
- copyable free-port results;
- a detailed ownership table containing host, protocol, owner, PID/container ID,
  project/service, source, and state.

### Workspaces and Registry screens

Projects can be registered by explicit path or discovered by scanning configured
roots. Each project card shows service, port, and Compose-file counts.

Project actions include:

- inspect project metadata;
- show diagnosis, redacted environment, and Make targets;
- prepare and resolve conflicts;
- start, stop, and restart through approvals;
- unregister without deleting project files.

### Containers screen

The container table displays name, shortened ID, image, state, health, published
ports, and Compose ownership. Users can view the last 200 log lines, inspect raw
one-shot statistics, and propose start, stop, or restart actions.

The separate Observability screen combines the SSE event stream with bounded
container logs, one-shot metrics, filtering and pause controls, and localhost
application previews. Topology and Processes views expose the live resource graph
and host runtime evidence.

### Docker screen

Tabbed Docker views provide:

- disk usage summary;
- images with tags, size, use status, and removal proposal;
- volumes with driver, mountpoint, current users, and destructive removal
  proposal for unused volumes;
- networks with driver, scope, member list, and detailed inspection.

### Approvals screen

The approvals page is the human safety gate. Each card shows risk, action summary,
action name, expiration time, and current status.

For pending approvals the user can:

- reject the proposal; or
- choose **Approve & execute**, confirm the decision, and execute the exact stored
  action.

The result is displayed after execution. Failed or unverified actions open a
detailed result dialog rather than being presented as successful.

### Audit Log screen

The audit screen lists action type, risk, status, verification status, action ID,
and request ID. It supports all/completed/failed filtering and opens the full
stored action record for inspection.

### Dialogs and notifications

The UI uses modal dialogs for project inspection, logs, metrics, approval details,
and operation results. Toast messages report successful refreshes, proposals,
errors, and completed decisions without hiding detailed verification data.

## 21. Configuration

The `.env.example` file documents the supported settings:

```env
ARBITER_HOST=127.0.0.1
ARBITER_PORT=8765
ARBITER_TRUSTED_HOSTS=localhost,127.0.0.1,::1
ALLOW_REMOTE_ACCESS=false
ARBITER_STATE_DIRECTORY=~/.local/state/arbiter
DATABASE_URL=sqlite:///./arbiter.db
PROJECT_ROOTS=/home/user/dev
PROJECT_SCAN_DEPTH=4
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=
LLM_MODEL=
LLM_REASONING_EFFORT=none
FILTER_LLM_MODEL=gpt-5.4-nano
AGENT_MAX_STEPS=12
AUTO_APPROVE_READ_ONLY=true
AUTO_APPROVE_LOW_RISK=false
DEFAULT_PORT_SEARCH_RANGE_START=3000
DEFAULT_PORT_SEARCH_RANGE_END=9999
OBSERVATION_INTERVAL_SECONDS=3
```

## 22. Running the application

Normal setup:

```bash
cp .env.example .env
uv sync --extra dev --extra mcp
uv run arbiter serve
```

Then open:

```text
http://127.0.0.1:8765
```

## 23. Testing and quality controls

The test suite uses fake scanners and Docker objects by default and does not mutate
the real Docker environment. It covers:

- `ss` parsing and port ownership;
- deterministic allocation and conflict detection;
- project discovery and SQLite registry behavior;
- Compose formats and environment-variable ports;
- structured Compose and `.env` editing;
- Makefile parsing and risk classification;
- secret redaction;
- approval expiration and argument immutability;
- action execution and verification;
- API health, projects, ports, Docker, approvals, and agent queries;
- LLM reasoning configuration and degraded provider errors;
- UI asset mounting and root redirect;
- MCP and A2A adapter construction;
- deterministic port reconciliation from registered and runtime evidence;
- property-based allocator invariants and concurrent approval reservations;
- an opt-in live-Docker Compose reconciliation and rollback suite.

Run quality checks with:

```bash
uv run pytest
uv run ruff check .
```

## 24. Current limitations and extension points

- YAML semantic editing can change comments or formatting.
- Health checks focus on configuration, containers, Docker health, and port
  ownership; project-specific HTTP/database probes need future health profiles.
- Compose is the directly supported project startup mechanism. Unknown custom
  scripts are not guessed or executed.
- The deterministic natural-language intent set is intentionally small; other
  questions require a configured compatible LLM.
- A2A is an adapter and capability mapping rather than a mandatory full protocol
  SDK deployment.
- Docker disk usage is practical but not yet a detailed byte-by-byte cleanup plan.
- The UI is a local single-user control panel and does not implement remote-user
  authentication.

The architecture is prepared for additional structured configuration actions,
health profiles, richer cleanup analysis, more agent tools, IDE integrations, and
other specialized development agents without duplicating core behavior.

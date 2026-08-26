# Arbiter — next steps

Updated: 2026-08-26

## Product focus

Arbiter should own one narrow problem exceptionally well:

> Understand why independently developed local projects interfere with one
> another, then reconcile those conflicts through an evidence-backed,
> approval-gated, verified workflow.

The next releases should deepen the resource graph, conflict reasoning, safety
boundary, and integration evidence. Avoid adding broad new management surfaces
until those foundations are demonstrably reliable.

## Completed in `feat/arbiter-priority-foundation`

- [x] Renamed the product, Python package, CLI, API identity, MCP server, A2A
  card, UI, database default, and managed backup directory to **Arbiter**.
- [x] Kept legacy `DEV_AGENT_HOST` and `DEV_AGENT_PORT` environment aliases for
  migration while making `ARBITER_HOST` and `ARBITER_PORT` canonical.
- [x] Confirmed the agent already uses the industry-standard LangChain v1
  `create_agent` API backed by LangGraph, typed tools, bounded model calls, and
  streamed execution evidence.
- [x] Added typed, read-only per-project port reconciliation plans.
- [x] Reconciliation now reserves both observed runtime ports and every
  registered project declaration before selecting an alternative.
- [x] Classified declaration conflicts, same-project duplicate claims, and
  unrelated runtime ownership separately, with Compose/`.env` source evidence.
- [x] Exposed reconciliation through REST and the bounded agent/MCP tool
  registries, and made `prepare_project` consume the same deterministic plan.
- [x] Added service and API coverage for declaration-only collisions, runtime
  collisions, duplicate claims, and deterministic allocation.
- [x] Added opt-in live-Docker smoke tests for inspection and an
  approval-gated temporary-container lifecycle.
- [x] Added a safe-bind guard: non-loopback serving requires the explicit
  `ALLOW_REMOTE_ACCESS=true` escape hatch.

## P0 — reliability and security evidence

- [x] Add a live-Docker Compose fixture that exercises the full workflow:
  detect conflict → propose → approve → edit → recreate one service → verify.
- [x] Add forced-failure live tests proving Compose and `.env` edits roll back
  after validation or recreation failures.
- [x] Add property-based tests for allocator invariants across TCP/UDP,
  configured range boundaries, duplicate declarations, and exhausted ranges.
- [x] Add concurrency tests proving two simultaneous preparation requests cannot
  approve the same replacement port.
- [ ] Separate observation/API concerns from privileged Docker mutation behind a
  narrow executor interface, ideally a local Unix socket with explicit actions.
- [ ] Add authentication, origin/CSRF protection, and auditable operator identity
  before treating remote access as supported. `ALLOW_REMOTE_ACCESS` is only an
  acknowledgement that an external boundary exists.
- [ ] Generate an API coverage inventory so every mutation route is paired with
  authorization, approval, immutable-argument, failure, and verification tests.

Completed on `feat/arbiter-p0-reliability`: reconciliation edits now compensate
after service-recreation failures, pending approvals reserve replacement ports in
SQLite by protocol, and reservations are released on rejection, expiration, or
execution completion. The Docker suite exercises both direct Compose and `.env`
sources and cleans up its labelled resources.

## P1 — deepen the differentiator

- [ ] Make every graph edge carry an evidence class: `declared`, `observed`, or
  `inferred`, plus source and confidence.
- [ ] Distinguish Compose `depends_on` from observed runtime communication.
- [ ] Correlate host/container sockets and configured service URLs into observed
  communication edges without claiming traffic that was not seen.
- [ ] Model reconciliation as a stable plan with preconditions and a state hash;
  reject approval execution when relevant machine/configuration state changed.
- [ ] Support multi-file Compose projects and changes spanning more than the
  first Compose file.
- [ ] Add project-defined HTTP/TCP/command health profiles so verification can
  prove application readiness rather than only container state and port binding.
- [ ] Improve the UI conflict view to show reason, owner/claim evidence,
  configuration source, proposed replacement, and affected resources.

## P2 — operational depth

- [ ] Persist a bounded causal event timeline linking observations, proposals,
  approvals, actions, and verification results.
- [ ] Add historical resource snapshots only where they directly help explain a
  conflict or failed reconciliation; do not attempt to become a general metrics
  platform.
- [ ] Expand Podman/containerd support only after defining a runtime capability
  contract and testing equivalent safety semantics.
- [ ] Improve Makefile inspection conservatively; do not label it execution
  intelligence until includes, variables, recursive Make, and pattern rules have
  explicit behavior and tests.

## Release gate for the next milestone

The next milestone is ready when:

1. The full Compose conflict-repair path passes against a real Docker daemon.
2. Rollback and stale-plan behavior are proven under failure and concurrency.
3. Every mutation API has approval, redaction, error, and verification coverage.
4. Remote exposure has first-party authentication or is documented as strictly
   unsupported rather than merely discouraged.
5. Graph consumers can distinguish declared, observed, and inferred relationships.

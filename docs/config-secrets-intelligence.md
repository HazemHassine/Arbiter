# Smart Config, .env & Secrets Intelligence

Arbiter's **Smart Config, .env & Secrets Intelligence** engine proactively detects configuration drift across `.env`, `compose.yaml`, and `.env.example` files, conducts safe environment variable audits without leaking plaintext secrets, and provides visual diffs with dry-run state previews before applying changes.

---

## Overview

Local development environments frequently suffer from subtle configuration drift between environment files, container orchestrators, and runtime process states. The Config Intelligence engine eliminates these issues by:

1. **Port Drift & Variable Detection**: Reconciling port declarations across `.env`, `compose.yaml`, `.env.example`, and host network listeners.
2. **Safe Secrets Auditing**: Comparing active environment variables with example templates and detecting unconfigured placeholders while strictly masking sensitive credentials.
3. **Visual Diffs & Time-Travel Previews**: Generating unified side-by-side diffs and forecasting before-and-after state transitions across files, ports, and container lifecycles in the operator approval workflow.

---

## Core Capabilities

### 1. Port Drift Detection

The engine inspects and cross-references port definitions across multiple sources:

- **Compose Default Mismatch**: Detects when a `.env` variable overrides a default specified in `compose.yaml` (e.g., `WEB_PORT=3000` overriding `${WEB_PORT:-8080}:80`).
- **Unresolved Compose Variables**: Identifies variables referenced in `compose.yaml` that lack a fallback default and are missing from `.env`.
- **Unreferenced `.env` Port Variables**: Flags port definitions in `.env` that are not consumed by any compose service or project target.
- **Example vs. Environment Divergence**: Highlights differences between template values in `.env.example` and local `.env` values.
- **Runtime Port Collisions**: Checks configured host ports against live listening sockets and flags collisions with external processes before container creation.

### 2. Safe Environment & Secrets Auditing

The audit system ensures complete visibility into missing or misconfigured configuration variables without risking credential exposure:

- **Missing Variables**: Identifies variables defined in `.env.example` (or `.env.sample`, `.env.template`, `.env.dist`, `.env.default`) that are absent from `.env`.
- **Placeholder Detection**: Flags variables set to common unconfigured placeholder strings (such as `change_me`, `your_api_key_here`, `todo`, `insert_secret`).
- **Undocumented Variables**: Highlights local `.env` keys that have not been documented in the repository's `.env.example`.
- **Zero Raw Secret Exposure**: Sensitive keys matching patterns such as `API_KEY`, `TOKEN`, `PASSWORD`, `SECRET`, `PRIVATE_KEY`, `CREDENTIALS`, etc. are masked with fixed-length redactions (e.g., `sk-proj-••••••••cdef`, `pa••••••••23`), retaining prefix/suffix tokens for operational debugging while preventing plaintext exposure in logs, APIs, and UIs.

### 3. Visual Diffs & Dry-Run Time Travel

Prior to executing any configuration change or port reconciliation action:

- **Unified Visual Diffs**: Generates structured line-by-line diffs (`context`, `added`, `deleted`) for target files. If the modified file is an environment configuration file, secrets are masked automatically in the diff output.
- **State Transition Forecasting**: Simulates the exact state transitions for affected resources (files updated, ports remapped, containers restarted or recreated).
- **Approval Workflow Integration**: Embedded directly into Arbiter's approval system (`/api/v1/approvals`) and CLI to provide operators with full context before approving high-risk operations.

---

## CLI Reference

### `arbiter config drift`
Audit all registered projects or a specific project for port drift and configuration mismatches.

```bash
# Audit all registered projects
arbiter config drift

# Audit a specific project
arbiter config drift <project-name-or-id>
```

#### Example Output
```json
{
  "project_name": "web-service",
  "status": "warning",
  "drift_score": 14,
  "port_drifts": [
    {
      "service": "web",
      "variable": "WEB_PORT",
      "env_value": 3000,
      "compose_default": 8080,
      "drift_type": "compose_default_mismatch",
      "severity": "warning",
      "message": "WEB_PORT in .env (3000) differs from compose.yaml default (8080)",
      "suggested_fix": "Update compose.yaml default or align .env with compose.yaml"
    }
  ],
  "missing_env_vars": [
    {
      "key": "DATABASE_URL",
      "status": "missing",
      "is_secret": true,
      "description": "Required database connection string"
    }
  ],
  "recommendations": [
    "Align WEB_PORT in .env (3000) with compose.yaml (8080)",
    "Add DATABASE_URL to .env (see .env.example)"
  ]
}
```

### `arbiter config audit`
Perform a credential-safe audit of environment variables and secrets.

```bash
# Summary audit across all projects
arbiter config audit

# Detailed audit for a specific project
arbiter config audit <project-name-or-id>
```

---

## REST API Reference

### `GET /api/v1/config-drift`
Returns configuration drift analysis and environment audit reports for all registered projects.

**Response:** `200 OK`
```json
[
  {
    "project_id": "proj-abc123",
    "project_name": "web-service",
    "status": "warning",
    "drift_score": 14,
    "has_env": true,
    "has_env_example": true,
    "has_compose": true,
    "port_drifts": [],
    "missing_env_vars": [],
    "env_audit": [],
    "recommendations": []
  }
]
```

### `GET /api/v1/projects/{identifier}/config-drift`
Returns configuration drift analysis and environment audit report for a specific project ID or name.

**Parameters:**
- `identifier` (path, string): Project ID or project directory name.

**Response:** `200 OK` (returns a single `ProjectConfigDrift` object).

### Approval Integration: `GET /api/v1/approvals/{approval_id}`
Approval records automatically include a `time_travel` object containing visual diffs and simulated state transitions for the proposed action.

---

## Agent Tool Reference

The deterministic and LLM agent service provides the `config_drift_audit` tool:

- **Name**: `config_drift_audit`
- **Description**: Audit a project for .env and Compose configuration drift, port divergences, and missing variables.
- **Parameters**:
  - `identifier` (string, optional): Project name or ID to audit. If omitted, audits all registered projects.

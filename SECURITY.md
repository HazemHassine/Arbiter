# Security policy

## Supported versions

Security fixes are made on `main` and included in the next tagged release. The
current `0.4.x` line is the supported release line.

## Reporting a vulnerability

Please do not disclose an unpatched vulnerability in a public issue. If private
vulnerability reporting is available in the repository's Security tab, use it;
otherwise contact the maintainer privately through the repository owner's GitHub
profile. Include affected versions, impact, prerequisites, reproduction steps,
and any suggested mitigation. Remove credentials, private source code, and other
personal data from the report.

## Security model

Arbiter is a single-user, local-first workstation control plane. It intentionally
has no built-in remote user authentication and binds to loopback by default. Host
validation and browser same-origin checks protect the local HTTP service from
hostile websites, but they do not turn it into a multi-user service.

If non-loopback access is enabled, the operator must provide TLS, authentication,
authorization, an exact `ARBITER_TRUSTED_HOSTS` allowlist, and network access
controls outside Arbiter. `ALLOW_REMOTE_ACCESS=true` only acknowledges that those
controls exist.

Arbiter can inspect the local process table, read recognized configuration files
inside explicitly registered projects, and access the Docker daemon. An account
that can call the API is therefore trusted at the same level as the workstation
operator. Docker socket access is particularly sensitive and can commonly be
used to obtain host-level control.

Risky operations use immutable, expiring approvals and a typed action dispatcher.
Approved Make targets and project configuration still originate from the
registered project and may execute project-controlled code. Review project
provenance and the exact approval payload before approving an action.

The complete audit record and remaining limitations are in
[`docs/content/docs/security.mdx`](docs/content/docs/security.mdx).

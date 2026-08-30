from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

from arbiter.models import Risk
from arbiter.services import Services


@dataclass
class PromptStatus:
    pending_approvals: int
    port_conflicts: int
    running_containers: int
    registered_projects: int
    status: str  # "ok", "warning", "critical"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def get_prompt_status(services: Services) -> PromptStatus:
    """Fast, safe status gatherer for shell prompts."""
    pending_approvals = 0
    port_conflicts = 0
    running_containers = 0
    registered_projects = 0
    approvals = []

    try:
        approvals = services.actions.approvals.list()
        pending_approvals = sum(1 for a in approvals if a.status == "pending")
    except Exception:
        pass

    try:
        conflicts = services.ports.detect_port_conflicts()
        port_conflicts = len(conflicts)
    except Exception:
        pass

    try:
        containers = services.docker.list_containers()
        running_containers = sum(1 for c in containers if c.state == "running")
    except Exception:
        pass

    try:
        projects = services.projects.list_projects()
        registered_projects = len(projects)
    except Exception:
        pass

    if port_conflicts > 0 or any(
        a.risk in (Risk.HIGH_RISK, Risk.DESTRUCTIVE) for a in (approvals or []) if a.status == "pending"
    ):
        status = "critical"
    elif pending_approvals > 0:
        status = "warning"
    else:
        status = "ok"

    return PromptStatus(
        pending_approvals=pending_approvals,
        port_conflicts=port_conflicts,
        running_containers=running_containers,
        registered_projects=registered_projects,
        status=status,
    )


def format_prompt_status(status: PromptStatus, output_format: str = "pill", color: bool = True) -> str:
    """Format the prompt status into target format."""
    fmt = output_format.lower()

    if fmt == "json":
        return json.dumps(status.to_dict(), indent=2)

    app_unit = "pending approval" if status.pending_approvals == 1 else "pending approvals"
    conf_unit = "conflict" if status.port_conflicts == 1 else "conflicts"
    app_text = f"{status.pending_approvals} {app_unit}"
    conf_text = f"{status.port_conflicts} {conf_unit}"

    if fmt == "plain":
        return f"Arbiter: {app_text} | {conf_text}"

    if fmt == "short":
        if color:
            c_app = "\x1b[1;33m" if status.pending_approvals > 0 else "\x1b[90m"
            c_conf = "\x1b[1;31m" if status.port_conflicts > 0 else "\x1b[90m"
            app_part = f"{c_app}{status.pending_approvals}!\x1b[0m"
            conf_part = f"{c_conf}{status.port_conflicts}⚡\x1b[0m"
            return f"\x1b[1;36m⚡\x1b[0m {app_part} {conf_part}"
        return f"⚡ {status.pending_approvals}! {status.port_conflicts}⚡"

    if fmt == "starship":
        if status.pending_approvals == 0 and status.port_conflicts == 0:
            return f"⚡ Arbiter: ok ({status.running_containers} running)"
        pills: list[str] = []
        if status.pending_approvals > 0:
            pills.append(app_text)
        if status.port_conflicts > 0:
            pills.append(conf_text)
        return f"⚡ Arbiter: {' | '.join(pills)}"

    # Default "pill" format
    if not color:
        return f"⚡ Arbiter: {app_text} | {conf_text}"

    prefix = "\x1b[1;36m⚡ Arbiter:\x1b[0m"
    app_badge = f"\x1b[1;33m{app_text}\x1b[0m" if status.pending_approvals > 0 else "\x1b[32m0 pending\x1b[0m"
    conf_badge = f"\x1b[1;31m{conf_text}\x1b[0m" if status.port_conflicts > 0 else "\x1b[32m0 conflicts\x1b[0m"

    return f"{prefix} {app_badge} | {conf_badge}"


def generate_shell_init(shell_type: str) -> str:
    """Generate shell initialization snippet for the requested shell / tool."""
    shell = shell_type.strip().lower()

    if shell == "starship":
        return """# Starship custom module configuration
# Add this block to your ~/.config/starship.toml:

[custom.arbiter]
command = "arbiter prompt --format starship"
when = "command -v arbiter >/dev/null 2>&1"
shell = ["sh"]
format = "[$output]($style) "
style = "bold cyan"
description = "Arbiter local environment status pill"
"""

    if shell == "zsh":
        return """# Arbiter Zsh prompt integration
# Add this snippet to your ~/.zshrc:

_arbiter_prompt_precmd() {
  if command -v arbiter >/dev/null 2>&1; then
    export ARBITER_PROMPT="$(arbiter prompt --format pill 2>/dev/null)"
  else
    unset ARBITER_PROMPT
  fi
}
autoload -Uz add-zsh-hook
add-zsh-hook precmd _arbiter_prompt_precmd

# Tip: To show the pill in your prompt, add $ARBITER_PROMPT to PROMPT or RPROMPT:
# RPROMPT='${ARBITER_PROMPT}'
"""

    if shell == "bash":
        return """# Arbiter Bash prompt integration
# Add this snippet to your ~/.bashrc:

_arbiter_prompt_update() {
  if command -v arbiter >/dev/null 2>&1; then
    export ARBITER_PROMPT="$(arbiter prompt --format pill 2>/dev/null)"
  else
    unset ARBITER_PROMPT
  fi
}
if [[ ! "$PROMPT_COMMAND" =~ "_arbiter_prompt_update" ]]; then
  PROMPT_COMMAND="_arbiter_prompt_update${PROMPT_COMMAND:+; $PROMPT_COMMAND}"
fi

# Tip: To show the pill in your prompt, prepend ${ARBITER_PROMPT} to PS1:
# PS1='${ARBITER_PROMPT} '"$PS1"
"""

    if shell == "fish":
        return """# Arbiter Fish prompt integration
# Add this to ~/.config/fish/conf.d/arbiter_prompt.fish or ~/.config/fish/config.fish:

function _arbiter_prompt_update --on-event fish_prompt
  if type -q arbiter
    set -g ARBITER_PROMPT (arbiter prompt --format pill 2>/dev/null)
  else
    set -e ARBITER_PROMPT
  end
end

# Tip: Print $ARBITER_PROMPT inside your fish_prompt function:
# echo -n "$ARBITER_PROMPT "
"""

    raise ValueError(f"Unknown shell type '{shell_type}'. Supported: starship, zsh, bash, fish")

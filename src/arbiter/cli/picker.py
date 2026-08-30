from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from typing import Any

from arbiter.models import ApprovalInfo, ContainerInfo, PortOwner, Project


@dataclass
class PickerItem:
    id: str
    title: str
    subtitle: str = ""
    badge: str = ""
    badge_style: str = ""
    details: str = ""
    raw: Any = None


def fuzzy_match(query: str, text: str) -> tuple[bool, int, list[int]]:
    """Fuzzy match query against text.

    Returns (is_match, score, matched_indices). Higher score indicates a better match.
    """
    if not query:
        return True, 0, []

    q = query.lower()
    t = text.lower()

    if q == t:
        return True, 1000, list(range(len(text)))

    # Check subsequence existence and collect indices
    t_idx = 0
    indices: list[int] = []
    for char in q:
        found = t.find(char, t_idx)
        if found == -1:
            return False, -1, []
        indices.append(found)
        t_idx = found + 1

    # Score calculation
    score = 100

    # Prefix match bonus
    if indices[0] == 0:
        score += 120

    # Contiguous characters and word boundary bonus
    for i, idx in enumerate(indices):
        if i > 0 and idx == indices[i - 1] + 1:
            score += 40
        if idx == 0 or text[idx - 1] in {"/", "-", "_", ".", ":", " ", "\t"}:
            score += 30

    # Distance penalty between first and last match
    match_span = indices[-1] - indices[0] + 1
    score -= match_span * 2

    # Excess length penalty
    score -= len(text) - len(query)

    return True, score, indices


class FuzzyPicker:
    """Interactive fzf-style picker for terminal selection."""

    def __init__(self, items: list[PickerItem], title: str = "Select an item", placeholder: str = "") -> None:
        self.items = items
        self.title = title
        self.query = placeholder
        self.selected_index = 0

    def filter_items(self) -> list[tuple[PickerItem, list[int]]]:
        if not self.query.strip():
            return [(item, []) for item in self.items]

        scored: list[tuple[int, PickerItem, list[int]]] = []
        for item in self.items:
            searchable = f"{item.title} {item.subtitle} {item.badge} {item.id}"
            is_match, score, indices = fuzzy_match(self.query, searchable)
            if is_match:
                scored.append((score, item, indices))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [(item, indices) for _, item, indices in scored]

    def run_interactive(self, input_stream=None, output_stream=None) -> PickerItem | None:
        """Run interactive picker using terminal raw mode."""
        inp = input_stream or sys.stdin
        out = output_stream or sys.stdout

        if not hasattr(inp, "isatty") or not inp.isatty():
            # Non-interactive fallback: if query matches or single item, return it
            filtered = self.filter_items()
            return filtered[0][0] if filtered else (self.items[0] if self.items else None)

        import termios
        import tty

        fd = inp.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            # Hide cursor and enter alternate screen or clear
            out.write("\x1b[?25l")
            out.flush()

            while True:
                filtered = self.filter_items()
                if self.selected_index >= len(filtered):
                    self.selected_index = max(0, len(filtered) - 1)

                self._render(filtered, out)

                # Read key sequence
                char = inp.read(1)
                if not char:
                    break

                if char in ("\r", "\n"):
                    if filtered and 0 <= self.selected_index < len(filtered):
                        return filtered[self.selected_index][0]
                    return None

                if char in ("\x03", "\x04"):  # Ctrl-C, Ctrl-D
                    return None

                if char == "\x1b":  # Escape sequence
                    import select

                    r, _, _ = select.select([inp], [], [], 0.05)
                    if not r:
                        # Standalone escape
                        return None
                    seq = inp.read(2)
                    if seq == "[A":  # Up arrow
                        self.selected_index = max(0, self.selected_index - 1)
                    elif seq == "[B":  # Down arrow
                        self.selected_index = min(len(filtered) - 1, self.selected_index + 1)
                    elif seq == "[Z":  # Shift-Tab
                        self.selected_index = max(0, self.selected_index - 1)
                    continue

                if char == "\t":  # Tab
                    self.selected_index = min(len(filtered) - 1, self.selected_index + 1)
                elif char in ("\x7f", "\x08"):  # Backspace
                    if self.query:
                        self.query = self.query[:-1]
                        self.selected_index = 0
                elif char == "\x15":  # Ctrl-U (clear input)
                    self.query = ""
                    self.selected_index = 0
                elif char == "\x17":  # Ctrl-W (delete word)
                    parts = self.query.rstrip().rsplit(" ", 1)
                    self.query = parts[0] + " " if len(parts) > 1 else ""
                    self.selected_index = 0
                elif char.isprintable():
                    self.query += char
                    self.selected_index = 0

        finally:
            # Restore cursor and terminal attributes
            out.write("\x1b[?25h\x1b[2J\x1b[H")
            out.flush()
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

    def _render(self, filtered: list[tuple[PickerItem, list[int]]], out) -> None:
        lines: list[str] = []
        lines.append("\x1b[2J\x1b[H")  # Clear screen and move to top-left

        # Header
        lines.append(f"\x1b[1;36m== Arbiter Fuzzy Selector ==\x1b[0m \x1b[90m({self.title})\x1b[0m\r\n")
        lines.append(f"\x1b[1;33m> \x1b[0m{self.query}\x1b[7m \x1b[0m\r\n")
        lines.append(f"\x1b[90mShowing {len(filtered)} / {len(self.items)} items\x1b[0m\r\n")
        lines.append("\x1b[90m" + "─" * 60 + "\x1b[0m\r\n")

        # Items list (limit to 10 visible)
        max_visible = 10
        start_idx = max(0, self.selected_index - max_visible // 2)
        end_idx = min(len(filtered), start_idx + max_visible)

        if not filtered:
            lines.append("  \x1b[90m(no matches found)\x1b[0m\r\n")
        else:
            for idx in range(start_idx, end_idx):
                item, _ = filtered[idx]
                is_selected = idx == self.selected_index
                pointer = "\x1b[1;32m❯\x1b[0m" if is_selected else " "
                badge_str = f" \x1b[1;35m[{item.badge}]\x1b[0m" if item.badge else ""
                sub_str = f" \x1b[90m- {item.subtitle}\x1b[0m" if item.subtitle else ""

                if is_selected:
                    lines.append(f" {pointer} \x1b[1;37;44m {item.title} \x1b[0m{badge_str}{sub_str}\r\n")
                else:
                    lines.append(f" {pointer} \x1b[37m{item.title}\x1b[0m{badge_str}{sub_str}\r\n")

        # Preview pane of selected item
        lines.append("\x1b[90m" + "─" * 60 + "\x1b[0m\r\n")
        if filtered and 0 <= self.selected_index < len(filtered):
            selected_item = filtered[self.selected_index][0]
            lines.append(f"\x1b[1;34mPreview [\x1b[37m{selected_item.id}\x1b[1;34m]:\x1b[0m\r\n")
            if selected_item.details:
                for d_line in selected_item.details.strip().split("\n")[:8]:
                    lines.append(f"  \x1b[36m{d_line}\x1b[0m\r\n")
            else:
                lines.append(f"  \x1b[90mID: {selected_item.id}\x1b[0m\r\n")

        # Footer
        lines.append("\x1b[90m" + "─" * 60 + "\x1b[0m\r\n")
        lines.append("\x1b[90m[↑/↓/Tab] Navigate  [Enter] Select  [Esc/Ctrl-C] Abort  [Ctrl-U] Clear\x1b[0m\r\n")

        out.write("".join(lines))
        out.flush()


def pick_project(projects: list[Project], prompt: str = "Select Project") -> Project | None:
    if not projects:
        return None
    items = [
        PickerItem(
            id=p.id,
            title=p.name,
            subtitle=str(p.path),
            badge=f"{len(p.services)} services",
            details=json.dumps(
                {
                    "id": p.id,
                    "name": p.name,
                    "path": str(p.path),
                    "services": list(p.services),
                    "ports": [f"{pt.service}:{pt.host_port}->{pt.container_port}" for pt in p.ports],
                    "compose_files": [str(c) for c in p.compose_files],
                },
                indent=2,
            ),
            raw=p,
        )
        for p in projects
    ]
    picker = FuzzyPicker(items, title=prompt)
    selected = picker.run_interactive()
    return selected.raw if selected else None


def pick_container(containers: list[ContainerInfo], prompt: str = "Select Container") -> ContainerInfo | None:
    if not containers:
        return None
    items = [
        PickerItem(
            id=c.id,
            title=c.name,
            subtitle=f"{c.image} ({c.state})",
            badge=c.compose_service or c.state,
            details=json.dumps(
                {
                    "id": c.id,
                    "name": c.name,
                    "image": c.image,
                    "state": c.state,
                    "project": c.compose_project,
                    "service": c.compose_service,
                    "ports": [f"{p.host_port}:{p.container_port}/{p.protocol}" for p in c.ports],
                },
                indent=2,
            ),
            raw=c,
        )
        for c in containers
    ]
    picker = FuzzyPicker(items, title=prompt)
    selected = picker.run_interactive()
    return selected.raw if selected else None


def pick_approval(approvals: list[ApprovalInfo], prompt: str = "Select Pending Approval") -> ApprovalInfo | None:
    if not approvals:
        return None
    items = [
        PickerItem(
            id=a.id,
            title=f"{a.action} ({a.risk.value})",
            subtitle=a.summary or a.id,
            badge=a.status,
            details=json.dumps(
                {
                    "id": a.id,
                    "action": a.action,
                    "risk": a.risk.value,
                    "status": a.status,
                    "summary": a.summary,
                    "arguments": a.arguments,
                    "created_at": str(a.created_at),
                    "expires_at": str(a.expires_at),
                },
                indent=2,
            ),
            raw=a,
        )
        for a in approvals
    ]
    picker = FuzzyPicker(items, title=prompt)
    selected = picker.run_interactive()
    return selected.raw if selected else None


def pick_port(ports: list[PortOwner], prompt: str = "Select Port") -> PortOwner | None:
    if not ports:
        return None
    items = [
        PickerItem(
            id=f"{p.protocol}:{p.port}",
            title=f"Port {p.port}/{p.protocol}",
            subtitle=p.process or p.container or p.owner_type,
            badge=f"PID {p.pid}" if p.pid else (p.service or p.owner_type),
            details=json.dumps(
                {
                    "port": p.port,
                    "protocol": p.protocol,
                    "owner_type": p.owner_type,
                    "pid": p.pid,
                    "process": p.process,
                    "command": p.command,
                    "container": p.container,
                    "project": p.project,
                    "service": p.service,
                },
                indent=2,
            ),
            raw=p,
        )
        for p in ports
    ]
    picker = FuzzyPicker(items, title=prompt)
    selected = picker.run_interactive()
    return selected.raw if selected else None

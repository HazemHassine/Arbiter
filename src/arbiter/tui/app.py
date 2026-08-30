from __future__ import annotations

import contextlib
import curses
import sys
import time
from typing import Any

from arbiter.config import get_settings
from arbiter.services import Services, build_services
from arbiter.tui.views import (
    TAB_APPROVALS,
    TAB_CONTAINERS,
    TAB_LOGS,
    TAB_NAMES,
    TAB_PORTS,
    TAB_PROJECTS,
    TUIData,
    TUIState,
    format_approval_row,
    format_container_row,
    format_port_row,
    format_project_row,
    get_item_details,
)


class ArbiterTUI:
    def __init__(self, services: Services) -> None:
        self.services = services
        self.state = TUIState()
        self.data = TUIData()
        self.running = True
        self.last_refresh_time = 0.0
        self.refresh_interval = 3.0

    def load_data(self) -> None:
        """Fetch fresh data from services."""
        try:
            self.data.ports = self.services.ports.list_used_ports()
        except Exception:
            self.data.ports = []

        try:
            self.data.conflicts = self.services.ports.detect_port_conflicts()
        except Exception:
            self.data.conflicts = []

        try:
            self.data.containers = self.services.docker.list_containers()
        except Exception:
            self.data.containers = []

        try:
            self.data.approvals = self.services.actions.approvals.list()
        except Exception:
            self.data.approvals = []

        try:
            self.data.projects = self.services.projects.list_projects()
        except Exception:
            self.data.projects = []

        self.last_refresh_time = time.time()

    def get_current_items(self) -> list[Any]:
        """Get filtered items for the current active tab."""
        tab = self.state.active_tab
        query = self.state.current_filter_query.strip().lower()

        if tab == TAB_PORTS:
            items = self.data.ports
            if query:
                return [
                    p
                    for p in items
                    if query in f"{p.port} {p.protocol} {p.process} {p.container} {p.project} {p.service}".lower()
                ]
            return items

        if tab == TAB_CONTAINERS:
            items = self.data.containers
            if query:
                return [
                    c
                    for c in items
                    if query in f"{c.name} {c.image} {c.state} {c.compose_project} {c.compose_service}".lower()
                ]
            return items

        if tab == TAB_APPROVALS:
            items = self.data.approvals
            if query:
                return [
                    a
                    for a in items
                    if query in f"{a.id} {a.action} {a.risk.value} {a.status} {a.summary}".lower()
                ]
            return items

        if tab == TAB_PROJECTS:
            items = self.data.projects
            if query:
                return [
                    p
                    for p in items
                    if query in f"{p.id} {p.name} {p.path} {' '.join(s for s in p.services)}".lower()
                ]
            return items

        if tab == TAB_LOGS:
            return self.state.log_lines

        return []

    def fetch_container_logs(self, container_id: str, container_name: str = "") -> None:
        """Load logs for a specific container."""
        try:
            raw_logs = self.services.docker.logs(container_id, tail=300)
            self.state.log_container_id = container_id
            self.state.log_container_name = container_name or container_id[:12]
            self.state.log_lines = raw_logs.strip().split("\n") if raw_logs.strip() else ["(No logs output)"]
            self.state.active_tab = TAB_LOGS
            self.state.log_scroll_offset = max(0, len(self.state.log_lines) - 20)
            self.state.status_message = f"Loaded logs for {self.state.log_container_name}"
            self.state.status_is_error = False
        except Exception as exc:
            self.state.status_message = f"Failed to fetch logs: {exc}"
            self.state.status_is_error = True

    def execute_approval(self, approval_id: str) -> None:
        """Approve and execute an action."""
        try:
            res = self.services.actions.approve_and_execute(approval_id)
            self.state.status_message = f"Executed {res.action} ({res.status})"
            self.state.status_is_error = res.status != "completed"
            self.load_data()
        except Exception as exc:
            self.state.status_message = f"Execution failed: {exc}"
            self.state.status_is_error = True

    def prepare_selected_project(self, project_id: str) -> None:
        """Trigger agent preparation for a project."""
        try:
            from arbiter.agent.service import AgentService

            agent = AgentService(self.services)
            res = agent.prepare_project(identifier=project_id)
            status = res.get("status", "unknown")
            self.state.status_message = f"Prepared project: status={status}"
            self.state.status_is_error = False
            self.load_data()
        except Exception as exc:
            self.state.status_message = f"Prepare failed: {exc}"
            self.state.status_is_error = True

    def run(self, stdscr) -> None:
        """Main curses interactive loop."""
        curses.curs_set(0)
        stdscr.nodelay(True)
        stdscr.keypad(True)

        # Initialize color pairs
        if curses.has_colors():
            curses.start_color()
            curses.use_default_colors()
            curses.init_pair(1, curses.COLOR_CYAN, -1)  # Headers / Accent
            curses.init_pair(2, curses.COLOR_GREEN, -1)  # Success / Active
            curses.init_pair(3, curses.COLOR_YELLOW, -1)  # Warnings / Pending
            curses.init_pair(4, curses.COLOR_RED, -1)  # Danger / Conflicts
            curses.init_pair(5, curses.COLOR_BLACK, curses.COLOR_CYAN)  # Highlight / Selection
            curses.init_pair(6, curses.COLOR_WHITE, curses.COLOR_BLUE)  # Active tab badge
            curses.init_pair(7, curses.COLOR_WHITE, -1)  # Normal text

        self.load_data()

        while self.running:
            # Auto-refresh periodically
            if time.time() - self.last_refresh_time > self.refresh_interval:
                self.load_data()

            max_y, max_x = stdscr.getmaxyx()
            stdscr.erase()

            if max_y < 12 or max_x < 50:
                stdscr.addstr(0, 0, "Terminal window too small for Arbiter TUI.")
                stdscr.refresh()
                time.sleep(0.1)
                continue

            self._draw_header(stdscr, max_x)
            self._draw_tabs(stdscr, max_x)

            if self.state.active_tab == TAB_LOGS:
                self._draw_logs_view(stdscr, max_y, max_x)
            else:
                self._draw_split_view(stdscr, max_y, max_x)

            self._draw_footer(stdscr, max_y, max_x)

            if self.state.show_help:
                self._draw_help_modal(stdscr, max_y, max_x)
            elif self.state.confirm_action:
                self._draw_confirm_modal(stdscr, max_y, max_x)

            stdscr.refresh()

            # Handle input
            try:
                key = stdscr.getch()
            except Exception:
                key = -1

            if key != -1:
                self._handle_input(key)

            time.sleep(0.03)

    def _draw_header(self, stdscr, max_x: int) -> None:
        pending_count = sum(1 for a in self.data.approvals if a.status == "pending")
        conflict_count = len(self.data.conflicts)
        container_count = sum(1 for c in self.data.containers if c.state == "running")

        title = "⚡ ARBITER DEV ENVIRONMENT CONTROLLER"
        stats = f"[⚡ {pending_count} Pending | ⚠️ {conflict_count} Conflicts | ● {container_count} Containers]"

        stdscr.attron(curses.color_pair(1) | curses.A_BOLD)
        stdscr.addstr(0, 1, title[:max_x - 2])
        stdscr.attroff(curses.color_pair(1) | curses.A_BOLD)

        if len(title) + len(stats) + 4 < max_x:
            color = curses.color_pair(4 if conflict_count > 0 else (3 if pending_count > 0 else 2))
            stdscr.attron(color)
            stdscr.addstr(0, max_x - len(stats) - 2, stats)
            stdscr.attroff(color)

    def _draw_tabs(self, stdscr, max_x: int) -> None:
        curr_x = 1
        for i, name in enumerate(TAB_NAMES):
            badge = f" {i + 1}: {name} "
            if i == self.state.active_tab:
                stdscr.attron(curses.color_pair(6) | curses.A_BOLD)
                stdscr.addstr(1, curr_x, badge)
                stdscr.attroff(curses.color_pair(6) | curses.A_BOLD)
            else:
                stdscr.attron(curses.color_pair(7))
                stdscr.addstr(1, curr_x, badge)
                stdscr.attroff(curses.color_pair(7))
            curr_x += len(badge) + 1

        # Divider line
        stdscr.addstr(2, 0, "─" * (max_x - 1))

    def _draw_split_view(self, stdscr, max_y: int, max_x: int) -> None:
        left_width = int(max_x * 0.55)
        right_width = max_x - left_width - 2
        content_height = max_y - 6

        items = self.get_current_items()
        selected_idx = self.state.current_selected_index

        if selected_idx >= len(items):
            selected_idx = max(0, len(items) - 1)
            self.state.set_current_selected_index(selected_idx)

        # Draw Left Table Header
        header_y = 3
        if self.state.active_tab == TAB_PORTS:
            header_text = f"{'PORT':<12} {'OWNER':<14} {'PID':<8} {'STATUS':<12}"
            stdscr.addstr(header_y, 1, header_text[:left_width - 1], curses.A_BOLD)
        elif self.state.active_tab == TAB_CONTAINERS:
            header_text = f"{'NAME':<16} {'STATE':<10} {'IMAGE':<16} {'PORTS':<12}"
            stdscr.addstr(header_y, 1, header_text[:left_width - 1], curses.A_BOLD)
        elif self.state.active_tab == TAB_APPROVALS:
            header_text = f"{'ID':<10} {'ACTION':<20} {'RISK':<8} {'STATUS':<10}"
            stdscr.addstr(header_y, 1, header_text[:left_width - 1], curses.A_BOLD)
        elif self.state.active_tab == TAB_PROJECTS:
            header_text = f"{'PROJECT':<16} {'SERVICES':<12} {'PORTS':<10}"
            stdscr.addstr(header_y, 1, header_text[:left_width - 1], curses.A_BOLD)

        # Draw Vertical Split Border
        for y in range(3, 3 + content_height + 1):
            if y < max_y - 2:
                stdscr.addstr(y, left_width, "│")

        # Draw Left Items
        start_row = 4
        if not items:
            stdscr.addstr(start_row, 2, "(No items to display)", curses.color_pair(7))
        else:
            visible_count = content_height - 1
            scroll_offset = max(0, selected_idx - visible_count // 2)
            end_idx = min(len(items), scroll_offset + visible_count)

            for i in range(scroll_offset, end_idx):
                row_y = start_row + (i - scroll_offset)
                if row_y >= max_y - 3:
                    break

                item = items[i]
                is_selected = i == selected_idx

                if self.state.active_tab == TAB_PORTS:
                    has_conf = any(
                        c.get("port") == item.port and c.get("protocol") == item.protocol
                        for c in self.data.conflicts
                    )
                    p_proto, owner, pid, _, status = format_port_row(item, has_conf)
                    line_str = f"{p_proto:<12} {owner[:13]:<14} {pid:<8} {status:<12}"[:left_width - 2]
                elif self.state.active_tab == TAB_CONTAINERS:
                    name, state, img, _, ports = format_container_row(item)
                    line_str = f"{name[:15]:<16} {state[:9]:<10} {img[:15]:<16} {ports[:11]:<12}"[:left_width - 2]
                elif self.state.active_tab == TAB_APPROVALS:
                    aid, act, risk, st, _ = format_approval_row(item)
                    line_str = f"{aid:<10} {act[:19]:<20} {risk:<8} {st:<10}"[:left_width - 2]
                elif self.state.active_tab == TAB_PROJECTS:
                    pname, svcs, ports, _ = format_project_row(item)
                    line_str = f"{pname[:15]:<16} {svcs:<12} {ports:<10}"[:left_width - 2]
                else:
                    line_str = str(item)[:left_width - 2]

                if is_selected:
                    stdscr.attron(curses.color_pair(5) | curses.A_BOLD)
                    stdscr.addstr(row_y, 1, f"❯ {line_str}"[:left_width - 1].ljust(left_width - 1))
                    stdscr.attroff(curses.color_pair(5) | curses.A_BOLD)
                else:
                    stdscr.addstr(row_y, 1, f"  {line_str}"[:left_width - 1])

        # Draw Right Inspector Pane
        inspector_x = left_width + 2
        stdscr.addstr(3, inspector_x, "INSPECTOR / DETAILS", curses.A_BOLD | curses.color_pair(1))

        selected_item = items[selected_idx] if (items and 0 <= selected_idx < len(items)) else None
        details_text = get_item_details(self.data, self.state, selected_item)

        detail_lines = details_text.split("\n")
        for idx, d_line in enumerate(detail_lines[:content_height - 1]):
            row_y = start_row + idx
            if row_y >= max_y - 3:
                break
            stdscr.addstr(row_y, inspector_x, d_line[:right_width])

    def _draw_logs_view(self, stdscr, max_y: int, max_x: int) -> None:
        title = f"LOGS: {self.state.log_container_name or 'None'} (Scroll: j/k, Top/Bottom: g/G, Follow: f)"
        stdscr.addstr(3, 1, title[:max_x - 2], curses.A_BOLD | curses.color_pair(1))

        content_height = max_y - 7
        lines = self.state.log_lines
        offset = self.state.log_scroll_offset

        if not lines:
            stdscr.addstr(5, 2, "No logs available.", curses.color_pair(7))
            return

        visible_lines = lines[offset:offset + content_height]
        for i, line in enumerate(visible_lines):
            row_y = 4 + i
            if row_y >= max_y - 3:
                break
            line_no = f"{offset + i + 1:4d} │ "
            stdscr.addstr(row_y, 1, line_no, curses.color_pair(3))
            stdscr.addstr(row_y, 1 + len(line_no), line[:max_x - len(line_no) - 3])

    def _draw_footer(self, stdscr, max_y: int, max_x: int) -> None:
        # Divider line
        stdscr.addstr(max_y - 3, 0, "─" * (max_x - 1))

        # Status / Filter line
        if self.state.is_filtering:
            filter_prompt = f"🔍 Filter: {self.state.current_filter_query}_ (Enter to apply, Esc to cancel)"
            stdscr.attron(curses.color_pair(3) | curses.A_BOLD)
            stdscr.addstr(max_y - 2, 1, filter_prompt[:max_x - 2])
            stdscr.attroff(curses.color_pair(3) | curses.A_BOLD)
        else:
            status_color = curses.color_pair(4 if self.state.status_is_error else 2)
            stdscr.attron(status_color)
            stdscr.addstr(max_y - 2, 1, f"Status: {self.state.status_message}"[:max_x - 2])
            stdscr.attroff(status_color)

        # Keymap hint bar
        hints = "[1-5/Tab] Tabs [j/k] Move [Enter] Inspect [a] Approve [l] Logs [p] Prep [r] Refresh [/] Find [q] Quit"
        stdscr.addstr(max_y - 1, 1, hints[:max_x - 2], curses.A_DIM)

    def _draw_help_modal(self, stdscr, max_y: int, max_x: int) -> None:
        box_w = min(64, max_x - 4)
        box_h = min(18, max_y - 4)
        start_y = (max_y - box_h) // 2
        start_x = (max_x - box_w) // 2

        # Draw background and border
        for y in range(start_y, start_y + box_h):
            stdscr.addstr(y, start_x, " " * box_w, curses.color_pair(5))

        title = " Arbiter TUI Shortcuts & Keybindings "
        stdscr.addstr(start_y + 1, start_x + (box_w - len(title)) // 2, title, curses.A_BOLD | curses.color_pair(5))

        shortcuts = [
            ("j / k, ↓ / ↑", "Navigate items up and down"),
            ("1 - 5, Tab", "Switch between primary tabs"),
            ("Enter", "Inspect details / Drill down"),
            ("a", "Approve & execute selected action"),
            ("d / x", "Reject selected approval"),
            ("l", "Jump to container live logs"),
            ("p", "Prepare selected project with Agent"),
            ("r", "Force data refresh"),
            ("/", "Fuzzy search in current tab"),
            ("g / G", "Jump to top / bottom"),
            ("? / Esc", "Toggle / close this help modal"),
            ("q / Ctrl-C", "Quit Arbiter TUI"),
        ]

        for i, (key_label, desc) in enumerate(shortcuts):
            row_y = start_y + 3 + i
            if row_y >= start_y + box_h - 1:
                break
            stdscr.addstr(row_y, start_x + 2, f"{key_label:<14} : {desc}"[:box_w - 4], curses.color_pair(5))

    def _draw_confirm_modal(self, stdscr, max_y: int, max_x: int) -> None:
        box_w = min(56, max_x - 4)
        box_h = 7
        start_y = (max_y - box_h) // 2
        start_x = (max_x - box_w) // 2

        for y in range(start_y, start_y + box_h):
            stdscr.addstr(y, start_x, " " * box_w, curses.color_pair(6))

        action_name = self.state.confirm_action.get("action", "action")
        target_id = self.state.confirm_action.get("id", "")

        prompt_1 = f"Confirm Execution: {action_name}"
        prompt_2 = f"Target ID: {target_id[:20]}"
        prompt_3 = "Press [y] to execute, [n] to cancel"

        stdscr.addstr(start_y + 1, start_x + 2, prompt_1[:box_w - 4], curses.A_BOLD | curses.color_pair(6))
        stdscr.addstr(start_y + 2, start_x + 2, prompt_2[:box_w - 4], curses.color_pair(6))
        stdscr.addstr(start_y + 4, start_x + 2, prompt_3[:box_w - 4], curses.A_BOLD | curses.color_pair(6))

    def _handle_input(self, key: int) -> None:
        # If in filter mode, capture text input
        if self.state.is_filtering:
            if key in (10, 13):  # Enter
                self.state.is_filtering = False
            elif key == 27:  # Esc
                self.state.set_current_filter_query("")
                self.state.is_filtering = False
            elif key in (curses.KEY_BACKSPACE, 127, 8):
                q = self.state.current_filter_query
                if q:
                    self.state.set_current_filter_query(q[:-1])
            elif 32 <= key <= 126:
                self.state.set_current_filter_query(self.state.current_filter_query + chr(key))
            return

        # If confirmation modal is open
        if self.state.confirm_action:
            if key in (ord("y"), ord("Y")):
                act_type = self.state.confirm_action.get("type")
                target_id = self.state.confirm_action.get("id")
                self.state.confirm_action = None
                if act_type == "approval" and target_id:
                    self.execute_approval(target_id)
                elif act_type == "prepare" and target_id:
                    self.prepare_selected_project(target_id)
            elif key in (ord("n"), ord("N"), 27):
                self.state.confirm_action = None
                self.state.status_message = "Action cancelled"
            return

        # If help modal is open
        if self.state.show_help:
            if key in (ord("?"), ord("q"), 27, 10, 13):
                self.state.show_help = False
            return

        items = self.get_current_items()
        curr_idx = self.state.current_selected_index

        # Navigation
        if key in (ord("j"), curses.KEY_DOWN):
            if self.state.active_tab == TAB_LOGS:
                self.state.log_scroll_offset = min(
                    len(self.state.log_lines) - 1, self.state.log_scroll_offset + 1
                )
            else:
                self.state.set_current_selected_index(min(len(items) - 1, curr_idx + 1))
        elif key in (ord("k"), curses.KEY_UP):
            if self.state.active_tab == TAB_LOGS:
                self.state.log_scroll_offset = max(0, self.state.log_scroll_offset - 1)
            else:
                self.state.set_current_selected_index(max(0, curr_idx - 1))
        elif key in (ord("g"), curses.KEY_HOME):
            if self.state.active_tab == TAB_LOGS:
                self.state.log_scroll_offset = 0
            else:
                self.state.set_current_selected_index(0)
        elif key in (ord("G"), curses.KEY_END):
            if self.state.active_tab == TAB_LOGS:
                self.state.log_scroll_offset = max(0, len(self.state.log_lines) - 20)
            else:
                self.state.set_current_selected_index(max(0, len(items) - 1))

        # Tab switching
        elif key in (9, ord("l"), curses.KEY_RIGHT) and self.state.active_tab != TAB_LOGS:  # Tab / right
            self.state.active_tab = (self.state.active_tab + 1) % len(TAB_NAMES)
        elif key in (ord("h"), curses.KEY_LEFT) and self.state.active_tab != TAB_LOGS:  # Left
            self.state.active_tab = (self.state.active_tab - 1) % len(TAB_NAMES)
        elif key in (ord("1"), ord("2"), ord("3"), ord("4"), ord("5")):
            self.state.active_tab = int(chr(key)) - 1

        # Quick Actions
        elif key == ord("/"):
            self.state.is_filtering = True
        elif key == ord("?"):
            self.state.show_help = True
        elif key in (ord("r"), ord("R")):
            self.state.status_message = "Reloading data..."
            self.load_data()
            self.state.status_message = "Data refreshed"
        elif key in (ord("q"), ord("Q")):
            self.running = False

        # Context-dependent Actions
        elif key in (10, 13):  # Enter
            if items and 0 <= curr_idx < len(items):
                item = items[curr_idx]
                if self.state.active_tab == TAB_CONTAINERS:
                    self.fetch_container_logs(item.id, item.name)
                elif self.state.active_tab == TAB_APPROVALS and item.status == "pending":
                    self.state.confirm_action = {
                        "type": "approval",
                        "action": item.action,
                        "id": item.id,
                    }

        elif key == ord("a"):  # Approve action
            if self.state.active_tab == TAB_APPROVALS and items and 0 <= curr_idx < len(items):
                item = items[curr_idx]
                if item.status == "pending":
                    self.state.confirm_action = {
                        "type": "approval",
                        "action": item.action,
                        "id": item.id,
                    }
                else:
                    self.state.status_message = f"Approval is already {item.status}"
            else:
                # Find first pending approval
                pending = [a for a in self.data.approvals if a.status == "pending"]
                if pending:
                    self.state.confirm_action = {
                        "type": "approval",
                        "action": pending[0].action,
                        "id": pending[0].id,
                    }
                else:
                    self.state.status_message = "No pending approvals to execute."

        elif key == ord("l") and self.state.active_tab == TAB_CONTAINERS and items and 0 <= curr_idx < len(items):
            item = items[curr_idx]
            self.fetch_container_logs(item.id, item.name)

        elif key == ord("p") and self.state.active_tab == TAB_PROJECTS and items and 0 <= curr_idx < len(items):
            item = items[curr_idx]
            self.state.confirm_action = {
                "type": "prepare",
                "action": f"arbiter prepare {item.name}",
                "id": item.id,
            }


def run_tui(services: Services | None = None) -> None:
    """Launch the interactive Terminal UI."""
    svc = services or build_services(get_settings())

    if not sys.stdin.isatty() or not sys.stdout.isatty():
        # Non-interactive fallback: output quick status table
        from arbiter.cli.prompt import format_prompt_status, get_prompt_status

        status = get_prompt_status(svc)
        print(format_prompt_status(status, output_format="pill"))
        return

    app = ArbiterTUI(svc)
    with contextlib.suppress(KeyboardInterrupt):
        curses.wrapper(app.run)

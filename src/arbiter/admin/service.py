import os
import platform
import sys
import threading
import time
from collections import Counter
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.engine import make_url

from arbiter.agent.service import AgentService
from arbiter.agent.tools import AgentTools
from arbiter.persistence.tables import (
    ActionRow,
    AgentRequestRow,
    ApprovalRow,
    ManagedFileBackupRow,
    PortReservationRow,
    ProjectRow,
)
from arbiter.safety.policies import ACTION_RISKS, needs_approval


class AdminService:
    def __init__(self, services) -> None:
        self.services = services

    def overview(self) -> dict[str, Any]:
        telemetry = self.services.telemetry.snapshot()
        return {
            "generated_at": time.time(),
            "telemetry": telemetry,
            "database": self._database(),
            "events": self.services.events.stats(),
            "observer": self.services.observer.status() if self.services.observer else {"running": False},
            "harness": self._harness(),
            "process": self._process(),
            "documentation": {
                "openapi": "/openapi.json",
                "swagger": "/docs",
                "redoc": "/redoc",
                "sections": [
                    {"title": "Resource topology", "anchor": "topology", "endpoint": "GET /api/v1/topology"},
                    {
                        "title": "Smart filtering",
                        "anchor": "intelligence",
                        "endpoint": "POST /api/v1/intelligence/filter",
                    },
                    {"title": "Safety pipeline", "anchor": "safety", "endpoint": "GET /api/v1/approvals"},
                    {"title": "Live events", "anchor": "events", "endpoint": "GET /api/v1/events/stream"},
                ],
            },
        }

    def _database(self) -> dict[str, Any]:
        tables = {
            "projects": ProjectRow,
            "approvals": ApprovalRow,
            "port_reservations": PortReservationRow,
            "actions": ActionRow,
            "agent_requests": AgentRequestRow,
            "managed_file_backups": ManagedFileBackupRow,
        }
        with self.services.database.sessions() as session:
            counts = {
                name: int(session.scalar(select(func.count()).select_from(table)) or 0)
                for name, table in tables.items()
            }
            action_statuses = Counter(
                str(status) for status in session.scalars(select(ActionRow.status)).all()
            )
            approval_statuses = Counter(
                str(status) for status in session.scalars(select(ApprovalRow.status)).all()
            )
        url = make_url(self.services.settings.database_url)
        result: dict[str, Any] = {
            "backend": url.get_backend_name(),
            "counts": counts,
            "total_rows": sum(counts.values()),
            "action_statuses": dict(action_statuses),
            "approval_statuses": dict(approval_statuses),
        }
        if url.get_backend_name() == "sqlite" and url.database:
            path = Path(url.database).expanduser()
            if not path.is_absolute():
                path = (Path.cwd() / path).resolve(strict=False)
            result.update({"path": str(path), "size_bytes": path.stat().st_size if path.exists() else 0})
        return result

    def _harness(self) -> dict[str, Any]:
        settings = self.services.settings
        tools = AgentTools(AgentService(self.services)).definitions()
        policies = [
            {"action": action, "risk": risk.value, "approval_required": needs_approval(risk, settings)}
            for action, risk in sorted(ACTION_RISKS.items())
        ]
        return {
            "provider_configured": bool(settings.llm_api_key and settings.llm_model),
            "agent_model": settings.llm_model or None,
            "filter_model": settings.filter_llm_model or None,
            "structured_filtering": bool(settings.llm_api_key and settings.filter_llm_model),
            "max_agent_steps": settings.agent_max_steps,
            "project_roots": [str(path) for path in settings.project_roots],
            "project_scan_depth": settings.project_scan_depth,
            "auto_approve": {
                "read_only": settings.auto_approve_read_only,
                "low_risk": settings.auto_approve_low_risk,
                "medium_and_higher": False,
            },
            "tool_count": len(tools),
            "tools": [item["function"]["name"] for item in tools],
            "policies": policies,
        }

    @staticmethod
    def _process() -> dict[str, Any]:
        rss = 0
        try:
            resident_pages = int(Path("/proc/self/statm").read_text().split()[1])
            rss = resident_pages * int(os.sysconf("SC_PAGE_SIZE"))
        except (OSError, ValueError, IndexError):
            pass
        try:
            load_average = list(os.getloadavg())
        except OSError:
            load_average = []
        return {
            "pid": os.getpid(),
            "python": platform.python_version(),
            "platform": platform.platform(),
            "executable": Path(sys.executable).name,
            "threads": threading.active_count(),
            "rss_bytes": rss,
            "cpu_time_seconds": round(time.process_time(), 3),
            "load_average": load_average,
        }

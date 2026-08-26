from arbiter.config import Settings
from arbiter.models import Risk

ACTION_RISKS = {
    "container.start": Risk.LOW_RISK,
    "container.stop": Risk.MEDIUM_RISK,
    "container.restart": Risk.MEDIUM_RISK,
    "container.pause": Risk.MEDIUM_RISK,
    "container.unpause": Risk.MEDIUM_RISK,
    "container.remove": Risk.HIGH_RISK,
    "compose.start": Risk.MEDIUM_RISK,
    "compose.stop": Risk.MEDIUM_RISK,
    "compose.restart": Risk.MEDIUM_RISK,
    "compose.restart_service": Risk.MEDIUM_RISK,
    "compose.change_port": Risk.MEDIUM_RISK,
    "project.resolve_ports": Risk.MEDIUM_RISK,
    "make.run": Risk.HIGH_RISK,
    "image.remove": Risk.HIGH_RISK,
    "volume.remove": Risk.DESTRUCTIVE,
}


def needs_approval(risk: Risk, settings: Settings) -> bool:
    if risk is Risk.READ_ONLY:
        return not settings.auto_approve_read_only
    if risk is Risk.LOW_RISK:
        return not settings.auto_approve_low_risk
    return True

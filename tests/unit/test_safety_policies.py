from arbiter.config import Settings
from arbiter.models import Risk
from arbiter.safety.policies import ACTION_RISKS, needs_approval


def test_action_risk_mappings():
    assert ACTION_RISKS["container.start"] == Risk.LOW_RISK
    assert ACTION_RISKS["container.stop"] == Risk.MEDIUM_RISK
    assert ACTION_RISKS["container.remove"] == Risk.HIGH_RISK
    assert ACTION_RISKS["volume.remove"] == Risk.DESTRUCTIVE
    assert ACTION_RISKS["project.resolve_ports"] == Risk.MEDIUM_RISK


def test_needs_approval_policy():
    settings = Settings(
        database_url="sqlite:///:memory:",
        auto_approve_read_only=True,
        auto_approve_low_risk=False,
        _env_file=None,
    )

    # Read-only auto-approved
    assert needs_approval(Risk.READ_ONLY, settings) is False

    # Low risk requires approval when auto_approve_low_risk=False
    assert needs_approval(Risk.LOW_RISK, settings) is True

    # Medium, high, destructive always require approval
    assert needs_approval(Risk.MEDIUM_RISK, settings) is True
    assert needs_approval(Risk.HIGH_RISK, settings) is True
    assert needs_approval(Risk.DESTRUCTIVE, settings) is True

    # When auto_approve_low_risk is enabled
    settings_auto_low = Settings(
        database_url="sqlite:///:memory:",
        auto_approve_read_only=True,
        auto_approve_low_risk=True,
        _env_file=None,
    )
    assert needs_approval(Risk.LOW_RISK, settings_auto_low) is False

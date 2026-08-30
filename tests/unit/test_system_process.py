from arbiter.system.models import ProcessInfo
from arbiter.system.processes import DEVELOPMENT_SIGNATURES


def test_development_signatures_classification():
    # Verify signatures map correctly
    sig_map = {kind: names for names, kind, _ in DEVELOPMENT_SIGNATURES}
    assert "uvicorn" in sig_map["development_server"]
    assert "postgres" in sig_map["database_or_search"]
    assert "node" in sig_map["javascript_runtime"]
    assert "python" in sig_map["python_runtime"]
    assert "docker" in sig_map["container_runtime"]


def test_process_info_model():
    p = ProcessInfo(
        pid=1234,
        ppid=1,
        process="uvicorn",
        command="uvicorn app:app --port 8000",
        cwd="/app",
        ports=[8000],
        kind="development_server",
        confidence=0.93,
    )
    assert p.pid == 1234
    assert p.process == "uvicorn"
    assert p.ports == [8000]
    assert p.kind == "development_server"

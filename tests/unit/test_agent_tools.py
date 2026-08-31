from arbiter.agent.service import AgentService
from arbiter.agent.tools import AgentTools
from arbiter.models import PortOwner


def test_agent_tools_definitions(service_factory):
    services = service_factory()
    agent = AgentService(services)
    tools = AgentTools(agent)

    definitions = tools.definitions()
    assert len(definitions) >= 10
    names = {d["function"]["name"] for d in definitions}
    assert "find_port_owner" in names
    assert "find_free_port" in names
    assert "list_projects" in names
    assert "containers_list" in names
    assert "topology_get" in names
    assert "stack_readiness_request_access" in names
    assert "readiness_authorizations_list" in names


def test_agent_tools_call_execution(service_factory):
    services = service_factory([PortOwner(port=5432, process="postgres", owner_type="process")])
    agent = AgentService(services)
    tools = AgentTools(agent)

    # Calling with dict
    owner = tools.call("find_port_owner", {"port": 5432})
    assert owner["process"] == "postgres"
    assert owner["port"] == 5432

    # Calling with JSON string
    owner_str = tools.call("find_port_owner", '{"port": 5432}')
    assert owner_str["process"] == "postgres"


def test_agent_langchain_tools_generation(service_factory):
    services = service_factory()
    agent = AgentService(services)
    tools = AgentTools(agent)

    lc_tools = tools.langchain_tools()
    assert len(lc_tools) >= 10
    lc_names = {t.name for t in lc_tools}
    assert "find_port_owner" in lc_names


def test_agent_tools_safe_runner_handles_invalid_args(service_factory):
    services = service_factory()
    agent = AgentService(services)
    tools = AgentTools(agent)

    runner = tools._safe_runner("find_port_owner")
    error_result = runner(bad_arg=123)
    assert error_result.get("error") == "malformed_tool_call"

"""Every registered ACP agent must actually run when you prompt it.

Two hand-maintained allow-lists and one hardcoded command chain decided which
agents worked. The registry grew to 46 agents while the lists stayed at 19 and
23, so a connected, working agent answered "integration coming soon", or was
silently run as the *opencode* CLI, or was rejected as "unsupported". GitHub
Copilot, Cursor, Droid, Kiro, GLM, Qwen, and Cline all shipped that way.
"""

from __future__ import annotations

import asyncio

import pytest

from superqode.agents.acp_registry import get_registry_agent_by_short_name
from superqode.agents.discovery import read_agents
from superqode.app.mixins.agent_run import AgentRunMixin, _acp_agent_short_names
from superqode.app_main import SuperQodeApp

# openclaw declares no run_command in the registry, so refusing it is correct.
_AGENTS_WITHOUT_A_LAUNCH_COMMAND = {"openclaw"}


def _registry_short_names() -> list[str]:
    agents = asyncio.run(read_agents(include_registry=False))
    return sorted(
        {
            str(meta.get("short_name", "")).strip().lower()
            for meta in agents.values()
            if meta.get("short_name") and str(meta.get("protocol", "")).strip().lower() == "acp"
        }
    )


class _Log:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    def add_info(self, value) -> None:
        self.messages.append(("info", str(value)))

    def add_error(self, value) -> None:
        self.messages.append(("error", str(value)))

    def text(self) -> str:
        return " ".join(message for _kind, message in self.messages)


@pytest.mark.parametrize("short_name", _registry_short_names())
def test_every_registered_agent_runs_instead_of_coming_soon(short_name, monkeypatch):
    """A prompt must reach a real ACP run, never the "coming soon" stub."""
    import superqode.app.mixins.agent_run as agent_run

    agents = asyncio.run(read_agents(include_registry=False))
    meta = next(m for m in agents.values() if str(m.get("short_name", "")).lower() == short_name)
    dispatched: dict[str, str] = {}

    class _Session:
        connected_agent = meta

    monkeypatch.setattr(agent_run, "get_session", lambda: _Session())

    class Driver(AgentRunMixin):
        # opencode, claude, and codex guard on a selected model before running.
        current_model = "auto"

        def _call_ui(self, func, *args, **kwargs):
            return func(*args, **kwargs)

        def _start_thinking(self, *_a, **_k):
            pass

        def _stop_thinking(self, *_a, **_k):
            pass

        def _run_agent_unified(self, *, agent_type, **_kwargs):
            dispatched["agent_type"] = agent_type

    log = _Log()
    send = getattr(AgentRunMixin._send_to_agent, "__wrapped__", AgentRunMixin._send_to_agent)
    send(Driver(), "hello", meta.get("name", short_name), log)

    assert "coming soon" not in log.text(), f"{short_name} is registered but not runnable"
    assert dispatched.get("agent_type") == short_name


def test_the_acp_short_name_cache_covers_the_whole_registry():
    """The routing set must track the registry, not a stale hardcoded list."""
    assert set(_registry_short_names()) <= set(_acp_agent_short_names())


@pytest.mark.parametrize("short_name", _registry_short_names())
def test_every_routed_agent_resolves_a_launch_command(short_name):
    """Routing an agent to ACP is useless if no command can be started.

    The command chain in ``_run_acp_jsonrpc_client`` only names the original
    agents; everything else depends on the registry providing ``run_command``.
    """
    if short_name in _AGENTS_WITHOUT_A_LAUNCH_COMMAND:
        pytest.skip(f"{short_name} declares no run_command in the registry")

    metadata = get_registry_agent_by_short_name(short_name)
    command = str((metadata or {}).get("run_command") or "").strip()
    assert command, f"{short_name} routes to ACP but has no command to launch"


def test_copilot_specifically_dispatches_as_copilot(monkeypatch):
    """The regression that shipped in 0.2.61: Copilot said 'coming soon'."""
    import superqode.app.mixins.agent_run as agent_run

    agents = asyncio.run(read_agents(include_registry=False))
    meta = next(m for m in agents.values() if m.get("short_name") == "copilot")
    dispatched: dict[str, str] = {}

    class _Session:
        connected_agent = meta

    monkeypatch.setattr(agent_run, "get_session", lambda: _Session())

    class Driver(AgentRunMixin):
        # opencode, claude, and codex guard on a selected model before running.
        current_model = "auto"

        def _call_ui(self, func, *args, **kwargs):
            return func(*args, **kwargs)

        def _start_thinking(self, *_a, **_k):
            pass

        def _stop_thinking(self, *_a, **_k):
            pass

        def _run_agent_unified(self, *, agent_type, **_kwargs):
            dispatched["agent_type"] = agent_type

    log = _Log()
    send = getattr(SuperQodeApp._send_to_agent, "__wrapped__", SuperQodeApp._send_to_agent)
    send(Driver(), "hello", "GitHub Copilot", log)

    assert dispatched.get("agent_type") == "copilot"
    assert "coming soon" not in log.text()
    assert get_registry_agent_by_short_name("copilot")["run_command"] == ("copilot --acp --stdio")

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from superqode.harness.backends.base import HarnessBackendRequest
from superqode.harness.backends.tau import TauHarnessBackend
from superqode.harness.catalog import resolve_harness
from superqode.harness.protocol import HarnessCreateRequest, HarnessMessage
from superqode.harness.tau_adapter import TauHarnessProtocolAdapter
from superqode.harness.templates import tau_template


class FakeTauSession:
    def __init__(self, events):
        self.events = list(events)
        self.provider_name = "anthropic"
        self.model = "claude-test"
        self.session_id = "tau-native-session"
        self.steering: list[str] = []
        self.cancelled = False

    async def prompt(self, content):
        assert content == "inspect this repository"
        for event in self.events:
            yield event

    def queue_steering_message(self, content):
        self.steering.append(content)

    def cancel(self):
        self.cancelled = True


def _tau_events():
    usage = SimpleNamespace(
        input=12,
        output=7,
        cache_read=2,
        cache_write=1,
        reasoning=3,
        total_tokens=22,
        cost=SimpleNamespace(total=0.004),
    )
    assistant = SimpleNamespace(
        role="assistant",
        text="done",
        stop_reason="stop",
        provider="anthropic",
        model="claude-test",
        usage=usage,
        error_message=None,
    )
    result = SimpleNamespace(
        text="README excerpt",
        model_dump=lambda **_kwargs: {"text": "README excerpt"},
    )
    return [
        SimpleNamespace(
            type="message_update",
            assistant_message_event=SimpleNamespace(type="thinking_delta", delta="checking"),
        ),
        SimpleNamespace(
            type="message_update",
            assistant_message_event=SimpleNamespace(type="text_delta", delta="done"),
        ),
        SimpleNamespace(
            type="tool_execution_start",
            tool_call_id="call-1",
            tool_name="read",
            args={"path": "README.md"},
        ),
        SimpleNamespace(
            type="tool_execution_end",
            tool_call_id="call-1",
            tool_name="read",
            result=result,
            is_error=False,
        ),
        SimpleNamespace(type="message_end", message=assistant),
        SimpleNamespace(type="agent_settled"),
    ]


@pytest.mark.asyncio
async def test_tau_adapter_maps_events_and_controls_session(tmp_path: Path):
    fake = FakeTauSession(_tau_events())
    calls = []

    async def factory(request, session_path, tool_mode):
        calls.append((request, session_path, tool_mode))
        return fake

    adapter = TauHarnessProtocolAdapter(session_factory=factory)
    ref = await adapter.create(
        HarnessCreateRequest(
            harness_id="tau",
            provider="anthropic",
            model="claude-test",
            working_directory=tmp_path,
            session_id="session-1",
        )
    )
    events = [
        event
        async for event in adapter.send(ref, HarnessMessage("user", "inspect this repository"))
    ]

    assert calls[0][2] == "read-only"
    assert calls[0][1] == tmp_path / ".superqode/tau/sessions/session-1.jsonl"
    assert [event.type for event in events] == [
        "model.requested",
        "model.thinking",
        "message.delta",
        "tool.requested",
        "tool.completed",
        "message.created",
        "model.completed",
    ]
    assert events[-1].data["usage"]["total_tokens"] == 22

    await adapter.steer(ref, HarnessMessage("user", "focus on tests"))
    await adapter.cancel(ref)
    checkpoint = await adapter.checkpoint(ref)
    assert fake.steering == ["focus on tests"]
    assert fake.cancelled is True
    assert checkpoint.state["tool_mode"] == "read-only"


@pytest.mark.asyncio
async def test_tau_backend_translates_protocol_events_for_tui(tmp_path: Path):
    fake = FakeTauSession(_tau_events())

    async def factory(_request, _session_path, _tool_mode):
        return fake

    backend = TauHarnessBackend(adapter=TauHarnessProtocolAdapter(session_factory=factory))
    request = HarnessBackendRequest(
        spec=tau_template(),
        prompt="inspect this repository",
        provider="anthropic",
        model="claude-test",
        working_directory=tmp_path,
        session_id="session-2",
    )
    events = [event async for event in backend.stream(request)]

    assert [event.type for event in events] == [
        "model_request",
        "thinking",
        "model_delta",
        "tool_call",
        "tool_result",
        "message.created",
        "turn_complete",
    ]
    assert events[2].data["text"] == "done"
    assert events[4].data["success"] is True


def test_tau_template_is_read_only_until_policy_bridge_exists():
    spec = tau_template()

    assert spec.runtime.backend == "tau"
    assert spec.execution_policy.allow_read is True
    assert spec.execution_policy.allow_write is False
    assert spec.execution_policy.allow_shell is False
    assert spec.agents[0].tools == ("read",)


def test_tau_is_always_visible_in_harness_catalog(tmp_path: Path):
    entry = resolve_harness("tau", root=tmp_path)

    assert entry.id == "tau"
    assert entry.runtime == "tau"
    assert entry.recommended is True
    if not entry.available:
        # The hint is environment-aware: a source checkout gets
        # `uv pip install -e ".[tau]"`, other contexts get a `superqode[tau]`
        # spec. Assert on the extra itself so the test holds in every context.
        assert "[tau]" in entry.issue


@pytest.mark.asyncio
async def test_installed_tau_event_models_match_adapter_contract(tmp_path: Path):
    events_module = pytest.importorskip("tau_agent.events")
    messages_module = pytest.importorskip("tau_agent.messages")
    provider_events = pytest.importorskip("tau_agent.provider_events")
    tools_module = pytest.importorskip("tau_agent.tools")
    coding_events = pytest.importorskip("tau_coding.events")

    partial = messages_module.AssistantMessage(
        content="hello",
        provider="anthropic",
        model="claude-test",
    )
    final = messages_module.AssistantMessage(
        content="hello",
        provider="anthropic",
        model="claude-test",
        usage=messages_module.Usage(input=2, output=1, total_tokens=3),
    )
    native_events = [
        events_module.MessageUpdateEvent(
            message=partial,
            assistant_message_event=provider_events.TextDeltaEvent(
                content_index=0,
                delta="hello",
                partial=partial,
            ),
        ),
        events_module.ToolExecutionStartEvent(
            tool_call_id="tool-1",
            tool_name="read",
            args={"path": "README.md"},
        ),
        events_module.ToolExecutionEndEvent(
            tool_call_id="tool-1",
            tool_name="read",
            result=tools_module.AgentToolResult(content="ok"),
            is_error=False,
        ),
        events_module.MessageEndEvent(message=final),
        coding_events.AgentSettledEvent(),
    ]
    fake = FakeTauSession(native_events)

    async def factory(_request, _session_path, _tool_mode):
        return fake

    adapter = TauHarnessProtocolAdapter(session_factory=factory)
    ref = await adapter.create(
        HarnessCreateRequest(
            harness_id="tau",
            working_directory=tmp_path,
            session_id="real-events",
        )
    )
    mapped = [
        event.type
        async for event in adapter.send(
            ref,
            HarnessMessage("user", "inspect this repository"),
        )
    ]

    assert mapped == [
        "model.requested",
        "message.delta",
        "tool.requested",
        "tool.completed",
        "message.created",
        "model.completed",
    ]

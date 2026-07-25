"""HarnessSpec backend for the optional Hugging Face Tau adapter."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from typing import Any

from ...agent.loop import AgentResponse
from ..events import HarnessEvent
from ..protocol import HarnessMessage, HarnessSessionRef
from ..tau_adapter import TauHarnessProtocolAdapter
from .base import HarnessBackendCapabilities, HarnessBackendRequest, HarnessBackendResult


class TauHarnessBackend:
    """Expose Tau through the normal HarnessSpec/TUI execution route."""

    name = "tau"
    capabilities = HarnessBackendCapabilities(
        backend="tau",
        supports_coding=True,
        supports_no_tool=False,
        supports_streaming=True,
        supports_approvals=False,
        supports_sandbox=False,
        supports_shell=False,
        supports_mcp=False,
        supports_typed_output=False,
        supports_workflow_children=False,
        event_detail="rich",
        notes=(
            "The maintained TUI preset is read-only until Tau tools participate "
            "in SuperQode approval policy.",
        ),
    )

    def __init__(self, *, adapter: TauHarnessProtocolAdapter | None = None) -> None:
        self.adapter = adapter or TauHarnessProtocolAdapter()

    async def run(self, request: HarnessBackendRequest) -> HarnessBackendResult:
        events: list[HarnessEvent] = []
        text: list[str] = []
        final_text = ""
        tool_calls = 0
        usage: dict[str, Any] = {}
        stopped_reason = "complete"
        error: str | None = None

        async for event in self._adapter_events(request):
            events.append(_backend_event(event))
            if event.type == "message.delta":
                text.append(str(event.data.get("text") or ""))
            elif event.type == "message.created" and event.data.get("role") == "assistant":
                final_text = str(event.data.get("content") or "")
            elif event.type == "tool.requested":
                tool_calls += 1
            elif event.type == "model.completed":
                raw_usage = event.data.get("usage")
                if isinstance(raw_usage, dict):
                    usage = dict(raw_usage)
            elif event.type == "run.failed":
                stopped_reason = "error"
                error = str(event.data.get("error") or "Tau run failed")

        response = AgentResponse(
            content="".join(text) or final_text,
            messages=[],
            tool_calls_made=tool_calls,
            iterations=max(1, int(usage.get("turns") or 1)),
            stopped_reason=stopped_reason,
            error=error,
            input_tokens=_optional_int(usage.get("input_tokens")),
            output_tokens=_optional_int(usage.get("output_tokens")),
            total_tokens=_optional_int(usage.get("total_tokens")),
            cost_usd=_optional_float(usage.get("cost_usd")),
            cost_currency="USD" if usage.get("cost_usd") is not None else None,
        )
        return HarnessBackendResult(
            response=response,
            backend=self.name,
            runtime=self.name,
            metadata={"events": events, "tau_tool_mode": _tool_mode_for_request(request)},
        )

    async def stream(self, request: HarnessBackendRequest) -> AsyncIterator[HarnessEvent]:
        async for event in self._adapter_events(request):
            yield _backend_event(event)

    async def _adapter_events(
        self,
        request: HarnessBackendRequest,
    ) -> AsyncIterator[HarnessEvent]:
        ref = _session_ref(request)
        ref = await self.adapter.resume(ref)
        async for event in self.adapter.send(ref, HarnessMessage("user", request.prompt)):
            yield event
            if event.type == "run.failed":
                raise RuntimeError(str(event.data.get("error") or "Tau run failed"))


def _session_ref(request: HarnessBackendRequest) -> HarnessSessionRef:
    session_id = request.session_id or "tau-session"
    safe_session_id = re.sub(r"[^A-Za-z0-9_.-]+", "-", session_id).strip(".-")
    safe_session_id = safe_session_id or "session"
    session_path = (
        request.working_directory
        / ".superqode"
        / "tau"
        / "sessions"
        / f"{safe_session_id}.jsonl"
    )
    return HarnessSessionRef(
        session_id=session_id,
        harness_id="tau",
        external_session_id=session_id,
        metadata={
            **dict(request.metadata),
            "provider": request.provider,
            "model": request.model,
            "working_directory": str(request.working_directory),
            "session_path": str(session_path),
            "tau_tool_mode": _tool_mode_for_request(request),
        },
    )


def _tool_mode_for_request(request: HarnessBackendRequest) -> str:
    del request
    return "read-only"


def _backend_event(event: HarnessEvent) -> HarnessEvent:
    """Translate canonical protocol events to the runtime event vocabulary."""
    event_type = event.type
    data = dict(event.data)
    if event_type == "message.delta":
        event_type = "model_delta"
    elif event_type == "model.thinking":
        event_type = "thinking"
    elif event_type == "tool.requested":
        event_type = "tool_call"
    elif event_type == "tool.completed":
        event_type = "tool_result"
    elif event_type == "adapter.tool.progress":
        event_type = "tool_delta"
    elif event_type == "model.requested":
        event_type = "model_request"
    elif event_type == "model.completed":
        event_type = "turn_complete"
    elif event_type == "run.failed":
        event_type = "error"
    return HarnessEvent(
        type=event_type,
        data=data,
        timestamp=event.timestamp,
        session_id=event.session_id,
        run_id=event.run_id,
        parent_event_id=event.parent_event_id,
    )


def _optional_int(value: Any) -> int | None:
    return int(value) if value is not None else None


def _optional_float(value: Any) -> float | None:
    return float(value) if value is not None else None

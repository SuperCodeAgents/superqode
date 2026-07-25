"""Optional Hugging Face Tau adapter for Harness Protocol v1.

Tau is intentionally imported only when a Tau session is created.  This keeps
the normal SuperQode import path independent from the optional ``tau-ai``
package and lets discovery report a useful installation hint.
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

from .events import HarnessEvent
from .protocol import (
    HarnessCapabilities,
    HarnessCheckpoint,
    HarnessCreateRequest,
    HarnessDescriptor,
    HarnessMessage,
    HarnessSessionRef,
)

TauSessionFactory = Callable[[HarnessCreateRequest, Path, str], Awaitable[Any]]


def tau_installation_status() -> tuple[bool, str]:
    """Return whether the supported Tau library is importable."""
    try:
        installed = importlib.util.find_spec("tau_coding") is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        installed = False
    if not installed:
        from superqode.providers.env_introspect import install_command

        return False, install_command("tau")
    try:
        version = importlib.metadata.version("tau-ai")
    except importlib.metadata.PackageNotFoundError:
        return False, "tau_coding is importable, but tau-ai package metadata is missing"
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", version)
    if match is None:
        return False, f"Tau version {version!r} cannot be validated; install tau-ai>=0.3.3,<0.4"
    parsed = tuple(int(part) for part in match.groups())
    if parsed < (0, 3, 3) or parsed >= (0, 4, 0):
        return False, f"Tau {version} is unsupported; install tau-ai>=0.3.3,<0.4"
    return True, ""


class TauHarnessProtocolAdapter:
    """Run Tau's ``CodingSession`` behind SuperQode's portable lifecycle."""

    def __init__(self, *, session_factory: TauSessionFactory | None = None) -> None:
        self.descriptor = HarnessDescriptor(
            id="tau",
            name="Hugging Face Tau",
            description=(
                "Tau's event-first Python coding-agent harness, normalized through "
                "SuperQode Harness Protocol"
            ),
            adapter_version="0.1",
            capabilities=HarnessCapabilities(
                streaming=True,
                resume=True,
                steer=True,
                cancel=True,
                checkpoint=True,
                approvals=False,
                tools=True,
                usage=True,
            ),
            metadata={
                "package": "tau-ai",
                "supported_versions": ">=0.3.3,<0.4",
                "default_tool_mode": "read-only",
            },
        )
        self._session_factory = session_factory or _create_tau_session
        self._sessions: dict[str, Any] = {}
        self._refs: dict[str, HarnessSessionRef] = {}

    async def create(self, request: HarnessCreateRequest) -> HarnessSessionRef:
        if request.harness_id != self.descriptor.id:
            raise ValueError(f"Tau adapter cannot create harness {request.harness_id!r}")
        session_id = request.session_id or f"tau-{uuid4().hex[:12]}"
        working_directory = request.working_directory.expanduser().resolve()
        tool_mode = _tool_mode(request.metadata)
        session_path = _session_path(working_directory, session_id)
        tau_session = await self._session_factory(request, session_path, tool_mode)
        ref = HarnessSessionRef(
            session_id=session_id,
            harness_id=self.descriptor.id,
            external_session_id=str(getattr(tau_session, "session_id", "") or session_id),
            metadata={
                **dict(request.metadata),
                "provider": str(
                    getattr(tau_session, "provider_name", None) or request.provider or ""
                ),
                "model": str(getattr(tau_session, "model", None) or request.model or ""),
                "working_directory": str(working_directory),
                "session_path": str(session_path),
                "tool_mode": tool_mode,
            },
        )
        self._sessions[session_id] = tau_session
        self._refs[session_id] = ref
        return ref

    async def resume(self, session: HarnessSessionRef) -> HarnessSessionRef:
        if session.harness_id != self.descriptor.id:
            raise ValueError(f"Tau adapter cannot resume harness {session.harness_id!r}")
        if session.session_id in self._sessions:
            return self._refs.get(session.session_id, session)
        metadata = dict(session.metadata)
        working_directory = (
            Path(str(metadata.get("working_directory") or Path.cwd())).expanduser().resolve()
        )
        request = HarnessCreateRequest(
            harness_id=self.descriptor.id,
            provider=str(metadata.get("provider") or ""),
            model=str(metadata.get("model") or ""),
            working_directory=working_directory,
            session_id=session.session_id,
            metadata=metadata,
        )
        session_path = _session_path(working_directory, session.session_id)
        tool_mode = _tool_mode(metadata)
        tau_session = await self._session_factory(request, session_path, tool_mode)
        resumed = HarnessSessionRef(
            session_id=session.session_id,
            harness_id=self.descriptor.id,
            external_session_id=str(
                getattr(tau_session, "session_id", "") or session.external_session_id or ""
            )
            or None,
            metadata={
                **metadata,
                "provider": str(
                    getattr(tau_session, "provider_name", None) or request.provider or ""
                ),
                "model": str(getattr(tau_session, "model", None) or request.model or ""),
                "working_directory": str(working_directory),
                "session_path": str(session_path),
                "tool_mode": tool_mode,
            },
        )
        self._sessions[session.session_id] = tau_session
        self._refs[session.session_id] = resumed
        return resumed

    async def send(
        self,
        session: HarnessSessionRef,
        message: HarnessMessage,
    ) -> AsyncIterator[HarnessEvent]:
        tau_session = await self._require_session(session)
        provider = str(getattr(tau_session, "provider_name", "") or "")
        model = str(getattr(tau_session, "model", "") or "")
        yield HarnessEvent(
            type="model.requested",
            data={"provider": provider, "model": model, "runtime": "tau"},
        )

        usage = _UsageTotals()
        async for tau_event in tau_session.prompt(message.content):
            for event in _map_tau_event(tau_event, usage):
                yield event

    async def steer(self, session: HarnessSessionRef, message: HarnessMessage) -> None:
        tau_session = await self._require_session(session)
        tau_session.queue_steering_message(message.content)

    async def cancel(self, session: HarnessSessionRef) -> None:
        tau_session = await self._require_session(session)
        tau_session.cancel()

    async def checkpoint(self, session: HarnessSessionRef) -> HarnessCheckpoint:
        ref = self._refs.get(session.session_id, session)
        session_path = str(ref.metadata.get("session_path") or "")
        return HarnessCheckpoint(
            session_id=session.session_id,
            harness_id=self.descriptor.id,
            external_checkpoint_id=session_path or None,
            state={
                "session_path": session_path,
                "provider": str(ref.metadata.get("provider") or ""),
                "model": str(ref.metadata.get("model") or ""),
                "tool_mode": str(ref.metadata.get("tool_mode") or "read-only"),
            },
        )

    async def _require_session(self, session: HarnessSessionRef) -> Any:
        active = self._sessions.get(session.session_id)
        if active is not None:
            return active
        await self.resume(session)
        return self._sessions[session.session_id]


class _UsageTotals:
    def __init__(self) -> None:
        self.input = 0
        self.output = 0
        self.cache_read = 0
        self.cache_write = 0
        self.reasoning = 0
        self.total_tokens = 0
        self.cost_usd = 0.0
        self.turns = 0

    def add(self, message: Any) -> None:
        usage = getattr(message, "usage", None)
        if usage is None:
            return
        self.input += int(getattr(usage, "input", 0) or 0)
        self.output += int(getattr(usage, "output", 0) or 0)
        self.cache_read += int(getattr(usage, "cache_read", 0) or 0)
        self.cache_write += int(getattr(usage, "cache_write", 0) or 0)
        self.reasoning += int(getattr(usage, "reasoning", 0) or 0)
        self.total_tokens += int(getattr(usage, "total_tokens", 0) or 0)
        cost = getattr(usage, "cost", None)
        self.cost_usd += float(getattr(cost, "total", 0.0) or 0.0)
        self.turns += 1

    def to_dict(self) -> dict[str, int | float]:
        return {
            "input_tokens": self.input,
            "output_tokens": self.output,
            "cache_read_tokens": self.cache_read,
            "cache_write_tokens": self.cache_write,
            "reasoning_tokens": self.reasoning,
            "total_tokens": self.total_tokens,
            "cost_usd": self.cost_usd,
            "turns": self.turns,
        }


def _map_tau_event(event: Any, usage: _UsageTotals) -> tuple[HarnessEvent, ...]:
    event_type = str(getattr(event, "type", "") or "")
    if event_type == "message_update":
        nested = getattr(event, "assistant_message_event", None)
        nested_type = str(getattr(nested, "type", "") or "")
        if nested_type == "text_delta":
            return (HarnessEvent(type="message.delta", data={"text": str(nested.delta)}),)
        if nested_type == "thinking_delta":
            return (HarnessEvent(type="model.thinking", data={"text": str(nested.delta)}),)
        return ()
    if event_type == "tool_execution_start":
        return (
            HarnessEvent(
                type="tool.requested",
                data={
                    "tool_call_id": str(getattr(event, "tool_call_id", "") or ""),
                    "tool_name": str(getattr(event, "tool_name", "") or "tool"),
                    "args": dict(getattr(event, "args", {}) or {}),
                },
            ),
        )
    if event_type == "tool_execution_update":
        result = getattr(event, "partial_result", None)
        return (
            HarnessEvent(
                type="adapter.tool.progress",
                data={
                    "tool_call_id": str(getattr(event, "tool_call_id", "") or ""),
                    "tool_name": str(getattr(event, "tool_name", "") or "tool"),
                    "text": str(getattr(result, "text", "") or ""),
                    "result": _wire_dict(result),
                },
            ),
        )
    if event_type == "tool_execution_end":
        result = getattr(event, "result", None)
        is_error = bool(getattr(event, "is_error", False))
        return (
            HarnessEvent(
                type="tool.completed",
                data={
                    "tool_call_id": str(getattr(event, "tool_call_id", "") or ""),
                    "tool_name": str(getattr(event, "tool_name", "") or "tool"),
                    "success": not is_error,
                    "output": str(getattr(result, "text", "") or ""),
                    "error": str(getattr(result, "text", "") or "") if is_error else None,
                    "result": _wire_dict(result),
                },
            ),
        )
    if event_type == "message_end":
        message = getattr(event, "message", None)
        if str(getattr(message, "role", "") or "") != "assistant":
            return ()
        usage.add(message)
        stop_reason = str(getattr(message, "stop_reason", "") or "")
        text = str(getattr(message, "text", "") or "")
        if stop_reason == "error":
            error = str(getattr(message, "error_message", "") or "Tau provider error")
            return (
                HarnessEvent(
                    type="model.completed",
                    data={
                        "provider": getattr(message, "provider", ""),
                        "model": getattr(message, "model", ""),
                        "usage": usage.to_dict(),
                        "stop_reason": stop_reason,
                    },
                ),
                HarnessEvent(
                    type="run.failed",
                    data={"error": error, "error_type": "TauProviderError"},
                ),
            )
        if not text or stop_reason == "toolUse":
            return ()
        return (
            HarnessEvent(
                type="message.created",
                data={
                    "role": "assistant",
                    "content": text,
                    "metadata": {
                        "provider": str(getattr(message, "provider", "") or ""),
                        "model": str(getattr(message, "model", "") or ""),
                        "stop_reason": stop_reason,
                        "usage": _wire_dict(getattr(message, "usage", None)),
                    },
                },
            ),
        )
    if event_type == "agent_settled":
        return (
            HarnessEvent(
                type="model.completed",
                data={"runtime": "tau", "usage": usage.to_dict()},
            ),
        )
    if event_type in {
        "queue_update",
        "compaction_start",
        "compaction_end",
        "auto_retry_start",
        "auto_retry_end",
    }:
        return (
            HarnessEvent(
                type=f"adapter.tau.{event_type}",
                data=_wire_dict(event),
            ),
        )
    return ()


async def _create_tau_session(
    request: HarnessCreateRequest,
    session_path: Path,
    _tool_mode: str,
) -> Any:
    available, issue = tau_installation_status()
    if not available:
        raise RuntimeError(issue)

    from tau_ai import FakeProvider
    from tau_coding import (
        CodingSession,
        CodingSessionConfig,
        create_read_tool,
        jsonl_session_storage,
        load_provider_settings,
        resolve_provider_selection,
    )

    settings = load_provider_settings()
    selection = resolve_provider_selection(
        settings,
        provider_name=request.provider or None,
        model=request.model or None,
    )
    tools = [create_read_tool(cwd=request.working_directory)]
    config = CodingSessionConfig(
        provider=FakeProvider([]),
        model=selection.model,
        storage=jsonl_session_storage(session_path),
        cwd=request.working_directory,
        tools=tools,
        session_id=request.session_id,
        provider_name=selection.provider.name,
        provider_settings=settings,
        runtime_provider_config=selection.provider,
        skills_enabled=True,
        extensions_enabled=False,
        project_extensions_enabled=False,
    )
    return await CodingSession.load(config)


def _tool_mode(metadata: dict[str, Any]) -> str:
    del metadata
    return "read-only"


def _session_path(working_directory: Path, session_id: str) -> Path:
    safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "-", session_id).strip(".-") or "session"
    return working_directory / ".superqode" / "tau" / "sessions" / f"{safe_id}.jsonl"


def _wire_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    dumper = getattr(value, "model_dump", None)
    if callable(dumper):
        return dict(dumper(mode="json", by_alias=False))
    if isinstance(value, dict):
        return dict(value)
    return {"value": str(value)}

"""Drive a vendor's own CLI on the user's subscription, without ACP.

Subscriptions must spend the plan the user already pays for. Every vendor CLI
here authenticates through its own login (``grok login``, ``copilot login``,
``cursor-agent login`` …) and exposes a non-interactive mode with structured
output, so SuperQode can render the turn in its own TUI while the vendor keeps
owning the agent loop.

Two things are deliberate:

* **Billing.** The child process starts from :func:`subscription_child_env`, so
  an API key left in the shell cannot silently move the session onto metered
  billing. The user's own environment is never modified: only the dict handed
  to this one subprocess omits those variables.
* **Permissions.** Vendor headless modes cannot prompt, so they require
  pre-authorisation. That is stated to the user on the first turn rather than
  being applied quietly.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Callable

from superqode.harness.events import HarnessEvent
from superqode.runtime.errors import RuntimeNotInstalledError

_DEFAULT_TURN_TIMEOUT = 900.0


def _turn_timeout() -> float:
    try:
        value = float(os.environ.get("SUPERQODE_VENDOR_CLI_TIMEOUT", "") or _DEFAULT_TURN_TIMEOUT)
    except ValueError:
        return _DEFAULT_TURN_TIMEOUT
    return value if value > 0 else _DEFAULT_TURN_TIMEOUT


# --- stream parsers -----------------------------------------------------------
#
# Each parser turns one decoded JSON object into zero or more HarnessEvents.
# They are pure so the wire formats can be tested from recorded fixtures
# without launching a vendor CLI.


def _text_event(text: str) -> list[HarnessEvent]:
    return [HarnessEvent(type="model_delta", data={"text": text})] if text else []


def parse_copilot_event(obj: dict) -> list[HarnessEvent]:
    """GitHub Copilot CLI ``--output-format json`` (JSONL)."""
    kind = str(obj.get("type") or "")
    data = obj.get("data") or {}
    if kind == "assistant.message_delta":
        return _text_event(str(data.get("deltaContent") or ""))
    if kind == "session.auto_mode_resolved":
        model = str(data.get("chosenModel") or "")
        # Copilot Free advertises no catalog, so this is the only place the
        # actually-used model is reported.
        return [HarnessEvent(type="model_request", data={"model": model})] if model else []
    if kind == "session.usage_checkpoint":
        return [HarnessEvent(type="turn_usage", data=dict(data))]
    if kind == "assistant.turn_end":
        return [HarnessEvent(type="turn_complete", data={"status": "completed"})]
    return []


def parse_grok_event(obj: dict) -> list[HarnessEvent]:
    """Grok CLI ``--output-format streaming-json``."""
    kind = str(obj.get("type") or "")
    if kind == "text":
        return _text_event(str(obj.get("data") or ""))
    if kind == "thought":
        return [HarnessEvent(type="thinking", data={"text": str(obj.get("data") or "")})]
    if kind == "end":
        return [
            HarnessEvent(
                type="turn_complete",
                data={
                    "status": "completed",
                    "stop_reason": obj.get("stopReason"),
                    "session_id": obj.get("sessionId"),
                    "usage": obj.get("usage") or {},
                },
            )
        ]
    return []


def parse_generic_event(obj: dict) -> list[HarnessEvent]:
    """Best-effort reader for Claude-Code-style ``stream-json`` and friends.

    Vendors that were not individually verified land here. It reads the shapes
    those formats share and stays silent on anything it does not recognise, so
    an unknown field can never be rendered as if it were assistant output.
    """
    kind = str(obj.get("type") or "")

    # {"type": "assistant", "message": {"content": [{"type": "text", "text": …}]}}
    message = obj.get("message")
    if isinstance(message, dict):
        chunks = []
        content = message.get("content")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    chunks.append(str(block.get("text") or ""))
        elif isinstance(content, str):
            chunks.append(content)
        return _text_event("".join(chunks))

    if kind in {"result", "end", "turn_end", "done"}:
        return [HarnessEvent(type="turn_complete", data={"status": "completed"})]

    for key in ("delta", "text", "content"):
        value = obj.get(key)
        if isinstance(value, str) and value:
            return _text_event(value)
    return []


PARSERS: dict[str, Callable[[dict], list[HarnessEvent]]] = {
    "copilot": parse_copilot_event,
    "grok": parse_grok_event,
    "generic": parse_generic_event,
}


# --- vendor descriptors -------------------------------------------------------


@dataclass(frozen=True)
class VendorCLISpec:
    """How to drive one vendor CLI non-interactively."""

    name: str  # runtime name, e.g. "grok-cli"
    vendor: str  # subscription_env vendor key
    label: str
    binary: str
    install_hint: str
    subcommand: tuple[str, ...] = ()
    #: Flag carrying the prompt; None means the prompt is positional.
    prompt_flag: str | None = "-p"
    output_format: tuple[str, ...] = ()
    model_flag: str | None = "--model"
    session_flag: str | None = None
    #: SuperQode approval mode -> the vendor's own permission flags. Headless
    #: modes cannot prompt per tool, so the closest equivalent in the vendor's
    #: own vocabulary is used rather than inventing one. A vendor that offers
    #: no gradation maps every mode to the same flags, and says so.
    permission_flags: dict[str, tuple[str, ...]] = field(default_factory=dict)
    parser: str = "generic"
    #: True when the vendor refuses to run headlessly without pre-authorisation.
    requires_pre_authorisation: bool = False

    def flags_for_approval(self, approval_mode: str | None) -> tuple[str, ...]:
        """Vendor permission flags for a SuperQode approval mode."""
        if not self.permission_flags:
            return ()
        mode = (approval_mode or "auto").strip().lower()
        if mode in self.permission_flags:
            return self.permission_flags[mode]
        return self.permission_flags.get("auto", ())

    @property
    def has_gradated_permissions(self) -> bool:
        """True when approval mode actually changes what the vendor allows."""
        return len({tuple(v) for v in self.permission_flags.values()}) > 1


VENDOR_CLI_SPECS: dict[str, VendorCLISpec] = {
    "grok": VendorCLISpec(
        name="grok-cli",
        vendor="grok",
        label="Grok",
        binary="grok",
        install_hint="install the Grok CLI, then run `grok login`",
        prompt_flag="-p",
        output_format=("--output-format", "streaming-json"),
        model_flag="--model",
        session_flag="--resume",
        permission_flags={
            "auto": ("--permission-mode", "bypassPermissions"),
            # Headless cannot prompt, so "ask" maps to the most conservative
            # mode that still makes progress: edits are auto-approved, arbitrary
            # execution is not silently bypassed.
            "ask": ("--permission-mode", "acceptEdits"),
            "deny": ("--permission-mode", "plan"),
        },
        parser="grok",
    ),
    "copilot": VendorCLISpec(
        name="copilot-cli",
        vendor="copilot",
        label="GitHub Copilot",
        binary="copilot",
        install_hint="run `npm install -g @github/copilot`, then `copilot login`",
        prompt_flag="-p",
        output_format=("--output-format", "json"),
        model_flag="--model",
        session_flag="--session-id",
        # Copilot's own help states --allow-all-tools is required for
        # non-interactive mode; there is no per-tool prompt to honour.
        permission_flags={
            "auto": ("--allow-all-tools",),
            "ask": ("--allow-all-tools",),
            "deny": ("--allow-all-tools",),
        },
        parser="copilot",
        requires_pre_authorisation=True,
    ),
    "cursor": VendorCLISpec(
        name="cursor-cli",
        vendor="cursor",
        label="Cursor",
        binary="cursor-agent",
        install_hint="install Cursor Agent, then sign in with `cursor-agent login`",
        prompt_flag="-p",
        output_format=("--output-format", "stream-json"),
        model_flag="--model",
        session_flag="--resume",
        permission_flags={
            "auto": ("--force",),
            "ask": ("--force",),
            "deny": ("--force",),
        },
        parser="generic",
        requires_pre_authorisation=True,
    ),
    "droid": VendorCLISpec(
        name="droid-cli",
        vendor="droid",
        label="Factory Droid",
        binary="droid",
        install_hint="install Factory Droid, then sign in with `droid`",
        subcommand=("exec",),
        prompt_flag=None,  # positional
        output_format=("--output-format", "json"),
        model_flag="--model",
        session_flag="--session-id",
        permission_flags={
            "auto": ("--auto", "high"),
            "ask": ("--auto", "low"),
            # Omitting --auto leaves Droid in its default read-only mode.
            "deny": (),
        },
        parser="generic",
    ),
    "devin": VendorCLISpec(
        name="devin-cli-print",
        vendor="devin",
        label="Devin",
        binary="devin",
        install_hint="install the Devin CLI, then run `devin auth login`",
        prompt_flag="-p",
        model_flag="--model",
        session_flag="--resume",
        permission_flags={
            "auto": ("--permission-mode", "dangerous"),
            "ask": ("--permission-mode", "accept-edits"),
            # Devin's most conservative mode still auto-approves read-only
            # tools; there is no full-deny in non-interactive mode.
            "deny": ("--permission-mode", "auto"),
        },
        parser="generic",
    ),
    "amp": VendorCLISpec(
        name="amp-cli",
        vendor="amp",
        label="Amp",
        binary="amp",
        install_hint="install the Amp CLI, then run `amp login`",
        prompt_flag="-x",
        output_format=("--stream-json",),
        model_flag=None,
        parser="generic",
    ),
}


def spec_for(vendor: str) -> VendorCLISpec | None:
    """Descriptor for a vendor id, profile id, or runtime name."""
    from superqode.providers.subscription_env import resolve_vendor

    key = resolve_vendor(vendor) or (vendor or "").strip().lower()
    if key in VENDOR_CLI_SPECS:
        return VENDOR_CLI_SPECS[key]
    for candidate in VENDOR_CLI_SPECS.values():
        if candidate.name == key:
            return candidate
    return None


# --- runtime ------------------------------------------------------------------


class VendorCLIRuntime:
    """Run a vendor CLI headlessly on the user's subscription."""

    def __init__(
        self,
        *,
        spec: VendorCLISpec,
        config: Any = None,
        approval_mode: str = "auto",
        **_unused: Any,
    ) -> None:
        """Build the runtime.

        Extra keyword arguments are accepted and ignored: the runtime registry
        passes shared plumbing (``gateway``, ``permission_manager``,
        ``approval_callback``) to every runtime, and a vendor CLI owns its own
        loop so it needs none of it. Every other runtime does the same.
        """
        if shutil.which(spec.binary) is None:
            raise RuntimeNotInstalledError(
                f"{spec.label} CLI was not found on PATH. To use it: {spec.install_hint}."
            )
        self.spec = spec
        self.config = config
        #: SuperQode approval mode ("auto" / "ask" / "deny"), translated into
        #: the vendor's own permission vocabulary for each turn.
        self.approval_mode = approval_mode
        self.stripped_api_keys: list[str] = []
        self._session_id: str | None = None
        self._process: Any = None
        self._cancelled = False
        self._announced_permissions = False

    @property
    def name(self) -> str:
        return self.spec.name

    @property
    def harness_owner(self) -> str:
        return self.spec.vendor

    @property
    def metadata(self) -> dict[str, Any]:
        return {
            "runtime": self.spec.name,
            "harness_owner": self.spec.vendor,
            "authentication": "vendor-subscription",
            "billing": "subscription",
            "structured_events": True,
            "model": getattr(self.config, "model", "") or "cli-default",
            "session_id": self._session_id,
        }

    def build_command(self, prompt: str) -> list[str]:
        """Argv for one non-interactive turn."""
        binary = shutil.which(self.spec.binary) or self.spec.binary
        argv: list[str] = [binary, *self.spec.subcommand]
        argv.extend(self.spec.output_format)

        model = str(getattr(self.config, "model", "") or "").strip()
        if model and model.lower() not in {"auto", "default"} and self.spec.model_flag:
            argv.extend([self.spec.model_flag, model])

        if self._session_id and self.spec.session_flag:
            argv.extend([self.spec.session_flag, self._session_id])

        argv.extend(self.spec.flags_for_approval(self.approval_mode))

        if self.spec.prompt_flag:
            argv.extend([self.spec.prompt_flag, prompt])
        else:
            argv.append(prompt)
        return argv

    def _permission_notice(self) -> HarnessEvent | None:
        """Explain how this turn is authorised, in the vendor's own terms.

        A headless CLI cannot prompt per tool, so the honest thing is to name
        the vendor mode actually in force rather than let the user assume their
        approval setting is being enforced call by call.
        """
        if self._announced_permissions or not self.spec.permission_flags:
            return None
        self._announced_permissions = True
        mode = (self.approval_mode or "auto").strip().lower()
        flags = " ".join(self.spec.flags_for_approval(mode)) or "the vendor default"

        if self.spec.has_gradated_permissions:
            detail = (
                f"{self.spec.label} runs non-interactively here, so SuperQode's "
                f"'{mode}' approval mode is applied as {self.spec.label}'s own "
                f"setting ({flags}) for the whole turn rather than prompting per "
                "tool call."
            )
        else:
            detail = (
                f"{self.spec.label} runs non-interactively here, which its CLI "
                f"only supports with tools pre-authorised ({flags}). Tool calls "
                "in this session are not individually approved, whatever the "
                "approval mode. Use the ACP route if you want per-tool prompts."
            )
        return HarnessEvent(type="thinking", data={"text": detail})

    async def run_harness_events(self, prompt: str) -> AsyncIterator[HarnessEvent]:
        """Stream one turn as normalized harness events."""
        from superqode.providers.subscription_env import subscription_child_env

        self._cancelled = False
        notice = self._permission_notice()
        if notice is not None:
            yield notice

        # Only the child's environment omits diverting API keys. os.environ is
        # left exactly as the user set it.
        child_env, self.stripped_api_keys = subscription_child_env(self.spec.vendor)
        argv = self.build_command(prompt)
        parser = PARSERS.get(self.spec.parser, parse_generic_event)

        try:
            self._process = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(getattr(self.config, "working_directory", os.getcwd())),
                env=child_env,
                limit=10 * 1024 * 1024,
            )
        except (OSError, ValueError) as exc:
            yield HarnessEvent(
                type="turn_complete",
                data={"status": "failed", "error": f"Could not start {self.spec.label}: {exc}"},
            )
            return

        saw_terminal_event = False
        try:
            async for event in self._stream(parser):
                if event.type == "turn_complete":
                    saw_terminal_event = True
                    self._remember_session(event)
                yield event
        except asyncio.TimeoutError:
            self._kill()
            yield HarnessEvent(
                type="turn_complete",
                data={
                    "status": "failed",
                    "error": (
                        f"{self.spec.label} exceeded {_turn_timeout():g}s "
                        "(set SUPERQODE_VENDOR_CLI_TIMEOUT to change the limit)"
                    ),
                },
            )
            return

        returncode = await self._process.wait()
        if self._cancelled:
            yield HarnessEvent(type="turn_complete", data={"status": "cancelled"})
            return
        if returncode != 0:
            stderr = b""
            if self._process.stderr is not None:
                try:
                    stderr = await self._process.stderr.read(4000)
                except Exception:  # noqa: BLE001 - diagnostics only
                    stderr = b""
            detail = stderr.decode(errors="replace").strip()
            yield HarnessEvent(
                type="turn_complete",
                data={
                    "status": "failed",
                    "error": detail or f"{self.spec.label} exited with {returncode}.",
                },
            )
            return
        if not saw_terminal_event:
            yield HarnessEvent(type="turn_complete", data={"status": "completed"})

    async def _stream(self, parser) -> AsyncIterator[HarnessEvent]:
        assert self._process is not None and self._process.stdout is not None
        deadline = _turn_timeout()
        while True:
            line = await asyncio.wait_for(self._process.stdout.readline(), timeout=deadline)
            if not line:
                return
            if self._cancelled:
                self._kill()
                return
            text = line.decode(errors="replace").strip()
            if not text:
                continue
            if not text.startswith("{"):
                # Plain progress output. Surfacing it as thinking keeps a
                # non-JSON vendor readable instead of silently blank.
                yield HarnessEvent(type="thinking", data={"text": text})
                continue
            try:
                obj = json.loads(text)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue
            for event in parser(obj):
                yield event

    async def run_streaming(self, prompt: str) -> AsyncIterator[str]:
        """Assistant text only, for callers that do not consume harness events.

        ``AgentRuntime`` requires this alongside ``run``; PureMode prefers
        ``run_harness_events`` when present, but the non-streaming paths do not.
        """
        async for event in self.run_harness_events(prompt):
            if event.type == "model_delta":
                text = str(event.data.get("text") or "")
                if text:
                    yield text

    async def run(self, prompt: str):
        """One turn as an ``AgentResponse``, for non-streaming callers."""
        from superqode.agent.loop import AgentResponse

        chunks: list[str] = []
        stopped_reason = "complete"
        error: str | None = None
        async for event in self.run_harness_events(prompt):
            if event.type == "model_delta":
                chunks.append(str(event.data.get("text") or ""))
            elif event.type == "turn_complete":
                status = str(event.data.get("status") or "")
                if status and status != "completed":
                    stopped_reason = status
                    error = event.data.get("error")
        return AgentResponse(
            content="".join(chunks),
            messages=[],
            tool_calls_made=0,
            iterations=1,
            stopped_reason=stopped_reason,
            error=error,
        )

    def _remember_session(self, event: HarnessEvent) -> None:
        session_id = event.data.get("session_id")
        if session_id:
            self._session_id = str(session_id)

    def _kill(self) -> None:
        process = self._process
        if process is not None and process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass

    def cancel(self) -> None:
        self._cancelled = True
        self._kill()

    def reset_cancellation(self) -> None:
        self._cancelled = False

    def set_model(self, model: str | None) -> None:
        if self.config is not None:
            self.config.model = model or ""

    async def aclose(self) -> None:
        self._kill()

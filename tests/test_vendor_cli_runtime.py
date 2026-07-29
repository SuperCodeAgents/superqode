"""Vendor CLI runtime: subscription billing, permissions, and wire formats.

The JSON fixtures are recorded from the real CLIs (Grok streaming-json and
GitHub Copilot JSONL, both verified against live subscriptions), so the parsers
stay honest without needing a vendor CLI installed in CI.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

from superqode.runtime.vendor_cli import (
    VENDOR_CLI_SPECS,
    VendorCLIRuntime,
    parse_copilot_event,
    parse_generic_event,
    parse_grok_event,
    spec_for,
)


def _events(parser, raw: str):
    return parser(json.loads(raw))


class TestGrokWireFormat:
    """Recorded from `grok -p ... --output-format streaming-json`."""

    def test_text_becomes_assistant_output(self):
        events = _events(parse_grok_event, '{"type":"text","data":"OK"}')

        assert [(e.type, e.data["text"]) for e in events] == [("model_delta", "OK")]

    def test_thought_is_reasoning_not_assistant_output(self):
        events = _events(parse_grok_event, '{"type":"thought","data":"pondering"}')

        assert [e.type for e in events] == ["thinking"]

    def test_end_carries_stop_reason_and_session(self):
        events = _events(
            parse_grok_event,
            '{"type":"end","stopReason":"EndTurn","sessionId":"abc","usage":{"input_tokens":7}}',
        )

        assert len(events) == 1
        assert events[0].type == "turn_complete"
        assert events[0].data["stop_reason"] == "EndTurn"
        assert events[0].data["session_id"] == "abc"
        assert events[0].data["usage"] == {"input_tokens": 7}


class TestCopilotWireFormat:
    """Recorded from `copilot -p ... --output-format json`."""

    def test_message_delta_becomes_assistant_output(self):
        events = _events(
            parse_copilot_event,
            '{"type":"assistant.message_delta","data":{"deltaContent":"CLI"}}',
        )

        assert [(e.type, e.data["text"]) for e in events] == [("model_delta", "CLI")]

    def test_auto_mode_reports_the_model_actually_used(self):
        """Copilot Free advertises no catalog, so this is the only model signal."""
        events = _events(
            parse_copilot_event,
            '{"type":"session.auto_mode_resolved","data":{"chosenModel":"gpt-5-mini"}}',
        )

        assert [(e.type, e.data["model"]) for e in events] == [("model_request", "gpt-5-mini")]

    def test_usage_checkpoint_is_reported(self):
        events = _events(
            parse_copilot_event,
            '{"type":"session.usage_checkpoint","data":{"totalPremiumRequests":0}}',
        )

        assert events[0].type == "turn_usage"

    def test_unrecognised_events_are_ignored(self):
        assert _events(parse_copilot_event, '{"type":"session.skills_loaded","data":{}}') == []


class TestGenericWireFormat:
    def test_claude_code_style_content_blocks(self):
        events = _events(
            parse_generic_event,
            '{"type":"assistant","message":{"content":[{"type":"text","text":"hi"}]}}',
        )

        assert [(e.type, e.data["text"]) for e in events] == [("model_delta", "hi")]

    def test_unknown_object_produces_nothing(self):
        """An unknown field must never be rendered as if it were the answer."""
        assert _events(parse_generic_event, '{"type":"telemetry","fooBar":123}') == []


class TestCommandConstruction:
    def _runtime(self, vendor, monkeypatch, model=""):
        monkeypatch.setattr(
            "superqode.runtime.vendor_cli.shutil.which", lambda name: f"/usr/bin/{name}"
        )

        class Config:
            def __init__(self):
                self.model = model
                self.working_directory = Path("/tmp")

        return VendorCLIRuntime(spec=spec_for(vendor), config=Config())

    def test_grok_uses_streaming_json_and_the_prompt_flag(self, monkeypatch):
        argv = self._runtime("grok", monkeypatch).build_command("hello")

        assert "--output-format" in argv and "streaming-json" in argv
        assert argv[-2:] == ["-p", "hello"]

    def test_droid_passes_the_prompt_positionally_after_exec(self, monkeypatch):
        argv = self._runtime("droid", monkeypatch).build_command("hello")

        assert argv[1] == "exec"
        assert argv[-1] == "hello"

    def test_auto_model_is_not_forwarded(self, monkeypatch):
        """'auto' is a SuperQode placeholder, not a vendor model id."""
        argv = self._runtime("grok", monkeypatch, model="auto").build_command("hi")

        assert "--model" not in argv

    def test_explicit_model_is_forwarded(self, monkeypatch):
        argv = self._runtime("grok", monkeypatch, model="grok-build-1").build_command("hi")

        assert argv[argv.index("--model") + 1] == "grok-build-1"

    def test_missing_binary_is_reported_with_install_help(self, monkeypatch):
        from superqode.runtime.errors import RuntimeNotInstalledError

        monkeypatch.setattr("superqode.runtime.vendor_cli.shutil.which", lambda _n: None)

        with pytest.raises(RuntimeNotInstalledError, match="grok login"):
            VendorCLIRuntime(spec=spec_for("grok"), config=None)


class TestPermissionTransparency:
    def test_pre_authorisation_is_announced_once(self, monkeypatch):
        monkeypatch.setattr(
            "superqode.runtime.vendor_cli.shutil.which", lambda name: f"/usr/bin/{name}"
        )
        runtime = VendorCLIRuntime(spec=spec_for("copilot"), config=None)

        first = runtime._permission_notice()
        second = runtime._permission_notice()

        assert first is not None
        assert "not individually approved" in first.data["text"]
        assert second is None, "the notice must not repeat every turn"

    def test_copilot_is_marked_as_requiring_pre_authorisation(self):
        """Its own help says --allow-all-tools is required for non-interactive."""
        spec = VENDOR_CLI_SPECS["copilot"]
        assert spec.requires_pre_authorisation is True
        assert "--allow-all-tools" in spec.flags_for_approval("auto")
        # Copilot offers no gradation non-interactively, so every approval mode
        # resolves to the same flags and the notice must say so.
        assert spec.has_gradated_permissions is False
        assert spec.flags_for_approval("deny") == spec.flags_for_approval("auto")


class TestSubscriptionBilling:
    def test_child_env_drops_the_key_while_os_environ_is_untouched(self, monkeypatch):
        """SuperQode must never modify the user's own API keys."""
        monkeypatch.setattr(
            "superqode.runtime.vendor_cli.shutil.which", lambda name: f"/usr/bin/{name}"
        )
        monkeypatch.setenv("XAI_API_KEY", "user-key")
        captured = {}

        async def fake_exec(*argv, **kwargs):
            captured["env"] = kwargs.get("env", {})
            raise OSError("stop after env capture")

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

        class Config:
            model = ""
            working_directory = Path("/tmp")

        runtime = VendorCLIRuntime(spec=spec_for("grok"), config=Config())

        async def drain():
            return [event async for event in runtime.run_harness_events("hi")]

        events = asyncio.run(drain())

        assert "XAI_API_KEY" not in captured["env"]
        assert os.environ["XAI_API_KEY"] == "user-key", "the user's key must survive"
        assert runtime.stripped_api_keys == ["XAI_API_KEY"]
        assert events[-1].data["status"] == "failed"

    def test_other_providers_keys_reach_the_child_untouched(self, monkeypatch):
        """A Grok subscription must not disturb an unrelated BYOK key."""
        monkeypatch.setattr(
            "superqode.runtime.vendor_cli.shutil.which", lambda name: f"/usr/bin/{name}"
        )
        monkeypatch.setenv("XAI_API_KEY", "xai")
        monkeypatch.setenv("OPENAI_API_KEY", "byok-key")
        captured = {}

        async def fake_exec(*argv, **kwargs):
            captured["env"] = kwargs.get("env", {})
            raise OSError("stop")

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

        class Config:
            model = ""
            working_directory = Path("/tmp")

        runtime = VendorCLIRuntime(spec=spec_for("grok"), config=Config())

        async def drain():
            return [event async for event in runtime.run_harness_events("hi")]

        asyncio.run(drain())

        assert captured["env"]["OPENAI_API_KEY"] == "byok-key"


class TestSpecTable:
    def test_every_spec_resolves_from_its_vendor_and_runtime_name(self):
        for vendor, spec in VENDOR_CLI_SPECS.items():
            assert spec_for(vendor) is spec
            assert spec_for(spec.name) is spec

    def test_every_spec_names_a_parser_that_exists(self):
        from superqode.runtime.vendor_cli import PARSERS

        for spec in VENDOR_CLI_SPECS.values():
            assert spec.parser in PARSERS

    def test_every_spec_has_install_help(self):
        for spec in VENDOR_CLI_SPECS.values():
            assert spec.install_hint.strip()

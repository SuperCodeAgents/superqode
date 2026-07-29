"""Tests for the route-aware ``:copilot`` command surface."""

from __future__ import annotations

import asyncio
import subprocess
from types import SimpleNamespace

from superqode.app_main import SuperQodeApp


class _Log:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []
        self.output = ""

    def add_info(self, value) -> None:
        self.messages.append(("info", str(value)))

    def add_success(self, value) -> None:
        self.messages.append(("success", str(value)))

    def add_error(self, value) -> None:
        self.messages.append(("error", str(value)))

    def write(self, value) -> None:
        self.output += str(value)


def test_copilot_completion_exposes_the_polished_command_family():
    values = {
        candidate.value
        for candidate in SuperQodeApp._copilot_subcommand_completion_candidates(":copilot ")
    }

    assert {
        ":copilot help",
        ":copilot connect",
        ":copilot login",
        ":copilot status",
        ":copilot models",
        ":copilot model",
        ":copilot mode",
        ":copilot sessions",
        ":copilot resume",
        ":copilot sdk",
        ":copilot cli",
        ":copilot version",
    } <= values


def test_copilot_models_uses_cli_catalog_when_sdk_is_absent(monkeypatch):
    chosen: dict[str, object] = {}

    # The CLI branch is guarded by shutil.which("copilot"). A developer machine
    # has the CLI installed and CI does not, so pin it for the test.
    monkeypatch.setattr(
        "superqode.app.mixins.commands_impl.shutil.which",
        lambda name: "/opt/copilot" if name == "copilot" else None,
    )

    class Stub:
        def _copilot_prefers_sdk(self):
            return False

        async def _copilot_acp_models(self):
            return (
                [
                    {"modelId": "auto", "name": "Auto"},
                    {"modelId": "gpt-example", "displayName": "GPT Example"},
                ],
                "auto",
            )

        def _show_vendor_model_picker(self, _log, **kwargs):
            chosen.update(kwargs)
            return True

        def _copilot_model_cmd(self, model, _log):
            chosen["selected"] = model

    log = _Log()
    asyncio.run(SuperQodeApp._copilot_models_cmd(Stub(), log))

    assert chosen["entries"] == [
        ("auto", "Auto"),
        ("gpt-example", "GPT Example"),
    ]
    assert chosen["current"] == "auto"
    chosen["on_choose"]("gpt-example")
    assert chosen["selected"] == "gpt-example"
    assert not log.messages


def test_copilot_cli_model_selection_uses_advertised_config_option():
    calls: list[tuple[str, str]] = []

    class Client:
        async def get_available_models(self):
            return [{"modelId": "auto"}, {"modelId": "gpt-example"}]

        def get_session_config_options(self):
            return [{"id": "model", "category": "model"}]

        async def set_config_option(self, option, value):
            calls.append((option, value))
            return True

        async def set_model(self, _value):
            raise AssertionError("model config option should be preferred")

    class Stub:
        current_model = ""
        current_provider = ""
        _acp_client_key = None

        async def _copilot_acp_client_on_loop(self):
            return Client()

        async def _run_copilot_acp_operation(self, operation):
            return await operation

        def _set_status_model(self, model):
            self.status_model = model

    stub = Stub()
    log = _Log()
    asyncio.run(SuperQodeApp._copilot_set_acp_model_cmd(stub, "gpt-example", log))

    assert calls == [("model", "gpt-example")]
    assert stub.current_model == "gpt-example"
    assert stub.current_provider == "github"
    assert stub.status_model == "gpt-example"
    assert ("success", "GitHub Copilot model set to gpt-example") in log.messages


def test_copilot_free_account_cannot_select_unadvertised_model():
    class Client:
        async def get_available_models(self):
            return [{"modelId": "auto"}]

        def get_session_config_options(self):
            return [{"id": "model", "category": "model"}]

    class Stub:
        current_model = ""

        async def _copilot_acp_client_on_loop(self):
            return Client()

        async def _run_copilot_acp_operation(self, operation):
            return await operation

    log = _Log()
    asyncio.run(SuperQodeApp._copilot_set_acp_model_cmd(Stub(), "paid-model", log))

    assert any(
        "not available to this Copilot account" in message
        for kind, message in log.messages
        if kind == "error"
    )


def test_copilot_empty_catalog_refuses_instead_of_reporting_false_success():
    """Copilot Free advertises no models, and the CLI accepts set_model anyway.

    Verified live against GitHub Copilot CLI 1.0.75 on a Free account:
    ``session/models`` returns ``[]``, no ``model`` config option is offered,
    and ``session/set_model`` still answers success for an arbitrary id.
    """

    class Client:
        async def get_available_models(self):
            return []

        def get_session_config_options(self):
            return [{"id": "mode", "category": "mode"}]

        async def set_model(self, _value):
            raise AssertionError("must not attempt a set the account cannot honour")

    class Stub:
        current_model = ""

        async def _copilot_acp_client_on_loop(self):
            return Client()

        async def _run_copilot_acp_operation(self, operation):
            return await operation

    log = _Log()
    asyncio.run(SuperQodeApp._copilot_set_acp_model_cmd(Stub(), "gpt-5", log))

    assert any(
        "advertises no selectable models" in message
        for kind, message in log.messages
        if kind == "error"
    )
    assert Stub.current_model == ""


def test_copilot_mode_resolves_short_name_to_the_advertised_uri():
    calls: list[str] = []
    agent = "https://agentclientprotocol.com/protocol/session-modes#agent"
    plan = "https://agentclientprotocol.com/protocol/session-modes#plan"

    class Client:
        async def set_mode(self, mode_id):
            calls.append(mode_id)
            return True

    class Stub:
        _copilot_mode_label = staticmethod(SuperQodeApp._copilot_mode_label)

        async def _copilot_acp_modes(self):
            return (
                [{"id": agent, "name": "Agent"}, {"id": plan, "name": "Plan"}],
                agent,
            )

        async def _copilot_acp_client_on_loop(self):
            return Client()

        async def _run_copilot_acp_operation(self, operation):
            return await operation

    log = _Log()
    asyncio.run(SuperQodeApp._copilot_mode_worker(Stub(), "plan", log))

    assert calls == [plan]
    assert ("success", "GitHub Copilot mode set to plan") in log.messages


def test_copilot_unknown_mode_lists_the_advertised_choices():
    plan = "https://agentclientprotocol.com/protocol/session-modes#plan"

    class Stub:
        _copilot_mode_label = staticmethod(SuperQodeApp._copilot_mode_label)

        async def _copilot_acp_modes(self):
            return ([{"id": plan, "name": "Plan"}], plan)

    log = _Log()
    asyncio.run(SuperQodeApp._copilot_mode_worker(Stub(), "turbo", log))

    assert ("error", "Unknown GitHub Copilot mode: turbo") in log.messages
    assert ("info", "Available modes: plan") in log.messages


def test_copilot_sessions_names_the_sdk_requirement_on_a_cli_only_install():
    class Stub:
        _copilot_requires_sdk_route = SuperQodeApp._copilot_requires_sdk_route

        def _copilot_prefers_sdk(self):
            return False

        def _copilot_runtime_or_connect(self, _log):
            raise AssertionError("must not reach into the SDK runtime")

    log = _Log()
    asyncio.run(SuperQodeApp._copilot_sessions_cmd(Stub(), log))

    errors = [message for kind, message in log.messages if kind == "error"]
    assert errors and "Copilot SDK" in errors[0]
    assert not any("not connected" in message for message in errors)


def test_copilot_version_uses_explicit_binary_argv(monkeypatch):
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(command, 0, stdout="GitHub Copilot CLI 1.0.75\n")

    monkeypatch.setattr(
        "superqode.app.mixins.commands_impl.shutil.which",
        lambda name: "/opt/copilot" if name == "copilot" else None,
    )
    monkeypatch.setattr(
        "superqode.app.mixins.commands_impl.subprocess.run",
        fake_run,
    )
    log = _Log()

    SuperQodeApp._copilot_version(log)

    assert captured["command"] == ["/opt/copilot", "--version"]
    assert captured["kwargs"]["stdin"] is subprocess.DEVNULL
    assert "1.0.75" in log.messages[0][1]


def test_copilot_help_calls_catalog_not_one_line_usage():
    log = _Log()

    SuperQodeApp._show_copilot_help(log)

    assert ":copilot models" in log.output
    assert "Copilot Free" in log.output

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from superqode.agent.loop import AgentConfig
from superqode.runtime.devin_cli import (
    DEFAULT_PERMISSION_MODE,
    DevinCLIRuntime,
    sandbox_supported,
)
from superqode.runtime.devin_status import probe_devin_cli, version_tuple


@pytest.fixture(autouse=True)
def _clear_devin_overrides(monkeypatch):
    monkeypatch.delenv("SUPERQODE_DEVIN_CLI_PERMISSION_MODE", raising=False)
    monkeypatch.delenv("SUPERQODE_DEVIN_CLI_SANDBOX", raising=False)


@pytest.fixture
def _installed(monkeypatch):
    """Pretend the CLI is on PATH with a deterministic sandbox answer."""
    monkeypatch.setattr("shutil.which", lambda _name: "/tmp/devin")
    monkeypatch.setattr("superqode.runtime.devin_cli.sandbox_supported", lambda: True)


def _runtime(tmp_path: Path, **kwargs) -> DevinCLIRuntime:
    return DevinCLIRuntime(
        config=AgentConfig(
            provider="devin", model=kwargs.pop("model", ""), working_directory=tmp_path
        )
    )


def test_version_tuple():
    assert version_tuple("devin 1.4.2") == (1, 4, 2)
    assert version_tuple("2.0.0") == (2, 0, 0)
    assert version_tuple("unknown") is None


def test_missing_cli_is_reported_with_install_hint(monkeypatch, tmp_path):
    monkeypatch.setattr("shutil.which", lambda _name: None)
    from superqode.runtime.errors import RuntimeNotInstalledError

    with pytest.raises(RuntimeNotInstalledError, match="docs.devin.ai/cli"):
        _runtime(tmp_path)


def test_print_turn_never_waits_on_a_prompt(_installed, tmp_path):
    """An unattended turn must use a mode that cannot block on approval."""
    command = _runtime(tmp_path)._command("hello")

    assert DEFAULT_PERMISSION_MODE == "bypass"
    assert command[command.index("--permission-mode") + 1] == "bypass"
    assert "--sandbox" in command


def test_prompt_is_separated_from_flags(_installed, tmp_path):
    """A prompt starting with `-` is still a prompt, not a flag."""
    command = _runtime(tmp_path)._command("--version is what I want to know")

    assert command[-3:] == ["--print", "--", "--version is what I want to know"]


def test_model_is_forwarded_when_set(_installed, tmp_path):
    command = _runtime(tmp_path, model="opus")._command("hi")

    assert command[command.index("--model") : command.index("--model") + 2] == ["--model", "opus"]

    assert "--model" not in _runtime(tmp_path)._command("hi")


def test_first_turn_starts_fresh_then_resumes_the_captured_session(_installed, tmp_path):
    runtime = _runtime(tmp_path)

    first = runtime._command("hello")
    assert "--resume" not in first
    assert "--continue" not in first

    runtime._started_session = True
    runtime._session_id = "brisk-otter"
    resumed = runtime._command("again")
    assert resumed[resumed.index("--resume") : resumed.index("--resume") + 2] == [
        "--resume",
        "brisk-otter",
    ]
    assert "--continue" not in resumed


def test_unresolved_session_falls_back_to_continue(_installed, tmp_path):
    runtime = _runtime(tmp_path)
    runtime._started_session = True

    command = runtime._command("again")

    assert "--continue" in command
    assert "--resume" not in command


def test_new_session_drops_continuity(_installed, tmp_path):
    runtime = _runtime(tmp_path)
    runtime._started_session = True
    runtime._session_id = "brisk-otter"

    runtime.new_session()

    command = runtime._command("fresh")
    assert "--resume" not in command
    assert "--continue" not in command


@pytest.mark.parametrize(
    "payload, expected",
    [
        (b'[{"id": "brisk-otter"}]', "brisk-otter"),
        (b'{"sessions": [{"session_id": "calm-vole"}]}', "calm-vole"),
        (b'[{"name": "eager-lynx"}]', "eager-lynx"),
        # Shapes SuperQode does not recognise must not invent an id.
        (b'{"unexpected": true}', None),
        (b"[]", None),
        (b"not json", None),
        (b'[{"unknown_key": "x"}]', None),
    ],
)
def test_session_capture_is_defensive_about_an_undocumented_schema(
    _installed, monkeypatch, tmp_path, payload, expected
):
    class Process:
        returncode = 0

        async def communicate(self):
            return payload, b""

    async def create(*_args, **_kwargs):
        return Process()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create)
    runtime = _runtime(tmp_path)

    asyncio.run(runtime._capture_session_id())

    assert runtime.session_id == expected


def test_session_capture_survives_a_failing_list(_installed, monkeypatch, tmp_path):
    class Process:
        returncode = 1

        async def communicate(self):
            return b"", b"boom"

    async def create(*_args, **_kwargs):
        return Process()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create)
    runtime = _runtime(tmp_path)

    asyncio.run(runtime._capture_session_id())

    assert runtime.session_id is None


def test_permission_mode_override_is_validated(_installed, monkeypatch, tmp_path):
    monkeypatch.setenv("SUPERQODE_DEVIN_CLI_PERMISSION_MODE", "accept_edits")
    runtime = _runtime(tmp_path)
    assert runtime.permission_mode == "accept-edits"

    runtime.set_permission_mode("autonomous")
    assert runtime.permission_mode == "autonomous"

    with pytest.raises(ValueError, match="permission mode must be one of"):
        runtime.set_permission_mode("yolo")


def test_sandbox_can_be_disabled_by_env(monkeypatch, tmp_path):
    monkeypatch.setattr("shutil.which", lambda _name: "/tmp/devin")
    monkeypatch.setattr("superqode.runtime.devin_cli.sandbox_supported", lambda: True)
    monkeypatch.setenv("SUPERQODE_DEVIN_CLI_SANDBOX", "0")

    assert "--sandbox" not in _runtime(tmp_path)._command("hi")


def test_sandbox_is_not_forced_where_devin_cannot_start(monkeypatch, tmp_path):
    """Devin refuses to run unsandboxed, so an unsupported platform must not get the flag."""
    monkeypatch.setattr("shutil.which", lambda _name: "/tmp/devin")
    monkeypatch.setattr("superqode.runtime.devin_cli.sandbox_supported", lambda: False)
    monkeypatch.setenv("SUPERQODE_DEVIN_CLI_SANDBOX", "1")

    assert "--sandbox" not in _runtime(tmp_path)._command("hi")


def test_sandbox_support_follows_the_platform(monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")
    assert sandbox_supported() is False

    monkeypatch.setattr("sys.platform", "darwin")
    assert sandbox_supported() is True

    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setattr("shutil.which", lambda name: None if name == "bwrap" else "/usr/bin/socat")
    assert sandbox_supported() is False
    monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/tool")
    assert sandbox_supported() is True


def test_stderr_is_drained_concurrently_and_bounded():
    class Stream:
        def __init__(self):
            self.chunks = [b"a" * 40000, b"b" * 40000, b""]

        async def read(self, _size):
            return self.chunks.pop(0)

    output = asyncio.run(DevinCLIRuntime._read_bounded_stderr(Stream(), limit=65536))

    assert len(output) == 65536
    assert output.endswith(b"b" * 40000)


def test_metadata_identifies_the_devin_harness(_installed, tmp_path):
    runtime = _runtime(tmp_path)

    assert runtime.metadata["runtime"] == "devin-cli"
    assert runtime.metadata["harness_owner"] == "devin"
    assert runtime.metadata["authentication"] == "devin-cli-login"
    # `--print` emits prose, so callers must not expect tool-call events.
    assert runtime.metadata["structured_events"] is False
    assert runtime.metadata["permission_mode"] == "bypass"
    assert runtime.metadata["session_id"] is None


def test_probe_points_at_the_install_docs_when_missing(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _name: None)

    status = probe_devin_cli()

    assert status.installed is False
    assert status.compatible is False
    assert "docs.devin.ai/cli" in status.detail


def test_probe_reports_a_signed_out_cli_without_blocking_it(monkeypatch):
    class Result:
        def __init__(self, returncode, stdout=""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = ""

    def run(args, **_kwargs):
        return Result(0, "devin 1.4.2\n") if args[1] == "version" else Result(1)

    monkeypatch.setattr("shutil.which", lambda _name: "/tmp/devin")
    monkeypatch.setattr("subprocess.run", run)

    status = probe_devin_cli()

    assert status.installed is True
    assert status.authenticated is False
    # An unauthenticated CLI is still usable once the user signs in, so the
    # runtime stays selectable and the detail carries the fix.
    assert status.compatible is True
    assert "devin auth login" in status.detail


def test_probe_reports_a_signed_in_cli(monkeypatch):
    class Result:
        returncode = 0
        stdout = "devin 1.4.2\n"
        stderr = ""

    monkeypatch.setattr("shutil.which", lambda _name: "/tmp/devin")
    monkeypatch.setattr("subprocess.run", lambda *_args, **_kwargs: Result())

    status = probe_devin_cli()

    assert status.version == (1, 4, 2)
    assert status.authenticated is True
    assert "signed in" in status.detail


def test_registry_exposes_devin_cli(monkeypatch):
    from superqode.runtime.registry import known_runtime_names, list_runtimes

    assert "devin-cli" in known_runtime_names()

    monkeypatch.setattr("shutil.which", lambda _name: None)
    info = {entry.name: entry for entry in list_runtimes()}["devin-cli"]

    assert info.implemented is True
    assert info.installed is False
    assert "docs.devin.ai/cli" in (info.install_hint or "")

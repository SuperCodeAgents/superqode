"""What SuperQode will and will not run on a user's behalf."""

from __future__ import annotations

import pytest

from superqode.agents.install_commands import classify_install_command


@pytest.mark.parametrize(
    "command,kind",
    [
        ("npm install -g @kilocode/cli", "npm"),
        ("npm i -g opencode-ai", "npm"),
        ("cargo install code-assistant", "cargo"),
        ("go install github.com/opencode-ai/opencode@latest", "go"),
        ("uv tool install superqode", "python"),
        ("pipx install stakpak", "python"),
        ("brew install something", "brew"),
    ],
)
def test_named_package_installs_are_runnable(command, kind):
    """The artifact is named, so consenting to install it is informed."""
    result = classify_install_command(command)

    assert result.runnable is True
    assert result.kind == kind
    assert result.argv[0] == command.split()[0]


@pytest.mark.parametrize(
    "command",
    [
        "curl -fsSL https://code.kimi.com/kimi-code/install.sh | bash",
        "curl -fsSL https://example.com/install.sh | sh",
        "irm https://x.ai/cli/install.ps1 | iex",
    ],
)
def test_pipe_to_shell_is_never_run(command):
    """Agreeing to install an agent is not agreement to run a remote script."""
    result = classify_install_command(command)

    assert result.runnable is False
    assert result.kind == "pipe-to-shell"
    assert "does not run those for you" in result.reason
    assert result.argv == []


def test_shell_metacharacters_are_not_run():
    """Anything needing a shell has the same reviewability problem."""
    result = classify_install_command("npm install -g foo && npm run setup")

    assert result.runnable is False
    assert result.argv == []


def test_bare_pip_install_is_reported_not_run_or_rewritten():
    """`pip install` targets whichever pip is first on PATH, rarely the right one.

    SuperQode neither runs it nor silently substitutes a different command for
    the one the registry declared; it names the uv equivalent instead.
    """
    result = classify_install_command("pip install stakpak")

    assert result.runnable is False
    assert result.command == "pip install stakpak", "the declared command must not be rewritten"
    assert "uv pip install stakpak" in result.reason
    assert result.argv == []


def test_unknown_commands_are_left_to_the_user():
    result = classify_install_command("bub install bub-acp-server@main")

    assert result.runnable is False
    assert result.reason


def test_missing_command_is_reported_as_none():
    result = classify_install_command("")

    assert result.kind == "none"
    assert result.runnable is False

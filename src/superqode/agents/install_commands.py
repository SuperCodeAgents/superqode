"""Classify ACP agent install commands and decide what SuperQode may run.

Agent install commands come from the registry and are written by third parties.
They fall into two very different groups:

* Package-manager installs (``npm install -g <pkg>``, ``cargo install <pkg>``,
  ``uv tool install <pkg>``). The artifact is named, so a user consenting to
  "install this agent" knows what is being fetched.
* Pipe-to-shell installs (``curl ... | bash``). These execute a remote script
  that the user cannot review and whose contents can change after SuperQode
  shipped. Consenting to install an agent is not informed consent to run
  arbitrary remote code, so SuperQode never runs these itself.

SuperQode deliberately does not repair the user's toolchain. If ``npm`` fails
because their Node is too old, the failure is reported verbatim and the flow
stops rather than escalating to sudo or editing PATH.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass

__all__ = ["InstallCommand", "classify_install_command"]

#: Leading tokens of commands whose artifact is explicitly named.
_RUNNABLE_PREFIXES: tuple[tuple[str, ...], ...] = (
    ("npm", "install"),
    ("npm", "i"),
    ("pnpm", "add"),
    ("yarn", "global"),
    ("cargo", "install"),
    ("go", "install"),
    ("uv", "tool"),
    ("uvx",),
    ("pipx", "install"),
    ("brew", "install"),
)

_SHELL_PIPE_TOKENS = ("|", "&&", ";", ">", "<", "`", "$(")


@dataclass(frozen=True)
class InstallCommand:
    """A registry install command and what SuperQode is willing to do with it."""

    raw: str
    #: Command SuperQode would actually run; normalised where needed.
    command: str
    kind: str  # "npm" | "cargo" | "go" | "python" | "brew" | "pipe-to-shell" | "other" | "none"
    runnable: bool
    #: Why the command is not runnable, shown to the user.
    reason: str = ""

    @property
    def argv(self) -> list[str]:
        """Argument vector for a runnable command, empty when not runnable."""
        if not self.runnable:
            return []
        try:
            return shlex.split(self.command)
        except ValueError:
            return []


def _is_pipe_to_shell(command: str) -> bool:
    lowered = command.lower()
    if "|" not in lowered:
        return False
    return any(shell in lowered for shell in ("sh", "bash", "zsh", "iex", "powershell"))


def classify_install_command(raw: str) -> InstallCommand:
    """Decide whether SuperQode may run ``raw`` on the user's behalf."""
    command = (raw or "").strip()
    if not command:
        return InstallCommand(raw="", command="", kind="none", runnable=False)

    if _is_pipe_to_shell(command):
        return InstallCommand(
            raw=command,
            command=command,
            kind="pipe-to-shell",
            runnable=False,
            reason=(
                "SuperQode does not run those for you. Remote scripts piped into "
                "a shell can change without notice; review the vendor's command "
                "before running it yourself."
            ),
        )

    # Anything else carrying shell metacharacters needs a shell to mean what it
    # says, and running it through one has the same reviewability problem.
    if any(token in command for token in _SHELL_PIPE_TOKENS):
        return InstallCommand(
            raw=command,
            command=command,
            kind="other",
            runnable=False,
            reason="This installer needs a shell to run, so SuperQode leaves it to you.",
        )

    try:
        tokens = shlex.split(command)
    except ValueError:
        return InstallCommand(
            raw=command,
            command=command,
            kind="other",
            runnable=False,
            reason="This install command could not be parsed safely.",
        )
    if not tokens:
        return InstallCommand(raw=command, command="", kind="none", runnable=False)

    # A bare `pip install` targets whichever pip is first on PATH, which is
    # rarely the environment the user expects. SuperQode does not silently
    # rewrite the registry's command into something else, so this is reported
    # rather than run, with the uv equivalent named for anyone who wants it.
    if tokens[0] in {"pip", "pip3"} and len(tokens) >= 3 and tokens[1] == "install":
        packages = [token for token in tokens[2:] if not token.startswith("-")]
        suggestion = " ".join(shlex.quote(package) for package in packages)
        return InstallCommand(
            raw=command,
            command=command,
            kind="python",
            runnable=False,
            reason=(
                "SuperQode does not run bare 'pip install', which targets whichever "
                "pip is first on PATH. To install it into a known environment, use "
                + (f"'uv pip install {suggestion}'" if suggestion else "'uv pip install'")
                + " yourself."
            ),
        )

    for prefix in _RUNNABLE_PREFIXES:
        if tuple(tokens[: len(prefix)]) == prefix:
            kind = {
                "npm": "npm",
                "pnpm": "npm",
                "yarn": "npm",
                "cargo": "cargo",
                "go": "go",
                "uv": "python",
                "uvx": "python",
                "pipx": "python",
                "brew": "brew",
            }.get(tokens[0], "other")
            return InstallCommand(raw=command, command=command, kind=kind, runnable=True)

    return InstallCommand(
        raw=command,
        command=command,
        kind="other",
        runnable=False,
        reason="SuperQode only runs recognised package-manager installs.",
    )

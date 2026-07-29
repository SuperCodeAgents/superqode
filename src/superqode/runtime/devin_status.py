"""Cheap local readiness probe for Cognition's Devin CLI.

Reads nothing but the binary's own output. Devin owns its credential store and
SuperQode never opens it, so sign-in state is inferred from the exit code of
``devin auth status`` and reported as advice rather than used as a gate.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import time
from dataclasses import dataclass

INSTALL_HINT = "install the Devin CLI from https://docs.devin.ai/cli"

# `list_runtimes()` runs this probe, and the TUI calls that once per vendor
# entry while building a picker - so an uncached probe spawned two `devin`
# subprocesses per keystroke and stalled completion for seconds. Installation,
# version, and sign-in barely change during a session, so a short TTL keeps the
# answer fresh enough for `:runtime doctor` without re-forking the CLI.
_CACHE_TTL_SECONDS = 30.0

# Devin publishes no documented floor for `devin acp` / `devin --print`, so
# SuperQode records the version for diagnostics and does not gate on it.
# Add a minimum here only when a release is known to break the subprocess path.


def version_tuple(text: str) -> tuple[int, int, int] | None:
    """Extract a semantic version triple from ``devin version`` output."""
    match = re.search(r"(?<!\d)(\d+)\.(\d+)\.(\d+)", text or "")
    return tuple(map(int, match.groups())) if match else None


@dataclass(frozen=True)
class DevinCLIStatus:
    binary: str | None
    version_text: str = ""
    version: tuple[int, int, int] | None = None
    issue: str = ""
    # None when sign-in state could not be determined; the CLI verifies it on
    # first use either way.
    authenticated: bool | None = None

    @property
    def installed(self) -> bool:
        return self.binary is not None

    @property
    def compatible(self) -> bool:
        return self.installed and not self.issue

    @property
    def detail(self) -> str:
        """One-line summary for `superqode runtime list`."""
        if not self.installed:
            return INSTALL_HINT
        if self.issue:
            return self.issue
        version = f"Devin CLI {self.version_text}" if self.version_text else "Devin CLI"
        if self.authenticated is True:
            return f"{version}; signed in"
        if self.authenticated is False:
            return f"{version}; run `devin auth login`"
        return f"{version}; sign-in is verified on first use"


def _run(binary: str, args: list[str], *, timeout: float) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(
            [binary, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None


_cached: tuple[float, DevinCLIStatus] | None = None


def clear_devin_cli_cache() -> None:
    """Drop the memoized probe so the next call re-runs the CLI."""
    global _cached
    _cached = None


def probe_devin_cli(*, timeout: float = 3.0, refresh: bool = False) -> DevinCLIStatus:
    """Report installation, version, and sign-in without touching credentials.

    The result is memoized for ``_CACHE_TTL_SECONDS``. Pass ``refresh=True``
    when the user has just been told to install or sign in and expects the next
    read to reflect it.
    """
    global _cached

    if not refresh and _cached is not None:
        probed_at, status = _cached
        if time.monotonic() - probed_at < _CACHE_TTL_SECONDS:
            return status
    status = _probe_devin_cli(timeout=timeout)
    _cached = (time.monotonic(), status)
    return status


def _probe_devin_cli(*, timeout: float) -> DevinCLIStatus:
    binary = shutil.which("devin")
    if not binary:
        return DevinCLIStatus(binary=None, issue=INSTALL_HINT)

    version_process = _run(binary, ["version"], timeout=timeout)
    if version_process is None:
        return DevinCLIStatus(binary=binary, issue="could not run `devin version`")

    text = (version_process.stdout or version_process.stderr or "").strip()
    version = version_tuple(text)
    if version_process.returncode:
        return DevinCLIStatus(
            binary=binary,
            version_text=text,
            version=version,
            issue=f"`devin version` failed: {text or 'no output'}",
        )

    # Exit status is the only sign-in signal SuperQode reads; an unreadable
    # result stays None so a probe quirk never blocks a working CLI.
    auth_process = _run(binary, ["auth", "status"], timeout=timeout)
    authenticated = None if auth_process is None else auth_process.returncode == 0

    return DevinCLIStatus(
        binary=binary,
        version_text=text,
        version=version,
        authenticated=authenticated,
    )


__all__ = [
    "DevinCLIStatus",
    "INSTALL_HINT",
    "clear_devin_cli_cache",
    "probe_devin_cli",
    "version_tuple",
]

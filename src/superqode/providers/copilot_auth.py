"""Establish whether the GitHub Copilot CLI is actually signed in.

The CLI has no ``whoami`` or ``auth status`` subcommand, and its token is kept
in the OS credential store (falling back to a file under ``~/.copilot/``), so
there is nothing readable to inspect. The only honest check is to start the CLI
and see whether it reports that authentication is required.

That costs a few seconds, so callers should run it in the background. It never
reads, copies, or logs a credential: the result is one boolean plus a reason.
"""

from __future__ import annotations

import asyncio
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

_DEFAULT_PROBE_TIMEOUT = 15.0


def _probe_timeout() -> float:
    try:
        value = float(os.environ.get("SUPERQODE_COPILOT_AUTH_PROBE_TIMEOUT", "") or 0)
    except ValueError:
        return _DEFAULT_PROBE_TIMEOUT
    return value if value > 0 else _DEFAULT_PROBE_TIMEOUT


@dataclass(frozen=True)
class CopilotLoginState:
    """Outcome of a sign-in probe."""

    signed_in: bool
    needs_login: bool
    detail: str

    @property
    def determined(self) -> bool:
        """True when the probe actually established a state either way."""
        return self.signed_in or self.needs_login


async def probe_copilot_login(timeout: float | None = None) -> CopilotLoginState:
    """Check the Copilot CLI sign-in state without prompting for anything."""
    binary = shutil.which("copilot")
    if binary is None:
        return CopilotLoginState(
            signed_in=False,
            needs_login=False,
            detail="the Copilot CLI is not on PATH",
        )

    # An explicit token is the documented headless path, so treat it as signed
    # in without starting a process. The value itself is never read.
    if os.environ.get("COPILOT_GITHUB_TOKEN"):
        return CopilotLoginState(
            signed_in=True,
            needs_login=False,
            detail="COPILOT_GITHUB_TOKEN is set",
        )

    from superqode.acp.client import ACPClient

    messages: list[str] = []
    limit = timeout or _probe_timeout()
    client = ACPClient(
        project_root=Path.cwd(),
        command="copilot --acp --stdio",
        startup_timeout=limit,
        # Probing must not disturb billing state either.
        subscription_vendor="copilot",
    )

    async def _on_thinking(message: str) -> None:
        messages.append(str(message))

    client.on_thinking = _on_thinking

    try:
        started = await asyncio.wait_for(client.start(), timeout=limit + 5.0)
    except (asyncio.TimeoutError, Exception) as exc:  # noqa: BLE001 - probe is advisory
        detail = "the probe timed out" if isinstance(exc, asyncio.TimeoutError) else str(exc)
        return CopilotLoginState(
            signed_in=False, needs_login=False, detail=detail or "probe failed"
        )
    finally:
        try:
            await client.stop()
        except Exception:  # noqa: BLE001 - best-effort teardown
            pass

    joined = " ".join(messages).lower()
    if "authentication required" in joined or "not signed in" in joined or "login" in joined:
        return CopilotLoginState(
            signed_in=False,
            needs_login=True,
            detail="the Copilot CLI reported that authentication is required",
        )
    if started:
        return CopilotLoginState(
            signed_in=True,
            needs_login=False,
            detail="the Copilot CLI started an authenticated session",
        )
    return CopilotLoginState(
        signed_in=False,
        needs_login=False,
        detail=(messages[-1] if messages else "the Copilot CLI did not start"),
    )


__all__ = ["CopilotLoginState", "probe_copilot_login"]

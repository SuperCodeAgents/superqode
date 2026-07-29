"""SuperQode 'update' CLI: upgrade SuperQode itself to the latest release.

The correct upgrade command depends entirely on how SuperQode was installed.
Running ``uv tool upgrade`` inside a git checkout does nothing useful, and
running ``pip install --upgrade`` against a uv tool environment rebuilds it
underneath the running process. ``running_context()`` already classifies the
environment, so reuse it rather than guessing.
"""

from __future__ import annotations

import json
import shlex
import shutil
import subprocess
import sys
import urllib.error
import urllib.request

import click

from superqode import __version__

PYPI_JSON_URL = "https://pypi.org/pypi/superqode/json"
_PYPI_TIMEOUT = 10.0


def latest_released_version(timeout: float = _PYPI_TIMEOUT) -> str | None:
    """Newest version on PyPI, or None when it cannot be determined."""
    try:
        with urllib.request.urlopen(PYPI_JSON_URL, timeout=timeout) as response:
            payload = json.load(response)
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return None
    version = payload.get("info", {}).get("version")
    return str(version) if version else None


def _version_tuple(value: str) -> tuple:
    parts = []
    for chunk in str(value).split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def is_newer(candidate: str, current: str) -> bool:
    """True when ``candidate`` is a strictly newer release than ``current``."""
    try:
        return _version_tuple(candidate) > _version_tuple(current)
    except (TypeError, ValueError):
        return False


def upgrade_command(context: str, target: str | None = None) -> list[str] | None:
    """Argv that upgrades SuperQode for ``context``, or None when unsupported.

    ``target`` pins an exact version; omit it for the newest release.
    """
    requirement = f"superqode=={target}" if target else "superqode"
    has_uv = shutil.which("uv") is not None

    if context == "uv-tool":
        if not has_uv:
            return None
        # `uv tool upgrade` keeps the extras the tool was installed with;
        # reinstalling by name would silently drop them.
        if target:
            return ["uv", "tool", "install", "--force", requirement]
        return ["uv", "tool", "upgrade", "superqode"]

    if context in {"venv", "project", "system"}:
        if has_uv:
            return ["uv", "pip", "install", "--python", sys.executable, "--upgrade", requirement]
        return [sys.executable, "-m", "pip", "install", "--upgrade", requirement]

    # dev-checkout is intentionally unsupported: the source of truth is git.
    return None


@click.command()
@click.option("--check", is_flag=True, help="Report the latest version without installing.")
@click.option("--version", "target", default=None, help="Install an exact version.")
@click.option("-y", "--yes", is_flag=True, help="Do not ask for confirmation.")
def update(check: bool, target: str | None, yes: bool) -> None:
    """Update SuperQode to the latest released version."""
    from superqode.providers.env_introspect import environment_info

    info = environment_info()
    click.echo(f"Installed : {__version__}  ({info.label})")

    latest = latest_released_version()
    if latest is None:
        click.echo("Latest    : unavailable (could not reach PyPI)")
    else:
        click.echo(f"Latest    : {latest}")

    if check:
        if latest and is_newer(latest, __version__):
            click.echo(f"\nAn update is available: {__version__} -> {latest}")
            click.echo("Run: superqode update")
        elif latest:
            click.echo("\nSuperQode is up to date.")
        return

    if info.context == "dev-checkout":
        click.echo(
            "\nRunning from a SuperQode git checkout, so there is nothing to install over.",
            err=True,
        )
        click.echo(f"Update it with git instead:\n  cd {info.project_root}\n  git pull", err=True)
        raise SystemExit(1)

    if not target and latest and not is_newer(latest, __version__):
        click.echo("\nAlready on the latest version. Nothing to do.")
        return

    argv = upgrade_command(info.context, target)
    if argv is None:
        click.echo(
            "\nCould not determine how to upgrade this installation. Install uv "
            "(https://docs.astral.sh/uv/) or upgrade with your package manager.",
            err=True,
        )
        raise SystemExit(1)

    printable = " ".join(shlex.quote(part) for part in argv)
    click.echo(f"\nUpdating with:\n  {printable}")
    if not yes and not click.confirm("Proceed?", default=True):
        click.echo("Cancelled.")
        return

    try:
        completed = subprocess.run(argv, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        click.echo(f"Update failed: {exc}", err=True)
        raise SystemExit(1) from exc

    if completed.returncode != 0:
        click.echo(f"Update failed (exit {completed.returncode}).", err=True)
        raise SystemExit(completed.returncode)

    click.echo("\nUpdated. Restart superqode to use the new version.")

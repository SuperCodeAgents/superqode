from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "install" / "install.sh"
HOSTED_INSTALLER = ROOT / "docs" / "install.sh"
WRAPPER = ROOT / "scripts" / "install.sh"

pytestmark = pytest.mark.skipif(shutil.which("sh") is None, reason="POSIX sh is required")


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _fake_tool_environment(tmp_path: Path) -> tuple[dict[str, str], Path]:
    command_bin = tmp_path / "commands"
    tool_bin = tmp_path / "tools"
    command_bin.mkdir()
    tool_bin.mkdir()
    uv_log = tmp_path / "uv.log"

    _write_executable(
        command_bin / "uv",
        """#!/bin/sh
printf '%s\\n' "$*" >> "$FAKE_UV_LOG"
if [ "$1" = "tool" ] && [ "$2" = "install" ]; then
    exit 0
fi
if [ "$1" = "tool" ] && [ "$2" = "dir" ]; then
    printf '%s\\n' "$FAKE_TOOL_BIN"
    exit 0
fi
exit 2
""",
    )
    _write_executable(tool_bin / "superqode", "#!/bin/sh\nprintf '%s\\n' 'superqode 0.test'\n")
    _write_executable(tool_bin / "sq", "#!/bin/sh\nprintf '%s\\n' 'sq 0.test'\n")

    env = {
        **os.environ,
        "HOME": str(tmp_path / "home"),
        "PATH": os.pathsep.join((str(command_bin), os.environ.get("PATH", ""))),
        "FAKE_UV_LOG": str(uv_log),
        "FAKE_TOOL_BIN": str(tool_bin),
    }
    return env, uv_log


def test_installer_is_valid_posix_shell_and_hosted_copy_stays_exact():
    for path in (INSTALLER, HOSTED_INSTALLER, WRAPPER):
        result = subprocess.run(
            ["sh", "-n", str(path)],
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr

    assert HOSTED_INSTALLER.read_bytes() == INSTALLER.read_bytes()


def test_installer_uses_isolated_uv_tool_install_and_verifies_both_commands(tmp_path: Path):
    env, uv_log = _fake_tool_environment(tmp_path)

    result = subprocess.run(
        ["sh", str(INSTALLER)],
        cwd=tmp_path,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "superqode 0.test" in result.stdout
    assert "sq 0.test" in result.stdout
    assert "SuperQode is installed. Run: superqode" in result.stdout
    uv_calls = uv_log.read_text(encoding="utf-8")
    assert ("tool install --no-config --upgrade --force --with litellm<1.92 superqode") in uv_calls
    assert "tool dir --bin --no-config" in uv_calls


def test_installer_supports_explicit_extras_and_version_pin(tmp_path: Path):
    env, uv_log = _fake_tool_environment(tmp_path)
    env["SUPERQODE_EXTRAS"] = "tau,vendor-sdks"
    env["SUPERQODE_VERSION"] = "0.2.37"

    result = subprocess.run(
        ["sh", str(INSTALLER)],
        cwd=tmp_path,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert (
        "tool install --no-config --upgrade --force "
        "--with litellm<1.92 "
        "superqode[tau,vendor-sdks]==0.2.37"
    ) in uv_log.read_text(encoding="utf-8")


def test_installer_rejects_malformed_options_before_running_uv(tmp_path: Path):
    env, uv_log = _fake_tool_environment(tmp_path)
    env["SUPERQODE_EXTRAS"] = "tau;unexpected"

    result = subprocess.run(
        ["sh", str(INSTALLER)],
        cwd=tmp_path,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "SUPERQODE_EXTRAS may contain only" in result.stderr
    assert not uv_log.exists()


def test_installer_bootstraps_uv_when_it_is_missing(tmp_path: Path):
    command_bin = tmp_path / "commands"
    tool_bin = tmp_path / "tools"
    home_dir = tmp_path / "home"
    command_bin.mkdir()
    tool_bin.mkdir()
    uv_log = tmp_path / "uv.log"
    uv_template = tmp_path / "uv-template"
    bootstrap = tmp_path / "uv-bootstrap.sh"

    _write_executable(
        uv_template,
        """#!/bin/sh
printf '%s\\n' "$*" >> "$FAKE_UV_LOG"
if [ "$1" = "tool" ] && [ "$2" = "install" ]; then exit 0; fi
if [ "$1" = "tool" ] && [ "$2" = "dir" ]; then
    printf '%s\\n' "$FAKE_TOOL_BIN"
    exit 0
fi
exit 2
""",
    )
    bootstrap.write_text(
        """#!/bin/sh
mkdir -p "$HOME/.local/bin"
cp "$FAKE_UV_TEMPLATE" "$HOME/.local/bin/uv"
chmod +x "$HOME/.local/bin/uv"
""",
        encoding="utf-8",
    )
    _write_executable(
        command_bin / "curl",
        '#!/bin/sh\nprintf \'%s\\n\' "$*" >> "$FAKE_CURL_LOG"\ncat "$FAKE_BOOTSTRAP"\n',
    )
    _write_executable(tool_bin / "superqode", "#!/bin/sh\nprintf '%s\\n' 'superqode 0.test'\n")
    _write_executable(tool_bin / "sq", "#!/bin/sh\nprintf '%s\\n' 'sq 0.test'\n")
    curl_log = tmp_path / "curl.log"
    env = {
        **os.environ,
        "HOME": str(home_dir),
        "PATH": os.pathsep.join((str(command_bin), "/usr/bin", "/bin")),
        "FAKE_BOOTSTRAP": str(bootstrap),
        "FAKE_CURL_LOG": str(curl_log),
        "FAKE_TOOL_BIN": str(tool_bin),
        "FAKE_UV_LOG": str(uv_log),
        "FAKE_UV_TEMPLATE": str(uv_template),
        "SUPERQODE_UV_INSTALLER_URL": "https://example.test/uv-install.sh",
    }

    result = subprocess.run(
        ["sh", str(INSTALLER)],
        cwd=tmp_path,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "official Astral uv installer will run now" in result.stdout
    assert "-LsSf https://example.test/uv-install.sh" in curl_log.read_text(encoding="utf-8")
    assert (home_dir / ".local/bin/uv").is_file()

"""`superqode update` must match how SuperQode was actually installed.

Running ``uv tool upgrade`` inside a git checkout does nothing useful, and
``pip install --upgrade`` against a uv tool environment rebuilds it underneath
the running process. The command therefore dispatches on ``running_context()``.
"""

from __future__ import annotations

import sys

import pytest
from click.testing import CliRunner

from superqode.commands.update import is_newer, update, upgrade_command


@pytest.fixture
def runner():
    return CliRunner()


class TestUpgradeCommandMapping:
    def test_uv_tool_upgrades_in_place_to_keep_extras(self, monkeypatch):
        """`uv tool upgrade` keeps extras; reinstalling by name would drop them."""
        monkeypatch.setattr("superqode.commands.update.shutil.which", lambda _n: "/usr/bin/uv")

        assert upgrade_command("uv-tool") == ["uv", "tool", "upgrade", "superqode"]

    def test_uv_tool_pinned_version_forces_an_exact_install(self, monkeypatch):
        monkeypatch.setattr("superqode.commands.update.shutil.which", lambda _n: "/usr/bin/uv")

        assert upgrade_command("uv-tool", "0.2.62") == [
            "uv",
            "tool",
            "install",
            "--force",
            "superqode==0.2.62",
        ]

    @pytest.mark.parametrize("context", ["venv", "project", "system"])
    def test_environment_installs_target_the_running_interpreter(self, context, monkeypatch):
        """uv must be told which interpreter, or it resolves a different env."""
        monkeypatch.setattr("superqode.commands.update.shutil.which", lambda _n: "/usr/bin/uv")

        assert upgrade_command(context) == [
            "uv",
            "pip",
            "install",
            "--python",
            sys.executable,
            "--upgrade",
            "superqode",
        ]

    def test_pip_is_used_when_uv_is_absent(self, monkeypatch):
        monkeypatch.setattr("superqode.commands.update.shutil.which", lambda _n: None)

        assert upgrade_command("venv") == [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--upgrade",
            "superqode",
        ]

    def test_dev_checkout_has_no_upgrade_command(self, monkeypatch):
        """A checkout's source of truth is git, not an installed artifact."""
        monkeypatch.setattr("superqode.commands.update.shutil.which", lambda _n: "/usr/bin/uv")

        assert upgrade_command("dev-checkout") is None

    def test_uv_tool_without_uv_has_no_command(self, monkeypatch):
        monkeypatch.setattr("superqode.commands.update.shutil.which", lambda _n: None)

        assert upgrade_command("uv-tool") is None


class TestVersionComparison:
    @pytest.mark.parametrize(
        "candidate,current,expected",
        [
            ("0.2.63", "0.2.62", True),
            ("0.3.0", "0.2.62", True),
            ("0.2.62", "0.2.62", False),
            ("0.2.61", "0.2.62", False),
            ("0.2.9", "0.2.10", False),
        ],
    )
    def test_is_newer(self, candidate, current, expected):
        assert is_newer(candidate, current) is expected


class TestUpdateCommand:
    def _env(self, monkeypatch, context, *, latest="9.9.9"):
        from superqode.providers.env_introspect import EnvironmentInfo

        monkeypatch.setattr(
            "superqode.providers.env_introspect.environment_info",
            lambda: EnvironmentInfo(
                context=context,
                label=context,
                python=sys.executable,
                prefix="/tmp",
                project_root="/tmp/checkout",
            ),
        )
        monkeypatch.setattr(
            "superqode.commands.update.latest_released_version", lambda timeout=10.0: latest
        )

    def test_check_never_installs_anything(self, runner, monkeypatch):
        self._env(monkeypatch, "uv-tool")

        def explode(*_a, **_k):  # pragma: no cover - must not run
            raise AssertionError("--check must not run a subprocess")

        monkeypatch.setattr("superqode.commands.update.subprocess.run", explode)

        result = runner.invoke(update, ["--check"])

        assert result.exit_code == 0
        assert "An update is available" in result.output

    def test_dev_checkout_refuses_and_points_at_git(self, runner, monkeypatch):
        self._env(monkeypatch, "dev-checkout")

        def explode(*_a, **_k):  # pragma: no cover - must not run
            raise AssertionError("a checkout must never be pip-installed over")

        monkeypatch.setattr("superqode.commands.update.subprocess.run", explode)

        result = runner.invoke(update, ["--yes"])

        assert result.exit_code == 1
        assert "git pull" in result.output

    def test_up_to_date_does_nothing(self, runner, monkeypatch):
        from superqode import __version__

        self._env(monkeypatch, "uv-tool", latest=__version__)

        def explode(*_a, **_k):  # pragma: no cover - must not run
            raise AssertionError("nothing to install when already current")

        monkeypatch.setattr("superqode.commands.update.subprocess.run", explode)

        result = runner.invoke(update, ["--yes"])

        assert result.exit_code == 0
        assert "Already on the latest version" in result.output

    def test_successful_update_runs_the_mapped_command(self, runner, monkeypatch):
        import subprocess

        self._env(monkeypatch, "uv-tool")
        monkeypatch.setattr("superqode.commands.update.shutil.which", lambda _n: "/usr/bin/uv")
        seen = {}

        def fake_run(argv, **_kwargs):
            seen["argv"] = argv
            return subprocess.CompletedProcess(argv, 0)

        monkeypatch.setattr("superqode.commands.update.subprocess.run", fake_run)

        result = runner.invoke(update, ["--yes"])

        assert result.exit_code == 0
        assert seen["argv"] == ["uv", "tool", "upgrade", "superqode"]
        assert "Restart superqode" in result.output

    def test_failed_update_propagates_the_exit_code(self, runner, monkeypatch):
        import subprocess

        self._env(monkeypatch, "uv-tool")
        monkeypatch.setattr("superqode.commands.update.shutil.which", lambda _n: "/usr/bin/uv")
        monkeypatch.setattr(
            "superqode.commands.update.subprocess.run",
            lambda argv, **_k: subprocess.CompletedProcess(argv, 3),
        )

        result = runner.invoke(update, ["--yes"])

        assert result.exit_code == 3
        assert "Update failed" in result.output

    def test_offline_still_attempts_the_update(self, runner, monkeypatch):
        """A private index or offline mirror must keep working."""
        import subprocess

        self._env(monkeypatch, "uv-tool", latest=None)
        monkeypatch.setattr("superqode.commands.update.shutil.which", lambda _n: "/usr/bin/uv")
        seen = {}

        def fake_run(argv, **_kwargs):
            seen["argv"] = argv
            return subprocess.CompletedProcess(argv, 0)

        monkeypatch.setattr("superqode.commands.update.subprocess.run", fake_run)

        result = runner.invoke(update, ["--yes"])

        assert result.exit_code == 0
        assert "unavailable" in result.output
        assert seen["argv"] == ["uv", "tool", "upgrade", "superqode"]

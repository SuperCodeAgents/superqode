"""Regression tests for the fast ``:diagnostics`` TUI command."""

from __future__ import annotations

from pathlib import Path

from superqode.app.mixins.slash_commands import SlashCommandMixin
from superqode.app.widgets import ConversationLog
from superqode.app_main import SuperQodeApp
from superqode.tools.diagnostics import quick_diagnostics


class _Log:
    def __init__(self) -> None:
        self.output = ""

    def add_error(self, message: str) -> None:
        self.output += f"ERROR: {message}\n"

    def add_info(self, message: str) -> None:
        self.output += f"INFO: {message}\n"

    def add_success(self, message: str) -> None:
        self.output += f"SUCCESS: {message}\n"


class _App:
    def _show_command_output(self, log: _Log, content, clear_log: bool = True) -> None:
        log.output += content.plain


def test_quick_diagnostics_reports_python_syntax_error(tmp_path: Path) -> None:
    source = tmp_path / "broken.py"
    source.write_text("def broken(:\n    pass\n", encoding="utf-8")

    diagnostics = quick_diagnostics(source)

    assert len(diagnostics) == 1
    assert diagnostics[0]["severity"] == "error"
    assert diagnostics[0]["file"] == str(source)
    assert diagnostics[0]["line"] == 1


def test_tui_diagnostics_renders_instead_of_import_crashing(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "broken.py"
    source.write_text("if True print('broken')\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    log = _Log()

    SlashCommandMixin._handle_diagnostics(_App(), ".", log)

    assert "Diagnostics for ." in log.output
    assert "broken.py:1:" in log.output
    assert "Fast scan only" in log.output


def test_tui_diagnostics_skips_dependency_directories(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "good.py").write_text("value = 1\n", encoding="utf-8")
    dependency = tmp_path / ".venv"
    dependency.mkdir()
    (dependency / "broken.py").write_text("def broken(:\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    log = _Log()

    SlashCommandMixin._handle_diagnostics(_App(), ".", log)

    assert "No fast syntax diagnostics found" in log.output
    assert "(1 file(s) checked)" in log.output


async def test_mounted_tui_diagnostics_command_renders_result(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "broken.py").write_text("def broken(:\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    app = SuperQodeApp()

    async with app.run_test(size=(90, 32)) as pilot:
        log = app.query_one("#log", ConversationLog)
        app._handle_command(":diagnostics broken.py", log)
        await pilot.pause()

        rendered = "\n".join(line.text for line in log.lines)
        assert "Diagnostics for broken.py" in rendered
        assert "broken.py:1:" in rendered

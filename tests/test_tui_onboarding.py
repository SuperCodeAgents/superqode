"""First-run onboarding should persist only after a successful connection."""

from __future__ import annotations

from pathlib import Path

from superqode.app.mixins.helper_startup import HelperStartupMixin


class _Log:
    def __init__(self) -> None:
        self.items: list[object] = []

    def write(self, value) -> None:
        self.items.append(value)


class _Startup(HelperStartupMixin):
    def __init__(self, marker: Path) -> None:
        self.marker = marker

    def _onboarding_marker(self) -> Path:
        return self.marker


def test_onboarding_remains_until_connection_is_completed(tmp_path: Path) -> None:
    app = _Startup(tmp_path / ".superqode" / ".onboarded")
    first_log = _Log()
    second_log = _Log()

    app._maybe_show_onboarding(first_log)
    app._maybe_show_onboarding(second_log)

    assert first_log.items
    assert second_log.items
    assert not app.marker.exists()

    app._mark_onboarding_complete()
    completed_log = _Log()
    app._maybe_show_onboarding(completed_log)

    assert app.marker.read_text(encoding="utf-8") == "1"
    assert completed_log.items == []

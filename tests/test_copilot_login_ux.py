"""Sign-in must be visible, and the one-time code must not need retyping.

Three failures reported from real use: no way to tell whether the Copilot CLI
was signed in (so the user signed in again needlessly), the device code had to
be transcribed by hand out of a scrolling log, and a completed sign-in produced
only a log line that had already scrolled away.
"""

from __future__ import annotations

import asyncio

import pytest

from superqode.providers.copilot_auth import CopilotLoginState, probe_copilot_login
from superqode.providers.subscription_login import extract_device_codes


class TestLoginStateProbe:
    def test_missing_cli_is_reported_as_undetermined_not_signed_out(self, monkeypatch):
        """Absent tooling is not evidence about the account."""
        monkeypatch.setattr("superqode.providers.copilot_auth.shutil.which", lambda _n: None)

        state = asyncio.run(probe_copilot_login())

        assert state.signed_in is False
        assert state.needs_login is False
        assert state.determined is False
        assert "not on PATH" in state.detail

    def test_explicit_token_counts_as_signed_in_without_starting_a_process(self, monkeypatch):
        monkeypatch.setattr(
            "superqode.providers.copilot_auth.shutil.which", lambda _n: "/usr/bin/copilot"
        )
        monkeypatch.setenv("COPILOT_GITHUB_TOKEN", "explicit")

        state = asyncio.run(probe_copilot_login())

        assert state.signed_in is True
        assert "COPILOT_GITHUB_TOKEN" in state.detail

    def test_the_probe_never_leaks_a_credential_value(self, monkeypatch):
        monkeypatch.setattr(
            "superqode.providers.copilot_auth.shutil.which", lambda _n: "/usr/bin/copilot"
        )
        monkeypatch.setenv("COPILOT_GITHUB_TOKEN", "super-secret-value")

        state = asyncio.run(probe_copilot_login())

        assert "super-secret-value" not in state.detail

    @pytest.mark.parametrize(
        "signed_in,needs_login,determined",
        [(True, False, True), (False, True, True), (False, False, False)],
    )
    def test_determined_only_when_a_state_was_established(self, signed_in, needs_login, determined):
        state = CopilotLoginState(signed_in=signed_in, needs_login=needs_login, detail="")

        assert state.determined is determined


class TestDeviceCodeExtraction:
    @pytest.mark.parametrize(
        "line,expected",
        [
            ("Please enter the code ABCD-1234 at https://github.com/login/device", "ABCD-1234"),
            ("First copy your one-time code: 9F2C-77AB", "9F2C-77AB"),
            ("Open https://github.com/login/device and enter XYZ9-QWE1", "XYZ9-QWE1"),
        ],
    )
    def test_codes_are_found_in_real_cli_output(self, line, expected):
        assert expected in extract_device_codes(line)


class TestClipboardAndToast:
    def _app(self):
        from superqode.app.mixins.helpers import HelpersMixin

        class Stub(HelpersMixin):
            def __init__(self):
                self.toasts = []
                self.clipboard_calls = []

            def copy_to_clipboard(self, value):
                self.clipboard_calls.append(value)

            def notify(self, message, title="", severity="information", timeout=None):
                self.toasts.append((title, message, severity))

        return Stub()

    def test_copy_uses_the_terminal_clipboard_path(self, monkeypatch):
        """Textual's OSC 52 path matters: it reaches the outer terminal over SSH."""
        app = self._app()
        monkeypatch.setitem(__import__("sys").modules, "pyperclip", None)

        app._copy_text_to_clipboard("ABCD-1234")

        assert "ABCD-1234" in app.clipboard_calls

    def test_empty_text_is_never_copied(self):
        app = self._app()

        assert app._copy_text_to_clipboard("") is False
        assert app.clipboard_calls == []

    def test_toast_failure_never_breaks_the_caller(self):
        from superqode.app.mixins.helpers import HelpersMixin

        class Exploding(HelpersMixin):
            def notify(self, *_a, **_k):
                raise RuntimeError("no notification system")

        # Reporting must never be the thing that breaks the action.
        Exploding()._toast("title", "body")

    def test_toast_carries_title_and_severity(self):
        app = self._app()

        app._toast("Signed in to GitHub Copilot", "Connecting now.", severity="information")

        assert app.toasts == [("Signed in to GitHub Copilot", "Connecting now.", "information")]

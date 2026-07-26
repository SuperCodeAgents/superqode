"""A single place for the TUI's modal prompts to declare their behavior.

Every inline prompt in the TUI (pickers, confirmations, install offers) has to
answer the same five questions: what does Enter do, what does a typed answer do,
what does Esc do, how do arrow keys move, and what do the number keys select.

Historically each prompt answered those by setting an ``_awaiting_*`` flag and
then being hand-registered in five separate dispatch sites. Missing one produced
a prompt that could not be cancelled, whose arrow keys did nothing, or whose
Enter was swallowed by a stale picker underneath it.

A ``PromptSpec`` answers all five questions once, and ``PromptStack`` routes the
keys. Prompts registered here cannot be partially wired.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

__all__ = ["PromptSpec", "PromptStack"]


@dataclass(frozen=True)
class PromptSpec:
    """Everything the TUI needs to know to drive one modal prompt.

    ``kind="picker"`` prompts have a highlighted row moved by arrow keys and
    chosen with Enter or a number. ``kind="text"`` prompts read a typed answer
    and treat Enter on an empty input as accepting the default.
    """

    name: str
    kind: str = "picker"
    #: Returns the current choices. Picker prompts must supply this.
    options: Callable[[], Sequence[Any]] | None = None
    #: Called with the chosen option when Enter or a number key selects it.
    on_select: Callable[[Any], None] | None = None
    #: Called with typed text. Returns True when the prompt handled it.
    on_text: Callable[[str], bool] | None = None
    #: Called when Esc or :cancel dismisses the prompt.
    on_cancel: Callable[[], None] | None = None
    #: Redraws the prompt after the highlight moves.
    render: Callable[[], None] | None = None
    #: Arbitrary per-prompt state (the runtime being installed, and so on).
    data: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in {"picker", "text"}:
            raise ValueError(f"Unknown prompt kind: {self.kind!r}")
        if self.kind == "picker" and self.options is None:
            raise ValueError(f"Picker prompt {self.name!r} must supply options")
        if self.kind == "text" and self.on_text is None:
            raise ValueError(f"Text prompt {self.name!r} must supply on_text")


class PromptStack:
    """Holds the active prompt and routes keys to it.

    A stack rather than a single slot because prompts genuinely nest: a missing
    dependency prompt opens on top of the runtime picker and must return to it
    on cancel.
    """

    def __init__(self) -> None:
        self._stack: list[PromptSpec] = []
        self._indexes: dict[str, int] = {}

    # -- lifecycle ---------------------------------------------------------

    def push(self, spec: PromptSpec) -> None:
        """Make ``spec`` the active prompt."""
        self._stack.append(spec)
        self._indexes.setdefault(spec.name, 0)

    def pop(self) -> PromptSpec | None:
        """Remove the active prompt without running its cancel hook."""
        if not self._stack:
            return None
        spec = self._stack.pop()
        self._indexes.pop(spec.name, None)
        return spec

    def clear(self) -> None:
        """Drop every prompt, e.g. when navigating home."""
        self._stack.clear()
        self._indexes.clear()

    @property
    def active(self) -> PromptSpec | None:
        return self._stack[-1] if self._stack else None

    def is_active(self, name: str) -> bool:
        active = self.active
        return active is not None and active.name == name

    # -- selection state ---------------------------------------------------

    @property
    def index(self) -> int:
        active = self.active
        return self._indexes.get(active.name, 0) if active else 0

    def set_index(self, value: int) -> None:
        active = self.active
        if active is None:
            return
        self._indexes[active.name] = max(0, min(value, self._option_count() - 1))

    def _option_count(self) -> int:
        active = self.active
        if active is None or active.options is None:
            return 0
        return len(list(active.options()))

    # -- key routing -------------------------------------------------------

    def navigate(self, delta: int) -> bool:
        """Move the highlight. Returns True when the prompt consumed the key."""
        active = self.active
        if active is None or active.kind != "picker":
            return False
        count = self._option_count()
        if count == 0:
            return False
        previous = self.index
        self.set_index(previous + delta)
        if self.index != previous and active.render is not None:
            active.render()
        return True

    def select(self) -> bool:
        """Choose the highlighted option (Enter)."""
        active = self.active
        if active is None:
            return False
        if active.kind == "text":
            return bool(active.on_text("")) if active.on_text else False
        return self.select_index(self.index)

    def select_index(self, index: int) -> bool:
        """Choose an option by position (number keys)."""
        active = self.active
        if active is None or active.kind != "picker" or active.options is None:
            return False
        options = list(active.options())
        if not (0 <= index < len(options)):
            return False
        # Pop before dispatching: the handler often opens the next prompt, and
        # it must not be buried underneath the one it is replacing.
        self.pop()
        if active.on_select is not None:
            active.on_select(options[index])
        return True

    def handle_text(self, text: str) -> bool:
        """Route a typed answer. Returns True when the prompt consumed it."""
        active = self.active
        if active is None:
            return False
        if active.on_text is not None:
            return bool(active.on_text(text))
        # A picker with no text handler still accepts a number.
        stripped = text.strip()
        if stripped.isdigit():
            return self.select_index(int(stripped) - 1)
        return False

    def cancel(self) -> bool:
        """Dismiss the active prompt (Esc). Returns True when one was open."""
        active = self.active
        if active is None:
            return False
        self.pop()
        if active.on_cancel is not None:
            active.on_cancel()
        return True

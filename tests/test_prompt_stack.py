"""Contract tests for the modal-prompt registry.

The bugs this replaces were all the same shape: a prompt wired into some of the
dispatch sites but not all of them, so it could not be cancelled, its arrow keys
did nothing, or Enter reached a stale picker underneath it. These tests pin the
contract that makes those states unreachable.
"""

from __future__ import annotations

import pytest

from superqode.app.prompt_stack import PromptSpec, PromptStack


def _picker(name: str, *, options=("a", "b", "c"), **kwargs) -> PromptSpec:
    return PromptSpec(name=name, kind="picker", options=lambda: list(options), **kwargs)


def test_picker_requires_options():
    with pytest.raises(ValueError, match="must supply options"):
        PromptSpec(name="broken", kind="picker")


def test_text_prompt_requires_a_text_handler():
    with pytest.raises(ValueError, match="must supply on_text"):
        PromptSpec(name="broken", kind="text")


def test_unknown_kind_is_rejected():
    with pytest.raises(ValueError, match="Unknown prompt kind"):
        PromptSpec(name="broken", kind="modal", options=list)


def test_every_prompt_is_cancellable():
    """The invariant that was impossible to state before the registry."""
    cancelled = []
    stack = PromptStack()

    for kind_spec in (
        _picker("picker", on_cancel=lambda: cancelled.append("picker")),
        PromptSpec(
            name="text",
            kind="text",
            on_text=lambda text: True,
            on_cancel=lambda: cancelled.append("text"),
        ),
    ):
        stack.push(kind_spec)
        assert stack.active is kind_spec
        assert stack.cancel() is True
        assert stack.active is None

    assert cancelled == ["picker", "text"]


def test_cancel_with_nothing_open_is_a_no_op():
    assert PromptStack().cancel() is False


def test_navigation_moves_the_highlight_and_redraws():
    renders = []
    stack = PromptStack()
    stack.push(_picker("p", render=lambda: renders.append(True)))

    assert stack.index == 0
    assert stack.navigate(1) is True
    assert stack.index == 1
    assert len(renders) == 1

    stack.navigate(-1)
    assert stack.index == 0


def test_navigation_clamps_at_both_ends():
    """A highlight that runs off the list is how pickers get stuck."""
    stack = PromptStack()
    stack.push(_picker("p"))

    for _ in range(10):
        stack.navigate(1)
    assert stack.index == 2  # three options

    for _ in range(10):
        stack.navigate(-1)
    assert stack.index == 0


def test_redraw_does_not_reset_the_highlight():
    """Regression: re-rendering a prompt used to snap the selection back to 0."""
    stack = PromptStack()
    spec = _picker("p")
    stack.push(spec)
    stack.navigate(1)
    stack.navigate(1)

    assert stack.index == 2
    if spec.render is not None:
        spec.render()
    assert stack.index == 2


def test_enter_selects_the_highlighted_option():
    chosen = []
    stack = PromptStack()
    stack.push(_picker("p", on_select=chosen.append))

    stack.navigate(1)
    assert stack.select() is True

    assert chosen == ["b"]
    assert stack.active is None, "selecting must close the prompt"


def test_number_keys_select_by_position():
    chosen = []
    stack = PromptStack()
    stack.push(_picker("p", on_select=chosen.append))

    assert stack.select_index(2) is True
    assert chosen == ["c"]


def test_out_of_range_number_leaves_the_prompt_open():
    chosen = []
    stack = PromptStack()
    stack.push(_picker("p", on_select=chosen.append))

    assert stack.select_index(9) is False
    assert chosen == []
    assert stack.active is not None


def test_prompt_is_popped_before_its_handler_runs():
    """A handler that opens the next prompt must not be buried by this one."""
    stack = PromptStack()
    seen_during_handler = []

    def on_select(_option):
        seen_during_handler.append(stack.active)
        stack.push(_picker("second"))

    stack.push(_picker("first", on_select=on_select))
    stack.select()

    assert seen_during_handler == [None], "the old prompt was still active"
    assert stack.is_active("second")


def test_prompts_nest_and_unwind_in_order():
    """A dependency prompt opens over the runtime picker and returns to it."""
    stack = PromptStack()
    stack.push(_picker("runtime"))
    stack.push(_picker("dependency"))

    assert stack.is_active("dependency")
    stack.cancel()
    assert stack.is_active("runtime")
    stack.cancel()
    assert stack.active is None


def test_typed_text_reaches_the_active_prompt():
    seen = []
    stack = PromptStack()
    stack.push(
        PromptSpec(
            name="text",
            kind="text",
            on_text=lambda value: (seen.append(value), True)[1],
        )
    )

    assert stack.handle_text("hello") is True
    assert seen == ["hello"]


def test_typed_number_selects_in_a_picker_without_a_text_handler():
    chosen = []
    stack = PromptStack()
    stack.push(_picker("p", on_select=chosen.append))

    assert stack.handle_text("2") is True
    assert chosen == ["b"]


def test_clear_drops_everything():
    stack = PromptStack()
    stack.push(_picker("one"))
    stack.push(_picker("two"))

    stack.clear()

    assert stack.active is None
    assert stack.cancel() is False

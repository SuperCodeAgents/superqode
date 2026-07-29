"""Regression contract for the public Click command tree."""

from __future__ import annotations

import hashlib

import click

from superqode.main import cli_main


EXPECTED_COMMAND_COUNT = 261
# Rebaselined when the GitHub Copilot CLI route returned to the Connect picker:
# the --connect choice list gained copilot-cli. No command was added, renamed,
# or removed, so EXPECTED_COMMAND_COUNT is unchanged.
EXPECTED_HELP_TREE_SHA256 = "aa36d63849da1a936c5ea6cf4881149a5afeffe4aa3ab1e4ba4a466af1595abd"


def _render_help_tree() -> tuple[int, str]:
    """Render every help page in Click registration order without invoking callbacks."""
    blocks: list[str] = []

    def visit(command: click.Command, context: click.Context, path: tuple[str, ...]) -> None:
        blocks.append(f"$ {' '.join((*path, '--help'))}\n{command.get_help(context)}")
        if not isinstance(command, click.Group):
            return
        for name, child in command.commands.items():
            child_context = click.Context(child, info_name=name, parent=context)
            visit(child, child_context, (*path, name))

    root_context = click.Context(cli_main, info_name="superqode")
    visit(cli_main, root_context, ("superqode",))
    payload = "\n".join(blocks).encode()
    return len(blocks), hashlib.sha256(payload).hexdigest()


def test_cli_help_tree_matches_refactor_baseline():
    """Commands, ordering, options, and rendered help must remain byte-identical."""
    command_count, help_digest = _render_help_tree()

    assert command_count == EXPECTED_COMMAND_COUNT
    assert help_digest == EXPECTED_HELP_TREE_SHA256

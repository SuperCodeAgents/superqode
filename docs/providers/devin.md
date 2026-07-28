# Devin

Devin is Cognition's coding agent. The Devin CLI is proprietary and ships as a
prebuilt binary with no embeddable SDK, so ACP is the supported integration
path. SuperQode starts its native ACP server and provides the terminal,
sessions, harness switching, approvals, and a normalized event stream.

## Install And Authenticate

```bash
# macOS / Linux / WSL
curl -fsSL https://cli.devin.ai/install.sh | bash

# macOS (Homebrew)
brew install --cask devin-cli
```

On Windows use the installer or PowerShell. The install script does not work
under Git Bash or CMD. Devin Desktop already bundles the CLI for Enterprise
users. Restart your terminal after installing so `devin` lands on PATH.

Devin owns its own sign-in. SuperQode never reads, copies, or refreshes Devin
tokens:

```bash
devin auth login
devin auth status
```

Verify that SuperQode can discover it:

```bash
superqode agents show devin
superqode agents doctor devin
```

## Connect From The TUI

Devin is listed on the Subscriptions screen of the connect picker:

```text
:connect subscriptions
```

Or connect directly:

```text
:connect devin
```

Both routes start `devin acp`. The generic ACP path stays available as
`:connect acp devin`, and `:runtime devin-cli` uses the plain CLI handoff
instead of the ACP session.

## Models

Devin CLI is model-agnostic and routes to Anthropic, OpenAI, Google, and
Cognition's own SWE models. Short names such as `opus`, `sonnet`, `gpt`,
`codex`, `gemini`, and `swe` resolve to the newest release in that family. The
choice belongs to the CLI, so set it before connecting:

```bash
devin --model opus
```

Or set a default in `~/.config/devin/config.json`:

```json
{ "agent": { "model": "swe-1-6-fast" } }
```

## Permissions

Devin applies its own permission layer underneath ACP. `--permission-mode`
accepts `normal`, `dangerous`, and `bypass`, and the config file takes
`permissions.allow`, `deny`, and `ask` rules such as `Read(**)` or
`Exec(sudo)`. SuperQode's approval prompts still apply on top of whatever Devin
allows.

## Related Documentation

- [Connection Methods and Vendors](../concepts/modes.md)
- [ACP Agent Catalog](acp.md)
- [Agent Runtimes](../runtimes.md)

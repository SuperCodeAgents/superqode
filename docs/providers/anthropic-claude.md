# Anthropic Claude

SuperQode connects to Claude through the Claude Agent SDK or the Anthropic BYOK
provider. Both routes use Anthropic API credentials.

## Connection routes

| Route | Primary command | Authentication | Harness owner |
| --- | --- | --- | --- |
| Claude Agent SDK | `:runtime claude-agent-sdk` | `ANTHROPIC_API_KEY` | Claude Agent SDK |
| Anthropic BYOK | `:connect byok anthropic <model>` | `ANTHROPIC_API_KEY` | SuperQode |

Claude Pro and Max are not offered in SuperQode's Subscriptions picker.
Anthropic scopes those plans to its first-party Claude experiences and bills
Console/API usage separately. Use Claude Code directly for subscription usage;
use one of the API-key routes below when connecting through SuperQode.

## Claude Agent SDK route

Install the optional runtime and set the Anthropic API key:

```bash
uv tool install "superqode[claude-agent-sdk]"
export ANTHROPIC_API_KEY="your-key"
```

Connect in the TUI:

```text
:runtime claude-agent-sdk
```

Run a headless task:

```bash
superqode --runtime claude-agent-sdk --print "review the current changes"
```

The SDK owns
the inner agent loop. SuperQode supplies the terminal, HarnessSpec context,
policy, evidence, evaluation, WorkOrder, and session controls supported by the
runtime adapter.

## SuperQode harness with Anthropic models

Use the Anthropic BYOK route when SuperQode should own the harness:

```text
:connect byok anthropic <model>
:harness core
```

The active HarnessSpec controls tools, memory, approvals, sandbox policy,
workflow, evidence, and evaluation.

## Troubleshooting

Check the SDK and API key:

```bash
superqode runtime doctor claude-agent-sdk
superqode providers doctor anthropic
```

## Related references

- [Connection overview](../concepts/modes.md)
- [ACP agents](acp.md)
- [BYOK providers](byok.md)
- [Harness system](../advanced/harness-system.md)

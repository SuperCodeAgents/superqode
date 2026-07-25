# Hugging Face Tau Integration

SuperQode treats [Hugging Face Tau](https://github.com/huggingface/tau) as an
optional harness, not as the main execution layer. Tau keeps ownership of its
provider-neutral agent loop and append-only session, while SuperQode normalizes
progress into Harness Protocol events and records it in the existing evidence
store.

## Install and select

```bash
uv tool install "superqode[tau]"
```

In the TUI, open `:harness` and select **Tau (Hugging Face)**. The entry remains
visible when the extra is missing and shows an installation command appropriate
for the environment running SuperQode. Tau appears on the first harness page,
and setup-aware completion works before installation:

```text
:harness ta
:harness switch ta
```

From the root `:connect` picker, press `H` to open the harness catalog.

Tau uses its own provider catalog and credentials. Configure those with Tau
before selecting the harness:

```bash
tau
/login
/model
```

The selected SuperQode provider/model must also be a valid Tau provider/model
pair. Tau's saved credentials take precedence over its provider environment
variable.

## Current safety boundary

The maintained `tau` preset is intentionally read-only. It gives Tau its
`read` tool but withholds `write`, `edit`, and `bash` because those native tools
do not yet participate in SuperQode's approval and sandbox policy.

Do not make Tau the default/main layer yet. Keep it as a canary integration
until a tool-governance bridge can enforce SuperQode permission decisions before
Tau executes a mutation.

## Event and session mapping

| Tau event or state | SuperQode representation |
| --- | --- |
| text delta | `message.delta` |
| thinking delta | `model.thinking` |
| tool start/end | `tool.requested` / `tool.completed` |
| final assistant message | `message.created` |
| settled agent + usage | `model.completed` |
| provider failure | `run.failed` |
| JSONL session | `.superqode/tau/sessions/<session-id>.jsonl` |
| steering / cancellation | Harness Protocol `steer` / `cancel` |

Tau is not pulled from models.dev because that service catalogs models and
providers, not agent harnesses. Tau is also not currently listed as an ACP
agent. SuperQode therefore discovers it as a pinned optional Python dependency
and direct Harness Protocol adapter.

## Next adoption gates

Before enabling coding mode by default:

1. Wrap Tau tool execution with SuperQode approval and sandbox policy.
2. Add provider/model alias mapping between the two catalogs.
3. Run write/edit/bash conformance tests in an isolated worktree.
4. Track upstream pre-1.0 compatibility and update the current
   `tau-ai>=0.3.3,<0.4` pin deliberately.
5. Consider contributing an ACP server upstream if Tau adopts ACP; do not create
   a private pseudo-ACP dialect in SuperQode.

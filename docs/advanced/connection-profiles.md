# Connection Profiles

Connection profiles determine how SuperQode connects to model providers and
agent runtimes. Each profile has a connector type, optional runtime, local
availability check, and the menu it appears on.

Profiles are split across two screens. The root screen holds the three ways
SuperQode's own harness runs a model plus two submenus. The subscriptions
screen holds the vendor coding agents. Every profile stays reachable by name
regardless of the screen it appears on, so `:connect codex` never requires a
detour through the submenu.

## Root Screen (`:connect`)

### 1. Local (connector: local, runtime: builtin)

Connects to local/self-hosted model servers. Opens a local provider picker (Ollama, MLX, LM Studio, vLLM, SGLang, TGI, DS4). Always available.

### 2. ACP (Agent Client Protocol) (connector: acp-picker)

Opens an interactive picker showing all discovered ACP agents. Always available. No model auth setup is needed before browsing the catalog.

### 3. BYOK (Bring Your Own Key) (connector: byok, runtime: builtin)

Brings your own API key. Opens a cloud provider picker, then model selector. Uses builtin runtime. detect() checks for configured provider credentials.

### 4. Subscriptions (connector: subscription-picker)

Opens the vendor screen below. Always available. Esc returns to the root
screen.

### 5. Other Harnesses (connector: harness-picker)

Opens a focused list of optional harness integrations that are neither main
connection profiles nor ACP agents. Hugging Face Tau appears here with its live
installation status.

## Subscriptions Screen (`:connect subscriptions`)

### Codex Subscription (connector: runtime, runtime: codex-sdk)

Self-contained: brings its own model and auth via Codex login. Requires openai_codex package and ~/.codex/auth.json. Auto-connects on selection.

### Claude Agent SDK (connector: runtime, runtime: claude-agent-sdk)

Self-contained: uses Anthropic API key directly. Requires claude_agent_sdk package and ANTHROPIC_API_KEY. Auto-connects on selection.

### Antigravity CLI (connector: runtime)

Handoff profile: shows the command to run `agy` in a terminal. Does not connect SuperQode's own loop. Requires agy binary on PATH.

### Grok Subscription (connector: acp, agent: grok)

Runs **Grok Build**, xAI's own coding agent, on an eligible SuperGrok or X Premium+ account. This matches the Codex and Claude subscription profiles: the vendor's agent owns the loop. Requires the `grok` binary on PATH and a local `grok login` (`~/.grok/auth.json`). SuperQode starts `grok agent stdio` over ACP.

To run **SuperQode's own harness** on the same subscription instead, use `:grok api [model]`. That imports the CLI session token into SuperQode's auth store and routes through the `grok-cli` provider (CLI chat proxy), so `core`/`workbench` and SuperQode's tools drive Grok 4.5.

### GitHub Copilot SDK (connector: runtime, runtime: copilot-sdk)

Uses the official GitHub Copilot SDK with the signed-in Copilot account or an
explicit GitHub token. Requires the optional `copilot-sdk` extra.

### Gemini CLI (connector: acp, agent: gemini)

Runs Google's Gemini CLI through `gemini --acp`. Requires the `gemini` command
and either its sign-in or `GEMINI_API_KEY`. Consumer Google AI accounts should
use Antigravity instead.

### Devin (connector: acp, agent: devin)

Runs Cognition's Devin CLI through `devin acp`. Requires the `devin` command
and a completed `devin auth login`. Devin owns its own credential store.

### GLM CLI (connector: acp, agent: glm)

Runs the community `glm-acp-agent` CLI, which uses GLM models as its reasoning
engine. It is not a first-party Z.ai client.

### Z.AI GLM API (connector: byok, runtime: builtin)

Uses the Z.AI general API through the builtin SuperQode harness. Requires
`ZAI_API_KEY`.

### Qwen Code (connector: acp, agent: qwen)

Runs QwenLM's first-party Qwen Code agent through its stable ACP mode. Requires
the `qwen` command and authentication from `qwen auth`.

### Kimi Code (connector: acp, agent: kimi)

Runs Moonshot AI's first-party Kimi Code agent through `kimi acp`. Requires the
`kimi` command and a completed Kimi Code `/login`.

## TUI Usage

In the TUI, use `:connect` to open the root screen. Each profile shows
availability status. Navigate with arrows or number keys. Enter on
**Subscriptions** opens the vendor screen, and Esc there returns to the root
screen instead of leaving the flow. `H` still opens the Other Harnesses picker
from the root screen.

Direct shortcuts:

- `:connect subscriptions` - open the vendor screen
- `:connect codex` - connect Codex SDK directly
- `:connect gemini-cli` - Google Gemini CLI over ACP
- `:connect devin` - Cognition Devin CLI over ACP
- `:connect glm-cli` - community GLM ACP agent
- `:connect copilot` - connect through the official GitHub Copilot SDK
- `:connect acp copilot` - advanced Copilot CLI ACP compatibility path
- `:connect other-harnesses` - browse optional non-ACP harnesses such as Tau
- `:copilot models` - list models available to the signed-in Copilot account
- `:connect claude` - connect Claude Agent SDK directly
- `:connect antigravity` - use `agy` headless mode with its Google Sign-In/keyring
- `:connect byok google` - use a Google API key through the BYOK path
- `:runtime antigravity-sdk` - optional direct Antigravity SDK/API-key runtime
- `:connect grok` - Grok Build, xAI's own coding agent, on your subscription (ACP)
- `:grok api [model]` - SuperQode's harness on the same subscription (opt-in)
- `:connect qwen-code` - QwenLM's first-party Qwen Code agent over ACP
- `:connect kimi-code` - Moonshot AI's first-party Kimi Code agent over ACP
- `:connect byok` - open the cloud provider picker
- `:connect byok <provider>/<model>` - connect to a cloud model directly
- `:connect <model>` - connect by model name alone (e.g. `:connect gpt-5.6`); the provider is resolved from the catalog, preferring first-party providers over gateway mirrors
- `:connect local` - open the local provider picker
- `:connect local <provider>/<model>` - connect to a local model directly
- `:connect acp` - open the ACP agent picker
- `:connect acp <agent>` - connect to an ACP agent directly

Special syntax: `:connect byok -` (previous), `:connect byok !` (history), `:connect byok last` (reconnect).

## CLI Usage

Use `--connect` / `-C` global flag:

```bash
superqode --connect codex --print "review this"
superqode --connect copilot --print "review this"
superqode --connect acp copilot
superqode -C claude --print "summarize changes"
superqode --connect grok
```

Use `superqode connect` subcommands:

```bash
superqode connect acp opencode
superqode connect byok anthropic <anthropic-model>
superqode connect local ollama qwen3:8b
superqode connect setup deepseek --json
```

## Runtime Mapping

- Codex profile -> runtime: codex-sdk
- GitHub Copilot SDK profile -> runtime: copilot-sdk
- GitHub Copilot ACP compatibility route -> ACP subprocess: copilot --acp --stdio
- Claude profile -> runtime: claude-agent-sdk
- BYOK/Local -> runtime: builtin
- ACP -> no runtime change (ACP subprocess)
- Antigravity -> handoff (no runtime)
- Grok subscription (`:connect grok`) -> Grok Build ACP subprocess (`grok agent stdio`)
- Grok via SuperQode harness (`:grok api`) -> `grok-cli` provider + CLI session token
- Qwen Code -> Qwen Code ACP subprocess (`qwen --acp`)
- Kimi Code -> Kimi Code ACP subprocess (`kimi acp`)
- Advanced -> user picks runtime

When --connect implies a runtime, it sets SUPERQODE_RUNTIME but does not override an explicit --runtime flag.

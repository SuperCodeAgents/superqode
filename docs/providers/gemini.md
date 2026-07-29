# Gemini CLI

Gemini CLI is Google's own coding agent and the reference ACP implementation.
SuperQode connects to its ACP server, so Gemini CLI keeps its agent loop while
SuperQode provides the terminal, sessions, harness switching, policy, and a
normalized event stream.

!!! note "Consumer accounts move to Antigravity"
    Google is migrating Google AI Pro, Ultra, and free Code Assist individual
    users to Antigravity CLI. Use [Antigravity](antigravity.md) for those
    accounts. Keep the Gemini CLI route for enterprise and API-key use.

## Install And Authenticate

```bash
npm install -g @google/gemini-cli
gemini
```

Sign in during the first run, or set an API key:

```bash
export GEMINI_API_KEY=your_api_key_here
# or
export GOOGLE_API_KEY=your_api_key_here
```

Verify that SuperQode can discover it:

```bash
superqode agents show gemini
superqode agents doctor gemini
```

## Connect From The TUI

Gemini CLI is listed on the Subscriptions screen of the connect picker:

```text
:connect subscriptions
```

Or connect directly:

```text
:connect acp gemini
```

Both routes start `gemini --acp` and hand the session to Gemini CLI. The
generic ACP path stays available as `:connect acp gemini`.

## Choose The Google Route

Google models reach SuperQode through several distinct paths:

| Goal | Route |
| --- | --- |
| Use the complete first-party Gemini CLI agent | `:connect acp gemini` |
| Use Google's newer signed-in agent harness | `:connect antigravity` |
| Use a Gemini model inside the SuperQode native harness | `:connect byok google <model>` |
| Use the Google-hosted Antigravity managed agent | `:antigravity managed` |

A coding-agent connection and a model connection are not interchangeable.
Choose Gemini CLI when you want its complete agent loop. Choose BYOK when you
want SuperQode's native harness to own tools, approvals, context, and workflow
around a Gemini model.

## Related Documentation

- [Google Antigravity](antigravity.md)
- [Connection Methods and Vendors](../concepts/modes.md)
- [ACP Agent Catalog](acp.md)

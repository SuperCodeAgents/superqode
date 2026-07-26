---
title: Sandboxes
description: Configure local, container, cloud, and experimental sandbox backends.
---

# Sandboxes

Run `superqode sandbox doctor` before selecting a backend. Local execution is
the default path; cloud providers are explicit integrations.

## Core and popular backends

| Sandbox | Install | Authentication | First run |
| --- | --- | --- | --- |
| Local OS | **Included**; uses macOS Seatbelt or Linux Bubblewrap when available | None | `superqode sandbox doctor local-os` |
| Docker | Install the Docker CLI and daemon | None | `superqode sandbox run docker --image python:3.12 -- pytest -q` |
| Podman | Install Podman | None | `superqode sandbox doctor podman` |
| Apple Container | Install the Apple `container` CLI; status support is experimental | None | `superqode sandbox doctor apple-container` |
| E2B | `uv tool install "superqode[sandbox-e2b]"` | `E2B_API_KEY` | `superqode sandbox run e2b -- "pytest -q"` |
| Daytona | `uv tool install "superqode[sandbox-daytona]"` | `DAYTONA_API_KEY` | `superqode sandbox doctor daytona` |
| Modal | `uv tool install "superqode[sandbox-modal]"` | Modal account configuration | `superqode sandbox doctor modal` |
| Vercel Sandbox | Install the Vercel Sandbox CLI | `VERCEL_OIDC_TOKEN` or `VERCEL_TOKEN` | `superqode sandbox doctor vercel` |

Install the three bundled Python cloud providers together with:

```bash
uv tool install "superqode[sandbox-cloud]"
```

## Experimental backends

| Sandbox | Separate installation | Authentication | Verification |
| --- | --- | --- | --- |
| Runloop | `uv pip install runloop_api_client langchain-runloop` | `RUNLOOP_API_KEY` | `superqode sandbox doctor runloop` |
| Amazon Bedrock AgentCore | `uv pip install bedrock-agentcore langchain-agentcore-codeinterpreter` | AWS credentials | `superqode sandbox doctor agentcore` |
| LangSmith | `uv pip install langsmith deepagents` | `LANGSMITH_API_KEY` | `superqode sandbox doctor langsmith` |

The OpenAI Agents runtime also recognizes optional `agents-e2b`,
`agents-daytona`, `agents-modal`, `agents-vercel`, `agents-runloop`,
`agents-blaxel`, and `agents-cloudflare` sandbox client packages. Install those
directly into the active environment when using the OpenAI Agents sandbox
surface.

See [Sandbox Commands](../cli-reference/sandbox-commands.md) and
[Safety and Permissions](../advanced/safety-permissions.md).


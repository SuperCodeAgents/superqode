---
title: Remote Interfaces
description: Configure Telegram, Slack, Discord, and the browser-hosted TUI.
---

# Remote interfaces

| Integration | Dependency | Authentication | Start | Detailed guide |
| --- | --- | --- | --- | --- |
| Telegram | **Included** transport | Telegram bot token and allowlist | `superqode daemon start` | [Chat Channels](../advanced/channels.md) |
| Slack | `uv tool install "superqode[channels]"` | Slack app and Socket Mode credentials | `superqode daemon start` | [Chat Channels](../advanced/channels.md) |
| Discord | `superqode[channels]` | Discord bot token and allowlist | `superqode daemon start` | [Chat Channels](../advanced/channels.md) |
| Browser-hosted TUI | `uv tool install "superqode[web]"` | Bind and access configuration | `superqode serve web` | [Authentication](../concepts/authentication.md) |

The terminal TUI is part of the standard installation and requires no optional
extra:

```bash
superqode
```


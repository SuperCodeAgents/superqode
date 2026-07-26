---
title: Memory
description: Configure local, SpecMem, Mem0, Cognee, and Supermemory providers.
---

# Memory

Local memory and SpecMem are included. External providers are opt-in and do not
replace the local default unless configuration selects them.

| Provider | Dependency | Authentication or service | Verify | Detailed guide |
| --- | --- | --- | --- | --- |
| Local memory | **Included** | None | `superqode memory status` | [Memory and Learning](../advanced/memory.md#local) |
| SpecMem | **Included** | Repository HarnessSpec and local store | `superqode memory status` | [Memory and Learning](../advanced/memory.md#specmem) |
| Mem0 | `uv tool install "superqode[mem0]"` | Mem0 credentials and configuration | `superqode memory status` | [Memory and Learning](../advanced/memory.md#mem0) |
| Cognee | Install separately with `uv pip install "cognee>=1.1.2,<2.0.0"` or provide `cognee-cli` | Cognee local configuration or cloud credentials | `superqode memory status` | [Memory and Learning](../advanced/memory.md#cognee) |
| Supermemory | `uv tool install "superqode[supermemory]"` | Supermemory credentials and configuration | `superqode memory status` | [Memory and Learning](../advanced/memory.md#supermemory) |

Install the two bundled external providers together with:

```bash
uv tool install "superqode[memory-providers]"
```

Cognee is not part of that bundle because its current dependency tree conflicts
with the base SuperQode environment. Run it separately or isolate it behind its
CLI boundary.

---
title: Dependency Compatibility
description: Review optional dependency conflicts and environment isolation requirements.
---

# Dependency compatibility

Install integrations according to repository requirements. The package
resolver blocks the following combinations because their current dependency
requirements cannot share one environment safely:

- `antigravity-sdk` or `vendor-sdks` with `mem0` or `memory-providers`
- `antigravity-sdk` or `vendor-sdks` with `adk`
- `antigravity-sdk` or `vendor-sdks` with `observability`
- `antigravity-sdk` or `vendor-sdks` with `sandbox-modal` or `sandbox-cloud`
- `antigravity-sdk` or `vendor-sdks` with `pydanticai` or `pydanticai-logfire`

These conflicts currently come from incompatible protobuf requirements. Use
separate `uv` tool environments when both integrations are required:

```bash
uv tool install "superqode[antigravity-sdk]"
uvx --from "superqode[mem0]" superqode memory status
```

Cognee also remains a separate installation because its current dependency
tree requires an older Rich release than SuperQode.

---
source_file: configuration.md
page_id: configuration
sdk_version: v3
page_type: reference
---

# ClientConfig Reference

`ClientConfig` manages global runtime settings, timeout overrides, and connection pooling parameters for the v3 SDK.

## Environment Variables

The default API timeout in `ClientConfig` can be globally overridden using the `SDK_V3_TIMEOUT_S` environment variable.

| Variable Name | Default Value | Description |
|---------------|---------------|-------------|
| SDK_V3_TIMEOUT_S | 30.0 | Overrides the default HTTP request timeout in seconds. |
| SDK_V3_ENVIRONMENT | production | Environment target (`sandbox`, `staging`, `production`). |
| SDK_V3_LOG_LEVEL | INFO | Logging verbosity (`DEBUG`, `INFO`, `WARNING`, `ERROR`). |

## Programmatic Configuration

```python
from sdk_v3 import ClientConfig

config = ClientConfig(
    timeout_s=45.0,
    environment="sandbox",
    max_connections=50
)
```

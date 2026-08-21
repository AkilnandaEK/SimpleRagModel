---
source_file: authentication.md
page_id: authentication
sdk_version: v3
page_type: guide
---

# Authentication & Credentials

The v3 SDK requires explicit authentication credentials before executing remote RPC operations.

## Bearer Token Authentication

To configure Bearer token authentication in the v3 SDK, initialize the client using the `BearerTokenAuth` class or pass `api_key` directly to `ClientConfig`.

```python
from sdk_v3 import Client, BearerTokenAuth

auth = BearerTokenAuth(token="v3_sec_key_994821")
client = Client(auth=auth)
```

## Supported Credentials

- **API Keys**: Static authentication keys provided in the developer portal.
- **OAuth2 Bearer Tokens**: Dynamic short-lived tokens obtained via token endpoint.
- **Mutual TLS (mTLS)**: Certificate-based identity verification for enterprise tiers.

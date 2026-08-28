---
source_file: webhooks.md
page_id: webhooks
sdk_version: v3
page_type: reference
---

# Webhook Management

The `WebhookManager` processes asynchronous event notifications emitted by the v3 SDK platform.

## Verifying Webhook Signatures

To verify a webhook signature using `WebhookManager`, pass the raw HTTP body, signature header, and webhook secret key to `WebhookManager.verify_signature()`.

```python
from sdk_v3 import WebhookManager

is_valid = WebhookManager.verify_signature(
    body=raw_bytes,
    signature_header=request.headers.get("X-Signature"),
    secret="whsec_abc123"
)
```

## Supported Events

- `event.delivered`: Triggered when a payload is successfully delivered.
- `event.failed`: Triggered when max retries are exhausted.

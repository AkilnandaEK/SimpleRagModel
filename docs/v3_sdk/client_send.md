---
source_file: client_send.md
page_id: client_send
sdk_version: v3
page_type: reference
---

# Client.send() Method Reference

The `Client.send()` method delivers API request payloads to downstream integration targets with configurable retry backoff and error recovery policies.

## Syntax

```python
response = client.send(
    payload={"event": "user.signup"},
    retry_backoff_ms=1000,
    max_retries=3
)
```

## Parameters

| Parameter | Type | Default | Required | Description |
|-----------|------|---------|----------|-------------|
| payload | dict | None | true | The event or message payload dictionary to transmit. |
| retry_backoff_ms | int | 1000 | false | Initial exponential backoff duration in milliseconds between retries. |
| max_retries | int | 3 | false | Maximum number of retry attempts before throwing an SDKError. |
| timeout_s | float | 30.0 | false | Request timeout threshold in seconds. |

## Response Payload

The method returns an `APIResponse` object containing the following fields:

- `status_code` (int): HTTP status code returned by the server.
- `transaction_id` (str): Unique tracking identifier for the sent message.
- `acknowledged` (bool): `true` if the server successfully accepted the request.

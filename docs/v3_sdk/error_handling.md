---
source_file: error_handling.md
page_id: error_handling
sdk_version: v3
page_type: reference
---

# Error Handling & Exceptions

All exceptions thrown by the v3 SDK inherit from the base `SDKError` class.

## Common Error Codes

| Error Code | Class Name | Description | Recovery Strategy |
|------------|------------|-------------|-------------------|
| ERR_TIMEOUT | SDKTimeoutError | Raised when a network operation exceeds `timeout_s`. | Retry with linear backoff. |
| ERR_RATE_LIMIT | SDKRateLimitError | Raised when request volume exceeds quota limits. | Pause execution for `retry_after_s` specified in exception headers. |
| ERR_AUTH_FAILED | SDKAuthError | Invalid or expired API credentials. | Re-authenticate and obtain a new token. |

## Handling ERR_RATE_LIMIT

When `ERR_RATE_LIMIT` is returned, retry attempts are automatically handled by pausing execution for the duration specified in the `retry_after_s` attribute or header before retrying the call.

```python
try:
    client.send(payload)
except SDKRateLimitError as err:
    print(f"Rate limited. Waiting {err.retry_after_s} seconds...")
```

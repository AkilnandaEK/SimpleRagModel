---
source_file: batch_processing.md
page_id: batch_processing
sdk_version: v3
page_type: reference
---

# Batch Processing & High Throughput

The `Client.batch_send()` method processes multiple request payloads in parallel workers.

## Concurrency Limits & Constraints

The maximum allowed batch size for `Client.batch_send()` is 50 items per single request call.

| Parameter | Type | Default | Required | Description |
|-----------|------|---------|----------|-------------|
| items | list[dict] | [] | true | List of item payloads to send in bulk (max 50). |
| concurrency | int | 5 | false | Maximum number of concurrent worker threads. |

## Code Example

```python
results = client.batch_send(
    items=[{"id": i} for i in range(25)],
    concurrency=5
)
```

# xmemory

Python client library for the [Xmemory](https://xmemory.ai) API.

## Quick start

```python
from xmemory import xmemory_instance

mem = xmemory_instance(
    url="https://api.xmemory.ai",   # or set XMEM_API_URL env var
    instance_id="<your-instance-id>",
    token="<your-token>",           # or set XMEM_AUTH_TOKEN env var
)

mem.write("Alice is a software engineer who loves Python.")
result = mem.read("What does Alice do?")
print(result.reader_result)
```

## Async quick start

```python
import asyncio
from xmemory import async_xmemory_instance

async def main():
    async with async_xmemory_instance(instance_id="<your-instance-id>") as mem:
        await mem.write("Alice is a software engineer who loves Python.")
        result = await mem.read("What does Alice do?")
        print(result.reader_result)

asyncio.run(main())
```

## Configuration

| Parameter     | Env var           | Default                    | Description                        |
|---------------|-------------------|----------------------------|------------------------------------|
| `url`         | `XMEM_API_URL`    | `https://api.xmemory.ai`   | Base URL of the Xmemory API        |
| `instance_id` | —                 | `None`                     | Instance to read/write against     |
| `token`       | `XMEM_AUTH_TOKEN` | `None`                     | Bearer token for authentication    |
| `timeout`     | —                 | `60`                       | Default request timeout in seconds |

## Context managers

Both clients support the context manager protocol and close the underlying HTTP connection on exit.

```python
# sync
with xmemory_instance(instance_id="abc") as mem:
    mem.write("...")

# async
async with async_xmemory_instance(instance_id="abc") as mem:
    await mem.write("...")
```

## External HTTP client

You can pass your own `httpx.Client` (or `httpx.AsyncClient`). The client will not be closed when
the Xmemory instance is closed, giving you full control over its lifecycle.

```python
import httpx
from xmemory import XmemoryAPI

http = httpx.Client(base_url="https://api.xmemory.ai", timeout=30)
mem = XmemoryAPI(http_client=http, instance_id="abc")
```

## Methods

### `check_health() → None`

Verify that the Xmemory API is reachable. Raises `XmemoryHealthCheckError` on failure.

```python
try:
    mem.check_health()
except XmemoryHealthCheckError as e:
    print(f"API is unreachable: {e}")
```

### `create_instance(schema_text, schema_type, *, timeout=None) → CreateInstanceResponse`

Create a new instance from a schema. On success the new `instance_id` is saved automatically
and used for subsequent calls.

```python
from xmemory import SchemaType

resp = mem.create_instance(schema_yml, SchemaType.YML)
resp = mem.create_instance(schema_json, SchemaType.JSON)
print(resp.instance_id)
```

### `get_schema(*, timeout=None) → GetSchemaResponse`

Fetch the current schema of the active instance.

```python
resp = mem.get_schema()
print(resp.schema_yaml)
```

### `update_schema(schema_text, schema_type, *, timeout=None) → bool`

Update the schema of the active instance. Returns `True` on success.

```python
ok = mem.update_schema(new_schema_yml, SchemaType.YML)
```

### `generate_schema(schema_description, *, old_schema_yml=None, timeout=None) → GenerateSchemaResponse`

Ask the API to generate a YML schema from a plain-text description.
Optionally pass `old_schema_yml` to refine an existing schema.

```python
resp = mem.generate_schema("People with name, role, and location.")
print(resp.generated_schema)
```

### `read(query, *, read_mode=ReadMode.SINGLE_ANSWER, timeout=None) → ReadResponse`

Query the instance and get a structured answer.

```python
resp = mem.read("Who is on the team?")
print(resp.reader_result)
```

Use `read_mode` to control the response format:

```python
from xmemory import ReadMode

resp = mem.read("Show people and companies", read_mode=ReadMode.XRESPONSE)
```

### `write(text, *, extraction_logic=ExtractionLogic.DEEP, timeout=None) → WriteResponse`

Extract structured objects from `text` and persist them to the instance.

```python
from xmemory import ExtractionLogic

resp = mem.write("Bob joined the team on Monday as a designer.")
resp = mem.write("...", extraction_logic=ExtractionLogic.FAST)
print(resp.cleaned_objects)
```

### `write_async(text, *, extraction_logic=ExtractionLogic.DEEP, timeout=None) → AsyncWriteResponse`

Submit a write job and return immediately with a `write_id` for polling.
Useful when you don't want to block on a potentially slow extraction.

```python
resp = mem.write_async("Bob joined the team on Monday as a designer.")
write_id = resp.write_id
```

### `write_status(write_id, *, timeout=None) → WriteStatusResponse`

Poll the status of a job submitted via `write_async`.

```python
from xmemory import WriteQueueStatus

status = mem.write_status(write_id)
if status.write_status == WriteQueueStatus.COMPLETED:
    print("Done!")
```

### `extract(text, *, extraction_logic=ExtractionLogic.DEEP, timeout=None) → ExtractionResponse`

Extract structured objects from `text` without writing them to the instance.

```python
resp = mem.extract("Carol is a manager based in Berlin.")
print(resp.objects_extracted)
```

## Async methods

`AsyncXmemoryAPI` exposes the same methods as `XmemoryAPI`, all as coroutines.
Use `await` for each call and `async with` or `await mem.aclose()` to clean up.

```python
from xmemory import async_xmemory_instance, ExtractionLogic, ReadMode

async with async_xmemory_instance(instance_id="abc") as mem:
    await mem.check_health()
    await mem.write("Alice is an engineer.", extraction_logic=ExtractionLogic.REGULAR)
    result = await mem.read("What does Alice do?", read_mode=ReadMode.SINGLE_ANSWER)

    # async write with polling
    job = await mem.write_async("Bob joined the team.")
    status = await mem.write_status(job.write_id)
```

## Error handling

All errors raise `XmemoryAPIError` (or its subclass `XmemoryHealthCheckError` for connectivity failures).
`XmemoryAPIError` carries an optional `.status` attribute with the HTTP status code.

```python
from xmemory import XmemoryAPIError, XmemoryHealthCheckError, xmemory_instance

mem = xmemory_instance(url="http://localhost:8000", instance_id="abc")

try:
    mem.check_health()
except XmemoryHealthCheckError as e:
    print(f"Could not reach the API: {e}")

try:
    resp = mem.read("something")
except XmemoryAPIError as e:
    print(f"API error (HTTP {e.status}): {e}")
```

## Package publishing to pip

```bash
python -m pip install --upgrade build twine
python -m build

# test with test.pypi.org (separate account and API key required)
python -m twine upload --repository testpypi dist/*

# publish the real version when ready
python -m twine upload dist/*

# test the package
pip install xmemory-ai
```

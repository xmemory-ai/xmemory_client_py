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

## Configuration

| Parameter     | Env var           | Default                    | Description                        |
|---------------|-------------------|----------------------------|------------------------------------|
| `url`         | `XMEM_API_URL`    | `https://api.xmemory.ai`   | Base URL of the Xmemory API        |
| `instance_id` | —                 | `None`                     | Instance to read/write against     |
| `token`       | `XMEM_AUTH_TOKEN` | `None`                     | Bearer token for authentication    |
| `timeout`     | —                 | `60`                       | Default request timeout in seconds |

## Methods

### `check_health() → None`

Verify that the Xmemory API is reachable. Raises `XmemoryHealthCheckError` on failure.
Unlike the constructor, this method performs the actual connectivity check, so you can
call it whenever you need to confirm the service is alive.

```python
try:
    mem.check_health()
    print("API is up")
except XmemoryHealthCheckError as e:
    print(f"API is unreachable: {e}")
```

### `generate_schema(schema_description, *, old_schema_yml=None, timeout=None) → GenerateSchemaResponse`

Ask the API to generate a YML schema from a plain-text description.

```python
resp = mem.generate_schema("People with name, role, and location.")
print(resp.generated_schema)
```

Optionally pass `old_schema_yml` to refine an existing schema.

### `create_instance(schema_text, schema_type, *, timeout=None) → bool`

Create a new instance with the given schema. On success, the new `instance_id`
is saved automatically and used for subsequent calls.

### `write(text, *, timeout=None, extract_write_id=None) → WriteResponse`

Extract structured objects from `text` and store them in the instance.

```python
resp = mem.write("Bob joined the team on Monday as a designer.")
print(resp.status)          # "ok" or "error"
print(resp.cleaned_objects) # written objects
```

### `read(query, *, read_mode=ReadMode.SINGLE_ANSWER, timeout=None) → ReadResponse`

Query the instance and get a natural-language answer.

```python
resp = mem.read("Who is on the team?")
print(resp.reader_result)
```

You can select the response format with `ReadMode`:

```python
from xmemory import ReadMode

resp = mem.read("Show people and companies", read_mode=ReadMode.XRESPONSE)
print(resp.reader_result)
```

### `extract(text, *, timeout=None, extract_write_id=None) → ExtractionResponse`

Extract structured objects from `text` without writing them to the instance.

```python
resp = mem.extract("Carol is a manager based in Berlin.")
print(resp.objects_extracted)
```

```python
from xmemory import SchemaType

ok = mem.create_instance(schema_yml, SchemaType.YML)
ok = mem.create_instance(schema_json, SchemaType.JSON)
```

### `update_schema(schema_text, schema_type, *, timeout=None) → bool`

Update the schema of the current instance.

```python
ok = mem.update_schema(new_schema_yml, SchemaType.YML)
```

## Error handling

All errors raise `XmemoryAPIError` (or its subclass `XmemoryHealthCheckError`
for connectivity failures).

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
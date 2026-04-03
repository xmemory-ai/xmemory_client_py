# xmemory

Python client library for the [xmemory](https://xmemory.ai) API.

## Quick start

```python
from xmemory import XmemoryClient, SchemaType

client = XmemoryClient(token="xmem_...")  # or set XMEM_AUTH_TOKEN env var

# Create an instance and start using it immediately
schema = """\
objects:
  person:
    fields:
      name:
        type: str
        required: true
        description: full name of the person
      role:
        type: str
        required: false
        description: job title or role
      location:
        type: str
        required: false
        description: city or location
relations: {}
"""

inst = client.admin.create_instance(
    cluster_id="<your-cluster-id>",
    name="my-memory",
    schema_text=schema,
    schema_type=SchemaType.YML,
)

inst.write("Alice is a software engineer based in Berlin.")
result = inst.read("What does Alice do?")
print(result.reader_result)
```

## Bind to an existing instance

```python
inst = client.instance("<your-instance-id>")
inst.write("Bob joined the team as a designer.")
result = inst.read("Who is on the team?")
```

## Async quick start

```python
import asyncio
from xmemory import AsyncXmemoryClient, SchemaType

async def main():
    async with AsyncXmemoryClient(token="xmem_...") as client:
        inst = await client.admin.create_instance(
            cluster_id="<cluster-id>",
            name="my-memory",
            schema_text=schema,  # same schema as above
            schema_type=SchemaType.YML,
        )
        await inst.write("Alice is a software engineer based in Berlin.")
        result = await inst.read("What does Alice do?")
        print(result.reader_result)

asyncio.run(main())
```

## Configuration

| Parameter     | Env var           | Default                    | Description                        |
|---------------|-------------------|----------------------------|------------------------------------|
| `url`         | `XMEM_API_URL`    | `https://api.xmemory.ai`   | Base URL of the Xmemory API        |
| `token`       | `XMEM_AUTH_TOKEN` | `None`                     | Bearer token for authentication    |
| `timeout`     | —                 | `60`                       | Default request timeout in seconds |

## Client structure

The client is organized into two namespaces:

- **`client.admin`** — cluster management, instance lifecycle, schema and metadata management
- **`client.instance(id)`** — instance-bound data operations (read, write, extract)

### Admin API (`client.admin`)

```python
# Clusters
clusters = client.admin.list_clusters()
cluster = client.admin.get_cluster("<cluster-id>")

# Instance lifecycle
inst = client.admin.create_instance(cluster_id, "name", schema, SchemaType.YML)
instances = client.admin.list_instances()
info = client.admin.get_instance("<instance-id>")
client.admin.delete_instance("<instance-id>")

# Schema management
schema = client.admin.get_instance_schema("<instance-id>")
client.admin.update_instance_schema("<instance-id>", new_schema, SchemaType.YML)

# Metadata management
client.admin.update_instance_metadata("<instance-id>", "new-name", "new description")

# Schema generation
result = client.admin.generate_schema(cluster_id, "People with name, role, and location.")
print(result.generated_schema)
```

`create_instance` returns an `InstanceAPI` bound to the new instance, ready for data operations.

`list_instances` and `get_instance` return `InstanceInfo` metadata objects.

### Instance API (`client.instance(id)`)

```python
inst = client.instance("<instance-id>")

# Read
result = inst.read("Who is on the team?")
print(result.reader_result)

# Write (synchronous)
result = inst.write("Bob joined the team on Monday as a designer.")
print(result.cleaned_objects)

# Write (async job)
job = inst.write_async("Bob joined the team on Monday as a designer.")
status = inst.write_status(job.write_id)

# Extract (without persisting)
result = inst.extract("Carol is a manager based in Berlin.")
print(result.objects_extracted)
```

#### Read modes

```python
from xmemory import ReadMode

result = inst.read("Show people and companies", read_mode=ReadMode.XRESPONSE)
```

#### Extraction logic

```python
from xmemory import ExtractionLogic

result = inst.write("...", extraction_logic=ExtractionLogic.FAST)
```

## Schema format

Schemas use the XMD (Xmemory Data Model) format with `objects` and `relations`:

```yaml
objects:
  person:
    fields:
      name:
        type: str
        required: true
        description: full name of the person
      role:
        type: str
        required: false
        description: job title or role
  company:
    fields:
      name:
        type: str
        required: true
        description: company name
      industry:
        type: str
        required: false
        description: industry or sector
relations:
  employment:
    objects:
      person:
        type: person
        on_delete: cascade
      company:
        type: company
        on_delete: cascade
    description: person works at company
```

Field types: `str`, `int`, `float`, `bool`, `date`, `datetime`.

## Context managers

Both clients support the context manager protocol and close the underlying HTTP connection on exit.

```python
# sync
with XmemoryClient(token="xmem_...") as client:
    inst = client.instance("abc")
    inst.write("...")

# async
async with AsyncXmemoryClient(token="xmem_...") as client:
    inst = client.instance("abc")
    await inst.write("...")
```

## External HTTP client

You can pass your own `httpx.Client` (or `httpx.AsyncClient`). The client will not be closed when
the Xmemory client is closed, giving you full control over its lifecycle.

```python
import httpx
from xmemory import XmemoryClient

http = httpx.Client(base_url="https://api.xmemory.ai", timeout=30)
client = XmemoryClient(http_client=http, token="xmem_...")
```

## Health check

```python
from xmemory import XmemoryHealthCheckError

try:
    client.check_health()
except XmemoryHealthCheckError as e:
    print(f"API is unreachable: {e}")
```

## Error handling

All errors raise `XmemoryAPIError` (or its subclass `XmemoryHealthCheckError` for connectivity failures).
`XmemoryAPIError` carries an optional `.status` attribute with the HTTP status code.

```python
from xmemory import XmemoryAPIError

try:
    result = client.instance("abc").read("something")
except XmemoryAPIError as e:
    print(f"API error (HTTP {e.status}): {e}")
```

## Response types

| Method | Returns |
|---|---|
| `admin.list_clusters()` | `list[ClusterInfo]` |
| `admin.get_cluster()` | `ClusterInfo` |
| `admin.create_instance()` | `InstanceAPI` |
| `admin.list_instances()` | `list[InstanceInfo]` |
| `admin.get_instance()` | `InstanceInfo` |
| `admin.get_instance_schema()` | `InstanceSchemaInfo` |
| `admin.update_instance_schema()` | `InstanceInfo` |
| `admin.update_instance_metadata()` | `InstanceInfo` |
| `admin.delete_instance()` | `list[uuid.UUID]` |
| `admin.generate_schema()` | `GenerateSchemaResult` |
| `inst.read()` | `ReadResult` |
| `inst.write()` | `WriteResult` |
| `inst.write_async()` | `AsyncWriteResult` |
| `inst.write_status()` | `WriteStatusResult` |
| `inst.extract()` | `ExtractResult` |

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

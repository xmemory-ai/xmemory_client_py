# xmemory

Python client library for the [xmemory](https://xmemory.ai) API.

## Quick start

```python
from xmemory import XmemoryClient, SchemaType

client = XmemoryClient(api_key="xmem_...")  # or set XMEM_API_KEY env var

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
    async with AsyncXmemoryClient(api_key="xmem_...") as client:
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
| `api_key`     | `XMEM_API_KEY`    | `None`                     | API key for authentication         |
| `timeout`     | —                 | `60`                       | Default request timeout in seconds |

> **Deprecation:** The legacy term `token` (argument `token=` and env var
> `XMEM_AUTH_TOKEN`) is still accepted for backwards compatibility but prints an
> orange-colored deprecation notice on use. Migrate to `api_key` /
> `XMEM_API_KEY`. The legacy names will be removed in a future release.

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
print(result.data_schema)
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

## Schema evolution

Schemas can change after creation. xmemory supports **safe, data-preserving
migrations** (rename / remove / type change) driven by structured migration
ops, plus a **suggestion engine** that proposes improvements from real read
traffic. Both paths are purely additive to this library — existing callers are
unaffected.

See the [Schema evolution section of the API reference](https://xmemory.ai/api/#schema-evolution)
for the conceptual model, and the [Python guide](https://xmemory.ai/python/) for
full walkthroughs.

### Suggestion-engine flow (review → decide → apply)

The engine surfaces a single rolling proposal per instance. The minimum flow is
three calls — review, decide (in bulk), apply:

```python
from xmemory import DecisionInput, XmemoryClient

client = XmemoryClient(api_key="xmem_...")
inst = client.instance("<instance-id>")

# 1. Review — get the consolidated proposal + its concurrency token.
review = inst.review_suggestions()
if review.status == "evolution_in_progress":
    print(f"A migration is in flight; retry in {review.retry_after_seconds}s")
else:
    proposal = review.proposal
    for item in proposal.items:
        print(item.item_fingerprint, item.rationale, item.op)

    # 2. Decide — accept / reject / defer per item, in one batch.
    decided = inst.decide_suggestions(
        proposal.proposal_version,
        [DecisionInput(item_fingerprint=item.item_fingerprint, decision="accept")
         for item in proposal.items],
    )

    # 3. Apply — commit accepted decisions as one migration.
    applied = inst.apply_pending_decisions(decided.next_proposal_version)
    print(applied.status, applied.summary)  # e.g. "ok" "added 1 field"
```

`review_suggestions()` returns a `ReviewSuggestionsResult`. When
`status == "evolution_in_progress"`, back off for `retry_after_seconds` and
retry instead of blocking.

### Direct migration flow (enhance → dry-run → update)

To drive a migration yourself (e.g. renaming a field), ask the server to
*enhance* the current schema, preview the DDL, then apply it:

```python
import yaml
from xmemory import XmemoryClient

client = XmemoryClient(api_key="xmem_...")
current = client.admin.get_instance_schema("<instance-id>").data_schema

# 1. Enhance — produce the new schema + an executor-ready migration plan.
enhanced = client.admin.enhance_schema(
    cluster_id="<cluster-id>",
    schema_description="Rename Person.mail to Person.email.",
    current_yml_schema=yaml.safe_dump(current),
)
print(enhanced.summary)
for op in enhanced.migration_plan.ops:
    print(op)

new_yaml = yaml.safe_dump(enhanced.data_schema)

# 2. Dry-run — preview the DDL without applying anything.
preview = client.admin.dry_run_migration(
    "<instance-id>", new_yaml, SchemaType.YML,
    migration_plan=enhanced.migration_plan,
)
print(preview.statements)

# 3. Update — apply. confirm_destructive=True is required for ops that drop data.
info = client.admin.update_instance_schema(
    "<instance-id>", new_yaml, SchemaType.YML,
    migration_plan=enhanced.migration_plan,
    confirm_destructive=False,
)
print(info.migration_id, info.prior_version, "->", info.new_version)
```

### Migration history

```python
page = client.admin.list_migrations("<instance-id>", limit=20)
for record in page.items:
    print(record.id, record.source, record.prior_version, "->", record.new_version)

detail = client.admin.get_migration("<instance-id>", "<migration-id>", include_yaml=True)
print(detail.yaml_before, detail.yaml_after)
```

Migration ops are exported as typed models (`MigrationPlan`, `MigrationOp`,
`AddField`, `RenameField`, `RemoveObject`, …). `ProposalItem.op` and
`MigrationRecord.ops` are kept as raw dicts for forward compatibility — call
`parse_migration_op(...)` / `parse_migration_plan(...)` to validate them into
typed ops.

Runnable end-to-end examples live in [`examples/`](examples/).

## Context managers

Both clients support the context manager protocol and close the underlying HTTP connection on exit.

```python
# sync
with XmemoryClient(api_key="xmem_...") as client:
    inst = client.instance("abc")
    inst.write("...")

# async
async with AsyncXmemoryClient(api_key="xmem_...") as client:
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
client = XmemoryClient(http_client=http, api_key="xmem_...")
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
`XmemoryAPIError` carries an optional `.status` (HTTP status code), `.code` (structured error code,
when the server returned one), and `.details` (structured error payload).

```python
from xmemory import XmemoryAPIError

try:
    result = client.instance("abc").read("something")
except XmemoryAPIError as e:
    print(f"API error (HTTP {e.status}): {e}")
```

The schema-evolution endpoints return structured error codes you can pattern
match on via `.code` rather than parsing the message — for example
`stale_proposal_version`, `dependency_closure_failed`,
`destructive_confirmation_required`, `non_additive_change_requires_plan`,
`stale_schema_version`, `migration_not_found`, `instance_not_initialised`:

```python
try:
    inst.apply_pending_decisions(token)
except XmemoryAPIError as e:
    if e.code == "stale_proposal_version":
        review = inst.review_suggestions()  # re-review and retry
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
| `admin.delete_instance()` | `list[str]` |
| `admin.generate_schema()` | `GenerateSchemaResult` |
| `admin.enhance_schema()` | `EnhanceSchemaResult` |
| `admin.dry_run_migration()` | `DryRunResult` |
| `admin.list_migrations()` | `ListMigrationsResult` |
| `admin.get_migration()` | `MigrationRecord` |
| `inst.read()` | `ReadResult` |
| `inst.write()` | `WriteResult` |
| `inst.write_async()` | `AsyncWriteResult` |
| `inst.write_status()` | `WriteStatusResult` |
| `inst.extract()` | `ExtractResult` |
| `inst.get_schema()` | `InstanceSchemaInfo` |
| `inst.describe()` | `DescribeResult` |
| `inst.review_suggestions()` | `ReviewSuggestionsResult` |
| `inst.decide_suggestions()` | `DecideSuggestionsResult` |
| `inst.apply_pending_decisions()` | `ApplyPendingDecisionsResult` |

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

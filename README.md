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
| `url`         | `XMEM_API_URL`    | `https://api.xmemory.ai`   | Base URL of the xmemory API        |
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

# Change one field and leave the rest alone
client.admin.patch_instance_metadata("<instance-id>", description="a new description")

# Schema generation
result = client.admin.generate_schema(cluster_id, "People with name, role, and location.")
print(result.data_schema)
```

`create_instance` returns an `InstanceAPI` bound to the new instance, ready for data operations.

`list_instances` and `get_instance` return `InstanceInfo` metadata objects.

#### Agent-facing instance metadata

An instance can carry metadata that shapes how agents connect to it and what
they do with it. `patch_instance_metadata` is the way to set the advisory
hints: every argument is independent, **omitting one leaves the stored value
untouched**, and passing `None` clears it.

```python
from xmemory import AgentSurface, BindingTier

client.admin.patch_instance_metadata(
    "<instance-id>",
    # Advisory hints — they seed what a connect flow proposes, and grant nothing.
    agent_surfaces=[AgentSurface.CLAUDE_CODE, AgentSurface.CODEX],
    agent_default_binding_tier=BindingTier.AUTOLOAD,
    agent_engagement_hints=["a convention is learned or corrected"],
)
```

Concurrent edits to these three are last-writer-wins by design: they only seed
what a connect flow proposes, so the loser of a race re-applies a suggestion.
`agent_owner_instructions` is not like that — see below.

Reading it back:

```python
info = client.admin.get_instance("<instance-id>")
info.agent_owner_instructions
info.agent_surfaces                    # e.g. ["claude_code", "codex"]
info.agent_default_binding_tier        # e.g. "autoload"
info.agent_engagement_hints
```

These read as plain strings rather than enums, so a value your server knows and
this release does not is returned rather than rejected.

**Setting the standing instructions.** Use `update_instance_metadata` for
`agent_owner_instructions`, not `patch_instance_metadata`. The field is
rendered to agents verbatim, and a second writer edits it from the same screen,
so a silently lost edit is a rule that stops being enforced. Only
`update_instance_metadata` carries `expected_owner_instructions_epoch`: pass
the epoch you read the value at and the server refuses the losing save instead
of applying it.

`patch_instance_metadata` also accepts the field — it is the only way to set it
without restating the name — but it can carry no guard, so an edit composed
from stale data overwrites a newer one silently. Reach for it only when you are
seeding a value nobody else is editing.

```python
info = client.admin.get_instance("<instance-id>")
client.admin.update_instance_metadata(
    "<instance-id>", info.name, info.description,
    agent_owner_instructions=(info.agent_owner_instructions or "") + "\nAlso: never paraphrase a rule.",
    expected_owner_instructions_epoch=info.agent_owner_instructions_epoch,
)
```

### Instance API (`client.instance(id)`)

```python
inst = client.instance("<instance-id>")

# Read
result = inst.read("Who is on the team?")
print(result.reader_result)
print(result.console_url)  # this read's trace in the console; None if none is configured

# Write (synchronous)
result = inst.write("Bob joined the team on Monday as a designer.")
print(result.changes)     # what the write created / updated / deleted
print(result.console_url)  # the same link for the write

# Write (async job)
job = inst.write_async("Bob joined the team on Monday as a designer.")
status = inst.write_status(job.write_id)

# Structured write: deterministic, LLM-free create/update/delete mutations
# (mutually exclusive with text; applied in list order)
from xmemory import ObjectCreate, ObjectMutation

result = inst.write(structured_mutations=[
    ObjectMutation(
        object_type="person",
        create=ObjectCreate(key={"name": "Bob"}, values={"role": "designer"}),
    ),
    # Plain dicts in the API wire form work too:
    {"object_mutation": {"object_type": "person", "update": {"key": {"name": "Bob"}, "values": {"role": None}}}},  # None clears
])

# Extract (without persisting)
result = inst.extract("Carol is a manager based in Berlin.")
print(result.objects_extracted)

# Describe: agent-facing tool docs, plus what this memory is for
described = inst.describe()
print(described.as_text())      # ready to inject into a system prompt
described.purpose               # what the memory is for (the instance description)
described.owner_instructions    # the standing preference set for it, verbatim
described.usage_brief           # generated from the schema; None until generated
```

`as_text()` includes `purpose` and `owner_instructions` when the instance has
them. `usage_brief` is left out of it — it restates the schema summary that is
already there — so read the attribute if you want it.

Both fields are free text set by anyone holding edit permission on the instance,
so `as_text()` labels each with where it came from rather than presenting it as
the library's own words. Those labels state provenance; they are not a security
boundary. If you inject this into a system prompt you are still handling text you
do not control.

#### Read modes

```python
from xmemory import ReadMode

result = inst.read("Show people and companies", read_mode=ReadMode.XRESPONSE)
```

#### Composite queries

When a query bundles several independent questions, the server may decompose it
into sub-queries and answer each one. `reader_result` is still the combined
answer (for `single-answer` mode, a labelled multi-part string); `reader_results`
holds one `TaggedReaderResult` (`sub_query`, `reader_result`, `error`) per
sub-query so you can read each answer unambiguously. A single-intent query yields
one entry, and the list is empty against a server without question decomposition.

```python
result = inst.read("Who leads sales, and where is HQ?")
for part in result.reader_results:
    print(part.sub_query, "->", part.error or part.reader_result)
```

#### Scoped reads

By default a read may draw on any object in the instance. Pass a `scope` to
restrict it to a specific set of concrete objects — each named by its `type`
plus its user-defined primary `key`:

```python
from xmemory import ReadScope, ScopeObject

result = inst.read(
    "What do these people do?",
    scope=ReadScope(
        objects=[
            ScopeObject(type="Person", key={"name": "Alice"}),
            ScopeObject(type="Person", key={"name": "Bob"}),
        ],
    ),
)
```

Only the listed objects are in scope. To also expose the relations among them,
set `relations_scope="all_relations"` (the default is `"no_relations"`):

```python
result = inst.read(
    "How are these people connected?",
    scope=ReadScope(
        objects=[
            ScopeObject(type="Person", key={"name": "Alice"}),
            ScopeObject(type="Company", key={"name": "Acme"}),
        ],
        relations_scope="all_relations",
    ),
)
```

Each `ScopeObject` names one object by its `type` plus its user-defined primary
`key`, using the same field name(s) as your schema, with one entry per
primary-key field. Only objects of a type that has a user-defined primary key
can be scoped. Scoped reads compose with `read_mode`.

#### Scoped writes

A write is normally free to touch anything in the instance: the extractor sees
the text alone, and whatever it produces is reconciled against the whole
instance. Pass a `scope` to anchor a text write to a set of concrete existing
objects instead:

```python
from xmemory import ScopeObject, WriteScope

result = inst.write(
    "After her promotion she is a surgeon, and her desk phone is +1-555-0100.",
    scope=WriteScope(
        objects=[ScopeObject(type="Person", key={"name": "Alice Johnson"})],
    ),
)
```

This does two things at once. The scoped objects' **current values** are shown
to the extractor, so the new information is folded into them instead of
producing a near-duplicate record. And the write is then **confined** to the
scope: it may only modify or delete the scoped objects, and create new objects
and relations anchored to them. A write that would touch any other existing
object fails with a validation error rather than applying partially — that
confinement is checked against the resulting plan, so it holds regardless of
what the extractor produced.

`WriteScope` takes the same `ScopeObject`s as `ReadScope`, identified the same
way. Unlike `ReadScope` there is no `relations_scope`: the relations among the
scoped objects always accompany the extraction hint.

Things to know before reaching for it:

- Scope applies to **text writes only** — combining it with
  `structured_mutations` raises a `ValueError`, since those bypass extraction
  entirely and there is nothing for a scope to anchor.
- Only objects of a type with a **user-defined primary key** can be scoped. A
  scope names records by that key, so a type declared `primary_key: []` has
  nothing to name its records by.
- The server currently accepts a scope with **fast extraction only**, and caps
  the number of scoped objects per write. Both are server-side rules, so they
  surface as an `XmemoryAPIError`.
- A scoped write additionally requires **read** permission on the instance,
  because the scoped objects' current values are shown to the extractor. An API
  key with write access alone is refused.
- `write_async` accepts the same `scope`; a scope violation surfaces through
  `write_status` as a failed write.

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

The library never modifies a client you pass in — the object you built is the object you keep. It adds
one header, `X-Xmemory-Client`, to the requests it issues through that client
(`xmemory-python/<version> (python <version>; <system>-<machine>)`, which the API uses to tell its own
clients apart). The header is added per request rather than installed on your client, so a client you
share with other traffic carries nothing of ours between calls.

Your `User-Agent` is never read and never written. Set it, clear it, leave it at httpx's default —
attribution is unaffected either way, because it does not live in that field. That is the reason for a
dedicated header: `User-Agent` belongs to whoever built the request, and a library claiming it has to
decide whose choice to overrule.

Setting the header on a client you pass in is not how you get attributed, and not necessary: the
library adds its own on every request it issues, and a per-request header wins over a client-level one
in httpx, so yours would be replaced on each call. `xmemory.client_identity()` and
`xmemory.CLIENT_HEADER` are exported for requests you send to the API **outside** this library:

```python
import httpx
from xmemory import CLIENT_HEADER, client_identity

# A call this library does not make for you -- an endpoint it does not wrap, say.
httpx.get(
    "https://api.xmemory.ai/some/endpoint",
    headers={CLIENT_HEADER: client_identity(), "Authorization": "Bearer xmem_..."},
)
```

The API key travels on every API request, whichever client issues it. `check_health()` is the one
exception, on both paths: it requests `/healthz`, which takes no key.

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
when the server returned one), `.details` (structured error payload), and `.retry_after`
(the `Retry-After` response header in seconds, when the server sent one).

```python
from xmemory import XmemoryAPIError

try:
    result = client.instance("abc").read("something")
except XmemoryAPIError as e:
    print(f"API error (HTTP {e.status}): {e}")
```

**Branch on `.code`, not on the HTTP status.** A single status can carry more
than one meaning, so the structured `.code` is the discriminator, never the bare
status. Pattern match on `.code` rather than parsing the message string.

### Account / billing & rate-limit codes

| HTTP | `.code` | Meaning | Retryable? |
|---|---|---|---|
| 402 | `QUOTA_EXCEEDED` | Tenant exhausted its plan's daily/monthly token quota. | No |
| 429 | `RATE_LIMITED` | Genuine velocity/rate limit. | Yes — back off and retry, honoring `.retry_after`. |

For `QUOTA_EXCEEDED`, `details` carries `{"kind": "daily_quota_exceeded" | "monthly_quota_exceeded",
"retry_after_seconds": int | None}`, and when the window is resettable the server also
sends a `Retry-After` header (surfaced as `.retry_after`).
The library never retries automatically — it only surfaces these values for you to act on.

```python
import time

try:
    result = client.instance("abc").write("…")
except XmemoryAPIError as e:
    if e.code == "QUOTA_EXCEEDED":
        kind = (e.details or {}).get("kind")  # daily_quota_exceeded | monthly_quota_exceeded
        # Non-retryable: surface to the user; e.retry_after (seconds) hints when the window resets.
        raise
    elif e.code == "RATE_LIMITED":
        # Retryable: back off, honoring e.retry_after if set, then retry.
        time.sleep(e.retry_after or 1)
    else:
        raise
```

### Schema-evolution codes

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
| `admin.get_setup_instructions()` | `AgentSetupResult` |
| `admin.get_instance_schema()` | `InstanceSchemaInfo` |
| `admin.update_instance_schema()` | `InstanceInfo` |
| `admin.update_instance_metadata()` | `InstanceInfo` |
| `admin.patch_instance_metadata()` | `InstanceInfo` |
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
| `inst.setup_instructions()` | `AgentSetupResult` |
| `inst.review_suggestions()` | `ReviewSuggestionsResult` |
| `inst.decide_suggestions()` | `DecideSuggestionsResult` |
| `inst.apply_pending_decisions()` | `ApplyPendingDecisionsResult` |

## License

This client library is released under the [MIT license](LICENSE). The MIT grant
covers this library only — the xmemory service it talks to and the technology
behind it are proprietary to xmemory Inc., and using the service is governed by
the [Terms & Conditions](https://xmemory.ai/terms-and-conditions.html).

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

## Connecting an instance elsewhere

`admin.get_setup_instructions(instance_id)` and `inst.setup_instructions()` both return an
`AgentSetupResult`: how to reach the same memory from another agent surface, ordered
most-likely-first. Available on either handle, because the MCP instance connection serves
the same tool.

```python
setup = inst.setup_instructions()
for surface in setup.surfaces:
    print(surface.label)
    for step in surface.steps:
        print(" ", step.description, step.command or "")
```

Two formats. The default, `SetupFormat.AGENT`, answers *what do I run right now, here*.
`SetupFormat.PROJECT` also returns the files a team commits once, so nobody sets the
instance up by hand:

```python
setup = inst.setup_instructions(format=SetupFormat.PROJECT)
if setup.format == SetupFormat.PROJECT and setup.project:
    for fragment in setup.project.fragments:
        print(fragment.path, fragment.merge)   # a merge, never a file to overwrite
```

**Check `setup.format` rather than assuming.** A server older than that parameter ignores
it and still answers 200, so asking for `PROJECT` is not the same as receiving it.

Nothing returned carries a credential: the steps tell a reader to sign in themselves, out
of band, so an instance id stays an identifier rather than a key.

Advisory values — `step.kind`, `fragment.merge`, `format` — arrive as enum members when
this release knows them and as plain strings when it does not, so a value added to the
server later does not make the whole result unparseable. A `step.kind` you do not
recognise is not something to execute.

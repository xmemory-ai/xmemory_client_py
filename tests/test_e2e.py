"""End-to-end tests against a running server.

Data operations (write/read/extract) require LLM services and may 500
on a minimal local setup. They are tested separately so admin/instance
management tests can pass independently.

Requires ``XMEM_API_KEY`` (and optionally ``XMEM_API_URL``) in the env.
The whole module is skipped when ``XMEM_API_KEY`` is unset, so CI
(which has no key) never runs these — they're for local dev against a
real backend.
"""

import os
import time

import pytest

from xmemory import (
    ExtractionLogic,
    SchemaType,
    ScopeObject,
    WriteScope,
    XmemoryAPIError,
    XmemoryClient,
)

API_KEY = os.environ.get("XMEM_API_KEY")
BASE_URL = os.environ.get("XMEM_API_URL", "https://api.stg.xmemory.ai")

pytestmark = pytest.mark.skipif(
    not API_KEY,
    reason="e2e tests require XMEM_API_KEY (set locally; intentionally unset in CI)",
)

SCHEMA_YML = """\
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


KEYLESS_SCHEMA_YML = """\
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
  note:
    primary_key: []
    fields:
      body:
        type: str
        required: true
        description: free-form note text
      status:
        type: str
        required: false
        description: current status of what the note describes
relations: {}
"""


@pytest.fixture(scope="module")
def client():
    c = XmemoryClient(url=BASE_URL, token=API_KEY)
    yield c
    c.close()


@pytest.fixture()
def instance(client):
    clusters = client.admin.list_clusters()
    assert len(clusters) > 0, "No clusters found"
    cluster_id = str(clusters[0].id)

    inst = client.admin.create_instance(
        cluster_id, "e2e-test-instance", SCHEMA_YML, SchemaType.YML,
        description="End-to-end test instance",
    )
    yield inst, client
    try:
        client.admin.delete_instance(str(inst.id))
    except XmemoryAPIError:
        pass


@pytest.fixture()
def keyless_instance(client):
    clusters = client.admin.list_clusters()
    assert len(clusters) > 0, "No clusters found"
    inst = client.admin.create_instance(
        str(clusters[0].id), "e2e-keyless-instance", KEYLESS_SCHEMA_YML, SchemaType.YML,
        description="End-to-end test instance with a keyless object type",
    )
    yield inst, client
    try:
        client.admin.delete_instance(str(inst.id))
    except XmemoryAPIError:
        pass


def test_health_check(client):
    client.check_health()


def test_list_clusters(client):
    clusters = client.admin.list_clusters()
    assert len(clusters) > 0
    assert clusters[0].name


def test_get_cluster(client):
    clusters = client.admin.list_clusters()
    cluster = client.admin.get_cluster(str(clusters[0].id))
    assert cluster.id == clusters[0].id


def test_create_and_delete_instance(instance):
    inst, client = instance
    assert inst.id

    # Verify it shows up in list
    instances = client.admin.list_instances()
    ids = [str(i.id) for i in instances]
    assert inst.id in ids


def test_get_instance(instance):
    inst, client = instance
    info = client.admin.get_instance(inst.id)
    assert info.name == "e2e-test-instance"
    assert info.description == "End-to-end test instance"


def test_get_schema(instance):
    inst, client = instance
    schema = client.admin.get_instance_schema(str(inst.id))
    assert schema.data_schema
    assert "person" in str(schema.data_schema)


def test_update_schema(instance):
    inst, client = instance
    new_schema = """\
objects:
  person:
    fields:
      name:
        type: str
        required: true
        description: full name
relations: {}
"""
    result = client.admin.update_instance_schema(str(inst.id), new_schema, SchemaType.YML)
    assert result.id


def test_update_metadata(instance):
    inst, client = instance
    updated = client.admin.update_instance_metadata(str(inst.id), "e2e-renamed", "New description")
    assert updated.name == "e2e-renamed"
    assert updated.description == "New description"

    info = client.admin.get_instance(str(inst.id))
    assert info.name == "e2e-renamed"


def test_generate_schema(client):
    clusters = client.admin.list_clusters()
    assert len(clusters) > 0
    cluster_id = str(clusters[0].id)

    result = client.admin.generate_schema(
        cluster_id, "Track people with their name, email, and company they work for"
    )
    assert result.data_schema
    assert "person" in str(result.data_schema).lower()


def test_write_and_read(instance):
    inst, _ = instance
    write_result = inst.write("Alice is a software engineer. Bob is a product manager.")
    assert write_result.write_id

    read_result = inst.read("Who are the people and what are their roles?")
    assert read_result.reader_result is not None


def test_extract(instance):
    inst, _ = instance
    result = inst.extract("Carol is a designer based in Berlin.")
    assert result.objects_extracted is not None


def test_structured_write_lifecycle(instance):
    """create -> update (incl. a None field-clear) -> delete, all LLM-free."""
    inst, _ = instance

    created = inst.write(structured_mutations=[
        {"object_mutation": {"object_type": "person", "create": {
            "key": {"name": "Eve"}, "values": {"role": "analyst", "location": "Lisbon"},
        }}},
    ])
    assert created.write_id
    assert "Eve" in str(created.changes["created"])

    updated = inst.write(structured_mutations=[
        {"object_mutation": {"object_type": "person", "update": {
            "key": {"name": "Eve"}, "values": {"role": "senior analyst", "location": None},
        }}},
    ])
    assert "senior analyst" in str(updated.changes["updated"])

    deleted = inst.write(structured_mutations=[
        {"object_mutation": {"object_type": "person", "delete": {"key": {"name": "Eve"}}}},
    ])
    assert "Eve" in str(deleted.changes["deleted"])


def test_write_async_and_poll(instance):
    inst, _ = instance
    async_result = inst.write_async("Dave is an intern starting next Monday.")
    assert async_result.write_id

    status = inst.write_status(async_result.write_id)
    for _ in range(15):
        if status.write_status.value in ("completed", "failed"):
            break
        time.sleep(2)
        status = inst.write_status(async_result.write_id)
    assert status.write_status.value == "completed"


def test_scoped_write_integrates_instead_of_duplicating(instance):
    """A scope anchors a text write to a known record and confines what it may touch."""
    inst, _ = instance

    inst.write(structured_mutations=[
        {"object_mutation": {"object_type": "person", "create": {
            "key": {"name": "Alice Johnson"}, "values": {"role": "resident", "location": "Boston"},
        }}},
        {"object_mutation": {"object_type": "person", "create": {
            "key": {"name": "Bob Lee"}, "values": {"role": "product manager"},
        }}},
    ])

    scoped = inst.write(
        "After her promotion she is a surgeon.",
        scope=WriteScope(objects=[ScopeObject(type="person", key={"name": "Alice Johnson"})]),
    )
    # The point of the hint: Alice is updated in place rather than forked into a
    # second, near-identical record.
    assert "surgeon" in str(scoped.changes["updated"])
    assert "Alice Johnson" not in str(scoped.changes["created"])


def test_scoped_write_rejects_an_out_of_scope_target(instance):
    """Confinement is checked against the plan, so it holds whatever the extractor produced."""
    inst, _ = instance

    inst.write(structured_mutations=[
        {"object_mutation": {"object_type": "person", "create": {
            "key": {"name": "Alice Johnson"}, "values": {"role": "resident"},
        }}},
        {"object_mutation": {"object_type": "person", "create": {
            "key": {"name": "Bob Lee"}, "values": {"role": "product manager"},
        }}},
    ])

    with pytest.raises(XmemoryAPIError):
        inst.write(
            "Bob Lee is now a director.",
            scope=WriteScope(objects=[ScopeObject(type="person", key={"name": "Alice Johnson"})]),
        )


def test_scoped_write_with_deep_extraction_is_refused_by_the_server(instance):
    """The client forwards the combination rather than pre-judging a server-side rule."""
    inst, _ = instance

    inst.write(structured_mutations=[
        {"object_mutation": {"object_type": "person", "create": {
            "key": {"name": "Alice Johnson"}, "values": {"role": "resident"},
        }}},
    ])

    with pytest.raises(XmemoryAPIError):
        inst.write(
            "She now works in Boston.",
            extraction_logic=ExtractionLogic.DEEP,
            scope=WriteScope(objects=[ScopeObject(type="person", key={"name": "Alice Johnson"})]),
        )


def test_scoped_write_by_xuid_anchors_to_a_keyless_record(keyless_instance):
    """A keyless type has no primary key, so xuid is the only way to scope to it."""
    inst, _ = keyless_instance

    inst.write(structured_mutations=[
        {"object_mutation": {"object_type": "person", "create": {
            "key": {"name": "Alice Johnson"}, "values": {"role": "resident"},
        }}},
    ])
    created = inst.write("A note: the Q3 migration is in progress.")
    xuid = created.changes["created_keyless_objects"][0]["xuid"]

    scoped = inst.write(
        "That work is now complete.",
        scope=WriteScope(objects=[ScopeObject(type="note", xuid=xuid)]),
    )
    assert "complete" in str(scoped.changes["updated"])
    assert scoped.changes["created"]["objects"] == []

    # Confinement still holds when the scope is named by xuid.
    with pytest.raises(XmemoryAPIError):
        inst.write(
            "Alice Johnson is now a surgeon.",
            scope=WriteScope(objects=[ScopeObject(type="note", xuid=xuid)]),
        )

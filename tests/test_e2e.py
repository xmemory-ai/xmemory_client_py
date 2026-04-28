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

from xmemory import XmemoryClient, XmemoryAPIError, SchemaType

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


def test_write_async_and_poll(instance):
    inst, _ = instance
    async_result = inst.write_async("Dave is an intern starting next Monday.")
    assert async_result.write_id

    for _ in range(15):
        status = inst.write_status(async_result.write_id)
        if status.write_status.value in ("completed", "failed"):
            break
        time.sleep(2)
    assert status.write_status.value == "completed"

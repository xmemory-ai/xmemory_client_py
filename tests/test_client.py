"""Unit tests for XmemoryClient / AdminAPI / InstanceAPI."""
from __future__ import annotations

import uuid

import httpx
import pytest
import respx

from xmemory import (
    AsyncXmemoryClient,
    InstanceAPI,
    SchemaType,
    XmemoryAPIError,
    XmemoryClient,
)

CLUSTER_ID = str(uuid.uuid4())
INSTANCE_ID = str(uuid.uuid4())
ORG_ID = str(uuid.uuid4())


def _api_ok(items: list[dict], ids: list[str] | None = None) -> dict:
    return {
        "ids": ids or [item.get("id", str(uuid.uuid4())) for item in items],
        "items": items,
        "errors": [],
    }


@pytest.fixture()
def base_url():
    return "https://api.xmemory.ai"


@pytest.fixture(autouse=True)
def httpx_mock(base_url):
    with respx.mock(base_url=base_url) as mock:
        yield mock


@pytest.fixture()
def client(base_url):
    with XmemoryClient(url=base_url, token="test-token") as c:
        yield c


@pytest.fixture()
async def async_client(base_url):
    async with AsyncXmemoryClient(url=base_url, token="test-token") as c:
        yield c


# ---------------------------------------------------------------------------
# Client construction
# ---------------------------------------------------------------------------


def test_client_default_construction():
    c = XmemoryClient(url="http://localhost:8000")
    c.close()


def test_client_rejects_url_and_http_client():
    with pytest.raises(ValueError):
        XmemoryClient(
            url="http://localhost:8000",
            http_client=httpx.Client(base_url="http://localhost:8000"),
        )


def test_client_context_manager(client):
    assert client.admin is not None


def test_token_passed_in_auth_header(httpx_mock, client):
    route = httpx_mock.get("/clusters").mock(return_value=httpx.Response(200, json=_api_ok([])))

    client.admin.list_clusters()

    assert route.called
    assert route.calls.last.request.headers["authorization"] == "Bearer test-token"


# ---------------------------------------------------------------------------
# Admin — clusters
# ---------------------------------------------------------------------------


def test_admin_list_clusters(httpx_mock, client):
    route = httpx_mock.get("/clusters").mock(return_value=httpx.Response(200, json=_api_ok([
        {"id": CLUSTER_ID, "org_id": ORG_ID, "name": "c1", "description": None},
    ])))

    clusters = client.admin.list_clusters()

    assert len(clusters) == 1
    assert clusters[0].name == "c1"
    assert route.called
    assert "verbose=true" in str(route.calls.last.request.url)


def test_admin_get_cluster(httpx_mock, client):
    route = httpx_mock.get(f"/clusters/{CLUSTER_ID}").mock(return_value=httpx.Response(200, json=_api_ok([
        {"id": CLUSTER_ID, "org_id": ORG_ID, "name": "c1", "description": "desc"},
    ])))

    cluster = client.admin.get_cluster(CLUSTER_ID)

    assert cluster.description == "desc"
    assert route.called


# ---------------------------------------------------------------------------
# Admin — instances
# ---------------------------------------------------------------------------


def test_admin_create_instance_returns_instance_api(httpx_mock, client):
    route = httpx_mock.post(f"/clusters/{CLUSTER_ID}/instances").mock(return_value=httpx.Response(201, json=_api_ok([
        {"id": INSTANCE_ID, "cluster_id": CLUSTER_ID, "name": "my-inst", "description": None},
    ])))

    inst = client.admin.create_instance(CLUSTER_ID, "my-inst", "tables: []", SchemaType.YML)

    assert isinstance(inst, InstanceAPI)
    assert inst.id == INSTANCE_ID
    assert route.called
    assert b'"name":"my-inst"' in route.calls.last.request.content


def test_admin_list_instances(httpx_mock, client):
    route = httpx_mock.get("/instances").mock(return_value=httpx.Response(200, json=_api_ok([
        {"id": INSTANCE_ID, "cluster_id": CLUSTER_ID, "name": "inst", "description": None},
    ])))

    instances = client.admin.list_instances()

    assert len(instances) == 1
    assert route.called


def test_admin_get_instance(httpx_mock, client):
    route = httpx_mock.get(f"/instances/{INSTANCE_ID}").mock(return_value=httpx.Response(200, json=_api_ok([
        {"id": INSTANCE_ID, "cluster_id": CLUSTER_ID, "name": "inst", "description": "d"},
    ])))

    info = client.admin.get_instance(INSTANCE_ID)

    assert info.description == "d"
    assert route.called


def test_admin_generate_schema(httpx_mock, client):
    route = httpx_mock.post(f"/clusters/{CLUSTER_ID}/instances/generate_schema").mock(
        return_value=httpx.Response(200, json=_api_ok([
            {"data_schema": {"tables": []}},
        ])),
    )

    result = client.admin.generate_schema(CLUSTER_ID, "a CRM")

    assert result.data_schema == {"tables": []}
    assert route.called
    assert b'"schema_description":"a CRM"' in route.calls.last.request.content


# ---------------------------------------------------------------------------
# InstanceAPI — data operations
# ---------------------------------------------------------------------------


def test_instance_read(httpx_mock, client):
    route = httpx_mock.post(f"/instances/{INSTANCE_ID}/read").mock(return_value=httpx.Response(200, json=_api_ok([
        {"trace_id": "r-1", "reader_result": {"answer": "An engineer"}},
    ])))

    resp = client.instance(INSTANCE_ID).read("Who is Bob?")

    assert resp.reader_result == {"answer": "An engineer"}
    assert route.called
    assert b'"query":"Who is Bob?"' in route.calls.last.request.content
    assert b'"mode":"single-answer"' in route.calls.last.request.content


def test_instance_write(httpx_mock, client):
    route = httpx_mock.post(f"/instances/{INSTANCE_ID}/write").mock(return_value=httpx.Response(200, json=_api_ok([
        {"write_id": "w-1", "trace_id": "ew-1", "cleaned_objects": []},
    ])))

    resp = client.instance(INSTANCE_ID).write("Bob is an engineer.")

    assert resp.write_id == "w-1"
    assert route.called
    assert b'"text":"Bob is an engineer."' in route.calls.last.request.content
    assert b'"extraction_logic":"deep"' in route.calls.last.request.content


def test_instance_write_async(httpx_mock, client):
    route = httpx_mock.post(f"/instances/{INSTANCE_ID}/write_async").mock(
        return_value=httpx.Response(200, json=_api_ok([{"write_id": "w-async-1"}])),
    )

    resp = client.instance(INSTANCE_ID).write_async("some text")

    assert resp.write_id == "w-async-1"
    assert route.called


def test_instance_write_status(httpx_mock, client):
    route = httpx_mock.post(f"/instances/{INSTANCE_ID}/write_status").mock(
        return_value=httpx.Response(200, json=_api_ok([
            {"write_id": "w-1", "write_status": "completed", "error_detail": None, "completed_at": None},
        ])),
    )

    resp = client.instance(INSTANCE_ID).write_status("w-1")

    assert resp.write_status.value == "completed"
    assert route.called
    assert b'"write_id":"w-1"' in route.calls.last.request.content


def test_instance_extract(httpx_mock, client):
    route = httpx_mock.post(f"/instances/{INSTANCE_ID}/extract").mock(return_value=httpx.Response(200, json=_api_ok([
        {"trace_id": "ew-1", "objects_extracted": {"objects": []}},
    ])))

    resp = client.instance(INSTANCE_ID).extract("Bob is an engineer.")

    assert resp.trace_id == "ew-1"
    assert route.called


# ---------------------------------------------------------------------------
# InstanceAPI — instance management
# ---------------------------------------------------------------------------


def test_admin_get_instance_schema(httpx_mock, client):
    route = httpx_mock.get(f"/instances/{INSTANCE_ID}/schema").mock(
        return_value=httpx.Response(200, json=_api_ok([{"data_schema": {"tables": []}}])),
    )

    schema = client.admin.get_instance_schema(INSTANCE_ID)

    assert schema.data_schema == {"tables": []}
    assert route.called


def test_admin_update_instance_schema(httpx_mock, client):
    route = httpx_mock.put(f"/instances/{INSTANCE_ID}/schema").mock(return_value=httpx.Response(200, json=_api_ok([
        {"id": INSTANCE_ID, "cluster_id": CLUSTER_ID, "name": "inst", "description": None},
    ])))

    result = client.admin.update_instance_schema(INSTANCE_ID, "tables: []", SchemaType.YML)

    assert str(result.id) == INSTANCE_ID
    assert route.called


def test_admin_update_instance_metadata(httpx_mock, client):
    route = httpx_mock.put(f"/instances/{INSTANCE_ID}").mock(return_value=httpx.Response(200, json=_api_ok([
        {"id": INSTANCE_ID, "cluster_id": CLUSTER_ID, "name": "new-name", "description": "new-desc"},
    ])))

    result = client.admin.update_instance_metadata(INSTANCE_ID, "new-name", "new-desc")

    assert result.name == "new-name"
    assert route.called
    assert b'"name":"new-name"' in route.calls.last.request.content


def test_admin_delete_instance(httpx_mock, client):
    route = httpx_mock.delete(f"/instances/{INSTANCE_ID}").mock(
        return_value=httpx.Response(200, json={"ids": [INSTANCE_ID], "items": [], "errors": []}),
    )

    deleted = client.admin.delete_instance(INSTANCE_ID)

    assert len(deleted) == 1
    assert route.called


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


def test_api_error_from_errors_field_2xx(httpx_mock, client):
    """Errors in the wrapper body on a 200 response."""
    httpx_mock.get(f"/clusters/{CLUSTER_ID}").mock(return_value=httpx.Response(200, json={
        "ids": [], "items": [],
        "errors": [{"code": "NOT_FOUND", "message": "Resource not found"}],
    }))

    with pytest.raises(XmemoryAPIError, match="Resource not found"):
        client.admin.get_cluster(CLUSTER_ID)


def test_api_error_from_errors_field_non_2xx(httpx_mock, client):
    """Structured errors in a non-2xx response body are preferred over raw HTTP text."""
    httpx_mock.get(f"/clusters/{CLUSTER_ID}").mock(return_value=httpx.Response(404, json={
        "ids": [], "items": [],
        "errors": [{"code": "NOT_FOUND", "message": "Resource not found"}],
    }))

    with pytest.raises(XmemoryAPIError, match="failed: Resource not found"):
        client.admin.get_cluster(CLUSTER_ID)


def test_api_error_from_http_status(httpx_mock, client):
    """Plain text error without structured body falls back to HTTP status."""
    httpx_mock.get("/clusters").mock(return_value=httpx.Response(500, text="Internal Server Error"))

    with pytest.raises(XmemoryAPIError, match="500"):
        client.admin.list_clusters()


def test_api_error_empty_items(httpx_mock, client):
    """Success response with no items raises an error."""
    httpx_mock.get(f"/instances/{INSTANCE_ID}").mock(return_value=httpx.Response(200, json={
        "ids": [], "items": [], "errors": [],
    }))

    with pytest.raises(XmemoryAPIError, match="returned no items"):
        client.admin.get_instance(INSTANCE_ID)


# ---------------------------------------------------------------------------
# Async
# ---------------------------------------------------------------------------


async def test_async_admin_list_clusters(httpx_mock, async_client):
    route = httpx_mock.get("/clusters").mock(return_value=httpx.Response(200, json=_api_ok([
        {"id": CLUSTER_ID, "org_id": ORG_ID, "name": "async-c", "description": None},
    ])))

    clusters = await async_client.admin.list_clusters()

    assert clusters[0].name == "async-c"
    assert route.called


async def test_async_instance_read(httpx_mock, async_client):
    route = httpx_mock.post(f"/instances/{INSTANCE_ID}/read").mock(return_value=httpx.Response(200, json=_api_ok([
        {"trace_id": "r-1", "reader_result": {"answer": "async answer"}},
    ])))

    resp = await async_client.instance(INSTANCE_ID).read("test query")

    assert resp.reader_result == {"answer": "async answer"}
    assert route.called


async def test_async_create_instance_returns_async_instance_api(httpx_mock, async_client):
    route = httpx_mock.post(f"/clusters/{CLUSTER_ID}/instances").mock(return_value=httpx.Response(201, json=_api_ok([
        {"id": INSTANCE_ID, "cluster_id": CLUSTER_ID, "name": "inst", "description": None},
    ])))

    inst = await async_client.admin.create_instance(CLUSTER_ID, "inst", "tables: []", SchemaType.YML)

    assert inst.id == INSTANCE_ID
    assert route.called

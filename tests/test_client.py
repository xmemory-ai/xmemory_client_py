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
    with XmemoryClient(url=base_url, api_key="test-api-key") as c:
        yield c


@pytest.fixture()
async def async_client(base_url):
    async with AsyncXmemoryClient(url=base_url, api_key="test-api-key") as c:
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


def test_api_key_passed_in_auth_header(httpx_mock, client):
    route = httpx_mock.get("/clusters").mock(return_value=httpx.Response(200, json=_api_ok([])))

    client.admin.list_clusters()

    assert route.called
    assert route.calls.last.request.headers["authorization"] == "Bearer test-api-key"


# ---------------------------------------------------------------------------
# Legacy `token` term — accepted with a deprecation notice
# ---------------------------------------------------------------------------


def test_legacy_token_argument_warns_and_still_works(httpx_mock, base_url, capsys):
    """Passing ``token=`` (legacy) must still authenticate but print an
    orange-colored deprecation notice naming the legacy term."""
    route = httpx_mock.get("/clusters").mock(return_value=httpx.Response(200, json=_api_ok([])))

    with XmemoryClient(url=base_url, token="legacy-value") as c:
        c.admin.list_clusters()

    err = capsys.readouterr().err
    assert "DeprecationWarning" in err
    assert "token" in err
    assert "\033[38;5;208m" in err  # orange ANSI prefix
    assert route.calls.last.request.headers["authorization"] == "Bearer legacy-value"


def test_legacy_token_env_var_warns_and_still_works(httpx_mock, base_url, monkeypatch, capsys):
    """``XMEM_AUTH_TOKEN`` is the legacy env var; it must still work but warn."""
    monkeypatch.delenv("XMEM_API_KEY", raising=False)
    monkeypatch.setenv("XMEM_AUTH_TOKEN", "legacy-env-value")
    route = httpx_mock.get("/clusters").mock(return_value=httpx.Response(200, json=_api_ok([])))

    with XmemoryClient(url=base_url) as c:
        c.admin.list_clusters()

    err = capsys.readouterr().err
    assert "DeprecationWarning" in err
    assert "XMEM_AUTH_TOKEN" in err
    assert "\033[38;5;208m" in err
    assert route.calls.last.request.headers["authorization"] == "Bearer legacy-env-value"


def test_api_key_argument_takes_precedence_over_legacy_token(base_url, capsys):
    """``api_key=`` wins over ``token=`` and silences the deprecation notice."""
    with XmemoryClient(url=base_url, api_key="new-value", token="old-value"):
        pass

    err = capsys.readouterr().err
    assert "DeprecationWarning" not in err


def test_new_env_var_preferred_over_legacy(httpx_mock, base_url, monkeypatch, capsys):
    """``XMEM_API_KEY`` is checked before ``XMEM_AUTH_TOKEN`` (no warning)."""
    monkeypatch.setenv("XMEM_API_KEY", "new-env-value")
    monkeypatch.setenv("XMEM_AUTH_TOKEN", "legacy-env-value")
    route = httpx_mock.get("/clusters").mock(return_value=httpx.Response(200, json=_api_ok([])))

    with XmemoryClient(url=base_url) as c:
        c.admin.list_clusters()

    err = capsys.readouterr().err
    assert "DeprecationWarning" not in err
    assert route.calls.last.request.headers["authorization"] == "Bearer new-env-value"


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
    assert resp.reader_results == []
    assert route.called
    assert b'"query":"Who is Bob?"' in route.calls.last.request.content
    assert b'"mode":"single-answer"' in route.calls.last.request.content


def test_instance_read_decomposed(httpx_mock, client):
    httpx_mock.post(f"/instances/{INSTANCE_ID}/read").mock(return_value=httpx.Response(200, json=_api_ok([
        {
            "trace_id": "r-1",
            "reader_result": "combined answer",
            "reader_results": [
                {"sub_query": "Who is Bob?", "reader_result": "An engineer"},
                {"sub_query": "Who is Ann?", "reader_result": "", "error": "no data"},
            ],
        },
    ])))

    resp = client.instance(INSTANCE_ID).read("Who are Bob and Ann?")

    assert resp.reader_result == "combined answer"
    assert [r.sub_query for r in resp.reader_results] == ["Who is Bob?", "Who is Ann?"]
    assert resp.reader_results[0].reader_result == "An engineer"
    assert resp.reader_results[0].error is None
    assert resp.reader_results[1].error == "no data"


def test_instance_describe_exposes_about(httpx_mock, client):
    route = httpx_mock.get(f"/instances/{INSTANCE_ID}/describe").mock(return_value=httpx.Response(200, json=_api_ok([
        {
            "instance_id": INSTANCE_ID,
            "instance_name": "Test Instance",
            "about": "xmemory is a first-party memory store.",
            "schema_summary": "",
            "tools": [],
        },
    ])))

    result = client.instance(INSTANCE_ID).describe()

    assert result.about == "xmemory is a first-party memory store."
    assert "xmemory is a first-party memory store." in result.as_text()
    assert route.called


def test_instance_describe_about_defaults_when_absent(httpx_mock, client):
    """A response from an older server without ``about`` still parses."""
    httpx_mock.get(f"/instances/{INSTANCE_ID}/describe").mock(return_value=httpx.Response(200, json=_api_ok([
        {"instance_id": INSTANCE_ID, "instance_name": "Test Instance", "schema_summary": "", "tools": []},
    ])))

    result = client.instance(INSTANCE_ID).describe()

    assert result.about == ""


def test_instance_write(httpx_mock, client):
    route = httpx_mock.post(f"/instances/{INSTANCE_ID}/write").mock(return_value=httpx.Response(200, json=_api_ok([
        {
            "write_id": "w-1",
            "trace_id": "ew-1",
            "cleaned_objects": [],
            "changes": {
                "created": {"objects": [{"name": "Person", "identifier": "name='Bob'", "fields": []}], "relations": []},
                "updated": [],
                "deleted": {"objects": [], "relations": []},
            },
        },
    ])))

    resp = client.instance(INSTANCE_ID).write("Bob is an engineer.")

    assert resp.write_id == "w-1"
    assert resp.changes["created"]["objects"][0]["identifier"] == "name='Bob'"
    # ``cleaned_objects`` is no longer exposed even though the server still sends it.
    assert not hasattr(resp, "cleaned_objects")
    assert route.called
    assert b'"text":"Bob is an engineer."' in route.calls.last.request.content
    assert b'"extraction_logic":"fast"' in route.calls.last.request.content


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


def test_api_error_from_errors_field_2xx_surfaces_details_and_retry_after(httpx_mock, client):
    """A 200 wrapper-body error still surfaces structured ``details`` and the
    HTTP ``Retry-After`` header on the raised error (the ``_parse`` path, not the
    non-2xx ``raise_for_status`` path)."""
    httpx_mock.get(f"/clusters/{CLUSTER_ID}").mock(return_value=httpx.Response(
        200,
        json={
            "ids": [], "items": [],
            "errors": [{
                "code": "QUOTA_EXCEEDED",
                "message": "Daily token quota exhausted.",
                "details": {"kind": "daily_quota_exceeded", "retry_after_seconds": 3600},
            }],
        },
        headers={"Retry-After": "3600"},
    ))

    with pytest.raises(XmemoryAPIError) as exc:
        client.admin.get_cluster(CLUSTER_ID)

    assert exc.value.code == "QUOTA_EXCEEDED"
    assert exc.value.details == {"kind": "daily_quota_exceeded", "retry_after_seconds": 3600}
    assert exc.value.retry_after == 3600


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


def test_quota_exceeded_402_surfaces_code_details_and_retry_after(httpx_mock, client):
    """402 QUOTA_EXCEEDED carries kind/retry_after_seconds in ``details`` and the
    HTTP ``Retry-After`` header is surfaced on ``retry_after``. Non-retryable —
    callers branch on ``code``, not the bare 402 status."""
    httpx_mock.get(f"/instances/{INSTANCE_ID}/schema").mock(return_value=httpx.Response(
        402,
        json={"errors": [{
            "code": "QUOTA_EXCEEDED",
            "message": "Daily token quota exhausted.",
            "details": {"kind": "daily_quota_exceeded", "retry_after_seconds": 3600},
        }]},
        headers={"Retry-After": "3600"},
    ))

    with pytest.raises(XmemoryAPIError) as exc:
        client.admin.get_instance_schema(INSTANCE_ID)

    assert exc.value.status == 402
    assert exc.value.code == "QUOTA_EXCEEDED"
    assert exc.value.details == {"kind": "daily_quota_exceeded", "retry_after_seconds": 3600}
    assert exc.value.retry_after == 3600


def test_trial_ended_402_surfaces_code_without_details(httpx_mock, client):
    """402 TRIAL_ENDED may carry no ``details`` (paywall-gate variant). Still
    distinguishable from QUOTA_EXCEEDED via ``code``."""
    httpx_mock.get(f"/clusters/{CLUSTER_ID}").mock(return_value=httpx.Response(
        402,
        json={"errors": [{"code": "TRIAL_ENDED", "message": "Trial has ended."}]},
    ))

    with pytest.raises(XmemoryAPIError) as exc:
        client.admin.get_cluster(CLUSTER_ID)

    assert exc.value.status == 402
    assert exc.value.code == "TRIAL_ENDED"
    assert exc.value.details is None
    assert exc.value.retry_after is None


def test_rate_limited_429_surfaces_code_and_retry_after(httpx_mock, client):
    """429 RATE_LIMITED is the genuine velocity limit (retryable with backoff);
    its ``Retry-After`` header is surfaced on ``retry_after``."""
    httpx_mock.get("/clusters").mock(return_value=httpx.Response(
        429,
        json={"errors": [{"code": "RATE_LIMITED", "message": "Too many requests."}]},
        headers={"Retry-After": "5"},
    ))

    with pytest.raises(XmemoryAPIError) as exc:
        client.admin.list_clusters()

    assert exc.value.status == 429
    assert exc.value.code == "RATE_LIMITED"
    assert exc.value.retry_after == 5


def test_rate_limited_429_negative_retry_after_clamped_to_zero(httpx_mock, client):
    """A negative ``Retry-After`` (e.g. clock skew) is clamped to 0, not passed
    through — callers can back off by ``retry_after`` without going negative."""
    httpx_mock.get("/clusters").mock(return_value=httpx.Response(
        429,
        json={"errors": [{"code": "RATE_LIMITED", "message": "Too many requests."}]},
        headers={"Retry-After": "-5"},
    ))

    with pytest.raises(XmemoryAPIError) as exc:
        client.admin.list_clusters()

    assert exc.value.status == 429
    assert exc.value.retry_after == 0


def test_rate_limited_429_http_date_retry_after_yields_none(httpx_mock, client):
    """The HTTP-date form of ``Retry-After`` is not parsed to an int; only the
    delta-seconds form populates ``retry_after`` (date form yields ``None``)."""
    httpx_mock.get("/clusters").mock(return_value=httpx.Response(
        429,
        json={"errors": [{"code": "RATE_LIMITED", "message": "Too many requests."}]},
        headers={"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"},
    ))

    with pytest.raises(XmemoryAPIError) as exc:
        client.admin.list_clusters()

    assert exc.value.status == 429
    assert exc.value.retry_after is None


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


def test_scope_serializes_to_canonical_wire_shape() -> None:
    """ReadScope/ScopeObject must emit the API's identity-ADT + relations_scope shape."""
    from xmemory import ReadScope, ScopeObject
    from xmemory._models import ReadMode, _ReadRequest

    scope = ReadScope(
        objects=[
            ScopeObject(type="Person", key={"name": "Alice"}),
            ScopeObject(type="Pet", key={"name": "Rex"}),
        ],
        relations_scope="all_relations",
    )
    body = _ReadRequest(query="q", mode=ReadMode.SINGLE_ANSWER, scope=scope).model_dump(
        by_alias=True, exclude_none=True
    )
    assert body["scope"] == {
        "objects": [
            {"type": "Person", "key": {"key": {"name": "Alice"}}},
            {"type": "Pet", "key": {"key": {"name": "Rex"}}},
        ],
        "relations_scope": "all_relations",
    }


def test_scope_defaults_to_no_relations() -> None:
    from xmemory import ReadScope, ScopeObject

    assert ReadScope(objects=[ScopeObject(type="Person", key={"name": "Bob"})]).relations_scope == "no_relations"


def test_scope_object_requires_a_non_empty_key() -> None:
    from xmemory import ScopeObject

    with pytest.raises(Exception):
        ScopeObject(type="Person")  # type: ignore[call-arg]  # key is required
    with pytest.raises(Exception):
        ScopeObject(type="Person", key={})

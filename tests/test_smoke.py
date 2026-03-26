"""Smoke tests — no live server required."""

import pytest
import httpx

from xmemory import (
    XmemoryAPI,
    AsyncXmemoryAPI,
    xmemory_instance,
    async_xmemory_instance,
    ExtractionLogic,
    ReadMode,
    SchemaType,
    XmemoryAPIError,
)


# ---------------------------------------------------------------------------
# Client construction
# ---------------------------------------------------------------------------


def test_sync_client_default_url():
    client = XmemoryAPI(instance_id="test-id")
    assert str(client.base_url).rstrip("/") == "https://api.xmemory.ai"
    client.close()


def test_sync_client_custom_url():
    client = XmemoryAPI(url="http://localhost:8000", instance_id="test-id")
    assert "localhost" in str(client.base_url)
    client.close()


def test_sync_client_rejects_url_and_http_client():
    with pytest.raises(XmemoryAPIError):
        XmemoryAPI(
            url="http://localhost:8000",
            http_client=httpx.Client(base_url="http://localhost:8000"),
        )


def test_sync_client_rejects_http_client_without_base_url():
    with pytest.raises(XmemoryAPIError):
        XmemoryAPI(http_client=httpx.Client())


def test_sync_client_rejects_wrong_http_client_type():
    with pytest.raises(XmemoryAPIError):
        XmemoryAPI(http_client="not-a-client")  # type: ignore


def test_xmemory_instance_factory():
    client = xmemory_instance(url="http://localhost:8000", instance_id="abc")
    assert client.instance_id == "abc"
    client.close()


async def test_async_client_default_url():
    client = AsyncXmemoryAPI(instance_id="test-id")
    assert str(client.base_url).rstrip("/") == "https://api.xmemory.ai"
    await client.aclose()


async def test_async_xmemory_instance_factory():
    client = async_xmemory_instance(url="http://localhost:8000", instance_id="abc")
    assert client.instance_id == "abc"
    await client.aclose()


# ---------------------------------------------------------------------------
# Context managers
# ---------------------------------------------------------------------------


def test_sync_context_manager():
    with xmemory_instance(url="http://localhost:8000", instance_id="abc") as client:
        assert client.instance_id == "abc"


async def test_async_context_manager():
    async with async_xmemory_instance(url="http://localhost:8000", instance_id="abc") as client:
        assert client.instance_id == "abc"


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


def test_extraction_logic_values():
    assert ExtractionLogic.FAST == "fast"
    assert ExtractionLogic.REGULAR == "regular"
    assert ExtractionLogic.DEEP == "deep"


def test_read_mode_values():
    assert ReadMode.SINGLE_ANSWER == "single-answer"
    assert ReadMode.RAW_TABLES == "raw-tables"
    assert ReadMode.XRESPONSE == "xresponse"


def test_schema_type_values():
    assert SchemaType.YML.value == 0
    assert SchemaType.JSON.value == 1


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


def test_api_error_carries_status():
    err = XmemoryAPIError("something went wrong", status=404)
    assert err.status == 404
    assert "something went wrong" in str(err)


def test_api_error_without_status():
    err = XmemoryAPIError("oops")
    assert err.status is None

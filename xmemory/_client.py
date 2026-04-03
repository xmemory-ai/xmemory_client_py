from __future__ import annotations

import os

import httpx

from xmemory._admin import AdminAPI, AsyncAdminAPI
from xmemory._exceptions import XmemoryAPIError, XmemoryHealthCheckError
from xmemory._instance import AsyncInstanceAPI, InstanceAPI
from xmemory._transport import AsyncTransport, SyncTransport


class XmemoryClient:
    """Synchronous Xmemory client with admin/instance namespaces.

    Usage::

        client = XmemoryClient(token="xmem_...")

        # Admin operations
        clusters = client.admin.list_clusters()
        inst = client.admin.create_instance(cluster_id, "name", schema, SchemaType.YML)

        # Instance-bound data operations
        inst.write("Bob is an engineer.")
        result = inst.read("Who is Bob?")

        # Bind to an existing instance
        inst = client.instance("abc-123")
    """

    def __init__(
        self,
        url: str | None = None,
        *,
        timeout: float = 60,
        token: str | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        token = token or os.environ.get("XMEM_AUTH_TOKEN")

        if http_client is not None:
            if not isinstance(http_client, httpx.Client):
                raise XmemoryAPIError("http_client must be an instance of httpx.Client")
            if url is not None:
                raise XmemoryAPIError("Cannot specify both 'url' and 'http_client' — set base_url on the client directly")
            if not http_client.base_url.host:
                raise XmemoryAPIError("http_client must have base_url set — or omit it and pass url= instead")
            self._client = http_client
            self._owns_client = False
        else:
            base = url or os.environ.get("XMEM_API_URL") or "https://api.xmemory.ai"
            self._client = httpx.Client(base_url=base, timeout=timeout)
            self._owns_client = True

        self._transport = SyncTransport(self._client, token, timeout)
        self._admin = AdminAPI(self._transport)

    @property
    def admin(self) -> AdminAPI:
        """Cluster and instance lifecycle management."""
        return self._admin

    def instance(self, instance_id: str) -> InstanceAPI:
        """Bind to an existing instance by ID."""
        return InstanceAPI(instance_id, self._transport)

    def check_health(self) -> None:
        """Verify the API server is reachable. Raises XmemoryHealthCheckError on failure."""
        try:
            resp = self._client.get("/healthz", timeout=self._transport.timeout)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise XmemoryHealthCheckError(
                "Health check HTTP error " + str(e.response.status_code),
                status=e.response.status_code,
            ) from e
        except httpx.ConnectError as e:
            raise XmemoryHealthCheckError("Health check connection error: " + str(e)) from e
        except Exception as e:
            raise XmemoryHealthCheckError("Health check failed: " + str(e)) from e

    def close(self) -> None:
        """Close the underlying HTTP client. No-op if the client was externally provided."""
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> XmemoryClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


class AsyncXmemoryClient:
    """Asynchronous Xmemory client with admin/instance namespaces.

    Usage::

        async with AsyncXmemoryClient(token="xmem_...") as client:
            clusters = await client.admin.list_clusters()
            inst = await client.admin.create_instance(cluster_id, "name", schema, SchemaType.YML)
            await inst.write("Bob is an engineer.")
    """

    def __init__(
        self,
        url: str | None = None,
        *,
        timeout: float = 60,
        token: str | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        token = token or os.environ.get("XMEM_AUTH_TOKEN")

        if http_client is not None:
            if not isinstance(http_client, httpx.AsyncClient):
                raise XmemoryAPIError("http_client must be an instance of httpx.AsyncClient")
            if url is not None:
                raise XmemoryAPIError("Cannot specify both 'url' and 'http_client' — set base_url on the client directly")
            if not http_client.base_url.host:
                raise XmemoryAPIError("http_client must have base_url set — or omit it and pass url= instead")
            self._client = http_client
            self._owns_client = False
        else:
            base = url or os.environ.get("XMEM_API_URL") or "https://api.xmemory.ai"
            self._client = httpx.AsyncClient(base_url=base, timeout=timeout)
            self._owns_client = True

        self._transport = AsyncTransport(self._client, token, timeout)
        self._admin = AsyncAdminAPI(self._transport)

    @property
    def admin(self) -> AsyncAdminAPI:
        """Cluster and instance lifecycle management."""
        return self._admin

    def instance(self, instance_id: str) -> AsyncInstanceAPI:
        """Bind to an existing instance by ID."""
        return AsyncInstanceAPI(instance_id, self._transport)

    async def check_health(self) -> None:
        """Verify the API server is reachable. Raises XmemoryHealthCheckError on failure."""
        try:
            resp = await self._client.get("/healthz", timeout=self._transport.timeout)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise XmemoryHealthCheckError(
                "Health check HTTP error " + str(e.response.status_code),
                status=e.response.status_code,
            ) from e
        except httpx.ConnectError as e:
            raise XmemoryHealthCheckError("Health check connection error: " + str(e)) from e
        except Exception as e:
            raise XmemoryHealthCheckError("Health check failed: " + str(e)) from e

    async def aclose(self) -> None:
        """Close the underlying HTTP client. No-op if the client was externally provided."""
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> AsyncXmemoryClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

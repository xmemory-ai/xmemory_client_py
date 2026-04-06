from __future__ import annotations

import uuid
from typing import Any

from xmemory._instance import AsyncInstanceAPI, InstanceAPI
from xmemory._models import (
    ClusterInfo,
    GenerateSchemaResult,
    InstanceInfo,
    InstanceSchemaInfo,
    SchemaType,
    _CreateInstanceRequest,
    _GenerateSchemaRequest,
    _UpdateMetadataRequest,
    _UpdateSchemaRequest,
    build_instance_schema,
)
from xmemory._transport import AsyncTransport, SyncTransport


class AdminAPI:
    """Cluster and instance lifecycle management (sync)."""

    def __init__(self, transport: SyncTransport) -> None:
        self._t = transport

    # -- Clusters -------------------------------------------------------------

    def list_clusters(
        self, *, ids: list[str] | None = None, timeout: float | None = None,
    ) -> list[ClusterInfo]:
        """List clusters accessible to the caller."""
        params: dict[str, Any] = {"verbose": "true"}
        if ids is not None:
            params["ids"] = ids
        return self._t.request_list("GET", "/clusters", ClusterInfo, params=params, timeout=timeout)

    def get_cluster(self, cluster_id: str, *, timeout: float | None = None) -> ClusterInfo:
        """Get a single cluster by ID."""
        return self._t.request_one("GET", f"/clusters/{cluster_id}", ClusterInfo, timeout=timeout)

    # -- Instances ------------------------------------------------------------

    def create_instance(
        self,
        cluster_id: str,
        name: str,
        schema_text: str,
        schema_type: SchemaType,
        *,
        description: str | None = None,
        schema_description: str | None = None,
        timeout: float | None = None,
    ) -> InstanceAPI:
        """Create a new instance inside a cluster. Returns a bound InstanceAPI."""
        info = self._t.request_one(
            "POST",
            f"/clusters/{cluster_id}/instances",
            InstanceInfo,
            body=_CreateInstanceRequest(
                name=name,
                description=description,
                instance_schema=build_instance_schema(schema_text, schema_type),
                schema_description=schema_description,
            ),
            timeout=timeout,
        )
        return InstanceAPI(str(info.id), self._t)

    def list_instances(
        self, *, ids: list[str] | None = None, timeout: float | None = None,
    ) -> list[InstanceInfo]:
        """List instances accessible to the caller."""
        params: dict[str, Any] = {"verbose": "true"}
        if ids is not None:
            params["ids"] = ids
        return self._t.request_list("GET", "/instances", InstanceInfo, params=params, timeout=timeout)

    def get_instance(self, instance_id: str, *, timeout: float | None = None) -> InstanceInfo:
        """Get a single instance by ID."""
        return self._t.request_one("GET", f"/instances/{instance_id}", InstanceInfo, timeout=timeout)

    def generate_schema(
        self,
        cluster_id: str,
        schema_description: str,
        *,
        current_yml_schema: str | None = None,
        timeout: float | None = None,
    ) -> GenerateSchemaResult:
        """Generate a schema from a natural language description."""
        return self._t.request_one(
            "POST",
            f"/clusters/{cluster_id}/instances/generate_schema",
            GenerateSchemaResult,
            body=_GenerateSchemaRequest(
                schema_description=schema_description,
                current_yml_schema=current_yml_schema,
            ),
            timeout=timeout,
        )

    def get_instance_schema(self, instance_id: str, *, timeout: float | None = None) -> InstanceSchemaInfo:
        """Get the current schema of an instance."""
        return self._t.request_one("GET", f"/instances/{instance_id}/schema", InstanceSchemaInfo, timeout=timeout)

    def update_instance_schema(
        self, instance_id: str, schema_text: str, schema_type: SchemaType, *, timeout: float | None = None,
    ) -> InstanceInfo:
        """Replace the schema of an instance."""
        return self._t.request_one(
            "PUT", f"/instances/{instance_id}/schema", InstanceInfo,
            body=_UpdateSchemaRequest(instance_schema=build_instance_schema(schema_text, schema_type)),
            timeout=timeout,
        )

    def update_instance_metadata(
        self, instance_id: str, name: str, description: str | None, *, timeout: float | None = None,
    ) -> InstanceInfo:
        """Update the name and description of an instance."""
        return self._t.request_one(
            "PUT", f"/instances/{instance_id}", InstanceInfo,
            body=_UpdateMetadataRequest(name=name, description=description),
            timeout=timeout,
        )

    def delete_instance(self, instance_id: str, *, timeout: float | None = None) -> list[uuid.UUID]:
        """Delete an instance by ID. Returns the list of deleted IDs."""
        return self._t.request_ids("DELETE", f"/instances/{instance_id}", timeout=timeout)


class AsyncAdminAPI:
    """Cluster and instance lifecycle management (async)."""

    def __init__(self, transport: AsyncTransport) -> None:
        self._t = transport

    # -- Clusters -------------------------------------------------------------

    async def list_clusters(
        self, *, ids: list[str] | None = None, timeout: float | None = None,
    ) -> list[ClusterInfo]:
        """List clusters accessible to the caller."""
        params: dict[str, Any] = {"verbose": "true"}
        if ids is not None:
            params["ids"] = ids
        return await self._t.request_list("GET", "/clusters", ClusterInfo, params=params, timeout=timeout)

    async def get_cluster(self, cluster_id: str, *, timeout: float | None = None) -> ClusterInfo:
        """Get a single cluster by ID."""
        return await self._t.request_one("GET", f"/clusters/{cluster_id}", ClusterInfo, timeout=timeout)

    # -- Instances ------------------------------------------------------------

    async def create_instance(
        self,
        cluster_id: str,
        name: str,
        schema_text: str,
        schema_type: SchemaType,
        *,
        description: str | None = None,
        schema_description: str | None = None,
        timeout: float | None = None,
    ) -> AsyncInstanceAPI:
        """Create a new instance inside a cluster. Returns a bound AsyncInstanceAPI."""
        info = await self._t.request_one(
            "POST",
            f"/clusters/{cluster_id}/instances",
            InstanceInfo,
            body=_CreateInstanceRequest(
                name=name,
                description=description,
                instance_schema=build_instance_schema(schema_text, schema_type),
                schema_description=schema_description,
            ),
            timeout=timeout,
        )
        return AsyncInstanceAPI(str(info.id), self._t)

    async def list_instances(
        self, *, ids: list[str] | None = None, timeout: float | None = None,
    ) -> list[InstanceInfo]:
        """List instances accessible to the caller."""
        params: dict[str, Any] = {"verbose": "true"}
        if ids is not None:
            params["ids"] = ids
        return await self._t.request_list("GET", "/instances", InstanceInfo, params=params, timeout=timeout)

    async def get_instance(self, instance_id: str, *, timeout: float | None = None) -> InstanceInfo:
        """Get a single instance by ID."""
        return await self._t.request_one("GET", f"/instances/{instance_id}", InstanceInfo, timeout=timeout)

    async def generate_schema(
        self,
        cluster_id: str,
        schema_description: str,
        *,
        current_yml_schema: str | None = None,
        timeout: float | None = None,
    ) -> GenerateSchemaResult:
        """Generate a schema from a natural language description."""
        return await self._t.request_one(
            "POST",
            f"/clusters/{cluster_id}/instances/generate_schema",
            GenerateSchemaResult,
            body=_GenerateSchemaRequest(
                schema_description=schema_description,
                current_yml_schema=current_yml_schema,
            ),
            timeout=timeout,
        )

    async def get_instance_schema(self, instance_id: str, *, timeout: float | None = None) -> InstanceSchemaInfo:
        """Get the current schema of an instance."""
        return await self._t.request_one("GET", f"/instances/{instance_id}/schema", InstanceSchemaInfo, timeout=timeout)

    async def update_instance_schema(
        self, instance_id: str, schema_text: str, schema_type: SchemaType, *, timeout: float | None = None,
    ) -> InstanceInfo:
        """Replace the schema of an instance."""
        return await self._t.request_one(
            "PUT", f"/instances/{instance_id}/schema", InstanceInfo,
            body=_UpdateSchemaRequest(instance_schema=build_instance_schema(schema_text, schema_type)),
            timeout=timeout,
        )

    async def update_instance_metadata(
        self, instance_id: str, name: str, description: str | None, *, timeout: float | None = None,
    ) -> InstanceInfo:
        """Update the name and description of an instance."""
        return await self._t.request_one(
            "PUT", f"/instances/{instance_id}", InstanceInfo,
            body=_UpdateMetadataRequest(name=name, description=description),
            timeout=timeout,
        )

    async def delete_instance(self, instance_id: str, *, timeout: float | None = None) -> list[uuid.UUID]:
        """Delete an instance by ID. Returns the list of deleted IDs."""
        return await self._t.request_ids("DELETE", f"/instances/{instance_id}", timeout=timeout)

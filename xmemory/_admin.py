from __future__ import annotations


from typing import Any

from xmemory._instance import AsyncInstanceAPI, InstanceAPI
from xmemory._models import (
    ClusterInfo,
    GenerateSchemaResult,
    InstanceInfo,
    InstanceSchemaInfo,
    SchemaType,
    _CreateInstanceRequest,
    _DryRunMigrationRequest,
    _GenerateSchemaRequest,
    _UpdateMetadataRequest,
    _UpdateSchemaRequest,
    build_instance_schema,
)
from xmemory._schema_evolution import (
    DryRunResult,
    EnhanceSchemaResult,
    GetMigrationResult,
    ListMigrationsResult,
    MigrationPlan,
    MigrationRecord,
    _serialize_plan,
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

    def enhance_schema(
        self,
        cluster_id: str,
        schema_description: str,
        current_yml_schema: str,
        *,
        timeout: float | None = None,
    ) -> EnhanceSchemaResult:
        """Evolve an existing schema, returning the new schema and a migration plan.

        Pass the instance's current YAML schema plus a description of the change
        you want. The result's ``migration_plan`` is executor-ready: hand it to
        :meth:`dry_run_migration` to preview the DDL, then to
        :meth:`update_instance_schema` to apply it.
        """
        return self._t.request_one(
            "POST",
            f"/clusters/{cluster_id}/instances/generate_schema",
            EnhanceSchemaResult,
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
        self,
        instance_id: str,
        schema_text: str,
        schema_type: SchemaType,
        *,
        migration_plan: MigrationPlan | dict[str, Any] | None = None,
        confirm_destructive: bool = False,
        timeout: float | None = None,
    ) -> InstanceInfo:
        """Replace the schema of an instance.

        For a non-additive change (rename / remove / type change) pass the
        ``migration_plan`` produced by :meth:`enhance_schema`; the server
        rejects non-additive changes that arrive without a plan. Set
        ``confirm_destructive=True`` to authorise ops that drop data
        (remove object/field, lossy type cast). The returned ``InstanceInfo``
        carries ``migration_id`` / ``prior_version`` / ``new_version`` /
        ``migration_warnings`` when a migration ran.
        """
        return self._t.request_one(
            "PUT", f"/instances/{instance_id}/schema", InstanceInfo,
            body=_UpdateSchemaRequest(
                instance_schema=build_instance_schema(schema_text, schema_type),
                migration_plan=_serialize_plan(migration_plan),
                confirm_destructive=confirm_destructive,
            ),
            timeout=timeout,
        )

    def dry_run_migration(
        self,
        instance_id: str,
        schema_text: str,
        schema_type: SchemaType,
        *,
        migration_plan: MigrationPlan | dict[str, Any] | None = None,
        confirm_destructive: bool = False,
        timeout: float | None = None,
    ) -> DryRunResult:
        """Preview a migration without applying it.

        Runs the full apply-path input validation (schema + plan + destructive
        gate + preconditions) and returns the planned DDL statements and a
        per-op-type summary, but executes no DDL.
        """
        return self._t.request_one(
            "POST", f"/instances/{instance_id}/migrations/dry_run", DryRunResult,
            body=_DryRunMigrationRequest(
                instance_schema=build_instance_schema(schema_text, schema_type),
                migration_plan=_serialize_plan(migration_plan),
                confirm_destructive=confirm_destructive,
            ),
            timeout=timeout,
        )

    def list_migrations(
        self,
        instance_id: str,
        *,
        limit: int = 50,
        before_id: str | None = None,
        include_yaml: bool = False,
        timeout: float | None = None,
    ) -> ListMigrationsResult:
        """List applied migrations for an instance (newest first).

        Paginate with ``before_id`` (pass the previous page's
        ``next_before_id``). YAML snapshots are omitted unless
        ``include_yaml=True``.
        """
        params: dict[str, Any] = {"limit": limit, "include_yaml": include_yaml}
        if before_id is not None:
            params["before_id"] = before_id
        return self._t.request_one(
            "GET", f"/instances/{instance_id}/migrations", ListMigrationsResult, params=params, timeout=timeout,
        )

    def get_migration(
        self,
        instance_id: str,
        migration_id: str,
        *,
        include_yaml: bool = False,
        timeout: float | None = None,
    ) -> MigrationRecord:
        """Get a single migration record. Set ``include_yaml=True`` for the
        before/after YAML snapshots."""
        result = self._t.request_one(
            "GET",
            f"/instances/{instance_id}/migrations/{migration_id}",
            GetMigrationResult,
            params={"include_yaml": include_yaml},
            timeout=timeout,
        )
        return result.record

    def update_instance_metadata(
        self, instance_id: str, name: str, description: str | None, *, timeout: float | None = None,
    ) -> InstanceInfo:
        """Update the name and description of an instance."""
        return self._t.request_one(
            "PUT", f"/instances/{instance_id}", InstanceInfo,
            body=_UpdateMetadataRequest(name=name, description=description),
            timeout=timeout,
        )

    def delete_instance(self, instance_id: str, *, timeout: float | None = None) -> list[str]:
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

    async def enhance_schema(
        self,
        cluster_id: str,
        schema_description: str,
        current_yml_schema: str,
        *,
        timeout: float | None = None,
    ) -> EnhanceSchemaResult:
        """Evolve an existing schema, returning the new schema and a migration plan.

        Pass the instance's current YAML schema plus a description of the change
        you want. The result's ``migration_plan`` is executor-ready: hand it to
        :meth:`dry_run_migration` to preview the DDL, then to
        :meth:`update_instance_schema` to apply it.
        """
        return await self._t.request_one(
            "POST",
            f"/clusters/{cluster_id}/instances/generate_schema",
            EnhanceSchemaResult,
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
        self,
        instance_id: str,
        schema_text: str,
        schema_type: SchemaType,
        *,
        migration_plan: MigrationPlan | dict[str, Any] | None = None,
        confirm_destructive: bool = False,
        timeout: float | None = None,
    ) -> InstanceInfo:
        """Replace the schema of an instance.

        For a non-additive change (rename / remove / type change) pass the
        ``migration_plan`` produced by :meth:`enhance_schema`; the server
        rejects non-additive changes that arrive without a plan. Set
        ``confirm_destructive=True`` to authorise ops that drop data
        (remove object/field, lossy type cast). The returned ``InstanceInfo``
        carries ``migration_id`` / ``prior_version`` / ``new_version`` /
        ``migration_warnings`` when a migration ran.
        """
        return await self._t.request_one(
            "PUT", f"/instances/{instance_id}/schema", InstanceInfo,
            body=_UpdateSchemaRequest(
                instance_schema=build_instance_schema(schema_text, schema_type),
                migration_plan=_serialize_plan(migration_plan),
                confirm_destructive=confirm_destructive,
            ),
            timeout=timeout,
        )

    async def dry_run_migration(
        self,
        instance_id: str,
        schema_text: str,
        schema_type: SchemaType,
        *,
        migration_plan: MigrationPlan | dict[str, Any] | None = None,
        confirm_destructive: bool = False,
        timeout: float | None = None,
    ) -> DryRunResult:
        """Preview a migration without applying it.

        Runs the full apply-path input validation (schema + plan + destructive
        gate + preconditions) and returns the planned DDL statements and a
        per-op-type summary, but executes no DDL.
        """
        return await self._t.request_one(
            "POST", f"/instances/{instance_id}/migrations/dry_run", DryRunResult,
            body=_DryRunMigrationRequest(
                instance_schema=build_instance_schema(schema_text, schema_type),
                migration_plan=_serialize_plan(migration_plan),
                confirm_destructive=confirm_destructive,
            ),
            timeout=timeout,
        )

    async def list_migrations(
        self,
        instance_id: str,
        *,
        limit: int = 50,
        before_id: str | None = None,
        include_yaml: bool = False,
        timeout: float | None = None,
    ) -> ListMigrationsResult:
        """List applied migrations for an instance (newest first).

        Paginate with ``before_id`` (pass the previous page's
        ``next_before_id``). YAML snapshots are omitted unless
        ``include_yaml=True``.
        """
        params: dict[str, Any] = {"limit": limit, "include_yaml": include_yaml}
        if before_id is not None:
            params["before_id"] = before_id
        return await self._t.request_one(
            "GET", f"/instances/{instance_id}/migrations", ListMigrationsResult, params=params, timeout=timeout,
        )

    async def get_migration(
        self,
        instance_id: str,
        migration_id: str,
        *,
        include_yaml: bool = False,
        timeout: float | None = None,
    ) -> MigrationRecord:
        """Get a single migration record. Set ``include_yaml=True`` for the
        before/after YAML snapshots."""
        result = await self._t.request_one(
            "GET",
            f"/instances/{instance_id}/migrations/{migration_id}",
            GetMigrationResult,
            params={"include_yaml": include_yaml},
            timeout=timeout,
        )
        return result.record

    async def update_instance_metadata(
        self, instance_id: str, name: str, description: str | None, *, timeout: float | None = None,
    ) -> InstanceInfo:
        """Update the name and description of an instance."""
        return await self._t.request_one(
            "PUT", f"/instances/{instance_id}", InstanceInfo,
            body=_UpdateMetadataRequest(name=name, description=description),
            timeout=timeout,
        )

    async def delete_instance(self, instance_id: str, *, timeout: float | None = None) -> list[str]:
        """Delete an instance by ID. Returns the list of deleted IDs."""
        return await self._t.request_ids("DELETE", f"/instances/{instance_id}", timeout=timeout)

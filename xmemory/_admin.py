from __future__ import annotations


from collections.abc import Sequence
from typing import Any

from xmemory._instance import AsyncInstanceAPI, InstanceAPI
from xmemory._models import (
    UNSET,
    ClusterInfo,
    GenerateSchemaResult,
    InstanceInfo,
    InstanceSchemaInfo,
    SchemaType,
    UnsetType,
    _CreateInstanceRequest,
    _DryRunMigrationRequest,
    _GenerateSchemaRequest,
    _PatchMetadataRequest,
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


def _as_str_list(
    value: Sequence[str] | None | UnsetType,
) -> list[str] | None | UnsetType:
    """Copy a caller's sequence into the plain list the request model holds.

    Accepted as a ``Sequence`` so a ``list[AgentSurface]`` is allowed — ``list`` is
    invariant, so a ``list[str]`` parameter would reject one. Copied rather than
    passed through so a caller mutating their list afterwards cannot change what a
    retry sends.

    A bare string is refused rather than iterated. ``str`` satisfies
    ``Sequence[str]``, so nothing in the signature stops one, and iterating it
    would send each character as its own entry — which, for the engagement hints,
    the server accepts and stores rather than rejects.
    """
    if value is None or isinstance(value, UnsetType):
        return value
    if isinstance(value, str):
        raise TypeError("expected a sequence of strings, not a bare string — wrap it in a list")
    return list(value)


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
        self,
        instance_id: str,
        name: str,
        description: str | None,
        *,
        agent_owner_instructions: str | None | UnsetType = UNSET,
        expected_owner_instructions_epoch: int | UnsetType = UNSET,
        timeout: float | None = None,
    ) -> InstanceInfo:
        """Update the name and description of an instance.

        ``agent_owner_instructions`` — what the owner tells agents to do with this
        instance — is left exactly as it is unless you name it. Pass ``None`` to
        clear it.

        When saving an edit you composed from a value read earlier, pass that
        response's :attr:`~xmemory.InstanceInfo.agent_owner_instructions_epoch` as
        ``expected_owner_instructions_epoch``: a save that raced someone else's
        edit is then refused rather than silently overwriting it.
        """
        return self._t.request_one(
            "PUT", f"/instances/{instance_id}", InstanceInfo,
            body=_UpdateMetadataRequest(
                name=name,
                description=description,
                agent_owner_instructions=agent_owner_instructions,
                expected_owner_instructions_epoch=expected_owner_instructions_epoch,
            ),
            timeout=timeout,
        )

    def patch_instance_metadata(
        self,
        instance_id: str,
        *,
        name: str | UnsetType = UNSET,
        description: str | None | UnsetType = UNSET,
        agent_surfaces: Sequence[str] | None | UnsetType = UNSET,
        agent_default_binding_tier: str | None | UnsetType = UNSET,
        agent_engagement_hints: Sequence[str] | None | UnsetType = UNSET,
        agent_owner_instructions: str | None | UnsetType = UNSET,
        timeout: float | None = None,
    ) -> InstanceInfo:
        """Change some of an instance's metadata, leaving the rest alone.

        Every argument is optional and independent: omit one and the stored value is
        untouched, pass ``None`` to clear it. Prefer this over
        :meth:`update_instance_metadata` when changing an agent hint, since it does
        not require restating the name.

        The three ``agent_*`` hints are advisory — they seed what a connect flow
        proposes to a user, and grant nothing. Use :class:`~xmemory.AgentSurface` and
        :class:`~xmemory.BindingTier` for the accepted values, or pass the plain
        strings if your server is newer than this release.
        ``agent_engagement_hints`` are short routing phrases ("a convention is
        learned or corrected"); the server caps them at 16 of at most 200 characters.

        ``agent_owner_instructions`` is authoritative rather than advisory: it is
        rendered verbatim wherever it is shown, and the server caps it at 2000
        characters. This endpoint takes no epoch guard — use
        :meth:`update_instance_metadata` when you need one.
        """
        return self._t.request_one(
            "PATCH", f"/instances/{instance_id}", InstanceInfo,
            body=_PatchMetadataRequest(
                name=name,
                description=description,
                agent_surfaces=_as_str_list(agent_surfaces),
                agent_default_binding_tier=agent_default_binding_tier,
                agent_engagement_hints=_as_str_list(agent_engagement_hints),
                agent_owner_instructions=agent_owner_instructions,
            ),
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
        self,
        instance_id: str,
        name: str,
        description: str | None,
        *,
        agent_owner_instructions: str | None | UnsetType = UNSET,
        expected_owner_instructions_epoch: int | UnsetType = UNSET,
        timeout: float | None = None,
    ) -> InstanceInfo:
        """Update the name and description of an instance.

        ``agent_owner_instructions`` — what the owner tells agents to do with this
        instance — is left exactly as it is unless you name it. Pass ``None`` to
        clear it.

        When saving an edit you composed from a value read earlier, pass that
        response's :attr:`~xmemory.InstanceInfo.agent_owner_instructions_epoch` as
        ``expected_owner_instructions_epoch``: a save that raced someone else's
        edit is then refused rather than silently overwriting it.
        """
        return await self._t.request_one(
            "PUT", f"/instances/{instance_id}", InstanceInfo,
            body=_UpdateMetadataRequest(
                name=name,
                description=description,
                agent_owner_instructions=agent_owner_instructions,
                expected_owner_instructions_epoch=expected_owner_instructions_epoch,
            ),
            timeout=timeout,
        )

    async def patch_instance_metadata(
        self,
        instance_id: str,
        *,
        name: str | UnsetType = UNSET,
        description: str | None | UnsetType = UNSET,
        agent_surfaces: Sequence[str] | None | UnsetType = UNSET,
        agent_default_binding_tier: str | None | UnsetType = UNSET,
        agent_engagement_hints: Sequence[str] | None | UnsetType = UNSET,
        agent_owner_instructions: str | None | UnsetType = UNSET,
        timeout: float | None = None,
    ) -> InstanceInfo:
        """Change some of an instance's metadata, leaving the rest alone.

        Every argument is optional and independent: omit one and the stored value is
        untouched, pass ``None`` to clear it. Prefer this over
        :meth:`update_instance_metadata` when changing an agent hint, since it does
        not require restating the name.

        The three ``agent_*`` hints are advisory — they seed what a connect flow
        proposes to a user, and grant nothing. Use :class:`~xmemory.AgentSurface` and
        :class:`~xmemory.BindingTier` for the accepted values, or pass the plain
        strings if your server is newer than this release.
        ``agent_engagement_hints`` are short routing phrases ("a convention is
        learned or corrected"); the server caps them at 16 of at most 200 characters.

        ``agent_owner_instructions`` is authoritative rather than advisory: it is
        rendered verbatim wherever it is shown, and the server caps it at 2000
        characters. This endpoint takes no epoch guard — use
        :meth:`update_instance_metadata` when you need one.
        """
        return await self._t.request_one(
            "PATCH", f"/instances/{instance_id}", InstanceInfo,
            body=_PatchMetadataRequest(
                name=name,
                description=description,
                agent_surfaces=_as_str_list(agent_surfaces),
                agent_default_binding_tier=agent_default_binding_tier,
                agent_engagement_hints=_as_str_list(agent_engagement_hints),
                agent_owner_instructions=agent_owner_instructions,
            ),
            timeout=timeout,
        )

    async def delete_instance(self, instance_id: str, *, timeout: float | None = None) -> list[str]:
        """Delete an instance by ID. Returns the list of deleted IDs."""
        return await self._t.request_ids("DELETE", f"/instances/{instance_id}", timeout=timeout)

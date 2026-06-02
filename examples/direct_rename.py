"""Direct migration flow: enhance_schema → dry_run_migration → update_instance_schema.

Drives a rename yourself instead of going through the suggestion engine. The
server emits a structured migration plan; you preview the DDL, then apply it.
A rename preserves data (unlike remove + add, which would drop the column).

Run against a staging instance:

    export XMEM_API_KEY=xmem_...
    export XMEM_API_URL=https://api.stg.xmemory.ai   # optional; defaults to prod
    export XMEM_CLUSTER_ID=<cluster-id>
    export XMEM_INSTANCE_ID=<instance-id>
    python examples/direct_rename.py
"""

import os

import yaml

from xmemory import SchemaType, XmemoryAPIError, XmemoryClient


def main() -> None:
    cluster_id = os.environ["XMEM_CLUSTER_ID"]
    instance_id = os.environ["XMEM_INSTANCE_ID"]
    client = XmemoryClient()

    current_schema = client.admin.get_instance_schema(instance_id).data_schema
    current_yaml = yaml.safe_dump(current_schema)

    # 1. Enhance — get the new schema + an executor-ready migration plan.
    enhanced = client.admin.enhance_schema(
        cluster_id=cluster_id,
        schema_description="Rename the `mail` field on the person object to `email`.",
        current_yml_schema=current_yaml,
    )
    print("Summary:", enhanced.summary)
    assert enhanced.migration_plan is not None
    for op in enhanced.migration_plan.ops:
        print("  op:", op)
    for repair in enhanced.repair_log:
        print("  auto-repair:", repair)

    new_yaml = yaml.safe_dump(enhanced.data_schema)

    # 2. Dry-run — preview the DDL. Nothing is applied.
    preview = client.admin.dry_run_migration(
        instance_id, new_yaml, SchemaType.YML, migration_plan=enhanced.migration_plan,
    )
    print(f"Dry-run against v{preview.current_version}:")
    for stmt in preview.statements:
        print("  ", stmt)
    print("  plan summary:", preview.plan_summary.count_by_op_type)

    # 3. Update — apply. A rename is non-destructive, so confirm_destructive stays
    #    False. Set it to True only for ops that drop data (remove*, lossy cast).
    try:
        info = client.admin.update_instance_schema(
            instance_id, new_yaml, SchemaType.YML,
            migration_plan=enhanced.migration_plan,
            confirm_destructive=False,
        )
    except XmemoryAPIError as exc:
        if exc.code == "destructive_confirmation_required":
            print("Plan would drop data; re-run with confirm_destructive=True to proceed.")
            return
        raise

    print(f"Applied migration {info.migration_id}: v{info.prior_version} -> v{info.new_version}")
    if info.migration_warnings:
        print("Warnings:", info.migration_warnings)


if __name__ == "__main__":
    main()
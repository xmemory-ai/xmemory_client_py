"""End-to-end suggestion-engine flow: read → flagged → review → decide → apply.

The suggestion engine watches read traffic. When a read can't be fully answered
because the schema lacks a field/object/relation, that gap accumulates and is
surfaced — on demand — as a single consolidated proposal you review, decide on
(in bulk), and apply as one migration.

Run against a test instance:

    export XMEM_API_KEY=xmem_...
    export XMEM_API_URL=<api-url>   # optional; defaults to https://api.xmemory.ai
    export XMEM_INSTANCE_ID=<instance-id>
    python examples/suggestion_engine_flow.py
"""

import os
import time

from xmemory import DecisionInput, XmemoryClient


def main() -> None:
    instance_id = os.environ["XMEM_INSTANCE_ID"]
    client = XmemoryClient()  # reads XMEM_API_KEY / XMEM_API_URL from the env
    inst = client.instance(instance_id)

    # Some reads that may not be fully answerable by the current schema — these
    # are what the gap analyzer learns from.
    inst.write("Dana Lopez is a staff engineer. Her desk phone is +1-555-0100.")
    inst.read("What is Dana's phone number?")

    # 1. Review — pull the rolling proposal. May report a migration in flight.
    review = inst.review_suggestions()
    if review.status == "evolution_in_progress":
        print(f"Evolution in progress; retry in {review.retry_after_seconds}s")
        time.sleep(review.retry_after_seconds or 5)
        review = inst.review_suggestions()

    proposal = review.proposal
    if proposal is None or not proposal.items:
        print("No pending suggestions.")
        return

    print(f"Proposal {proposal.proposal_version} (schema v{proposal.schema_version}):")
    for item in proposal.items:
        blocked = " (cannot be applied as proposed)" if item.apply_blocked else ""
        print(f"  - [{item.item_fingerprint}]{blocked} {item.rationale}")
        print(f"      op: {item.op}")
        if item.evidence_query_samples:
            print(f"      seen in: {item.evidence_query_samples[:2]}")

    # 2. Decide — accept everything that can be applied; in practice you'd
    #    choose per item. An apply_blocked item would fail the whole apply.
    decisions = [
        DecisionInput(item_fingerprint=item.item_fingerprint, decision="accept")
        for item in proposal.items
        if not item.apply_blocked
    ]
    if not decisions:
        print("Every suggestion is blocked; nothing to accept.")
        return
    decided = inst.decide_suggestions(proposal.proposal_version, decisions)
    for warning in decided.warnings:
        print(f"  dependency warning: {warning.kind} — {warning.guidance}")

    # 3. Apply — commit accepted decisions as a single migration.
    applied = inst.apply_pending_decisions(decided.next_proposal_version)
    if applied.status == "nothing_to_apply":
        print("Nothing to apply.")
    else:
        print(
            f"Applied migration {applied.migration_id}: "
            f"v{applied.prior_version} -> v{applied.new_version} ({applied.summary})"
        )


if __name__ == "__main__":
    main()
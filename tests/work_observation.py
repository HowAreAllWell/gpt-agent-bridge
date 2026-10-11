"""Test-only observation of actual Work records and completion of fixture watchers.

No event waiters, lease/continuation protocol, receipt schema or model API.
"""
import asyncio
import copy


async def delegate_item(project_ref, assignments):
    """Exercise one explicit assignment; return its actual item receipt for dispatch fixtures.

    Envelope and cohort assertions use the public MCP result directly in cohort tests.
    This helper provides no scalar argument or receipt compatibility.
    """
    import server
    assert len(assignments) == 1
    payload = (await server.delegate(project_ref, assignments=assignments)).structured_content
    return payload['items'][0] if 'items' in payload else payload


def work_record(work):
    return copy.deepcopy({key: work[key] for key in (
        "work_ref", "project_ref", "state", "reason", "settled_at",
        "post_state_change_seq", "submission_evidence", "agy_recovery_reprompt"
    ) if key in work})


async def finished_work(project_ref, work_ref):
    import server
    resolved = server._required_project_context(project_ref)
    if isinstance(resolved, dict):
        return resolved
    work = server._lookup_work(project_ref, str(resolved.root), work_ref)
    if work.get("ok") is False:
        return work
    if work["state"] not in server.WORK_TERMINAL_STATES:
        handoff = server._HANDOFF_REGISTRY.get(work.get("handoff_id"), {})
        task = handoff.get("watcher_task")
        if task is not None:
            await asyncio.shield(task)
    return work_record(work)

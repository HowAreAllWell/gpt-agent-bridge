"""Preserve unique MCP evidence; remove only proven copies of structured payloads."""
import json
from mcp.types import CallToolResult, TextContent


def _duplicates_payload(text, payload):
    try:
        # Compare JSON types too: Python's True == 1 is not proof of duplication.
        canonical = lambda value: json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)
        return canonical(json.loads(text)) == canonical(payload)
    except (ValueError, TypeError, RecursionError):
        return False


def _id_suffix(payload, key):
    value = payload.get(key) if isinstance(payload, dict) else None
    return f" {value}" if isinstance(value, str) and value else ""


def _delegate_summary(payload):
    items = payload.get('items')
    if isinstance(items, list):
        counts = {name: sum(item.get('outcome') == name for item in items)
                  for name in ('submitted', 'not_submitted', 'delivery_unknown')}
        lines = ['Dispatch: ' + ', '.join(f'{count} {name}' for name, count in counts.items()) + '.']
        refusals = [item for item in items if item.get('outcome') == 'not_submitted']
        refused = next((item for item in refusals if item.get('error_type') == 'PriorWorkDiagnosticsRequired'),
                       refusals[0] if refusals else None)
        if refused:
            lines.append(f"Primary refusal item {refused['index']}: " + str(refused.get('error_type', 'not_submitted'))[:100] + '.')
            if refused.get('error_type') == 'PriorWorkDiagnosticsRequired':
                gap = refused.get('prior_work') or {}
                lines.append('No input for this item; prior Work' + _id_suffix(gap, 'work_ref') +
                             f"; {gap.get('additional_count', 0)} additional gaps. Use agent_terminal_read before delegating to this Agent again.")
        if refused and refused.get('error_type') != 'PriorWorkDiagnosticsRequired' and (
                refused.get('submission_evidence') or {}).get('mutation_possible') is False:
            lines.append(_summary(refused, None))
        if counts['delivery_unknown']:
            lines.append('Delivery unknown is not safe to blindly resend.')
    else:
        items = []
        lines = [_summary(payload, None)]
    advisories = [item['prior_work_advisory'] for item in items if item.get('prior_work_advisory')]
    if advisories:
        primary = advisories[0]
        additional = len(advisories) - 1 + sum(a.get('additional_count', 0) for a in advisories)
        lines.append('Prior Work' + _id_suffix(primary, 'work_ref') + ': Bridge has no recorded report evidence serving; '
                     f'{additional} additional gaps. Read work_report if relevant.')
    if isinstance(payload.get('items'), list):
        lines.append('If results are pending and no independent work remains, '
                     'end this turn; an enabled local completion extension can notify report readiness, '
                     'otherwise wait for a manual user reminder.')
    return '\n'.join(lines)


def _summary(payload, tool_name):
    if tool_name == 'delegate':
        return _delegate_summary(payload)
    if tool_name in ("commit", "commit_prepare") and "status" in payload:
        status = str(payload["status"])
        effects = payload.get("side_effects", {})
        result = payload.get("result", payload)
        ref = effects.get("ref_updated", result.get("ref_updated"))
        objects = effects.get("objects_may_remain", result.get("objects_may_remain"))
        suffix = f" Ref updated: {ref if ref is not None else 'unknown'}; objects may remain: {objects if objects is not None else 'unknown'}." if ref is not None or objects is not None else ""
        if "index_updated" in payload:
            suffix += " Index updated: " + str(payload["index_updated"] if payload["index_updated"] is not None else "unknown") + "."
        reason = str(payload.get("reason", result.get("reason", "")))[:100]
        if status == "previewed" and "index_updated" in payload:
            # Fresh paths-mode preparation: response evidence carries the index fact.
            head = "Commit candidate ready for review"
        elif status == "previewed":
            # Saved-candidate paging and no-paths capture are indistinguishable
            # in this response; state only what the evidence proves.
            head = "Commit candidate ready for review; no staging or recapture in this response"
        else:
            head = f"Candidate {status}" + (f": {reason}" if reason else "")
        return head + "." + suffix
    if tool_name == "project_text_edit" and payload.get("status") == "unknown":
        return "Text edit outcome unknown. Inspect the file before another edit."
    if tool_name == "project_text_edit" and payload.get("ok") is True:
        return "Project text edited; hashes and counts are in structuredContent."
    if payload.get("ok") is False:
        if payload.get("error_type") == "WorkDispatchTransportUncertain":
            named = _id_suffix(payload, "work_ref")
            named = named.replace(" ", " for ", 1) if named else ""
            evidence = payload.get("submission_evidence") or {}
            mutation_possible = evidence.get("mutation_possible")
            if mutation_possible is False:
                reason = str(payload.get("error") or evidence.get("native_error_code")
                             or evidence.get("proves") or "backend refused before input")[:300]
                return "No prompt/input was sent" + named + ": " + reason
            if mutation_possible is True:
                return ("Delivery unknown" + named
                        + "; submission evidence and safety instruction are in structuredContent.")
            return "Dispatch evidence unavailable" + named + "; details are in structuredContent."
        if tool_name == "work_report" and payload.get("error_type") == "WorkReportMissing":
            return "Report missing for" + _id_suffix(payload, "work_ref") + "."
        return "Error: " + str(payload.get("error_type", "application_error"))[:100]
    if tool_name == "work_report" and payload.get("ok") is True:
        return "Report page for" + _id_suffix(payload, "work_ref") + "."
    if tool_name == "agent_terminal_read" and payload.get("ok") is True:
        return "Terminal text for" + _id_suffix(payload, "agent_ref") + "."
    if tool_name == "current_state_update" and payload.get("ok") is True:
        return "State publication recorded; not a Git commit."
    return "Result available in structuredContent."


def compact_result(result, tool_name=None):
    if not isinstance(result, CallToolResult) or result.structured_content is None:
        return result  # Protocol errors keep their only evidence.
    metadata = result.structured_content
    content = [block for block in result.content
               if block.type != "text" or not _duplicates_payload(block.text, metadata)]
    summary = _summary(metadata, tool_name)
    if not any(block.type == "text" and block.text == summary for block in content):
        content.append(TextContent(type="text", text=summary))
    return result.model_copy(update={"content": content})


def forbid_extra_arguments(mcp, names=None):
    """Set SDK runtime argument validation and regenerate the advertised schema."""
    tools = mcp._tool_manager.list_tools() if names is None else [
        mcp._tool_manager.get_tool(name) for name in names]
    for tool in tools:
        model = tool.fn_metadata.arg_model
        model.model_config = {**model.model_config, "extra": "forbid"}
        model.model_rebuild(force=True)
        tool.parameters = model.model_json_schema(by_alias=True)

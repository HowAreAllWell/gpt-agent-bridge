"""Internal read metadata contract and shared native-image serialization.

Public read carries UTF-8 text and native images only; PDF/DOCX originals are
refused by the tool boundary (UnsupportedReadFormat) and belong to prepare_file_attachment.
This module stays the private text/image/error model support: the SDK no longer
publishes a read outputSchema, so callers validate metadata here explicitly.
"""
import json
from typing import Any, Literal

from mcp.types import CallToolResult, TextContent
from mcp.server.mcpserver import Image
from .tool_presentation import compact_result
from pydantic import BaseModel, ConfigDict, JsonValue, ValidationError, model_validator

_SUCCESS = ('path workspace_ref canonical_root file_size_bytes file_sha256 '
            'project_ref project_root execution_target target_kind work_ref provenance '
            'coverage pagination observation_mode version').split()
_TEXT = ('content content_offset content_end_offset content_start_line content_start_column '
         'offset_unit line_unit content_limit content_page_chars content_total_chars '
         'content_next_offset content_has_more').split()
_NULLABLE = {'work_ref', 'content_next_offset'}


def _required(fields):
    return {'required': fields, 'properties': {
        field: {'not': {'type': 'null'}} for field in fields if field not in _NULLABLE}}


def _conditions(schema):
    schema['allOf'] = [
        {'if': {'properties': {'ok': {'const': False}}},
         'then': _required(['error_type', 'error']),
         'else': {**_required(_SUCCESS), 'allOf': [
             {'if': {'required': ['kind'], 'properties': {'kind': {'const': 'image'}}},
              'then': _required(['mime_type']), 'else': _required(_TEXT)}]}}]


class ReadPagination(BaseModel):
    model_config = ConfigDict(extra='allow', strict=True)
    unit: Literal['unicode_characters', 'whole_image']
    next_offset: int | None
    offset: int | None = None


class ReadVersion(BaseModel):
    model_config = ConfigDict(extra='allow', strict=True)
    git_head: str | None


class ReadResultModel(BaseModel):
    """Text/image/error metadata; extra diagnostics are preserved."""
    model_config = ConfigDict(extra='allow', strict=True, json_schema_extra=_conditions)
    ok: bool
    error_type: str | None = None
    error: str | None = None
    binary: bool | None = None
    path: str | None = None
    kind: Literal['image'] | None = None
    mime_type: str | None = None
    workspace_ref: str | None = None
    canonical_root: str | None = None
    project_ref: str | None = None
    project_root: str | None = None
    execution_target: str | None = None
    target_kind: Literal['project_root', 'work_checkout'] | None = None
    work_ref: str | None = None
    file_size_bytes: int | None = None
    file_sha256: str | None = None
    provenance: dict[str, JsonValue] | None = None
    coverage: dict[str, JsonValue] | None = None
    pagination: ReadPagination | None = None
    version: ReadVersion | None = None
    observation_mode: Literal['current_worktree'] | None = None
    content: str | None = None
    content_offset: int | None = None
    content_end_offset: int | None = None
    content_start_line: int | None = None
    content_start_column: int | None = None
    offset_unit: Literal['unicode_characters'] | None = None
    line_unit: Literal['LF_delimited_1_based'] | None = None
    content_limit: int | None = None
    content_page_chars: int | None = None
    content_total_chars: int | None = None
    content_next_offset: int | None = None
    content_has_more: bool | None = None

    @model_validator(mode='before')
    @classmethod
    def require_variant_fields(cls, value):
        if isinstance(value, dict):
            required = (['error_type', 'error'] if value.get('ok') is False else
                        _SUCCESS + (['mime_type'] if value.get('kind') == 'image' else _TEXT))
            if any(field not in value or (value[field] is None and field not in _NULLABLE)
                   for field in required):
                raise ValueError('read metadata is missing required variant fields')
        return value


def read_tool_result(value: dict[str, Any]) -> CallToolResult:
    """Add structured metadata without default fields, wrappers or image duplication."""
    return compact_result(CallToolResult(content=[], structured_content=value))


class NativeImageEnvelopeError(Exception):
    """The read native-image envelope violated the internal producer contract.

    This is an internal/protocol validation failure, not an application error: it
    must surface at dispatch as isError=true with no native image and no
    structuredContent, never as an ordinary ok=false result and never as image
    metadata text without the image. Reasons are fixed short strings so the
    diagnostic stays bounded and no payload bytes are echoed."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason

    def wire_result(self) -> CallToolResult:
        return CallToolResult(content=[TextContent(type='text', text=(
            'internal error: read image envelope failed producer validation: '
            + self.reason))], isError=True)


def is_image_success_metadata(value: Any) -> bool:
    """True only for a successful image-kind metadata dict."""
    return (isinstance(value, dict) and value.get('ok') is True
            and value.get('kind') == 'image')


def native_image_result(value: list[Any]) -> CallToolResult:
    """Read image serialization (EVO-046 closed): accept ONLY an exactly valid
    internal envelope — a 2-element list whose first element is the production
    mcp Image wrapper and whose second element is a metadata dict that validates
    with ReadResultModel, is a successful image result, and whose mime_type equals
    the converted native ImageContent mimeType. Emits one native image block plus
    one compact text block holding the FULL original metadata dict; no
    structuredContent, no duplicate base64, no evidence rewriting. Any other
    shape raises NativeImageEnvelopeError so dispatch fails closed."""
    if not isinstance(value, list) or len(value) != 2:
        raise NativeImageEnvelopeError('envelope must be a 2-element list')
    image, metadata = value
    if not isinstance(image, Image):
        raise NativeImageEnvelopeError('first element must be the mcp Image wrapper')
    if not isinstance(metadata, dict):
        raise NativeImageEnvelopeError('second element must be a metadata dict')
    try:
        ReadResultModel.model_validate(metadata)
    except ValidationError as exc:
        raise NativeImageEnvelopeError(
            'metadata failed ReadResultModel validation') from exc
    if not is_image_success_metadata(metadata):
        raise NativeImageEnvelopeError('metadata must be a successful image result')
    image_content = image.to_image_content()
    if str(image_content.mime_type) != metadata.get('mime_type'):
        raise NativeImageEnvelopeError(
            'native image mimeType does not match metadata mime_type')
    return CallToolResult(content=[image_content, TextContent(
        type='text', text=json.dumps(metadata, ensure_ascii=False, separators=(',', ':')))])

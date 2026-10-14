"""Catalog construction diagnostics through MCP; no live hosts or business calls."""
import hashlib
import io
import json
import os
from datetime import datetime
import unittest
from unittest.mock import AsyncMock, patch

import anyio
from mcp import ClientSession
from mcp.shared.memory import create_client_server_memory_streams
from mcp.shared.message import ClientMessageMetadata
from mcp.types import ListToolsRequest, ListToolsResult, PaginatedRequestParams

os.environ.setdefault("BRIDGE_PATH_TOKEN", "test-token-abcdefghijklmnopqrstuvwxyz-012345")
from gpt_agent_bridge import server


class CatalogListingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        for field, value in (("_catalog_sequence", 0), ("_catalog_listing", None)):
            patcher = patch.object(server.mcp, field, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    async def test_initialized_memory_list_records_once_without_request_secrets(self):
        expected = await server.mcp.list_tools()
        secret = "SYNTHETIC-REQUEST-HEADER-SECRET"
        lowlevel = server.mcp._lowlevel_server
        wire_catalogs = []

        class RecordingSend:
            def __init__(self, stream):
                self.stream = stream

            def __getattr__(self, name):
                return getattr(self.stream, name)

            async def __aenter__(self):
                await self.stream.__aenter__()
                return self

            async def __aexit__(self, *args):
                return await self.stream.__aexit__(*args)

            async def send(self, message):
                payload = getattr(message.message, "root", message.message)
                result = getattr(payload, "result", None)
                if isinstance(result, dict) and "tools" in result:
                    wire_catalogs.append(result)
                await self.stream.send(message)
        with self.assertLogs("mcp.bridge.catalog", level="INFO") as logs:
            async with create_client_server_memory_streams() as (client_streams, server_streams):
                async with anyio.create_task_group() as group:
                    group.start_soon(lowlevel.run, server_streams[0], RecordingSend(server_streams[1]),
                                     lowlevel.create_initialization_options())
                    async with ClientSession(*client_streams) as client:
                        await client.initialize()
                        self.assertIsNone(server.mcp._catalog_listing)
                        response = await client.send_request(
                            ListToolsRequest(params=PaginatedRequestParams(
                                _meta={"synthetic_private": secret},
                            )),
                            ListToolsResult,
                            metadata=ClientMessageMetadata(headers={"authorization": secret}),
                        )
                    group.cancel_scope.cancel()
        self.assertEqual(response.tools, expected)
        self.assertTrue(all(t.annotations is not None for t in response.tools))
        self.assertEqual(len(wire_catalogs), 1)
        self.assertEqual(len(wire_catalogs[0]["tools"]), 21 - 3)
        self.assertNotIn("nextCursor", wire_catalogs[0])
        self.assertTrue(all("annotations" in t for t in wire_catalogs[0]["tools"]))
        self.assertEqual(len(response.tools), 21 - 3)
        self.assertIsNone(response.next_cursor)
        self.assertEqual(len(logs.records), 1)
        event = json.loads(logs.records[0].getMessage())
        self.assertEqual(event, server.mcp._catalog_listing)
        self.assertEqual(event["status"], "constructed")
        self.assertEqual(event["sequence"], 1)
        self.assertEqual(event["pid"], os.getpid())
        self.assertIsNotNone(datetime.fromisoformat(event["utc"]).tzinfo)
        self.assertEqual(event["tool_count"], 21 - 3)
        self.assertEqual(event["names"], sorted(t.name for t in expected))
        self.assertEqual(event["read_only_count"], 12 - 1)
        self.assertFalse(event["cursor_present"])
        self.assertFalse(event["names_truncated"])
        self.assertNotIn(secret, json.dumps(event))
        self.assertNotIn(secret, "\n".join(logs.output))
        self.assertEqual(set(event), {
            "event", "status", "utc", "pid", "sequence", "tool_count", "names",
            "names_truncated", "read_only_count", "descriptor_sha256", "cursor_present",
        })

    async def test_health_and_helper_do_not_record_a_listing(self):
        with patch.object(server._CATALOG_LOGGER, "info") as log, patch.object(
            server.HERDR, "_call", AsyncMock(return_value={"snapshot": {"agents": []}})
        ):
            await server.mcp.list_tools()
            await server.bridge_health()
            self.assertIsNone(server.mcp._catalog_listing)
            log.assert_not_called()
            await server.mcp._handle_list_tools(None, None)
            observed = server.mcp._catalog_listing.copy()
            await server.bridge_health()
            self.assertEqual(server.mcp._catalog_listing, observed)
            self.assertEqual(log.call_count, 1)

    async def test_logging_failure_preserves_original_list_result(self):
        original = ListToolsResult(tools=await server.mcp.list_tools())
        with patch.object(server.MCPServer, "_handle_list_tools", AsyncMock(return_value=original)), \
                patch.object(server._CATALOG_LOGGER, "info", side_effect=RuntimeError("SYNTHETIC-LOG-SECRET")):
            result = await server.mcp._handle_list_tools(object(), object())
        self.assertIs(result, original)
        self.assertEqual(server.mcp._catalog_listing["sequence"], 1)
        self.assertNotIn("SYNTHETIC-LOG-SECRET", json.dumps(server.mcp._catalog_listing))

    async def test_descriptor_digest_tracks_schema_not_order_or_request(self):
        tools = await server.mcp.list_tools()
        result = ListToolsResult(tools=tools)
        with patch.object(server.MCPServer, "_handle_list_tools", AsyncMock(return_value=result)), \
                patch.object(server._CATALOG_LOGGER, "info") as log:
            await server.mcp._handle_list_tools(None, None)
            first = server.mcp._catalog_listing["descriptor_sha256"]
            canonical = json.dumps(sorted(
                [t.model_dump(mode="json", by_alias=True) for t in tools], key=lambda t: t["name"]
            ), sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
            self.assertEqual(first, hashlib.sha256(canonical.encode()).hexdigest())
            result.tools = list(reversed(result.tools))
            await server.mcp._handle_list_tools(object(), {"private": "SYNTHETIC-REQUEST-SECRET"})
            self.assertEqual(first, server.mcp._catalog_listing["descriptor_sha256"])
            changed = result.tools[0].model_copy(deep=True)
            changed.input_schema["description"] = "SYNTHETIC-DESCRIPTOR-SECRET"
            result.tools = [changed, *result.tools[1:]]
            await server.mcp._handle_list_tools(None, None)
            self.assertNotEqual(first, server.mcp._catalog_listing["descriptor_sha256"])
            self.assertEqual(server.mcp._catalog_listing["sequence"], 3)
            self.assertNotIn("SYNTHETIC", str(log.call_args_list))

    async def test_large_catalog_log_is_bounded_without_filtering_result(self):
        template = (await server.mcp.list_tools())[0]
        tools = [template.model_copy(update={"name": "public_" + str(i) + "x" * 200}) for i in range(70)]
        original = ListToolsResult(tools=tools, next_cursor="SYNTHETIC-CURSOR-SECRET")
        with patch.object(server.MCPServer, "_handle_list_tools", AsyncMock(return_value=original)), \
                patch.object(server._CATALOG_LOGGER, "info") as log:
            result = await server.mcp._handle_list_tools(None, None)
        self.assertIs(result, original)
        event = server.mcp._catalog_listing
        self.assertEqual(event["tool_count"], 70)
        self.assertEqual(len(event["names"]), 64)
        self.assertTrue(all(len(name) <= 128 for name in event["names"]))
        self.assertTrue(event["names_truncated"])
        self.assertTrue(event["cursor_present"])
        self.assertNotIn("SYNTHETIC-CURSOR-SECRET", str(log.call_args_list))

    async def test_configured_logger_emits_one_json_line_at_info(self):
        output = io.StringIO()
        handler = server._CATALOG_LOGGER.handlers[0]
        with patch.object(handler, "stream", output):
            await server.mcp._handle_list_tools(None, None)
        lines = output.getvalue().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0]), server.mcp._catalog_listing)

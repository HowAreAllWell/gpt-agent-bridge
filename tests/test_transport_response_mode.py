import ast
import asyncio
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("BRIDGE_PATH_TOKEN", "test-token-abcdefghijklmnopqrstuvwxyz-012345")

from gpt_agent_bridge import server

SERVER_SOURCE = Path(server.__file__).resolve().read_text(encoding="utf-8")


def _startup_mcp_run_call():
    tree = ast.parse(SERVER_SOURCE)
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != "main":
            continue
        for stmt in ast.walk(node):
            if (
                isinstance(stmt, ast.Call)
                and isinstance(stmt.func, ast.Attribute)
                and stmt.func.attr == "run"
                and isinstance(stmt.func.value, ast.Name)
                and stmt.func.value.id == "mcp"
            ):
                return stmt
    raise AssertionError("mcp.run(...) startup call not found in package server.main")


def _modern_post_scope(method: str, params: dict, extra_headers: list[tuple[bytes, bytes]]):
    first_receive = True
    stream_open = asyncio.Event()
    sent_messages: list[dict] = []

    async def receive():
        nonlocal first_receive
        if first_receive:
            first_receive = False
            return {
                "type": "http.request",
                "body": json.dumps({
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": method,
                    "params": {
                        "_meta": {
                            "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                            "io.modelcontextprotocol/clientCapabilities": {},
                        },
                        **params,
                    },
                }).encode(),
                "more_body": False,
            }
        await stream_open.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        sent_messages.append(message)

    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": server.MCP_PATH,
        "raw_path": server.MCP_PATH.encode(),
        "query_string": b"",
        "headers": [
            (b"accept", b"application/json, text/event-stream"),
            (b"content-type", b"application/json"),
            *extra_headers,
        ],
        "client": ("test", 1),
        "server": ("test", 80),
    }
    return scope, receive, send, sent_messages, stream_open


def _sse_app():
    from mcp.server.transport_security import TransportSecuritySettings

    with patch.object(server, "_mcp_auth_secrets", return_value=()):
        return server.mcp.streamable_http_app(
            streamable_http_path=server.MCP_PATH,
            json_response=False,
            stateless_http=True,
            transport_security=TransportSecuritySettings(
                enable_dns_rebinding_protection=False
            ),
        )


class TransportResponseModeTests(unittest.IsolatedAsyncioTestCase):
    def test_startup_contract_is_sse_capable_not_json_only(self):
        call = _startup_mcp_run_call()
        kwargs = {kw.arg: kw.value for kw in call.keywords}
        self.assertIsInstance(kwargs["transport"], ast.Constant)
        self.assertEqual(kwargs["transport"].value, "streamable-http")
        self.assertIsInstance(kwargs["json_response"], ast.Constant)
        self.assertIs(kwargs["json_response"].value, False)
        self.assertIsInstance(kwargs["host"], ast.Constant)
        self.assertEqual(kwargs["host"].value, "127.0.0.1")
        self.assertIsInstance(kwargs["port"], ast.Name)
        self.assertEqual(kwargs["port"].id, "PORT")
        self.assertIsInstance(kwargs["streamable_http_path"], ast.Name)
        self.assertEqual(kwargs["streamable_http_path"].id, "MCP_PATH")
        self.assertIsInstance(kwargs["transport_security"], ast.Name)
        self.assertEqual(kwargs["transport_security"].id, "security")

    async def test_modern_era_long_call_commits_sse_with_keepalive_pings(self):
        import mcp.server._streamable_http_modern as modern

        scope, receive, send, sent_messages, stream_open = _modern_post_scope(
            "tools/call",
            {"name": "search", "arguments": {"query": "delegate", "project_ref": "test-root"}},
            [
                (b"mcp-protocol-version", b"2026-07-28"),
                (b"mcp-method", b"tools/call"),
                (b"mcp-name", b"search"),
            ],
        )
        from gpt_agent_bridge.workspace_context import WorkspaceRegistry, WorkspaceRegistryStore
        import tempfile
        tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(tempdir.cleanup)
        registry = WorkspaceRegistry(server.ROOT, json.dumps({"test-root": str(server.ROOT)}),
            store=WorkspaceRegistryStore(Path(tempdir.name) / "registry.json"))
        registry_patch = patch.object(server, "_WORKSPACE_REGISTRY", registry)
        registry_patch.start()
        self.addCleanup(registry_patch.stop)
        lease = await server._access_gate().acquire("writer")
        request_task = None
        try:
            with patch.object(modern, "_SSE_PING_INTERVAL", 0.05):
                app = _sse_app()
                async with app.router.lifespan_context(app):
                    request_task = asyncio.create_task(app(scope, receive, send))
                    await asyncio.sleep(0.35)
                    start = next(
                        (m for m in sent_messages if m["type"] == "http.response.start"),
                        None,
                    )
                    self.assertIsNotNone(
                        start, "long reader-gated call did not commit SSE in time"
                    )
                    headers = {name.lower(): value for name, value in start["headers"]}
                    self.assertEqual(headers[b"content-type"], b"text/event-stream")
                    streamed = b"".join(
                        m.get("body", b"")
                        for m in sent_messages
                        if m["type"] == "http.response.body"
                    )
                    self.assertIn(b": ping", streamed)
                    self.assertNotIn(b"event: message", streamed)
                    await lease.release()
                    lease = None
                    await asyncio.wait_for(request_task, 10)
                    request_task = None
        finally:
            stream_open.set()
            if request_task is not None and not request_task.done():
                request_task.cancel()
                await asyncio.gather(request_task, return_exceptions=True)
            if lease is not None:
                await lease.release()

        final = sent_messages[-1]
        self.assertEqual(final["type"], "http.response.body")
        self.assertFalse(final["more_body"])
        self.assertIn(b"event: message", final["body"])
        self.assertIn(b'"result"', final["body"])

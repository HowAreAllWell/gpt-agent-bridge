import os
import unittest
from unittest.mock import patch

from starlette.requests import Request
from starlette.responses import PlainTextResponse
from mcp.server.transport_security import TransportSecurityMiddleware


os.environ.setdefault(
    "BRIDGE_PATH_TOKEN",
    "test-token-abcdefghijklmnopqrstuvwxyz-012345",
)

import server


class MCPAuthTests(unittest.IsolatedAsyncioTestCase):
    async def _call_middleware(
        self,
        secrets,
        *,
        path=None,
        request_path=None,
        headers=(),
        downstream=None,
    ):
        calls = []

        async def app(scope, receive, send):
            calls.append(scope)
            if downstream is not None:
                response = await downstream(scope, receive)
                await response(scope, receive, send)
                return
            await PlainTextResponse("ok")(scope, receive, send)

        middleware = server._MCPSharedSecretMiddleware(
            app,
            path or server.MCP_PATH,
            secrets,
        )
        messages = []
        scope = {
            "type": "http",
            "method": "POST",
            "path": request_path or path or server.MCP_PATH,
            "headers": [(key.lower().encode(), value.encode()) for key, value in headers],
        }

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            messages.append(message)

        await middleware(scope, receive, send)
        return calls, messages

    def test_auth_is_disabled_without_configuration(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(server.MCP_AUTH_SECRET_ENV, None)
            os.environ.pop(server.MCP_AUTH_PREVIOUS_SECRET_ENV, None)
            self.assertEqual(server._mcp_auth_secrets(), ())

    def test_current_and_previous_secrets_form_rotation_window(self):
        with patch.dict(
            os.environ,
            {
                server.MCP_AUTH_SECRET_ENV: "c" * 40,
                server.MCP_AUTH_PREVIOUS_SECRET_ENV: "p" * 40,
            },
        ):
            self.assertEqual(server._mcp_auth_secrets(), ("c" * 40, "p" * 40))

    def test_previous_secret_requires_current_secret(self):
        with patch.dict(
            os.environ,
            {server.MCP_AUTH_PREVIOUS_SECRET_ENV: "p" * 40},
            clear=False,
        ):
            os.environ.pop(server.MCP_AUTH_SECRET_ENV, None)
            with self.assertRaisesRegex(RuntimeError, "required"):
                server._mcp_auth_secrets()

    def test_secret_validation_rejects_short_or_duplicate_values(self):
        for current, previous, message in (
            ("short", None, "at least"),
            ("c" * 40, "c" * 40, "must differ"),
        ):
            with self.subTest(message=message), patch.dict(
                os.environ,
                {
                    server.MCP_AUTH_SECRET_ENV: current,
                    **(
                        {server.MCP_AUTH_PREVIOUS_SECRET_ENV: previous}
                        if previous is not None
                        else {}
                    ),
                },
                clear=False,
            ):
                if previous is None:
                    os.environ.pop(server.MCP_AUTH_PREVIOUS_SECRET_ENV, None)
                with self.assertRaisesRegex(RuntimeError, message):
                    server._mcp_auth_secrets()

    async def test_missing_and_invalid_auth_return_401_without_downstream_call(self):
        for authorization in (None, "Bearer wrong" + "x" * 35):
            headers = [] if authorization is None else [("Authorization", authorization)]
            with self.subTest(authorization=authorization):
                calls, messages = await self._call_middleware(("s" * 40,), headers=headers)
                self.assertEqual(calls, [])
                self.assertEqual(messages[0]["status"], 401)
                self.assertIn(
                    (b"www-authenticate", b"Bearer"),
                    messages[0]["headers"],
                )
                self.assertNotIn(b"s" * 40, messages[1]["body"])

    async def test_current_and_previous_auth_are_accepted(self):
        for secret in ("c" * 40, "p" * 40):
            with self.subTest(secret=secret):
                calls, messages = await self._call_middleware(
                    ("c" * 40, "p" * 40),
                    headers=[("Authorization", f"Bearer {secret}")],
                )
                self.assertEqual(len(calls), 1)
                self.assertEqual(messages[0]["status"], 200)

    async def test_wrong_path_is_left_to_existing_path_boundary(self):
        calls, messages = await self._call_middleware(
            ("s" * 40,),
            request_path="/mcp/not-the-configured-path",
        )
        self.assertEqual(len(calls), 1)
        self.assertEqual(messages[0]["status"], 200)

    async def test_valid_auth_does_not_bypass_host_origin_checks(self):
        security = server.TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=["127.0.0.1:8765"],
            allowed_origins=["https://chatgpt.com"],
        )

        async def transport_guard(scope, receive):
            request = Request(scope, receive)
            error = await TransportSecurityMiddleware(security).validate_request(
                request,
                is_post=True,
            )
            return error or PlainTextResponse("ok")

        for headers, expected_status in (
            (
                [
                    ("Authorization", "Bearer " + "s" * 40),
                    ("Content-Type", "application/json"),
                    ("Host", "evil.example"),
                ],
                421,
            ),
            (
                [
                    ("Authorization", "Bearer " + "s" * 40),
                    ("Content-Type", "application/json"),
                    ("Host", "127.0.0.1:8765"),
                    ("Origin", "https://evil.example"),
                ],
                403,
            ),
        ):
            with self.subTest(expected_status=expected_status):
                calls, messages = await self._call_middleware(
                    ("s" * 40,),
                    headers=headers,
                    downstream=transport_guard,
                )
                self.assertEqual(len(calls), 1)
                self.assertEqual(messages[0]["status"], expected_status)


if __name__ == "__main__":
    unittest.main()

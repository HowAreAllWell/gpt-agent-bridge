import os
import unittest
from unittest.mock import patch


os.environ.setdefault(
    "BRIDGE_PATH_TOKEN",
    "test-token-abcdefghijklmnopqrstuvwxyz-012345",
)

from gpt_agent_bridge import server


class TransportSecuritySettingsTests(unittest.TestCase):
    def test_security_is_disabled_without_allowlist_configuration(self):
        with patch.dict(
            os.environ,
            {
                "BRIDGE_MCP_ENABLE_DNS_REBINDING_PROTECTION": "false",
            },
            clear=False,
        ):
            for name in (
                "BRIDGE_MCP_ALLOWED_HOSTS",
                "BRIDGE_MCP_ALLOWED_ORIGINS",
            ):
                os.environ.pop(name, None)

            settings = server._transport_security_settings()

        self.assertFalse(settings.enable_dns_rebinding_protection)

    def test_exact_host_and_origin_are_accepted(self):
        with patch.dict(
            os.environ,
            {
                "BRIDGE_MCP_ENABLE_DNS_REBINDING_PROTECTION": "true",
                "BRIDGE_MCP_ALLOWED_HOSTS": '["bridge.example.com"]',
                "BRIDGE_MCP_ALLOWED_ORIGINS": '["https://chatgpt.com"]',
            },
            clear=False,
        ):
            settings = server._transport_security_settings()

        self.assertTrue(settings.enable_dns_rebinding_protection)
        self.assertEqual(settings.allowed_hosts, ["bridge.example.com"])
        self.assertEqual(settings.allowed_origins, ["https://chatgpt.com"])

    def test_port_wildcard_is_accepted_for_host_and_origin(self):
        with patch.dict(
            os.environ,
            {
                "BRIDGE_MCP_ENABLE_DNS_REBINDING_PROTECTION": "true",
                "BRIDGE_MCP_ALLOWED_HOSTS": '["bridge.example.com:*"]',
                "BRIDGE_MCP_ALLOWED_ORIGINS": '["https://chatgpt.com:*"]',
            },
            clear=False,
        ):
            settings = server._transport_security_settings()

        self.assertEqual(settings.allowed_hosts, ["bridge.example.com:*"])
        self.assertEqual(settings.allowed_origins, ["https://chatgpt.com:*"])

    def test_security_requires_at_least_one_allowed_host(self):
        with patch.dict(
            os.environ,
            {
                "BRIDGE_MCP_ENABLE_DNS_REBINDING_PROTECTION": "true",
                "BRIDGE_MCP_ALLOWED_HOSTS": "[]",
                "BRIDGE_MCP_ALLOWED_ORIGINS": "[\"https://chatgpt.com\"]",
            },
            clear=False,
        ):
            with self.assertRaisesRegex(RuntimeError, "requires a non-empty"):
                server._transport_security_settings()

    def test_allowlist_is_rejected_when_security_is_disabled(self):
        with patch.dict(
            os.environ,
            {
                "BRIDGE_MCP_ENABLE_DNS_REBINDING_PROTECTION": "false",
                "BRIDGE_MCP_ALLOWED_HOSTS": '["bridge.example.com"]',
                "BRIDGE_MCP_ALLOWED_ORIGINS": "[]",
            },
            clear=False,
        ):
            with self.assertRaisesRegex(RuntimeError, "true is required"):
                server._transport_security_settings()

    def test_arbitrary_wildcards_are_rejected(self):
        invalid_values = (
            ("BRIDGE_MCP_ALLOWED_HOSTS", '["*.example.com"]'),
            ("BRIDGE_MCP_ALLOWED_ORIGINS", '["https://*.example.com"]'),
        )
        for variable, value in invalid_values:
            with self.subTest(variable=variable):
                environment = {
                    "BRIDGE_MCP_ENABLE_DNS_REBINDING_PROTECTION": "true",
                    "BRIDGE_MCP_ALLOWED_HOSTS": '["bridge.example.com"]',
                    "BRIDGE_MCP_ALLOWED_ORIGINS": "[]",
                    variable: value,
                }
                with patch.dict(os.environ, environment, clear=False):
                    with self.assertRaisesRegex(RuntimeError, "unsupported wildcards"):
                        server._transport_security_settings()

    def test_duplicate_values_are_rejected(self):
        with patch.dict(
            os.environ,
            {
                "BRIDGE_MCP_ENABLE_DNS_REBINDING_PROTECTION": "true",
                "BRIDGE_MCP_ALLOWED_HOSTS": '["bridge.example.com", "bridge.example.com"]',
                "BRIDGE_MCP_ALLOWED_ORIGINS": "[]",
            },
            clear=False,
        ):
            with self.assertRaisesRegex(RuntimeError, "duplicate values"):
                server._transport_security_settings()


if __name__ == "__main__":
    unittest.main()

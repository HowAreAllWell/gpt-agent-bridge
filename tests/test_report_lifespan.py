"""Whole-server graceful shutdown owns the process-local report store once.

These tests drive the real ASGI lifespan protocol (the seam Uvicorn also drives)
against the server's streamable-http app. They never touch the live host's own
``/tmp/bridge-reports-*`` store: every store here is a fresh per-test ReportStore,
and forced-exit residue is created only in a disposable subprocess that the test
cleans up itself.
"""
import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('BRIDGE_PATH_TOKEN', 'test-token-abcdefghijklmnopqrstuvwxyz-012345')

import server
import work_reports
from mcp.server.transport_security import TransportSecuritySettings

REPO_ROOT = Path(server.__file__).resolve().parent


class _LifespanDriver:
    """Drive the app's real ASGI lifespan protocol the way Uvicorn does."""

    def __init__(self, app):
        self.app = app
        self.incoming = asyncio.Queue()
        self.sent = []
        self.task = None

    async def _receive(self):
        return await self.incoming.get()

    async def _send(self, message):
        self.sent.append(message)

    async def __aenter__(self):
        self.task = asyncio.create_task(self.app({'type': 'lifespan'}, self._receive, self._send))
        await self.incoming.put({'type': 'lifespan.startup'})
        await self._wait_for('lifespan.startup.complete')
        return self

    async def __aexit__(self, *exc):
        await self.incoming.put({'type': 'lifespan.shutdown'})
        await self._wait_for('lifespan.shutdown.complete')
        await self.task

    async def _wait_for(self, kind, timeout=10):
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while not any(m['type'] == kind for m in self.sent):
            failed = [m for m in self.sent if m['type'].endswith('.failed')]
            if failed:
                raise AssertionError(f'lifespan failure event: {failed[0]}')
            if self.task.done():
                raise AssertionError(f'lifespan task ended early: {self.task.exception()} / {self.sent}')
            if loop.time() > deadline:
                raise AssertionError(f'timed out waiting for {kind}: {self.sent}')
            await asyncio.sleep(0.01)


class ReportServerLifespanTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = work_reports.ReportStore()
        self.real_close = self.store.close
        self.close_calls = []
        self.addCleanup(self.real_close)  # LIFO: runs after patch.stopall; idempotent anyway.
        self.addCleanup(patch.stopall)
        patch.object(server, '_REPORT_STORE', self.store).start()
        patch.object(self.store, 'close', self.counted_close).start()
        with patch.object(server, '_mcp_auth_secrets', return_value=()):
            self.app = server.mcp.streamable_http_app(
                streamable_http_path=server.MCP_PATH,
                json_response=False,
                transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
            )
        self.session_manager = server.mcp._lowlevel_server._session_manager

    def counted_close(self):
        # Ordering evidence: the session manager's own teardown nulls its task
        # group, so close observing _task_group None (after run started) proves
        # report-store close ran after the MCP/session-manager lifespan work.
        started = getattr(self.session_manager, '_has_started', False)
        self.close_calls.append({'index': len(self.close_calls),
                                 'session_teardown_done': started and self.session_manager._task_group is None})
        self.real_close()

    async def post_unknown_session(self):
        """A client-session attempt that the running session manager answers."""
        sent, first = [], True

        async def receive():
            nonlocal first
            if first:
                first = False
                return {'type': 'http.request', 'body': b'{}', 'more_body': False}
            return {'type': 'http.disconnect'}

        async def send(message):
            sent.append(message)

        scope = {
            'type': 'http', 'asgi': {'version': '3.0', 'spec_version': '2.3'},
            'http_version': '1.1', 'method': 'POST', 'scheme': 'http',
            'path': server.MCP_PATH, 'raw_path': server.MCP_PATH.encode(),
            'query_string': b'', 'root_path': '', 'server': ('testserver', 80),
            'client': ('testclient', 123),
            'headers': [(b'content-type', b'application/json'), (b'content-length', b'2'),
                        (b'accept', b'application/json, text/event-stream'),
                        (b'mcp-session-id', b'unknown-session-id')],
        }
        await self.app(scope, receive, send)
        return next(m for m in sent if m['type'] == 'http.response.start')['status']

    async def test_graceful_whole_server_shutdown_closes_store_once_and_cleans_files(self):
        async with _LifespanDriver(self.app):
            # Lazy: whole-server startup alone allocates no report directory.
            self.assertIsNone(self.store._root)
            self.assertEqual(self.close_calls, [])
            key = self.store.allocate()
            root = Path(self.store._root)
            self.assertEqual(os.stat(root).st_mode & 0o777, 0o700)
            final, pending = root / key, root / (key + '.pending')
            final.write_text('published report', encoding='utf-8')
            pending.write_text('staging bytes', encoding='utf-8')
            # Request/client-session traffic while serving never closes the store.
            self.assertEqual(await self.post_unknown_session(), 404)
            self.assertEqual(self.close_calls, [])
        # Graceful whole-server teardown ran exactly once, after session-manager work.
        self.assertEqual([c['index'] for c in self.close_calls], [0])
        self.assertTrue(all(c['session_teardown_done'] for c in self.close_calls))
        self.assertFalse(final.exists())
        self.assertFalse(pending.exists())
        self.assertFalse(root.exists())
        self.assertEqual(self.store._keys, set())
        self.assertIsNone(self.store._fd)
        self.assertIsNone(self.store._root)

    async def test_no_report_lifecycle_creates_no_report_root(self):
        async with _LifespanDriver(self.app):
            self.assertIsNone(self.store._root)
            self.assertEqual(self.store._keys, set())
            self.assertEqual(self.close_calls, [])
        self.assertEqual([c['index'] for c in self.close_calls], [0])
        self.assertIsNone(self.store._root)
        self.assertEqual(self.store._keys, set())

    async def test_close_is_idempotent_tolerates_late_writer_and_keeps_unknown_names(self):
        key = self.store.allocate()
        root = Path(self.store._root)
        final, pending = root / key, root / (key + '.pending')
        final.write_text('x', encoding='utf-8')
        pending.write_text('y', encoding='utf-8')
        late = root / 'late-agent-writer.bin'
        late.write_bytes(b'arrived after dispatch')
        self.store.close()
        self.assertFalse(final.exists())
        self.assertFalse(pending.exists())
        # Unknown names are never broadened-deleted; rmdir failure is tolerated.
        self.assertTrue(late.exists())
        self.assertTrue(root.exists())
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        # Repeated close stays a silent no-op.
        self.store.close()
        self.store.close()
        self.assertEqual(self.store._keys, set())
        self.assertIsNone(self.store._fd)
        self.assertIsNone(self.store._root)
        self.assertTrue(late.exists())

    @unittest.skipIf(hasattr(os, 'geteuid') and os.geteuid() == 0,
                     'root ignores directory write-permission bits')
    async def test_unlink_failure_leaves_residue_without_raising(self):
        key = self.store.allocate()
        root = Path(self.store._root)
        final = root / key
        final.write_text('x', encoding='utf-8')
        os.chmod(root, 0o500)  # Drop write permission: unlink and rmdir must fail.
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        self.addCleanup(os.chmod, root, 0o700)
        self.store.close()  # Must not raise.
        self.assertTrue(final.exists())
        self.assertTrue(root.exists())
        self.assertEqual(self.store._keys, set())
        self.assertIsNone(self.store._fd)

    async def test_forced_termination_leaves_residue_outside_the_guarantee(self):
        # A real abrupt exit (no lifespan teardown, no atexit) leaves files behind;
        # the child only ever creates its own disposable store and this test
        # removes it again. This documents the accepted residual, it is not faked.
        child = (
            "import os, work_reports\n"
            "store = work_reports.ReportStore()\n"
            "key = store.allocate()\n"
            "with open(os.path.join(store._root, key), 'w', encoding='utf-8') as handle:\n"
            "    handle.write('forced-exit residue evidence')\n"
            "print(store._root, flush=True)\n"
            "os._exit(1)\n"
        )
        proc = subprocess.run([sys.executable, '-c', child], cwd=str(REPO_ROOT),
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 1, proc.stderr)
        root = Path(proc.stdout.strip().splitlines()[-1])
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        self.assertTrue(root.is_dir(), proc.stderr)
        self.assertTrue(any(name.endswith('.txt') for name in os.listdir(root)))

    def test_forced_termination_residual_is_documented_not_faked(self):
        capacity = (REPO_ROOT / 'docs' / 'WORK-CAPACITY.md').read_text(encoding='utf-8').lower()
        for phrase in ('/tmp/bridge-reports-', '0700', 'lazily created', 'per-process',
                       'graceful whole-server shutdown', 'sigkill', 'atexit',
                       'never scans', 'no startup scan'):
            self.assertIn(phrase, capacity)
        lifecycle = (REPO_ROOT / 'docs' / 'LIFECYCLE-RESTART-CONTRACT.md').read_text(encoding='utf-8').lower()
        for phrase in ('graceful whole-server shutdown', 'sigkill', 'does not scan',
                       '/tmp/bridge-reports-', 'no startup scan'):
            self.assertIn(phrase, lifecycle)


if __name__ == '__main__':
    unittest.main()

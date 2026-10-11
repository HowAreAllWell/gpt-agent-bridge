"""Actual server call paths and gates; workers/resolution use temporary fixtures."""
import asyncio
import os
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ.setdefault("BRIDGE_PATH_TOKEN", "synthetic-reader-cancellation-token-0123456789")
import server


class ReaderCancellationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.workspace = SimpleNamespace(root=self.root)
        self.target = SimpleNamespace(workspace=self.workspace)
        for name, value in [
            ("_resolve_evidence_target", lambda *a: self.target),
            ("_required_project_context", lambda *a: self.workspace),
            ("_evidence_result", lambda result, target: result),
        ]:
            p = patch.object(server, name, value)
            p.start()
            self.addCleanup(p.stop)

    def route(self, name):
        if name == "read":
            return server, "_compute_bridge_read", lambda: server.read("p", "fixture.txt")
        if name == "search":
            return server, "_compute_workspace_search", lambda: server.search("p", "needle")
        if name == "current":
            return server, "_compute_workspace_diff", lambda: server.diff("p")
        if name == "pinned":
            return server, "_compute_revision_diff", lambda: server.diff("p", base="a", target="b")
        return server._project_continuity, "checkpoint", lambda: server.checkpoint("p", "new", "missing")

    async def exercise(self, name, fails, repeated):
        owner, attr, call = self.route(name)
        started, finish, ended = threading.Event(), threading.Event(), threading.Event()
        events = []
        def worker(*args):
            started.set()
            try:
                if not finish.wait(3):
                    raise AssertionError("fixture cleanup deadline")
                if fails:
                    raise ValueError("terminal-worker-failure")
                return {"ok": True}
            finally:
                events.append("worker_end")
                ended.set()
        gate = server._access_gate(self.root)
        writer_acquired = asyncio.Event()
        async def writer():
            lease = await gate.acquire("writer")
            events.append("writer_acquired")
            writer_acquired.set()
            await lease.release()
        with patch.object(owner, attr, worker):
            task = asyncio.create_task(call())
            competing = None
            try:
                for _ in range(200):
                    if started.is_set():
                        break
                    await asyncio.sleep(.005)
                self.assertTrue(started.is_set())
                competing = asyncio.create_task(writer())
                task.cancel()
                await asyncio.sleep(.03)
                if repeated:
                    task.cancel()
                    await asyncio.sleep(.03)
                early = writer_acquired.is_set()
                held = not task.done()
                finish.set()
                cancelled = False
                try:
                    await task
                except asyncio.CancelledError:
                    cancelled = True
                await competing
                self.assertFalse(early, "writer admitted while worker still running")
                self.assertTrue(held, "caller ended before worker joined")
                self.assertTrue(cancelled, "worker exception replaced cancellation")
                self.assertTrue(ended.is_set())
                self.assertEqual(events, ["worker_end", "writer_acquired"])
                self.assertEqual(gate.active_readers, 0)
                self.assertFalse(gate.writer_active)
            finally:
                finish.set()
                await asyncio.gather(task, *([competing] if competing else []), return_exceptions=True)

    async def test_cancel_holds_real_gate(self):
        for name in ("read", "search", "current", "pinned", "current_state_update"):
            for fails in (False, True):
                for repeated in (False, True):
                    with self.subTest(route=name, worker_fails=fails, repeated=repeated):
                        await self.exercise(name, fails, repeated)

    async def test_normal_return_and_failure(self):
        for name in ("read", "search", "current", "pinned", "current_state_update"):
            owner, attr, call = self.route(name)
            with self.subTest(route=name):
                with patch.object(owner, attr, return_value={"ok": True, "sentinel": name}):
                    self.assertEqual(await call(), {"ok": True, "sentinel": name})
                with patch.object(owner, attr, side_effect=ValueError("normal failure")):
                    with self.assertRaisesRegex(ValueError, "normal failure"):
                        await call()
                gate = server._access_gate(self.root)
                self.assertEqual(gate.active_readers, 0)
                self.assertFalse(gate.writer_active)

import asyncio
import inspect
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch


os.environ.setdefault(
    "BRIDGE_PATH_TOKEN",
    "test-token-abcdefghijklmnopqrstuvwxyz-012345",
)

import server
import herdr_backend


class LifecycleContractTests(unittest.IsolatedAsyncioTestCase):


    async def test_access_gate_allows_readers_and_prioritizes_waiting_writer(self):
        gate = server._AccessGate("test-worktree")
        first = await gate.acquire("read_only")
        second = await gate.acquire("read_only")
        writer_task = asyncio.create_task(gate.acquire("writer"))
        reader_task = asyncio.create_task(gate.acquire("read_only"))
        await asyncio.sleep(0)
        self.assertFalse(writer_task.done())
        self.assertFalse(reader_task.done())
        await first.release()
        await second.release()
        writer = await asyncio.wait_for(writer_task, 1)
        self.assertTrue(gate.writer_active)
        self.assertFalse(reader_task.done())
        await writer.release()
        reader = await asyncio.wait_for(reader_task, 1)
        await reader.release()
        self.assertEqual(gate.snapshot()["active_readers"], 0)


    def test_closed_loop_access_gate_is_safely_replaced(self):
        async def hold_writer():
            gate = server._access_gate()
            lease = await gate.acquire("writer")
            return gate, lease

        with patch.object(server, "_ACCESS_GATES", {}):
            loop_a = asyncio.new_event_loop()
            try:
                gate_a, _lease_a = loop_a.run_until_complete(hold_writer())
            finally:
                loop_a.close()
            async def acquire_writer():
                gate_b = server._access_gate()
                lease_b = await asyncio.wait_for(gate_b.acquire("writer"), 1)
                await lease_b.release()
                return gate_b

            gate_b = asyncio.run(acquire_writer())

        self.assertIsNot(gate_a, gate_b)


if __name__ == "__main__":
    unittest.main()

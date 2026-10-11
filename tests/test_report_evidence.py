"""Bounded dedicated-report probes; no registry lock over I/O or retry delay."""
import asyncio
import unittest
from unittest.mock import patch
import os
os.environ.setdefault('BRIDGE_PATH_TOKEN', 'test-token-abcdefghijklmnopqrstuvwxyz-012345')
import server


class ReportEvidenceTests(unittest.IsolatedAsyncioTestCase):
    async def probe(self, values, interval=1):
        calls, delays = [], []
        values = iter(values)
        def read(*args):
            acquired = server._WORK_REGISTRY_LOCK.acquire(blocking=False)
            self.assertTrue(acquired, 'report I/O must run without the registry lock')
            server._WORK_REGISTRY_LOCK.release()
            calls.append(args)
            value = next(values)
            if isinstance(value, Exception):
                raise value
            return value
        async def delay(seconds):
            def check():
                acquired = server._WORK_REGISTRY_LOCK.acquire(blocking=False)
                if acquired:
                    server._WORK_REGISTRY_LOCK.release()
                return acquired
            self.assertTrue(await asyncio.to_thread(check))
            delays.append(seconds)
        with patch.object(server._REPORT_STORE, 'read', read), \
                patch.object(server, '_report_evidence_sleep', delay), \
                patch.object(server, '_REPORT_EVIDENCE_RETRY_INTERVAL_SECONDS', interval):
            result = await server._probe_requested_reports([('work-a', 'key')])
        return result, calls, delays

    async def test_readable_missing_rename_race_invalid_unknown(self):
        missing = {'ok': False, 'error_type': 'WorkReportMissing'}
        readable = {'ok': True}
        cases = [([readable], 'readable', 1, 0), ([missing] * 3, 'missing', 3, 2),
                 ([missing, readable], 'readable', 2, 1)]
        cases += [([{'ok': False, 'error_type': code}], 'invalid', 1, 0)
                  for code in server._REPORT_EVIDENCE_INVALID]
        cases += [([value], 'unknown', 1, 0) for value in (None, {}, 'bad', RuntimeError('private'))]
        for values, status, reads, sleeps in cases:
            with self.subTest(status=status, values=values):
                result, calls, delays = await self.probe(values)
                self.assertEqual(result, [{'work_ref': 'work-a', 'status': status}])
                self.assertEqual(len(calls), reads)
                self.assertEqual(len(delays), sleeps)
                self.assertLessEqual(sum(delays), 5)
                self.assertTrue(all(call == ('key', 0, 1, None) for call in calls))

    async def test_cap_and_empty_key(self):
        missing = {'ok': False, 'error_type': 'WorkReportMissing'}
        _, _, delays = await self.probe([missing] * 3, interval=100)
        self.assertEqual(sum(delays), 5)
        with patch.object(server._REPORT_STORE, 'read') as read:
            self.assertEqual(await server._read_requested_report(None), 'unknown')
            read.assert_not_called()

    async def test_batch_shares_retry_windows_and_drops_nonmissing(self):
        calls, sleeps = [], []
        async def read(key):
            calls.append(key)
            return 'missing' if key == 'missing' else 'readable'
        async def delay(seconds):
            sleeps.append(seconds)
        with patch.object(server, '_read_requested_report', read), \
                patch.object(server, '_report_evidence_sleep', delay):
            result = await server._probe_requested_reports([('one', 'ready'), ('two', 'missing')])
        self.assertEqual(result, [{'work_ref': 'one', 'status': 'readable'}, {'work_ref': 'two', 'status': 'missing'}])
        self.assertEqual(calls.count('ready'), 1)
        self.assertEqual(calls.count('missing'), 3)
        self.assertEqual(sleeps, [1, 1])

"""Live fixed-query failure/cleanup paths; injected processes only in test /tmp."""
import asyncio
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from gpt_agent_bridge import fixed_git


class FixedGitLifecycleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    async def test_spawn_and_nonzero_failures_are_not_clean(self):
        with patch.object(fixed_git.subprocess,'Popen',side_effect=FileNotFoundError('fixture')):
            rc,out,err = await fixed_git.observe_async(self.root,['status','--porcelain'])
        self.assertEqual(rc,-1)
        self.assertEqual(out,b'')
        self.assertIn(b'GitObservationSpawnError',err)
        rc,out,err = await fixed_git.observe_async(self.root,['rev-parse','--verify','HEAD'])
        self.assertNotEqual(rc,0)
        self.assertEqual(out,b'')

    async def test_inherited_pipes_timeout_reaps_group(self):
        actual = subprocess.Popen
        pidfile=self.root/'child'
        code=f"""import os,signal,time
if os.fork()==0:
 signal.signal(signal.SIGTERM,signal.SIG_IGN)
 open({str(pidfile)!r},'w').write(str(os.getpid()))
 os.write(1,b'partial-output')
 os.write(2,b'partial-error')
 time.sleep(30)
else: time.sleep(.03)
"""
        children=[]
        def spawn(argv,**kwargs):
            child=actual([sys.executable,'-c',code],**kwargs);children.append(child);return child
        try:
            with patch.object(fixed_git.subprocess,'Popen',side_effect=spawn):
                rc,out,err=await fixed_git.observe_async(self.root,['rev-parse','HEAD'],.15,1024,1024)
            self.assertEqual(rc,-1)
            self.assertEqual(out,b'partial-output')
            self.assertIn(b'coverage incomplete',err)
            self.assertTrue(all(c.poll() is not None for c in children))
            pid=int(pidfile.read_text())
            status=Path(f'/proc/{pid}/status')
            if status.exists():
                self.assertIn('State:\tZ',status.read_text())
        finally:
            if pidfile.exists():
                try: os.kill(int(pidfile.read_text()),signal.SIGKILL)
                except ProcessLookupError: pass

    async def test_cancellation_joins_fixed_query_worker_twice(self):
        ready=threading.Event();actual=subprocess.Popen;children=[]
        def spawn(argv,**kwargs):
            child=actual([sys.executable,'-c','import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(30)'],**kwargs)
            children.append(child);ready.set();return child
        with patch.object(fixed_git.subprocess,'Popen',side_effect=spawn):
            task=asyncio.create_task(fixed_git.observe_async(self.root,['rev-parse','HEAD'],5))
            try:
                self.assertTrue(await asyncio.to_thread(ready.wait,2))
                task.cancel()
                await asyncio.sleep(0)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError): await task
            finally:
                if not task.done(): task.cancel();await asyncio.gather(task,return_exceptions=True)
        self.assertEqual(len(children),1)
        self.assertIsNotNone(children[0].poll())

    async def test_escaped_pipe_timeout_does_not_claim_complete(self):
        actual=subprocess.Popen;pidfile=self.root/'escaped'
        code=f"""import os,time
if os.fork()==0:
 os.setsid()
 open({str(pidfile)!r},'w').write(str(os.getpid()))
 os.write(1,b'kept')
 time.sleep(30)
else: time.sleep(.03)
"""
        def spawn(argv,**kwargs): return actual([sys.executable,'-c',code],**kwargs)
        try:
            with patch.object(fixed_git.subprocess,'Popen',side_effect=spawn):
                rc,out,err=await fixed_git.observe_async(self.root,['rev-parse','HEAD'],.15,1024,1024)
            self.assertEqual(rc,-1)
            self.assertEqual(out,b'kept')
            self.assertIn(b'coverage incomplete',err)
        finally:
            if pidfile.exists():
                try: os.kill(int(pidfile.read_text()),signal.SIGKILL)
                except ProcessLookupError: pass

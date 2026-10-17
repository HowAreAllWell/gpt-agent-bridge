"""Project isolation at the real ASGI feed, no browser/session/token fixture."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from starlette.applications import Starlette
from gpt_agent_bridge.browser_notifications import BrowserNotifications
from tests import test_browser_notifications as fixtures


class ProjectsTests(unittest.IsolatedAsyncioTestCase):
    setUp = fixtures.BrowserNotificationTests.setUp
    work = fixtures.BrowserNotificationTests.work
    request = fixtures.BrowserNotificationTests.request

    async def test_two_registered_roots_have_independent_blocked_cursors_and_checks(self):
        self.config={'version':2,'projects':[{'project_ref':'p','root':'/project'},{'project_ref':'b','root':'/other'}],
                     'extension_id':'a'*32,'token':'t'*48,'port':8765}
        self.feed=BrowserNotifications(self.config)
        roots={'p':'/project','b':'/other'}
        async def read(w):return {'ok':w.get('readable',True),'file_sha256':'b'*64}
        self.app=Starlette(routes=self.feed.routes(lambda p,r:[w for w in self.works if (w['project_ref'],w['workspace_root'])==(p,r)],read,roots.__getitem__))
        a=self.work(readable=False);b=self.work(project_ref='b',workspace_root='/other')
        first=(await self.request('?project_ref=p')).json();second=(await self.request('?project_ref=b')).json()
        self.assertEqual(first['cursor'],0);self.assertEqual(second['events'][0]['work_ref'],b['work_ref'])
        self.assertEqual((await self.request('?project_ref=b&check='+a['work_ref'])).json()['check']['state'],'unavailable')
        self.assertEqual((await self.request()).status_code,410)
        scope=self.feed.scope_id(self.config['projects'][0]);roots['p']='/replacement'
        self.assertEqual((await self.request('?project_ref=p&scope_id='+scope)).status_code,410)
        self.assertEqual((await self.request('?project_ref=b')).json()['events'][0]['work_ref'],b['work_ref'])

    async def test_reload_adds_new_project_without_new_epoch_or_reinterpreting_old(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'config.json';path.write_text(json.dumps(self.config));path.chmod(0o600)
            self.feed.config_path=path;epoch=self.feed.epoch
            old=self.work();self.assertEqual(self.feed.sequence,1)
            config={k:self.config[k] for k in ['extension_id','token','port']}
            config.update(version=2,projects=[{'project_ref':'p','root':'/project'},{'project_ref':'b','root':'/b'}])
            path.write_text(json.dumps(config));self.work(project_ref='b',workspace_root='/b')
            self.assertEqual(self.feed.sequence,2);self.assertEqual(self.feed.epoch,epoch)
            path.chmod(0o644);self.work(project_ref='b',workspace_root='/b');self.assertEqual(self.feed.sequence,2)
            self.assertIsNone(self.feed.config);self.assertEqual(old['browser_notification_sequence'],1)


class ConfigTests(unittest.TestCase):
    def test_secret_file_and_duplicate_projects_fail_closed(self):
        c={'version':2,'projects':[],'extension_id':'a'*32,'token':'t'*48,'port':8765}
        self.assertEqual(BrowserNotifications.validate_config(c),c)
        for rows in [[{'project_ref':'../bad','root':'/a'}],[{'project_ref':'a','root':'/a/../b'}],
                     [{'project_ref':'a','root':'/a'},{'project_ref':'a','root':'/b'}]]:
            with self.assertRaises(ValueError):BrowserNotifications.validate_config({**c,'projects':rows})
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'c';p.write_text(json.dumps(c));p.chmod(0o600)
            q=Path(d)/'link';q.symlink_to(p)
            with self.assertRaises(OSError):BrowserNotifications.read_config(q)
            p.chmod(0o644)
            with self.assertRaises(ValueError):BrowserNotifications.read_config(p)

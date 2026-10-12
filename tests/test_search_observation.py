"""Opt-in untracked logs with bounded transport; no native Agent or host I/O."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from gpt_agent_bridge import server
from gpt_agent_bridge import search_observation as so
from tests import test_file_observation as fixtures


class UntrackedSearchTests(unittest.IsolatedAsyncioTestCase):
    setUp=fixtures.FileObservationTests.setUp
    git=fixtures.FileObservationTests.git
    good=fixtures.FileObservationTests.good
    bad=fixtures.FileObservationTests.bad

    async def test_opt_in_nonignored_logs_exact_read_locators_and_default(self):
        service=so.UntrackedSearch(server._resolve_evidence_target,server._access_gate)
        for root,work in [(self.root,None),(self.link,'w')]:
            (root/'.gitignore').write_text('ignored/\n')
            (root/'tracked').write_text('needle tracked\n')
            (root/'ignored').mkdir(); (root/'ignored/tracked').write_text('needle tracked despite ignore\n')
            self.git('add','.gitignore','tracked',root=root)
            self.git('add','-f','ignored/tracked',root=root)
            (root/'ignored/private').write_text('needle NEVER\n')
            (root/'log \n\t" -> 字').write_text('no\nneedle one\nneedle two\n')
            (root/' \t\n ').write_text('needle whitespace\n')
            (root/'binary').write_bytes(b'\0needle\n')
            (self.outside/'escape').write_text('needle NEVER-OUTSIDE\n')
            (root/'escape-link').symlink_to(self.outside/'escape')
            (root/'escape-dir').symlink_to(self.outside,target_is_directory=True)
            os.mkfifo(root/'fifo')
            default=await server.search('p','needle',work_ref=work)
            self.assertTrue(default['ok'],default)
            self.assertEqual({m['path'] for m in default['matches']},{'tracked','ignored/tracked'})
            offset=0; matches=[]
            while True:
                page=self.good(await service.search('p','needle',work_ref=work,match_offset=offset,max_matches=2))
                matches.extend(page['matches']); offset=page['match_next_offset']
                self.assertEqual(page['coverage']['untracked_files'],'included_nonignored')
                if offset is None: break
            self.assertEqual(len(matches),5,matches)
            self.assertFalse(any('NEVER' in m['line_text'] for m in matches))
            for m in matches:
                read=await server.read('p',**m['read_locator'],work_ref=work)
                self.assertTrue(read['ok'],read)
                self.assertTrue(read['content'].startswith(m['line_text']))
            one=self.good(await service.search('p','needle',path_prefix='log \n\t" -> 字',work_ref=work))
            self.assertEqual(one['total_matches'],2)
            self.bad(await service.search('p','needle',path_prefix='escape-dir',work_ref=work))

    async def test_literal_prefix_long_lines_and_json_page_budget(self):
        service=so.UntrackedSearch(server._resolve_evidence_target,server._access_gate)
        name=':(exclude)file'
        (self.root/name).write_text('needle '+('😀'*1000)+'\n')
        (self.root/'other').write_text('needle NEVER\n')
        page=self.good(await service.search('p','needle',path_prefix=name))
        self.assertEqual(page['total_matches'],1); self.assertEqual(page['matches'][0]['path'],name)
        self.assertTrue(page['matches'][0]['line_text_truncated'])
        for i in range(60): (self.root/(f'{i:03}'+('😀'*45))).write_text('needle '+('😀'*300)+'\n')
        offset=0; matches=[]
        while True:
            page=self.good(await service.search('p','needle',max_matches=50,match_offset=offset))
            matches.extend(page['matches']); offset=page['match_next_offset']
            if offset is None: break
        self.assertEqual(len(matches),62)
        self.assertEqual(len({m['path'] for m in matches}),62)

    async def test_caps_failures_and_bad_records_have_no_completeness(self):
        service=so.UntrackedSearch(server._resolve_evidence_target,server._access_gate)
        (self.root/'log').write_text('needle\n'*2000)
        with patch.object(so,'MAX_STDOUT',64):
            self.bad(await service.search('p','needle'),'SearchObservationTooLarge')
        cases=[(2,b''),(0,b'broken'),(0,b'file\0bad\0line\n'),
               (0,b'bad\xff\0'+b'1\0line\n'),(1,b'file\0'+b'1\0line\n')]
        for answer in cases:
            with self.subTest(answer=answer),patch.object(so,'_capture',return_value=answer):
                self.bad(await service.search('p','needle'))
        with patch.object(so,'_capture',return_value=(1,b'')):
            page=self.good(await service.search('p','absent'))
            self.assertEqual(page['total_matches'],0)
        with patch.object(so,'_capture',side_effect=FileNotFoundError(2,'missing git')):
            self.bad(await service.search('p','needle'))

    async def test_pipe_timeout_stderr_cap_and_child_reaped(self):
        # Replace only process creation with synthetic Python pipe writers.
        # Production argv is separately asserted; no real hooks/drivers created.
        real=subprocess.Popen; children=[]
        def spawn_program(code):
            def spawn(argv,**kwargs):
                self.assertEqual(argv[:3],['git','--no-pager','--no-optional-locks'])
                if not str(kwargs.get('cwd','')).startswith('/proc/self/fd/'):
                    return real(argv,**kwargs)
                child=real([sys.executable,'-c',code],**kwargs); children.append(child); return child
            return spawn
        service=so.UntrackedSearch(server._resolve_evidence_target,server._access_gate)
        with patch.object(so.fixed_git.subprocess,'Popen',side_effect=spawn_program('import time; time.sleep(2)')),patch.object(so,'GREP_SECONDS',.05):
            self.bad(await service.search('p','needle'),'SearchTimedOut')
        with patch.object(so.fixed_git.subprocess,'Popen',side_effect=spawn_program('import os; os.write(2,b"x"*10000)')):
            self.bad(await service.search('p','needle'),'SearchObservationTooLarge')
        self.assertTrue(all(c.poll() is not None for c in children))

    async def test_two_pass_changes_and_prefix_replacement_fail(self):
        service=so.UntrackedSearch(server._resolve_evidence_target,server._access_gate)
        with patch.object(so,'_capture',side_effect=[(0,b'file\0' + b'1\0old\n'),(0,b'file\0' + b'1\0new\n')]):
            self.bad(await service.search('p','needle'),'SearchChanged')
        directory=self.root/'logs'; directory.mkdir()
        (directory/'one').write_text('needle')
        def swapped(*args,**kwargs):
            if not directory.is_symlink():
                directory.rename(self.root/'saved-logs')
                directory.symlink_to(self.outside,target_is_directory=True)
            return 1,b''
        with patch.object(so,'_capture',side_effect=swapped):
            self.bad(await service.search('p','needle',path_prefix='logs'),'SearchTargetChanged')

    async def test_invalid_inputs_and_fixed_git_options(self):
        resolver=unittest.mock.Mock(side_effect=AssertionError('no resolution'))
        service=so.UntrackedSearch(resolver,server._access_gate)
        for args in [{'query':''},{'query':'x\0y'},{'query':'x\ny'},{'query':'x'*501},{'query':'\udcff'},
                     {'query':'x','max_matches':True},{'query':'x','match_offset':-1},
                     {'query':'x','path_prefix':'../outside'},{'query':'x','path_prefix':'.git'}]:
            self.bad(await service.search('p',**args))
        resolver.assert_not_called()
        argv=so.grep_argv('-needle','a -> b')
        self.assertIn('--untracked',argv); self.assertIn('--exclude-standard',argv)
        self.assertIn('--no-textconv',argv); self.assertIn('--no-recurse-submodules',argv)
        self.assertIn('--no-column',argv)
        self.assertEqual(argv[-4:],['-e','-needle','--',':(literal)a -> b'])

    async def test_default_tracked_raw_preview_contract_and_hostile_records(self):
        # Both branches return the raw first <=300 decoded characters of the
        # matching line without an invented truncation marker; CR is preserved.
        long_line = 'needle ' + 'y' * 305
        (self.root / 'long').write_text(long_line + '\n')
        (self.root / 'crlf').write_bytes(b'needle one\r\nplain two\r\n')
        (self.root / 'name.txt').write_text('name.txt here\n')
        self.git('add', 'long', 'crlf', 'name.txt', root=self.root)
        default = self.good(await server.search('p', 'needle'))
        by_path = {m['path']: m for m in default['matches']}
        self.assertEqual(by_path['long']['line_text'], long_line[:300])
        self.assertTrue(by_path['long']['line_text_truncated'])
        self.assertNotIn('...[truncated', by_path['long']['line_text'])
        self.assertEqual(by_path['crlf']['line_text'], 'needle one\r')
        self.assertFalse(by_path['crlf']['line_text_truncated'])
        for m in default['matches']:
            read = await server.read('p', **m['read_locator'])
            self.assertTrue(read['ok'], read)
            self.assertTrue(read['content'].startswith(m['line_text']))
        # The explicit -e operand keeps a query naming an existing file a
        # pattern; the old post-"--" form silently returned zero matches.
        named = self.good(await server.search('p', 'name.txt'))
        self.assertEqual([m['path'] for m in named['matches']], ['name.txt'])
        self.assertEqual(named['matches'][0]['line_number'], 1)
        # Opt-in untracked branch: same raw preview and exact read locator.
        (self.root / 'ulog').write_text('needle ' + 'z' * 310 + '\n')
        page = self.good(await server.search('p', 'needle', include_untracked=True, max_matches=50))
        item = next(m for m in page['matches'] if m['path'] == 'ulog')
        self.assertEqual(item['line_text'], ('needle ' + 'z' * 310)[:300])
        self.assertTrue(item['line_text_truncated'])
        self.assertNotIn('...[truncated', item['line_text'])
        read = await server.read('p', **item['read_locator'])
        self.assertTrue(read['content'].startswith(item['line_text']))
        # Default branch shares the opt-in single-pattern query contract.
        for query in ('x\ny', '\udcff', 'x\0y', 'x' * 501):
            self.assertEqual((await server.search('p', query))['error_type'], 'InvalidQuery')
        # Malformed, nonpositive and overlong line records never claim coverage.
        actual = server._git_run_bytes_bounded
        for answer in ((0, b'file' + b'\0' + b'1' + b'\0' + b'line', b''),
                       (0, b'file\0' + b'0' + b'\0line\n', b''),
                       (0, b'file\0' + b'1' * 13 + b'\0line\n', b''),
                       (1, b'file\0' + b'1' + b'\0line\n', b'')):
            def observe(*args, **kwargs):
                return answer if args[0] == 'grep' else actual(*args, **kwargs)
            with self.subTest(answer=answer), patch.object(server, '_git_run_bytes_bounded', side_effect=observe):
                self.bad(await server.search('p', 'needle'), 'SearchOutputMalformed')
        with patch.object(server, '_git_run_bytes_bounded', return_value=(1, b'', b'')):
            page = self.good(await server.search('p', 'absent'))
            self.assertEqual(page['total_matches'], 0)

    async def test_hostile_color_column_config_cannot_corrupt_either_branch(self):
        service = so.UntrackedSearch(server._resolve_evidence_target, server._access_gate)
        line300 = 'needle ' + 'x' * 293   # exactly 300 decoded characters
        line301 = 'needle ' + 'y' * 294   # 301 decoded characters
        (self.root / 'edge.txt').write_bytes(
            (line300 + '\n' + line301 + '\nneedle cr\r\nneedle plain\n').encode())
        (self.root / 'ulog').write_text('needle untracked\n')
        self.git('add', 'edge.txt', root=self.root)
        hostile = {'GIT_CONFIG_COUNT': '2',
                   'GIT_CONFIG_KEY_0': 'color.grep', 'GIT_CONFIG_VALUE_0': 'always',
                   'GIT_CONFIG_KEY_1': 'grep.column', 'GIT_CONFIG_VALUE_1': 'true'}
        with patch.dict(os.environ, hostile):
            default = self.good(await server.search('p', 'needle'))
            optin = self.good(await service.search('p', 'needle', max_matches=50))
        for label, page in (('default', default), ('opt-in', optin)):
            for m in page['matches']:
                self.assertIsInstance(m['line_number'], int, (label, m))
                self.assertGreaterEqual(m['line_number'], 1)
                self.assertNotIn('\x1b[', m['line_text'], (label, m))
                self.assertNotIn('\x00', m['line_text'], (label, m))
            edge = {m['line_number']: m for m in page['matches'] if m['path'] == 'edge.txt'}
            if label == 'default':
                self.assertEqual(set(edge), {1, 2, 3, 4})
                self.assertEqual({m['path'] for m in page['matches']}, {'edge.txt'})
            else:
                self.assertEqual(len(edge), 4)
                self.assertIn('ulog', {m['path'] for m in page['matches']})
            self.assertEqual(edge[1]['line_text'], line300, label)
            self.assertFalse(edge[1]['line_text_truncated'])
            self.assertEqual(edge[2]['line_text'], line301[:300], label)
            self.assertTrue(edge[2]['line_text_truncated'])
            self.assertEqual(edge[3]['line_text'], 'needle cr\r', label)
            for m in page['matches']:
                read = await server.read('p', **m['read_locator'])
                self.assertTrue(read['ok'], read)
                self.assertTrue(read['content'].startswith(m['line_text']))
        shared_default = {m['line_number']: m['line_text'] for m in default['matches']}
        shared_optin = {m['line_number']: m['line_text'] for m in optin['matches'] if m['path'] == 'edge.txt'}
        self.assertEqual(shared_default, shared_optin)

    async def test_default_search_whitespace_only_root_name_stays_followable(self):
        (self.root / ' \t\n ').write_text('needle whitespace\n')
        self.git('add', ' \t\n ', root=self.root)
        result = self.good(await server.search('p', 'needle'))
        match, = result['matches']
        self.assertEqual(match['path'], './ \t\n ')
        self.assertEqual(match['read_locator']['path'], './ \t\n ')
        self.assertEqual(match['line_text'], 'needle whitespace')
        read = await server.read('p', **match['read_locator'])
        self.assertTrue(read['ok'], read)
        self.assertEqual(read['content'], 'needle whitespace\n')

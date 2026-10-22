"""Review regressions: real private files; command/account/service boundaries substituted."""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import stat
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]


def module(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/name)
    result=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


# Do not import test_preparation: some of its cases read real source pairing data.
prep=module('prepare-bridge.py')


class ReadOnlyStatus(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='bridge-status-')
        self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name);self.home=self.base/'owner'
        self.home.mkdir(mode=0o700)

    def invoke(self, files=None, services=None, home=None, uid=1000):
        output=io.StringIO();actual_file=getattr(prep,'status_file',None)
        def metadata(path,owner,private=False,**kwargs):
            if files is not None:return files.get(str(path),'absent')
            if Path(path).is_relative_to(self.home):return actual_file(path,owner,private,**kwargs)
            return 'absent'  # Never inspect the real installed root records.
        ancestor_ids={(p.stat().st_dev,p.stat().st_ino) for p in self.base.parents}
        actual_fstat=os.fstat
        def trusted_ancestors(fd):
            st=actual_fstat(fd)
            if (st.st_dev,st.st_ino) in ancestor_ids:
                values=list(st);values[0]=stat.S_IFDIR|0o755;values[4]=0
                return os.stat_result(values)
            return st
        with contextlib.ExitStack() as stack:
            for obj,name,value in (
                (prep.sys,'argv',['prepare','status']),
                (prep.os,'getuid',uid),
                (prep.pwd,'getpwuid',SimpleNamespace(pw_dir=str(home or self.home))),
            ):
                stack.enter_context(patch.object(obj,name,return_value=value) if name!='argv' else patch.object(obj,name,value))
            stack.enter_context(patch.object(prep.platform,'system',return_value='Linux'))
            # create=True, lock opens, copying, secrets, installers and network
            # must never be reached, even on an empty or damaged preparation.
            for obj,name in ((prep,'directory'),(prep,'release_files'),(prep,'command'),
                             (prep,'load_script'),(prep,'prepare_copy'),(prep,'prepare_venv'),
                             (prep,'publish'),(prep,'replace_tunnel_credentials'),
                             (prep.os,'mkdir'),(prep.tempfile,'mkstemp'),(prep.fcntl,'flock'),
                             (prep.os,'rename'),(prep.os,'replace'),(prep.os,'unlink'),
                             (prep.os,'chmod'),(prep.os,'chown'),(prep.shutil,'copyfile'),
                             (prep.os,'execv'),(prep.urllib.request,'urlopen'),
                             (prep.getpass,'getpass')):
                stack.enter_context(patch.object(obj,name,side_effect=AssertionError('status reached '+name)))
            stack.enter_context(patch('builtins.input',side_effect=AssertionError('status prompted')))
            stack.enter_context(patch('builtins.open',side_effect=AssertionError('status opened payload')))
            stack.enter_context(patch.object(prep,'status_file',side_effect=metadata,create=True))
            stack.enter_context(patch.object(prep,'status_service',side_effect=lambda unit: (services or {}).get(unit),create=True))
            stack.enter_context(patch.object(prep.os,'fstat',side_effect=trusted_ancestors))
            stack.enter_context(patch.object(prep.subprocess,'run',side_effect=AssertionError('real command forbidden')))
            original_open=os.open
            def opened(path,flags,*args,**kwargs):
                self.assertFalse(flags & (os.O_CREAT|os.O_TRUNC|os.O_WRONLY|os.O_RDWR))
                return original_open(path,flags,*args,**kwargs)
            stack.enter_context(patch.object(prep.os,'open',side_effect=opened))
            with contextlib.redirect_stdout(output):prep.main()
        return output.getvalue()

    def test_empty_and_nonempty_home_status_never_creates_state_or_lock(self):
        for nonempty in (False,True):
            if nonempty:(self.home/'unrelated.txt').write_text('keep')
            result=self.invoke(services={name:{'LoadState':'not-found'} for name in
                ('gpt-agent-bridge-autostart.service','gpt-agent-bridge-tunnel.service')})
            self.assertIn('Not prepared',result)
            self.assertFalse((self.home/'.local').exists())
        self.assertEqual((self.home/'unrelated.txt').read_text(),'keep')

    def test_partial_install_reports_failure_without_recommending_reinstall(self):
        files={str(self.home/'.local/share/gpt-agent-bridge/product/release-manifest.json'):'present'}
        services={'gpt-agent-bridge-autostart.service':{'LoadState':'loaded','ActiveState':'active','SubState':'running','UnitFileState':'enabled','ExecMainStatus':'0'},
                  'gpt-agent-bridge-tunnel.service':{'LoadState':'loaded','ActiveState':'failed','SubState':'failed','UnitFileState':'disabled','ExecMainStatus':'78'}}
        result=self.invoke(files,services)
        self.assertIn('Partial',result);self.assertIn('Bridge: active/running',result)
        self.assertIn('Tunnel: failed/failed',result);self.assertIn('exit 78',result)
        self.assertIn('Keep existing files',result);self.assertIn('Web connection: not checked',result)

    def test_state_without_product_is_partial_not_a_fresh_install(self):
        result=self.invoke({str(self.home/'.local/share/gpt-agent-bridge'):'present'},
            {name:{'LoadState':'not-found'} for name in
             ('gpt-agent-bridge-autostart.service','gpt-agent-bridge-tunnel.service')})
        self.assertIn('Partial',result);self.assertNotIn('Run ./prepare to begin',result)

    def test_running_services_do_not_claim_web_success_or_request_repair(self):
        files={str(p):'present' for p in (
            self.home/'.local/share/gpt-agent-bridge',
            self.home/'.local/share/gpt-agent-bridge/product/release-manifest.json',
            Path('/usr/local/lib/gpt-agent-bridge-autostart/installation.json'),
            Path('/usr/local/lib/gpt-agent-bridge-tunnel-autostart/installation.json'))}
        services={name:{'LoadState':'loaded','ActiveState':'active','SubState':'running',
            'UnitFileState':'enabled','ExecMainStatus':'0','FragmentPath':'/etc/systemd/system/'+name}
            for name in ('gpt-agent-bridge-autostart.service','gpt-agent-bridge-tunnel.service')}
        result=self.invoke(files,services)
        self.assertIn('Web connection: not checked',result)
        self.assertNotIn('Keep existing files',result);self.assertNotIn('initialized_healthy',result)

    def test_unverified_metadata_and_missing_systemctl_are_honest(self):
        path=self.home/'.local/share/gpt-agent-bridge/product/release-manifest.json'
        result=self.invoke({str(path):'unverified'})
        self.assertIn('unverified',result);self.assertIn('Bridge: unknown',result)
        self.assertNotIn('Not prepared',result)

    def test_unsupported_home_and_root_do_not_probe_or_create(self):
        for home,uid in ((Path('relative-home'),1000),(Path('/'),1000),(self.home,0)):
            with self.subTest(home=home,uid=uid):
                self.assertIn('Status unavailable',self.invoke(home=home,uid=uid))

    def test_status_rejects_windows_phase_before_any_observation(self):
        with patch.object(prep.sys,'argv',['prepare','status','--windows-phase','inspect']), \
                patch.object(prep,'preparation_status',side_effect=AssertionError('unexpected observation')), \
                self.assertRaisesRegex(prep.Refusal,'WINDOWS_PHASE_INVALID'):
            prep.main()

    def test_metadata_is_nofollow_and_does_not_read_payload(self):
        path=self.home/'receipt.json';path.write_text('not JSON; metadata only');path.chmod(0o600)
        ancestor_ids={(p.stat().st_dev,p.stat().st_ino) for p in self.base.parents}
        actual_fstat=os.fstat
        def trusted_ancestors(fd):
            st=actual_fstat(fd)
            if (st.st_dev,st.st_ino) in ancestor_ids:
                values=list(st);values[0]=stat.S_IFDIR|0o755;values[4]=0
                return os.stat_result(values)
            return st
        with patch.object(prep.os,'fstat',side_effect=trusted_ancestors), \
                patch('builtins.open',side_effect=AssertionError('payload read forbidden')):
            self.assertEqual(prep.status_file(path,os.getuid(),True),'present')
            self.assertEqual(prep.status_file(path,os.getuid()+1,True),'unverified')
            path.chmod(0o664)
            self.assertEqual(prep.status_file(path,os.getuid(),True),'unverified')
            path.unlink();path.symlink_to(self.home/'outside-sentinel')
            self.assertEqual(prep.status_file(path,os.getuid(),True),'unverified')
            alias=self.base/'alias';alias.symlink_to(self.home,target_is_directory=True)
            self.assertEqual(prep.status_file(alias/'receipt.json',os.getuid(),True),'unverified')
            with patch.object(prep.os,'open',side_effect=PermissionError('DO_NOT_PRINT')):
                self.assertEqual(prep.status_file(path,os.getuid(),True),'unverified')

    def test_systemctl_is_read_only_bounded_and_discards_unknown_output(self):
        reply=SimpleNamespace(returncode=0,stdout='LoadState=loaded\nActiveState=failed\nSubState=failed\nUnitFileState=disabled\nExecMainStatus=78\nFragmentPath=/etc/systemd/system/gpt-agent-bridge-tunnel.service\nDropInPaths=\nNeedDaemonReload=no\n')
        with patch.object(prep.subprocess,'run',return_value=reply) as run:
            result=prep.status_service('gpt-agent-bridge-tunnel.service')
        self.assertEqual(result['ExecMainStatus'],'78')
        argv=run.call_args.args[0];kwargs=run.call_args.kwargs
        self.assertEqual(argv[:2],['/usr/bin/systemctl','show'])
        self.assertNotIn('ExecStart',repr(argv));self.assertNotIn('Environment',repr(argv))
        self.assertLessEqual(kwargs['timeout'],5);self.assertEqual(kwargs['stdin'],subprocess.DEVNULL)
        for failure in (FileNotFoundError(),subprocess.TimeoutExpired('fixture',3)):
            with patch.object(prep.subprocess,'run',side_effect=failure):
                self.assertIsNone(prep.status_service('gpt-agent-bridge-tunnel.service'))
        for text in ('Environment=DO_NOT_PRINT\n','ActiveState=DO_NOT_PRINT\n','x'*9000):
            reply.stdout=text
            with patch.object(prep.subprocess,'run',return_value=reply):
                self.assertIsNone(prep.status_service('gpt-agent-bridge-tunnel.service'))

    def test_shell_status_without_python_or_git_never_bootstraps(self):
        binaries=self.base/'bin';binaries.mkdir()
        source=(ROOT/'prepare').read_text()
        self.assertIn('exec /usr/bin/python3 -B',source)
        # Substitute only the absolute interpreter boundary; no host interpreter,
        # package manager or source helper is executed by this shell fixture.
        entry=self.base/'prepare';entry.write_text(source.replace('/usr/bin/python3',str(binaries/'python3')))
        # Only this audited shell and synthetic commands may execute.
        for python in (False,True):
            if python:
                executable=binaries/'python3';executable.write_text('#!/bin/sh\nprintf "fixture python: %s\\n" "$*"\n');executable.chmod(0o700)
                dirname=binaries/'dirname';dirname.write_text('#!/bin/sh\nprintf "%s\\n" "${2%/*}"\n');dirname.chmod(0o700)
            result=subprocess.run(['/bin/sh',str(entry),'status'],env={'PATH':str(binaries)},stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=3)
            self.assertNotIn('sudo',result.stdout+result.stderr)
            self.assertNotIn('Install Python',result.stdout+result.stderr)
            if python:
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                self.assertIn('fixture python: -B ',result.stdout);self.assertTrue(result.stdout.rstrip().endswith('status'))
            else:self.assertIn('Status unavailable',result.stdout)


@contextlib.contextmanager
def fixture_umask(value):
    previous=os.umask(value)
    try:
        yield
    finally:
        os.umask(previous)


class FirstInstallRepairs(unittest.TestCase):
    """Only temporary fixture data; every external command and prompt is stubbed."""
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='bridge-first-install-')
        self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name)
        self.state=self.base/'state';self.state.mkdir(mode=0o700)
        base=self.base
        class FixturePath(type(Path())):
            def stat(path, *, follow_symlinks=True):
                # Simulate trusted ancestors, independently of the host /tmp mode.
                if path in base.parents:
                    return os.stat_result((stat.S_IFDIR|0o700,0,0,1,os.getuid(),os.getgid(),0,0,0,0))
                if not path.is_relative_to(base):
                    raise AssertionError('filesystem access outside fixture: '+str(path))
                return super().stat(follow_symlinks=follow_symlinks)
        for item in (
            patch.object(prep,'Path',FixturePath),
            patch.object(prep.subprocess,'run',side_effect=AssertionError('external command forbidden')),
            patch.object(prep.urllib.request,'urlopen',side_effect=AssertionError('network forbidden')),
            patch.object(prep,'load_script',side_effect=AssertionError('installer import forbidden')),
            patch('builtins.input',side_effect=AssertionError('prompt forbidden')),
            patch.object(prep.getpass,'getpass',side_effect=AssertionError('secret prompt forbidden')),
            patch.object(prep.os,'execv',side_effect=AssertionError('exec forbidden')),
        ):
            item.start();self.addCleanup(item.stop)

    def release(self):
        source=self.base/'shared-workspace'/'release'
        source.mkdir(parents=True,mode=0o775)
        payload={name:b'fixture only\n' for name in (
            'prepare','scripts/prepare-system.py','scripts/release-assets.json',
            'browser-extension/extension/projects.js','templates/WEB-PRINCIPAL-CORE.md',
            'requirements.txt','Bridge-Skills.zip')}
        payload['requirements.txt']=b''
        parents={source,source.parent}
        for name,data in payload.items():
            path=source/name;path.parent.mkdir(parents=True,exist_ok=True)
            parents.update(p for p in path.parents if p==source or p.is_relative_to(source))
            path.write_bytes(data);path.chmod(0o664)
        for parent in parents:parent.chmod(0o775)
        manifest={'version':1,'files':{n:hashlib.sha256(d).hexdigest() for n,d in payload.items()},'executables':['prepare']}
        (source/'release-manifest.json').write_text(json.dumps(manifest))
        return source,manifest

    def fake_child(self,args,**kwargs):
        args=[str(a) for a in args]
        with fixture_umask(kwargs.get('umask',-1) if kwargs.get('umask',-1)>=0 else 0o002):
            if args[0]=='git':
                product=Path(args[-1] if args[1]=='init' else args[2])
                if args[1]=='init':(product/'.git').mkdir()
                return SimpleNamespace(returncode=0,stdout=str(product)+'\n')
            if args[1:3]==['-m','venv']:
                venv=Path(args[-1]);(venv/'bin').mkdir(parents=True)
                (venv/'bin/python').write_text('not an executable fixture')
                (venv/'bin/python').chmod(0o700)
                (venv/'pyvenv.cfg').write_text('synthetic')
                return SimpleNamespace(returncode=0,stdout='')
            if args[1:3]==['-m','pip']:
                package=Path(args[-1])/'.venv/lib/fixture-package'
                package.mkdir(parents=True);(package/'module.py').write_text('fixture = True\n')
                return SimpleNamespace(returncode=0,stdout='')
            if '-c' in args:return SimpleNamespace(returncode=1,stdout='')
            raise AssertionError('unexpected command: '+repr(args))

    def test_group_writable_release_copies_into_private_product(self):
        source,manifest=self.release();product=self.state/'product'
        with fixture_umask(0o002),patch.object(prep.subprocess,'run',side_effect=self.fake_child):
            prep.prepare_copy(source,product)
        self.assertEqual(source.parent.stat().st_mode&0o777,0o775)
        for name in manifest['files']:
            self.assertEqual((product/name).read_bytes(),(source/name).read_bytes())
            self.assertEqual((product/name).stat().st_mode&0o777,0o700 if name=='prepare' else 0o600)
            for parent in (product/name).parents:
                if parent==product or parent.is_relative_to(product):
                    self.assertEqual(parent.stat().st_mode&0o777,0o700)
        self.assertEqual((product/'.git').stat().st_mode&0o777,0o700)

    def test_skills_zip_is_required_and_rehashed_without_private_attachment_copy(self):
        source,manifest=self.release()
        self.assertIn('Bridge-Skills.zip',manifest['files'])
        self.assertEqual(prep.release_files(source),manifest)
        archive=source/'Bridge-Skills.zip'
        original=archive.read_bytes()
        archive.write_bytes(b'changed archive')
        with self.assertRaisesRegex(prep.Refusal,'RELEASE_DIGEST_MISMATCH'):
            prep.release_files(source)
        archive.write_bytes(original)
        del manifest['files']['Bridge-Skills.zip']
        (source/'release-manifest.json').write_text(json.dumps(manifest))
        with self.assertRaisesRegex(prep.Refusal,'INCOMPLETE_RELEASE'):
            prep.release_files(source)

    def test_partial_copy_repeats_exactly_but_preserves_changed_product(self):
        # Retain the old distribution test's copy contract without building or
        # importing any real checkout extension or running Git/venv/services.
        source,_=self.release();product=self.state/'product'
        product.mkdir(mode=0o700)
        prep.publish(product/'prepare',(source/'prepare').read_bytes(),mode=0o700)
        with patch.object(prep.subprocess,'run',side_effect=self.fake_child):
            prep.prepare_copy(source,product)
            before=prep.release_files(product)
            prep.prepare_copy(source,product)
            self.assertEqual(prep.release_files(product),before)
            changed=product/'scripts/prepare-system.py';changed.write_bytes(b'user edit')
            with self.assertRaisesRegex(prep.Refusal,'EXISTING_FILE_NO_OVERWRITE'):
                prep.prepare_copy(source,product)
            self.assertEqual(changed.read_bytes(),b'user edit')
        (source/'Bridge-Skills.zip').unlink()
        with self.assertRaises(FileNotFoundError):
            prep.prepare_copy(source,self.state/'never-created')
        self.assertFalse((self.state/'never-created').exists())

    def test_copy_rechecks_the_bytes_after_release_validation(self):
        source,_=self.release();product=self.state/'product'
        original=prep.release_files
        def changed(path):
            result=original(path);(source/'prepare').write_bytes(b'changed after validation')
            return result
        with patch.object(prep,'release_files',side_effect=changed):
            with self.assertRaisesRegex(prep.Refusal,'RELEASE_DIGEST_MISMATCH'):
                prep.prepare_copy(source,product)
        self.assertFalse((product/'prepare').exists())

    def test_readable_release_still_refuses_symlink_ancestry(self):
        source,_=self.release();linked=self.base/'linked-release';linked.symlink_to(source,target_is_directory=True)
        with self.assertRaisesRegex(prep.Refusal,'symlinks are unsupported'):
            prep.release_files(linked)

    def assert_release_parent_swap_blocked(self,name):
        source,_=self.release();target=source/name
        outside=self.base/'outside-release';outside.mkdir(mode=0o700)
        sentinel=outside/target.name;sentinel.write_bytes(b'outside-release sentinel')
        sentinel_id=(sentinel.stat().st_dev,sentinel.stat().st_ino)
        original_directory=prep.directory;original_open=os.open
        swapped=False;outside_opened=False;opened_fds=[]
        def checked(path,*args,**kwargs):
            nonlocal swapped
            result=original_directory(path,*args,**kwargs)
            if Path(path)==target.parent and kwargs.get('release_input') and not swapped:
                target.parent.rename(target.parent.with_name(target.parent.name+'-checked'))
                target.parent.symlink_to(outside,target_is_directory=True)
                swapped=True
            return result
        def opened(path,flags,*args,**kwargs):
            nonlocal outside_opened
            fd=original_open(path,flags,*args,**kwargs)
            opened_fds.append(fd)
            st=os.fstat(fd)
            if (st.st_dev,st.st_ino)==sentinel_id:outside_opened=True
            return fd
        failure=None
        with patch.object(prep,'directory',side_effect=checked),patch.object(prep.os,'open',side_effect=opened):
            try:prep.release_files(source)
            except (OSError,ValueError,prep.Refusal) as error:failure=error
        self.assertTrue(swapped,'fixture did not replace the checked parent')
        self.assertFalse(outside_opened,'opened the outside-release sentinel after the parent swap')
        self.assertIsInstance(failure,OSError)
        for fd in set(opened_fds):
            with self.assertRaises(OSError):os.fstat(fd)

    def test_manifest_parent_swapped_after_check_never_opens_outside_file(self):
        self.assert_release_parent_swap_blocked('release-manifest.json')

    def test_payload_parent_swapped_after_check_never_opens_outside_file(self):
        self.assert_release_parent_swap_blocked('scripts/prepare-system.py')

    def test_release_read_closes_opened_fds_on_success_and_leaf_failure(self):
        source,_=self.release();target=source/'scripts/prepare-system.py'
        original_open=os.open;opened=[]
        def tracked(*args,**kwargs):
            fd=original_open(*args,**kwargs);opened.append(fd);return fd
        with patch.object(prep.os,'open',side_effect=tracked):
            self.assertEqual(prep.read(target,False,release_input=True),b'fixture only\n')
            with self.assertRaises(FileNotFoundError):
                prep.read(target.with_name('missing.py'),False,release_input=True)
        for fd in set(opened):
            with self.assertRaises(OSError):os.fstat(fd)

    def test_payload_symlink_leaf_is_not_followed(self):
        source,_=self.release();target=source/'scripts/prepare-system.py'
        outside=self.base/'outside-payload';outside.write_bytes(b'outside-release sentinel')
        target.unlink();target.symlink_to(outside)
        with self.assertRaises(OSError):prep.release_files(source)

    def test_private_execution_parent_refusal_names_exact_path_without_chmod(self):
        parent=self.base/'shared';parent.mkdir(mode=0o775);parent.chmod(0o775)
        with self.assertRaises(prep.Refusal) as caught:
            prep.directory(parent/'product',private=True)
        output=io.StringIO()
        with contextlib.redirect_stderr(output):prep.report_failure(caught.exception)
        self.assertIn(str(parent),output.getvalue())
        self.assertIn('group/other-writable',output.getvalue())
        self.assertIn('this directory only',output.getvalue())
        self.assertNotIn('Re-enter',output.getvalue())
        self.assertEqual(parent.stat().st_mode&0o777,0o775)
        self.assertFalse((parent/'product').exists())

    def test_venv_creation_under_umask_002_is_private_and_parent_mask_unchanged(self):
        product=self.state/'product';product.mkdir(mode=0o700)
        with fixture_umask(0o002),patch.object(prep.subprocess,'run',side_effect=self.fake_child) as run:
            prep.prepare_venv(product)
            self.assertEqual(os.umask(0o002),0o002)
        for path in (product/'.venv',product/'.venv/bin'):
            self.assertEqual(path.stat().st_mode&0o777,0o700)
        self.assertEqual((product/'.venv/pyvenv.cfg').stat().st_mode&0o777,0o600)
        self.assertEqual(run.call_args.kwargs.get('umask'),0o077)

    def test_existing_group_writable_venv_is_reported_without_chmod_or_recreation(self):
        product=self.state/'product';product.mkdir(mode=0o700)
        venv=product/'.venv';venv.mkdir(mode=0o775);venv.chmod(0o775)
        prep.publish(product/'venv-owner.json',prep.json_bytes(
            {'path':str(venv),'owner':os.getuid(),'purpose':'bridge-preparation-venv-v1'}))
        with self.assertRaises(prep.Refusal) as caught:prep.prepare_venv(product)
        self.assertIn(str(venv),str(caught.exception))
        self.assertIn('group/other-writable',str(caught.exception))
        self.assertEqual(venv.stat().st_mode&0o777,0o775)

    def historical_venv(self,mode):
        product=self.state/'product';product.mkdir(mode=0o700)
        venv=product/'.venv';(venv/'bin').mkdir(parents=True,mode=0o700)
        venv.chmod(mode)
        (venv/'bin/python').write_bytes(b'historical interpreter fixture')
        (venv/'pyvenv.cfg').write_text('historical fixture')
        return product,venv

    def test_unmarked_group_writable_venv_is_refused_without_changes(self):
        product,venv=self.historical_venv(0o775)
        with self.assertRaises(prep.Refusal) as caught:prep.prepare_venv(product)
        self.assertIn(str(venv),str(caught.exception))
        self.assertIn('group/other-writable',str(caught.exception))
        self.assertEqual(venv.stat().st_mode&0o777,0o775)
        self.assertEqual((venv/'bin/python').read_bytes(),b'historical interpreter fixture')
        self.assertFalse((product/'venv-owner.json').exists())

    def test_safe_unmarked_historical_venv_is_reused_without_rebuild(self):
        product,venv=self.historical_venv(0o755)
        self.assertEqual(prep.prepare_venv(product),venv/'bin/python')
        self.assertEqual(venv.stat().st_mode&0o777,0o755)
        self.assertEqual((venv/'bin/python').read_bytes(),b'historical interpreter fixture')
        self.assertFalse((product/'venv-owner.json').exists())

    def test_private_child_failure_does_not_change_parent_umask(self):
        with fixture_umask(0o002):
            with self.assertRaisesRegex(AssertionError,'external command forbidden'):
                prep.command(['synthetic-venv'],private=True)
            self.assertEqual(os.umask(0o002),0o002)

    def test_builder_restores_umask_on_success_and_failure(self):
        builder=module('build-distribution.py')
        def create(source,destination):
            (destination/'nested/child').mkdir(parents=True)
            if destination.name=='interrupted':raise RuntimeError('synthetic interruption')
            return {'synthetic':'only'}
        with fixture_umask(0o002),patch.object(builder,'build_private',side_effect=create):
            self.assertEqual(builder.build(self.base,self.state/'built'),{'synthetic':'only'})
            self.assertEqual(os.umask(0o002),0o002)
            with self.assertRaisesRegex(RuntimeError,'synthetic interruption'):
                builder.build(self.base,self.state/'interrupted')
            self.assertEqual(os.umask(0o002),0o002)
        for destination in ('built','interrupted'):
            self.assertEqual((self.state/destination/'nested').stat().st_mode&0o777,0o700)
            self.assertEqual((self.state/destination/'nested/child').stat().st_mode&0o777,0o700)

    def test_pip_and_reentry_are_private_without_installers_or_services(self):
        source,_=self.release();product=self.state/'product';home=self.base/'home'
        class StopBeforeServices(Exception):pass
        with fixture_umask(0o002),patch.object(prep,'SOURCE',source), \
                patch('builtins.input',return_value='yes'), \
                patch.object(prep.subprocess,'run',side_effect=self.fake_child) as run, \
                patch.object(prep.os,'execv',side_effect=StopBeforeServices) as reentry:
            with self.assertRaises(StopBeforeServices):
                prep.run_locked(SimpleNamespace(action='prepare',existing_extension=None),home,self.state)
            self.assertEqual(os.umask(0o002),0o002)
        pip=next(c for c in run.call_args_list if c.args[0][1:3]==['-m','pip'])
        self.assertEqual(pip.kwargs['umask'],0o077)
        self.assertIn('-B',reentry.call_args.args[1])
        probe=next(c for c in run.call_args_list if '-c' in c.args[0])
        self.assertIn('-B',probe.args[0])
        package=product/'.venv/lib/fixture-package'
        self.assertEqual(package.stat().st_mode&0o777,0o700)
        self.assertEqual((package/'module.py').stat().st_mode&0o777,0o600)

    def test_reentry_explains_continuation_without_repeating_trust_banner(self):
        product=self.state/'product';product.mkdir(mode=0o700)
        (product/'release-manifest.json').write_text('{}');(product/'requirements.txt').write_text('')
        python=product/'.venv/bin/python';output=io.StringIO()
        with patch.object(prep,'SOURCE',product),patch.object(prep.sys,'executable',str(python)), \
                patch.object(prep,'prepare_copy'),patch.object(prep,'prepare_venv',return_value=python), \
                contextlib.redirect_stdout(output):
            with self.assertRaisesRegex(AssertionError,'external command forbidden'):
                prep.run_locked(SimpleNamespace(action='prepare'),self.base/'home',self.state)
        self.assertIn('Continuing preparation in the private Python environment.',output.getvalue())
        self.assertNotIn('Bridge will create',output.getvalue())

    def test_known_installer_diagnostics_keep_only_safe_code_and_stage(self):
        system=module('prepare-system.py')
        error=RuntimeError('synthetic secret must not appear')
        error.code='installation_not_completed';error.stage='preflight'
        output=io.StringIO()
        with contextlib.redirect_stdout(output):system.report_failure(error)
        self.assertIn('installation_not_completed (stage: preflight)',output.getvalue())
        self.assertNotIn('synthetic secret',output.getvalue())
        self.assertNotIn('installer status',output.getvalue())
        error.code='client_version';error.stage='synthetic secret'
        output=io.StringIO()
        with contextlib.redirect_stderr(output):prep.report_failure(error)
        self.assertIn('client_version',output.getvalue())
        self.assertNotIn('synthetic secret',output.getvalue())

    def test_unknown_errors_and_unknown_codes_never_print_raw_values(self):
        system=module('prepare-system.py')
        for error in (ValueError('synthetic secret'),RuntimeError('synthetic secret')):
            error.code='synthetic_secret_code';error.stage='synthetic_secret_stage'
            for report,redirect in ((system.report_failure,contextlib.redirect_stdout),
                                    (prep.report_failure,contextlib.redirect_stderr)):
                output=io.StringIO()
                with redirect(output):report(error)
                self.assertNotIn('synthetic',output.getvalue())
                self.assertIn('retained',output.getvalue())
        output=io.StringIO()
        with contextlib.redirect_stdout(output):system.report_failure(ValueError('START_OUTCOME_UNKNOWN_INSPECT'))
        self.assertIn('Starting the service could not be confirmed',output.getvalue())


class OptionalReminders(unittest.TestCase):
    """Public entry contracts with private data and every external boundary faked."""
    release=FirstInstallRepairs.release

    def setUp(self):
        FirstInstallRepairs.setUp(self)
        self.home=self.base/'home';self.home.mkdir(mode=0o700)
        self.state=self.home/'.local/share/gpt-agent-bridge'
        self.state.mkdir(parents=True,mode=0o700)
        self.product=self.state/'product';self.product.mkdir(mode=0o700)
        self.python=self.product/'.venv/bin/python'
        self.config=self.home/'.config/gpt-agent-bridge/browser-notifications.json'
        source,manifest=self.release()
        for name in manifest['files']:
            path=self.product/name;path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            path.write_bytes((source/name).read_bytes());path.chmod(0o600)
        (self.product/'release-manifest.json').write_text(json.dumps(manifest))
        self.python.parent.mkdir(parents=True,mode=0o700)
        self.python.write_bytes(b'never execute fixture interpreter');self.python.chmod(0o700)
        (self.product/'.venv/pyvenv.cfg').write_text('synthetic')
        account=SimpleNamespace(pw_name='fixture',pw_dir=str(self.home))
        self.identity={'user':'fixture','uid':os.getuid(),'gid':os.getgid(),'home':str(self.home)}
        self.bridge_plan={**self.identity,'repo':str(self.product),'workspace':str(self.product),'port':8765,'entrypoint':'module'}
        self.tunnel_plan=dict(self.identity)
        self.bridge=SimpleNamespace(installation_record=lambda:{'plan':self.bridge_plan})
        self.tunnel=SimpleNamespace(record=lambda:{'plan':self.tunnel_plan},configured_owner=lambda plan:None)
        self.calls=[]
        def script(name,source):
            self.assertEqual(source,self.product)
            self.calls.append(name)
            if name=='install-bridge-autostart.py':return self.bridge
            if name=='install-bridge-tunnel-autostart.py':return self.tunnel
            raise AssertionError('unexpected installer import: '+name)
        for item in (
            patch.object(prep,'SOURCE',self.product),
            patch.object(prep.sys,'executable',str(self.python)),
            patch.object(prep.pwd,'getpwuid',return_value=account),
            patch.object(prep.platform,'release',return_value='Linux'),
            patch.object(prep,'load_script',side_effect=script),
            patch.object(prep,'environment_ready',return_value=True),
            patch.object(prep,'prepare_copy',side_effect=AssertionError('reminders cannot copy core')),
            patch.object(prep,'prepare_venv',side_effect=AssertionError('reminders cannot create venv')),
            patch.object(prep,'download',side_effect=AssertionError('reminders cannot download')),
            patch.object(prep,'select_herdr',side_effect=AssertionError('reminders cannot select Herdr')),
            patch.object(prep,'command',side_effect=AssertionError('external command forbidden')),
            patch.object(prep,'prepare_plugin',side_effect=AssertionError('beginner flow cannot request an App ID')),
        ):
            item.start();self.addCleanup(item.stop)

    def args(self,action='reminders'):
        return SimpleNamespace(action=action,existing_extension=None,windows_phase=None,
                               windows_target_base64=None,windows_proof=None)

    def run_action(self,args):
        output=io.StringIO()
        with contextlib.redirect_stdout(output):prep.run_locked(args,self.home,self.state)
        return output.getvalue()

    def template(self):
        path=self.product/'browser-extension/extension'
        (path/'manifest.json').write_text(json.dumps({'key':'Zml4dHVyZQ==','manifest_version':3}))
        (path/'worker.js').write_bytes(b'fixture worker only')

    def notification_reader(self,path):
        if not path.exists():return None
        return json.loads(prep.read(path))

    def pair(self,existing=None):
        self.template()
        with patch.object(prep,'notification_config',side_effect=self.notification_reader), \
                patch('builtins.input',return_value='yes'),patch.dict(os.environ,{},clear=True):
            args=self.args();args.existing_extension=existing
            return self.run_action(args)

    def reserve(self):
        args=self.args();args.windows_phase='reserve'
        import base64
        args.windows_target_base64=base64.b64encode('C:\\Users\\Fixture\\Reminders'.encode()).decode()
        return json.loads(self.run_action(args))

    def wsl(self):
        return patch.dict(os.environ,{'WSL_DISTRO_NAME':'Fixture Distro','BRIDGE_WSL_DISTRO':'Fixture Distro'},clear=True)

    def test_reminders_reject_missing_or_changed_core_before_pairing(self):
        for fail in ('missing product','changed payload','wrong owner','wrong repo','missing tunnel','foreign tunnel','missing venv config','unsafe venv','bad environment'):
            with self.subTest(fail=fail),contextlib.ExitStack() as stack:
                if fail=='missing product':
                    stack.enter_context(patch.object(prep,'directory',side_effect=FileNotFoundError('fixture')))
                elif fail=='changed payload':
                    stack.enter_context(patch.object(prep,'release_files',side_effect=prep.Refusal('RELEASE_DIGEST_MISMATCH')))
                elif fail=='wrong owner':
                    stack.enter_context(patch.dict(self.bridge_plan,uid=-1))
                elif fail=='wrong repo':
                    stack.enter_context(patch.dict(self.bridge_plan,repo='/fixture/foreign'))
                elif fail=='missing tunnel':
                    stack.enter_context(patch.object(self.tunnel,'record',side_effect=FileNotFoundError('fixture')))
                elif fail=='foreign tunnel':
                    stack.enter_context(patch.dict(self.tunnel_plan,uid=-1))
                elif fail=='missing venv config':
                    cfg=self.product/'.venv/pyvenv.cfg';cfg.rename(cfg.with_suffix('.held'))
                    stack.callback(lambda:cfg.with_suffix('.held').rename(cfg))
                elif fail=='unsafe venv':
                    venv=self.product/'.venv';venv.chmod(0o775)
                    stack.callback(lambda:venv.chmod(0o700))
                else:stack.enter_context(patch.object(prep,'environment_ready',return_value=False))
                control=stack.enter_context(patch.object(prep,'windows_control',side_effect=AssertionError('metadata before core')))
                extension=stack.enter_context(patch.object(prep,'prepare_extension',side_effect=AssertionError('pairing before core')))
                for phase in (None,'inspect','reserve','stage','confirm','continue'):
                    args=self.args();args.windows_phase=phase
                    with self.assertRaisesRegex(prep.Refusal,'REMINDERS_CORE_NOT_READY'):
                        self.run_action(args)
                control.assert_not_called();extension.assert_not_called()
        self.assertFalse(self.config.exists());self.assertFalse((self.state/'windows-extension.json').exists())

    def test_valid_core_observation_uses_records_and_no_service_commands(self):
        self.assertEqual(prep.reminder_runtime(self.product,self.home),self.python)
        self.assertEqual(self.calls,['install-bridge-autostart.py','install-bridge-tunnel-autostart.py'])

    def test_core_without_state_does_not_create_reminder_directories(self):
        import shutil
        shutil.rmtree(self.state)
        with patch.object(prep.os,'getuid',return_value=1000), \
                patch.object(prep.sys,'argv',['prepare','reminders']), \
                self.assertRaisesRegex(prep.Refusal,'REMINDERS_CORE_NOT_READY'):
            prep.main()
        self.assertFalse(self.state.exists())

    def test_default_core_ignores_missing_bad_and_unconfirmed_reminders(self):
        async def probe(_):return {'bridge_mcp':'initialized_healthy'}
        self.bridge.load_config=lambda:{};self.bridge.probe=probe
        self.tunnel.CREDENTIALS=self.state/'synthetic-tunnel-credentials'
        self.tunnel.CREDENTIALS.write_text('{}')
        self.tunnel.read_file=lambda *a:b'{}';self.tunnel.validate_credentials=lambda value:value
        self.tunnel.configure=lambda:(_ for _ in ()).throw(AssertionError('no credential prompt'))
        (self.product/'scripts/release-assets.json').write_text(json.dumps({'fixture':{'tunnel':{}}}))
        prep.remember_source_kind(self.state,'full')
        for kind in ('fresh','unconfirmed','malformed'):
            with self.subTest(kind=kind),contextlib.ExitStack() as stack:
                if kind!='fresh':
                    (self.state/'windows-extension.json').write_text('{"confirmed":false}' if kind=='unconfirmed' else 'bad receipt')
                    (self.state/'extension.json').write_text('unreadable as receipt')
                    self.config.parent.mkdir(parents=True,exist_ok=True,mode=0o700);self.config.write_bytes(b'bad pairing')
                before={p:p.read_bytes() for p in (self.state/'windows-extension.json',self.state/'extension.json',self.config) if p.exists()}
                for name in ('windows_record','windows_control','notification_config','prepare_extension','extension_handoff'):
                    stack.enter_context(patch.object(prep,name,side_effect=AssertionError('core touched optional reminders: '+name)))
                stack.enter_context(patch.object(prep,'prepare_copy'))
                stack.enter_context(patch.object(prep,'prepare_venv',return_value=self.python))
                stack.enter_context(patch.object(prep,'select_herdr',return_value=self.base/'herdr'))
                stack.enter_context(patch.object(prep.platform,'machine',return_value='fixture'))
                stack.enter_context(patch.object(prep,'download',return_value=self.state/'bundle'))
                actions=[]
                stack.enter_context(patch.object(prep,'command',side_effect=lambda argv,**kw:actions.append(str(argv[3])) or ''))
                def probe_result(coroutine):
                    # The fake probe completes without IO; don't create even an
                    # asyncio self-pipe/socket while checking core routing.
                    try:coroutine.send(None)
                    except StopIteration as done:return done.value
                    finally:coroutine.close()
                    raise AssertionError('fixture probe unexpectedly awaited IO')
                stack.enter_context(patch.object(prep.asyncio,'run',side_effect=probe_result))
                stack.enter_context(patch.object(prep,'publish',side_effect=AssertionError('handoff must not copy attachments')))
                output=self.run_action(self.args('prepare'))
                self.assertIn('return to the FULL package folder you extracted, select Bridge-Skills.zip at its root, then in ordinary ChatGPT Web use @Plugin Creator',output)
                self.assertNotIn('Creator-attachments',output)
                self.assertNotIn('Keep this terminal open',output)
                self.assertNotIn('real UI acceptance',output)
                self.assertNotIn('if unsupported',output)
                self.assertFalse((self.state/'Creator-attachments').exists())
                self.assertEqual(actions,['bridge','tunnel-install','tunnel-start'])
                self.assertIn('Chrome completion reminders are optional',output)
                self.assertIn('does not confirm the remote Web plugin',output)
                self.assertNotIn('own-App ID',output)
                self.assertNotIn('personal-plugin',output)
                for path,data in before.items():self.assertEqual(path.read_bytes(),data)
                if kind=='fresh':
                    self.assertFalse(self.config.exists());self.assertFalse((self.state/'extension').exists())

    def test_checkout_source_handoff_requests_full_package(self):
        async def probe(_):return {'bridge_mcp':'initialized_healthy'}
        self.bridge.load_config=lambda:{}
        self.bridge.probe=probe
        self.tunnel.CREDENTIALS=self.state/'synthetic-tunnel-credentials'
        self.tunnel.CREDENTIALS.write_text('{}')
        self.tunnel.read_file=lambda *a:b'{}'
        self.tunnel.validate_credentials=lambda value:value
        self.tunnel.configure=lambda:(_ for _ in ()).throw(AssertionError('no credential prompt'))
        (self.product/'scripts/release-assets.json').write_text(json.dumps({'fixture':{'tunnel':{}}}))
        checkout=self.base/'checkout';checkout.mkdir(mode=0o700)
        revision='a'*40
        (self.state/('release-'+revision)).mkdir(mode=0o700)
        actions=[]
        def command(argv,**kwargs):
            args=[str(item) for item in argv]
            if args[:2]==['git','-C']:
                if '--show-toplevel' in args:return str(checkout)
                if '--porcelain' in args:return ''
                if 'rev-parse' in args:return revision
            if args and args[0]=='sudo':actions.append(args[3])
            return ''
        def probe_result(coroutine):
            try:coroutine.send(None)
            except StopIteration as done:return done.value
            finally:coroutine.close()
            raise AssertionError('fixture probe unexpectedly awaited IO')
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(prep,'SOURCE',checkout))
            stack.enter_context(patch('builtins.input',return_value='yes'))
            stack.enter_context(patch.object(prep,'prepare_copy'))
            stack.enter_context(patch.object(prep,'release_files'))
            stack.enter_context(patch.object(prep,'prepare_venv',return_value=self.python))
            stack.enter_context(patch.object(prep,'reenter'))
            stack.enter_context(patch.object(prep,'select_herdr',return_value=self.base/'herdr'))
            stack.enter_context(patch.object(prep,'download',return_value=self.state/'bundle'))
            stack.enter_context(patch.object(prep.platform,'machine',return_value='fixture'))
            stack.enter_context(patch.object(prep,'command',side_effect=command))
            stack.enter_context(patch.object(prep.asyncio,'run',side_effect=probe_result))
            output=self.run_action(self.args('prepare'))
        self.assertEqual((self.state/'source-kind').read_bytes(),b'checkout\n')
        self.assertIn('this source checkout has no Bridge-Skills.zip',output)
        self.assertIn('Obtain the FULL installation package',output)
        self.assertNotIn('return to the FULL package folder you extracted',output)
        self.assertNotIn('Creator-attachments',output)
        self.assertEqual(actions,['bridge','tunnel-install','tunnel-start'])

    def test_fresh_linux_reminders_only_prepare_extension_and_reuse_identity(self):
        self.pair()
        paths=(self.config,self.state/'notification-pending.json',self.state/'extension.json',self.state/'extension/connection.js')
        before={p:p.read_bytes() for p in paths}
        self.pair()
        for path,data in before.items():self.assertEqual(path.read_bytes(),data)
        self.assertNotIn('prepare-system.py',self.calls)

    def test_existing_linux_loading_path_and_key_are_preserved(self):
        self.template()
        old=self.state/'old-loading-path';old.mkdir(mode=0o700)
        (old/'manifest.json').write_text('{"manifest_version":3}')
        (old/'manifest.json').chmod(0o600)
        config={'version':3,'discovery':'registered','port':8765,'token':'fixture-token','extension_id':'a'*32}
        prep.publish(self.config,prep.json_bytes(config))
        self.pair(old)
        record=json.loads((self.state/'extension.json').read_text())
        self.assertEqual(record['path'],str(old));self.assertEqual(record['extension_id'],'a'*32)
        self.assertNotIn('key',json.loads((old/'manifest.json').read_text()))
        self.assertEqual(json.loads(self.config.read_text())['token'],'fixture-token')

    def test_missing_authority_or_changed_identity_is_refused_on_rerun(self):
        self.pair();before=(self.state/'extension/connection.js').read_bytes()
        self.config.unlink();(self.state/'notification-pending.json').unlink()
        with self.assertRaisesRegex(prep.Refusal,'EXISTING_EXTENSION_WITHOUT_CONFIG_INSPECT'):self.pair()
        config={'version':3,'discovery':'registered','port':8765,'token':'changed','extension_id':'b'*32}
        prep.publish(self.config,prep.json_bytes(config))
        with self.assertRaisesRegex(prep.Refusal,'EXTENSION_ID_MISMATCH'):self.pair()
        self.assertEqual((self.state/'extension/connection.js').read_bytes(),before)

    def test_conflicting_pending_pairing_is_not_overwritten(self):
        self.pair();previous=(self.state/'notification-pending.json').read_bytes()
        pending=json.loads(previous);pending['token']='unknown other authority'
        prep.publish(self.state/'notification-pending.json',prep.json_bytes(pending),previous=previous)
        with self.assertRaisesRegex(prep.Refusal,'PAIRING_AUTHORITY_INCONSISTENT'):self.pair()

    def test_single_changed_token_and_unknown_loading_path_are_not_repaired(self):
        self.pair();connection=(self.state/'extension/connection.js').read_bytes()
        (self.state/'notification-pending.json').unlink()
        previous=self.config.read_bytes();config=json.loads(previous);config['token']='changed token'
        prep.publish(self.config,prep.json_bytes(config),previous=previous)
        with self.assertRaisesRegex(prep.Refusal,'PAIRING_AUTHORITY_INCONSISTENT'):self.pair()
        self.assertEqual((self.state/'extension/connection.js').read_bytes(),connection)
        (self.state/'extension.json').unlink()
        with self.assertRaisesRegex(prep.Refusal,'EXISTING_EXTENSION_PATH_REQUIRED_NO_NEW_ID'):self.pair()

    def test_pending_first_generation_reuses_known_identity_but_rejects_unknown_id(self):
        self.template()
        config={'version':3,'discovery':'registered','port':8765,'token':'synthetic-token',
                'extension_id':prep.extension_id(json.loads((self.product/'browser-extension/extension/manifest.json').read_text()))}
        pending=self.state/'notification-pending.json';prep.publish(pending,prep.json_bytes(config))
        self.pair();self.assertEqual(json.loads(self.config.read_text()),config)
        # A pending first generation cannot silently adopt another release key.
        self.config.unlink();(self.state/'extension.json').unlink()
        import shutil
        shutil.rmtree(self.state/'extension')
        previous=pending.read_bytes();config['extension_id']='b'*32
        prep.publish(pending,prep.json_bytes(config),previous=previous)
        with self.assertRaisesRegex(prep.Refusal,'EXTENSION_ID_MISMATCH'):self.pair()

    def test_linux_entry_reminders_skips_dependency_bootstrap(self):
        entry=(ROOT/'prepare').read_text()
        branch=entry.split('if [ "${1:-prepare}" = reminders ]; then',1)[1].split('elif ',1)[0]
        self.assertNotIn('ensurepip',branch);self.assertNotIn('sudo',branch)
        self.assertNotIn('apt-get',branch);self.assertNotIn('git',branch)
        self.assertIn('exec python3 -B',entry);self.assertTrue(entry.rstrip().endswith('"$@"'))

    def test_windows_all_five_phases_and_repeated_reservation_preserve_receipt(self):
        self.template()
        with self.wsl(),patch.object(prep,'notification_config',side_effect=self.notification_reader), \
                patch.object(prep,'extension_unc',return_value='\\\\wsl.localhost\\Fixture Distro\\fixture\\extension'), \
                patch('builtins.input',return_value='yes'):
            inspect=self.args();inspect.windows_phase='inspect'
            self.assertEqual(json.loads(self.run_action(inspect)),{'mode':'fresh'})
            reserved=self.reserve();self.assertEqual(reserved['mode'],'windows')
            self.assertEqual(self.reserve(),reserved)
            stage=self.args();stage.windows_phase='stage'
            self.assertIn('waiting for Windows publication',self.run_action(stage))
            staged=json.loads(self.run_action(inspect));self.assertIn('proof',staged)
            self.assertEqual(staged['target'],reserved['target']);self.assertEqual(staged['nonce'],reserved['nonce'])
            confirm=self.args();confirm.windows_phase='confirm';confirm.windows_proof=staged['proof']
            confirmed=json.loads(self.run_action(confirm));self.assertTrue(confirmed['confirmed'])
            before={p:p.read_bytes() for p in (self.config,self.state/'notification-pending.json',self.state/'windows-extension.json',self.state/'extension/connection.js')}
            follow=self.args();follow.windows_phase='continue'
            self.assertIn(reserved['target'],self.run_action(follow))
            self.assertIn(reserved['target'],self.run_action(self.args()))
            for path,data in before.items():self.assertEqual(path.read_bytes(),data)

    def test_windows_inspect_existing_linux_pairing_is_one_json(self):
        self.pair()
        args=self.args();args.windows_phase='inspect'
        with self.wsl():self.assertEqual(json.loads(self.run_action(args)),{'mode':'existing'})
        self.assertFalse((self.state/'windows-extension.json').exists())

    def test_windows_unknown_proof_and_missing_pairing_never_regenerate(self):
        self.template()
        with self.wsl(),patch.object(prep,'notification_config',side_effect=self.notification_reader), \
                patch.object(prep,'extension_unc',return_value='\\\\wsl.localhost\\Fixture Distro\\fixture\\extension'), \
                patch('builtins.input',return_value='yes'):
            self.reserve();args=self.args();args.windows_phase='stage';self.run_action(args)
            args.windows_phase='confirm';args.windows_proof='0'*64
            before=(self.state/'windows-extension.json').read_bytes()
            with self.assertRaisesRegex(prep.Refusal,'WINDOWS_CONFIRMATION_CHANGED'):self.run_action(args)
            self.assertEqual((self.state/'windows-extension.json').read_bytes(),before)
            self.config.unlink();(self.state/'notification-pending.json').unlink()
            args.windows_phase='stage'
            with self.assertRaisesRegex(prep.Refusal,'WINDOWS_PAIRING_AUTHORITY_MISSING'):self.run_action(args)

    def test_reentry_preserves_action_phase_parameters_without_stdout(self):
        class Reentered(Exception):pass
        for phase in (None,'inspect','reserve','stage','confirm','continue'):
            with self.subTest(phase=phase),patch.object(prep,'SOURCE',self.base/'release'), \
                    patch.object(prep.os,'execv',side_effect=Reentered) as call:
                args=self.args();args.windows_phase=phase;args.windows_target_base64='Zml4dHVyZQ=='
                args.windows_proof='f'*64
                output=io.StringIO()
                with contextlib.redirect_stdout(output),self.assertRaises(Reentered):
                    prep.run_locked(args,self.home,self.state)
                argv=call.call_args.args[1]
                expected=[str(self.python),'-B',str(self.product/'scripts/prepare-bridge.py'),'reminders']
                if phase:expected+=['--windows-phase',phase]
                expected+=['--windows-target-base64','Zml4dHVyZQ==','--windows-proof','f'*64]
                self.assertEqual(argv,expected);self.assertEqual(output.getvalue(),'')

    def test_status_and_credentials_do_not_enter_reminders(self):
        with patch.object(prep,'prepare_reminders',side_effect=AssertionError('not a reminder action')), \
                patch.object(prep,'windows_record',side_effect=AssertionError('not a reminder action')), \
                patch.object(prep,'status_service',return_value=None), \
                patch.object(prep,'status_file',return_value='absent'), \
                patch.object(prep,'replace_tunnel_credentials') as credentials, \
                patch('builtins.input',return_value='no'):
            self.run_action(self.args('status'));self.run_action(self.args('credentials'))
            credentials.assert_called_once_with(self.product)

    def test_windows_phases_cannot_enter_core_actions(self):
        for action in ('prepare','status','credentials'):
            args=self.args(action);args.windows_phase='inspect'
            with self.assertRaisesRegex(prep.Refusal,'WINDOWS_PHASE_INVALID'):self.run_action(args)

    def test_environment_probe_is_isolated_and_checks_product_prefix(self):
        # Test the actual helper beneath setUp's explicit boundary stub.
        actual=module('prepare-bridge.py')
        with patch.object(actual,'Path',prep.Path), \
                patch.object(actual.subprocess,'run',return_value=SimpleNamespace(returncode=0)) as run:
            self.assertTrue(actual.environment_ready(self.python,self.product))
        argv=run.call_args.args[0]
        self.assertEqual(argv[:3],[str(self.python),'-I','-B'])
        self.assertIn('sys.prefix',argv[4]);self.assertEqual(argv[-1],str(self.product))


class Repairs(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name);self.state=self.base/'state';self.state.mkdir(mode=0o700)
        self.root=self.base/'project';self.root.mkdir()
    def test_owned_venv_directory_interruption_is_completed_without_removal(self):
        product=self.state/'product';product.mkdir(mode=0o700)
        def interrupted(args,**kw):
            (product/'.venv').mkdir(mode=0o700);raise OSError('interrupted')
        with patch.object(prep,'command',side_effect=interrupted),self.assertRaises(OSError):prep.prepare_venv(product)
        marker=(product/'venv-owner.json').read_bytes()
        python=prep.prepare_venv(product);self.assertTrue(python.is_file())
        self.assertEqual((product/'venv-owner.json').read_bytes(),marker)
        with patch.object(prep,'command',side_effect=AssertionError('no repeat')):self.assertEqual(prep.prepare_venv(product),python)
    def test_unknown_empty_venv_not_deleted_or_adopted(self):
        product=self.state/'product';product.mkdir();(product/'.venv').mkdir()
        with self.assertRaisesRegex(prep.Refusal,'UNOWNED_PARTIAL'):prep.prepare_venv(product)
        self.assertTrue((product/'.venv').is_dir());self.assertFalse((product/'venv-owner.json').exists())
    def test_private_explicit_credential_replacement_does_not_control_service(self):
        from types import SimpleNamespace
        credentials=self.state/'credentials';old={'tunnel_id':'synthetic','runtime_api_key':'old'}
        prep.publish(credentials,prep.json_bytes(old))
        fake=SimpleNamespace(CREDENTIALS=credentials,record=lambda:{'plan':{}},configured_owner=lambda _:None,validate_credentials=lambda v:v)
        secrets=iter(['new-tunnel','new-key'])
        with patch.object(prep,'load_script',return_value=fake),patch.object(prep,'command',side_effect=AssertionError('no services')):
            prep.replace_tunnel_credentials(ROOT,lambda _:'yes',lambda _:next(secrets))
        self.assertEqual(json.loads(credentials.read_text())['runtime_api_key'],'new-key');self.assertEqual(credentials.stat().st_mode&0o777,0o600)
        secrets=iter(['new-tunnel','sk-admin-forbidden'])
        with patch.object(prep,'load_script',return_value=fake),self.assertRaisesRegex(prep.Refusal,'ADMIN_KEY_REFUSED'):
            prep.replace_tunnel_credentials(ROOT,lambda _:'yes',lambda _:next(secrets))
    def test_two_cooperating_preparers_cannot_enter_same_writer_scope(self):
        from types import SimpleNamespace
        home=self.base/'owner';home.mkdir(mode=0o700)
        entries=[]
        def body(args,actual_home,state):
            self.assertEqual(actual_home,home)
            self.assertEqual(state,home/'.local/share/gpt-agent-bridge')
            entries.append(state)
            if len(entries)==1:
                # A second main opens the same lock independently; it must not
                # reach run_locked while the first entry still owns the scope.
                with self.assertRaises(BlockingIOError):prep.main()
        with patch.object(prep.sys,'argv',['prepare','prepare']), \
                patch.object(prep.pwd,'getpwuid',return_value=SimpleNamespace(pw_dir=str(home))), \
                patch.object(prep,'run_locked',side_effect=body), \
                patch.object(prep,'command',side_effect=AssertionError('no runtime actions')):
            prep.main()
            self.assertEqual(len(entries),1)
            prep.main()  # A third entry succeeds after the first closes its lock.
            self.assertEqual(len(entries),2)
    def test_credential_activation_observes_stop_before_start_and_stops_on_unknown(self):
        from types import SimpleNamespace
        system=module('prepare-system.py');calls=[]
        for states in [['active','inactive','active'],['active','deactivating']]:
            iterator=iter(states)
            fake=SimpleNamespace(record=lambda:{},managed_properties=lambda:{'ActiveState':next(iterator)},lifecycle=lambda a:calls.append(a))
            with patch.object(system,'snapshot'),patch.object(system,'module',return_value=fake):
                if len(states)==3:
                    self.assertEqual(system.activate_credentials(ROOT,self.state)['active'],'active');self.assertEqual(calls,['stop','start'])
                else:
                    calls.clear()
                    with self.assertRaisesRegex(ValueError,'STOP_UNKNOWN'):system.activate_credentials(ROOT,self.state)
                    self.assertEqual(calls,['stop'])
    def test_owned_partial_venv_with_interpreter_but_missing_pip_recovers(self):
        product=self.state/'product';product.mkdir(mode=0o700);venv=product/'.venv'
        prep.publish(product/'venv-owner.json',prep.json_bytes({'path':str(venv),'owner':os.getuid(),'purpose':'bridge-preparation-venv-v1'}))
        subprocess.run([os.sys.executable,'-m','venv','--without-pip',str(venv)],check=True)
        python=prep.prepare_venv(product)
        self.assertEqual(subprocess.run([str(python),'-I','-c','import pip'],capture_output=True).returncode,0)
    def test_upgrade_preserves_legacy_root_scope_in_private_connection_and_receipt(self):
        import hashlib
        old=self.state/'original-extension';old.mkdir(mode=0o700)
        prep.publish(old/'manifest.json',b'{"manifest_version":3,"version":"0.3.4"}')
        config=self.state/'config.json';identity={'project_ref':'legacy','root':str(self.root)}
        prep.publish(config,prep.json_bytes({**identity,'port':8765,'token':'t'*48,'extension_id':'a'*32}))
        result=prep.prepare_extension(ROOT,self.state,config,old)
        expected={**identity,'scope_id':hashlib.sha256(('legacy\0'+str(self.root)).encode()).hexdigest()}
        self.assertEqual(result['legacy_identity'],expected)
        self.assertIn(json.dumps(expected),(old/'connection.js').read_text())
    def test_windows_embedded_entry_accepts_clean_checkout_and_forwards_actions(self):
        # Exact embedded program; no PowerShell/WSL or Windows execution claimed.
        script=(ROOT/'Start-Bridge.ps1').read_text();self.assertIn('"$release/scripts/prepare-bridge.py" $Action',script)
        code=script.split("$copy = @'\n",1)[1].split("\n'@",1)[0]
        checkout=self.base/'checkout';checkout.mkdir(mode=0o700)
        import shutil
        names=subprocess.check_output(['git','-C',str(ROOT),'ls-files','-z','--','.',':(exclude).principal',':(exclude).principal/**',':(exclude).app.json']).decode().split('\0')
        # Copy explicit candidate product paths, excluding an existing release
        # receipt so this exercises the actual clean checkout acquisition path.
        names=[n for n in names if n and n!='release-manifest.json']
        for name in names:
            dest=checkout/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/name,dest)
        subprocess.run(['git','init','-q',str(checkout)],check=True)
        subprocess.run(['git','add','--',*names],cwd=checkout,check=True)
        subprocess.run(['git','-c','user.name=Fixture','-c','user.email=fixture@invalid','commit','-qm','fixture'],cwd=checkout,check=True)
        home=self.state/'windows-home';home.mkdir(mode=0o700)
        with patch.object(prep.sys,'argv',['copy',str(checkout)]),patch('pathlib.Path.home',return_value=home):exec(compile(code,'Start-Bridge.ps1 embedded','exec'),{})
        manifest=prep.release_files(home/'.local/share/bridge-release');self.assertIn('scripts/prepare-system.py',manifest['files']);self.assertNotIn('scripts/prepare-provider.py',manifest['files'])
        with patch.object(prep.sys,'argv',['copy',str(checkout)]),patch('pathlib.Path.home',return_value=home):exec(compile(code,'Start-Bridge.ps1 embedded repeat','exec'),{})

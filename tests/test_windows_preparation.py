"""First-use paths and distro choice; no real WSL, browser or service execution."""
import contextlib
import ast
import base64
import io
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tests.test_preparation import ROOT, prep

WINDOWS_POWERSHELL=shutil.which('powershell.exe')
POWERSHELL=WINDOWS_POWERSHELL or shutil.which('pwsh')


class WindowsEntry(unittest.TestCase):
    def powershell(self,code):
        # Encoded input also works with Windows PowerShell 5.1 from WSL, with no
        # script files/profile/launcher execution or Linux-path conversion needed.
        code="$ProgressPreference='SilentlyContinue'; [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding;\n"+code
        encoded=base64.b64encode(code.encode('utf-16le')).decode('ascii')
        # Keep the Windows 32767-character command-line limit out of ParseInput
        # and large function fixtures; only synthetic test code travels on stdin.
        loader="& ([ScriptBlock]::Create([Text.Encoding]::Unicode.GetString([Convert]::FromBase64String([Console]::In.ReadToEnd()))))"
        return subprocess.run([POWERSHELL,'-NoProfile','-NonInteractive','-Command',loader],input=encoded,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=30)

    def test_every_runtime_call_is_pinned_after_selection_and_before_writes(self):
        script=(ROOT/'Start-Bridge.ps1').read_text()
        calls=[line for line in script.splitlines() if '& wsl.exe ' in line]
        self.assertEqual(sum('--list ' in line for line in calls),2)
        runtime=[line for line in calls if '--list ' not in line]
        self.assertGreaterEqual(len(runtime),7)
        for line in runtime:self.assertRegex(line,r'& wsl.exe --distribution \$[Dd]istro --exec ')
        self.assertLess(script.index('$distro = Select-BridgeWslDistro'),script.index('sudo apt-get'))
        self.assertLess(script.index('$actual = @('),script.index('$copy ='))
        self.assertIn('"BRIDGE_WSL_DISTRO=$distro" python3',script)
        self.assertNotRegex(script,r'--(?:set-default|set-version|shutdown|terminate)\b')

    @unittest.skipUnless(WINDOWS_POWERSHELL,'Windows native API fixture requires Windows PowerShell; no install attempted')
    def test_native_windows_publication_and_refusals_in_owned_temp_only(self):
        # Execute only functions, never the launcher. The source is a local dummy
        # directory at the filesystem seam, not WSL or an installed extension.
        script=(ROOT/'Start-Bridge.ps1').read_text()
        functions=script[script.index('function Get-BridgeWsl2Distros'):script.index("if (-not (Get-Command wsl.exe")]
        code=r"""$ErrorActionPreference='Stop'; Set-StrictMode -Version Latest
FUNCTIONS
$root=Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) ('bridge-publication-fixture-'+[Guid]::NewGuid().ToString('N'))
$folder=New-Object IO.DirectoryInfo($root); $folder.Create((New-BridgePrivateAcl))
try {
 $source=Join-Path $root 'source'; [void][IO.Directory]::CreateDirectory($source)
 $files=@{}
 foreach($name in @('connection.js','manifest.json','worker.js')) {
  [IO.File]::WriteAllBytes((Join-Path $source $name),[Text.Encoding]::UTF8.GetBytes('SYNTHETIC_PRIVATE_DUMMY'))
  $files[$name]=Get-BridgeFileDigest (Join-Path $source $name)
 }
 $info=(@{target=(Join-Path $root "chosen Unicode 旧 O'Brien");nonce=('a'*32);proof=('b'*64);source=$source;confirmed=$false;spec=@{files=$files}}|ConvertTo-Json -Depth 5)|ConvertFrom-Json
 Publish-BridgeWindowsFiles $info
 Assert-BridgeDeployment $info.target $info $true
 Publish-BridgeWindowsFiles $info # acknowledged-lost publication is observed, not overwritten
 $info.confirmed=$true
 Publish-BridgeWindowsFiles $info
 $info.target=Join-Path $root 'missing-confirmed'
 $bad=$false; try {Publish-BridgeWindowsFiles $info} catch {$bad=$true}; if(-not $bad -or (Test-Path -LiteralPath $info.target)){throw 'missing confirmed target recreated'}
 $bad=$false; try { Publish-BridgeWindowsExtension $info 'wrong-distro' } catch { $bad=$true }; if(-not $bad){throw 'wrong distro accepted'}
 # Another cooperating Windows thread holding the same native mutex blocks us.
 $info.target=Join-Path $root 'busy'
 $hash=[Security.Cryptography.SHA256]::Create()
 try {$key=([BitConverter]::ToString($hash.ComputeHash([Text.Encoding]::UTF8.GetBytes($info.target.ToUpperInvariant())))).Replace('-','')}finally{$hash.Dispose()}
 $ready=New-Object Threading.ManualResetEvent($false); $release=New-Object Threading.ManualResetEvent($false)
 $runner=[PowerShell]::Create()
 $null=$runner.AddScript('$m=New-Object Threading.Mutex($false,$args[0]); try { if(-not $m.WaitOne(0)){throw "lock unavailable"}; try {$null=$args[1].Set();$null=$args[2].WaitOne(10000)} finally {$m.ReleaseMutex()} } finally {$m.Dispose()}').AddArgument(('Global\BridgeExtension-'+$key)).AddArgument($ready).AddArgument($release)
 $running=$runner.BeginInvoke()
 try {
  if(-not $ready.WaitOne(10000)){throw 'fixture lock not acquired'}
  $bad=$false; try {Publish-BridgeWindowsFiles $info} catch {if($_.Exception.Message -eq 'WINDOWS_DESTINATION_BUSY'){$bad=$true}}; if(-not $bad){throw 'overlapping writer accepted'}
 } finally {$null=$release.Set();$null=$runner.EndInvoke($running);$runner.Dispose();$ready.Dispose();$release.Dispose()}
 # Complete known files with a matching private marker can be resumed.
 $info.confirmed=$false; $info.target=Join-Path $root 'partial'
 $stage=$info.target+'.bridge-stage-'+$info.nonce
 $folder=New-Object IO.DirectoryInfo($stage); $folder.Create((New-BridgePrivateAcl))
 [IO.File]::WriteAllText((Join-Path $stage '.bridge-install.json'),(@{target=$info.target;nonce=$info.nonce;proof=$info.proof}|ConvertTo-Json -Compress))
 [IO.File]::Copy((Join-Path $source 'worker.js'),(Join-Path $stage 'worker.js'))
 Publish-BridgeWindowsFiles $info
 Assert-BridgeDeployment $info.target $info $true
 # Unknown occupied target, changed known file, unsafe ACL, and a reparse ancestor refuse.
 $unknown=Join-Path $root 'unrelated'; [void][IO.Directory]::CreateDirectory($unknown)
 $info.target=$unknown
 $bad=$false; try { Publish-BridgeWindowsFiles $info } catch { $bad=$true }; if(-not $bad){throw 'unknown target accepted'}
 $info.target=Join-Path $root 'partial'; [IO.File]::WriteAllText((Join-Path $info.target 'worker.js'),'changed')
 $bad=$false; try { Publish-BridgeWindowsFiles $info } catch { $bad=$true }; if(-not $bad){throw 'changed file accepted'}
 $unsafe=Join-Path $root 'unsafe'; [void][IO.Directory]::CreateDirectory($unsafe)
 $acl=(New-Object IO.DirectoryInfo($unsafe)).GetAccessControl()
 $acl.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule((New-Object Security.Principal.SecurityIdentifier('S-1-1-0')),'Read','Allow')))
 (New-Object IO.DirectoryInfo($unsafe)).SetAccessControl($acl)
 $bad=$false; try { Assert-BridgePrivateEntry $unsafe $true } catch { $bad=$true }; if(-not $bad){throw 'unsafe ACL accepted'}
 $acl.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule((New-Object Security.Principal.SecurityIdentifier('S-1-1-0')),'Modify','Allow')))
 (New-Object IO.DirectoryInfo($unsafe)).SetAccessControl($acl)
 $bad=$false; try { Assert-BridgeWindowsParent (Join-Path $unsafe 'child') } catch { $bad=$true }; if(-not $bad){throw 'writable parent accepted'}
 foreach($path in @('relative','\\server\share\extension','C:\bad\..\extension','C:\NUL','C:\trailing.')) {
  $bad=$false; try { Get-BridgeWindowsTarget $path | Out-Null } catch { $bad=$true }; if(-not $bad){throw 'unsafe path accepted'}
 }
 $query=${function:Get-BridgeDosDevice}
 try {
  function Get-BridgeDosDevice { param($Drive) '\??\C:\synthetic-subst' }
  $bad=$false; try {Get-BridgeWindowsTarget $info.target | Out-Null} catch {$bad=$true}; if(-not $bad){throw 'ambiguous volume accepted'}
 } finally { ${function:Get-BridgeDosDevice}=$query }
 # A junction is confined to this owned fixture and removed before recursive cleanup.
 $junction=Join-Path $root 'junction'
 $null=New-Item -ItemType Junction -Path $junction -Target $source
 try {
  $bad=$false; try { Assert-BridgeWindowsParent (Join-Path $junction 'extension') } catch { $bad=$true }; if(-not $bad){throw 'junction accepted'}
 } finally { [IO.Directory]::Delete($junction) }
 'native publication/refusal fixtures passed'
} finally { if([IO.Directory]::Exists($root)){[IO.Directory]::Delete($root,$true)} }
""".replace('FUNCTIONS',functions)
        result=self.powershell(code)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('native publication/refusal fixtures passed',result.stdout)
        self.assertNotIn('SYNTHETIC_PRIVATE_DUMMY',result.stdout+result.stderr)

    @unittest.skipUnless(POWERSHELL,'PowerShell unavailable; no install attempted')
    def test_powershell_syntax_without_executing_launcher(self):
        source=(ROOT/'Start-Bridge.ps1').read_text().replace("'","''")
        code=f"$tokens=$null; $errors=$null; [void][System.Management.Automation.Language.Parser]::ParseInput('{source}',[ref]$tokens,[ref]$errors); if ($errors.Count) {{ $errors | Out-String | Write-Output; exit 1 }}"
        result=self.powershell(code)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    @unittest.skipUnless(POWERSHELL,'PowerShell unavailable; no install attempted')
    def test_metadata_transport_pins_distro_and_preserves_extra_arguments(self):
        script=(ROOT/'Start-Bridge.ps1').read_text()
        functions=script[script.index('function Get-BridgeWsl2Distros'):script.index("if (-not (Get-Command wsl.exe")]
        code=r"""$ErrorActionPreference='Stop'; Set-StrictMode -Version Latest
FUNCTIONS
function wsl.exe { $script:captured=@($args); $global:LASTEXITCODE=0; '{"mode":"fresh"}' }
$result=Get-BridgeWindowsMetadata "Fixture O'Brien 旧" '/fixture/script.py' 'reserve' @('--windows-target-base64','SYNTHETIC_NOT_A_SECRET')
if($result.mode -ne 'fresh'){throw 'metadata result invalid'}
if(($script:captured -join '|') -cne "--distribution|Fixture O'Brien 旧|--exec|env|BRIDGE_WSL_DISTRO=Fixture O'Brien 旧|python3|/fixture/script.py|prepare|--windows-phase|reserve|--windows-target-base64|SYNTHETIC_NOT_A_SECRET"){throw 'metadata argv changed'}
'metadata fixture passed'
""".replace('FUNCTIONS',functions)
        result=self.powershell(code)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('metadata fixture passed',result.stdout)

    def choice(self,names,details,answer):
        # Only the exact pure selection functions execute, never the launcher or wsl.exe.
        script=(ROOT/'Start-Bridge.ps1').read_text()
        functions=script[script.index('function Get-BridgeWsl2Distros'):script.index("if (-not (Get-Command wsl.exe")]
        fixture=json.dumps(dict(names=names,details=details,answer=answer),ensure_ascii=False).replace("'","''")
        code="""$ErrorActionPreference='Stop'; Set-StrictMode -Version Latest
$f=ConvertFrom-Json 'FIXTURE'
function Write-Host { }
$script:prompts=@()
function Read-Host { param($Prompt) $script:prompts+= $Prompt; return $f.answer }
FUNCTIONS
try {
 $eligible=@(Get-BridgeWsl2Distros -Names $f.names -Details $f.details)
 $chosen=Select-BridgeWslDistro -Names $f.names -Eligible $eligible
 @{chosen=$chosen; selectionCount=@($chosen).Count; eligible=$eligible; prompts=$script:prompts} | ConvertTo-Json -Compress
} catch { @{error=$_.Exception.Message; prompts=$script:prompts} | ConvertTo-Json -Compress }
""".replace('FIXTURE',fixture).replace('FUNCTIONS',functions)
        result=self.powershell(code)
        self.assertEqual(result.returncode,0,result.stderr)
        return json.loads(result.stdout)

    @unittest.skipUnless(POWERSHELL,'PowerShell unavailable; no install attempted')
    def test_actual_names_versions_single_confirmation_and_multi_choice(self):
        name="Team [dev] & O'Brien"
        chosen=self.choice([name],[f'* {name}    Stopped    2'],'')
        self.assertEqual(chosen['chosen'],name)
        self.assertIn(name,chosen['prompts'][0])
        self.assertEqual(self.choice([name],[f'* {name}    Stopped    2'],'n')['selectionCount'],0)
        for answer in ['Ubuntu-24.04','Debian']:
            with self.subTest(answer=answer):
                selected=self.choice(['Ubuntu-24.04','Debian','Legacy'],
                    ['NAME STATE VERSION','* Ubuntu-24.04    Running    2','  Debian    已停止    2','  Legacy    Stopped    1'],answer)
                self.assertEqual(selected['chosen'],answer)
                self.assertEqual(selected['eligible'],['Ubuntu-24.04','Debian'])

    @unittest.skipUnless(POWERSHELL,'PowerShell unavailable; no install attempted')
    def test_overlapping_inventory_names_in_both_orders_and_mixed_versions(self):
        for names in [['Ubuntu','Ubuntu Dev'],['Ubuntu Dev','Ubuntu']]:
            for versions in [(2,2),(1,2),(2,1)]:
                rows=[f'* Ubuntu Running {versions[0]}',f'Ubuntu Dev Stopped {versions[1]}']
                expected=[name for name in names if versions[['Ubuntu','Ubuntu Dev'].index(name)]==2]
                for details in [rows,list(reversed(rows))]:
                    for answer in expected:
                        with self.subTest(names=names,details=details,answer=answer):
                            result=self.choice(names,details,answer)
                            self.assertEqual(result.get('chosen'),answer,result)
                            self.assertEqual(result['eligible'],expected)
                    for answer in set(names)-set(expected):
                        self.assertIn('error',self.choice(names,details,answer))

    @unittest.skipUnless(POWERSHELL,'PowerShell unavailable; no install attempted')
    def test_refuse_unknown_wsl1_and_ambiguous_inventory(self):
        for names,rows,answer in [
            (['Old'],['* Old Stopped 1'],''),
            (['One','Two'],['* One Running 2','Two Stopped 2'],'Missing'),
            (['One','Old'],['* One Running 2','Old Stopped 1'],'Old'),
            (['One'],['One Stopped 2','One Running 2'],''),
            (['One'],['One Stopped ?'],''),
            (['One','One'],['One Stopped 2'],''),
            (['Ubuntu','Ubuntu Dev'],['Ubuntu Dev Stopped 2'],'Ubuntu Dev'),
            (['Ubuntu','Ubuntu Dev'],['Ubuntu Running 2','Ubuntu Dev Stopped 2','Ubuntu Dev Stopped 2'],'Ubuntu'),
            (['Ubuntu Dev','Ubuntu'],['Ubuntu Dev Stopped 2','Ubuntu Running 2','Ubuntu Stopped 1'],'Ubuntu Dev'),
            (['Ubuntu','Ubuntu Dev'],['Ubuntu Running 2','Ubuntu Dev Stopped 2','Ubuntu Dev Stopped ?'],'Ubuntu'),
        ]:
            with self.subTest(names=names,rows=rows,answer=answer):
                self.assertIn('error',self.choice(names,rows,answer))


class ExtensionHandoff(unittest.TestCase):
    def capture(self,record,env,convert=None,kernel='Linux'):
        output=io.StringIO()
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ,env,clear=True))
            stack.enter_context(patch.object(prep.platform,'release',return_value=kernel))
            stack.enter_context(patch.object(prep,'read',side_effect=AssertionError('handoff cannot read files')))
            stack.enter_context(patch.object(prep,'notification_config',side_effect=AssertionError('handoff cannot read secrets')))
            run=stack.enter_context(patch.object(prep.subprocess,'run',side_effect=convert or AssertionError('no converter expected')))
            stack.enter_context(contextlib.redirect_stdout(output))
            error=None
            try:prep.extension_handoff(record)
            except prep.Refusal as e:error=str(e)
        return output.getvalue(),error,run

    def test_linux_uses_actual_receipt_path_without_home_guess_or_secret_read(self):
        record={'path':"/srv/owners/alice/old apps/extension $[1] & O'Brien",'extension_id':'a'*32,'token':'SYNTHETIC_DO_NOT_PRINT'}
        output,error,run=self.capture(record,{'HOME':'/wrong/home'})
        self.assertIsNone(error);run.assert_not_called()
        self.assertIn(record['path'],output);self.assertIn(record['extension_id'],output)
        self.assertNotIn('/wrong/home',output);self.assertNotIn(record['token'],output)
        self.assertNotIn('Windows path',output)
        self.assertIn('does not mean Chrome, services, Tunnel or Chat are connected',output)

    def test_verified_wsl_unc_uses_argv_and_roundtrip_for_adopted_path(self):
        distro="Team [dev] & O'Brien"
        path="/srv/owners/alice/旧扩展 $[1] & O'Brien"
        windows='\\\\wsl$\\'+distro+path.replace('/','\\')
        def converter(args,**kwargs):
            self.assertEqual(kwargs,dict(capture_output=True,text=True,timeout=10))
            if args==['wslpath','-w',path]:return SimpleNamespace(returncode=0,stdout=windows+'\n')
            self.assertEqual(args,['wslpath','-u',windows])
            return SimpleNamespace(returncode=0,stdout=path+'\n')
        output,error,run=self.capture({'path':path,'extension_id':'b'*32},
            {'HOME':'/wrong/home','WSL_DISTRO_NAME':distro,'BRIDGE_WSL_DISTRO':distro},converter)
        self.assertIsNone(error);self.assertEqual(run.call_count,2)
        self.assertIn('\\\\wsl.localhost\\'+distro+path.replace('/','\\')+'\n',output)
        self.assertIn('WSL distro: '+distro,output)

    def test_failed_or_unverified_conversion_stops_without_leaking_converter_output(self):
        path='/srv/owner/extension';unc='\\\\wsl.localhost\\Chosen\\srv\\owner\\extension'
        cases=[
            ('missing-distro',{},'microsoft-standard-WSL2',None),
            ('wrong-distro',{'WSL_DISTRO_NAME':'Other','BRIDGE_WSL_DISTRO':'Chosen'},'Linux',None),
            ('missing-command',{'WSL_DISTRO_NAME':'Chosen'},'Linux',FileNotFoundError('SYNTHETIC_SECRET')),
            ('failed-command',{'WSL_DISTRO_NAME':'Chosen'},'Linux',lambda *a,**k:SimpleNamespace(returncode=1,stdout='SYNTHETIC_SECRET')),
            ('wrong-unc',{'WSL_DISTRO_NAME':'Chosen'},'Linux',lambda *a,**k:SimpleNamespace(returncode=0,stdout='\\\\wsl.localhost\\Other\\extension')),
            ('drive-path',{'WSL_DISTRO_NAME':'Chosen'},'Linux',lambda *a,**k:SimpleNamespace(returncode=0,stdout='D:\\extension')),
            ('wrong-roundtrip',{'WSL_DISTRO_NAME':'Chosen'},'Linux',lambda args,**k:SimpleNamespace(returncode=0,stdout=unc if args[1]=='-w' else '/different')),
            ('multiline',{'WSL_DISTRO_NAME':'Chosen'},'Linux',lambda *a,**k:SimpleNamespace(returncode=0,stdout=unc+'\nSYNTHETIC_SECRET')),
        ]
        for name,env,kernel,converter in cases:
            with self.subTest(name=name):
                output,error,run=self.capture({'path':path,'extension_id':'a'*32},env,converter,kernel)
                self.assertEqual(error,'WINDOWS_EXTENSION_PATH_UNVERIFIED')
                self.assertIn('Windows extension path: unavailable/unverified',output)
                self.assertIn('Private extension Linux path: '+path,output)
                self.assertNotIn('SYNTHETIC_SECRET',output)
                self.assertNotIn('copy into Chrome',output)
                if name in ('missing-distro','wrong-distro'):run.assert_not_called()

    def test_main_prints_real_generated_path_before_service_failure_using_passwd_home(self):
        self.check_handoff_service_boundary(conversion_ok=True)

    def test_unverified_handoff_stops_before_any_service_change(self):
        self.check_handoff_service_boundary(conversion_ok=False)

    def check_handoff_service_boundary(self,conversion_ok):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp)/'passwd home';home.mkdir(mode=0o700)
            state=prep.directory(home/'.local/share/gpt-agent-bridge',True)
            product=prep.directory(state/'product',True);prep.directory(product/'scripts')
            prep.publish(product/'release-manifest.json',b'{}')
            prep.publish(product/'requirements.txt',b'')
            prep.publish(product/'scripts/release-assets.json',b'{"synthetic":{"tunnel":{}}}')
            python=product/'.venv/bin/python';output=io.StringIO();distro='Fixture WSL2'
            real_prepare=prep.prepare_extension
            def generate(source,state,config,existing,**kwargs):
                return real_prepare(ROOT,state,config,existing,**kwargs)
            def run(args,**kwargs):
                if args[0]=='wslpath':
                    if not conversion_ok:return SimpleNamespace(returncode=1,stdout='SYNTHETIC_DO_NOT_PRINT')
                    if args[1]=='-w':value='\\\\wsl.localhost\\'+distro+args[2].replace('/','\\')
                    else:value=args[2].removeprefix('\\\\wsl.localhost\\'+distro).replace('\\','/')
                    return SimpleNamespace(returncode=0,stdout=value+'\n')
                self.assertEqual(args[0],str(python)) # isolated dependency probe only
                return SimpleNamespace(returncode=0)
            def service(args,**kwargs):
                self.assertTrue(conversion_ok,'unverified Windows handoff must stop before service changes')
                self.assertEqual(args[:2],['sudo','python3'])
                self.assertEqual(args[3],'bridge')
                self.assertIn(str(state/'extension'),output.getvalue())
                self.assertIn('copy into Chrome',output.getvalue())
                raise prep.Refusal('SYNTHETIC_SERVICE_FAILURE')
            with contextlib.ExitStack() as stack:
                for obj,name,value in [(prep,'SOURCE',product),(prep.sys,'executable',str(python)),
                        (prep,'prepare_copy',lambda *a:product),(prep,'prepare_venv',lambda *a:python),
                        (prep,'download',lambda *a:state/'synthetic-bundle'),(prep,'select_herdr',lambda:'/synthetic/herdr'),
                        (prep,'prepare_extension',generate),(prep,'command',service)]:
                    stack.enter_context(patch.object(obj,name,value))
                stack.enter_context(patch.object(prep.subprocess,'run',side_effect=run))
                stack.enter_context(patch.object(prep.pwd,'getpwuid',return_value=SimpleNamespace(pw_dir=str(home),pw_name='synthetic')))
                stack.enter_context(patch.object(prep.platform,'machine',return_value='synthetic'))
                stack.enter_context(patch.dict(os.environ,{'HOME':'/wrong/home','WSL_DISTRO_NAME':distro,'BRIDGE_WSL_DISTRO':distro},clear=True))
                stack.enter_context(patch.object(prep.sys,'argv',['prepare']))
                stack.enter_context(patch('builtins.input',return_value='yes'))
                stack.enter_context(contextlib.redirect_stdout(output))
                code='SYNTHETIC_SERVICE_FAILURE' if conversion_ok else 'WINDOWS_EXTENSION_PATH_UNVERIFIED'
                with self.assertRaisesRegex(prep.Refusal,code):prep.main()
            receipt=json.loads((state/'extension.json').read_text())
            config=json.loads((home/'.config/gpt-agent-bridge/browser-notifications.json').read_text())
            self.assertEqual(receipt['path'],str(state/'extension'))
            self.assertIn(receipt['extension_id'],output.getvalue())
            self.assertNotIn(config['token'],output.getvalue())
            self.assertNotIn('/wrong/home',output.getvalue())
            self.assertNotIn('Software preparation is complete',output.getvalue())
            self.assertNotIn('SYNTHETIC_DO_NOT_PRINT',output.getvalue())
            if not conversion_ok:self.assertIn('Windows extension path: unavailable/unverified',output.getvalue())


class WindowsPreparation(unittest.TestCase):
    """Real materialization with synthetic config IO; no HTTP dependency or live config."""
    target="D:\\Fixture 旧 O'Brien\\extension"

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.home=Path(self.tmp.name)/'home';self.home.mkdir(mode=0o700)
        self.state=prep.directory(self.home/'state',True)
        self.config=self.home/'config/browser-notifications.json'
        stack=contextlib.ExitStack();self.addCleanup(stack.close)
        stack.enter_context(patch.dict(os.environ,{'WSL_DISTRO_NAME':'Fixture','BRIDGE_WSL_DISTRO':'Fixture'}))
        # Only replace the config parser's optional HTTP imports; all generated
        # config/receipt/file writes and private reads use the real preparation code.
        stack.enter_context(patch.object(prep,'notification_config',side_effect=lambda p:json.loads(prep.read(p)) if p.exists() else None))
        stack.enter_context(patch.object(prep,'extension_unc',side_effect=lambda p:'\\\\wsl.localhost\\Fixture'+p.replace('/','\\')))

    def reserve(self):return prep.windows_control('reserve',self.state,self.config,self.target)

    def materialize(self):
        record=prep.prepare_extension(ROOT,self.state,self.config)
        prep.windows_staged(self.state,record)
        return record

    def authority_reader(self):
        # Execute the actual config validator/reader without importing its HTTP
        # routes. No dependency stubs or replacement validation semantics.
        tree=ast.parse((ROOT/'src/gpt_agent_bridge/browser_notifications.py').read_text())
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='BrowserNotifications')
        cls.body=[n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name in ('validate_config','read_config')]
        namespace=dict(Path=Path,json=json,os=os,re=re,stat=stat)
        exec(compile(ast.Module(body=[cls],type_ignores=[]),'<actual config reader>','exec'),namespace)
        return namespace['BrowserNotifications'].read_config

    @contextlib.contextmanager
    def run_fixture(self):
        # All external effects are mocked; run_locked and extension/config IO
        # remain real and operate only in this test's private temporary home.
        product=prep.directory(self.state/'product',True);prep.directory(product/'scripts')
        prep.publish(product/'requirements.txt',b'')
        prep.publish(product/'release-manifest.json',b'{}')
        prep.publish(product/'scripts/release-assets.json',b'{"fixture":{"tunnel":{}}}')
        python=product/'.venv/bin/python';output=io.StringIO()
        with contextlib.ExitStack() as stack:
            for obj,name,value in [(prep,'SOURCE',product),(prep.sys,'executable',str(python)),
                    (prep,'prepare_copy',lambda *a:None),(prep,'prepare_venv',lambda *a:python),
                    (prep,'select_herdr',lambda:'/fixture/herdr'),(prep,'download',lambda *a:'/fixture/bundle'),
                    (prep,'notification_config',self.authority_reader())]:
                stack.enter_context(patch.object(obj,name,value))
            stack.enter_context(patch.object(prep.platform,'machine',return_value='fixture'))
            actual=prep.prepare_extension
            materialize=stack.enter_context(patch.object(prep,'prepare_extension',side_effect=lambda source,*a,**kw:actual(ROOT,*a,**kw)))
            stack.enter_context(patch.object(prep.subprocess,'run',return_value=SimpleNamespace(returncode=0)))
            stack.enter_context(patch('builtins.input',return_value='yes'))
            service=stack.enter_context(patch.object(prep,'command',side_effect=prep.Refusal('SYNTHETIC_SERVICE_STOP')))
            stack.enter_context(contextlib.redirect_stdout(output))
            yield materialize,service,output

    def generation(self,confirmed=False,partial=False):
        self.config=self.home/'.config/gpt-agent-bridge/browser-notifications.json'
        self.reserve()
        if partial:
            actual=prep.publish
            def interrupted(path,*a,**kw):
                if path.name=='worker.js':raise OSError('synthetic interruption')
                return actual(path,*a,**kw)
            with patch.object(prep,'publish',side_effect=interrupted):
                with self.assertRaises(OSError):self.materialize()
        else:self.materialize()
        if confirmed:
            info=prep.windows_control('inspect',self.state,self.config)
            prep.windows_control('confirm',self.state,self.config,proof=info['proof'])

    def snapshot(self):
        # Digests keep even synthetic bearer values out of assertion diagnostics.
        return {str(p.relative_to(self.home)):prep.digest(p.read_bytes())
                for p in self.home.rglob('*') if p.is_file()}

    def test_different_pending_only_windows_authority_cannot_rewrite_generation(self):
        self.generation(confirmed=True)
        pending=self.state/'notification-pending.json'
        changed=json.loads(pending.read_bytes());changed['token']='different_synthetic_token_'+'x'*32
        pending.write_bytes(prep.json_bytes(changed));self.config.unlink()
        info=prep.windows_control('inspect',self.state,self.config)
        with self.run_fixture() as (materialize,service,output):
            before=self.snapshot()
            for phase in ('stage','continue','continue'):
                with self.assertRaises(prep.Refusal) as error:
                    prep.run_locked(SimpleNamespace(action='prepare',existing_extension=None,windows_phase=phase),self.home,self.state)
                self.assertEqual(self.snapshot(),before)
                self.assertEqual(str(error.exception),'WINDOWS_PAIRING_AUTHORITY_INCONSISTENT')
                self.assertEqual(prep.windows_control('inspect',self.state,self.config),info)
            materialize.assert_not_called();service.assert_not_called()
            self.assertNotIn(changed['token'],output.getvalue())

    def test_good_active_windows_authority_does_not_hide_inconsistent_backup(self):
        self.generation(confirmed=True)
        pending=self.state/'notification-pending.json';original=pending.read_bytes()
        info=prep.windows_control('inspect',self.state,self.config)
        for field in ('token','extension_id','port','legacy_identity'):
            with self.subTest(field=field):
                changed=json.loads(original)
                if field=='token':changed[field]='different_synthetic_token_'+'x'*32
                elif field=='extension_id':changed[field]='a'*32 if changed[field]!='a'*32 else 'b'*32
                elif field=='port':changed[field]=8766
                else:
                    changed={k:changed[k] for k in ('extension_id','token','port')}
                    changed.update(project_ref='synthetic',root=str(self.home))
                pending.write_bytes(prep.json_bytes(changed))
                with self.run_fixture() as (materialize,service,output):
                    before=self.snapshot()
                    with self.assertRaisesRegex(prep.Refusal,'^WINDOWS_PAIRING_AUTHORITY_INCONSISTENT$'):
                        prep.run_locked(SimpleNamespace(action='prepare',existing_extension=None,windows_phase='continue'),self.home,self.state)
                    self.assertEqual(self.snapshot(),before)
                    self.assertEqual(prep.windows_control('inspect',self.state,self.config),info)
                    materialize.assert_not_called();service.assert_not_called()
                    self.assertNotIn(changed['token'],output.getvalue())
        pending.write_bytes(original)

    def test_different_active_windows_authority_cannot_override_matching_backup(self):
        self.generation(confirmed=True)
        changed=json.loads(self.config.read_bytes());changed['token']='different_synthetic_token_'+'x'*32
        self.config.write_bytes(prep.json_bytes(changed))
        info=prep.windows_control('inspect',self.state,self.config)
        with self.run_fixture() as (materialize,service,output):
            before=self.snapshot()
            with self.assertRaisesRegex(prep.Refusal,'^WINDOWS_PAIRING_AUTHORITY_INCONSISTENT$'):
                prep.run_locked(SimpleNamespace(action='prepare',existing_extension=None,windows_phase='continue'),self.home,self.state)
            self.assertEqual(self.snapshot(),before)
            self.assertEqual(prep.windows_control('inspect',self.state,self.config),info)
            materialize.assert_not_called();service.assert_not_called()
            self.assertNotIn(changed['token'],output.getvalue())

    def test_inconsistent_partial_windows_generation_refuses_before_writes(self):
        base=self.home
        for early in (True,False):
            with self.subTest(before_connection=early):
                self.home=prep.directory(base/('early' if early else 'late'),True)
                self.state=prep.directory(self.home/'state',True)
                self.config=self.home/'.config/gpt-agent-bridge/browser-notifications.json'
                if early:self.generation(partial=True)
                else:
                    self.reserve();prep.prepare_extension(ROOT,self.state,self.config)
                    self.config.unlink()  # Surviving connection/receipt anchor the sole backup.
                self.assertIsNone(prep.windows_record(self.state)['spec'])
                pending=self.state/'notification-pending.json'
                changed=json.loads(pending.read_bytes());changed['token']='different_synthetic_token_'+'x'*32
                pending.write_bytes(prep.json_bytes(changed))
                info=prep.windows_control('inspect',self.state,self.config)
                with self.run_fixture() as (materialize,service,output):
                    before=self.snapshot()
                    with self.assertRaisesRegex(prep.Refusal,'^WINDOWS_PAIRING_AUTHORITY_INCONSISTENT$'):
                        prep.run_locked(SimpleNamespace(action='prepare',existing_extension=None,windows_phase='stage'),self.home,self.state)
                    self.assertEqual(self.snapshot(),before)
                    self.assertEqual(prep.windows_control('inspect',self.state,self.config),info)
                    materialize.assert_not_called();service.assert_not_called()

    def test_matching_active_only_windows_generation_recreates_identical_backup(self):
        self.generation(confirmed=True)
        pending=self.state/'notification-pending.json';original=pending.read_bytes();pending.unlink()
        info=prep.windows_control('inspect',self.state,self.config)
        with self.run_fixture() as (materialize,service,output):
            before=self.snapshot()
            with self.assertRaisesRegex(prep.Refusal,'^SYNTHETIC_SERVICE_STOP$'):
                prep.run_locked(SimpleNamespace(action='prepare',existing_extension=None,windows_phase='continue'),self.home,self.state)
            self.assertEqual(prep.digest(pending.read_bytes()),prep.digest(original))
            after=self.snapshot();after.pop(str(pending.relative_to(self.home)))
            self.assertEqual(after,before)
            self.assertEqual(prep.windows_control('inspect',self.state,self.config),info)
            materialize.assert_called_once();service.assert_called_once()
            self.assertNotIn(json.loads(original)['token'],output.getvalue())

    def test_current_connection_agreement_cannot_replace_recorded_windows_digest(self):
        base=self.home
        for replace_receipt_hash in (False,True):
            with self.subTest(replace_receipt_hash=replace_receipt_hash):
                self.home=prep.directory(base/str(replace_receipt_hash),True)
                self.state=prep.directory(self.home/'state',True)
                self.generation(confirmed=True)
                changed=json.loads(self.config.read_bytes());changed['token']='different_synthetic_token_'+'x'*32
                self.config.write_bytes(prep.json_bytes(changed))
                (self.state/'notification-pending.json').write_bytes(prep.json_bytes(changed))
                receipt_path=self.state/'extension.json';receipt=json.loads(receipt_path.read_bytes())
                data=prep.extension_connection(changed,receipt)
                (self.state/'extension/connection.js').write_bytes(data)
                if replace_receipt_hash:
                    receipt['files']['connection.js']=prep.digest(data)
                    receipt_path.write_bytes(prep.json_bytes(receipt))
                code='WINDOWS_SOURCE_CHANGED' if replace_receipt_hash else 'WINDOWS_PAIRING_AUTHORITY_INCONSISTENT'
                with self.run_fixture() as (materialize,service,output):
                    before=self.snapshot()
                    with self.assertRaisesRegex(prep.Refusal,'^'+code+'$'):
                        prep.run_locked(SimpleNamespace(action='prepare',existing_extension=None,windows_phase='stage'),self.home,self.state)
                    self.assertEqual(self.snapshot(),before)
                    materialize.assert_not_called();service.assert_not_called()

    def test_missing_windows_pairing_authority_refuses_before_any_generation_write(self):
        self.generation(confirmed=True)
        self.config.unlink();(self.state/'notification-pending.json').unlink()
        info=prep.windows_control('inspect',self.state,self.config)
        with self.run_fixture() as (materialize,service,output):
            before=self.snapshot()
            for phase in ('stage','continue','continue'):
                args=SimpleNamespace(action='prepare',existing_extension=None,windows_phase=phase)
                with self.assertRaisesRegex(prep.Refusal,'^WINDOWS_PAIRING_AUTHORITY_MISSING$'):
                    prep.run_locked(args,self.home,self.state)
                self.assertEqual(self.snapshot(),before)
                self.assertEqual(prep.windows_control('inspect',self.state,self.config),info)
            materialize.assert_not_called();service.assert_not_called()

    def test_partial_windows_generation_without_authority_is_not_a_fresh_reservation(self):
        self.generation(partial=True)
        self.config.unlink();(self.state/'notification-pending.json').unlink()
        self.assertIsNone(prep.windows_record(self.state)['spec'])
        with self.run_fixture() as (materialize,service,output):
            for receipt_present in (True,False):
                if not receipt_present:(self.state/'extension.json').unlink()
                before=self.snapshot()
                with self.assertRaisesRegex(prep.Refusal,'^WINDOWS_PAIRING_AUTHORITY_MISSING$'):
                    prep.run_locked(SimpleNamespace(action='prepare',existing_extension=None,windows_phase='stage'),self.home,self.state)
                self.assertEqual(self.snapshot(),before)
            materialize.assert_not_called();service.assert_not_called()

    def test_pending_only_windows_pairing_recovers_same_confirmed_generation(self):
        self.generation(confirmed=True)
        original=self.config.read_bytes();self.config.unlink()
        info=prep.windows_control('inspect',self.state,self.config)
        with self.run_fixture() as (materialize,service,output):
            before=self.snapshot()
            with self.assertRaisesRegex(prep.Refusal,'^SYNTHETIC_SERVICE_STOP$'):
                prep.run_locked(SimpleNamespace(action='prepare',existing_extension=None,windows_phase='continue'),self.home,self.state)
            self.assertEqual(prep.digest(self.config.read_bytes()),prep.digest(original))
            after=self.snapshot();after.pop(str(self.config.relative_to(self.home)))
            self.assertEqual(after,before)
            self.assertEqual(prep.windows_control('inspect',self.state,self.config),info)
            materialize.assert_called_once();service.assert_called_once()
            self.assertNotIn(json.loads(original)['token'],output.getvalue())

    def test_pending_only_interrupted_windows_generation_resumes_before_publication(self):
        self.generation(partial=True)
        original=self.config.read_bytes();self.config.unlink()
        reserved=prep.windows_record(self.state)
        self.assertFalse((self.state/'extension/connection.js').exists())
        with self.run_fixture() as (materialize,service,output):
            prep.run_locked(SimpleNamespace(action='prepare',existing_extension=None,windows_phase='stage'),self.home,self.state)
            self.assertEqual(prep.digest(self.config.read_bytes()),prep.digest(original))
            self.assertEqual(prep.digest((self.state/'notification-pending.json').read_bytes()),prep.digest(original))
            connection=json.loads((self.state/'extension/connection.js').read_text().removeprefix('export const connection = ').removesuffix(';\n'))
            self.assertEqual(prep.digest(connection['token'].encode()),prep.digest(json.loads(original)['token'].encode()))
            self.assertEqual(connection['extension_id'],json.loads(original)['extension_id'])
            staged=prep.windows_record(self.state)
            self.assertEqual(staged['nonce'],reserved['nonce']);self.assertEqual(staged['target'],reserved['target'])
            self.assertEqual(staged['spec']['extension_id'],json.loads(original)['extension_id'])
            self.assertFalse(staged['confirmed'])
            materialize.assert_called_once();service.assert_not_called()
            self.assertNotIn(json.loads(original)['token'],output.getvalue())

    def test_malformed_active_or_pending_windows_authority_refuses_without_mutation(self):
        self.generation(confirmed=True)
        for path in (self.config,self.state/'notification-pending.json'):
            original=path.read_bytes()
            for bad in (b'{',b'{"token":"SYNTHETIC_DO_NOT_PRINT"}'):
                with self.subTest(authority=path.name,malformed_json=bad==b'{'):
                    path.write_bytes(bad)
                    with self.run_fixture() as (materialize,service,output):
                        before=self.snapshot()
                        with self.assertRaisesRegex(prep.Refusal,'^WINDOWS_PAIRING_AUTHORITY_INVALID$') as error:
                            prep.run_locked(SimpleNamespace(action='prepare',existing_extension=None,windows_phase='continue'),self.home,self.state)
                        self.assertEqual(self.snapshot(),before)
                        materialize.assert_not_called();service.assert_not_called()
                        self.assertNotIn('SYNTHETIC_DO_NOT_PRINT',str(error.exception)+output.getvalue())
            path.write_bytes(original)

    def test_reserved_copy_confirmation_and_exact_reentry_keep_identity(self):
        self.assertEqual(prep.windows_control('inspect',self.state,self.config),{'mode':'fresh'})
        with self.assertRaisesRegex(prep.Refusal,'RESERVATION_REQUIRED'):
            prep.windows_control('confirm',self.state,self.config,proof='unreserved')
        self.reserve();record=self.materialize();original=self.config.read_bytes()
        info=prep.windows_control('inspect',self.state,self.config)
        self.assertFalse(info['confirmed']);self.assertEqual(info['target'],self.target)
        token=json.loads(original)['token'];self.assertNotIn(token,json.dumps(info))
        self.assertEqual(record['path'],str(self.state/'extension'))
        self.assertEqual(prep.extension_id(json.loads((self.state/'extension/manifest.json').read_text())),info['spec']['extension_id'])
        with self.assertRaisesRegex(prep.Refusal,'CONFIRMATION_CHANGED'):
            prep.windows_control('confirm',self.state,self.config,proof='wrong')
        self.assertTrue(prep.windows_control('confirm',self.state,self.config,proof=info['proof'])['confirmed'])
        self.assertEqual(self.materialize(),record);self.assertEqual(self.config.read_bytes(),original)
        with self.assertRaisesRegex(prep.Refusal,'TARGET_CHANGED'):
            prep.windows_control('reserve',self.state,self.config,'C:\\different')
        out=io.StringIO()
        with contextlib.redirect_stdout(out):prep.extension_handoff(record,prep.windows_record(self.state))
        self.assertIn(self.target,out.getvalue());self.assertNotIn(record['path'],out.getvalue())
        self.assertNotIn(token,out.getvalue())

    def test_interrupted_materialization_reuses_pending_token_and_destination(self):
        initial=self.reserve();publish=prep.publish
        def interrupted(path,*args,**kwargs):
            if path.name=='worker.js':raise OSError('synthetic interruption')
            return publish(path,*args,**kwargs)
        with patch.object(prep,'publish',side_effect=interrupted):
            with self.assertRaises(OSError):self.materialize()
        config=self.config.read_bytes();self.assertIsNone(prep.windows_record(self.state)['spec'])
        self.materialize()
        self.assertEqual(self.config.read_bytes(),config)
        self.assertEqual(prep.windows_record(self.state)['nonce'],initial['nonce'])

    def test_existing_authority_and_adoption_are_not_fresh_windows_targets(self):
        prep.publish(self.config,b'{"synthetic":"existing"}')
        self.assertEqual(prep.windows_control('inspect',self.state,self.config),{'mode':'existing'})
        with self.assertRaisesRegex(prep.Refusal,'NO_RELOCATION'):self.reserve()
        self.assertFalse((self.state/'windows-extension.json').exists())

    def test_original_existing_extension_without_config_still_refuses(self):
        old=self.home/'old';old.mkdir(mode=0o700)
        with self.assertRaisesRegex(prep.Refusal,'EXISTING_EXTENSION_WITHOUT_CONFIG'):
            prep.prepare_extension(ROOT,self.state,self.config,old)
        self.assertFalse(self.config.exists())

    def test_recorded_keyed_and_keyless_legacy_paths_are_not_relocated(self):
        for keyed in (True,False):
            with self.subTest(keyed=keyed):
                name='keyed' if keyed else 'keyless'
                state=prep.directory(self.state/name,True)
                old=prep.directory(self.home/('old-'+name),True)
                config=self.home/(name+'.json')
                manifest=json.loads((ROOT/'browser-extension/extension/manifest.json').read_text())
                identity=prep.extension_id(manifest) if keyed else 'a'*32
                if not keyed:manifest.pop('key')
                prep.publish(old/'manifest.json',prep.json_bytes(manifest))
                prep.publish(config,prep.json_bytes({'project_ref':'fixture','root':str(self.home),'port':8765,'extension_id':identity,'token':'s'*48}))
                before=config.read_bytes()
                record=prep.prepare_extension(ROOT,state,config,old)
                self.assertEqual(record['path'],str(old));self.assertEqual(record['extension_id'],identity)
                self.assertEqual('key' in json.loads((old/'manifest.json').read_text()),keyed)
                self.assertEqual(prep.prepare_extension(ROOT,state,config),record)
                self.assertEqual(config.read_bytes(),before)
                self.assertEqual(prep.windows_control('inspect',state,config),{'mode':'existing'})
                with self.assertRaisesRegex(prep.Refusal,'NO_RELOCATION'):
                    prep.windows_control('reserve',state,config,self.target)
                self.assertFalse((state/'windows-extension.json').exists())

    def test_changed_source_wrong_distro_and_unsafe_paths_refuse(self):
        for target in ['relative','C:\\a\\..\\b','\\\\server\\share','C:\\NUL','C:\\trailing.']:
            with self.assertRaises(prep.Refusal):prep.windows_target(target)
        with patch.dict(os.environ,{'BRIDGE_WSL_DISTRO':'Other'}):
            with self.assertRaisesRegex(prep.Refusal,'IDENTITY_UNVERIFIED'):self.reserve()
        self.reserve();self.materialize()
        (self.state/'extension/worker.js').write_text('unknown edit')
        with self.assertRaisesRegex(prep.Refusal,'SOURCE_CHANGED'):
            prep.windows_control('inspect',self.state,self.config)

    def test_stage_and_continue_gate_services_and_preserve_reexec_phase(self):
        # Use the real run_locked placement boundary, with all external preparation
        # and service operations replaced. No actual dependency probe/installer.
        config=self.home/'.config/gpt-agent-bridge/browser-notifications.json'
        self.config=config;self.reserve()
        product=prep.directory(self.state/'product',True);prep.directory(product/'scripts')
        prep.publish(product/'requirements.txt',b'')
        prep.publish(product/'release-manifest.json',b'{}')
        prep.publish(product/'scripts/release-assets.json',b'{"fixture":{"tunnel":{}}}')
        python=product/'.venv/bin/python'
        args=SimpleNamespace(action='prepare',existing_extension=None,windows_phase='stage')
        output=io.StringIO()
        with contextlib.ExitStack() as stack:
            for obj,name,value in [(prep,'SOURCE',product),(prep.sys,'executable',str(python)),
                    (prep,'prepare_copy',lambda *a:None),(prep,'prepare_venv',lambda *a:python),
                    (prep,'select_herdr',lambda:'/fixture/herdr'),(prep,'download',lambda *a:'/fixture/bundle')]:
                stack.enter_context(patch.object(obj,name,value))
            stack.enter_context(patch.object(prep.platform,'machine',return_value='fixture'))
            materialize=prep.prepare_extension
            stack.enter_context(patch.object(prep,'prepare_extension',side_effect=lambda source,*a,**kw:materialize(ROOT,*a,**kw)))
            stack.enter_context(patch.object(prep.subprocess,'run',return_value=SimpleNamespace(returncode=0)))
            stack.enter_context(patch('builtins.input',return_value='yes'))
            service=stack.enter_context(patch.object(prep,'command',side_effect=prep.Refusal('SYNTHETIC_SERVICE_STOP')))
            stack.enter_context(contextlib.redirect_stdout(output))
            prep.run_locked(args,self.home,self.state);service.assert_not_called()
            self.assertIn('publication is pending',output.getvalue())
            args.windows_phase='continue'
            with self.assertRaisesRegex(prep.Refusal,'PUBLICATION_PENDING'):prep.run_locked(args,self.home,self.state)
            service.assert_not_called()
            info=prep.windows_control('inspect',self.state,self.config)
            prep.windows_control('confirm',self.state,self.config,proof=info['proof'])
            with self.assertRaisesRegex(prep.Refusal,'SYNTHETIC_SERVICE_STOP'):prep.run_locked(args,self.home,self.state)
            self.assertEqual(service.call_args.args[0][:2],['sudo','python3'])
            self.assertIn(self.target,output.getvalue())
            args.windows_phase='stage'
            with patch.object(prep.sys,'executable','/fixture/other-python'),patch.object(prep.os,'execv',side_effect=OSError('synthetic exec')) as execute:
                with self.assertRaises(OSError):prep.run_locked(args,self.home,self.state)
                self.assertEqual(execute.call_args.args[1][-2:],['--windows-phase','stage'])

    def test_status_and_credentials_do_not_enter_windows_publication(self):
        with patch.object(prep,'windows_record',side_effect=AssertionError('not a preparation action')):
            with contextlib.redirect_stdout(io.StringIO()):prep.run_locked(SimpleNamespace(action='status',existing_extension=None),self.home,self.state)
            with patch.object(prep,'replace_tunnel_credentials') as credentials,patch('builtins.input',return_value='no'):
                prep.run_locked(SimpleNamespace(action='credentials',existing_extension=None),self.home,self.state)
                credentials.assert_called_once()

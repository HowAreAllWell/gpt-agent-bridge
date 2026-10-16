"""First-use paths and distro choice; no real WSL, browser or service execution."""
import contextlib
import base64
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tests.test_preparation import ROOT, prep

POWERSHELL=shutil.which('pwsh') or shutil.which('powershell.exe')


class WindowsEntry(unittest.TestCase):
    def powershell(self,code):
        # Encoded input also works with Windows PowerShell 5.1 from WSL, with no
        # script files/profile/launcher execution or Linux-path conversion needed.
        code="$ProgressPreference='SilentlyContinue'; [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding;\n"+code
        encoded=base64.b64encode(code.encode('utf-16le')).decode('ascii')
        return subprocess.run([POWERSHELL,'-NoProfile','-NonInteractive','-EncodedCommand',encoded],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=30)

    def test_every_runtime_call_is_pinned_after_selection_and_before_writes(self):
        script=(ROOT/'Start-Bridge.ps1').read_text()
        calls=[line for line in script.splitlines() if '& wsl.exe ' in line]
        self.assertEqual(sum('--list ' in line for line in calls),2)
        runtime=[line for line in calls if '--list ' not in line]
        self.assertEqual(len(runtime),7)
        for line in runtime:self.assertIn('& wsl.exe --distribution $distro --exec ',line)
        self.assertLess(script.index('$distro = Select-BridgeWslDistro'),script.index('sudo apt-get'))
        self.assertLess(script.index('$actual = @('),script.index('$copy ='))
        self.assertIn('"BRIDGE_WSL_DISTRO=$distro" python3',script)
        self.assertNotRegex(script,r'--(?:set-default|set-version|shutdown|terminate)\b')

    @unittest.skipUnless(POWERSHELL,'PowerShell unavailable; no install attempted')
    def test_powershell_syntax_without_executing_launcher(self):
        source=(ROOT/'Start-Bridge.ps1').read_text().replace("'","''")
        code=f"$tokens=$null; $errors=$null; [void][System.Management.Automation.Language.Parser]::ParseInput('{source}',[ref]$tokens,[ref]$errors); if ($errors.Count) {{ $errors | Out-String | Write-Output; exit 1 }}"
        result=self.powershell(code)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

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

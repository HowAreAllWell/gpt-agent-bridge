"""First-use paths and distro choice; no real WSL, browser or service execution."""
import contextlib
import ast
import base64
import importlib.util
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

# Importing test_preparation reads the real extension connection. Load only the
# preparer's stdlib-only definitions; fixture methods opt into any later IO.
ROOT=Path(__file__).resolve().parents[1]
_spec=importlib.util.spec_from_file_location('windows_preparation_fixture',ROOT/'scripts/prepare-bridge.py')
prep=importlib.util.module_from_spec(_spec)
exec(compile((ROOT/'scripts/prepare-bridge.py').read_bytes(),_spec.origin,'exec'),prep.__dict__)

POWERSHELL=shutil.which('powershell.exe') or shutil.which('pwsh')


def synthetic_extension_source(source):
    """Only these public fixture bytes exist; never inspect a checkout template."""
    template=source/'browser-extension/extension'
    for path in (source,source/'browser-extension',template):path.mkdir(mode=0o700,exist_ok=True)
    for name,data in {'manifest.json':b'{"manifest_version":3,"key":"Zml4dHVyZQ=="}',
                      'worker.js':b'// synthetic worker\n','projects.js':b'// synthetic projects\n'}.items():
        path=template/name;path.write_bytes(data);path.chmod(0o600)
    return source


def notification_reader():
    # Actual validation without importing HTTP routes or consulting Path.home().
    tree=ast.parse((ROOT/'src/gpt_agent_bridge/browser_notifications.py').read_text())
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='BrowserNotifications')
    cls.body=[n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name in ('validate_config','read_config')]
    namespace=dict(Path=Path,json=json,os=os,re=re,stat=stat)
    exec(compile(ast.Module(body=[cls],type_ignores=[]),'<actual config reader>','exec'),namespace)
    return namespace['BrowserNotifications'].read_config


@contextlib.contextmanager
def fixture_preparer(base):
    class FixturePath(type(Path())):
        def stat(path,*,follow_symlinks=True):
            if path in base.parents:
                return os.stat_result((stat.S_IFDIR|0o700,0,0,1,os.getuid(),os.getgid(),0,0,0,0))
            if not path.is_relative_to(base):raise AssertionError('outside temporary fixture: '+str(path))
            return super().stat(follow_symlinks=follow_symlinks)
    with contextlib.ExitStack() as stack:
        stack.enter_context(patch.object(prep,'Path',FixturePath))
        for obj,name in ((prep,'command'),(prep,'load_script'),(prep.subprocess,'run'),
                         (prep.os,'execv'),(prep.urllib.request,'urlopen'),(prep.getpass,'getpass')):
            stack.enter_context(patch.object(obj,name,side_effect=AssertionError('external boundary forbidden: '+name)))
        stack.enter_context(patch.object(prep.pwd,'getpwuid',return_value=SimpleNamespace(pw_dir=str(base/'home'),pw_name='fixture')))
        stack.enter_context(patch.object(prep.platform,'release',return_value='Linux'))
        stack.enter_context(patch('builtins.input',side_effect=AssertionError('unexpected prompt')))
        yield


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
        runtime=[line for line in calls if '--list ' not in line]
        self.assertTrue(runtime)
        for line in runtime:self.assertRegex(line,r'& wsl.exe --distribution \$[Dd]istro --exec ')
        self.assertLess(script.index('$distro = Select-BridgeWslDistro'),script.index('sudo apt-get'))
        self.assertLess(script.index('$actual = @('),script.index('$copy ='))
        self.assertIn('"BRIDGE_WSL_DISTRO=$distro" python3',script)
        self.assertNotRegex(script,r'--(?:set-default|set-version|shutdown|terminate)\b')

    @unittest.skipUnless(POWERSHELL,'PowerShell unavailable; status AST fixture not run')
    def test_status_inventory_never_executes_or_starts_a_distro(self):
        # Parse the launcher as data. Run only the isolated status clause with
        # fake inventory/commands; never execute the launcher or real wsl.exe.
        source=(ROOT/'Start-Bridge.ps1').read_text().replace("'","''")
        code=r"""$ErrorActionPreference='Stop'; Set-StrictMode -Version Latest
$tokens=$null; $errors=$null
$tree=[System.Management.Automation.Language.Parser]::ParseInput('SOURCE',[ref]$tokens,[ref]$errors)
if ($errors.Count) { throw 'syntax invalid' }
$route=@($tree.EndBlock.Statements | Where-Object {
    $_ -is [System.Management.Automation.Language.IfStatementAst] -and
    $_.Clauses[0].Item1.Extent.Text -ceq '$Action -eq ''status'''
})
if ($route.Count -ne 1) { throw 'status needs an early independent route' }
$body=$route[0].Clauses[0].Item2
if ($body.Statements[-1] -isnot [System.Management.Automation.Language.ReturnStatementAst]) { throw 'status falls through' }
$calls=$body.FindAll({param($n) $n -is [System.Management.Automation.Language.CommandAst]},$true)
foreach ($call in $calls) {
    if ($call.GetCommandName() -notin @('Get-Command','Write-Host','wsl.exe')) { throw 'status has a write/runtime/selection boundary' }
    if ($call.GetCommandName() -eq 'wsl.exe' -and $call.Extent.Text -cnotin @('wsl.exe --list --verbose 2>$null','& wsl.exe --list --verbose 2>$null')) { throw 'status may enter a distro' }
}
if ($route[0].Extent.StartOffset -gt ('SOURCE').IndexOf('if (-not (Get-Command wsl.exe')) { throw 'status enters bootstrap' }
function Get-Command { $script:available }
function wsl.exe {
    if (($args -join '|') -cne '--list|--verbose') { throw 'real WSL/runtime forbidden' }
    $script:queries++
    if ($script:throwQuery) { throw 'SYNTHETIC_RAW_FAILURE_NOT_FOR_DISPLAY' }
    $global:LASTEXITCODE=$script:result; $script:rows
}
function Write-Host { param($Object) $script:messages+= [string]$Object }
$action='status'
foreach ($case in @('unavailable','empty','stopped','running','unsupported','failed','exception')) {
    $script:throwQuery=$case -eq 'exception'
    $script:available=if ($case -eq 'unavailable') {$null} else {'fake-wsl'}
    $script:rows=switch ($case) {
        'stopped' { '  NAME STATE VERSION'; '* Fixture 旧 Stopped 2' }
        'running' { '  NAME STATE VERSION'; '* Fixture 旧 Running 2' }
        'unsupported' { 'unrecognized inventory (no backend claim)' }
        default { @() }
    }
    $script:result=if ($case -eq 'failed') {1} else {0}
    $script:queries=0; $script:messages=@()
    $text=$body.Extent.Text
    & ([ScriptBlock]::Create($text.Substring(1,$text.Length-2)))
    if ($script:queries -ne $(if ($case -eq 'unavailable') {0} else {1})) { throw 'inventory repeated' }
    $message=$script:messages -join '|'
    if ($message -notmatch 'not checked|not inspected') { throw 'backend status overstated' }
    if ($message -notmatch 'not started|Nothing was started') { throw 'start behavior unclear' }
    if ($case -eq 'stopped' -and $message -notmatch 'Stopped') { throw 'stopped state lost' }
    if ($case -eq 'running' -and $message -notmatch 'Running') { throw 'running state lost' }
    if ($message -match 'Bridge: active|Tunnel: active') { throw 'backend status invented' }
    if ($message -match 'SYNTHETIC_RAW_FAILURE') { throw 'query exception leaked' }
}
'read-only status fixture passed'
""".replace('SOURCE',source)
        result=self.powershell(code)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('read-only status fixture passed',result.stdout)

    def test_windows_publication_guards_without_native_api_execution(self):
        # Source contracts only: native ACL/mutex/publication acceptance is separate.
        script=(ROOT/'Start-Bridge.ps1').read_text()
        publish=script.split('function Publish-BridgeWindowsFiles {',1)[1].split('function Get-BridgeWindowsMetadata {',1)[0]
        marker=script.split('function Assert-BridgeDeployment {',1)[1].split('function Publish-BridgeWindowsExtension {',1)[0]
        for field in ('target','nonce','proof'):
            self.assertIn('$saved.'+field+' -cne $Info.'+field,marker)
        self.assertIn('WINDOWS_DESTINATION_CHANGED',marker)
        for refusal in ('WINDOWS_RECEIPT_INVALID','WINDOWS_DESTINATION_BUSY',
                        'WINDOWS_PUBLICATION_AMBIGUOUS','WINDOWS_CONFIRMED_DESTINATION_MISSING'):
            self.assertIn(refusal,publish)
        self.assertLess(publish.index('Assert-BridgeWindowsParent $target'),publish.index('$folder.Create'))
        self.assertLess(publish.index('Assert-BridgeDeployment $stage $Info $true'),publish.index('[IO.Directory]::Move'))
        self.assertIn("'CreateNew','Write','None'",publish)
        self.assertIn('$mutex.ReleaseMutex()',publish)

    @unittest.skipUnless(POWERSHELL,'PowerShell unavailable; no install attempted')
    def test_powershell_syntax_without_executing_launcher(self):
        source=(ROOT/'Start-Bridge.ps1').read_text().replace("'","''")
        code=f"$tokens=$null; $errors=$null; [void][System.Management.Automation.Language.Parser]::ParseInput('{source}',[ref]$tokens,[ref]$errors); if ($errors.Count) {{ $errors | Out-String | Write-Output; exit 1 }}"
        result=self.powershell(code)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    @unittest.skipUnless(POWERSHELL,'PowerShell unavailable; no install attempted')
    def test_metadata_transport_pins_distro_and_preserves_extra_arguments(self):
        script=(ROOT/'Start-Bridge.ps1').read_text()
        functions=script[script.index('function Get-BridgeWindowsMetadata'):script.index("if (-not (Get-Command wsl.exe")]
        target="D:\\Fixture 旧 O'Brien\\extension"
        encoded=base64.b64encode(target.encode('utf-8')).decode('ascii')
        code=r"""$ErrorActionPreference='Stop'; Set-StrictMode -Version Latest
FUNCTIONS
function wsl.exe { $script:captured=@($args); $global:LASTEXITCODE=0; '{"mode":"fresh"}' }
$target='TARGET'
$encoded=[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($target))
if ($encoded -cne 'ENCODED') { throw 'target encoding changed' }
$result=Get-BridgeWindowsMetadata "Fixture O'Brien 旧" "/fixture/旧 O'Brien/script.py" 'reserve' @('--windows-target-base64',$encoded)
if($result.mode -ne 'fresh'){throw 'metadata result invalid'}
if(($script:captured -join '|') -cne "--distribution|Fixture O'Brien 旧|--exec|env|BRIDGE_WSL_DISTRO=Fixture O'Brien 旧|python3|-B|/fixture/旧 O'Brien/script.py|reminders|--windows-phase|reserve|--windows-target-base64|$encoded"){throw 'metadata argv changed'}
$proof='synthetic_nonce_bound_proof_' + ('a'*64)
$null=Get-BridgeWindowsMetadata "Fixture O'Brien 旧" "/fixture/旧 O'Brien/script.py" 'confirm' @('--windows-proof',$proof)
if(($script:captured -join '|') -cne "--distribution|Fixture O'Brien 旧|--exec|env|BRIDGE_WSL_DISTRO=Fixture O'Brien 旧|python3|-B|/fixture/旧 O'Brien/script.py|reminders|--windows-phase|confirm|--windows-proof|$proof"){throw 'confirmation proof changed'}
'metadata fixture passed'
""".replace('FUNCTIONS',functions).replace('TARGET',target.replace("'","''")).replace('ENCODED',encoded)
        result=self.powershell(code)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('metadata fixture passed',result.stdout)

    @unittest.skipUnless(POWERSHELL,'PowerShell unavailable; metadata failure fixture not run')
    def test_metadata_failure_stops_without_publish_or_prepare_fallback(self):
        script=(ROOT/'Start-Bridge.ps1').read_text()
        function=script[script.index('function Get-BridgeWindowsMetadata'):script.index("if (-not (Get-Command wsl.exe")]
        code=r"""$ErrorActionPreference='Stop'; Set-StrictMode -Version Latest
FUNCTION
$script:calls=0; $script:published=$false
function wsl.exe { $script:calls++; $global:LASTEXITCODE=2; 'SYNTHETIC_RAW_OUTPUT_NOT_FOR_DISPLAY' }
function Publish-BridgeWindowsExtension { $script:published=$true }
$caught=$false
try {
    $info=Get-BridgeWindowsMetadata 'Fixture' '/fixture/script.py' 'inspect'
    Publish-BridgeWindowsExtension $info 'Fixture'
} catch {
    $caught=$true
    if ($_.Exception.Message -notlike 'WINDOWS_REMINDERS_STOPPED:*') { throw 'unexpected error' }
    if ($_.Exception.Message -match 'SYNTHETIC_RAW_OUTPUT') { throw 'raw output leaked' }
}
if (-not $caught -or $script:published -or $script:calls -ne 1) { throw 'failure retried or published' }
'metadata failure fixture passed'
""".replace('FUNCTION',function)
        result=self.powershell(code)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('metadata failure fixture passed',result.stdout)
        self.assertNotIn('SYNTHETIC_RAW_OUTPUT',result.stdout+result.stderr)

    @unittest.skipUnless(POWERSHELL,'PowerShell unavailable; launcher routing AST not checked')
    def test_optional_reminders_routing_without_executing_launcher(self):
        source=(ROOT/'Start-Bridge.ps1').read_text().replace("'","''")
        code=r"""$ErrorActionPreference='Stop'; Set-StrictMode -Version Latest
$source='SOURCE'
$tokens=$null; $errors=$null
$tree=[System.Management.Automation.Language.Parser]::ParseInput($source,[ref]$tokens,[ref]$errors)
if ($errors.Count) { throw 'launcher syntax invalid' }
$action=@($tree.ParamBlock.Parameters | Where-Object { $_.Name.VariablePath.UserPath -eq 'Action' })
if ($action.Count -ne 1 -or $action[0].DefaultValue.Value -ne 'prepare') { throw 'core default changed' }
$routes=@($tree.EndBlock.Statements | Where-Object {
    $_ -is [System.Management.Automation.Language.IfStatementAst] -and
    $_.Clauses[0].Item1.Extent.Text -match '^\$Action\s+-eq\s+''reminders''$'
})
if ($routes.Count -ne 1 -or $null -ne $routes[0].ElseClause) { throw 'reminders must be a separate action' }
$body=$routes[0].Clauses[0].Item2
if ($body.Statements[-1] -isnot [System.Management.Automation.Language.ReturnStatementAst]) { throw 'reminders falls through to core' }
foreach ($core in @('sudo apt-get','$copy =','python3 "$release/scripts/prepare-bridge.py" $Action')) {
    if ($source.IndexOf($core) -lt $body.Extent.EndOffset) { throw 'reminders enters core bootstrap/copy' }
}
$commands=$tree.FindAll({param($node) $node -is [System.Management.Automation.Language.CommandAst]},$true)
foreach ($call in $commands) {
    $extensionCall=$call.GetCommandName() -in @('Get-BridgeWindowsMetadata','Publish-BridgeWindowsExtension','Get-BridgeWindowsTarget','Assert-BridgeWindowsParent')
    $extensionWsl=$call.GetCommandName() -eq 'wsl.exe' -and $call.Extent.Text -match 'reminders|--windows-phase'
    $extensionPrompt=$call.GetCommandName() -eq 'Read-Host' -and $call.Extent.Text -match 'Private Windows extension folder|Prepare the private extension'
    if (-not ($extensionCall -or $extensionWsl -or $extensionPrompt)) { continue }
    $node=$call.Parent; $inFunction=$false
    while ($null -ne $node) {
        if ($node -is [System.Management.Automation.Language.FunctionDefinitionAst]) { $inFunction=$true; break }
        $node=$node.Parent
    }
    if ($inFunction) { continue }
    if ($call.Extent.StartOffset -lt $body.Extent.StartOffset -or $call.Extent.EndOffset -gt $body.Extent.EndOffset) { throw 'core/status/credentials publish extension' }
}
$text=$body.Extent.Text
$locator=$text.IndexOf('pwd.getpwuid(os.getuid()).pw_dir')
$inspect=$text.IndexOf('Get-BridgeWindowsMetadata $distro $script ''inspect''')
if ($locator -lt 0 -or $inspect -lt $locator -or $inspect -gt $text.IndexOf('Read-Host')) { throw 'prepared product must be checked before destination prompts' }
if (-not $text.Contains('product/scripts/prepare-bridge.py') -or $text -match '\$script prepare|sudo|apt-get|\$copy') { throw 'reminders bootstraps core' }
if ($text -match '--user\b' -or -not $text.Contains('pwd.getpwuid(os.getuid()).pw_dir')) { throw 'prepared product user differs from selected distro default user' }
foreach ($phase in @('inspect','reserve','confirm')) {
    if (-not $text.Contains('Get-BridgeWindowsMetadata $distro $script '''+$phase+'''')) { throw 'metadata phase missing' }
}
if (-not $text.Contains("'--windows-target-base64',"+'$encoded') -or -not $text.Contains("'--windows-proof',"+'$info.proof')) { throw 'pairing arguments changed' }
if (-not $text.Contains('reminders --windows-phase stage') -or -not $text.Contains('reminders --windows-phase continue')) { throw 'reminder stages missing' }
if (-not $source.Contains('if ($Action -eq ''reminders'') { throw ''Run Start-Bridge.ps1 prepare first')) { throw 'reminders can bootstrap missing WSL' }
'routing AST fixture passed'
""".replace('SOURCE',source)
        result=self.powershell(code)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('routing AST fixture passed',result.stdout)

    def choice(self,names,details,answer):
        # Only the exact pure selection functions execute, never the launcher or wsl.exe.
        script=(ROOT/'Start-Bridge.ps1').read_text()
        functions=script[script.index('function Get-BridgeWsl2Distros'):script.index('function Get-BridgeDosDevice')]
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

    def test_core_reaches_service_boundary_without_reminders_using_passwd_home(self):
        self.check_main_boundary(reminders=False)

    def test_reminder_handoff_failure_never_controls_services_using_passwd_home(self):
        self.check_main_boundary(reminders=True)

    def check_main_boundary(self,reminders):
        with tempfile.TemporaryDirectory() as tmp, fixture_preparer(Path(tmp)):
            home=Path(tmp)/'home';home.mkdir(mode=0o700)
            state=prep.directory(home/'.local/share/gpt-agent-bridge',True)
            product=synthetic_extension_source(state/'product')
            prep.publish(product/'release-manifest.json',b'{}')
            prep.publish(product/'scripts/release-assets.json',b'{"fixture":{"tunnel":{}}}')
            python=product/'.venv/bin/python';output=io.StringIO()
            with contextlib.ExitStack() as stack:
                for obj,name,value in [(prep,'SOURCE',product),(prep.sys,'executable',str(python)),
                        (prep,'notification_config',notification_reader()),
                        (prep,'reminder_runtime',lambda p,h:python)]:
                    stack.enter_context(patch.object(obj,name,value))
                stack.enter_context(patch.dict(os.environ,{'HOME':'/wrong/home','WSL_DISTRO_NAME':'Fixture','BRIDGE_WSL_DISTRO':'Fixture'},clear=True))
                stack.enter_context(patch.object(prep.sys,'argv',['prepare','reminders' if reminders else 'prepare']))
                if reminders:
                    stack.enter_context(patch.object(prep,'extension_unc',side_effect=prep.Refusal('WSL_PATH_CONVERSION_FAILED')))
                    stack.enter_context(patch('builtins.input',return_value='yes'))
                    service=stack.enter_context(patch.object(prep,'command',side_effect=AssertionError('reminders cannot control services')))
                    code='WINDOWS_EXTENSION_PATH_UNVERIFIED'
                else:
                    for name in ('windows_record','windows_control','notification_config','prepare_extension','extension_handoff'):
                        stack.enter_context(patch.object(prep,name,side_effect=AssertionError('core touched optional reminders')))
                    stack.enter_context(patch.object(prep,'prepare_copy'))
                    stack.enter_context(patch.object(prep,'prepare_venv',return_value=python))
                    stack.enter_context(patch.object(prep,'environment_ready',return_value=True))
                    stack.enter_context(patch.object(prep,'select_herdr',return_value='/fixture/herdr'))
                    stack.enter_context(patch.object(prep,'download',return_value=state/'bundle'))
                    stack.enter_context(patch.object(prep.platform,'machine',return_value='fixture'))
                    service=stack.enter_context(patch.object(prep,'command',side_effect=prep.Refusal('SYNTHETIC_CORE_STOP')))
                    code='SYNTHETIC_CORE_STOP'
                with contextlib.redirect_stdout(output),self.assertRaisesRegex(prep.Refusal,code):prep.main()
                if reminders:service.assert_not_called()
                else:
                    service.assert_called_once()
                    self.assertEqual(service.call_args.args[0][:4],['sudo','python3',product/'scripts/prepare-system.py','bridge'])
            config=home/'.config/gpt-agent-bridge/browser-notifications.json'
            if reminders:
                receipt=json.loads((state/'extension.json').read_text())
                self.assertEqual(receipt['path'],str(state/'extension'))
                self.assertIn(receipt['path'],output.getvalue())
                self.assertNotIn(json.loads(config.read_text())['token'],output.getvalue())
                self.assertIn('Windows extension path: unavailable/unverified',output.getvalue())
            else:
                self.assertFalse(config.exists());self.assertFalse((state/'extension').exists())
                self.assertFalse((state/'windows-extension.json').exists())
            self.assertNotIn('/wrong/home',output.getvalue())


class WindowsPreparation(unittest.TestCase):
    """Real materialization with synthetic config IO; no HTTP dependency or live config."""
    target="D:\\Fixture 旧 O'Brien\\extension"

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        base=Path(self.tmp.name)
        stack=contextlib.ExitStack();self.addCleanup(stack.close)
        stack.enter_context(fixture_preparer(base))
        self.source=synthetic_extension_source(base/'source')
        self.home=base/'home';self.home.mkdir(mode=0o700)
        self.state=prep.directory(self.home/'state',True)
        self.config=self.home/'config/browser-notifications.json'
        stack.enter_context(patch.dict(os.environ,{'WSL_DISTRO_NAME':'Fixture','BRIDGE_WSL_DISTRO':'Fixture'},clear=True))
        stack.enter_context(patch.object(prep,'notification_config',notification_reader()))
        stack.enter_context(patch.object(prep,'extension_unc',side_effect=lambda p:'\\\\wsl.localhost\\Fixture'+p.replace('/','\\')))

    def reserve(self):return prep.windows_control('reserve',self.state,self.config,self.target)

    def materialize(self):
        record=prep.prepare_extension(self.source,self.state,self.config)
        prep.windows_staged(self.state,record)
        return record

    @contextlib.contextmanager
    def run_fixture(self):
        # Trust/runtime observation is a boundary stub; pairing/file IO stays real.
        product=prep.directory(self.state/'product',True)
        python=product/'.venv/bin/python';output=io.StringIO()
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(prep,'SOURCE',product))
            stack.enter_context(patch.object(prep.sys,'executable',str(python)))
            stack.enter_context(patch.object(prep,'reminder_runtime',return_value=python))
            for name in ('prepare_copy','prepare_venv','select_herdr','download'):
                stack.enter_context(patch.object(prep,name,side_effect=AssertionError('reminders cannot prepare core')))
            actual=prep.prepare_extension
            materialize=stack.enter_context(patch.object(prep,'prepare_extension',side_effect=lambda source,*a,**kw:actual(self.source,*a,**kw)))
            stack.enter_context(patch('builtins.input',return_value='yes'))
            service=stack.enter_context(patch.object(prep,'command',side_effect=AssertionError('reminders cannot control services')))
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

    def test_inconsistent_windows_authorities_cannot_rewrite_generation(self):
        base=self.home
        cases=[('pending-only','token'),('active','token')]+[
            ('pending',field) for field in ('token','extension_id','port','legacy_identity')]
        for index,(authority,field) in enumerate(cases):
            with self.subTest(authority=authority,field=field):
                self.home=base/str(index);self.home.mkdir(mode=0o700)
                self.state=prep.directory(self.home/'state',True)
                self.generation(confirmed=True)
                pending=self.state/'notification-pending.json'
                path=self.config if authority=='active' else pending
                changed=json.loads(path.read_bytes())
                if field=='token':changed[field]='different_synthetic_token_'+'x'*32
                elif field=='extension_id':changed[field]='a'*32 if changed[field]!='a'*32 else 'b'*32
                elif field=='port':changed[field]=8766
                else:
                    changed={k:changed[k] for k in ('extension_id','token','port')}
                    changed.update(project_ref='synthetic',root=str(self.home))
                path.write_bytes(prep.json_bytes(changed))
                if authority=='pending-only':self.config.unlink()
                info=prep.windows_control('inspect',self.state,self.config)
                with self.run_fixture() as (materialize,service,output):
                    before=self.snapshot()
                    for phase in ('stage','continue','continue'):
                        with self.assertRaisesRegex(prep.Refusal,'^WINDOWS_PAIRING_AUTHORITY_INCONSISTENT$') as error:
                            prep.run_locked(SimpleNamespace(action='reminders',existing_extension=None,windows_phase=phase),self.home,self.state)
                        self.assertEqual(self.snapshot(),before)
                        self.assertEqual(prep.windows_control('inspect',self.state,self.config),info)
                        self.assertNotIn(changed['token'],str(error.exception)+output.getvalue())
                    materialize.assert_not_called();service.assert_not_called()

    def test_inconsistent_partial_windows_generation_refuses_before_writes(self):
        base=self.home
        for early in (True,False):
            with self.subTest(before_connection=early):
                self.home=prep.directory(base/('early' if early else 'late'),True)
                self.state=prep.directory(self.home/'state',True)
                self.config=self.home/'.config/gpt-agent-bridge/browser-notifications.json'
                if early:self.generation(partial=True)
                else:
                    self.reserve();prep.prepare_extension(self.source,self.state,self.config)
                    self.config.unlink()  # Surviving connection/receipt anchor the sole backup.
                self.assertIsNone(prep.windows_record(self.state)['spec'])
                pending=self.state/'notification-pending.json'
                changed=json.loads(pending.read_bytes());changed['token']='different_synthetic_token_'+'x'*32
                pending.write_bytes(prep.json_bytes(changed))
                info=prep.windows_control('inspect',self.state,self.config)
                with self.run_fixture() as (materialize,service,output):
                    before=self.snapshot()
                    with self.assertRaisesRegex(prep.Refusal,'^WINDOWS_PAIRING_AUTHORITY_INCONSISTENT$'):
                        prep.run_locked(SimpleNamespace(action='reminders',existing_extension=None,windows_phase='stage'),self.home,self.state)
                    self.assertEqual(self.snapshot(),before)
                    self.assertEqual(prep.windows_control('inspect',self.state,self.config),info)
                    materialize.assert_not_called();service.assert_not_called()

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
                        prep.run_locked(SimpleNamespace(action='reminders',existing_extension=None,windows_phase='stage'),self.home,self.state)
                    self.assertEqual(self.snapshot(),before)
                    materialize.assert_not_called();service.assert_not_called()

    def test_missing_windows_pairing_authority_refuses_before_any_generation_write(self):
        self.generation(confirmed=True)
        self.config.unlink();(self.state/'notification-pending.json').unlink()
        info=prep.windows_control('inspect',self.state,self.config)
        with self.run_fixture() as (materialize,service,output):
            before=self.snapshot()
            for phase in ('stage','continue','continue'):
                args=SimpleNamespace(action='reminders',existing_extension=None,windows_phase=phase)
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
                    prep.run_locked(SimpleNamespace(action='reminders',existing_extension=None,windows_phase='stage'),self.home,self.state)
                self.assertEqual(self.snapshot(),before)
            materialize.assert_not_called();service.assert_not_called()

    def test_matching_surviving_windows_authority_recovers_same_confirmed_generation(self):
        base=self.home
        for survivor in ('active','pending'):
            with self.subTest(survivor=survivor):
                self.home=base/survivor;self.home.mkdir(mode=0o700)
                self.state=prep.directory(self.home/'state',True)
                self.generation(confirmed=True)
                missing=self.state/'notification-pending.json' if survivor=='active' else self.config
                original=missing.read_bytes();missing.unlink()
                info=prep.windows_control('inspect',self.state,self.config)
                with self.run_fixture() as (materialize,service,output):
                    before=self.snapshot()
                    prep.run_locked(SimpleNamespace(action='reminders',existing_extension=None,windows_phase='continue'),self.home,self.state)
                    self.assertEqual(prep.digest(missing.read_bytes()),prep.digest(original))
                    after=self.snapshot();after.pop(str(missing.relative_to(self.home)))
                    self.assertEqual(after,before)
                    self.assertEqual(prep.windows_control('inspect',self.state,self.config),info)
                    materialize.assert_called_once();service.assert_not_called()
                    self.assertNotIn(json.loads(original)['token'],output.getvalue())

    def test_pending_only_interrupted_windows_generation_resumes_before_publication(self):
        self.generation(partial=True)
        original=self.config.read_bytes();self.config.unlink()
        reserved=prep.windows_record(self.state)
        self.assertFalse((self.state/'extension/connection.js').exists())
        with self.run_fixture() as (materialize,service,output):
            prep.run_locked(SimpleNamespace(action='reminders',existing_extension=None,windows_phase='stage'),self.home,self.state)
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
                        with self.assertRaises(ValueError) as error:
                            prep.run_locked(SimpleNamespace(action='reminders',existing_extension=None,windows_phase='continue'),self.home,self.state)
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
            prep.prepare_extension(self.source,self.state,self.config,old)
        self.assertFalse(self.config.exists())

    def test_recorded_keyed_and_keyless_legacy_paths_are_not_relocated(self):
        for keyed in (True,False):
            with self.subTest(keyed=keyed):
                name='keyed' if keyed else 'keyless'
                state=prep.directory(self.state/name,True)
                old=prep.directory(self.home/('old-'+name),True)
                config=self.home/(name+'.json')
                manifest=json.loads((self.source/'browser-extension/extension/manifest.json').read_text())
                identity=prep.extension_id(manifest) if keyed else 'a'*32
                if not keyed:manifest.pop('key')
                prep.publish(old/'manifest.json',prep.json_bytes(manifest))
                prep.publish(config,prep.json_bytes({'project_ref':'fixture','root':str(self.home),'port':8765,'extension_id':identity,'token':'s'*48}))
                before=config.read_bytes()
                record=prep.prepare_extension(self.source,state,config,old)
                self.assertEqual(record['path'],str(old));self.assertEqual(record['extension_id'],identity)
                self.assertEqual('key' in json.loads((old/'manifest.json').read_text()),keyed)
                self.assertEqual(prep.prepare_extension(self.source,state,config),record)
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

    def test_reminder_phases_never_control_services_and_preserve_reexec_action(self):
        self.config=self.home/'.config/gpt-agent-bridge/browser-notifications.json'
        self.reserve()
        args=SimpleNamespace(action='reminders',existing_extension=None,windows_phase='stage')
        with self.run_fixture() as (materialize,service,output):
            for action in ('prepare','status','credentials'):
                with self.assertRaisesRegex(prep.Refusal,'WINDOWS_PHASE_INVALID'):
                    prep.run_locked(SimpleNamespace(action=action,existing_extension=None,windows_phase='stage'),self.home,self.state)
            prep.run_locked(args,self.home,self.state)
            self.assertIn('waiting for Windows publication',output.getvalue())
            args.windows_phase='continue'
            with self.assertRaisesRegex(prep.Refusal,'PUBLICATION_PENDING'):prep.run_locked(args,self.home,self.state)
            info=prep.windows_control('inspect',self.state,self.config)
            prep.windows_control('confirm',self.state,self.config,proof=info['proof'])
            prep.run_locked(args,self.home,self.state)
            self.assertIn(self.target,output.getvalue())
            self.assertEqual(materialize.call_count,2);service.assert_not_called()
            args.windows_phase='stage'
            product=self.state/'product';python=product/'.venv/bin/python'
            with patch.object(prep.sys,'executable','/fixture/other-python'),patch.object(prep.os,'execv',side_effect=OSError('synthetic exec')) as execute:
                with self.assertRaises(OSError):prep.run_locked(args,self.home,self.state)
                self.assertEqual(execute.call_args.args[1],[str(python),'-B',str(product/'scripts/prepare-bridge.py'),'reminders','--windows-phase','stage'])
            service.assert_not_called()

    def test_status_and_credentials_do_not_enter_windows_publication(self):
        with patch.object(prep,'windows_record',side_effect=AssertionError('not a preparation action')), \
                patch.object(prep,'status_service',return_value=None), \
                patch.object(prep,'status_file',return_value='absent'):
            with contextlib.redirect_stdout(io.StringIO()):prep.run_locked(SimpleNamespace(action='status',existing_extension=None),self.home,self.state)
            with patch.object(prep,'replace_tunnel_credentials') as credentials,patch('builtins.input',return_value='no'):
                prep.run_locked(SimpleNamespace(action='credentials',existing_extension=None),self.home,self.state)
                credentials.assert_called_once()

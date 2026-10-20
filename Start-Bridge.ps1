# Run this reviewed file, not a remotely piped script. Explicitly select one WSL2 distro.
[CmdletBinding()]
param([ValidateSet('prepare','reminders','status','credentials')][string]$Action = 'prepare',
      [string]$ExtensionDirectory)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ($Action -eq 'status') {
    # Inventory only: even a read-only Linux command would start a stopped distro.
    if ($null -eq (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
        Write-Host 'WSL is unavailable. Linux services were not inspected. Nothing was started or installed.'
        return
    }
    try {
        $inventory = @(& wsl.exe --list --verbose 2>$null)
        if ($LASTEXITCODE -ne 0) { throw 'WSL inventory failed' }
    } catch {
        Write-Host 'WSL inventory unavailable. Linux services were not inspected. Nothing was started or installed.'
        return
    }
    Write-Host 'WSL inventory only (no Linux user selected; no distro was started):'
    if ($inventory.Count -eq 0) { Write-Host 'No WSL distributions reported.' }
    foreach ($row in $inventory) { Write-Host (($row -replace "`0", '').TrimEnd()) }
    Write-Host 'Bridge/Tunnel and Web connection: not checked. Nothing was started or installed.'
    Write-Host 'For Linux service status, run ./prepare status from this updated release in an already running Linux terminal.'
    return
}

function Get-BridgeWsl2Distros {
    param([string[]]$Names, [string[]]$Details)
    if (@($Names | Sort-Object -Unique).Count -ne $Names.Count) { throw 'Ambiguous WSL distro names.' }
    foreach ($name in $Names) {
        if ($name -notmatch '^[^\\/:*?"<>|\x00-\x1f]+$' -or $name.StartsWith('-')) { throw 'Unsupported WSL distro name.' }
    }
    $versions = @{}
    foreach ($row in $Details) {
        # Associate each row with the longest exact inventory name first:
        # "Ubuntu Dev" must never count as a second row for "Ubuntu".
        $candidates = @($Names | Where-Object { $row -cmatch ('^\s*\*?\s*' + [regex]::Escape($_) + '(?=\s|$)') } | Sort-Object Length -Descending)
        if ($candidates.Count -eq 0) { continue } # localized heading/blank line
        $name = $candidates[0]
        $pattern = '^\s*\*?\s*' + [regex]::Escape($name) + '\s+.+?\s+(?<version>[12])\s*$'
        $match = [regex]::Match($row, $pattern)
        if (-not $match.Success -or $versions.ContainsKey($name)) { throw 'Cannot unambiguously verify WSL versions; no preparation has run.' }
        $versions[$name] = $match.Groups['version'].Value
    }
    foreach ($name in $Names) {
        if (-not $versions.ContainsKey($name)) { throw 'Cannot unambiguously verify WSL versions; no preparation has run.' }
    }
    foreach ($name in $Names) {
        if ($versions[$name] -eq '2') { $name }
    }
}

function Select-BridgeWslDistro {
    param([string[]]$Names, [string[]]$Eligible)
    if ($Eligible.Count -eq 0) { throw 'No verified WSL2 distro is available. WSL1 is unsupported; no conversion or preparation has run.' }
    Write-Host ('Available WSL2 distros: ' + ($Eligible -join ', '))
    if ($Names.Count -eq 1) {
        if ((Read-Host ("Use WSL2 distro '{0}'? [Y/n]" -f $Eligible[0])) -cnotin @('', 'y', 'Y', 'yes')) { return }
        return $Eligible[0]
    }
    $choice = Read-Host 'Choose one WSL2 distro by its exact name from the list above'
    if ($Eligible -cnotcontains $choice) { throw 'The selected name is not a verified installed WSL2 distro; no preparation has run.' }
    return $choice
}

function Get-BridgeDosDevice {
    param([string]$Drive)
    if (-not ('BridgeInstallerVolume' -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.Text;
using System.Runtime.InteropServices;
public static class BridgeInstallerVolume {
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    public static extern uint QueryDosDevice(string name, StringBuilder result, int length);
}
'@
    }
    $buffer = New-Object Text.StringBuilder(4096)
    if ([BridgeInstallerVolume]::QueryDosDevice($Drive,$buffer,$buffer.Capacity) -eq 0) { throw 'WINDOWS_VOLUME_UNVERIFIED' }
    return $buffer.ToString()
}

function Get-BridgeWindowsTarget {
    param([string]$Path)
    if ($Path -notmatch '^[A-Za-z]:\\[^<>:"/|?*\x00-\x1f]+$' -or $Path.Length -gt 180) { throw 'WINDOWS_TARGET_INVALID: use a local NTFS folder with an existing parent.' }
    foreach ($part in $Path.Substring(3).Split('\')) {
        if (-not $part -or $part -in @('.','..') -or $part -match '[ .]$' -or $part -match '^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\..*)?$') { throw 'WINDOWS_TARGET_INVALID' }
    }
    $full = [IO.Path]::GetFullPath($Path)
    if (-not [string]::Equals($Path,$full,[StringComparison]::OrdinalIgnoreCase)) { throw 'WINDOWS_TARGET_INVALID' }
    $drive = New-Object IO.DriveInfo($full.Substring(0,3))
    if ($drive.DriveType -ne [IO.DriveType]::Fixed -or $drive.DriveFormat -cne 'NTFS') { throw 'WINDOWS_TARGET_UNSUPPORTED: only fixed local NTFS is supported.' }
    $device = Get-BridgeDosDevice $full.Substring(0,2)
    if ($device -cnotmatch '^\\Device\\HarddiskVolume[0-9]+$') { throw 'WINDOWS_VOLUME_AMBIGUOUS' } # e.g. SUBST
    foreach ($other in [IO.Directory]::GetLogicalDrives()) {
        if (-not [string]::Equals($other,$full.Substring(0,3),[StringComparison]::OrdinalIgnoreCase) -and (Get-BridgeDosDevice $other.Substring(0,2)) -ceq $device) { throw 'WINDOWS_VOLUME_AMBIGUOUS' }
    }
    return $full.Substring(0,1).ToUpperInvariant() + $full.Substring(1)
}

function Get-BridgeTrustedSids {
    @([Security.Principal.WindowsIdentity]::GetCurrent().User.Value,
      'S-1-5-18','S-1-5-32-544',
      'S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464')
}

function Assert-BridgeWindowsParent {
    param([string]$Target)
    $parent = [IO.Path]::GetDirectoryName($Target)
    $trusted = @(Get-BridgeTrustedSids)
    $current = New-Object IO.DirectoryInfo($parent)
    $first = $true
    while ($null -ne $current) {
        if (-not $current.Exists -or ($current.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'WINDOWS_PARENT_UNSAFE' }
        $acl = $current.GetAccessControl()
        if ($trusted -notcontains $acl.GetOwner([Security.Principal.SecurityIdentifier]).Value) { throw 'WINDOWS_PARENT_OWNER_UNSAFE' }
        # Creation rights on a drive root are normal; deletion/ACL substitution is not.
        $danger = [Security.AccessControl.FileSystemRights]::DeleteSubdirectoriesAndFiles -bor [Security.AccessControl.FileSystemRights]::ChangePermissions -bor [Security.AccessControl.FileSystemRights]::TakeOwnership -bor [Security.AccessControl.FileSystemRights]::Delete
        if ($first) { $danger = $danger -bor [Security.AccessControl.FileSystemRights]::Write }
        foreach ($rule in $acl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier])) {
            if ($rule.AccessControlType -eq 'Allow' -and -not ($rule.PropagationFlags -band [Security.AccessControl.PropagationFlags]::InheritOnly) -and $trusted -notcontains $rule.IdentityReference.Value -and ($rule.FileSystemRights -band $danger)) { throw 'WINDOWS_PARENT_WRITABLE_BY_OTHERS' }
        }
        $first = $false
        $current = $current.Parent
    }
}

function New-BridgePrivateAcl {
    $acl = New-Object Security.AccessControl.DirectorySecurity
    $sid = [Security.Principal.WindowsIdentity]::GetCurrent().User
    $acl.SetOwner($sid)
    $acl.SetAccessRuleProtection($true,$false)
    foreach ($value in @($sid.Value,'S-1-5-18','S-1-5-32-544')) {
        $identity = New-Object Security.Principal.SecurityIdentifier($value)
        $rule = New-Object Security.AccessControl.FileSystemAccessRule($identity,'FullControl','ContainerInherit, ObjectInherit','None','Allow')
        $acl.AddAccessRule($rule)
    }
    return $acl
}

function Assert-BridgePrivateEntry {
    param([string]$Path,[bool]$Directory)
    $item = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    if ($item.PSIsContainer -ne $Directory -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'WINDOWS_ENTRY_UNSAFE' }
    $acl = $item.GetAccessControl()
    $user = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    if ($acl.GetOwner([Security.Principal.SecurityIdentifier]).Value -cne $user -or ($Directory -and -not $acl.AreAccessRulesProtected)) { throw 'WINDOWS_ENTRY_NOT_PRIVATE' }
    $allowed = @($user,'S-1-5-18','S-1-5-32-544')
    $full = $false
    foreach ($rule in $acl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier])) {
        if ($rule.AccessControlType -eq 'Allow') {
            if ($allowed -notcontains $rule.IdentityReference.Value) { throw 'WINDOWS_ENTRY_NOT_PRIVATE' }
            if ($rule.IdentityReference.Value -ceq $user -and ($rule.FileSystemRights -band [Security.AccessControl.FileSystemRights]::FullControl) -eq [Security.AccessControl.FileSystemRights]::FullControl) { $full = $true }
        }
    }
    if (-not $full) { throw 'WINDOWS_ENTRY_NOT_PRIVATE' }
}

function Get-BridgeFileDigest {
    param([string]$Path)
    $stream = [IO.File]::Open($Path,'Open','Read','Read')
    try {
        if ($stream.Length -gt 1000000) { throw 'WINDOWS_FILE_TOO_LARGE' }
        $sha = [Security.Cryptography.SHA256]::Create()
        try { return ([BitConverter]::ToString($sha.ComputeHash($stream))).Replace('-','').ToLowerInvariant() }
        finally { $sha.Dispose() }
    } finally { $stream.Dispose() }
}

function Assert-BridgeDeployment {
    param([string]$Path,$Info,[bool]$Complete)
    Assert-BridgePrivateEntry $Path $true
    $marker = Join-Path $Path '.bridge-install.json'
    Assert-BridgePrivateEntry $marker $false
    if ((New-Object IO.FileInfo($marker)).Length -gt 4096) { throw 'WINDOWS_MARKER_INVALID' }
    $saved = [IO.File]::ReadAllText($marker) | ConvertFrom-Json
    if ($saved.target -cne $Info.target -or $saved.nonce -cne $Info.nonce -or $saved.proof -cne $Info.proof) { throw 'WINDOWS_DESTINATION_UNKNOWN' }
    $files = @($Info.spec.files.PSObject.Properties.Name)
    foreach ($item in Get-ChildItem -LiteralPath $Path -Force) {
        if ($item.Name -ceq '.bridge-install.json') { continue }
        if ($files -cnotcontains $item.Name) { throw 'WINDOWS_DESTINATION_UNKNOWN' }
        Assert-BridgePrivateEntry $item.FullName $false
        if ((Get-BridgeFileDigest $item.FullName) -cne $Info.spec.files.($item.Name)) { throw 'WINDOWS_DESTINATION_CHANGED' }
    }
    if ($Complete) {
        foreach ($name in $files) {
            Assert-BridgePrivateEntry (Join-Path $Path $name) $false
            if ((Get-BridgeFileDigest (Join-Path $Path $name)) -cne $Info.spec.files.$name) { throw 'WINDOWS_DESTINATION_CHANGED' }
        }
    }
}

function Publish-BridgeWindowsExtension {
    param($Info,[string]$Distro)
    $prefix = '\\wsl.localhost\' + $Distro + '\'
    if (-not $Info.source.StartsWith($prefix,[StringComparison]::Ordinal) -or $Info.source.Contains('..')) { throw 'WINDOWS_SOURCE_INVALID' }
    Publish-BridgeWindowsFiles $Info
}

function Publish-BridgeWindowsFiles {
    param($Info)
    $target = Get-BridgeWindowsTarget $Info.target
    if ($target -cne $Info.target -or $Info.nonce -cnotmatch '^[0-9a-f]{32}$' -or $Info.proof -cnotmatch '^[0-9a-f]{64}$') { throw 'WINDOWS_RECEIPT_INVALID' }
    $files = @($Info.spec.files.PSObject.Properties)
    if ($files.Count -lt 1 -or $files.Count -gt 64 -or @($files.Name) -cnotcontains 'connection.js' -or @($files.Name) -cnotcontains 'manifest.json') { throw 'WINDOWS_SOURCE_INVALID' }
    foreach ($file in $files) {
        if ($file.Name -cnotmatch '^[A-Za-z0-9_-]+\.(js|json|html|css)$' -or $file.Value -cnotmatch '^[0-9a-f]{64}$') { throw 'WINDOWS_SOURCE_INVALID' }
    }
    # The shared target name serializes cooperating installers across Windows sessions.
    $hash = [Security.Cryptography.SHA256]::Create()
    try { $key = ([BitConverter]::ToString($hash.ComputeHash([Text.Encoding]::UTF8.GetBytes($target.ToUpperInvariant())))).Replace('-','') } finally { $hash.Dispose() }
    $security = New-Object Security.AccessControl.MutexSecurity
    $sid = [Security.Principal.WindowsIdentity]::GetCurrent().User
    $security.SetOwner($sid)
    $security.SetAccessRuleProtection($true,$false)
    $security.AddAccessRule((New-Object Security.AccessControl.MutexAccessRule($sid,'FullControl','Allow')))
    $created = $false
    $mutex = New-Object Threading.Mutex($false,('Global\BridgeExtension-'+$key),[ref]$created,$security)
    $held = $false
    try {
        try { $held = $mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $held = $true }
        if (-not $held) { throw 'WINDOWS_DESTINATION_BUSY' }
        Assert-BridgeWindowsParent $target
        foreach ($file in $files) {
            if ((Get-BridgeFileDigest (Join-Path $Info.source $file.Name)) -cne $file.Value) { throw 'WINDOWS_SOURCE_CHANGED' }
        }
        $stage = $target + '.bridge-stage-' + $Info.nonce
        if ([IO.File]::Exists($target)) { throw 'WINDOWS_DESTINATION_EXISTS' }
        if ([IO.Directory]::Exists($target)) {
            if (Test-Path -LiteralPath $stage) { throw 'WINDOWS_PUBLICATION_AMBIGUOUS' }
            Assert-BridgeDeployment $target $Info $true
            return
        }
        if ($Info.confirmed) { throw 'WINDOWS_CONFIRMED_DESTINATION_MISSING' }
        if (Test-Path -LiteralPath $stage) { Assert-BridgeDeployment $stage $Info $false }
        else {
            $folder = New-Object IO.DirectoryInfo($stage)
            $folder.Create((New-BridgePrivateAcl))
            Assert-BridgePrivateEntry $stage $true
            if (@(Get-ChildItem -LiteralPath $stage -Force).Count) { throw 'WINDOWS_STAGE_NOT_EMPTY' }
            $marker = @{target=$target;nonce=$Info.nonce;proof=$Info.proof} | ConvertTo-Json -Compress
            $stream = [IO.File]::Open((Join-Path $stage '.bridge-install.json'),'CreateNew','Write','None')
            try { $bytes = [Text.Encoding]::UTF8.GetBytes($marker); $stream.Write($bytes,0,$bytes.Length); $stream.Flush($true) } finally { $stream.Dispose() }
        }
        foreach ($file in $files) {
            $destination = Join-Path $stage $file.Name
            if (Test-Path -LiteralPath $destination) { continue } # hashes already checked
            $bytes = [IO.File]::ReadAllBytes((Join-Path $Info.source $file.Name))
            if ($bytes.Length -gt 1000000) { throw 'WINDOWS_FILE_TOO_LARGE' }
            $stream = [IO.File]::Open($destination,'CreateNew','Write','None')
            try { $stream.Write($bytes,0,$bytes.Length); $stream.Flush($true) } finally { $stream.Dispose() }
        }
        Assert-BridgeDeployment $stage $Info $true
        Assert-BridgeWindowsParent $target
        [IO.Directory]::Move($stage,$target) # same-volume, no overwrite; no cross-filesystem rename
        Assert-BridgeDeployment $target $Info $true
    } finally {
        if ($held) { $mutex.ReleaseMutex() }
        $mutex.Dispose()
    }
}

function Get-BridgeWindowsMetadata {
    param([string]$Distro,[string]$Script,[string]$Phase,[string[]]$Extra=@())
    $lines = @(& wsl.exe --distribution $Distro --exec env "BRIDGE_WSL_DISTRO=$Distro" python3 -B $Script reminders --windows-phase $Phase @Extra)
    if ($LASTEXITCODE -ne 0) { throw 'WINDOWS_REMINDERS_STOPPED: reminders require completed core preparation and a matching Linux reminders action. Retain any recorded destination; inspect before retry.' }
    return (($lines -join "`n") | ConvertFrom-Json)
}

if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
    throw 'WSL is unavailable. Enable Windows Subsystem for Linux through Windows Features, reboot, then run this file again. See docs/GETTING-STARTED.md.'
}
$listed = @(& wsl.exe --list --quiet)
if ($LASTEXITCODE -ne 0) { throw 'Cannot list installed WSL distros; no preparation has run.' }
$distros = @($listed | ForEach-Object { ($_ -replace "`0", '').Trim() } | Where-Object { $_ })
if ($distros.Count -eq 0) {
    if ($Action -eq 'reminders') { throw 'Run Start-Bridge.ps1 prepare first in an existing WSL2 Linux system before setting up reminders.' }
    if ((Read-Host 'Install Ubuntu through official WSL (Windows elevation/reboot may be required)? Type yes') -cne 'yes') { return }
    Start-Process -FilePath 'wsl.exe' -Verb RunAs -ArgumentList '--install', '-d', 'Ubuntu' -Wait
    Write-Host 'Finish Ubuntu user creation and any requested reboot, then run this file again.'
    return
}
$listed = @(& wsl.exe --list --verbose)
if ($LASTEXITCODE -ne 0) { throw 'Cannot verify installed WSL versions; no preparation has run.' }
$details = @($listed | ForEach-Object { ($_ -replace "`0", '').TrimEnd() })
$eligible = @(Get-BridgeWsl2Distros -Names $distros -Details $details)
$distro = Select-BridgeWslDistro -Names $distros -Eligible $eligible
if (-not $distro) { return }
# Observe the selected runtime before dependency installation or release writes.
$actual = @(& wsl.exe --distribution $distro --exec printenv WSL_DISTRO_NAME)
if ($LASTEXITCODE -ne 0 -or $actual.Count -ne 1 -or $actual[0] -cne $distro) { throw 'Selected WSL distro is unavailable or its identity differs; no preparation has run.' }
Write-Host ("Using WSL2 distro: {0}. Its default Linux user owns this preparation. WSL default/version and existing sessions are unchanged." -f $distro)
if ($Action -eq 'reminders') {
    # Use the prepared product; reminders never bootstrap Linux, copy a release
    # or request core service setup. The Linux action validates the existing core
    # before returning metadata or creating any notification pairing.
    $paths = @(& wsl.exe --distribution $distro --exec python3 -I -B -c "from pathlib import Path; import os,pwd; print(Path(pwd.getpwuid(os.getuid()).pw_dir)/'.local/share/gpt-agent-bridge/product/scripts/prepare-bridge.py')")
    if ($LASTEXITCODE -ne 0 -or $paths.Count -ne 1) { throw 'Cannot locate the prepared Linux product. Complete Start-Bridge.ps1 prepare first.' }
    $script = $paths[0].Trim()
    $info = Get-BridgeWindowsMetadata $distro $script 'inspect'
    if ($info.mode -eq 'fresh') {
        $choice = $ExtensionDirectory
        if (-not $choice) {
            $default = Join-Path $env:LOCALAPPDATA 'GPT-Agent-Bridge-extension'
            $choice = Read-Host ("Private Windows extension folder (existing parent, local NTFS) [{0}]" -f $default)
            if (-not $choice) { $choice = $default }
        }
        $target = Get-BridgeWindowsTarget $choice
        Assert-BridgeWindowsParent $target
        if (Test-Path -LiteralPath $target) { throw 'WINDOWS_DESTINATION_EXISTS: choose a new folder explicitly; nothing was overwritten.' }
        if ((Read-Host ("Prepare the private extension at '{0}'? Type yes" -f $target)) -cne 'yes') { return }
        $encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($target))
        $info = Get-BridgeWindowsMetadata $distro $script 'reserve' @('--windows-target-base64',$encoded)
    } elseif ($ExtensionDirectory) {
        if ($info.mode -ne 'windows' -or (Get-BridgeWindowsTarget $ExtensionDirectory) -cne $info.target) { throw 'EXISTING_INSTALLATION_NO_RELOCATION' }
    }
    if ($info.mode -eq 'windows') {
        if ($null -eq $info.spec) {
            & wsl.exe --distribution $distro --exec env "BRIDGE_WSL_DISTRO=$distro" python3 -B $script reminders --windows-phase stage
            if ($LASTEXITCODE -ne 0) { throw 'WINDOWS_MATERIALIZATION_STOPPED: retain prepared objects; inspect before retry.' }
            $info = Get-BridgeWindowsMetadata $distro $script 'inspect'
        }
        try { Publish-BridgeWindowsExtension $info $distro }
        catch {
            $code = 'WINDOWS_PUBLICATION_STOPPED'
            if ($_.Exception.Message -match '^(WINDOWS_[A-Z_]+)(?:[: ]|$)') { $code = $matches[1] }
            throw ($code + ': keep the same recorded folder and staging files; inspect before retry. Core preparation is separate.')
        }
        $null = Get-BridgeWindowsMetadata $distro $script 'confirm' @('--windows-proof',$info.proof)
        & wsl.exe --distribution $distro --exec env "BRIDGE_WSL_DISTRO=$distro" python3 -B $script reminders --windows-phase continue
        if ($LASTEXITCODE -ne 0) { throw 'Reminder preparation stopped; retain the confirmed Windows folder and inspect the failure.' }
        return
    }
    # Existing Linux/WSL extension identities keep their recorded load paths.
    & wsl.exe --distribution $distro --exec env "BRIDGE_WSL_DISTRO=$distro" python3 -B $script reminders
    if ($LASTEXITCODE -ne 0) { throw 'Reminder preparation stopped; retain the existing extension identity and inspect the failure.' }
    return
}
& wsl.exe --distribution $distro --exec sh -c 'command -v python3 >/dev/null && command -v git >/dev/null && python3 -c "import ensurepip"'
if ($LASTEXITCODE -ne 0) {
    if ((Read-Host ("Install Python 3/venv and Git with apt in '{0}'? Type yes" -f $distro)) -cne 'yes') { return }
    & wsl.exe --distribution $distro --exec sudo apt-get update
    if ($LASTEXITCODE -ne 0) { throw 'Package index failed; no Bridge setup has run.' }
    & wsl.exe --distribution $distro --exec sudo apt-get install -y python3 python3-venv git
    if ($LASTEXITCODE -ne 0) { throw 'System dependencies are incomplete. See distro package manager output.' }
}
$linuxSource = (& wsl.exe --distribution $distro --exec wslpath -a $PSScriptRoot).Trim()
if ($LASTEXITCODE -ne 0) { throw 'Cannot map the complete release directory into WSL.' }
# Only the release allowlist is copied. Destination files must match on repeat.
$copy = @'
import pathlib,sys,json,hashlib,os,subprocess,importlib.util
source=pathlib.Path(sys.argv[1]);target=pathlib.Path.home()/'.local/share/bridge-release'
if not (source/'release-manifest.json').exists():
 scope=['--','.',':(exclude).principal',':(exclude).principal/**',':(exclude).app.json']
 if subprocess.check_output(['git','-C',str(source),'status','--porcelain',*scope]).strip():raise SystemExit('dirty checkout; review first')
 revision=subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip()
 spec=importlib.util.spec_from_file_location('distribution',source/'scripts/build-distribution.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
 release=pathlib.Path.home()/('.local/share/bridge-source-'+revision)
 if not release.exists():
  release.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
  module.build(source,release)
 source=release
manifest=json.loads((source/'release-manifest.json').read_text())
for name,sha in manifest['files'].items():
 p=pathlib.Path(name)
 if p.is_absolute() or '..' in p.parts or p.parts[0] in ('.git','.principal'):raise SystemExit('unsafe release path')
 data=(source/p).read_bytes()
 if hashlib.sha256(data).hexdigest()!=sha:raise SystemExit('release checksum mismatch')
 dest=target/p
 for parent in [target,*dest.parents]:
  if parent.is_symlink():raise SystemExit('symlink destination refused')
 dest.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
 if dest.exists():
  if dest.read_bytes()!=data:raise SystemExit('existing release differs; preserved for inspection')
 else:
  with dest.open('xb') as f:f.write(data)
  dest.chmod(0o700 if name in manifest.get('executables',['prepare']) else 0o600)
m=target/'release-manifest.json';data=(source/'release-manifest.json').read_bytes()
if m.exists() and m.read_bytes()!=data:raise SystemExit('different release receipt')
if not m.exists():m.write_bytes(data);m.chmod(0o600)
print(target)
'@
$release = (& wsl.exe --distribution $distro --exec python3 -c $copy $linuxSource).Trim()
if ($LASTEXITCODE -ne 0) { throw 'Release copy was not confirmed. Original files were retained.' }
& wsl.exe --distribution $distro --exec env "BRIDGE_WSL_DISTRO=$distro" python3 "$release/scripts/prepare-bridge.py" $Action
if ($LASTEXITCODE -ne 0) { throw 'Preparation stopped; follow the local recovery message. Do not reinstall or reset state.' }

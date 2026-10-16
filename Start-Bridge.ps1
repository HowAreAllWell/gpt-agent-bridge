# Run this reviewed file, not a remotely piped script. Explicitly select one WSL2 distro.
[CmdletBinding()]
param([ValidateSet('prepare','status','credentials')][string]$Action = 'prepare')
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

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

if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
    throw 'WSL is unavailable. Enable Windows Subsystem for Linux through Windows Features, reboot, then run this file again. See docs/GETTING-STARTED.md.'
}
$listed = @(& wsl.exe --list --quiet)
if ($LASTEXITCODE -ne 0) { throw 'Cannot list installed WSL distros; no preparation has run.' }
$distros = @($listed | ForEach-Object { ($_ -replace "`0", '').Trim() } | Where-Object { $_ })
if ($distros.Count -eq 0) {
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

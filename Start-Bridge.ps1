# Run this reviewed file, not a remotely piped script. Uses the current default WSL distro.
[CmdletBinding()]
param()
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
    throw 'WSL is unavailable. Enable Windows Subsystem for Linux through Windows Features, reboot, then run this file again. See docs/GETTING-STARTED.md.'
}
$distros = @(& wsl.exe --list --quiet) | ForEach-Object { ($_ -replace "`0", '').Trim() } | Where-Object { $_ }
if ($distros.Count -eq 0) {
    if ((Read-Host 'Install Ubuntu through official WSL (Windows elevation/reboot may be required)? Type yes') -cne 'yes') { return }
    Start-Process -FilePath 'wsl.exe' -Verb RunAs -ArgumentList '--install', '-d', 'Ubuntu' -Wait
    Write-Host 'Finish Ubuntu user creation and any requested reboot, then run this file again.'
    return
}
# Do not change the default distro or choose a random existing session.
Write-Host 'Using your existing default WSL distro. Existing sessions are retained.'
& wsl.exe --exec sh -c 'command -v python3 >/dev/null && command -v git >/dev/null && python3 -c "import ensurepip"'
if ($LASTEXITCODE -ne 0) {
    if ((Read-Host 'Install Python 3/venv and Git with apt in this distro? Type yes') -cne 'yes') { return }
    & wsl.exe --exec sudo apt-get update
    if ($LASTEXITCODE -ne 0) { throw 'Package index failed; no Bridge setup has run.' }
    & wsl.exe --exec sudo apt-get install -y python3 python3-venv git
    if ($LASTEXITCODE -ne 0) { throw 'System dependencies are incomplete. See distro package manager output.' }
}
$linuxSource = (& wsl.exe --exec wslpath -a $PSScriptRoot).Trim()
if ($LASTEXITCODE -ne 0) { throw 'Cannot map the complete release directory into WSL.' }
# Only the release allowlist is copied. Destination files must match on repeat.
$copy = @'
import pathlib,sys,json,hashlib,os
source=pathlib.Path(sys.argv[1]);target=pathlib.Path.home()/'.local/share/bridge-release'
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
$release = (& wsl.exe --exec python3 -c $copy $linuxSource).Trim()
if ($LASTEXITCODE -ne 0) { throw 'Release copy was not confirmed. Original files were retained.' }
& wsl.exe --exec python3 "$release/scripts/prepare-bridge.py"
if ($LASTEXITCODE -ne 0) { throw 'Preparation stopped; follow the local recovery message. Do not reinstall or reset state.' }

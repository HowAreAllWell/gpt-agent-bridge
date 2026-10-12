# Run in the owning user's Windows PowerShell 5.1+ (not inside Linux).
# Never installs WSL or starts Bridge/Herdr/Tunnel. Installation is disabled by default.
[CmdletBinding()]
param(
    [ValidateSet('Plan', 'Install', 'Enable', 'Status', 'Disable', 'Uninstall')]
    [string]$Action = 'Plan',
    [Parameter(Mandatory = $true)][string]$Distro,
    [Parameter(Mandatory = $true)][string]$LinuxUser,
    [switch]$StopAnchor
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function ConvertTo-WindowsArgument([string]$Value) {
    # These operands deliberately accept no quotes, backslashes or shell syntax.
    # wsl.exe is launched directly, never through cmd/PowerShell/Bash -c.
    if ($Value -notmatch '\A[\p{L}\p{N}_][\p{L}\p{N} ._-]{0,63}\z') {
        throw 'Unsupported argument characters.'
    }
    return '"' + $Value + '"'
}

function Get-XmlBoolean($Node, [bool]$Default) {
    if ($null -eq $Node) { return $Default }
    switch ($Node.InnerText) {
        'true' { return $true }
        '1' { return $true }
        'false' { return $false }
        '0' { return $false }
        default { throw 'Unknown XML boolean representation.' }
    }
}

function Get-OwnedTask([Nullable[bool]]$ExpectedEnabled = $null) {
    # A failed read is not proof of absence. Enumerate the folder and filter locally.
    $tasks = @(Get-ScheduledTask -TaskPath '\' -ErrorAction Stop |
        Where-Object { $_.TaskName -ceq $script:TaskName })
    if ($tasks.Count -eq 0) { return $null }
    if ($tasks.Count -ne 1) { throw 'Ambiguous task ownership.' }
    $task = $tasks[0]
    $xml = [xml](Export-ScheduledTask -TaskName $script:TaskName -TaskPath '\')
    $ns = New-Object System.Xml.XmlNamespaceManager($xml.NameTable)
    $ns.AddNamespace('t', 'http://schemas.microsoft.com/windows/2004/02/mit/task')
    $execs = @($xml.SelectNodes('/t:Task/t:Actions/t:Exec', $ns))
    $actions = @($xml.SelectNodes('/t:Task/t:Actions/*', $ns))
    $triggers = @($xml.SelectNodes('/t:Task/t:Triggers/*', $ns))
    $principals = @($xml.SelectNodes('/t:Task/t:Principals/t:Principal', $ns))
    if ($actions.Count -ne 1 -or $execs.Count -ne 1 -or $triggers.Count -ne 1 -or $principals.Count -ne 1 -or
        $task.Description -cne $script:Description -or
        $xml.SelectSingleNode('/t:Task/t:RegistrationInfo/t:Description', $ns).InnerText -cne $script:Description -or
        $execs[0].Command -cne $script:Wsl -or $execs[0].Arguments -cne $script:Arguments -or
        $triggers[0].LocalName -cne 'LogonTrigger' -or $triggers[0].UserId -cne $script:Sid -or
        $principals[0].UserId -cne $script:Sid -or
        $principals[0].LogonType -cne 'InteractiveToken' -or
        $principals[0].RunLevel -cne 'LeastPrivilege' -or
        $null -ne $principals[0].SelectSingleNode('t:GroupId', $ns) -or
        ($execs[0].SelectSingleNode('t:WorkingDirectory', $ns) -and $execs[0].WorkingDirectory) -or
        $xml.Task.Settings.ExecutionTimeLimit -cne 'PT0S' -or
        $xml.Task.Settings.MultipleInstancesPolicy -cne 'IgnoreNew') {
        throw 'Existing task does not match this helper; refusing any change.'
    }
    $triggerEnabled = Get-XmlBoolean ($triggers[0].SelectSingleNode('t:Enabled', $ns)) $true
    $enabled = Get-XmlBoolean ($xml.SelectSingleNode('/t:Task/t:Settings/t:Enabled', $ns)) $true
    $onBattery = Get-XmlBoolean ($xml.SelectSingleNode('/t:Task/t:Settings/t:DisallowStartIfOnBatteries', $ns)) $true
    $stopOnBattery = Get-XmlBoolean ($xml.SelectSingleNode('/t:Task/t:Settings/t:StopIfGoingOnBatteries', $ns)) $true
    $triggerLimit = $triggers[0].SelectSingleNode('t:ExecutionTimeLimit', $ns)
    $delay = $triggers[0].SelectSingleNode('t:Delay', $ns)
    $context = $xml.SelectSingleNode('/t:Task/t:Actions', $ns).GetAttribute('Context')
    if (-not $triggerEnabled -or $onBattery -or $stopOnBattery -or
        $task.Settings.DisallowStartIfOnBatteries -or $task.Settings.StopIfGoingOnBatteries -or
        $enabled -ne [bool]$task.Settings.Enabled -or
        ($null -ne $ExpectedEnabled -and $enabled -ne [bool]$ExpectedEnabled) -or
        ($triggerLimit -and $triggerLimit.InnerText -cne 'PT0S') -or
        ($delay -and $delay.InnerText -cne 'PT0S') -or
        $triggers[0].SelectSingleNode('t:Repetition | t:StartBoundary | t:EndBoundary', $ns) -or
        ($context -and $context -cne $principals[0].GetAttribute('id'))) {
        throw 'Task enabled state or scheduling policy readback mismatch.'
    }
    return $task
}

function Assert-OwnedTaskState([bool]$Enabled) {
    $verified = Get-OwnedTask -ExpectedEnabled $Enabled
    if ($null -eq $verified) { throw 'Registered task could not be read back.' }
    return $verified
}

function Assert-NoAnchorInstance {
    # COM GetInstances(0) checks instances as well as the CIM scheduling state.
    # Read failures or unknown/queued states never establish safe removal.
    $verified = Assert-OwnedTaskState $false
    if ($verified.State -notin @('Ready', 'Disabled')) { throw 'Anchor is running, queued or in an unknown state.' }
    $scheduler = New-Object -ComObject 'Schedule.Service'
    $scheduler.Connect()
    $registered = $scheduler.GetFolder('\').GetTask($script:TaskName)
    if ($registered.GetInstances(0).Count -ne 0) { throw 'Anchor instances remain; inspect before retry.' }
    $again = Assert-OwnedTaskState $false
    if ($again.State -notin @('Ready', 'Disabled')) { throw 'Anchor state changed during verification.' }
}

function Assert-ReadyDistro {
    # Mutating task actions require an already running distro. No implicit wake.
    $running = @(& $script:Wsl --list --running --quiet 2>$null)
    if ($LASTEXITCODE -ne 0) { throw 'Cannot verify running WSL distros.' }
    $names = @($running | ForEach-Object { ($_ -replace "`0", '').Trim() })
    if ($names -cnotcontains $Distro) { throw 'Open the selected distro explicitly and verify systemd first.' }
    $name = @(& $script:Wsl --distribution $Distro --user $LinuxUser --exec /usr/bin/id -un 2>$null)
    if ($LASTEXITCODE -ne 0 -or (($name -join '').Trim() -cne $LinuxUser)) {
        throw 'The explicit Linux user could not be verified.'
    }
    $uid = @(& $script:Wsl --distribution $Distro --user $LinuxUser --exec /usr/bin/id -u 2>$null)
    if ($LASTEXITCODE -ne 0 -or (($uid -join '').Trim() -notmatch '^[1-9][0-9]*$')) {
        throw 'A verified nonroot Linux user is required.'
    }
    $init = @(& $script:Wsl --distribution $Distro --user $LinuxUser --exec /usr/bin/cat /proc/1/comm 2>$null)
    if ($LASTEXITCODE -ne 0 -or (($init -join '').Trim() -cne 'systemd')) {
        throw 'Selected distro must already use systemd as PID 1.'
    }
    & $script:Wsl --distribution $Distro --user $LinuxUser --exec /usr/bin/test -x /usr/bin/sleep 2>$null
    if ($LASTEXITCODE -ne 0) { throw 'The fixed Linux sleep executable is unavailable.' }
}

try {
    if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT -or
        [Environment]::OSVersion.Version.Build -lt 19041 -or $PSVersionTable.PSVersion -lt [version]'5.1') {
        throw 'Requires supported Windows 10/11, PowerShell 5.1+, WSL2 and ScheduledTasks.'
    }
    if ((Get-CimInstance Win32_OperatingSystem).ProductType -ne 1) { throw 'Only Windows client editions are supported.' }
    if ($LinuxUser -notmatch '\A[a-z_][a-z0-9_-]{0,31}\z' -or $LinuxUser -ceq 'root') {
        throw 'Specify an explicit nonroot Linux username.'
    }
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $script:Sid = $identity.User.Value
    if ($Sid -in @('S-1-5-18', 'S-1-5-19', 'S-1-5-20')) { throw 'Service identities including SYSTEM are unsupported.' }
    Import-Module ScheduledTasks -ErrorAction Stop
    $script:Wsl = Join-Path ([Environment]::GetFolderPath('System')) 'wsl.exe'
    if (-not (Test-Path -LiteralPath $Wsl -PathType Leaf)) { throw 'wsl.exe is unavailable.' }
    $script:Arguments = '--distribution ' + (ConvertTo-WindowsArgument $Distro) +
        ' --user ' + (ConvertTo-WindowsArgument $LinuxUser) + ' --exec /usr/bin/sleep infinity'
    $script:TaskName = 'GPTAgentBridge-WSL-' + $Sid
    $script:Description = 'GPT-Agent Bridge WSL logon anchor v1: ' + $Distro + '/' + $LinuxUser

    # Registered distros belong to this Windows user, not SYSTEM or another account.
    # Registry Version avoids localized parsing of wsl -l -v.
    if ($Action -in @('Plan', 'Install', 'Enable')) {
        $entries = @(Get-ChildItem 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss' |
            ForEach-Object { Get-ItemProperty -LiteralPath $_.PSPath } |
            Where-Object { $_.DistributionName -ceq $Distro })
        if ($entries.Count -ne 1 -or $entries[0].Version -ne 2) { throw 'Unknown distro or non-WSL2 registration.' }
    }
    $task = Get-OwnedTask
    switch ($Action) {
        'Plan' {
            [pscustomobject]@{ Action = $Action; Distro = $Distro; LinuxUser = $LinuxUser;
                LinuxUserVerified = $false; Trigger = 'Current-user logon'; EnabledOnInstall = $false;
                TaskSettingsExecutionTimeLimit = 'PT0S'; TriggerLimitVerified = $false;
                MultipleInstances = 'IgnoreNew'; Arguments = $Arguments }
        }
        'Install' {
            if ($null -ne $task) { throw 'Task already exists; no overwrite or adoption.' }
            Assert-ReadyDistro
            $trigger = New-ScheduledTaskTrigger -AtLogOn -User $Sid
            $principal = New-ScheduledTaskPrincipal -UserId $Sid -LogonType Interactive -RunLevel Limited
            $settings = New-ScheduledTaskSettingsSet -Disable -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew `
                -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
            $definition = New-ScheduledTask -Action (New-ScheduledTaskAction -Execute $Wsl -Argument $Arguments) `
                -Trigger $trigger -Principal $principal -Settings $settings -Description $Description
            Register-ScheduledTask -TaskName $TaskName -TaskPath '\' -InputObject $definition | Out-Null
            Assert-OwnedTaskState $false | Out-Null
            Write-Output 'Installed; disabled state and owned task policy verified. Enable is a separate choice.'
        }
        'Enable' {
            if ($null -eq $task) { throw 'Install this task first.' }
            Assert-ReadyDistro
            Enable-ScheduledTask -TaskName $TaskName -TaskPath '\' | Out-Null
            Assert-OwnedTaskState $true | Out-Null
            Write-Output 'Enabled state verified. No immediate start was requested; scheduler restart may retrigger logon.'
        }
        'Status' {
            if ($null -eq $task) { Write-Output 'Not installed.' }
            else { [pscustomobject]@{ State = $task.State; Enabled = $task.Settings.Enabled;
                TaskSettingsExecutionTimeLimit = 'PT0S'; TriggerLimitVerified = $false;
                BridgeHealth = 'Not probed'; WorkResume = 'Not established' } }
        }
        'Disable' {
            if ($null -eq $task) { throw 'No owned task installed.' }
            Disable-ScheduledTask -TaskName $TaskName -TaskPath '\' | Out-Null
            Assert-OwnedTaskState $false | Out-Null
            if ($StopAnchor) {
                Stop-ScheduledTask -TaskName $TaskName -TaskPath '\'
                Assert-NoAnchorInstance
            }
            Write-Output 'Disabled state verified. Stopping the anchor may indirectly affect WSL/Bridge availability.'
        }
        'Uninstall' {
            if ($null -eq $task) { throw 'No owned task installed.' }
            if ($task.State -notin @('Ready', 'Disabled', 'Running', 'Queued')) { throw 'Unknown anchor state; refusing removal.' }
            if ($task.State -in @('Running', 'Queued') -and -not $StopAnchor) { throw 'Running or queued anchor requires explicit -StopAnchor.' }
            Disable-ScheduledTask -TaskName $TaskName -TaskPath '\' | Out-Null
            Assert-OwnedTaskState $false | Out-Null
            if ($StopAnchor) { Stop-ScheduledTask -TaskName $TaskName -TaskPath '\' }
            Assert-NoAnchorInstance
            Unregister-ScheduledTask -TaskName $TaskName -TaskPath '\' -Confirm:$false
            if ($null -ne (Get-OwnedTask)) { throw 'Task removal could not be verified.' }
            Write-Output 'Owned task removed. No distro shutdown or Linux service changes.'
        }
    }
} catch {
    # Do not echo raw native output or invocation data. Unknown outcomes need inspection.
    Write-Error 'Refused or outcome uncertain. Verify prerequisites/owned task locally; do not blindly retry.'
    exit 1
}

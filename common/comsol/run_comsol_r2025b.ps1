param(
    [Parameter(Mandatory = $true)]
    [string]$TaskScript,

    [Parameter(Mandatory = $true)]
    [string]$ReportPath,

    [ValidateRange(1, 3)]
    [int]$StartupAttempts = 2,

    [ValidateRange(1, 30)]
    [int]$StartupRetryDelaySeconds = 5,

    [ValidateRange(10, 3600)]
    [int]$StartupReportTimeoutSeconds = 120,

    [ValidateSet('stop', 'warn')]
    [string]$StartupReportTimeoutAction = 'warn',

    [ValidateRange(0, 64)]
    [int]$ProcessorCount = 0,

    [ValidateSet('auto', 'scalable', 'native')]
    [string]$Allocator = 'auto',

    [ValidateSet('auto', 'off', 'matrix', 'vector', 'on')]
    [string]$AssemblyScalabilityMode = 'auto',

    [hashtable]$ResourceBudgets = @{},

    [string]$RunId = '',
    [pscustomobject]$Limits = $null,
    [string]$RunDir = '',
    [string]$UsagePath = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '..\require_powershell7.ps1')
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
. (Join-Path $repoRoot 'common\host_execution_lease.ps1')
. (Join-Path $repoRoot 'common\multipole\resource_budget_support.ps1')
foreach ($stageName in $ResourceBudgets.Keys) {
    if ($stageName -notin @('prepare', 'solver', 'postprocess')) {
        throw "Unknown COMSOL resource stage: $stageName"
    }
}
$stageBudgets = @{}
foreach ($stageName in @('prepare', 'solver', 'postprocess')) {
    $stageBudgets[$stageName] = if ($ResourceBudgets.ContainsKey($stageName)) {
        $ResourceBudgets[$stageName]
    } else {
        Get-HostResourceBudget -Role COMSOL -Stage $stageName
    }
}
# Isolate managed LiveLink sessions; cleanup ownership still requires exact
# process ancestry and creation identities, not this session lock.
$solverBudget = @{}
foreach ($entry in $stageBudgets.solver.GetEnumerator()) { $solverBudget[$entry.Key] = $entry.Value }
$solverBudget.exclusive_resources = @(
    @($solverBudget.exclusive_resources) + 'comsol-server-session' | Select-Object -Unique
)
$stageBudgets.solver = $solverBudget
$resourceLease = Enter-HostResourceStage -Role COMSOL -Stage prepare `
    -Budget $stageBudgets.prepare -RunId $RunId
try {
$bootstrapDir = Join-Path $PSScriptRoot 'livelink_r2025b'
$failureClassifier = Join-Path $PSScriptRoot 'livelink_failure_classification.ps1'
$environmentPreflight = Join-Path $PSScriptRoot 'livelink_environment.ps1'
. (Join-Path $PSScriptRoot 'resolve_comsol_64.ps1')
$launcher = Get-Comsol64Launcher
$matlabRoot = if ($env:MATLAB_R2025B_ROOT) {
    [IO.Path]::GetFullPath($env:MATLAB_R2025B_ROOT)
} else {
    Join-Path $env:ProgramFiles 'MATLAB\R2025b\MatlabR2025b'
}

if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) {
    throw "COMSOL MATLAB launcher not found: $launcher"
}
if (-not (Test-Path -LiteralPath $matlabRoot -PathType Container)) {
    throw "MATLAB R2025b root not found: $matlabRoot"
}
. $failureClassifier
. $environmentPreflight

$runtimeWritePaths = @(Get-ComsolRuntimeWritePaths -UserProfile $env:USERPROFILE -TempPath $env:TEMP)
Assert-ComsolRuntimeWriteAccess -Paths $runtimeWritePaths

function Get-ComsolServerProcessIds {
    return @(Get-Process -Name 'comsolmphserver' -ErrorAction SilentlyContinue |
        ForEach-Object { [int]$_.Id })
}

function Stop-ComsolAttemptServers {
    param([int]$RootProcessId, [hashtable]$Observation, [string]$Reason)
    try {
        $sample = Get-ManagedSolverProcessSample -RootProcessIds @($RootProcessId) `
            -RootProcessStartedAtUtcTicks @{([string]$RootProcessId)=$Observation.tracked_ticks[[string]$RootProcessId]} `
            -TrackedProcessIds @($Observation.tracked_ticks.Keys | ForEach-Object {[int]$_}) `
            -TrackedProcessStartedAtUtcTicks $Observation.tracked_ticks
        foreach ($identity in $sample.tracked_process_started_at_utc_ticks.GetEnumerator()) {
            if (-not $Observation.tracked_ticks.ContainsKey([string]$identity.Key)) {
                $Observation.tracked_ticks[[string]$identity.Key]=$identity.Value
            }
        }
    } catch {
        # Existing exact identities remain usable; absent ancestry is never ownership.
        Write-Warning "COMSOL_CLEANUP_OBSERVATION_UNAVAILABLE ERROR=$($_.Exception.Message)" -WarningAction Continue
    }
    $attemptIds = @(Get-ComsolServerProcessIds | Where-Object {$Observation.tracked_ticks.ContainsKey([string]$_)})
    foreach ($processId in $attemptIds) {
        if (Test-ManagedRootProcessIsLive -ProcessId $processId `
                -ExpectedStartedAtUtcTicks ([int64]$Observation.tracked_ticks[[string]$processId])) {
            Stop-ManagedSolverProcesses -ProcessIds @($processId) -ExpectedStartedAtUtcTicks $Observation.tracked_ticks
            if ($Reason -eq 'task completion') {
                Write-Verbose "Stopped completed attempt-local COMSOL server PID $processId."
            } else {
                Write-Warning "Stopped attempt-local COMSOL server PID $processId after $Reason."
            }
        }
    }
}

function Start-ComsolLauncherProcess {
    param([string]$FilePath, [string[]]$Arguments)
    $startInfo = [Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $FilePath
    $startInfo.WorkingDirectory = $repoRoot
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    foreach ($argument in $Arguments) { [void]$startInfo.ArgumentList.Add($argument) }
    return [Diagnostics.Process]::Start($startInfo)
}

$task = (Resolve-Path -LiteralPath $TaskScript).Path
$report = [System.IO.Path]::GetFullPath($ReportPath)
$reportDir = Split-Path -Parent $report
if (-not (Test-Path -LiteralPath $reportDir)) {
    New-Item -ItemType Directory -Path $reportDir -Force | Out-Null
}

$oldMatlabPath = $env:MATLABPATH
try {
    $env:MATLABPATH = if ($oldMatlabPath) { "$bootstrapDir;$oldMatlabPath" } else { $bootstrapDir }
    $env:COMSOL_MATLAB_TASK = $task
    $env:COMSOL_BOOTSTRAP_REPORT = $report

    for ($attempt = 1; $attempt -le $StartupAttempts; $attempt++) {
        if ($attempt -gt 1) {
            Update-HostResourceStage -Lease $resourceLease -Stage prepare `
                -Budget $stageBudgets.prepare -RetainedMemoryBytes 0 | Out-Null
        }
        Remove-Item -LiteralPath $report -Force -ErrorAction SilentlyContinue
        $launcherArguments = @()
        if ($ProcessorCount -gt 0) {
            $launcherArguments += @('-np', [string]$ProcessorCount)
        }
        if ($Allocator -ne 'auto') {
            $launcherArguments += @('-alloc', $Allocator)
        }
        if ($AssemblyScalabilityMode -ne 'auto') {
            $launcherArguments += @('-memoptassem', $AssemblyScalabilityMode)
        }
        $launcherArguments += @(
            '-login', 'auto', 'matlab',
            '-mlroot', $matlabRoot,
            '-nodesktop',
            '-mlnosplash',
            '-mlstartdir', $repoRoot
        )
        Update-HostResourceStage -Lease $resourceLease -Stage solver `
            -Budget $stageBudgets.solver -RetainedMemoryBytes 0 | Out-Null
        $attemptObservation = New-RepositoryProcessObservation -Limits $Limits -RunDir $RunDir -UsagePath $UsagePath
        $launcherProcess = Start-ComsolLauncherProcess -FilePath $launcher `
            -Arguments $launcherArguments
        $launcherStartedUtc = $launcherProcess.StartTime.ToUniversalTime()
        $attemptObservation.tracked_ids = @([int]$launcherProcess.Id)
        $attemptObservation.tracked_ticks = @{([string]$launcherProcess.Id)=$launcherStartedUtc.Ticks}
        $attemptObservation.last_sample = $null
        $observeAttempt = {
            try {
                $sample = Get-ManagedSolverProcessSample -RootProcessIds @([int]$launcherProcess.Id) `
                    -RootProcessStartedAtUtcTicks @{([string]$launcherProcess.Id)=$launcherStartedUtc.Ticks} `
                    -TrackedProcessIds $attemptObservation.tracked_ids -TrackedProcessStartedAtUtcTicks $attemptObservation.tracked_ticks
                foreach ($identity in $sample.tracked_process_started_at_utc_ticks.GetEnumerator()) {
                    if (-not $attemptObservation.tracked_ticks.ContainsKey([string]$identity.Key)) {
                        $attemptObservation.tracked_ticks[[string]$identity.Key]=$identity.Value
                    }
                }
                $attemptObservation.tracked_ids = @($attemptObservation.tracked_ticks.Keys | ForEach-Object {[int]$_})
                $attemptObservation.last_sample = $sample
                $observed = Update-RepositoryProcessObservation -Observation $attemptObservation -Sample $sample
            } catch {
                if (-not $attemptObservation.observation_warning_sent) {
                    Write-Warning "RESOURCE_OBSERVATION_WARNING=unavailable ERROR=$($_.Exception.Message)" -WarningAction Continue
                    $attemptObservation.observation_warning_sent = $true
                }
                if (-not $attemptObservation.physical_danger) {
                    $attemptObservation.critical_since = $null
                    return
                }
                $observed = @{physical_danger=$true}
            }
            if ($observed.physical_danger) {
                Stop-ManagedSolverProcesses -ProcessIds $attemptObservation.tracked_ids `
                    -ExpectedStartedAtUtcTicks $attemptObservation.tracked_ticks
                throw 'COMSOL_PHYSICAL_MEMORY_DANGER: owned attempt stopped; Compute is not retried.'
            }
        }
        try {
        try {
            Register-HostResourceProcess -Lease $resourceLease -ProcessId $launcherProcess.Id | Out-Null
        } catch {
            # Do not leave an unregistered solver running if ownership publication fails.
            if (-not $launcherProcess.HasExited) {
                $launcherProcess.Kill($true)
                $launcherProcess.WaitForExit()
            }
            Stop-ComsolAttemptServers -RootProcessId $launcherProcess.Id -Observation $attemptObservation -Reason 'resource registration failure'
            throw
        }
        $standardOutputRead = $launcherProcess.StandardOutput.ReadToEndAsync()
        $standardErrorRead = $launcherProcess.StandardError.ReadToEndAsync()
        $reportDeadline = [DateTime]::UtcNow.AddSeconds($StartupReportTimeoutSeconds)
        $reportTimeoutWarned = $false
        while (-not $launcherProcess.HasExited -and
               -not (Test-Path -LiteralPath $report -PathType Leaf)) {
            & $observeAttempt
            if ([DateTime]::UtcNow -ge $reportDeadline) {
                if ($StartupReportTimeoutAction -eq 'stop') { break }
                if (-not $reportTimeoutWarned) {
                    Write-Warning ("COMSOL/MATLAB task report wait exceeded " +
                        "$StartupReportTimeoutSeconds seconds; continuing the same attempt.")
                    $reportTimeoutWarned = $true
                }
            }
            Start-Sleep -Milliseconds 500
            $launcherProcess.Refresh()
        }
        $startupTimedOut = -not $launcherProcess.HasExited -and
            -not (Test-Path -LiteralPath $report -PathType Leaf) -and
            $StartupReportTimeoutAction -eq 'stop'
        if ($startupTimedOut) {
            try { $launcherProcess.Kill($true) } catch {
                Stop-Process -Id $launcherProcess.Id -Force -ErrorAction SilentlyContinue
            }
            $launcherProcess.WaitForExit()
            $launcherExit = 124
            Write-Warning ("COMSOL/MATLAB did not create the task report within " +
                "$StartupReportTimeoutSeconds seconds (attempt $attempt/$StartupAttempts).")
        } else {
            while (-not $launcherProcess.HasExited) {
                & $observeAttempt
                [void]$launcherProcess.WaitForExit(500)
            }
            $launcherExit = $launcherProcess.ExitCode
        }
        $launcherStandardOutput = $standardOutputRead.GetAwaiter().GetResult()
        $launcherStandardError = $standardErrorRead.GetAwaiter().GetResult()
        Receive-HostResourceStage -Lease $resourceLease | Out-Null

        if (Test-Path -LiteralPath $report -PathType Leaf) {
            $reportText = Get-Content -LiteralPath $report -Raw -Encoding UTF8
            $reportText
            if ($launcherExit -eq 0 -and $reportText -match '(?m)^STATUS=PASS$') {
                Stop-ComsolAttemptServers -RootProcessId $launcherProcess.Id -Observation $attemptObservation -Reason 'task completion'
                Update-HostResourceStage -Lease $resourceLease -Stage postprocess `
                    -Budget $stageBudgets.postprocess -RetainedMemoryBytes 0 | Out-Null
                return
            }
            Stop-ComsolAttemptServers -RootProcessId $launcherProcess.Id -Observation $attemptObservation -Reason 'task failure'
            Update-HostResourceStage -Lease $resourceLease -Stage postprocess `
                -Budget $stageBudgets.postprocess -RetainedMemoryBytes 0 | Out-Null
            if ($attempt -lt $StartupAttempts -and
                (Test-ComsolRetryableStartupReport -ReportText $reportText)) {
                $archivedReport = $report + '.startup_retry.' + $attempt + '.' +
                    (Get-Date -Format 'yyyyMMdd_HHmmss')
                Move-Item -LiteralPath $report -Destination $archivedReport
                Write-Warning ("COMSOL server was disconnected during the first model open; " +
                    "archived the report at $archivedReport and retrying a clean startup in " +
                    "$StartupRetryDelaySeconds s (attempt $($attempt + 1)/$StartupAttempts).")
                Start-Sleep -Seconds $StartupRetryDelaySeconds
                continue
            }
            throw "R2025b LiveLink task failed (launcher exit $launcherExit)."
        }

        $launcherLogStem = $report + '.launcher.attempt' + $attempt
        [IO.File]::WriteAllText($launcherLogStem + '.stdout.log', $launcherStandardOutput)
        [IO.File]::WriteAllText($launcherLogStem + '.stderr.log', $launcherStandardError)
        $noReportReason = if ($startupTimedOut) { 'startup report timeout' } `
            else { 'startup without a task report' }
        Stop-ComsolAttemptServers -RootProcessId $launcherProcess.Id -Observation $attemptObservation -Reason $noReportReason
        Update-HostResourceStage -Lease $resourceLease -Stage postprocess `
            -Budget $stageBudgets.postprocess -RetainedMemoryBytes 0 | Out-Null
        if ($StartupReportTimeoutAction -eq 'warn') { break }
        if ($attempt -lt $StartupAttempts) {
            Write-Warning ("COMSOL/MATLAB exited before the task report was created; " +
                "retrying clean startup in $StartupRetryDelaySeconds s " +
                "(attempt $($attempt + 1)/$StartupAttempts).")
            Start-Sleep -Seconds $StartupRetryDelaySeconds
        }
        } finally {
            if ($null -ne $attemptObservation.last_sample -and $null -ne $attemptObservation.usage) {
                try {
                    $null = Update-RepositoryProcessObservation -Observation $attemptObservation -Sample $attemptObservation.last_sample -Final
                    if ($attemptObservation.usage.status -ne 'physical_danger') {
                        $attemptObservation.usage.status = if ($launcherProcess.ExitCode -eq 0) { 'running' } else { 'process_failed' }
                    }
                    Write-ResourceUsage -Usage $attemptObservation.usage -Path $UsagePath
                    Complete-ResourceUsage -RunDir $RunDir -UsagePath $UsagePath | Out-Null
                } catch {
                    Write-Warning "RESOURCE_OBSERVATION_WARNING=finalization_failed ERROR=$($_.Exception.Message)" -WarningAction Continue
                }
            }
            # A JVM fatal log belongs to this launcher only after it exits and
            # when the exact PID file was created during this process lifetime.
            # Keep its raw bytes in the scientific owner's normal log inventory.
            try {
                $crashPath = Join-Path $repoRoot "hs_err_pid$($launcherProcess.Id).log"
                if ($launcherProcess.HasExited -and (Test-Path -LiteralPath $crashPath -PathType Leaf)) {
                    $crashFile = Get-Item -LiteralPath $crashPath
                    if ($crashFile.CreationTimeUtc -ge $launcherStartedUtc) {
                        [IO.File]::Move($crashPath, (Join-Path $reportDir $crashFile.Name))
                    }
                }
            } catch {
                # Retain an untransported log and the original task exception.
                Write-Warning "COMSOL_JVM_CRASH_LOG_NOT_MOVED PID=$($launcherProcess.Id) ERROR=$($_.Exception.Message)" `
                    -WarningAction Continue
            }
        }
    }
}
finally {
    $env:MATLABPATH = $oldMatlabPath
    Remove-Item Env:COMSOL_MATLAB_TASK -ErrorAction SilentlyContinue
    Remove-Item Env:COMSOL_BOOTSTRAP_REPORT -ErrorAction SilentlyContinue
}

throw "LiveLink task did not create its report after $StartupAttempts clean startup attempts: $report"
} finally {
    Exit-HostResourceStage -Lease $resourceLease | Out-Null
}

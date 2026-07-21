param(
    [Parameter(Mandatory = $true)]
    [string]$TaskScript,

    [Parameter(Mandatory = $true)]
    [string]$ReportPath,

    [ValidateRange(1, 3)]
    [int]$StartupAttempts = 2,

    [ValidateRange(1, 30)]
    [int]$StartupRetryDelaySeconds = 5,

    [ValidateRange(10, 600)]
    [int]$StartupReportTimeoutSeconds = 120,

    [ValidateRange(0, 64)]
    [int]$ProcessorCount = 0,

    [ValidateSet('auto', 'scalable', 'native')]
    [string]$Allocator = 'auto'
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$bootstrapDir = Join-Path $PSScriptRoot 'livelink_r2025b'
$failureClassifier = Join-Path $PSScriptRoot 'livelink_failure_classification.ps1'
$environmentPreflight = Join-Path $PSScriptRoot 'livelink_environment.ps1'
$launcher = 'D:\COMSOL 6.4\COMSOL64\Multiphysics\bin\win64\comsolmphserver.exe'
$matlabRoot = 'C:\Program Files\MATLAB\R2025b\MatlabR2025b'

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
    param([int[]]$Before, [string]$Reason)
    $after = @(Get-ComsolServerProcessIds)
    $attemptIds = @(Get-ComsolAttemptServerIds -Before $Before -After $after)
    foreach ($processId in $attemptIds) {
        $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
        if ($null -ne $process -and $process.ProcessName -eq 'comsolmphserver') {
            Stop-Process -Id $processId -Force
            Write-Warning "Stopped attempt-local COMSOL server PID $processId after $Reason."
        }
    }
}

function Start-ComsolLauncherProcess {
    param([string]$FilePath, [string[]]$Arguments)
    $startInfo = [Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $FilePath
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
        Remove-Item -LiteralPath $report -Force -ErrorAction SilentlyContinue
        $launcherArguments = @()
        if ($ProcessorCount -gt 0) {
            $launcherArguments += @('-np', [string]$ProcessorCount)
        }
        if ($Allocator -ne 'auto') {
            $launcherArguments += @('-alloc', $Allocator)
        }
        $launcherArguments += @(
            '-login', 'auto', 'matlab',
            '-mlroot', $matlabRoot,
            '-nodesktop',
            '-mlnosplash',
            '-mlstartdir', $repoRoot
        )
        $serversBeforeAttempt = @(Get-ComsolServerProcessIds)
        $launcherProcess = Start-ComsolLauncherProcess -FilePath $launcher `
            -Arguments $launcherArguments
        $standardOutputRead = $launcherProcess.StandardOutput.ReadToEndAsync()
        $standardErrorRead = $launcherProcess.StandardError.ReadToEndAsync()
        $reportDeadline = [DateTime]::UtcNow.AddSeconds($StartupReportTimeoutSeconds)
        while (-not $launcherProcess.HasExited -and
               -not (Test-Path -LiteralPath $report -PathType Leaf) -and
               [DateTime]::UtcNow -lt $reportDeadline) {
            Start-Sleep -Milliseconds 500
            $launcherProcess.Refresh()
        }
        $startupTimedOut = -not $launcherProcess.HasExited -and
            -not (Test-Path -LiteralPath $report -PathType Leaf)
        if ($startupTimedOut) {
            try { $launcherProcess.Kill($true) } catch {
                Stop-Process -Id $launcherProcess.Id -Force -ErrorAction SilentlyContinue
            }
            $launcherProcess.WaitForExit()
            $launcherExit = 124
            Write-Warning ("COMSOL/MATLAB did not create the task report within " +
                "$StartupReportTimeoutSeconds seconds (attempt $attempt/$StartupAttempts).")
        } else {
            if (-not $launcherProcess.HasExited) { $launcherProcess.WaitForExit() }
            $launcherExit = $launcherProcess.ExitCode
        }
        $launcherStandardOutput = $standardOutputRead.GetAwaiter().GetResult()
        $launcherStandardError = $standardErrorRead.GetAwaiter().GetResult()

        if (Test-Path -LiteralPath $report -PathType Leaf) {
            $reportText = Get-Content -LiteralPath $report -Raw -Encoding UTF8
            $reportText
            if ($launcherExit -eq 0 -and $reportText -match '(?m)^STATUS=PASS$') {
                return
            }
            Stop-ComsolAttemptServers -Before $serversBeforeAttempt -Reason 'task failure'
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
        Stop-ComsolAttemptServers -Before $serversBeforeAttempt -Reason $noReportReason
        if ($attempt -lt $StartupAttempts) {
            Write-Warning ("COMSOL/MATLAB exited before the task report was created; " +
                "retrying clean startup in $StartupRetryDelaySeconds s " +
                "(attempt $($attempt + 1)/$StartupAttempts).")
            Start-Sleep -Seconds $StartupRetryDelaySeconds
        }
    }
}
finally {
    $env:MATLABPATH = $oldMatlabPath
    Remove-Item Env:COMSOL_MATLAB_TASK -ErrorAction SilentlyContinue
    Remove-Item Env:COMSOL_BOOTSTRAP_REPORT -ErrorAction SilentlyContinue
}

throw "LiveLink task did not create its report after $StartupAttempts clean startup attempts: $report"

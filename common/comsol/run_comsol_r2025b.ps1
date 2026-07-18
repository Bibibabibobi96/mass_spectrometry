param(
    [Parameter(Mandatory = $true)]
    [string]$TaskScript,

    [Parameter(Mandatory = $true)]
    [string]$ReportPath,

    [ValidateRange(1, 3)]
    [int]$StartupAttempts = 2,

    [ValidateRange(1, 30)]
    [int]$StartupRetryDelaySeconds = 5,

    [ValidateRange(0, 64)]
    [int]$ProcessorCount = 0,

    [ValidateSet('auto', 'scalable', 'native')]
    [string]$Allocator = 'auto'
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$bootstrapDir = Join-Path $PSScriptRoot 'livelink_r2025b'
$launcher = 'D:\COMSOL 6.4\COMSOL64\Multiphysics\bin\win64\comsolmphserver.exe'
$matlabRoot = 'C:\Program Files\MATLAB\R2025b\MatlabR2025b'

if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) {
    throw "COMSOL MATLAB launcher not found: $launcher"
}
if (-not (Test-Path -LiteralPath $matlabRoot -PathType Container)) {
    throw "MATLAB R2025b root not found: $matlabRoot"
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
        & $launcher @launcherArguments
        $launcherExit = $LASTEXITCODE

        if (Test-Path -LiteralPath $report -PathType Leaf) {
            $reportText = Get-Content -LiteralPath $report -Raw -Encoding UTF8
            $reportText
            if ($launcherExit -eq 0 -and $reportText -match '(?m)^STATUS=PASS$') {
                return
            }
            throw "R2025b LiveLink task failed (launcher exit $launcherExit)."
        }

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

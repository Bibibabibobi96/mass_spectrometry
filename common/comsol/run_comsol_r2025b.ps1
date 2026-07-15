param(
    [Parameter(Mandatory = $true)]
    [string]$TaskScript,

    [Parameter(Mandatory = $true)]
    [string]$ReportPath
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

    & $launcher -login auto matlab `
        -mlroot $matlabRoot `
        -nodesktop `
        -mlnosplash `
        -mlstartdir $repoRoot
    $launcherExit = $LASTEXITCODE
}
finally {
    $env:MATLABPATH = $oldMatlabPath
    Remove-Item Env:COMSOL_MATLAB_TASK -ErrorAction SilentlyContinue
    Remove-Item Env:COMSOL_BOOTSTRAP_REPORT -ErrorAction SilentlyContinue
}

if (-not (Test-Path -LiteralPath $report -PathType Leaf)) {
    throw "LiveLink task did not create its report: $report"
}
$reportText = Get-Content -LiteralPath $report -Raw -Encoding UTF8
$reportText
if ($launcherExit -ne 0 -or $reportText -notmatch '(?m)^STATUS=PASS$') {
    throw "R2025b LiveLink task failed (launcher exit $launcherExit)."
}

param(
    [Parameter(Mandatory = $true)]
    [string]$ReferenceCsv,

    [Parameter(Mandatory = $true)]
    [string]$CandidateCsv,

    [Parameter(Mandatory = $true)]
    [string]$ReportPath,

    [double]$MaxTofDifferenceUs = 0.001,
    [double]$MaxLandingDifferenceMm = 0.05
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$repoRoot = (Resolve-Path (Join-Path $projectRoot '..\..')).Path
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
$diagnostics = Join-Path $projectRoot 'analysis\solver_diagnostics.py'
& $python $diagnostics compare-particle-exports `
    --reference $ReferenceCsv --candidate $CandidateCsv --report $ReportPath `
    --max-tof-difference-us $MaxTofDifferenceUs `
    --max-landing-difference-mm $MaxLandingDifferenceMm
if ($LASTEXITCODE -ne 0) {
    throw 'Candidate particle result differs from the formal reference.'
}

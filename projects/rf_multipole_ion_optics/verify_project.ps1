param(
  [ValidateSet('Freshness','Core','Static','Formal')][string]$Level = 'Static',
  [ValidateSet('All','quadrupole','hexapole','octupole')][string]$StructuralVariant = 'All',
  [string]$PythonExe = '',
  [switch]$FreshnessPrevalidated
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$repoRoot = (Resolve-Path (Join-Path $projectRoot '..\..')).Path
$selectedVariants = if ($StructuralVariant -eq 'All') { @('quadrupole','hexapole','octupole') } else { @($StructuralVariant) }
$hostExecutionLease = $null
$hostExecutionLeaseSupport = Join-Path $repoRoot 'common\host_execution_lease.ps1'
if (Test-Path -LiteralPath $hostExecutionLeaseSupport -PathType Leaf) {
  . $hostExecutionLeaseSupport
  $hostExecutionLease = Enter-HostExecutionLease -Role GATE
}
try {
$python = if ($PythonExe) { [IO.Path]::GetFullPath($PythonExe) } elseif ($env:SIMULATION_PYTHON_EXE) { $env:SIMULATION_PYTHON_EXE } else { Join-Path $repoRoot '.venv\Scripts\python.exe' }
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw "Python 3.11 runtime missing: $python" }
if ($FreshnessPrevalidated -and $Level -eq 'Freshness') {
  throw 'FreshnessPrevalidated cannot be combined with Level=Freshness.'
}

if (-not $FreshnessPrevalidated) {
  Push-Location $repoRoot
  try {
    foreach ($variant in $selectedVariants) {
      & $python -m projects.rf_multipole_ion_optics.analysis.resolve_contract --structural-variant $variant --check
      if ($LASTEXITCODE -ne 0) { throw "Variant publication gate failed: $variant" }
    }
    if ('quadrupole' -in $selectedVariants) {
    & $python -m projects.rf_multipole_ion_optics.analysis.resolve_contract --check
    if ($LASTEXITCODE -ne 0) { throw 'Resolved-contract gate failed.' }
    & $python -m projects.rf_multipole_ion_optics.analysis.resolve_contract --profile interface --check
    if ($LASTEXITCODE -ne 0) { throw 'Interface-readiness contract gate failed.' }
    & $python -m projects.rf_multipole_ion_optics.analysis.resolve_contract --profile mass_filter --check
    if ($LASTEXITCODE -ne 0) { throw 'Mass-filter resolved contract gate failed.' }
    & $python -m projects.rf_multipole_ion_optics.analysis.sync_simion_geometry --check
    if ($LASTEXITCODE -ne 0) { throw 'SIMION geometry publication gate failed.' }
    & $python -m projects.rf_multipole_ion_optics.analysis.generate_official_particle_table --check `
      (Join-Path $projectRoot 'variants\quadrupole\config\particles\official_fixed_100.ion') --check-canonical `
      (Join-Path $projectRoot 'variants\quadrupole\config\particles\official_fixed_100_canonical.csv') --resolved-design `
      (Join-Path $projectRoot 'variants\quadrupole\config\resolved_design_official.json')
    if ($LASTEXITCODE -ne 0) { throw 'Paired-particle identity gate failed.' }
    }
  } finally { Pop-Location }
} else {
  "MULTIPOLE_FRESHNESS=PREVALIDATED STRUCTURAL_VARIANT=$StructuralVariant"
}
if ($Level -eq 'Freshness') {
  "PROJECT_GATE=PASS PROJECT=rf_multipole_ion_optics LEVEL=$Level STRUCTURAL_VARIANT=$StructuralVariant"
  return
}
if ('quadrupole' -in $selectedVariants) {
Push-Location $repoRoot
try {
  & $python -m `
    projects.rf_multipole_ion_optics.workflows.mass_filter_reference.theory `
    --check-mode
} finally { Pop-Location }
if ($LASTEXITCODE -ne 0) { throw 'Quadrupole L0 reference gate failed.' }
Push-Location $repoRoot
try {
  & $python -m `
    projects.rf_multipole_ion_optics.workflows.mass_filter_reference.run_finite_length `
    --check-contract
} finally { Pop-Location }
if ($LASTEXITCODE -ne 0) { throw 'Quadrupole mass-filter L1 contract gate failed.' }
& $python (Join-Path $projectRoot 'analysis\entry_aperture_l0.py') --check
if ($LASTEXITCODE -ne 0) { throw 'Entry-aperture L0 reference gate failed.' }
}
# Core is the no-solver, active-design contract gate.  It deliberately stops
# before the repository-wide RF analysis suite and PowerShell tree parse; those
# broader regressions remain part of Static integration verification.
if ($Level -eq 'Core') {
  "PROJECT_GATE=PASS PROJECT=rf_multipole_ion_optics LEVEL=$Level STRUCTURAL_VARIANT=$StructuralVariant"
  return
}

Push-Location $repoRoot
try {
  foreach ($variant in $selectedVariants) {
    $testDirectory = if ($variant -eq 'quadrupole') { 'analysis' } else { $variant }
    & $python -m unittest discover -s (Join-Path $projectRoot "tests\$testDirectory") -p 'test_*.py'
    if ($LASTEXITCODE -ne 0) { throw "Python variant tests failed: $variant" }
  }
} finally { Pop-Location }
$parseErrors = @()
Get-ChildItem -LiteralPath $projectRoot -Recurse -Filter '*.ps1' | ForEach-Object {
  $tokens = $null
  $fileErrors = $null
  [System.Management.Automation.Language.Parser]::ParseFile($_.FullName,[ref]$tokens,[ref]$fileErrors) | Out-Null
  if ($fileErrors) { $parseErrors += $fileErrors }
}
if ($parseErrors.Count -gt 0) { throw "PowerShell syntax gate failed: $($parseErrors -join '; ')" }

if ($Level -eq 'Formal') {
  throw "FORMAL_UNQUALIFIED STRUCTURAL_VARIANT=$($selectedVariants -join ','): current-owner qualification and applicable GUI/CAD closure are required separately for each selected structure; frozen historical qualifications retain their recorded identity."
}

"PROJECT_GATE=PASS PROJECT=rf_multipole_ion_optics LEVEL=$Level STRUCTURAL_VARIANT=$StructuralVariant"
} finally {
  if ($null -ne $hostExecutionLease) {
    Exit-HostExecutionLease -Lease $hostExecutionLease
  }
}

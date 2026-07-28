param(
  [ValidateSet('Freshness','Core','Static','Formal')][string]$Level = 'Static',
  [string]$PythonExe = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$repoRoot = (Resolve-Path (Join-Path $projectRoot '..\..')).Path
$python = if ($PythonExe) { [IO.Path]::GetFullPath($PythonExe) } else { Join-Path $repoRoot '.venv\Scripts\python.exe' }
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw "Python 3.11 runtime missing: $python" }

Push-Location $repoRoot
try {
  & $python -m projects.rf_quadrupole_collision_cooling.analysis.resolve_contract --check
  if ($LASTEXITCODE -ne 0) { throw 'Resolved-contract gate failed.' }
  & $python -m projects.rf_quadrupole_collision_cooling.analysis.resolve_contract --profile interface --check
  if ($LASTEXITCODE -ne 0) { throw 'Interface-readiness contract gate failed.' }
  & $python -m projects.rf_quadrupole_collision_cooling.analysis.resolve_contract --profile mass_filter --check
  if ($LASTEXITCODE -ne 0) { throw 'Mass-filter resolved contract gate failed.' }
  foreach ($registrationStage in @('s2')) {
    & $python -m projects.rf_quadrupole_collision_cooling.analysis.resolve_spatial_registration `
      --stage $registrationStage --check
    if ($LASTEXITCODE -ne 0) {
      throw "RF-to-oaTOF $registrationStage spatial-registration publication is stale."
    }
  }
  & $python -m projects.rf_quadrupole_collision_cooling.analysis.sync_simion_geometry --check
  if ($LASTEXITCODE -ne 0) { throw 'SIMION geometry publication gate failed.' }
  & $python -m projects.rf_quadrupole_collision_cooling.analysis.generate_official_particle_table --check `
    (Join-Path $projectRoot 'config\particles\official_fixed_100.ion') --check-canonical `
    (Join-Path $projectRoot 'config\particles\official_fixed_100_canonical.csv') --resolved-design `
    (Join-Path $projectRoot 'config\resolved_design_official.json')
  if ($LASTEXITCODE -ne 0) { throw 'Paired-particle identity gate failed.' }
  & $python -m common.multipole.runtime_profile --repo-root $repoRoot `
    --project-id rf_quadrupole_collision_cooling --runtime-profile-id functional_baseline `
    --output (Join-Path ([IO.Path]::GetTempPath()) 'rfquad_runtime_profile_gate.json')
  if ($LASTEXITCODE -ne 0) { throw 'Multipole runtime-profile gate failed.' }
} finally { Pop-Location }
if ($Level -eq 'Freshness') {
  "PROJECT_GATE=PASS PROJECT=rf_quadrupole_collision_cooling LEVEL=$Level"
  return
}
Push-Location $repoRoot
try {
  & $python -m `
    projects.rf_quadrupole_collision_cooling.workflows.mass_filter_reference.theory `
    --check-mode
} finally { Pop-Location }
if ($LASTEXITCODE -ne 0) { throw 'Quadrupole L0 reference gate failed.' }
Push-Location $repoRoot
try {
  & $python -m `
    projects.rf_quadrupole_collision_cooling.workflows.mass_filter_reference.run_finite_length `
    --check-contract
} finally { Pop-Location }
if ($LASTEXITCODE -ne 0) { throw 'Quadrupole mass-filter L1 contract gate failed.' }
& $python (Join-Path $projectRoot 'analysis\entry_aperture_l0.py') --check
if ($LASTEXITCODE -ne 0) { throw 'Entry-aperture L0 reference gate failed.' }
Push-Location $repoRoot
try {
  & $python -m projects.rf_quadrupole_collision_cooling.analysis.build_oatof_handoff `
    --check-contract `
    --resolved-registration (Join-Path $projectRoot 'config\resolved_rf_to_oatof_s2_spatial_registration.json')
} finally { Pop-Location }
if ($LASTEXITCODE -ne 0) { throw 'RF-to-oaTOF handoff contract gate failed.' }
$candidateValidators = @(
  'validate_field_performance_experiment.py',
  'validate_rf_continuous_shield.py',
  'validate_rf_hybrid_mesh.py',
  'validate_rf_energy_match.py',
  'validate_rf_piecewise_swept_mesh.py',
  'validate_rf_rod_region_swept_mesh.py',
  'validate_s2_passive_connector.py'
  'validate_s3_pulse_capture.py',
  'validate_spatial_registration_migration.py'
)
$previousPythonPath = $env:PYTHONPATH
try {
  $env:PYTHONPATH = $repoRoot
  foreach ($validator in $candidateValidators) {
    & $python (Join-Path $projectRoot "analysis\$validator")
    if ($LASTEXITCODE -ne 0) {
      throw "Candidate-contract static gate failed: $validator"
    }
  }
} finally {
  $env:PYTHONPATH = $previousPythonPath
}

# Core is the no-solver, active-design contract gate.  It deliberately stops
# before the repository-wide RF analysis suite and PowerShell tree parse; those
# broader regressions remain part of Static integration verification.
if ($Level -eq 'Core') {
  "PROJECT_GATE=PASS PROJECT=rf_quadrupole_collision_cooling LEVEL=$Level"
  return
}

& $python -m unittest discover -s (Join-Path $projectRoot 'tests\analysis') -p 'test_*.py'
if ($LASTEXITCODE -ne 0) { throw 'Python analysis tests failed.' }
$parseErrors = @()
Get-ChildItem -LiteralPath $projectRoot -Recurse -Filter '*.ps1' | ForEach-Object {
  $tokens = $null
  $fileErrors = $null
  [System.Management.Automation.Language.Parser]::ParseFile($_.FullName,[ref]$tokens,[ref]$fileErrors) | Out-Null
  if ($fileErrors) { $parseErrors += $fileErrors }
}
if ($parseErrors.Count -gt 0) { throw "PowerShell syntax gate failed: $($parseErrors -join '; ')" }

if ($Level -eq 'Formal') {
  throw 'Formal gate is intentionally unavailable until the component geometry and SolidWorks assembly are selected and synchronized.'
}

"PROJECT_GATE=PASS PROJECT=rf_quadrupole_collision_cooling LEVEL=$Level"

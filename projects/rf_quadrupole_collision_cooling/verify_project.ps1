param(
  [ValidateSet('Static','Candidate','Formal')][string]$Level = 'Static',
  [string]$PythonExe = '',
  [string]$ComsolRunLabel = '',
  [string]$SimionRunLabel = '',
  [string]$ComparisonLabel = '',
  [ValidateSet('transport_no_collision','transport_interface_readiness')]
  [string]$CandidateMode = 'transport_no_collision'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$repoRoot = (Resolve-Path (Join-Path $projectRoot '..\..')).Path
$python = if ($PythonExe) { [IO.Path]::GetFullPath($PythonExe) } else { Join-Path $repoRoot '.venv\Scripts\python.exe' }
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw "Python 3.11 runtime missing: $python" }

& $python (Join-Path $projectRoot 'analysis\resolve_contract.py') --check
if ($LASTEXITCODE -ne 0) { throw 'Resolved-contract gate failed.' }
& $python (Join-Path $projectRoot 'analysis\resolve_contract.py') --profile interface --check
if ($LASTEXITCODE -ne 0) { throw 'Interface-readiness contract gate failed.' }
& $python (Join-Path $projectRoot 'analysis\sync_simion_geometry.py') --check
if ($LASTEXITCODE -ne 0) { throw 'SIMION geometry publication gate failed.' }
& $python (Join-Path $projectRoot 'analysis\generate_official_particle_table.py') --check `
  (Join-Path $projectRoot 'config\particles\official_fixed_25.ion')
if ($LASTEXITCODE -ne 0) { throw 'Paired-particle identity gate failed.' }
& $python (Join-Path $projectRoot 'analysis\quadrupole_l0.py') --check-mode
if ($LASTEXITCODE -ne 0) { throw 'Quadrupole L0 reference gate failed.' }
& $python (Join-Path $projectRoot 'analysis\entry_aperture_l0.py') --check
if ($LASTEXITCODE -ne 0) { throw 'Entry-aperture L0 reference gate failed.' }
& $python (Join-Path $projectRoot 'analysis\build_oatof_handoff.py') --check-contract
if ($LASTEXITCODE -ne 0) { throw 'RF-to-oaTOF handoff contract gate failed.' }
& $python (Join-Path $projectRoot 'analysis\build_interface_handoff.py') --check-contract
if ($LASTEXITCODE -ne 0) { throw 'Two-boundary time-resolved interface contract gate failed.' }
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

if ($Level -eq 'Candidate') {
  if (-not $PSBoundParameters.ContainsKey('CandidateMode')) {
    throw 'Candidate gate requires an explicit CandidateMode.'
  }
  if ([string]::IsNullOrWhiteSpace($ComsolRunLabel) -or [string]::IsNullOrWhiteSpace($SimionRunLabel) -or
      [string]::IsNullOrWhiteSpace($ComparisonLabel)) {
    throw 'Candidate gate requires explicit ComsolRunLabel, SimionRunLabel, and ComparisonLabel.'
  }
  & (Join-Path $projectRoot 'tests\cross_solver\verify_transport_candidate.ps1') `
    -ComsolRunLabel $ComsolRunLabel -SimionRunLabel $SimionRunLabel -ComparisonLabel $ComparisonLabel `
    -Mode $CandidateMode -PythonExe $python
  if ($LASTEXITCODE -ne 0) { throw 'Cross-solver transport candidate gate failed.' }
}
elseif ($Level -eq 'Formal') {
  throw 'Formal gate is intentionally unavailable until the component geometry and SolidWorks assembly are selected and synchronized.'
}

"PROJECT_GATE=PASS PROJECT=rf_quadrupole_collision_cooling LEVEL=$Level"

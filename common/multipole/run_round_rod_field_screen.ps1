[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)]
  [string]$ProjectRoot,
  [string]$RunId = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRootPath = (Resolve-Path -LiteralPath $ProjectRoot).Path
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$workspaceRoot = Split-Path -Parent $repoRoot
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
$project = Get-Content -LiteralPath (Join-Path $projectRootPath 'config\project.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$projectId = [string]$project.project_id
& $python (Join-Path $repoRoot 'common\contracts\artifact_project.py') `
  --artifact-projects-root (Join-Path $workspaceRoot 'artifacts\projects') --project-id $projectId
if ($LASTEXITCODE -ne 0) { throw 'Multipole artifact project initialization failed.' }
if ([string]::IsNullOrWhiteSpace($RunId)) {
  $taskLabel = $projectId.Replace('_','-') + '-round-rod-screen'
  $RunId = (Get-Date -Format 'yyyyMMdd_HHmmss') + "__sim__comsol__${taskLabel}__l2"
}
& $python (Join-Path $repoRoot 'common\contracts\artifact_naming.py') run $RunId
if ($LASTEXITCODE -ne 0) { throw "Invalid run_id: $RunId" }

$runDir = Join-Path $workspaceRoot "artifacts\projects\$projectId\runs\$RunId"
if (Test-Path -LiteralPath $runDir) { throw "Run already exists: $runDir" }
$inputDir = Join-Path $runDir 'inputs'
$resultDir = Join-Path $runDir 'results'
$logDir = Join-Path $runDir 'logs'
New-Item -ItemType Directory -Force -Path $inputDir,$resultDir,$logDir | Out-Null
$baseline = Join-Path $inputDir 'baseline.json'
$familyOperating = Join-Path $inputDir 'family_operating_contract.json'
$contract = Join-Path $inputDir 'round_rod_field_screen.json'
Copy-Item -LiteralPath (Join-Path $projectRootPath 'config\baseline.json') -Destination $baseline
Copy-Item -LiteralPath (Join-Path $projectRootPath 'config\round_rod_field_screen.json') -Destination $contract
Push-Location $repoRoot
try {
  & $python -m common.multipole.resolve_family_operating_contract `
    --adapter high-order --baseline $baseline --output $familyOperating
  if ($LASTEXITCODE -ne 0) { throw 'Shared multipole operating-contract resolution failed.' }
} finally { Pop-Location }
$samples = Join-Path $resultDir 'round_rod_potential_samples.csv'
$metrics = Join-Path $resultDir 'round_rod_field_screen_metrics.json'
$report = Join-Path $logDir 'comsol_round_rod_field_screen.txt'
$summary = Join-Path $runDir 'summary.json'
$runConfig = Join-Path $runDir 'run_config.json'
$manifestWriter = Join-Path $repoRoot 'common\contracts\write_run_manifest.py'
$analysis = Join-Path $repoRoot 'common\multipole\analyze_round_rod_screen.py'
$task = Join-Path $repoRoot 'common\multipole\solve_round_rod_field_screen.m'

[ordered]@{
  schema_version = 1
  role = 'multipole_round_rod_field_screen_run_config'
  run_id = $RunId
  project = $projectId
  mode = 'round_rod_field_screen'
  project_root = $projectRootPath
  inputs = [ordered]@{
    baseline = $baseline
    family_operating_contract = $familyOperating
    field_screen = $contract
    comsol_task = $task
    analysis = $analysis
  }
  parameters = [ordered]@{ model_level = 'L2'; field_dimension = 2; particle_tracking = $false }
  formal_gate_passed = $false
} | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $runConfig -Encoding UTF8
[ordered]@{ schema_version=1; role='multipole_round_rod_field_screen_summary'; status='interrupted' } |
  ConvertTo-Json | Set-Content -LiteralPath $summary -Encoding UTF8
& $python $manifestWriter --run-config $runConfig --status interrupted --software 'COMSOL 6.4' --software 'MATLAB R2025b' --software 'Python 3.11' --output $summary
if ($LASTEXITCODE -ne 0) { throw 'Initial run manifest failed.' }

$environmentNames = @('MULTIPOLE_BASELINE','MULTIPOLE_FAMILY_OPERATING','MULTIPOLE_ROUND_ROD_SCREEN','MULTIPOLE_ROUND_ROD_SAMPLES')
$oldEnvironment = @{}
foreach ($name in $environmentNames) { $oldEnvironment[$name] = [Environment]::GetEnvironmentVariable($name) }
try {
  try {
    $env:MULTIPOLE_BASELINE = $baseline
    $env:MULTIPOLE_FAMILY_OPERATING = $familyOperating
    $env:MULTIPOLE_ROUND_ROD_SCREEN = $contract
    $env:MULTIPOLE_ROUND_ROD_SAMPLES = $samples
    & (Join-Path $repoRoot 'common\comsol\run_comsol_r2025b.ps1') -TaskScript $task -ReportPath $report
    if ($LASTEXITCODE -ne 0) { throw 'COMSOL round-rod field screen failed.' }
    & $python $analysis --samples $samples --contract $contract --output $metrics
    if ($LASTEXITCODE -ne 0) { throw 'Round-rod harmonic analysis failed.' }
    $result = Get-Content -LiteralPath $metrics -Raw -Encoding UTF8 | ConvertFrom-Json
    [ordered]@{
      schema_version = 1
      role = 'multipole_round_rod_field_screen_summary'
      status = 'success'
      project_id = $projectId
      model_level = 'L2'
      selected_rod_radius_ratio = $result.selected_candidate.rod_radius_ratio
      selected_rod_radius_mm = $result.selected_candidate.rod_radius_mm
      selected_parasitic_harmonic_score = $result.selected_candidate.parasitic_harmonic_score
      particle_tracking = $false
      formal_gate_passed = $false
    } | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $summary -Encoding UTF8
    & $python $manifestWriter --run-config $runConfig --status success --software 'COMSOL 6.4' --software 'MATLAB R2025b' --software 'Python 3.11' --output $samples --output $metrics --output $report --output $summary
    if ($LASTEXITCODE -ne 0) { throw 'Final run manifest failed.' }
    Write-Output "ROUND_ROD_L2=PASS PROJECT=$projectId RUN_ID=$RunId RATIO=$($result.selected_candidate.rod_radius_ratio)"
  } catch {
    [ordered]@{ schema_version=1; role='multipole_round_rod_field_screen_summary'; status='failed'; reason=$_.Exception.Message } |
      ConvertTo-Json | Set-Content -LiteralPath $summary -Encoding UTF8
    & $python $manifestWriter --run-config $runConfig --status failed --software 'COMSOL 6.4' --software 'MATLAB R2025b' --software 'Python 3.11' --output $summary
    throw
  }
} finally {
  foreach ($name in $environmentNames) { [Environment]::SetEnvironmentVariable($name, $oldEnvironment[$name]) }
}

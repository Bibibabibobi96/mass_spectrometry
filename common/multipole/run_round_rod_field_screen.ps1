[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)][string]$ProjectId,
  [Parameter(Mandatory = $true)][string]$DesignProfileId,
  [string]$RunId = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$workspaceRoot = Split-Path -Parent $repoRoot
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
$registryPreflight = Get-Content -LiteralPath (Join-Path $repoRoot 'config\project_registry.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$projectMatches = @($registryPreflight.projects | Where-Object { [string]$_.project_id -eq $ProjectId })
if ($projectMatches.Count -ne 1) { throw "ProjectId is not unique in the canonical project registry: $ProjectId" }
& $python (Join-Path $repoRoot 'common\contracts\artifact_project.py') `
  --artifact-projects-root (Join-Path $workspaceRoot 'artifacts\projects') --project-id $ProjectId
if ($LASTEXITCODE -ne 0) { throw 'Multipole artifact project initialization failed.' }
if ([string]::IsNullOrWhiteSpace($RunId)) {
  $taskLabel = $ProjectId.Replace('_','-') + '-' + $DesignProfileId + '-round-rod-screen'
  $RunId = (Get-Date -Format 'yyyyMMdd_HHmmss') + "__sim__comsol__${taskLabel}__l2"
}
& $python (Join-Path $repoRoot 'common\contracts\artifact_naming.py') run $RunId
if ($LASTEXITCODE -ne 0) { throw "Invalid run_id: $RunId" }

$runDir = Join-Path $workspaceRoot "artifacts\projects\$ProjectId\runs\$RunId"
if (Test-Path -LiteralPath $runDir) { throw "Run already exists: $runDir" }
$inputDir = Join-Path $runDir 'inputs'
$resultDir = Join-Path $runDir 'results'
$logDir = Join-Path $runDir 'logs'
New-Item -ItemType Directory -Force -Path $inputDir,$resultDir,$logDir | Out-Null
$profileResolution = Join-Path $inputDir 'design_profile_resolution.json'
$env:PYTHONPATH = $repoRoot
try {
  & $python -m common.multipole.design_profile --repo-root $repoRoot --project-id $ProjectId `
    --design-profile-id $DesignProfileId --output $profileResolution
  if ($LASTEXITCODE -ne 0) { throw 'Governed design profile resolution failed.' }
} finally { Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue }
$profile = Get-Content -LiteralPath $profileResolution -Raw -Encoding UTF8 | ConvertFrom-Json
$identity = $profile.profile.identity
$projectRootPath = [string]$profile.project_root
$registry = Join-Path $inputDir 'project_registry.json'
$descriptor = Join-Path $inputDir 'project.json'
$profiles = Join-Path $inputDir 'design_profiles.json'
$request = Join-Path $inputDir 'multipole_design_request.json'
$variables = Join-Path $inputDir 'design_variables.json'
$envelope = Join-Path $inputDir 'optimization_envelope.json'
Copy-Item -LiteralPath $profile.registry_path -Destination $registry
Copy-Item -LiteralPath $profile.descriptor_path -Destination $descriptor
Copy-Item -LiteralPath $profile.profiles_path -Destination $profiles
Copy-Item -LiteralPath $profile.paths.design_request -Destination $request
Copy-Item -LiteralPath $profile.paths.design_variables -Destination $variables
Copy-Item -LiteralPath $profile.paths.optimization_envelope -Destination $envelope
$resolved = Join-Path $inputDir 'multipole_resolved_design.json'
Push-Location $repoRoot
try {
  $env:PYTHONPATH = $repoRoot
  & $python -m common.multipole.compile_design_request --request $request `
    --design-variables $variables --optimization-envelope $envelope --output $resolved `
    --provenance-root $inputDir --project-id $ProjectId `
    --radial-order-n ([int]$identity.radial_order_n) `
    --electrode-count ([int]$identity.electrode_count)
  if ($LASTEXITCODE -ne 0) { throw 'Governed multipole design compilation failed.' }
} finally { Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue; Pop-Location }
$design = Get-Content -LiteralPath $resolved -Raw -Encoding UTF8 | ConvertFrom-Json
$resolvedHash = [string]$design.resolved_sha256
$contract = Join-Path $inputDir 'round_rod_field_screen.json'
Copy-Item -LiteralPath (Join-Path $projectRootPath 'config\round_rod_field_screen.json') -Destination $contract
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
  project = $ProjectId
  mode = 'round_rod_field_screen'
  project_root = $projectRootPath
  inputs = [ordered]@{
    project_registry = $registry
    project_descriptor = $descriptor
    design_profiles = $profiles
    design_profile_resolution = $profileResolution
    design_request = $request
    design_variables = $variables
    optimization_envelope = $envelope
    multipole_resolved_design = $resolved
    field_screen = $contract
    comsol_task = $task
    analysis = $analysis
  }
  parameters = [ordered]@{
    model_level = 'L2'
    design_profile_id = $DesignProfileId
    parent_resolved_design_sha256 = $resolvedHash
    field_dimension = 2
    particle_tracking = $false
  }
  formal_gate_passed = $false
} | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $runConfig -Encoding UTF8
[ordered]@{ schema_version=1; role='multipole_round_rod_field_screen_summary'; status='interrupted' } |
  ConvertTo-Json | Set-Content -LiteralPath $summary -Encoding UTF8
& $python $manifestWriter --run-config $runConfig --status interrupted --software 'COMSOL 6.4' --software 'MATLAB R2025b' --software 'Python 3.11' --output $summary
if ($LASTEXITCODE -ne 0) { throw 'Initial run manifest failed.' }

$environmentNames = @('MULTIPOLE_RESOLVED_DESIGN','MULTIPOLE_ROUND_ROD_SCREEN','MULTIPOLE_ROUND_ROD_SAMPLES')
$oldEnvironment = @{}
foreach ($name in $environmentNames) { $oldEnvironment[$name] = [Environment]::GetEnvironmentVariable($name) }
try {
  try {
    $env:MULTIPOLE_RESOLVED_DESIGN = $resolved
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
      project_id = $ProjectId
      design_profile_id = $DesignProfileId
      parent_resolved_design_sha256 = $resolvedHash
      model_level = 'L2'
      candidate_count = @($result.candidates).Count
      particle_tracking = $false
      formal_gate_passed = $false
    } | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $summary -Encoding UTF8
    & $python $manifestWriter --run-config $runConfig --status success --software 'COMSOL 6.4' --software 'MATLAB R2025b' --software 'Python 3.11' --output $samples --output $metrics --output $report --output $summary
    if ($LASTEXITCODE -ne 0) { throw 'Final run manifest failed.' }
    Write-Output "ROUND_ROD_L2=PASS PROJECT=$ProjectId PROFILE=$DesignProfileId RUN_ID=$RunId PARENT_SHA256=$resolvedHash CANDIDATES=$(@($result.candidates).Count)"
  } catch {
    [ordered]@{ schema_version=1; role='multipole_round_rod_field_screen_summary'; status='failed'; reason=$_.Exception.Message } |
      ConvertTo-Json | Set-Content -LiteralPath $summary -Encoding UTF8
    & $python $manifestWriter --run-config $runConfig --status failed --software 'COMSOL 6.4' --software 'MATLAB R2025b' --software 'Python 3.11' --output $summary
    throw
  }
} finally {
  foreach ($name in $environmentNames) { [Environment]::SetEnvironmentVariable($name, $oldEnvironment[$name]) }
}

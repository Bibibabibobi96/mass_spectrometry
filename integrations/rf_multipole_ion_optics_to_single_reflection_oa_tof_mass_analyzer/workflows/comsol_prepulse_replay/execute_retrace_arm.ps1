[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$RunId,
  [Parameter(Mandatory)][string]$ArmPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$integrationRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$repoRoot = (Resolve-Path (Join-Path $integrationRoot '..\..')).Path
$workspaceRoot = Split-Path -Parent $repoRoot
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
$artifactRoot = Join-Path $workspaceRoot `
  'artifacts\projects\single_reflection_oa_tof_mass_analyzer'
& $python (Join-Path $repoRoot 'common\contracts\artifact_naming.py') run $RunId
if ($LASTEXITCODE -ne 0) { throw 'COMSOL retrace RunId is invalid.' }
$runDir = Join-Path $artifactRoot "runs\$RunId"
if (Test-Path -LiteralPath $runDir) { throw "Run already exists: $runDir" }
$sourceArm = (Resolve-Path -LiteralPath $ArmPath).Path
$armSourceDocument = Get-Content -LiteralPath $sourceArm -Raw -Encoding UTF8 |
  ConvertFrom-Json
$declaredOutputRoot = [IO.Path]::GetFullPath([string]$armSourceDocument.output_root)
$declaredOutputModel = [IO.Path]::GetFullPath([string]$armSourceDocument.output_model)
$expectedOutputRoot = [IO.Path]::GetFullPath((Join-Path $runDir 'results'))
$expectedOutputModel = [IO.Path]::GetFullPath((Join-Path $runDir 'comsol\retrace.mph'))
if (-not $declaredOutputRoot.Equals($expectedOutputRoot,[StringComparison]::OrdinalIgnoreCase) -or
    -not $declaredOutputModel.Equals($expectedOutputModel,[StringComparison]::OrdinalIgnoreCase)) {
  throw 'Retrace arm outputs must be the exact run-local results and COMSOL model paths.'
}
$inputDir = Join-Path $runDir 'inputs'
$resultDir = $expectedOutputRoot
$comsolDir = Split-Path -Parent $expectedOutputModel
$logDir = Join-Path $runDir 'logs'
New-Item -ItemType Directory -Path $inputDir,$resultDir,$comsolDir,$logDir | Out-Null
. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')
$arm = Copy-VerifiedRunInput -Source $sourceArm -Destination (Join-Path $inputDir 'retrace_arm.json')
$document = Get-Content -LiteralPath $arm -Raw -Encoding UTF8 | ConvertFrom-Json
$plan = Join-Path $inputDir 'retrace_execution_plan.json'
& $python -m integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.comsol_retrace_contract `
  validate-arm --arm $arm --plan-output $plan
if ($LASTEXITCODE -ne 0) { throw 'COMSOL retrace arm contract failed.' }
$execution = Get-Content -LiteralPath $plan -Raw -Encoding UTF8 | ConvertFrom-Json
if ([bool]$execution.mesh_rebuild) { throw 'Retrace core refuses geometry or mesh rebuilds.' }
$runConfig = Join-Path $runDir 'run_config.json'
$summary = Join-Path $runDir 'summary.json'
$manifest = Join-Path $runDir 'run_manifest.json'
$software = @('COMSOL 6.4','MATLAB R2025b','Python 3.11')
[ordered]@{
  schema_version=1;run_id=$RunId;project='single_reflection_oa_tof_mass_analyzer'
  mode='rf_oatof_comsol_declarative_retrace_arm';project_root=$repoRoot
  inputs=[ordered]@{retrace_arm=$arm;execution_plan=$plan}
  parameters=[ordered]@{
    arm_id=$document.arm_id;change_class=$document.change_class
    mesh_rebuilt=$false;electrostatics_rerun=[bool]$execution.electrostatics
    particle_solve=$true
  }
  formal_gate_passed=$false
} | ConvertTo-Json -Depth 7 | Set-Content -LiteralPath $runConfig -Encoding UTF8
[ordered]@{
  schema_version=1;role='rf_oatof_comsol_retrace_summary';status='interrupted'
  reason='Frozen arm validated; COMSOL retrace not complete.'
} | ConvertTo-Json | Set-Content -LiteralPath $summary -Encoding UTF8
Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $runConfig `
  -Status interrupted -Software $software -Outputs @($summary)

$report = Join-Path $logDir 'comsol_retrace_report.txt'
$task = Join-Path $integrationRoot 'stages\comsol\run_retrace_arm.m'
$names = @('RF_OATOF_COMSOL_RETRACE_ARM','RF_OATOF_COMSOL_RETRACE_REPO_ROOT')
$saved = @{}
try {
  foreach ($name in $names) {
    $saved[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
  }
  try {
    $env:RF_OATOF_COMSOL_RETRACE_ARM = $arm
    $env:RF_OATOF_COMSOL_RETRACE_REPO_ROOT = $repoRoot
    & (Join-Path $repoRoot 'common\comsol\run_comsol_r2025b.ps1') `
      -TaskScript $task -ReportPath $report
    if ($LASTEXITCODE -ne 0) { throw 'COMSOL retrace arm failed.' }
  } finally {
    foreach ($name in $names) {
      [Environment]::SetEnvironmentVariable($name, $saved[$name], 'Process')
    }
  }
  $census = Join-Path $resultDir 'particle_census.csv'
  $particles = Join-Path $resultDir 'particles.csv'
  foreach ($path in @($report,$census,$particles,$expectedOutputModel)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
      throw "COMSOL retrace required output is missing: $path"
    }
  }
  $rows = @(Import-Csv -LiteralPath $census)
  $detected = @($rows | Where-Object { $_.status -eq 'hit' }).Count
  [ordered]@{
    schema_version=1;role='rf_oatof_comsol_retrace_summary';status='success'
    arm_id=$document.arm_id;change_class=$document.change_class
    particles=$rows.Count;detected=$detected;mesh_rebuilt=$false
    electrostatics_rerun=[bool]$execution.electrostatics;particle_solve=$true
    formal_gate_passed=$false
  } | ConvertTo-Json | Set-Content -LiteralPath $summary -Encoding UTF8
  $outputs = @($summary,$report,$expectedOutputModel) + @(
    Get-ChildItem -LiteralPath $resultDir -Recurse -File |
      Select-Object -ExpandProperty FullName
  )
  Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $runConfig `
    -Manifest $manifest -Status success -Software $software `
    -Outputs @($outputs | Select-Object -Unique)
  Write-Output "COMSOL_RETRACE_ARM=PASS RUN_ID=$RunId ARM_ID=$($document.arm_id)"
} catch {
  if (Test-Path -LiteralPath $runConfig) {
    Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig `
      -Summary $summary -SummaryRole 'rf_oatof_comsol_retrace_summary' `
      -Reason $_.Exception.Message -Software $software
  }
  throw
}

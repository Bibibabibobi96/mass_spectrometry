[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)]
  [string]$RunId,
  [string]$PythonExe = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$projectRoot = $PSScriptRoot
$repoRoot = (Resolve-Path (Join-Path $projectRoot '..\..')).Path
$workspaceRoot = Split-Path -Parent $repoRoot
$artifactRoot = Join-Path $workspaceRoot 'artifacts\projects\wehnelt_electron_gun'
$python = if ($PythonExe) { [IO.Path]::GetFullPath($PythonExe) } else { Join-Path $repoRoot '.venv\Scripts\python.exe' }
$software = @('COMSOL 6.4 via MATLAB R2025b')
. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')

function Get-FileSha256 {
  [CmdletBinding()]
  param([Parameter(Mandatory = $true)][string]$Path)
  $stream = [IO.File]::OpenRead($Path)
  $algorithm = [Security.Cryptography.SHA256]::Create()
  try {
    return [BitConverter]::ToString($algorithm.ComputeHash($stream)).Replace('-','')
  } finally {
    $algorithm.Dispose()
    $stream.Dispose()
  }
}

function Add-FrozenInput {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory = $true)][string]$Name,
    [Parameter(Mandatory = $true)][string]$Source,
    [Parameter(Mandatory = $true)][string]$Destination,
    [Parameter(Mandatory = $true)][System.Collections.IDictionary]$Inputs
  )
  $destinationParent = Split-Path -Parent $Destination
  if (-not (Test-Path -LiteralPath $destinationParent -PathType Container)) {
    New-Item -ItemType Directory -Force -Path $destinationParent | Out-Null
  }
  Copy-Item -LiteralPath $Source -Destination $Destination
  if ((Get-FileSha256 -Path $Source) -ne (Get-FileSha256 -Path $Destination)) {
    throw "Frozen Wehnelt input differs from its source: $Source"
  }
  $Inputs[$Name] = $Destination
}

function Get-ExistingRunOutputs {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory = $true)][string]$RunDirectory,
    [Parameter(Mandatory = $true)][string]$InputDirectory
  )
  $excluded = @(
    [IO.Path]::GetFullPath((Join-Path $RunDirectory 'run_config.json')),
    [IO.Path]::GetFullPath((Join-Path $RunDirectory 'run_manifest.json'))
  )
  return @(
    Get-ChildItem -LiteralPath $RunDirectory -Recurse -File |
      Where-Object {
        -not $_.FullName.StartsWith(
          [IO.Path]::GetFullPath($InputDirectory) + [IO.Path]::DirectorySeparatorChar,
          [StringComparison]::OrdinalIgnoreCase
        ) -and $excluded -notcontains $_.FullName
      } |
      Sort-Object FullName |
      ForEach-Object { $_.FullName }
  )
}

function New-BuildSummary {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory = $true)][ValidateSet('success','failed','interrupted')]
    [string]$Status,
    [Parameter(Mandatory = $true)][string]$Reason,
    [Parameter(Mandatory = $true)][string]$FailureStage,
    [string]$ReportPath = ''
  )
  $reportText = if (-not [string]::IsNullOrWhiteSpace($ReportPath) -and
      (Test-Path -LiteralPath $ReportPath -PathType Leaf)) {
    Get-Content -LiteralPath $ReportPath -Raw -Encoding UTF8
  } else { '' }
  $staticGatePassed = @(
    'commercial_wrapper_pending','commercial_wrapper','report_validation',
    'manifest_finalization','none'
  ) -contains $FailureStage
  $commercialWrapperStarted = @(
    'commercial_wrapper','report_validation','manifest_finalization','none'
  ) -contains $FailureStage
  $commercialWrapperCompleted = @(
    'report_validation','manifest_finalization','none'
  ) -contains $FailureStage
  return [ordered]@{
    schema_version = 1
    role = 'wehnelt_build_only_smoke_summary'
    status = $Status
    reason = $Reason
    failure_stage = $FailureStage
    threshold_result_eligible = $false
    candidate_evidence_allowed = $false
    formal_asset_modified = $false
    formal_gate_passed = $false
    static_gate_passed = $staticGatePassed
    commercial_wrapper_started = $commercialWrapperStarted
    commercial_wrapper_completed = $commercialWrapperCompleted
    geometry_built = $reportText -match '(?m)^GEOMETRY_BUILT=true$'
    mesh_built = $reportText -match '(?m)^MESH_BUILT=true$'
    electrostatics_solved = $reportText -match '(?m)^ELECTROSTATICS_SOLVED=true$'
    cpt_tree_built = $reportText -match '(?m)^CPT_TREE_BUILT=true$'
    particle_tracing_solved = $reportText -match '(?m)^PARTICLE_TRACING_SOLVED=true$'
    contract_loaded = $reportText -match '(?m)^CONTRACT_LOADED=true$'
    parameter_bindings_verified = $reportText -match '(?m)^PARAMETER_BINDINGS_VERIFIED=true$'
  }
}

$package = New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot `
  -RunId $RunId -Project 'wehnelt_electron_gun' -Mode 'build_only_smoke' `
  -Software $software -AdditionalDirectories @('comsol')
$manifestPath = Join-Path $package.run_dir 'run_manifest.json'
$environmentNames = @('WEHNELT_RUN_ID','WEHNELT_ARTIFACT_ROOT')
$savedEnvironment = Save-RunEnvironment -Names $environmentNames
$report = Join-Path $package.log_dir 'build_only_report.txt'
$wrapperLog = Join-Path $package.log_dir 'commercial_wrapper.log'
$geometryModel = Join-Path $package.run_dir 'comsol\ElectronGun_CoilT.mph'
$electrostaticModel = Join-Path $package.run_dir 'comsol\ElectronGun_CoilT_ES.mph'
$cptModel = Join-Path $package.run_dir 'comsol\wehnelt_electron_gun__model.mph'
$failureStage = 'run_initialized'
$frozenInputs = [ordered]@{}
$manifestRepoRoot = $repoRoot
$runConfig = [ordered]@{
  schema_version = 1
  run_id = $RunId
  project = 'wehnelt_electron_gun'
  mode = 'build_only_smoke'
  project_root = $projectRoot
  inputs = $frozenInputs
  parameters = [ordered]@{
    execution_mode = 'build_only'
    evidence_particle_count = 1
    mesh_build_required = $true
    electrostatics_solver_run = $false
    particle_solver_run = $false
    candidate_evidence_allowed = $false
    formal_asset_modified = $false
    lifecycle_stage = $failureStage
  }
  formal_gate_passed = $false
}

Write-RunJson -Value $runConfig -Path $package.run_config
Write-RunJson -Path $package.summary -Value (
  New-BuildSummary -Status interrupted `
    -Reason 'Run initialized; task-specific inputs are not frozen yet.' `
    -FailureStage $failureStage
)
Write-VerifiedRunManifest -Python $package.python -RepoRoot $manifestRepoRoot `
  -RunConfig $package.run_config -Manifest $manifestPath -Status interrupted `
  -Software $software -Outputs @($package.summary)

try {
  $failureStage = 'input_freeze'
  $codeRoot = Join-Path $package.input_dir 'code'
  $infrastructureRoot = Join-Path $package.input_dir 'infrastructure'
  New-Item -ItemType Directory -Force -Path $codeRoot,$infrastructureRoot | Out-Null

  $projectFrozenFiles = [ordered]@{
    runner = 'run_build_only_smoke.ps1'
    task_script = 'tests\comsol\test_build_only.m'
    paths = 'egun_paths.m'
    contract_loader = 'load_wehnelt_contract.m'
    parameter_binding = 'apply_wehnelt_contract_parameters.m'
    phase1 = 'phase1_geometry_coil_transverse.m'
    phase2 = 'phase2_electrostatics_coil_transverse.m'
    phase4 = 'phase4_thermal_emission_coil_transverse.m'
    baseline = 'config\baseline.json'
    numerical_modes = 'config\numerical_modes.json'
    resolved_contract = 'config\resolved_model.json'
    mode = 'config\modes\build_only_smoke.json'
    execution_profiles = 'config\execution_profiles.json'
    project_descriptor = 'config\project.json'
    resolver = 'analysis\resolve_contract.py'
    static_gate = 'verify_project.ps1'
  }
  foreach ($entry in $projectFrozenFiles.GetEnumerator()) {
    Add-FrozenInput -Name $entry.Key `
      -Source (Join-Path $projectRoot $entry.Value) `
      -Destination (Join-Path $codeRoot $entry.Value) -Inputs $frozenInputs
  }

  $commonFrozenFiles = [ordered]@{
    artifact_support = 'common\contracts\run_artifact_support.ps1'
    manifest_writer = 'common\contracts\write_run_manifest.py'
    manifest_verifier = 'common\contracts\verify_run_manifest.py'
    artifact_naming = 'common\contracts\artifact_naming.py'
    file_identity = 'common\contracts\file_identity.py'
    comsol_runner = 'common\comsol\run_comsol_r2025b.ps1'
    comsol_launcher_resolver = 'common\comsol\resolve_comsol_64.ps1'
    comsol_failure_classifier = 'common\comsol\livelink_failure_classification.ps1'
    comsol_environment = 'common\comsol\livelink_environment.ps1'
    comsol_startup = 'common\comsol\livelink_r2025b\comsolstartup.m'
  }
  foreach ($entry in $commonFrozenFiles.GetEnumerator()) {
    Add-FrozenInput -Name $entry.Key `
      -Source (Join-Path $repoRoot $entry.Value) `
      -Destination (Join-Path $infrastructureRoot $entry.Value) -Inputs $frozenInputs
  }

  $runConfig.inputs = $frozenInputs
  $runConfig.parameters.lifecycle_stage = 'inputs_frozen'
  Write-RunJson -Value $runConfig -Path $package.run_config
  . $frozenInputs.artifact_support
  $manifestRepoRoot = $infrastructureRoot
  Write-RunJson -Path $package.summary -Value (
    New-BuildSummary -Status interrupted `
      -Reason 'Inputs are frozen; the Static gate has not completed.' `
      -FailureStage 'static_gate_pending'
  )
  Write-VerifiedRunManifest -Python $package.python -RepoRoot $manifestRepoRoot `
    -RunConfig $package.run_config -Manifest $manifestPath -Status interrupted `
    -Software $software -Outputs (Get-ExistingRunOutputs `
      -RunDirectory $package.run_dir -InputDirectory $package.input_dir)

  $failureStage = 'static_gate'
  & (Join-Path $projectRoot 'verify_project.ps1') -PythonExe $package.python
  if ($LASTEXITCODE -ne 0) {
    throw 'Wehnelt Static gate failed before the commercial build.'
  }

  $failureStage = 'commercial_wrapper_pending'
  $runConfig.parameters.lifecycle_stage = $failureStage
  Write-RunJson -Value $runConfig -Path $package.run_config
  Write-RunJson -Path $package.summary -Value (
    New-BuildSummary -Status interrupted `
      -Reason 'Static gate passed; the commercial wrapper has not reached a terminal state.' `
      -FailureStage $failureStage
  )
  Write-VerifiedRunManifest -Python $package.python -RepoRoot $manifestRepoRoot `
    -RunConfig $package.run_config -Manifest $manifestPath -Status interrupted `
    -Software $software -Outputs @($package.summary)

  $failureStage = 'commercial_wrapper'
  Set-Content -LiteralPath $wrapperLog -Encoding UTF8 -Value @(
    "WRAPPER_ENTRY=$($frozenInputs.comsol_runner)"
    "TASK_SCRIPT=$($frozenInputs.task_script)"
    "REPORT_PATH=$report"
    'STREAM_CAPTURE=all_powershell_streams_merged'
    "STARTED_AT_UTC=$([DateTime]::UtcNow.ToString('o'))"
    'TERMINAL_STATE=pending'
  )
  $env:WEHNELT_RUN_ID = $RunId
  $env:WEHNELT_ARTIFACT_ROOT = $artifactRoot
  try {
    & $frozenInputs.comsol_runner -TaskScript $frozenInputs.task_script `
      -ReportPath $report *>&1 |
      Tee-Object -LiteralPath $wrapperLog -Append
    $wrapperExitCode = $LASTEXITCODE
    Add-Content -LiteralPath $wrapperLog -Encoding UTF8 -Value @(
      "WRAPPER_EXIT_CODE=$wrapperExitCode"
      "FINISHED_AT_UTC=$([DateTime]::UtcNow.ToString('o'))"
      'TERMINAL_STATE=returned'
    )
    if ($wrapperExitCode -ne 0) {
      throw "Wehnelt R2025b/COMSOL build-only task exited with code $wrapperExitCode."
    }
  } catch {
    Add-Content -LiteralPath $wrapperLog -Encoding UTF8 -Value @(
      "WRAPPER_EXCEPTION=$($_.Exception.Message)"
      "FINISHED_AT_UTC=$([DateTime]::UtcNow.ToString('o'))"
      'TERMINAL_STATE=failed'
    )
    throw
  }

  $failureStage = 'report_validation'
  foreach ($required in @($report,$geometryModel,$electrostaticModel,$cptModel)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
      throw "Wehnelt build-only output is missing: $required"
    }
  }
  $reportText = Get-Content -LiteralPath $report -Raw -Encoding UTF8
  foreach ($token in @(
      'GEOMETRY_BUILT=true','MESH_BUILT=true','ELECTROSTATICS_SOLVED=false',
      'CPT_TREE_BUILT=true','PARTICLE_TRACING_SOLVED=false',
      'CONTRACT_LOADED=true','CONTRACT_PROJECT_ID=wehnelt_electron_gun',
      'SELECTED_MODE_ID=build_only_smoke',
      'PARAMETER_BINDINGS_VERIFIED=true',
      'CANDIDATE_EVIDENCE_ALLOWED=false','STATUS=PASS')) {
    if ($reportText -notmatch [regex]::Escape($token)) {
      throw "Wehnelt build-only report is missing required state: $token"
    }
  }

  $failureStage = 'manifest_finalization'
  $runConfig.parameters.lifecycle_stage = 'completed'
  Write-RunJson -Value $runConfig -Path $package.run_config
  $successSummary = New-BuildSummary -Status success `
    -Reason 'The governed build-only workflow completed.' -FailureStage 'none' `
    -ReportPath $report
  $successSummary['geometry_model'] = 'comsol/ElectronGun_CoilT.mph'
  $successSummary['electrostatic_model'] = 'comsol/ElectronGun_CoilT_ES.mph'
  $successSummary['cpt_model'] = 'comsol/wehnelt_electron_gun__model.mph'
  $successSummary['report'] = 'logs/build_only_report.txt'
  $successSummary['wrapper_log'] = 'logs/commercial_wrapper.log'
  Write-RunJson -Path $package.summary -Value $successSummary
  Write-VerifiedRunManifest -Python $package.python -RepoRoot $manifestRepoRoot `
    -RunConfig $package.run_config -Manifest $manifestPath -Status success `
    -Software $software -Outputs (Get-ExistingRunOutputs `
      -RunDirectory $package.run_dir -InputDirectory $package.input_dir)
  Write-Output "WEHNELT_BUILD_ONLY=PASS RUN_ID=$RunId RUN_DIR=$($package.run_dir)"
} catch {
  $reason = $_.Exception.Message
  $knownInputs = @($frozenInputs.Values | ForEach-Object {
    [IO.Path]::GetFullPath([string]$_)
  })
  $recoveredIndex = 0
  foreach ($file in Get-ChildItem -LiteralPath $package.input_dir -Recurse -File |
      Sort-Object FullName) {
    if ($knownInputs -notcontains $file.FullName) {
      $recoveredIndex += 1
      $frozenInputs[("recovered_input_{0:D3}" -f $recoveredIndex)] = $file.FullName
    }
  }
  $runConfig.inputs = $frozenInputs
  $runConfig.parameters.lifecycle_stage = 'failed'
  Write-RunJson -Value $runConfig -Path $package.run_config
  Write-RunJson -Path $package.summary -Value (
    New-BuildSummary -Status failed -Reason $reason `
      -FailureStage $failureStage -ReportPath $report
  )
  $outputs = Get-ExistingRunOutputs `
    -RunDirectory $package.run_dir -InputDirectory $package.input_dir
  Write-VerifiedRunManifest -Python $package.python -RepoRoot $manifestRepoRoot `
    -RunConfig $package.run_config -Manifest $manifestPath -Status failed `
    -Software $software -Outputs $outputs
  throw
} finally {
  Restore-RunEnvironment -Names $environmentNames -Snapshot $savedEnvironment
}

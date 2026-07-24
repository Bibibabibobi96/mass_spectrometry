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

$bootstrapFiles = [ordered]@{
  powershell_runtime_gate = 'common\require_powershell7.ps1'
  artifact_support = 'common\contracts\run_artifact_support.ps1'
  manifest_writer = 'common\contracts\write_run_manifest.py'
  manifest_verifier = 'common\contracts\verify_run_manifest.py'
  artifact_naming = 'common\contracts\artifact_naming.py'
  file_identity = 'common\contracts\file_identity.py'
  particle_physics = 'common\contracts\particle_physics.py'
}
$bootstrapIdentity = [ordered]@{}
foreach ($entry in $bootstrapFiles.GetEnumerator()) {
  $source = Join-Path $repoRoot $entry.Value
  $bootstrapIdentity[$entry.Key] = [ordered]@{
    source_repo_path = $entry.Value.Replace('\','/')
    sha256 = Get-FileSha256 -Path $source
  }
}
. (Join-Path $repoRoot $bootstrapFiles.artifact_support)

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

function Assert-BuildOnlyModeDescriptor {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory = $true)][string]$Path,
    [Parameter(Mandatory = $true)][string]$ResolvedPath,
    [Parameter(Mandatory = $true)][string]$ExecutionProfilesPath
  )
  $mode = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 |
    ConvertFrom-Json -AsHashtable
  $expectedKeys = @(
    'schema_version','mode','status','numerical_contract','claim_limit'
  )
  $keyDifferences = @(Compare-Object `
    -ReferenceObject @($expectedKeys | Sort-Object) `
    -DifferenceObject @($mode.Keys | Sort-Object))
  if ($keyDifferences.Count -ne 0) {
    throw "Build-only mode descriptor has unexpected fields: $Path"
  }
  if ($mode.schema_version -ne 1 -or
      $mode.mode -cne 'build_only_smoke' -or
      $mode.status -cne 'prototype' -or
      $mode.numerical_contract -cne '../numerical_modes.json#/modes/build_only_smoke' -or
      $mode.claim_limit -cne 'Build and GUI-binding smoke only; no solver, Candidate, Formal, or collection-efficiency evidence.') {
    throw "Build-only mode descriptor differs from the governed smoke contract: $Path"
  }
  $resolved = Get-Content -LiteralPath $ResolvedPath -Raw -Encoding UTF8 |
    ConvertFrom-Json -AsHashtable
  if ($resolved.selected_mode_id -cne $mode.mode -or
      $resolved.numerical.execution_mode -cne 'build_only') {
    throw 'Build-only mode descriptor differs from the frozen resolved contract.'
  }
  $profiles = Get-Content -LiteralPath $ExecutionProfilesPath -Raw -Encoding UTF8 |
    ConvertFrom-Json -AsHashtable
  $matchingProfiles = @($profiles.profiles | Where-Object { $_.mode -ceq $mode.mode })
  $evidenceLevels = @($matchingProfiles | ForEach-Object { $_.evidence_levels })
  $runnerSteps = @($matchingProfiles | ForEach-Object { $_.steps } | Where-Object {
      $_.entrypoint -ceq 'run_build_only_smoke.ps1'
    })
  if ($matchingProfiles.Count -ne 1 -or
      $evidenceLevels.Count -ne 1 -or
      $evidenceLevels[0] -cne 'plan' -or
      $runnerSteps.Count -ne 1) {
    throw 'Build-only mode descriptor does not have one matching governed execution profile.'
  }
}

function Read-BuildOnlyReport {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory = $true)][string]$Path,
    [Parameter(Mandatory = $true)][System.Collections.IDictionary]$Expected
  )
  if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
    throw "Wehnelt build-only report is missing: $Path"
  }
  $values = [ordered]@{}
  $lineNumber = 0
  foreach ($line in Get-Content -LiteralPath $Path -Encoding UTF8) {
    $lineNumber += 1
    if ([string]::IsNullOrWhiteSpace($line)) {
      continue
    }
    if ($line -cnotmatch '^([A-Z][A-Z0-9_]*)=(.*)$') {
      throw "Malformed build-only report line $lineNumber."
    }
    $key = $Matches[1]
    $value = $Matches[2]
    if (-not $Expected.Contains($key)) {
      throw "Unknown build-only report key at line ${lineNumber}: $key"
    }
    if ($values.Contains($key)) {
      throw "Duplicate build-only report key at line ${lineNumber}: $key"
    }
    $values[$key] = $value
  }
  foreach ($entry in $Expected.GetEnumerator()) {
    if (-not $values.Contains($entry.Key)) {
      throw "Build-only report is missing required key: $($entry.Key)"
    }
    if ([string]$values[$entry.Key] -cne [string]$entry.Value) {
      throw "Build-only report value mismatch for $($entry.Key)."
    }
  }
  return $values
}

function Invoke-VerifiedRecordTransition {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory = $true)][string[]]$Paths,
    [Parameter(Mandatory = $true)][scriptblock]$Action
  )
  $snapshots = [ordered]@{}
  foreach ($path in $Paths) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
      throw "Cannot transition a run record without its verified prestate file: $path"
    }
    $snapshots[$path] = [IO.File]::ReadAllBytes($path)
  }
  try {
    & $Action
  } catch {
    $transitionError = $_
    foreach ($entry in $snapshots.GetEnumerator()) {
      [IO.File]::WriteAllBytes([string]$entry.Key, [byte[]]$entry.Value)
    }
    throw $transitionError
  }
}

function Assert-FrozenInputSet {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory = $true)][string]$InputDirectory,
    [Parameter(Mandatory = $true)][System.Collections.IDictionary]$Inputs
  )
  $declared = @($Inputs.Values | ForEach-Object {
    [IO.Path]::GetFullPath([string]$_)
  } | Sort-Object)
  $declaredUnique = @($declared | Select-Object -Unique)
  if ($declared.Count -ne $declaredUnique.Count) {
    throw 'Frozen input declarations contain duplicate paths.'
  }
  $actual = @(Get-ChildItem -LiteralPath $InputDirectory -Recurse -File |
    ForEach-Object { $_.FullName } | Sort-Object)
  $differences = @(Compare-Object -ReferenceObject $declaredUnique `
    -DifferenceObject $actual)
  if ($differences.Count -ne 0) {
    $details = @($differences | ForEach-Object {
      '{0}:{1}' -f $_.SideIndicator,$_.InputObject
    }) -join '; '
    throw "Frozen input directory differs from its declarations: $details"
  }
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
    [bool]$CommercialWrapperInvocationAttempted = $false,
    [bool]$CommercialWrapperCompleted = $false,
    [System.Collections.IDictionary]$ReportValues = $null
  )
  $staticGatePassed = @(
    'frozen_input_validation','commercial_wrapper_pending','commercial_wrapper',
    'precommercial_input_validation','report_validation','input_set_validation',
    'manifest_finalization','none'
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
    commercial_wrapper_invocation_attempted = $CommercialWrapperInvocationAttempted
    commercial_wrapper_completed = $CommercialWrapperCompleted
    geometry_built = $null -ne $ReportValues -and $ReportValues.GEOMETRY_BUILT -ceq 'true'
    mesh_built = $null -ne $ReportValues -and $ReportValues.MESH_BUILT -ceq 'true'
    electrostatics_solved = $null -ne $ReportValues -and $ReportValues.ELECTROSTATICS_SOLVED -ceq 'true'
    cpt_tree_built = $null -ne $ReportValues -and $ReportValues.CPT_TREE_BUILT -ceq 'true'
    particle_tracing_solved = $null -ne $ReportValues -and $ReportValues.PARTICLE_TRACING_SOLVED -ceq 'true'
    contract_loaded = $null -ne $ReportValues -and $ReportValues.CONTRACT_LOADED -ceq 'true'
    parameter_bindings_verified = $null -ne $ReportValues -and $ReportValues.PARAMETER_BINDINGS_VERIFIED -ceq 'true'
  }
}

$environmentNames = @(
  'WEHNELT_RUN_ID','WEHNELT_ARTIFACT_ROOT',
  'PYTHONDONTWRITEBYTECODE','RUFF_NO_CACHE'
)
$savedEnvironment = Save-RunEnvironment -Names $environmentNames
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:RUFF_NO_CACHE = 'true'
$package = $null
$manifestPath = ''
$report = ''
$wrapperLog = ''
$geometryModel = ''
$electrostaticModel = ''
$cptModel = ''
$failureStage = 'package_initialization'
$frozenInputs = [ordered]@{}
$manifestRepoRoot = $repoRoot
$runConfig = $null
$recordPaths = @()
$commercialWrapperInvocationAttempted = $false
$commercialWrapperCompleted = $false

try {
  $package = New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot `
    -RunId $RunId -Project 'wehnelt_electron_gun' -Mode 'build_only_smoke' `
    -Software $software -AdditionalDirectories @('comsol')
  $manifestPath = Join-Path $package.run_dir 'run_manifest.json'
  $recordPaths = @($package.run_config,$package.summary,$manifestPath)
  $report = Join-Path $package.log_dir 'build_only_report.txt'
  $wrapperLog = Join-Path $package.log_dir 'commercial_wrapper.log'
  $geometryModel = Join-Path $package.run_dir 'comsol\ElectronGun_CoilT.mph'
  $electrostaticModel = Join-Path $package.run_dir 'comsol\ElectronGun_CoilT_ES.mph'
  $cptModel = Join-Path $package.run_dir 'comsol\wehnelt_electron_gun__model.mph'
  $failureStage = 'run_initialized'
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
      bootstrap_boundary = [ordered]@{
        role = 'live_repository_initialization_only'
        frozen_replacement_required_before_static_gate = $true
        files = $bootstrapIdentity
      }
    }
    formal_gate_passed = $false
  }
  Invoke-VerifiedRecordTransition -Paths $recordPaths -Action {
    Write-RunJson -Value $runConfig -Path $package.run_config
    Write-RunJson -Path $package.summary -Value (
      New-BuildSummary -Status interrupted `
        -Reason 'Run initialized; task-specific inputs are not frozen yet.' `
        -FailureStage $failureStage
    )
    Write-VerifiedRunManifest -Python $package.python -RepoRoot $manifestRepoRoot `
      -RunConfig $package.run_config -Manifest $manifestPath -Status interrupted `
      -Software $software -Outputs @($package.summary)
  }

  $failureStage = 'input_freeze'
  $snapshotRoot = Join-Path $package.input_dir 'repository'
  $codeRoot = Join-Path $snapshotRoot 'projects\wehnelt_electron_gun'
  $infrastructureRoot = $snapshotRoot
  New-Item -ItemType Directory -Force -Path $codeRoot | Out-Null

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
    analysis_package = 'analysis\__init__.py'
    resolver = 'analysis\resolve_contract.py'
    static_gate = 'verify_project.ps1'
  }
  foreach ($entry in $projectFrozenFiles.GetEnumerator()) {
    Add-FrozenInput -Name $entry.Key `
      -Source (Join-Path $projectRoot $entry.Value) `
      -Destination (Join-Path $codeRoot $entry.Value) -Inputs $frozenInputs
  }
  foreach ($file in Get-ChildItem -LiteralPath (Join-Path $projectRoot 'tests\analysis') `
      -Filter '*.py' -File | Sort-Object Name) {
    $key = 'static_test_' + ($file.BaseName -replace '[^A-Za-z0-9]+','_')
    Add-FrozenInput -Name $key -Source $file.FullName `
      -Destination (Join-Path $codeRoot ('tests\analysis\' + $file.Name)) `
      -Inputs $frozenInputs
  }

  $commonFrozenFiles = [ordered]@{
    python_project_config = 'pyproject.toml'
    powershell_runtime_gate = 'common\require_powershell7.ps1'
    lightweight_gate = 'common\verify_lightweight.ps1'
    artifact_support = 'common\contracts\run_artifact_support.ps1'
    manifest_writer = 'common\contracts\write_run_manifest.py'
    manifest_verifier = 'common\contracts\verify_run_manifest.py'
    artifact_naming = 'common\contracts\artifact_naming.py'
    file_identity = 'common\contracts\file_identity.py'
    particle_physics = 'common\contracts\particle_physics.py'
    project_registry_builder = 'common\contracts\build_project_registry.py'
    machine_contracts = 'common\contracts\machine_contracts.py'
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
  foreach ($file in Get-ChildItem -LiteralPath (Join-Path $repoRoot 'common\contracts\schemas') `
      -Filter '*.json' -File | Sort-Object Name) {
    $key = 'contract_schema_' + ($file.BaseName -replace '[^A-Za-z0-9]+','_')
    Add-FrozenInput -Name $key -Source $file.FullName `
      -Destination (Join-Path $snapshotRoot ('common\contracts\schemas\' + $file.Name)) `
      -Inputs $frozenInputs
  }

  foreach ($entry in $bootstrapIdentity.GetEnumerator()) {
    if ((Get-FileSha256 -Path $frozenInputs[$entry.Key]) -cne $entry.Value.sha256) {
      throw "Bootstrap dependency changed before it was frozen: $($entry.Key)"
    }
  }
  Assert-BuildOnlyModeDescriptor -Path $frozenInputs.mode `
    -ResolvedPath $frozenInputs.resolved_contract `
    -ExecutionProfilesPath $frozenInputs.execution_profiles

  $runConfig.inputs = $frozenInputs
  $runConfig.parameters.lifecycle_stage = 'inputs_frozen'
  . $frozenInputs.artifact_support
  $manifestRepoRoot = $infrastructureRoot
  Invoke-VerifiedRecordTransition -Paths $recordPaths -Action {
    Write-RunJson -Value $runConfig -Path $package.run_config
    Write-RunJson -Path $package.summary -Value (
      New-BuildSummary -Status interrupted `
        -Reason 'Inputs are frozen; the Static gate has not completed.' `
        -FailureStage 'static_gate_pending'
    )
    Write-VerifiedRunManifest -Python $package.python -RepoRoot $manifestRepoRoot `
      -RunConfig $package.run_config -Manifest $manifestPath -Status interrupted `
      -Software $software -Outputs (Get-ExistingRunOutputs `
        -RunDirectory $package.run_dir -InputDirectory $package.input_dir)
  }

  $failureStage = 'static_gate'
  Push-Location $snapshotRoot
  try {
    & $package.python -m projects.wehnelt_electron_gun.analysis.resolve_contract `
      --baseline $frozenInputs.baseline `
      --modes $frozenInputs.numerical_modes `
      --mode build_only_smoke `
      --evidence-particle-count 1 `
      --check $frozenInputs.resolved_contract
    $resolverExitCode = $LASTEXITCODE
  } finally {
    Pop-Location
  }
  if ($resolverExitCode -ne 0) {
    throw 'Frozen Wehnelt baseline, numerical mode, and resolved contract differ.'
  }
  & $frozenInputs.static_gate -PythonExe $package.python
  if ($LASTEXITCODE -ne 0) {
    throw 'Frozen Wehnelt Static gate failed before the commercial build.'
  }
  $failureStage = 'frozen_input_validation'
  Assert-FrozenInputSet -InputDirectory $package.input_dir -Inputs $frozenInputs

  $failureStage = 'commercial_wrapper_pending'
  $runConfig.parameters.lifecycle_stage = $failureStage
  Invoke-VerifiedRecordTransition -Paths $recordPaths -Action {
    Write-RunJson -Value $runConfig -Path $package.run_config
    Write-RunJson -Path $package.summary -Value (
      New-BuildSummary -Status interrupted `
        -Reason 'Static gate passed; the commercial wrapper has not reached a terminal state.' `
        -FailureStage $failureStage
    )
    Write-VerifiedRunManifest -Python $package.python -RepoRoot $manifestRepoRoot `
      -RunConfig $package.run_config -Manifest $manifestPath -Status interrupted `
      -Software $software -Outputs @($package.summary)
  }
  $failureStage = 'precommercial_input_validation'
  Assert-FrozenInputSet -InputDirectory $package.input_dir -Inputs $frozenInputs

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
    $commercialWrapperInvocationAttempted = $true
    & $frozenInputs.comsol_runner -TaskScript $frozenInputs.task_script `
      -ReportPath $report *>&1 |
      Tee-Object -FilePath $wrapperLog -Append
    $wrapperExitCode = $LASTEXITCODE
    $commercialWrapperCompleted = $true
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
  foreach ($modelPath in @($geometryModel,$electrostaticModel,$cptModel)) {
    if (-not (Test-Path -LiteralPath $modelPath -PathType Leaf) -or
        (Get-Item -LiteralPath $modelPath).Length -le 0) {
      throw "Wehnelt build-only MPH is missing or empty: $modelPath"
    }
  }
  $expectedReport = [ordered]@{
    TASK = 'WEHNELT_THREE_STAGE_BUILD_ONLY'
    ELECTROSTATIC_MODEL_PATH = $electrostaticModel
    CPT_MODEL_PATH = $cptModel
    GEOMETRY_BUILT = 'true'
    MESH_BUILT = 'true'
    ELECTROSTATICS_SOLVED = 'false'
    CPT_TREE_BUILT = 'true'
    PARTICLE_TRACING_SOLVED = 'false'
    CONTRACT_LOADED = 'true'
    CONTRACT_PROJECT_ID = 'wehnelt_electron_gun'
    SELECTED_MODE_ID = 'build_only_smoke'
    PARAMETER_BINDINGS_VERIFIED = 'true'
    CANDIDATE_EVIDENCE_ALLOWED = 'false'
    STATUS = 'PASS'
  }
  $reportValues = Read-BuildOnlyReport -Path $report -Expected $expectedReport
  $failureStage = 'input_set_validation'
  Assert-FrozenInputSet -InputDirectory $package.input_dir -Inputs $frozenInputs

  $failureStage = 'manifest_finalization'
  $runConfig.parameters.lifecycle_stage = 'completed'
  $successSummary = New-BuildSummary -Status success `
    -Reason 'The governed build-only workflow completed.' -FailureStage 'none' `
    -CommercialWrapperInvocationAttempted $commercialWrapperInvocationAttempted `
    -CommercialWrapperCompleted $commercialWrapperCompleted `
    -ReportValues $reportValues
  $successSummary['geometry_model'] = 'comsol/ElectronGun_CoilT.mph'
  $successSummary['electrostatic_model'] = 'comsol/ElectronGun_CoilT_ES.mph'
  $successSummary['cpt_model'] = 'comsol/wehnelt_electron_gun__model.mph'
  $successSummary['report'] = 'logs/build_only_report.txt'
  $successSummary['wrapper_log'] = 'logs/commercial_wrapper.log'
  Invoke-VerifiedRecordTransition -Paths $recordPaths -Action {
    Write-RunJson -Value $runConfig -Path $package.run_config
    Write-RunJson -Path $package.summary -Value $successSummary
    Write-VerifiedRunManifest -Python $package.python -RepoRoot $manifestRepoRoot `
      -RunConfig $package.run_config -Manifest $manifestPath -Status success `
      -Software $software -Outputs (Get-ExistingRunOutputs `
        -RunDirectory $package.run_dir -InputDirectory $package.input_dir)
  }
  Write-Output "WEHNELT_BUILD_ONLY=PASS RUN_ID=$RunId RUN_DIR=$($package.run_dir)"
} catch {
  $runError = $_
  if ($null -ne $package -and $null -ne $runConfig) {
    try {
      Invoke-VerifiedRecordTransition -Paths $recordPaths -Action {
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
          New-BuildSummary -Status failed -Reason $runError.Exception.Message `
            -FailureStage $failureStage `
            -CommercialWrapperInvocationAttempted $commercialWrapperInvocationAttempted `
            -CommercialWrapperCompleted $commercialWrapperCompleted
        )
        $outputs = Get-ExistingRunOutputs `
          -RunDirectory $package.run_dir -InputDirectory $package.input_dir
        Write-VerifiedRunManifest -Python $package.python -RepoRoot $manifestRepoRoot `
          -RunConfig $package.run_config -Manifest $manifestPath -Status failed `
          -Software $software -Outputs $outputs
      }
    } catch {
      throw "Run failed at $failureStage and terminal finalization also failed; the last verified prestate was restored. Run error: $($runError.Exception.Message) Finalization error: $($_.Exception.Message)"
    }
  }
  throw $runError
} finally {
  Restore-RunEnvironment -Names $environmentNames -Snapshot $savedEnvironment
}

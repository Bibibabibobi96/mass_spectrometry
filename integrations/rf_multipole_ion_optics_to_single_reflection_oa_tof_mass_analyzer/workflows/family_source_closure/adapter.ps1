[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$CompositionPlan,
  [Parameter(Mandatory)][string]$ResolvedConnection,
  [Parameter(Mandatory)][string]$PythonExe,
  [Parameter(Mandatory)][string]$RepoRoot,
  [string]$RunId = '',
  [switch]$PrepareOnly,
  [switch]$SolverAuthorized
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$workflowRoot = $PSScriptRoot
$integrationRoot = (Resolve-Path (Join-Path $workflowRoot '..\..')).Path
$registryPath =
  Join-Path $integrationRoot 'config\execution_adapter_profiles.json'
$sourceRevisionRegistryPath = Join-Path $integrationRoot (
  'config\family_source_revision_registry.json'
)
$plan = Get-Content -LiteralPath $CompositionPlan -Raw -Encoding UTF8 |
  ConvertFrom-Json
$resolved = Get-Content -LiteralPath $ResolvedConnection -Raw -Encoding UTF8 |
  ConvertFrom-Json
$steps = @($plan.execution_steps)
if ($steps.Count -ne 1 -or $steps[0].step_id -ne 'rf_to_oatof_transfer') {
  throw 'Prepared family plan does not contain one transfer step.'
}
if ($plan.selection.connection_profile_id -ne
    $resolved.selection.connection_profile_id) {
  throw 'Prepared family plan and resolved connection identities differ.'
}

$frozenArguments = @{}
foreach ($argument in @($steps[0].arguments)) {
  $separator = $argument.IndexOf('=')
  if ($separator -le 0) {
    throw "Prepared family adapter argument is invalid: $argument"
  }
  $name = $argument.Substring(0, $separator)
  if ($frozenArguments.ContainsKey($name)) {
    throw "Prepared family adapter argument is duplicated: $name"
  }
  $frozenArguments[$name] = $argument.Substring($separator + 1)
}
$expectedArguments = @(
  'adapter_registry_sha256',
  'source_revision_registry_path',
  'source_revision_registry_sha256',
  'source_revision_id',
  'preregistration_path',
  'preregistration_sha256',
  'runtime_binding_path',
  'runtime_binding_sha256',
  'source_branch_id',
  'resolved_budget_filename',
  'resolved_budget_sha256'
)
if (@($frozenArguments.Keys | Where-Object {
      $_ -notin $expectedArguments
    }).Count -ne 0 -or
    @($expectedArguments | Where-Object {
      -not $frozenArguments.ContainsKey($_)
    }).Count -ne 0) {
  throw 'Prepared family adapter arguments differ from the closed contract.'
}
$sourceBranchId = [string]$frozenArguments.source_branch_id
$sourceRevisionId = [string]$frozenArguments.source_revision_id
if ($sourceBranchId -notin @('comsol','simion')) {
  throw 'Prepared family source branch is invalid.'
}
if ((Get-FileHash -LiteralPath $registryPath -Algorithm SHA256).Hash -ne
    $frozenArguments.adapter_registry_sha256) {
  throw 'Family adapter registry changed after preparation.'
}

$repo = [IO.Path]::GetFullPath($RepoRoot)
$expectedRevisionRegistryPath = [IO.Path]::GetFullPath(
  (Join-Path $repo $frozenArguments.source_revision_registry_path)
)
if (-not $expectedRevisionRegistryPath.Equals(
      [IO.Path]::GetFullPath($sourceRevisionRegistryPath),
      [StringComparison]::OrdinalIgnoreCase
    ) -or
    (Get-FileHash -LiteralPath $sourceRevisionRegistryPath `
      -Algorithm SHA256).Hash -ne
    $frozenArguments.source_revision_registry_sha256) {
  throw 'Family source revision registry changed after preparation.'
}
$sourceRevisionRegistry = Get-Content -LiteralPath `
  $sourceRevisionRegistryPath -Raw -Encoding UTF8 | ConvertFrom-Json
$sourceRevisions = @($sourceRevisionRegistry.revisions | Where-Object {
  $_.source_revision_id -eq $sourceRevisionId -and
  $_.connection_profile_id -eq $plan.selection.connection_profile_id
})
if ($sourceRevisions.Count -ne 1 -or
    $sourceBranchId -notin @($sourceRevisions[0].source_branch_ids)) {
  throw 'Prepared family source revision no longer resolves uniquely.'
}
$sourceRevision = $sourceRevisions[0]
$preregistrationPath = [IO.Path]::GetFullPath(
  (Join-Path $repo $frozenArguments.preregistration_path)
)
if ($sourceRevision.preregistration.path -ne
      $frozenArguments.preregistration_path -or
    $sourceRevision.preregistration.sha256 -ne
      $frozenArguments.preregistration_sha256 -or
    -not (Test-Path -LiteralPath $preregistrationPath -PathType Leaf) -or
    (Get-FileHash -LiteralPath $preregistrationPath `
      -Algorithm SHA256).Hash -ne
      $frozenArguments.preregistration_sha256) {
  throw 'Family source revision preregistration changed after preparation.'
}
$registry = Get-Content -LiteralPath $registryPath -Raw -Encoding UTF8 |
  ConvertFrom-Json
$mappings = @($registry.mappings | Where-Object {
  $_.connection_profile_id -eq $plan.selection.connection_profile_id
})
if ($mappings.Count -ne 1) {
  throw 'Family execution adapter mapping no longer resolves uniquely.'
}
$mapping = $mappings[0]
$adapterPath = [IO.Path]::GetFullPath($PSCommandPath)
$expectedAdapterPath = (
  'integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/' +
  'workflows/family_source_closure/adapter.ps1'
)
if ($mapping.adapter_entrypoint -ne $expectedAdapterPath -or
    (Get-FileHash -LiteralPath $adapterPath -Algorithm SHA256).Hash -ne
    $mapping.adapter_sha256) {
  throw 'Family adapter implementation differs from its registry identity.'
}
if ($sourceRevision.runtime_binding.path -ne
      $frozenArguments.runtime_binding_path -or
    $sourceRevision.runtime_binding.sha256 -ne
      $frozenArguments.runtime_binding_sha256 -or
    ($sourceRevisionId -eq 'baseline' -and (
      $mapping.runtime_binding_path -ne
        $frozenArguments.runtime_binding_path -or
      $mapping.runtime_binding_sha256 -ne
        $frozenArguments.runtime_binding_sha256
    ))) {
  throw 'Prepared family runtime binding differs from its revision registry.'
}

$runtimeBinding = [IO.Path]::GetFullPath(
  (Join-Path $repo $frozenArguments.runtime_binding_path)
)
if (-not (Test-Path -LiteralPath $runtimeBinding -PathType Leaf) -or
    (Get-FileHash -LiteralPath $runtimeBinding -Algorithm SHA256).Hash -ne
    $frozenArguments.runtime_binding_sha256) {
  throw 'Family runtime binding is missing or stale.'
}
$runDirectory = [IO.Path]::GetFullPath((Split-Path -Parent $CompositionPlan))
$resolvedBudgetPath = [IO.Path]::GetFullPath(
  (Join-Path $runDirectory $frozenArguments.resolved_budget_filename)
)
if ($frozenArguments.resolved_budget_filename -ne
    'resolved_engineering_budget.json' -or
    -not (Test-Path -LiteralPath $resolvedBudgetPath -PathType Leaf) -or
    (Get-FileHash -LiteralPath $resolvedBudgetPath -Algorithm SHA256).Hash -ne
    $frozenArguments.resolved_budget_sha256) {
  throw 'Prepared family engineering budget is missing or stale.'
}

. (Join-Path $integrationRoot 'runtime\runtime_binding.ps1')
$runtime = Resolve-RfOatofRuntimeBinding -RepoRoot $repo `
  -ResolvedConnection $ResolvedConnection `
  -RuntimeBinding $runtimeBinding `
  -ExpectedConnectionProfileId $plan.selection.connection_profile_id `
  -SourceBranchId $sourceBranchId
$budget = Get-Content -LiteralPath $resolvedBudgetPath -Raw -Encoding UTF8 |
  ConvertFrom-Json
if ($budget.role -ne 'integration_resolved_engineering_budget' -or
    $budget.integration_id -ne $plan.integration_id -or
    $budget.connection_profile_id -ne
    $plan.selection.connection_profile_id -or
    $budget.source_revision_id -ne $sourceRevisionId -or
    $budget.source_identity.source_branch_id -ne $sourceBranchId -or
    $budget.source_identity.solver_id -ne
    $runtime.source_identity.solver_id -or
    $budget.source_identity.run_id -ne $runtime.source_identity.run_id -or
    $budget.source_identity.project_id -ne
    $runtime.source_identity.project_id -or
    $budget.source_identity.manifest_sha256 -ne
    $runtime.source_identity.manifest_sha256 -or
    $budget.source_identity.event_sha256 -ne
    $runtime.source_identity.event_sha256 -or
    $budget.source_identity.particle_source_sha256 -ne
    $runtime.source_identity.particle_source_sha256 -or
    $budget.source_identity.metadata_sha256 -ne
    $runtime.source_identity.metadata_sha256 -or
    [int]$budget.particle_count -ne 100 -or
    $budget.retention_class -ne 'compact') {
  throw 'Family budget and runtime source identities differ before stage 1.'
}

if ($PrepareOnly) {
  Write-Output (
    "FAMILY_SOURCE_CLOSURE_ADAPTER=PREPARED PROFILE=" +
    "$($plan.selection.connection_profile_id) SOURCE_BRANCH=$sourceBranchId " +
    "SOURCE_REVISION=$sourceRevisionId"
  )
  exit 0
}
if (-not $SolverAuthorized) {
  throw 'Family source-closure execution requires explicit solver authorization.'
}
& $PythonExe -m common.contracts.artifact_naming run $RunId
if ($LASTEXITCODE -ne 0) {
  throw 'RunId must satisfy the repository artifact naming contract.'
}
$workspaceRoot = Split-Path -Parent $repo
$runsRoot = Join-Path $workspaceRoot (
  'artifacts\projects\' + $plan.integration_id + '\runs'
)
$expectedRunDirectory = [IO.Path]::GetFullPath((Join-Path $runsRoot $RunId))
if (-not $runDirectory.Equals(
    $expectedRunDirectory,
    [StringComparison]::OrdinalIgnoreCase
  )) {
  throw 'Family execution directory must be the canonical parent run.'
}

$transferRunner = $runtime.implementation.transfer_runner
& $transferRunner `
  -ConnectionProfileId $plan.selection.connection_profile_id `
  -ResolvedConnection $ResolvedConnection `
  -ResolvedEngineeringBudget $resolvedBudgetPath `
  -RuntimeBinding $runtimeBinding `
  -SourceBranchId $sourceBranchId `
  -Stamp $RunId.Substring(0, 15) `
  -PythonExe $PythonExe
if ($LASTEXITCODE -ne 0) {
  throw 'Family mapped RF-to-oaTOF transfer failed.'
}

$receipt = [ordered]@{
  schema_version = 1
  role = 'integration_family_source_closure_execution_receipt'
  integration_run_id = $RunId
  connection_profile_id = $plan.selection.connection_profile_id
  source_branch_id = $sourceBranchId
  source_revision_id = $sourceRevisionId
  source_identity = $budget.source_identity
  composition_plan_sha256 =
    (Get-FileHash -LiteralPath $CompositionPlan -Algorithm SHA256).Hash
  resolved_connection_sha256 =
    (Get-FileHash -LiteralPath $ResolvedConnection -Algorithm SHA256).Hash
  resolved_engineering_budget_sha256 =
    (Get-FileHash -LiteralPath $resolvedBudgetPath -Algorithm SHA256).Hash
  runtime_binding_sha256 =
    (Get-FileHash -LiteralPath $runtimeBinding -Algorithm SHA256).Hash
  stage_run_ids = [ordered]@{
    pre_pulse_interface_transport =
      "$($RunId.Substring(0, 15))__sim__comsol__rf-oatof-pre-pulse-interface-gap0__n100"
    pulse_capture =
      "$($RunId.Substring(0, 15))__sim__comsol__rf-oatof-pulse-capture-gap0__n100"
    analyzer_transport =
      "$($RunId.Substring(0, 15))__sim__cross__rf-oatof-analyzer-transport-gap0__n100"
  }
  stage_runtime_binding_sha256s = [ordered]@{
    pre_pulse_interface_transport =
      (Get-FileHash -LiteralPath $runtimeBinding -Algorithm SHA256).Hash
    pulse_capture =
      (Get-FileHash -LiteralPath $runtimeBinding -Algorithm SHA256).Hash
    analyzer_transport =
      (Get-FileHash -LiteralPath $runtimeBinding -Algorithm SHA256).Hash
  }
  preregistration_sha256 =
    (Get-FileHash -LiteralPath $preregistrationPath -Algorithm SHA256).Hash
  execution_status = 'completed_pending_paired_analysis'
  claim_status = 'FUNCTIONAL_SCREEN_ONLY'
}
$receiptPath = Join-Path $runDirectory 'execution_receipt.json'
$receipt | ConvertTo-Json -Depth 6 |
  Set-Content -LiteralPath $receiptPath -Encoding UTF8

$publisherModule = (
  'integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.' +
  'workflows.family_source_closure.publish_run'
)
Push-Location -LiteralPath $repo
try {
  & $PythonExe -m $publisherModule `
    --repo-root $repo `
    --integration-run-dir $runDirectory `
    --receipt $receiptPath `
    --resolved-connection $ResolvedConnection `
    --composition-plan $CompositionPlan `
    --resolved-engineering-budget $resolvedBudgetPath
  if ($LASTEXITCODE -ne 0) {
    throw 'Family source-closure parent run publication failed.'
  }
} finally {
  Pop-Location
}
Write-Output (
  "FAMILY_SOURCE_CLOSURE_ADAPTER=EXECUTED RUN_ID=$RunId " +
  "SOURCE_BRANCH=$sourceBranchId SOURCE_REVISION=$sourceRevisionId"
)

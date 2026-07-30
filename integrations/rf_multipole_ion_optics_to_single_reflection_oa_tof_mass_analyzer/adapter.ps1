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

$integrationRoot = $PSScriptRoot
$adapterRegistryPath = Join-Path $integrationRoot 'config\execution_adapter_profiles.json'
$preregistrationPath = Join-Path $integrationRoot 'config\migration_equivalence_preregistration.json'
$plan = Get-Content -LiteralPath $CompositionPlan -Raw -Encoding UTF8 | ConvertFrom-Json
$resolved = Get-Content -LiteralPath $ResolvedConnection -Raw -Encoding UTF8 | ConvertFrom-Json
$steps = @($plan.execution_steps)
if ($steps.Count -ne 1 -or $steps[0].step_id -ne 'rf_to_oatof_transfer') {
    throw 'Prepared composition plan does not contain one migration execution step.'
}
if ($plan.selection.connection_profile_id -ne $resolved.selection.connection_profile_id) {
    throw 'Prepared plan and resolved connection profile identities differ.'
}
$frozenArguments = @{}
foreach ($argument in @($steps[0].arguments)) {
    $separatorIndex = $argument.IndexOf('=')
    if ($separatorIndex -le 0) {
        throw "Prepared adapter argument is invalid: $argument"
    }
    $name = $argument.Substring(0, $separatorIndex)
    $value = $argument.Substring($separatorIndex + 1)
    if ([string]::IsNullOrWhiteSpace($name) -or $frozenArguments.ContainsKey($name)) {
        throw "Prepared adapter argument is invalid: $argument"
    }
    $frozenArguments[$name] = $value
}
$expectedArguments = @(
    'adapter_registry_sha256',
    'preregistration_sha256',
    'oracle_sha256',
    'runtime_binding_path',
    'runtime_binding_sha256',
    'resolved_budget_filename',
    'resolved_budget_sha256'
)
if (@($frozenArguments.Keys | Where-Object { $_ -notin $expectedArguments }).Count -ne 0 -or
    @($expectedArguments | Where-Object { -not $frozenArguments.ContainsKey($_) }).Count -ne 0) {
    throw 'Prepared adapter argument names differ from the migration contract.'
}
if ((Get-FileHash -LiteralPath $adapterRegistryPath -Algorithm SHA256).Hash -ne
    $frozenArguments.adapter_registry_sha256) {
    throw 'Execution adapter registry changed after composition preparation.'
}
if ($frozenArguments.resolved_budget_filename -ne 'resolved_engineering_budget.json') {
    throw 'Prepared engineering-budget filename differs from the migration contract.'
}
$compositionDirectory = [IO.Path]::GetFullPath((Split-Path -Parent $CompositionPlan))
$resolvedBudgetPath = [IO.Path]::GetFullPath(
    (Join-Path $compositionDirectory $frozenArguments.resolved_budget_filename)
)
if ((Split-Path -Parent $resolvedBudgetPath) -ne $compositionDirectory -or
    -not (Test-Path -LiteralPath $resolvedBudgetPath -PathType Leaf)) {
    throw 'Prepared resolved engineering budget is missing or escapes the run directory.'
}
if ((Get-FileHash -LiteralPath $resolvedBudgetPath -Algorithm SHA256).Hash -ne
    $frozenArguments.resolved_budget_sha256) {
    throw 'Resolved engineering budget changed after composition preparation.'
}
$resolvedBudget = Get-Content -LiteralPath $resolvedBudgetPath -Raw -Encoding UTF8 |
    ConvertFrom-Json
if ($resolvedBudget.role -ne 'integration_resolved_engineering_budget' -or
    $resolvedBudget.integration_id -ne $plan.integration_id -or
    $resolvedBudget.connection_profile_id -ne $plan.selection.connection_profile_id -or
    [int]$resolvedBudget.particle_count -ne 100 -or
    $resolvedBudget.retention_class -ne 'compact') {
    throw 'Resolved engineering budget identity or authorized scope differs.'
}
$registry = Get-Content -LiteralPath $adapterRegistryPath -Raw -Encoding UTF8 | ConvertFrom-Json
$mappings = @($registry.mappings | Where-Object {
    $_.connection_profile_id -eq $plan.selection.connection_profile_id
})
if ($mappings.Count -ne 1) { throw 'Execution adapter mapping no longer resolves uniquely.' }
$mapping = $mappings[0]
$adapterPath = [IO.Path]::GetFullPath($PSCommandPath)
if ($mapping.adapter_entrypoint -ne
        'integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/adapter.ps1' -or
    (Get-FileHash -LiteralPath $adapterPath -Algorithm SHA256).Hash -ne
        $mapping.adapter_sha256) {
    throw 'Execution adapter implementation differs from its frozen registry identity.'
}
if ($mapping.runtime_binding_path -ne $frozenArguments.runtime_binding_path -or
    $mapping.runtime_binding_sha256 -ne $frozenArguments.runtime_binding_sha256) {
    throw 'Prepared runtime binding differs from the current adapter registry.'
}
$runtimeBinding = [IO.Path]::GetFullPath(
    (Join-Path $RepoRoot $frozenArguments.runtime_binding_path)
)
$repoBoundary = [IO.Path]::GetFullPath($RepoRoot).TrimEnd(
    [IO.Path]::DirectorySeparatorChar,
    [IO.Path]::AltDirectorySeparatorChar
)
if (-not $runtimeBinding.StartsWith(
        $repoBoundary + [IO.Path]::DirectorySeparatorChar,
        [StringComparison]::OrdinalIgnoreCase
    ) -or
    -not (Test-Path -LiteralPath $runtimeBinding -PathType Leaf) -or
    (Get-FileHash -LiteralPath $runtimeBinding -Algorithm SHA256).Hash -ne
        $frozenArguments.runtime_binding_sha256) {
    throw 'Frozen runtime binding is missing, stale or escapes the repository.'
}
$bindingDocument = Get-Content -LiteralPath $runtimeBinding -Raw -Encoding UTF8 |
    ConvertFrom-Json
$implementationPaths = [ordered]@{
    run_artifact_support = 'runtime/run_artifacts.ps1'
    runtime_binding_support = 'runtime/runtime_binding.ps1'
    transfer_runner = 'runtime/run_transfer.ps1'
    pre_pulse_runner = 'stages/comsol/run_pre_pulse_interface_transport.ps1'
    pre_pulse_builder = 'stages/comsol/build_pre_pulse_interface_transport_model.m'
    pre_pulse_field_preparer = 'stages/comsol/prepare_pre_pulse_interface_transport_field_model.m'
    pre_pulse_field_solver = 'stages/comsol/solve_pre_pulse_interface_transport_field.m'
    pulse_capture_runner = 'stages/comsol/run_pulse_capture.ps1'
    pulse_capture_solver = 'stages/comsol/solve_pulse_capture.m'
    analyzer_transport_runner = 'stages/cross_solver/run_analyzer_transport.ps1'
}
$actualImplementationNames = @(
    $bindingDocument.implementation.PSObject.Properties.Name | Sort-Object
)
$expectedImplementationNames = @($implementationPaths.Keys | Sort-Object)
if ([string]::Join("`n", $actualImplementationNames) -ne
    [string]::Join("`n", $expectedImplementationNames)) {
    throw 'Runtime implementation binding does not contain the complete closed file set.'
}
$implementation = @{}
$integrationPrefix = (
    'integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/'
)
foreach ($name in $implementationPaths.Keys) {
    $record = $bindingDocument.implementation.$name
    $expectedRelative = $integrationPrefix + $implementationPaths[$name]
    $path = [IO.Path]::GetFullPath((Join-Path $RepoRoot ([string]$record.path)))
    if ([string]$record.path -ne $expectedRelative -or
        -not $path.StartsWith(
            $repoBoundary + [IO.Path]::DirectorySeparatorChar,
            [StringComparison]::OrdinalIgnoreCase
        ) -or
        -not (Test-Path -LiteralPath $path -PathType Leaf) -or
        (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -ne
            ([string]$record.sha256).ToUpperInvariant()) {
        throw "Runtime implementation identity differs before stage 1: $name"
    }
    $implementation[$name] = $path
}
$workflowEntrypoint = $implementation.transfer_runner
$fixedTransferRunner = [IO.Path]::GetFullPath(
    (Join-Path $integrationRoot 'runtime\run_transfer.ps1')
)
if (-not $workflowEntrypoint.Equals(
        $fixedTransferRunner,
        [StringComparison]::OrdinalIgnoreCase
    )) {
    throw 'Frozen transfer runner differs from the sole integration entrypoint.'
}
. $implementation.runtime_binding_support
$runtime = Resolve-RfOatofRuntimeBinding -RepoRoot $RepoRoot `
    -ResolvedConnection $ResolvedConnection -RuntimeBinding $runtimeBinding `
    -ExpectedConnectionProfileId $plan.selection.connection_profile_id
$connectorLengthMm = [double]$resolved.connector.length_mm
$actualPreregistrationSha256 = (
    Get-FileHash -LiteralPath $preregistrationPath -Algorithm SHA256
).Hash
if ($actualPreregistrationSha256 -ne $frozenArguments.preregistration_sha256) {
    throw 'Migration preregistration changed after composition preparation.'
}
$preregistration = Get-Content -LiteralPath $preregistrationPath -Raw -Encoding UTF8 |
    ConvertFrom-Json
if ($preregistration.equivalence_status -ne 'BLOCKED' -or
    $preregistration.execution_status -ne 'NOT_RUN') {
    throw 'Migration preregistration no longer has the required pre-execution state.'
}
$oraclePath = [IO.Path]::GetFullPath(
    (Join-Path $RepoRoot ([string]$preregistration.legacy_oracle.path))
)
$actualOracleSha256 = (Get-FileHash -LiteralPath $oraclePath -Algorithm SHA256).Hash
if ($actualOracleSha256 -ne $frozenArguments.oracle_sha256 -or
    $actualOracleSha256 -ne
        ([string]$preregistration.legacy_oracle.sha256).ToUpperInvariant()) {
    throw 'Migration oracle differs from the frozen preregistration and plan.'
}
$oracle = Get-Content -LiteralPath $oraclePath -Raw -Encoding UTF8 | ConvertFrom-Json
$oracleIdentity = [ordered]@{
    run_id = [string]$oracle.source_identity.run_id
    project_id = [string]$oracle.source_identity.project_id
    manifest_sha256 = ([string]$oracle.source_identity.manifest.sha256).ToUpperInvariant()
    event_sha256 = ([string]$oracle.source_identity.events.sha256).ToUpperInvariant()
    metadata_sha256 = ([string]$oracle.source_identity.metadata.sha256).ToUpperInvariant()
}
foreach ($name in @(
    'run_id','project_id','manifest_sha256','event_sha256','metadata_sha256'
)) {
    $budgetValue = ([string]$resolvedBudget.source_identity.$name)
    $runtimeValue = ([string]$runtime.source_identity.$name)
    $oracleValue = ([string]$oracleIdentity.$name)
    if ($name.EndsWith('_sha256')) {
        $budgetValue = $budgetValue.ToUpperInvariant()
        $runtimeValue = $runtimeValue.ToUpperInvariant()
        $oracleValue = $oracleValue.ToUpperInvariant()
    }
    if ([string]::IsNullOrWhiteSpace($budgetValue) -or
        $budgetValue -ne $runtimeValue -or $budgetValue -ne $oracleValue) {
        throw "Budget, oracle and runtime source identity differ before stage 1: $name"
    }
}
if ($PrepareOnly) {
    Write-Output ((
            'INTEGRATION_ADAPTER=PREPARED CONNECTION_PROFILE_ID={0} ' +
            'CONNECTOR_MM={1:g} RUNTIME_BINDING_SHA256={2} EQUIVALENCE=BLOCKED/NOT_RUN'
        ) -f $plan.selection.connection_profile_id, $connectorLengthMm,
            $frozenArguments.runtime_binding_sha256)
    exit 0
}
if (-not $SolverAuthorized) {
    throw 'Integration adapter execution requires explicit solver authorization.'
}
& $PythonExe -m common.contracts.artifact_naming run $RunId
if ($LASTEXITCODE -ne 0) {
    throw 'RunId must satisfy the repository artifact naming contract.'
}
$stamp = $RunId.Substring(0, 15)
$workspaceRoot = Split-Path -Parent ([IO.Path]::GetFullPath($RepoRoot))
$canonicalRunsRoot = [IO.Path]::GetFullPath(
    (Join-Path $workspaceRoot (
        'artifacts\projects\' + $plan.integration_id + '\runs'
    ))
)
$expectedRunDirectory = [IO.Path]::GetFullPath(
    (Join-Path $canonicalRunsRoot $RunId)
)
if (-not $compositionDirectory.Equals(
        $expectedRunDirectory,
        [StringComparison]::OrdinalIgnoreCase
    ) -or
    -not ([IO.Path]::GetFileName($compositionDirectory)).Equals(
        $RunId,
        [StringComparison]::Ordinal
    )) {
    throw 'Solver execution OutputDirectory must be the canonical RunId directory.'
}
& $workflowEntrypoint -ConnectionProfileId $plan.selection.connection_profile_id `
    -ResolvedConnection $ResolvedConnection `
    -ResolvedEngineeringBudget $resolvedBudgetPath `
    -RuntimeBinding $runtimeBinding `
    -Stamp $stamp -PythonExe $PythonExe
if ($LASTEXITCODE -ne 0) {
    throw 'Mapped RF-to-oaTOF transfer runner failed.'
}
$receipt = [ordered]@{
    schema_version = 1
    role = 'integration_migration_execution_receipt'
    integration_run_id = $RunId
    connection_profile_id = $plan.selection.connection_profile_id
    composition_plan_sha256 = (Get-FileHash -LiteralPath $CompositionPlan -Algorithm SHA256).Hash
    resolved_connection_sha256 = (Get-FileHash -LiteralPath $ResolvedConnection -Algorithm SHA256).Hash
    resolved_engineering_budget_sha256 = (
        Get-FileHash -LiteralPath $resolvedBudgetPath -Algorithm SHA256
    ).Hash
    runtime_binding_sha256 = (
        Get-FileHash -LiteralPath $runtimeBinding -Algorithm SHA256
    ).Hash
    preregistration_sha256 = $actualPreregistrationSha256
    oracle_sha256 = $actualOracleSha256
    connector_length_mm = $connectorLengthMm
    execution_status = 'completed_not_equivalence_evaluated'
    equivalence_status = 'BLOCKED'
}
$receiptPath = Join-Path (Split-Path -Parent $CompositionPlan) 'execution_receipt.json'
$receipt | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $receiptPath -Encoding UTF8
$publisherModule = (
    'integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.' +
    'publish_integration_run'
)
Push-Location -LiteralPath $RepoRoot
try {
    & $PythonExe -m $publisherModule `
        --repo-root $RepoRoot `
        --integration-run-dir $compositionDirectory `
        --receipt $receiptPath `
        --resolved-connection $ResolvedConnection `
        --composition-plan $CompositionPlan `
        --resolved-engineering-budget $resolvedBudgetPath
    if ($LASTEXITCODE -ne 0) {
        throw 'Integration run identity publication failed.'
    }
}
finally {
    Pop-Location
}
$manifestPath = Join-Path $compositionDirectory 'run_manifest.json'
Write-Output (
    "INTEGRATION_ADAPTER=EXECUTED RUN_ID=$RunId EQUIVALENCE=BLOCKED " +
    "RECEIPT=$receiptPath MANIFEST=$manifestPath"
)

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
    'workflow_entrypoint',
    'adapter_registry_sha256',
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
if ($mapping.workflow_entrypoint -ne $frozenArguments.workflow_entrypoint) {
    throw 'Prepared execution mapping differs from the current adapter registry.'
}
$workflowEntrypoint = [IO.Path]::GetFullPath(
    (Join-Path $RepoRoot $frozenArguments.workflow_entrypoint)
)
if (-not (Test-Path -LiteralPath $workflowEntrypoint -PathType Leaf)) {
    throw "Mapped workflow entrypoint is missing: $workflowEntrypoint"
}
$connectorLengthMm = [double]$resolved.connector.length_mm
$preregistration = Get-Content -LiteralPath $preregistrationPath -Raw -Encoding UTF8 |
    ConvertFrom-Json
if ($preregistration.equivalence_status -ne 'BLOCKED' -or
    $preregistration.execution_status -ne 'NOT_RUN') {
    throw 'Migration preregistration no longer has the required pre-execution state.'
}
if ($PrepareOnly) {
    Write-Output ((
            'INTEGRATION_ADAPTER=PREPARED CONNECTION_PROFILE_ID={0} CONNECTOR_MM={1:g} WORKFLOW={2} ' +
            'EQUIVALENCE=BLOCKED/NOT_RUN'
        ) -f $plan.selection.connection_profile_id, $connectorLengthMm,
            $frozenArguments.workflow_entrypoint)
    exit 0
}
if (-not $SolverAuthorized) {
    throw 'Integration adapter execution requires explicit solver authorization.'
}
if ($RunId -notmatch '^(?<stamp>\d{8}_\d{6})__[a-z0-9][a-z0-9._-]*$') {
    throw 'RunId must begin with yyyyMMdd_HHmmss__ and contain a nonempty integration label.'
}
$stamp = $Matches.stamp
& $workflowEntrypoint -ConnectionProfileId $plan.selection.connection_profile_id `
    -ResolvedConnection $ResolvedConnection `
    -ResolvedEngineeringBudget $resolvedBudgetPath `
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

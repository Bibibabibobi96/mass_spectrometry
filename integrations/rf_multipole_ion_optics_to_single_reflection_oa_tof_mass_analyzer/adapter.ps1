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
if ($steps.Count -ne 1 -or $steps[0].step_id -ne 'legacy_s2_s3_cumulative_migration') {
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
    'legacy_s2_entrypoint',
    'legacy_s3_entrypoint',
    'connector_case_id',
    'adapter_registry_sha256'
)
if (@($frozenArguments.Keys | Where-Object { $_ -notin $expectedArguments }).Count -ne 0 -or
    @($expectedArguments | Where-Object { -not $frozenArguments.ContainsKey($_) }).Count -ne 0) {
    throw 'Prepared adapter argument names differ from the migration contract.'
}
if ((Get-FileHash -LiteralPath $adapterRegistryPath -Algorithm SHA256).Hash -ne
    $frozenArguments.adapter_registry_sha256) {
    throw 'Execution adapter registry changed after composition preparation.'
}
$registry = Get-Content -LiteralPath $adapterRegistryPath -Raw -Encoding UTF8 | ConvertFrom-Json
$mappings = @($registry.mappings | Where-Object {
    $_.connection_profile_id -eq $plan.selection.connection_profile_id
})
if ($mappings.Count -ne 1) { throw 'Execution adapter mapping no longer resolves uniquely.' }
$mapping = $mappings[0]
if ($mapping.connector_case_id -ne $frozenArguments.connector_case_id -or
    $mapping.legacy_entrypoints.s2_field -ne $frozenArguments.legacy_s2_entrypoint -or
    $mapping.legacy_entrypoints.s3_cumulative -ne $frozenArguments.legacy_s3_entrypoint) {
    throw 'Prepared execution mapping differs from the current adapter registry.'
}
$s2Entrypoint = [IO.Path]::GetFullPath((Join-Path $RepoRoot $frozenArguments.legacy_s2_entrypoint))
$s3Entrypoint = [IO.Path]::GetFullPath((Join-Path $RepoRoot $frozenArguments.legacy_s3_entrypoint))
foreach ($entrypoint in @($s2Entrypoint, $s3Entrypoint)) {
    if (-not (Test-Path -LiteralPath $entrypoint -PathType Leaf)) {
        throw "Mapped legacy entrypoint is missing: $entrypoint"
    }
}
$preregistration = Get-Content -LiteralPath $preregistrationPath -Raw -Encoding UTF8 |
    ConvertFrom-Json
if ($preregistration.equivalence_status -ne 'BLOCKED' -or
    $preregistration.execution_status -ne 'NOT_RUN') {
    throw 'Migration preregistration no longer has the required pre-execution state.'
}
if ($PrepareOnly) {
    Write-Output ((
            'INTEGRATION_ADAPTER=PREPARED PROFILE={0} CASE={1} S2={2} S3={3} ' +
            'EQUIVALENCE=BLOCKED/NOT_RUN'
        ) -f $plan.selection.connection_profile_id, $mapping.connector_case_id,
            $frozenArguments.legacy_s2_entrypoint, $frozenArguments.legacy_s3_entrypoint)
    exit 0
}
if (-not $SolverAuthorized) {
    throw 'Integration adapter execution requires explicit solver authorization.'
}
if ($RunId -notmatch '^(?<stamp>\d{8}_\d{6})__[a-z0-9][a-z0-9._-]*$') {
    throw 'RunId must begin with yyyyMMdd_HHmmss__ and contain a nonempty integration label.'
}
$stamp = $Matches.stamp
& $s3Entrypoint -ConnectorCaseId $mapping.connector_case_id -Stamp $stamp -PythonExe $PythonExe
if ($LASTEXITCODE -ne 0) {
    throw 'Mapped S2/S3 cumulative runner failed.'
}
$receipt = [ordered]@{
    schema_version = 1
    role = 'integration_migration_execution_receipt'
    integration_run_id = $RunId
    connection_profile_id = $plan.selection.connection_profile_id
    composition_plan_sha256 = (Get-FileHash -LiteralPath $CompositionPlan -Algorithm SHA256).Hash
    resolved_connection_sha256 = (Get-FileHash -LiteralPath $ResolvedConnection -Algorithm SHA256).Hash
    connector_case_id = $mapping.connector_case_id
    execution_status = 'completed_not_equivalence_evaluated'
    equivalence_status = 'BLOCKED'
}
$receiptPath = Join-Path (Split-Path -Parent $CompositionPlan) 'execution_receipt.json'
$receipt | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $receiptPath -Encoding UTF8
Write-Output "INTEGRATION_ADAPTER=EXECUTED RUN_ID=$RunId EQUIVALENCE=BLOCKED RECEIPT=$receiptPath"

# Shared integration engineering-budget admission; no solver or run creation.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '../../common/contracts/run_artifact_support.ps1')

function Get-IntegrationStageBudget {
  [CmdletBinding(DefaultParameterSetName='Connection')]
  param(
    [Parameter(Mandatory)]$Document,
    [Parameter(Mandatory)][string]$ExpectedIntegrationId,
    [Parameter(Mandatory,ParameterSetName='Connection')][string]$ExpectedConnectionProfileId,
    [Parameter(Mandatory,ParameterSetName='Workflow')][string]$ExpectedWorkflowId,
    [Parameter(Mandatory)][string]$StageId,
    [Parameter(Mandatory)][ValidateSet('comsol','simion')][string]$Solver,
    [ValidateSet('compact','solver_review')][string]$ExpectedRetentionClass='compact'
  )
  $selectionMatches = if ($PSCmdlet.ParameterSetName -eq 'Workflow') {
    $document.schema_version -eq 2 -and $document.workflow_id -ceq $ExpectedWorkflowId
  } else {
    $document.schema_version -eq 1 -and $document.connection_profile_id -ceq $ExpectedConnectionProfileId
  }
  if (-not $selectionMatches -or
      $document.role -ne 'integration_resolved_engineering_budget' -or
      $document.integration_id -ne $ExpectedIntegrationId -or
      $document.retention_class -ne $ExpectedRetentionClass -or
      [int]$document.particle_count -lt 1) {
    throw 'Resolved integration engineering-budget identity differs.'
  }
  if ($document.stage_limits.PSObject.Properties.Name -notcontains $StageId) {
    throw "Resolved integration engineering budget omits stage: $StageId"
  }
  $limits = $document.stage_limits.$StageId
  $requiredLimitNames = @(
      'wall_clock_seconds',
      'transient_run_directory_bytes',
      'process_tree_working_set_bytes',
      'minimum_system_available_memory_bytes',
      'compact_final_retained_bytes'
    )
  if ($document.schema_version -eq 2 -and
      @($limits.PSObject.Properties.Name | Where-Object {
        $_ -notin @('solver', 'automatic_retry_count') -and $_ -notin $requiredLimitNames
      }).Count -ne 0) {
    throw "Resolved integration engineering-budget stage has unsupported fields: $StageId"
  }
  if ($limits.solver -ne $Solver -or
      [int]$limits.automatic_retry_count -ne 0) {
    throw "Resolved integration engineering-budget stage differs: $StageId"
  }
  foreach ($limitName in $requiredLimitNames) {
    if ($limits.PSObject.Properties.Name -notcontains $limitName -or
        [long]$limits.$limitName -le 0) {
      throw "Resolved integration engineering-budget stage has no positive ${limitName}: $StageId"
    }
  }
  $stageLimits = [pscustomobject][ordered]@{
      wall_clock_seconds = [int]$limits.wall_clock_seconds
      transient_run_directory_bytes = [long]$limits.transient_run_directory_bytes
      process_tree_working_set_bytes = [long]$limits.process_tree_working_set_bytes
      minimum_system_available_memory_bytes =
        [long]$limits.minimum_system_available_memory_bytes
      compact_final_retained_bytes = [long]$limits.compact_final_retained_bytes
      automatic_retry_count = 0
    }
  return $stageLimits
}

function Initialize-IntegrationStageBudget {
  [CmdletBinding(DefaultParameterSetName='Connection')]
  param(
    [Parameter(Mandatory)][string]$ResolvedBudget,
    [Parameter(Mandatory)][string]$InputDir,
    [Parameter(Mandatory)][string]$ExpectedIntegrationId,
    [Parameter(Mandatory,ParameterSetName='Connection')][string]$ExpectedConnectionProfileId,
    [Parameter(Mandatory,ParameterSetName='Workflow')][string]$ExpectedWorkflowId,
    [Parameter(Mandatory)][string]$StageId,
    [Parameter(Mandatory)][ValidateSet('comsol','simion')][string]$Solver,
    [ValidateSet('compact','solver_review')][string]$ExpectedRetentionClass='compact'
  )
  $frozen = Join-Path $InputDir 'resolved_integration_engineering_budget.json'
  $identity = $null
  $null = Copy-VerifiedRunInput -Source $ResolvedBudget -Destination $frozen -VerifiedIdentity ([ref]$identity)
  $document = Get-Content -LiteralPath $frozen -Raw -Encoding UTF8 | ConvertFrom-Json
  $selection = @{} + $PSBoundParameters
  $selection.Remove('ResolvedBudget')
  $selection.Remove('InputDir')
  $stageLimits = Get-IntegrationStageBudget @selection -Document $document
  return [pscustomobject]@{
    limits = $stageLimits
    frozen_budget = $frozen
    resolved_budget_sha256 = $identity.sha256
  }
}

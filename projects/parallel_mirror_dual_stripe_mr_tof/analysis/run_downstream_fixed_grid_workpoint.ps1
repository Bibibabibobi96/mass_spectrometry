[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$BaselineManifest,
  [string]$Stripe1PerturbationManifest = '',
  [string]$Stripe2PerturbationManifest = '',
  [string]$Prism1PerturbationManifest = '',
  [string]$Prism2PerturbationManifest = '',
  [string]$PriorWorkpointManifest = '',
  [pscustomobject]$CapacityWorkflowSession = $null,
  [string]$ContractPath = '',
  [string]$RunId = '',
  [string]$PythonExe = ''
)

# Production analysis entry: reads five completed flights; never launches SIMION.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$workspaceRoot = Split-Path -Parent $repoRoot
. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')
$project = 'parallel_mirror_dual_stripe_mr_tof'
$python = if ($PythonExe) { [IO.Path]::GetFullPath($PythonExe) } else { Join-Path $repoRoot '.venv\Scripts\python.exe' }
$contract = if ($ContractPath) { $ContractPath } else { Join-Path $PSScriptRoot '..\config\simion_candidate_two_zone.json' }
$perturbationPaths = @($Stripe1PerturbationManifest, $Stripe2PerturbationManifest, $Prism1PerturbationManifest, $Prism2PerturbationManifest)
$hasAllPerturbations = @($perturbationPaths | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }).Count -eq 4
$hasAnyPerturbation = @($perturbationPaths | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }).Count -gt 0
$hasPrior = -not [string]::IsNullOrWhiteSpace($PriorWorkpointManifest)
if (($hasPrior -and $hasAnyPerturbation) -or (-not $hasPrior -and -not $hasAllPerturbations)) {
  throw 'Supply either PriorWorkpointManifest or all four perturbation manifests.'
}
if (-not $RunId) { $RunId = (Get-Date -Format 'yyyyMMdd_HHmmss') + '__analysis__python__mrtof-downstream-fixed-grid-workpoint' }
$package = New-RunPackage -Python $python -RepoRoot $repoRoot `
  -ArtifactRoot (Join-Path $workspaceRoot "artifacts\projects\$project") `
  -RunId $RunId -Project $project -Mode downstream_fixed_grid_workpoint `
  -Software @('Python 3.11', 'NumPy') -RetentionContractEnabled -RetentionClass compact `
  -CapacityLedgerLifecycleEnabled
$terminalized = $false
$lease = $null
$capacitySession = $CapacityWorkflowSession
$ownsCapacitySession = $null -eq $CapacityWorkflowSession
if(-not $ownsCapacitySession -and [string]$capacitySession.status-ne'active'){throw 'Inherited workpoint capacity session is not active.'}
$failureStage = 'freeze_inputs'
try {
  $failureStage = 'capacity_startup'
  $protectedInputRuns = @($BaselineManifest, $PriorWorkpointManifest) + $perturbationPaths |
    Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
    ForEach-Object { Split-Path -Parent (Resolve-Path -LiteralPath $_).Path }
  if($ownsCapacitySession){
    $capacitySession = Enter-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot `
      -ArtifactRoot (Join-Path $workspaceRoot 'artifacts') -RunDirectory $package.artifact_run_dir `
      -CommittedNewBytes 1048576 -ProtectedPaths $protectedInputRuns `
      -Owner "mrtof-downstream-fixed-grid-workpoint:$RunId"
  }else{
    $renewal=Update-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot `
      -Session $capacitySession -ProtectedPaths (@($protectedInputRuns)+@($package.artifact_run_dir))
    $capacitySession=$renewal.session
  }
  $startupPath = Join-Path $package.result_dir 'artifact_capacity_gate_startup.json'
  Write-RunJson -Path $startupPath -Depth 14 -Value $capacitySession

  $failureStage = 'freeze_inputs'
  $frozenContract = Copy-VerifiedRunInput -Source $contract -Destination (Join-Path $package.input_dir 'contract.json')
  $definitionPath = Join-Path $package.input_dir 'workpoint_definition.json'
  if ($hasPrior) {
    $definition = [ordered]@{
      schema_version = 1
      role = 'mrtof_downstream_transported_jacobian_definition'
      contract = $frozenContract
      baseline_manifest = (Resolve-Path -LiteralPath $BaselineManifest).Path
      prior_workpoint_manifest = (Resolve-Path -LiteralPath $PriorWorkpointManifest).Path
    }
  } else {
    $definition = [ordered]@{
      schema_version = 1
      role = 'mrtof_downstream_fixed_grid_workpoint_definition'
      contract = $frozenContract
      baseline_manifest = (Resolve-Path -LiteralPath $BaselineManifest).Path
      perturbation_manifests = [ordered]@{
        stripe_1_voltage_v = (Resolve-Path -LiteralPath $Stripe1PerturbationManifest).Path
        stripe_2_voltage_v = (Resolve-Path -LiteralPath $Stripe2PerturbationManifest).Path
        prism_1_voltage_v = (Resolve-Path -LiteralPath $Prism1PerturbationManifest).Path
        prism_2_voltage_v = (Resolve-Path -LiteralPath $Prism2PerturbationManifest).Path
      }
    }
  }
  Write-RunJson -Path $definitionPath -Value $definition
  $sourcePaths = @(
    'projects/parallel_mirror_dual_stripe_mr_tof/analysis/downstream_fixed_grid_workpoint.py',
    'projects/parallel_mirror_dual_stripe_mr_tof/analysis/run_downstream_fixed_grid_workpoint.ps1',
    'projects/parallel_mirror_dual_stripe_mr_tof/analysis/joint_mirror_stripe_l0.py',
    'projects/parallel_mirror_dual_stripe_mr_tof/analysis/two_prism_operating_point.py',
    'projects/parallel_mirror_dual_stripe_mr_tof/analysis/simion_candidate_reference.py',
    'common/contracts/file_identity.py',
    'common/contracts/verify_run_manifest.py',
    'common/contracts/run_artifact_support.ps1'
  )
  $sourceCopies = @{}
  foreach ($relative in $sourcePaths) {
    $source = Join-Path $repoRoot $relative
    $sourceCopies[$source] = Copy-VerifiedRunInput -Source $source `
      -Destination (Join-Path $package.input_dir ([IO.Path]::GetFileName($relative)))
  }
  $configuration = Get-Content -LiteralPath $package.run_config -Raw | ConvertFrom-Json -AsHashtable
  $configuration.parameters = [ordered]@{
    solver_execution = 'none'
    consumer_projection_id = 'mrtof_downstream_workpoint_observation'
    consumed_scope = 'run_config_and_two_trial_json_outputs__not_full_PA_verification'
    numerical_authority = 'contract.downstream_fixed_grid_workpoint_profile'
    jacobian_source = if ($hasPrior) { 'transported_prior_fine_grid_audit' } else { 'four_same_problem_perturbation_flights' }
  }
  foreach ($file in Get-ChildItem -LiteralPath $package.input_dir -File) { $configuration.inputs[$file.Name] = $file.FullName }
  Write-RunJson -Path $package.run_config -Value $configuration
  $failureStage = 'audit_five_trials'
  $proposalPath = Join-Path $package.result_dir 'downstream_fixed_grid_workpoint.json'
  $analysisLog = Join-Path $package.log_dir 'downstream_fixed_grid_workpoint.log'
  $lease = Enter-HostExecutionLease -Role GATE -Stage downstream_workpoint_audit -RunId $RunId
  Invoke-RunToolRootContext -RepoRoot $repoRoot -Operation {
    & $python -m projects.parallel_mirror_dual_stripe_mr_tof.analysis.downstream_fixed_grid_workpoint `
      --definition $definitionPath --output $proposalPath --freeze-input-dir (Join-Path $package.input_dir 'trials') `
      2>&1 | Tee-Object -FilePath $analysisLog
    if ($LASTEXITCODE -ne 0) { throw 'Downstream fixed-grid workpoint audit failed.' }
  }
  foreach ($pair in $sourceCopies.GetEnumerator()) {
    if (-not (Test-RunFilesIdentical -Left $pair.Key -Right $pair.Value)) { throw "Source changed during audit: $($pair.Key)" }
  }
  $index = 0
  foreach ($file in Get-ChildItem -LiteralPath (Join-Path $package.input_dir 'trials') -Recurse -File) {
    $index += 1
    $configuration.inputs[('trial_projection_{0:D2}' -f $index)] = $file.FullName
  }
  $proposal = Get-Content -LiteralPath $proposalPath -Raw | ConvertFrom-Json -AsHashtable
  $configuration.parameters.consumed_trials = $proposal.consumed_trials
  $configuration.parameters.resolved_numerics = $proposal.resolved_numerics
  Write-RunJson -Path $package.run_config -Depth 18 -Value $configuration
  Write-RunJson -Path $package.summary -Depth 12 -Value ([ordered]@{
    schema_version = 1; role = 'mrtof_downstream_fixed_grid_workpoint_summary'; status = 'success'
    qualification = $proposal.qualification
    target_drift_period_ratio = $proposal.target_drift_period_ratio
    classification = $proposal.classification
    proposed_voltages_v = $proposal.proposed_voltages_v
    trust_scale = $proposal.trust_scale
    jacobian_use = if ($proposal.ContainsKey('jacobian_use')) { $proposal.jacobian_use } else { 'measured_same_problem_forward_stencil' }
    required_next_action = 'reuse_response_fields_and_validate_proposal_with_real_center_flight'
  })
  $failureStage = 'publish'
  $retention = Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config
  $terminal = Update-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot `
    -Session $capacitySession -RemainingCommittedNewBytes $(if($ownsCapacitySession){0}else{$capacitySession.committed_new_bytes})
  $capacitySession = $terminal.session
  $terminalPath = Join-Path $package.result_dir 'artifact_capacity_gate_terminal.json'
  Write-RunJson -Path $terminalPath -Depth 14 -Value $terminal
  Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config -Status success `
    -Software @('Python 3.11', 'NumPy') `
    -Outputs @($package.summary, $proposalPath, $analysisLog, $startupPath, $terminalPath, $retention)
  $terminalized = $true
  Write-Host "MRTOF_DOWNSTREAM_WORKPOINT=PASS RUN_ID=$RunId PROPOSAL=$proposalPath"
} catch {
  Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config -Summary $package.summary `
    -SummaryRole mrtof_downstream_fixed_grid_workpoint_summary -Reason $_.Exception.Message `
    -Software @('Python 3.11', 'NumPy') -Status failed -FailureStage $failureStage
  $terminalized = $true
  throw
} finally {
  if (-not $terminalized) {
    Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config -Summary $package.summary `
      -SummaryRole mrtof_downstream_fixed_grid_workpoint_summary -Reason 'Workpoint audit interrupted.' `
      -Software @('Python 3.11', 'NumPy') -Status interrupted -FailureStage $failureStage
  }
  try {
    if ($lease) { Exit-HostExecutionLease -Lease $lease }
  } finally {
    if ($ownsCapacitySession -and $null -ne $capacitySession) {
      $null = Exit-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $capacitySession
    }
  }
}

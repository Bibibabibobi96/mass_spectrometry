[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$PriorWorkpointPath,
  [Parameter(Mandatory)][string]$ConfirmationRunPath,
  [string]$ContractPath='',
  [string]$RunId='',
  [string]$PythonExe=''
)

# One recoverable, read-only Newton step for S1/S2.  P1/P2, mirror, source,
# accelerator and PA fields are inputs, not adjustment variables.
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$repoRoot=(Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$workspaceRoot=Split-Path -Parent $repoRoot
$project='parallel_mirror_dual_stripe_mr_tof'
$python=if($PythonExe){[IO.Path]::GetFullPath($PythonExe)}else{Join-Path $repoRoot '.venv\Scripts\python.exe'}
$contract=if($ContractPath){[IO.Path]::GetFullPath($ContractPath)}else{Join-Path $PSScriptRoot '..\config\simion_candidate_two_zone.json'}
if(-not$RunId){$RunId=(Get-Date -Format 'yyyyMMdd_HHmmss')+'__analysis__python__mrtof-locked-prism-stripe-step'}
. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')
$package=New-RunPackage -Python $python -RepoRoot $repoRoot `
  -ArtifactRoot (Join-Path $workspaceRoot "artifacts\projects\$project") `
  -RunId $RunId -Project $project -Mode downstream_locked_prism_stripe_step `
  -Software @('Python 3.11','NumPy') -RetentionContractEnabled -RetentionClass compact `
  -CapacityLedgerLifecycleEnabled
$terminalized=$false;$capacitySession=$null;$failureStage='preflight'
try {
  $prior=(Resolve-Path -LiteralPath $PriorWorkpointPath).Path
  $confirmation=(Resolve-Path -LiteralPath $ConfirmationRunPath).Path
  $confirmationManifest=Join-Path $confirmation 'run_manifest.json'
  & $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') $confirmationManifest --require-status success --require-project $project | Out-Null
  if($LASTEXITCODE-ne0){throw "Confirmation run is not a verified success: $confirmation"}
  $confirmationLog=Join-Path $confirmation 'logs\native_two_prism_flight.log'
  $confirmationReceipt=Join-Path $confirmation 'results\two_prism_trial_materialization.json'
  foreach($path in @($prior,$confirmationLog,$confirmationReceipt,$contract)){
    if(-not(Test-Path -LiteralPath $path -PathType Leaf)){throw "Required locked-stripe input is missing: $path"}
  }
  $failureStage='capacity_startup'
  $capacitySession=Enter-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot `
    -ArtifactRoot (Join-Path $workspaceRoot 'artifacts') -RunDirectory $package.artifact_run_dir `
    -CommittedNewBytes 1048576 -ProtectedPaths @($confirmation,$prior) `
    -Owner "mrtof-locked-prism-stripe-step:$RunId"
  $startup=Join-Path $package.result_dir 'artifact_capacity_gate_startup.json'
  Write-RunJson -Path $startup -Depth 14 -Value $capacitySession
  $failureStage='freeze_inputs'
  $frozenPrior=Copy-VerifiedRunInput -Source $prior -Destination (Join-Path $package.input_dir 'prior_workpoint.json')
  $frozenLog=Copy-VerifiedRunInput -Source $confirmationLog -Destination (Join-Path $package.input_dir 'confirmation_flight.log')
  $frozenReceipt=Copy-VerifiedRunInput -Source $confirmationReceipt -Destination (Join-Path $package.input_dir 'confirmation_materialization.json')
  $frozenContract=Copy-VerifiedRunInput -Source $contract -Destination (Join-Path $package.input_dir 'contract.json')
  $source=Copy-VerifiedRunInput -Source (Join-Path $PSScriptRoot 'downstream_locked_prism_stripe_step.py') -Destination (Join-Path $package.input_dir 'downstream_locked_prism_stripe_step.py')
  $observation=Join-Path $package.result_dir 'confirmation_observation.json'
  $proposal=Join-Path $package.result_dir 'locked_prism_stripe_step.json'
  $log=Join-Path $package.log_dir 'locked_prism_stripe_step.log'
  $failureStage='solve'
  Push-Location $repoRoot
  try {
    $env:PYTHONPATH=$repoRoot
    & $python -m projects.parallel_mirror_dual_stripe_mr_tof.analysis.downstream_locked_prism_stripe_step `
      --prior-proposal $frozenPrior --confirmation-log $frozenLog --confirmation-receipt $frozenReceipt `
      --contract $frozenContract --observation-output $observation --output $proposal 2>&1 | Tee-Object -FilePath $log
    if($LASTEXITCODE-ne0){throw 'Locked-prism Stripe step failed.'}
  } finally {Pop-Location}
  if(-not(Test-RunFilesIdentical -Left (Join-Path $PSScriptRoot 'downstream_locked_prism_stripe_step.py') -Right $source)){throw 'Locked-stripe solver source changed during analysis.'}
  $result=Get-Content -LiteralPath $proposal -Raw|ConvertFrom-Json -Depth 40
  $configuration=Get-Content -LiteralPath $package.run_config -Raw|ConvertFrom-Json -AsHashtable
  $configuration.inputs=[ordered]@{prior_workpoint=$frozenPrior;confirmation_log=$frozenLog;confirmation_receipt=$frozenReceipt;contract=$frozenContract;solver_source=$source}
  $configuration.parameters=[ordered]@{locked_coordinates=$result.locked_coordinates;solved_coordinates=$result.solved_coordinates;proposed_voltages_v=$result.proposed_voltages_v;trust_scale=$result.trust_scale}
  Write-RunJson -Path $package.run_config -Depth 30 -Value $configuration
  Write-RunJson -Path $package.summary -Depth 20 -Value ([ordered]@{schema_version=1;role='mrtof_locked_prism_stripe_workpoint_step';status='success';qualification='bounded_two_variable_real_field_stripe_correction';locked_coordinates=$result.locked_coordinates;solved_coordinates=$result.solved_coordinates;proposed_voltages_v=$result.proposed_voltages_v;predicted_residuals=$result.predicted_residuals;trust_scale=$result.trust_scale;reason='P1/P2 handoff was accepted from the real centre flight; this step changes only S1/S2 and requires one confirming centre flight.'})
  $retention=Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config
  $terminal=Update-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $capacitySession -RemainingCommittedNewBytes 0
  $capacitySession=$terminal.session;$terminalPath=Join-Path $package.result_dir 'artifact_capacity_gate_terminal.json';Write-RunJson -Path $terminalPath -Depth 14 -Value $terminal
  Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config -Status success -Software @('Python 3.11','NumPy') -Outputs @($package.summary,$proposal,$observation,$log,$startup,$terminalPath,$retention)
  $terminalized=$true
  Write-Host "MRTOF_LOCKED_PRISM_STRIPE_STEP=PASS RUN_ID=$RunId PROPOSAL=$proposal"
} catch {
  if(-not$terminalized){Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config -Summary $package.summary -SummaryRole mrtof_locked_prism_stripe_workpoint_step -Reason $_.Exception.Message -Software @('Python 3.11','NumPy') -FailureStage $failureStage;$terminalized=$true}
  throw
} finally {
  if($null-ne$capacitySession){$null=Exit-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $capacitySession}
}

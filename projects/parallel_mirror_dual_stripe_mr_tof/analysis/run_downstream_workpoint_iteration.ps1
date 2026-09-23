[CmdletBinding()]
param(
  [string]$InitialWorkpointManifest = '',
  [string]$SeedTrialManifest = '',
  [string]$NativeCorridorBankRunPath = '',
  [Parameter(Mandatory)][string]$GeometryReviewRunPath,
  [Parameter(Mandatory)][string]$MirrorRunPath,
  [Parameter(Mandatory)][string]$StripeRunPath,
  [Parameter(Mandatory)][string]$AcceleratorProviderReceiptPath,
  [string]$NativeSystemRuntimeBundlePath = '',
  [string]$BunchSourceReceiptPath = '',
  [switch]$PulseAcceleratorUntilInitialExit,
  [string]$AcceleratorPulseSchedulePath = '',
  [string]$TrajectoryProfileId = '',
  [double]$TrajectoryStepScale = 1.0,
  [double]$AcceleratorSourceYOffsetMm = 0.0,
  [switch]$RetainBaselineGuiWorkbench,
  [string]$ResumeParentCheckpoint = '',
  # A new controller contract may alter acceptance tolerances without changing
  # any PA-producing input.  Reuse only a checkpointed private runtime family;
  # it never imports the prior controller state or iteration evidence.
  [string]$NativeRuntimeCheckpoint = '',
  [string]$ResumeSuccessfulChildManifest = '',
  [string]$ContractPath = '',
  [string]$RunId = '',
  [string]$SimionExe = '',
  [string]$PythonExe = ''
)

# Production workflow: each iteration is a separately manifested real N=1
# flight.  This parent owns only the finite-state decisions and lineage chain.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')
. (Join-Path $PSScriptRoot '..\simion\native_corridor_runtime_support.ps1')
$project = 'parallel_mirror_dual_stripe_mr_tof'
$python = if ($PythonExe) { [IO.Path]::GetFullPath($PythonExe) } else { Join-Path $repoRoot '.venv\Scripts\python.exe' }
$contract = if ($ContractPath) { (Resolve-Path -LiteralPath $ContractPath).Path } else { Join-Path $PSScriptRoot '..\config\simion_candidate_two_zone.json' }
$trialRunner = Join-Path $PSScriptRoot '..\simion\run_two_prism_trial.ps1'
$bunchScreeningRunner = Join-Path $PSScriptRoot 'run_native_corridor_bunch_screening.ps1'
$artifactRoot = Join-Path (Split-Path -Parent $repoRoot) "artifacts\projects\$project"
$artifactWorkspaceRoot = Join-Path (Split-Path -Parent $repoRoot) 'artifacts'
if (-not $RunId) { $RunId = (Get-Date -Format 'yyyyMMdd_HHmmss') + '__sim__simion__mrtof-downstream-auto-workpoint' }
if ([string]::IsNullOrWhiteSpace($NativeCorridorBankRunPath)) { throw 'NativeCorridorBankRunPath is required.' }
if ([string]::IsNullOrWhiteSpace($NativeSystemRuntimeBundlePath)) { throw 'NativeCorridorBankRunPath requires NativeSystemRuntimeBundlePath.' }
if ([bool]$InitialWorkpointManifest -eq [bool]$SeedTrialManifest) { throw 'Supply InitialWorkpointManifest or SeedTrialManifest, exclusively.' }
if ($SeedTrialManifest -and $ResumeSuccessfulChildManifest) { throw 'Seed bootstrap does not accept an iteration child override.' }
if ($ResumeParentCheckpoint -and -not $ResumeSuccessfulChildManifest -and -not $SeedTrialManifest) {
  throw 'ResumeParentCheckpoint requires ResumeSuccessfulChildManifest as the exact latest successful child.'
}

function Get-ManifestOutputPath {
  param([Parameter(Mandatory)][string]$ManifestPath,[Parameter(Mandatory)][string]$FileName)
  $manifest = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json -Depth 50
  $matches = @($manifest.outputs | Where-Object { [IO.Path]::GetFileName([string]$_.path) -eq $FileName })
  if ($matches.Count -ne 1) { throw "Manifest must bind exactly one $FileName output: $ManifestPath" }
  $declared = [string]$matches[0].path
  $path = if ([IO.Path]::IsPathRooted($declared)) {
    [IO.Path]::GetFullPath($declared)
  } else {
    [IO.Path]::GetFullPath((Join-Path (Split-Path -Parent $ManifestPath) $declared))
  }
  if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Manifest output is missing: $path" }
  $hash = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
  if ($hash -ne ([string]$matches[0].sha256).ToLowerInvariant()) { throw "Manifest output hash differs: $path" }
  return $path
}

function New-CenterTrialArguments {
  param([Parameter(Mandatory)][double[]]$Voltages,[Parameter(Mandatory)][string]$ChildRunId)
  $arguments = @{
    GeometryReviewRunPath=$GeometryReviewRunPath;MirrorRunPath=$MirrorRunPath
    StripeRunPath=$StripeRunPath
    Prism1VoltageV=$Voltages[2];Prism2VoltageV=$Voltages[3]
    Stripe1VoltageV=$Voltages[0];Stripe2VoltageV=$Voltages[1]
    TrajectoryStepScale=$TrajectoryStepScale;AcceleratorSourceYOffsetMm=$AcceleratorSourceYOffsetMm
    RunId=$ChildRunId;PythonExe=$python;CapacityWorkflowSession=$capacitySession
  }
  $arguments.AcceleratorProviderReceiptPath=$AcceleratorProviderReceiptPath
  $arguments.NativeCorridorBankRunPath=$NativeCorridorBankRunPath
  $arguments.NativeSystemRuntimeBundlePath=$NativeSystemRuntimeBundlePath
  $arguments.NativeCorridorRuntimeSession=$nativeRuntimeSession
  if ($SimionExe) { $arguments.SimionExe = $SimionExe }
  if ($PulseAcceleratorUntilInitialExit) { $arguments.PulseAcceleratorUntilInitialExit = $true }
  if ($AcceleratorPulseSchedulePath) { $arguments.AcceleratorPulseSchedulePath = $AcceleratorPulseSchedulePath }
  if ($TrajectoryProfileId) { $arguments.TrajectoryProfileId = $TrajectoryProfileId }
  return $arguments
}

function Get-WorkpointBootstrapEvidence {
  param([string]$Manifest,[double[]]$Voltages)
  & $python (Join-Path $repoRoot 'common/contracts/verify_run_manifest.py') $Manifest --require-status success `
    --require-project $project --require-mode finite_3d_two_prism_voltage_trial | Out-Host
  if($LASTEXITCODE-ne0){throw 'Centre trial manifest is not verified success.'}
  $materialization=Get-ManifestOutputPath -ManifestPath $Manifest -FileName 'two_prism_trial_materialization.json'
  $observationPath=Get-ManifestOutputPath -ManifestPath $Manifest -FileName 'two_prism_trial_observation.json'
  $receipt=Get-Content -LiteralPath $materialization -Raw|ConvertFrom-Json -AsHashtable
  $observation=Get-Content -LiteralPath $observationPath -Raw|ConvertFrom-Json -AsHashtable
  $actual=@(@($receipt.stripe_biases_v)+@($receipt.prism_voltages_v))
  if($actual.Count-ne4-or$Voltages.Count-ne4){throw 'Centre trial must bind four voltages.'}
  for($index=0;$index-lt4;$index++){
    if(-not[double]::IsFinite([double]$actual[$index])-or[double]$actual[$index]-ne$Voltages[$index]){throw 'Centre trial voltages differ.'}
  }
  if(($observation.prism_voltages_v-join',')-ne($receipt.prism_voltages_v-join',')){throw 'Centre trial observed prism voltages differ.'}
  $reasons=@()
  if($observation['status']-notin@('full_drift_observed','target_phase_observed','detected')){$reasons+='target_phase_status_invalid'}
  $termination=$observation['termination_diagnostic']
  if(-not($termination-is[Collections.IDictionary]-and$termination.Contains('physical_collision')-and
    $termination.physical_collision-is[bool]-and$termination.physical_collision-eq$false)){$reasons+='collision_absence_not_proven'}
  $residuals=$observation['residuals']
  $target='Stripe_target_phase_y_minus_origin_mm'
  if(-not($residuals-is[Collections.IDictionary]-and$residuals.Contains($target)-and
    $null-ne$residuals[$target]-and[double]::IsFinite([double]$residuals[$target]))){$reasons+='target_phase_residual_missing'}
  $static=$observation['static_return_diagnostic']
  if(-not($static-is[Collections.IDictionary]-and$static['status']-eq'detector_hit'-and
    $static['event_contract_ok']-is[bool]-and$static['event_contract_ok']-eq$true)){$reasons+='static_detector_contract_failed'}
  return [ordered]@{
    passed=($reasons.Count-eq0);reasons=$reasons;actual_voltages_v=$actual
    child_manifest=$Manifest;child_manifest_sha256=(Get-FileHash -LiteralPath $Manifest -Algorithm SHA256).Hash
    observation_path=$observationPath;observation_sha256=(Get-FileHash -LiteralPath $observationPath -Algorithm SHA256).Hash
    materialization_path=$materialization;materialization_sha256=(Get-FileHash -LiteralPath $materialization -Algorithm SHA256).Hash
  }
}
# Recovery probes consume the same manifest, voltage, topology and event gate
# as bootstrap stencil trials.
function Get-CenterTrialPhysicalEvidence {
  param([string]$Manifest,[double[]]$Voltages)
  return Get-WorkpointBootstrapEvidence -Manifest $Manifest -Voltages $Voltages
}
function Save-WorkpointBootstrap {
  param($Bootstrap,[string]$BootstrapPath)
  Write-RunJson -Path $BootstrapPath -Depth 30 -Value $Bootstrap
  if((Get-Variable nativeRuntimeSession -ErrorAction SilentlyContinue)-and$null-ne$nativeRuntimeSession-and
     (Test-Path -LiteralPath $nativeRuntimeSession.checkpoint_path)){
    Save-NativeWorkflowCheckpoint -Reason 'Bootstrap physical attempt recorded.' -WorkflowOutcome bootstrap_in_progress
  }
}
function Invoke-WorkpointStencil {
  param([Parameter(Mandatory)]$Bootstrap,[Parameter(Mandatory)][string]$BootstrapPath,[switch]$RetainBaselineGuiWorkbench)
  $seedVoltages=[double[]]$Bootstrap.seed_voltages_v
  $steps=[double[]]$Bootstrap.forward_steps_v
  if(-not$Bootstrap.Contains('attempts')){$Bootstrap['attempts']=@()}
  foreach($attempt in $Bootstrap.attempts){
    if(-not($attempt-is[Collections.IDictionary])-or
      @('axis','direction','signed_step_v','child_manifest','child_manifest_sha256','observation_sha256','materialization_sha256','passed'|Where-Object{-not$attempt.Contains($_)}).Count){throw 'Bootstrap attempt schema is incomplete.'}
    if([int]$attempt.axis-lt-1-or[int]$attempt.axis-gt3-or$attempt.passed-isnot[bool]-or
      ([int]$attempt.axis-eq-1-and[int]$attempt.direction-ne0)-or
      ([int]$attempt.axis-ge0-and[int]$attempt.direction-notin@(1,-1))){throw 'Bootstrap attempt axis or direction is invalid.'}
    if([int]$attempt.direction-eq-1){
      $forward=@($Bootstrap.attempts|Where-Object{[int]$_.axis-eq[int]$attempt.axis-and[int]$_.direction-eq1})
      if($forward.Count-ne1-or$forward[0].passed){throw 'Reverse bootstrap attempt requires one rejected forward attempt.'}
    }
  }
  # Preserve not-yet-rechecked legacy slots in every intermediate checkpoint;
  # only physically accepted slots are rebuilt into the active children array.
  if(-not$Bootstrap.Contains('resume_children')){$Bootstrap['resume_children']=@($Bootstrap.children)}
  $priorChildren=@($Bootstrap.resume_children)
  if($priorChildren.Count-gt5){throw 'Bootstrap has more than five child slots.'}
  $Bootstrap.children=@()
  $Bootstrap['signed_steps_v']=@()
  for($axis=-1;$axis-lt4;$axis++){
    $script:failureStage='bootstrap_center_'+($axis+1)
    $accepted=$false
    $directions=if($axis-lt0){@(0)}else{@(1,-1)}
    foreach($direction in $directions){
      $signedStep=if($axis-lt0){0.0}else{$direction*$steps[$axis]}
      $voltages=[double[]]$seedVoltages.Clone()
      if($axis-ge0){$voltages[$axis]+=$signedStep}
      $recorded=@($Bootstrap.attempts|Where-Object{[int]$_.axis-eq$axis-and[int]$_.direction-eq$direction})
      if($recorded.Count-gt1){throw 'Bootstrap has duplicate physical attempt identities.'}
      if($recorded.Count){
        if([double]$recorded[0].signed_step_v-ne$signedStep){throw 'Bootstrap recorded signed step differs.'}
        $manifest=[string]$recorded[0].child_manifest
      }elseif($direction-ne-1-and$priorChildren.Count-gt($axis+1)){
        $manifest=[string]$priorChildren[$axis+1]
      }else{
        $bootstrapId=$RunId+$(if($axis-lt0){'-baseline'}else{'-stencil-'+($axis+1)})+$(if($direction-eq-1){'-reverse'}else{''})
        $arguments=New-CenterTrialArguments -Voltages $voltages -ChildRunId $bootstrapId
        if($axis-lt0-and$RetainBaselineGuiWorkbench){$arguments.RetainGuiWorkbench=$true}
        & $trialRunner @arguments | Out-Host
        $manifest=Join-Path $artifactRoot "runs\$bootstrapId\run_manifest.json"
      }
      $evidence=Get-WorkpointBootstrapEvidence -Manifest $manifest -Voltages $voltages
      if($recorded.Count){
        foreach($field in @('observation_sha256','materialization_sha256','child_manifest_sha256','passed')){
          if($recorded[0][$field]-ne$evidence[$field]){throw "Bootstrap attempt evidence changed: $field"}
        }
      }else{
        $attempt=[ordered]@{axis=$axis;direction=$direction;signed_step_v=$signedStep}
        foreach($field in $evidence.Keys){$attempt[$field]=$evidence[$field]}
        $Bootstrap.attempts+=,$attempt
      }
      if($evidence.passed){
        $Bootstrap.children+=,$manifest
        if($axis-ge0){$Bootstrap.signed_steps_v+=,$signedStep}
        $accepted=$true
      }
      Save-WorkpointBootstrap -Bootstrap $Bootstrap -BootstrapPath $BootstrapPath
      if($accepted){break}
      Write-Host "MRTOF_BOOTSTRAP_PHYSICAL_REJECT axis=$axis signed_step_v=$signedStep reasons=$($evidence.reasons-join',')"
    }
    if(-not$accepted){throw "Bootstrap physical gate failed for axis $axis; no further stencil is permitted."}
  }
  $auditId=$RunId+'-jacobian'
  & $auditRunner -BaselineManifest $Bootstrap.children[0] `
    -Stripe1PerturbationManifest $Bootstrap.children[1] -Stripe2PerturbationManifest $Bootstrap.children[2] `
    -Prism1PerturbationManifest $Bootstrap.children[3] -Prism2PerturbationManifest $Bootstrap.children[4] `
    -ContractPath $frozenContract -RunId $auditId -PythonExe $python -CapacityWorkflowSession $capacitySession | Out-Host
  return Join-Path $artifactRoot "runs\$auditId\run_manifest.json"
}

function Find-AcceptedRecoveryAnchorEvidence {
  param([Parameter(Mandatory)]$History,[Parameter(Mandatory)]$Lineage,[Parameter(Mandatory)]$Anchor)
  $anchorVoltages=@($Anchor.voltages_v|ForEach-Object{[double]$_})
  $children=@($Lineage.children)
  [array]::Reverse($children)
  foreach($child in $children){
    if(-not $child.observation-or-not $child.materialization-or-not(Test-Path -LiteralPath $child.observation)-or-not(Test-Path -LiteralPath $child.materialization)){continue}
    # A later rejected candidate retains the accepted workpoint in its decision.
    # Bind the recovery anchor to the child flight's own materialization instead.
    $materialization=Get-Content -LiteralPath $child.materialization -Raw|ConvertFrom-Json -AsHashtable
    $actual=@($materialization.stripe_biases_v+$materialization.prism_voltages_v|ForEach-Object{[double]$_})
    if($actual.Count-eq4-and@(0..3|Where-Object{[math]::Abs($actual[$_]-$anchorVoltages[$_])-gt1e-10}).Count-eq0){
      return [ordered]@{observation=$child.observation;materialization=$child.materialization;child_manifest=$child.child_manifest;child_manifest_sha256=$child.child_manifest_sha256}
    }
  }
  throw 'Recovery accepted anchor has no manifest-bound lineage evidence.'
}

function Save-IterationRecoveryState {
  param([Parameter(Mandatory)]$State,[Parameter(Mandatory)][string]$Path)
  Write-RunJson -Path $Path -Depth 40 -Value $State
  if($null-ne$nativeRuntimeSession-and(Test-Path -LiteralPath $nativeRuntimeSession.checkpoint_path)){
    Save-NativeWorkflowCheckpoint -Reason 'Local S model recovery state recorded.' -WorkflowOutcome execution_failed_recovery_pending
  }
}

function Get-RecoveryProbeDirections {
  param([Parameter(Mandatory)]$History,[Parameter(Mandatory)]$Anchor)
  # Select the nearest real S-only candidate on each axis.  The derivative
  # probe must be on the same side of the accepted anchor: a positive finite
  # difference is evidence for a positive correction only, never for a
  # negative extrapolation.
  $anchorV=@($Anchor.voltages_v|ForEach-Object{[double]$_})
  $directions=@(1,1)
  foreach($axis in @(0,1)){
    $candidates=@()
    foreach($item in @($History)){
      if($item-isnot[Collections.IDictionary] -or -not $item.Contains('observation_record') -or
         $item.observation_record-isnot[Collections.IDictionary]){continue}
      $record=$item.observation_record
      if(-not $record.Contains('voltages_v') -or $record.voltages_v-isnot[Collections.IEnumerable]){continue}
      $voltage=@($record.voltages_v|ForEach-Object{[double]$_})
      if($voltage.Count-ne4){continue}
      if([math]::Abs($voltage[2]-$anchorV[2])-gt1e-10-or[math]::Abs($voltage[3]-$anchorV[3])-gt1e-10){continue}
      $delta=$voltage[$axis]-$anchorV[$axis]
      if([math]::Abs($delta)-le1e-12){continue}
      $distance=[math]::Max([math]::Abs($voltage[0]-$anchorV[0]),[math]::Abs($voltage[1]-$anchorV[1]))
      $candidates+=,[pscustomobject]@{delta=$delta;distance=$distance}
    }
    if($candidates.Count){
      $nearest=@($candidates|Sort-Object distance|Select-Object -First 1)[0]
      $directions[$axis]=if($nearest.delta-gt0){1}else{-1}
    }
  }
  return $directions
}

function Get-InterruptedSOnlyTopologyRecoveryDecision {
  param([Parameter(Mandatory)]$History)
  # A host interruption can occur after an older controller recorded one or
  # more S-only topology backtracks, but before it reached the newer recovery
  # transition.  Convert that unambiguous persisted evidence into the same
  # solver-neutral recovery request used for a newly observed topology loss.
  # This is deliberately narrow: it never reclassifies P motion, and it needs
  # a fully recorded accepted S anchor plus a signed S-only rejected origin.
  $decisions=@($History.decisions)
  $anchorIndex=-1
  for($index=$decisions.Count-1;$index-ge0;$index--){
    $candidate=$decisions[$index]
    if($candidate-is[Collections.IDictionary] -and $candidate.coordinate_group-eq'stripe_1_stripe_2' -and
       $candidate.accepted_workpoint-is[Collections.IDictionary]){$anchorIndex=$index;break}
  }
  if($anchorIndex-lt0){return $null}
  if($anchorIndex-ge($decisions.Count-1)){return $null}
  $anchor=$decisions[$anchorIndex].accepted_workpoint
  if($anchor.voltages_v-isnot[Collections.IEnumerable]){return $null}
  $anchorV=@($anchor.voltages_v|ForEach-Object{[double]$_})
  if($anchorV.Count-ne4){return $null}
  $first=$null
  foreach($candidate in @($decisions[($anchorIndex+1)..($decisions.Count-1)])){
    if($candidate-is[Collections.IDictionary] -and $candidate.state-eq'recovery_required'){return $null}
    if($candidate-is[Collections.IDictionary] -and $candidate.coordinate_group-eq'physical_topology_backtrack' -and
       $candidate.invalid_trial_reason-eq'collision_or_invalid_topology' -and
       $candidate.recovery_state-is[Collections.IDictionary] -and
       $candidate.recovery_state.recovery_origin_voltages_v-is[Collections.IEnumerable]){$first=$candidate;break}
  }
  if($null-eq$first){return $null}
  $origin=@($first.recovery_state.recovery_origin_voltages_v|ForEach-Object{[double]$_})
  if($origin.Count-ne4){return $null}
  if([math]::Abs($origin[2]-$anchorV[2])-gt1e-10-or[math]::Abs($origin[3]-$anchorV[3])-gt1e-10){return $null}
  $directions=@(0,0)
  foreach($axis in @(0,1)){
    $delta=$origin[$axis]-$anchorV[$axis]
    if([math]::Abs($delta)-le1e-12){return $null}
    $directions[$axis]=if($delta-gt0){1}else{-1}
  }
  return [ordered]@{
    schema_version=1;role='mrtof_downstream_workpoint_iteration_decision';state='recovery_required';terminal_reason=$null
    iteration=$first.iteration;coordinate_group='stripe_1_stripe_2';observation_record=$anchor;accepted_workpoint=$anchor
    candidate_accepted=$false;invalid_trial_reason='collision_or_invalid_topology';invalid_trial_detail='persisted S-only topology loss before automatic local-model recovery'
    invalid_candidate_voltages_v=$origin;prediction_assessment=[ordered]@{accepted=$false;topology_valid=$false;model_invalid_reason='s_only_topology_loss';candidate_voltages_v=$origin}
    recovery_state=[ordered]@{schema_version=1;accepted_anchor=$anchor;advance_multiplier=[double]$first.recovery_state.advance_multiplier;backtrack_multiplier=[double]$first.recovery_state.backtrack_multiplier;rejected_line_count=1;recovery_origin_voltages_v=$origin;model_invalid_reason='s_only_topology_loss';trusted_prediction_count=0;initial_probe_directions=$directions}
    next_action='refresh_independent_s_columns_after_persisted_s_only_topology_loss'
  }
}

function Invoke-SLocalModelRecovery {
  param([Parameter(Mandatory)]$Decision,[Parameter(Mandatory)]$History,[Parameter(Mandatory)]$Lineage,
    [Parameter(Mandatory)][string]$StatePath,[Parameter(Mandatory)][string]$HistoryPath,[Parameter(Mandatory)]$ContractDocument)
  $anchor=$Decision.recovery_state.accepted_anchor
  if($anchor-isnot[Collections.IDictionary]){throw 'Recovery decision lacks accepted anchor.'}
  $anchorEvidence=Find-AcceptedRecoveryAnchorEvidence -History $History -Lineage $Lineage -Anchor $anchor
  $steps=@($ContractDocument.downstream_fixed_grid_workpoint_profile.forward_stencil_steps_v|ForEach-Object{[double]$_})
  if($steps.Count-ne4-or$steps[0]-le0-or$steps[1]-le0){throw 'Recovery stencil steps are invalid.'}
  $state=[ordered]@{
    schema_version=1;role='mrtof_downstream_workpoint_local_model_recovery';status='probing'
    accepted_anchor=[ordered]@{record=$anchor;evidence=$anchorEvidence}
    trigger=[ordered]@{iteration=$Decision.iteration;reason=$Decision.recovery_state.model_invalid_reason;decision=$Decision}
    model_version=0;allowed_abs_step_v=@($steps[0],$steps[1]);probe_steps_v=@($steps[0],$steps[1]);recovery_round=1;maximum_recovery_rounds=2;trusted_prediction_count=0
    total_probe_budget=8;probe_budget_remaining=8;probes=@();history_validation=$null;model=$null;next_action='probe_missing_independent_s_columns'
  }
  if(Test-Path -LiteralPath $StatePath){
    $stored=Get-Content -LiteralPath $StatePath -Raw|ConvertFrom-Json -AsHashtable
    if($stored.role-eq$state.role-and$stored.accepted_anchor-is[Collections.IDictionary] -and
       ($stored.accepted_anchor.record.voltages_v-join',')-eq($anchor.voltages_v-join',')){$state=$stored}
  }
  # Revalidate persisted evidence against the current lineage.  A checkpoint
  # made by an earlier workflow revision may have bound the anchor to a later
  # rejected child's copied accepted_workpoint.
  if($state.accepted_anchor.evidence.materialization-ne$anchorEvidence.materialization){
    $state.accepted_anchor.evidence=$anchorEvidence
    if($state.status-eq'validated'){
      $state.status='probing';$state.model_version=0;$state.model=$null;$state.history_validation=$null
      $state.next_action='revalidate_local_model_against_corrected_anchor_evidence'
    }
  }
  if(-not $state.Contains('recovery_round')){$state.recovery_round=1}
  if(-not $state.Contains('maximum_recovery_rounds')){$state.maximum_recovery_rounds=2}
  if(-not $state.Contains('probe_steps_v')){$state.probe_steps_v=@($steps[0],$steps[1])}
  if(-not $state.Contains('recovery_policy_version')){$state.recovery_policy_version=1}
  if(-not $state.Contains('total_probe_budget')){$state.total_probe_budget=8}
  foreach($storedProbe in @($state.probes)){
    if(-not $storedProbe.Contains('round')){$storedProbe.round=1}
  }
  $requiredDirections=Get-RecoveryProbeDirections -History $History -Anchor $anchor
  # The recovery trigger is the authoritative failed local candidate.  It is
  # more specific than the broader history, which can include diagnostic or
  # already superseded probe records.
  if($state.trigger-is[Collections.IDictionary] -and $state.trigger.decision-is[Collections.IDictionary] -and
     $state.trigger.decision.observation_record-is[Collections.IDictionary]){
    $triggerV=@($state.trigger.decision.observation_record.voltages_v|ForEach-Object{[double]$_})
    if($triggerV.Count-eq4){
      foreach($axis in @(0,1)){
        $delta=$triggerV[$axis]-[double]$anchor.voltages_v[$axis]
        if([math]::Abs($delta)-gt1e-12){$requiredDirections[$axis]=if($delta-gt0){1}else{-1}}
      }
    }
  }
  # An S-only topology loss has no valid observation at the rejected voltage.
  # Its signed displacement is nevertheless useful only to choose the first
  # probe side; each axis still falls back to the opposite side automatically
  # when the first physical probe is rejected.
  # Direction hints exist only for a topology-loss trigger.  Prediction or
  # residual-stagnation recovery has no such hint and must retain the
  # independently inferred directions above.
  $hint=$null
  if($Decision.recovery_state-is[Collections.IDictionary]-and
     $Decision.recovery_state.Contains('initial_probe_directions')){
    $hint=$Decision.recovery_state.initial_probe_directions
  }
  if($hint-is[Collections.IEnumerable] -and @($hint).Count-eq2){
    $hint=@($hint|ForEach-Object{[int]$_})
    if($hint[0] -in @(-1,1) -and $hint[1] -in @(-1,1)){$requiredDirections=$hint}
  }
  # Version-one checkpoints only recorded the probe round.  Preserve every
  # signed step and its round, but resume the bounded recovery once so the
  # model obtains evidence on the side occupied by the failed candidate.
  if([int]$state.recovery_policy_version-lt2){
    $state.recovery_policy_version=2
    if($state.status-eq'terminal'-and$state.terminal_reason-eq'model_recovery_exhausted'){
      $state.status='probing';$state.terminal_reason=$null;$state.model=$null
      $state.next_action='probe_history_supported_s_directions'
    }
  }
  # Version three makes the budget an auditable ledger.  Earlier revisions
  # decremented and later topped up a mutable counter, which could incorrectly
  # strand a recovery after a policy migration.  Recompute only from recorded
  # started probes and retain the fixed total limit.
  if([int]$state.recovery_policy_version-lt3){
    $usedProbeCount=@($state.probes|Where-Object{$_.status-eq'started'-or$_.status-eq'accepted_physical_probe'-or$_.status-eq'rejected_physical_probe'-or$_.status-eq'failed'}).Count
    $state.probe_budget_remaining=[math]::Max(0,[int]$state.total_probe_budget-$usedProbeCount)
    $state.recovery_policy_version=3
    if($state.status-eq'terminal'-and$state.terminal_reason-eq'model_recovery_exhausted'){
      $state.status='probing';$state.terminal_reason=$null;$state.model=$null
      $state.next_action='complete_missing_directional_s_columns_within_fixed_budget'
    }
  }
  # Version four repairs an interrupted fallback where the opposite probe was
  # already physically accepted but the preferred rejected side caused the
  # old loop to classify the axis as missing.  Resume from the saved evidence;
  # do not consume another flight or alter the fixed probe budget.
  if([int]$state.recovery_policy_version-lt4){
    $state.recovery_policy_version=4
    if($state.status-eq'terminal'-and$state.terminal_reason-eq'model_recovery_exhausted' -and
       $null-eq$state.model-and$null-eq$state.history_validation){
      $state.status='probing';$state.terminal_reason=$null
      $state.next_action='build_model_from_saved_accepted_directional_columns'
    }
  }
  # Version five migrates a terminal state created solely because the final
  # local radius had no comparable historical flight.  Its accepted probe
  # columns remain valid evidence and are re-evaluated as a provisional,
  # bounded model; no probe is restarted.
  if([int]$state.recovery_policy_version-lt5){
    $state.recovery_policy_version=5
    $noNearbyHistory=($state.history_validation-is[Collections.IDictionary] -and
      [int]$state.history_validation.comparable_observation_count-eq0 -and
      [int]$state.history_validation.eligible_observation_count-eq0)
    if($state.status-eq'terminal'-and$state.terminal_reason-eq'model_recovery_exhausted' -and
       $null-eq$state.model-and$noNearbyHistory -and
       [int]$state.recovery_round-ge[int]$state.maximum_recovery_rounds){
      $state.status='probing';$state.terminal_reason=$null
      $state.next_action='re_evaluate_saved_final_radius_columns_as_provisional_model'
    }
  }
  # A failed local-history check is evidence that the derivative scale is too
  # broad, not evidence that the accepted anchor is invalid.  One smaller,
  # bounded refresh round may replace just those two derivative columns.
  if($state.status-eq'terminal'-and$state.terminal_reason-eq'model_recovery_exhausted' -and
     $state.history_validation-is[Collections.IDictionary]-and -not$state.history_validation.passed -and
     [int]$state.recovery_round-lt[int]$state.maximum_recovery_rounds){
    $state.recovery_round=[int]$state.recovery_round+1
    $state.probe_steps_v=@($state.probe_steps_v|ForEach-Object{[double]$_*0.2})
    $state.allowed_abs_step_v=@($state.probe_steps_v)
    $state.probe_budget_remaining=[int]$state.probe_budget_remaining+2
    $state.status='probing';$state.terminal_reason=$null;$state.model=$null
    $state.next_action='refresh_independent_s_columns_at_smaller_local_scale'
  }
  if($state.status-eq'validated'){return $state}
  if($state.status-eq'terminal'){return $state}
  Save-IterationRecoveryState -State $state -Path $StatePath
  foreach($axis in @(0,1)){
    $accepted=$false
    $requiredDirection=[int]$requiredDirections[$axis]
    $existing=@($state.probes|Where-Object{[int]$_.axis-eq$axis-and$_.status-eq'accepted_physical_probe'-and[int]$_.round-eq[int]$state.recovery_round})
    if($existing.Count-eq1){$accepted=$true}
    if($existing.Count-gt1){throw 'Recovery has more than one accepted physical probe for an axis and round.'}
    foreach($direction in @($requiredDirection,-$requiredDirection)|Select-Object -Unique){
      if($accepted){break}
      if(@($state.probes|Where-Object{[int]$_.axis-eq$axis-and[int]$_.direction-eq$direction-and[int]$_.round-eq[int]$state.recovery_round}).Count){continue}
      if($state.probe_budget_remaining-le0){break}
      $trial=@($anchor.voltages_v|ForEach-Object{[double]$_});$trial[$axis]+=$direction*[double]$state.probe_steps_v[$axis]
      $label=if($axis-eq0){'s1'}else{'s2'}
      $roundSuffix=if([int]$state.recovery_round-gt1){'-r{0}'-f $state.recovery_round}else{''}
      $probeId='{0}-recovery{1}-{2}-{3}' -f $RunId,$roundSuffix,$label,$(if($direction-eq1){'positive'}else{'negative'})
      $probe=[ordered]@{round=[int]$state.recovery_round;axis=$axis;direction=$direction;signed_step_v=($direction*[double]$state.probe_steps_v[$axis]);run_id=$probeId;status='started'}
      $state.probes+=,$probe;$state.probe_budget_remaining--;Save-IterationRecoveryState -State $state -Path $StatePath
      try{
        $arguments=New-CenterTrialArguments -Voltages $trial -ChildRunId $probeId
        & $trialRunner @arguments | Out-Host
        $manifest=Join-Path $artifactRoot "runs\$probeId\run_manifest.json"
        $evidence=Get-CenterTrialPhysicalEvidence -Manifest $manifest -Voltages $trial
        foreach($key in $evidence.Keys){$probe[$key]=$evidence[$key]}
        $probe.status=if($evidence.passed){'accepted_physical_probe'}else{'rejected_physical_probe'}
      }catch{$probe.status='failed';$probe.failure_reason=$_.Exception.Message}
      Save-IterationRecoveryState -State $state -Path $StatePath
      if($probe.status-eq'accepted_physical_probe'){$accepted=$true;break}
    }
    if(-not$accepted){$state.status='terminal';$state.terminal_reason='model_recovery_exhausted';$state.next_action='stop_with_best_accepted_workpoint';Save-IterationRecoveryState -State $state -Path $StatePath;return $state}
  }
  # A rejected preferred side may have required the opposite physical probe.
  # Build and validate the model from the actually accepted signed columns,
  # never from the initial-direction request that caused the fallback.
  $s1=@($state.probes|Where-Object{[int]$_.axis-eq0-and$_.status-eq'accepted_physical_probe'-and[int]$_.round-eq[int]$state.recovery_round}|Select-Object -First 1)
  $s2=@($state.probes|Where-Object{[int]$_.axis-eq1-and$_.status-eq'accepted_physical_probe'-and[int]$_.round-eq[int]$state.recovery_round}|Select-Object -First 1)
  if($s1.Count-ne1-or$s2.Count-ne1){throw 'Accepted local S probe columns are incomplete.'}
  $s1=$s1[0];$s2=$s2[0]
  $usedDirections=@([int]$s1.direction,[int]$s2.direction)
  $modelPath=Join-Path (Split-Path -Parent $StatePath) 'iteration_local_s_model.json'
  Push-Location -LiteralPath $repoRoot
  try{
    & $python -m projects.parallel_mirror_dual_stripe_mr_tof.analysis.downstream_workpoint_iteration `
      --prior $frozenProposal --contract $frozenContract --refresh-history $historyPath --refresh-anchor-observation $anchorEvidence.observation `
      --refresh-anchor-materialization $anchorEvidence.materialization --refresh-s1-observation $s1.observation_path `
      --refresh-s1-materialization $s1.materialization_path --refresh-s2-observation $s2.observation_path `
      --refresh-s2-materialization $s2.materialization_path --refresh-history-window 2 `
      --refresh-trusted-radius-linf-v ([math]::Max([double]$state.probe_steps_v[0],[double]$state.probe_steps_v[1])) `
      --refresh-supported-directions $usedDirections[0] $usedDirections[1] `
      --refresh-position-tolerance-mm ([double]$ContractDocument.downstream_fixed_grid_workpoint_profile.automatic_iteration.acceptance_tolerances.Stripe_target_phase_y_minus_origin_mm) `
      --output $modelPath | Out-Host
    if($LASTEXITCODE-ne0){throw 'Local S Jacobian refresh failed.'}
  }finally{Pop-Location}
  $model=Get-Content -LiteralPath $modelPath -Raw|ConvertFrom-Json -AsHashtable
  # With no accepted S-only history inside the final, reduced radius there is
  # no contradictory observation to reject the directly measured columns.
  # Keep the model provisional and its radius fixed at the last probe scale;
  # the first bounded real flight is the required prediction test.  A prior
  # round still contracts first, so this never turns missing evidence into a
  # large-step permission.
  $noNearbyHistory=($model.history_validation-is[Collections.IDictionary] -and
    [int]$model.history_validation.comparable_observation_count-eq0 -and
    [int]$model.history_validation.eligible_observation_count-eq0)
  if(-not$model.history_validation.passed -and $noNearbyHistory -and
     [int]$state.recovery_round-ge[int]$state.maximum_recovery_rounds){
    $model.history_validation.passed=$true
    $model.history_validation.validation_status='provisional_no_nearby_history'
    $model.history_validation.first_correction_requires_real_prediction_acceptance=$true
    $model.history_validation.first_correction_max_linf_v=([math]::Max([double]$state.probe_steps_v[0],[double]$state.probe_steps_v[1]))
    Write-RunJson -Path $modelPath -Depth 30 -Value $model
  }
  if(-not($model.history_validation-is[Collections.IDictionary]) -or $model.history_validation.passed-isnot[bool] -or -not$model.history_validation.passed){
    if([int]$state.recovery_round-lt[int]$state.maximum_recovery_rounds){
      $state.recovery_round=[int]$state.recovery_round+1
      $state.probe_steps_v=@($state.probe_steps_v|ForEach-Object{[double]$_*0.2})
      $state.allowed_abs_step_v=@($state.probe_steps_v)
      $state.probe_budget_remaining=[int]$state.probe_budget_remaining+2
      $state.status='retry';$state.history_validation=$model.history_validation;$state.model=$null
      $state.next_action='refresh_independent_s_columns_at_smaller_local_scale';Save-IterationRecoveryState -State $state -Path $StatePath;return $state
    }
    $state.status='terminal';$state.terminal_reason='model_recovery_exhausted';$state.history_validation=$model.history_validation;$state.next_action='stop_with_best_accepted_workpoint';Save-IterationRecoveryState -State $state -Path $StatePath;return $state
  }
  $state.status='validated';$state.model_version=2;$state.history_validation=$model.history_validation;$state.model=[ordered]@{path=$modelPath;sha256=(Get-FileHash -LiteralPath $modelPath -Algorithm SHA256).Hash.ToLowerInvariant();local_s_physical_jacobian_columns=$model.local_s_physical_jacobian_columns;trusted_radius_linf_v=([math]::Max([double]$state.probe_steps_v[0],[double]$state.probe_steps_v[1]));supported_directions=$usedDirections};$state.next_action='resume_bounded_s_solve_from_accepted_anchor';Save-IterationRecoveryState -State $state -Path $StatePath
  return $state
}

function Save-NativeWorkflowCheckpoint {
  param([Parameter(Mandatory)][string]$Reason,[switch]$ExternalInterruption,
    [string]$WorkflowOutcome='execution_failed_recovery_pending',$FinalDecision=$null)
  if($null-ne$nativeRuntimeSession-and$nativeRuntimeSession.directory-and(Test-Path -LiteralPath $nativeRuntimeSession.directory)){
    $null=Invoke-RunCapacityLifecycleAdapter -Python $python -RepoRoot $repoRoot -Action register-writing `
      -ArtifactRoot $artifactWorkspaceRoot -RunConfig $nativeRuntimeSession.owner_run_config
  }
  $checkpointOutputs=@()
  if($null-ne$nativeRuntimeSession-and(Test-Path -LiteralPath $nativeRuntimeSession.checkpoint_path)){$checkpointOutputs+=$nativeRuntimeSession.checkpoint_path}
  foreach($name in @('workpoint_bootstrap.json','iteration_history.json','iteration_lineage.json','iteration_recovery_state.json')){
    $path=Join-Path $package.result_dir $name
    if(Test-Path -LiteralPath $path){$checkpointOutputs+=$path}
  }
  $bestHandoffVariable=Get-Variable bestPhysicalHandoffPath -ErrorAction SilentlyContinue
  if($null-ne$bestHandoffVariable-and$null-ne$bestHandoffVariable.Value-and(Test-Path -LiteralPath $bestHandoffVariable.Value)){$checkpointOutputs+=$bestHandoffVariable.Value}
  $checkpointOutputs+=@(Get-ChildItem -LiteralPath $package.result_dir -Filter 'iteration_*_*.json' -File|ForEach-Object{$_.FullName})
  $checkpointOutputs=@($checkpointOutputs|Select-Object -Unique)
  Write-RunJson -Path $package.summary -Depth 20 -Value ([ordered]@{
    schema_version=1;role='mrtof_downstream_workpoint_iteration_summary';status='checkpoint'
    workflow_outcome=$WorkflowOutcome;reason=$Reason;failure_stage=$failureStage;final_decision=$FinalDecision
    external_interruption=[bool]$ExternalInterruption;resume_requires_new_run_id=$true
    native_runtime_owner_run=$nativeRuntimeSession.owner_run_directory
  })
  Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config `
    -Status checkpoint -Software @('SIMION 2020','Python 3.11','NumPy') -Outputs (@($package.summary)+$checkpointOutputs) | Out-Host
  $null=Invoke-RunCapacityLifecycleAdapter -Python $python -RepoRoot $repoRoot -Action register-writing `
    -ArtifactRoot $artifactWorkspaceRoot -RunConfig $package.run_config
  if($null-ne$capacitySession){$null=Update-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $capacitySession -RemainingCommittedNewBytes 0}
}

function New-RecoveredSFirstCandidate {
  param([Parameter(Mandatory)]$Recovery,[Parameter(Mandatory)]$History,[Parameter(Mandatory)][int]$Iteration,[Parameter(Mandatory)][string]$OutputPath)
  # The local-column probes already have a content-verified accepted anchor.
  # Derive the first bounded S candidate from that evidence; do not fly the
  # anchor again.  The next real flight is therefore the model's first
  # prediction test, and remains capped by the provisional local radius.
  $anchorEvidence=$Recovery.accepted_anchor.evidence
  Push-Location -LiteralPath $repoRoot
  try {
    & $python -m projects.parallel_mirror_dual_stripe_mr_tof.analysis.downstream_workpoint_iteration `
      --prior $frozenProposal --observation ([string]$anchorEvidence.observation) `
      --materialization ([string]$anchorEvidence.materialization) `
      --child-manifest ([string]$anchorEvidence.child_manifest) --contract $frozenContract `
      --history $historyPath --iteration $Iteration --recovery-resume --output $OutputPath | Out-Host
    if($LASTEXITCODE-ne0){throw 'Could not derive the bounded first S recovery candidate.'}
  } finally { Pop-Location }
  $proposal=Get-Content -LiteralPath $OutputPath -Raw|ConvertFrom-Json -AsHashtable
  if($proposal.state-ne'continue'-or$proposal.recovery_resume_proposal-ne$true){throw 'Recovered S candidate was not a continue proposal.'}
  return $proposal
}

$resumeNativeCheckpoint=$null;$resumeBootstrapPath=$null;$resumeParentRun=$null;$runtimeOwnerRun=$null;$bestPhysicalHandoffPath=$null
if($ResumeParentCheckpoint){
  $resumePath=(Resolve-Path -LiteralPath $ResumeParentCheckpoint).Path
  $resumeParentRun=if(Test-Path -LiteralPath $resumePath -PathType Leaf){Split-Path -Parent $resumePath}else{$resumePath}
  if((Split-Path $resumeParentRun -Leaf)-eq$RunId){throw 'Checkpoint recovery requires a new parent RunId, including external interruption.'}
  $resumeManifest=Join-Path $resumeParentRun 'run_manifest.json'
  if((Get-Content -LiteralPath $resumeManifest -Raw|ConvertFrom-Json).status-ne'checkpoint'){throw 'Native execution assets can resume only from a nonterminal checkpoint.'}
  $resumeNativeCheckpoint=Get-ManifestOutputPath -ManifestPath $resumeManifest -FileName 'native_corridor_runtime_checkpoint.json'
  $savedRuntime=Get-Content -LiteralPath $resumeNativeCheckpoint -Raw|ConvertFrom-Json
  $runtimeOwnerRun=Split-Path (Split-Path ([string]$savedRuntime.directory) -Parent) -Parent
  if([IO.Path]::GetFullPath($resumeNativeCheckpoint)-ne[IO.Path]::GetFullPath((Join-Path $runtimeOwnerRun 'results/native_corridor_runtime_checkpoint.json'))){throw 'Native checkpoint receipt escapes its asset owner.'}
  if((Get-Content -LiteralPath (Join-Path $runtimeOwnerRun 'run_manifest.json') -Raw|ConvertFrom-Json).status-ne'checkpoint'){throw 'Native runtime owner is already terminal.'}
  if($SeedTrialManifest){$resumeBootstrapPath=Get-ManifestOutputPath -ManifestPath $resumeManifest -FileName 'workpoint_bootstrap.json'}
  $projectionArgs=@($resumeManifest,'--require-status','checkpoint','--require-project',$project,
    '--require-mode','downstream_fixed_grid_workpoint_iteration','--consumer-projection-id','mrtof_native_execution_resume_v1',
    '--consumed-output',$resumeNativeCheckpoint)
  if($resumeBootstrapPath){$projectionArgs+=@('--consumed-output',$resumeBootstrapPath)}
  & $python (Join-Path $repoRoot 'common/contracts/verify_run_manifest.py') @projectionArgs
  if($LASTEXITCODE-ne0){throw 'Native recovery checkpoint manifest binding differs.'}
}
if($NativeRuntimeCheckpoint){
  if($ResumeParentCheckpoint){throw 'Native runtime reuse and workflow checkpoint resume are mutually exclusive.'}
  $resumeNativeCheckpoint=(Resolve-Path -LiteralPath $NativeRuntimeCheckpoint).Path
  $savedRuntime=Get-Content -LiteralPath $resumeNativeCheckpoint -Raw|ConvertFrom-Json -AsHashtable
  if($savedRuntime.role-ne'mrtof_native_runtime_checkpoint'-or$savedRuntime.status-ne'prepared'){
    throw 'Native runtime reuse requires a prepared checkpoint receipt.'
  }
  $runtimeOwnerRun=Split-Path (Split-Path ([string]$savedRuntime.directory) -Parent) -Parent
  if([IO.Path]::GetFullPath($resumeNativeCheckpoint)-ne[IO.Path]::GetFullPath((Join-Path $runtimeOwnerRun 'results/native_corridor_runtime_checkpoint.json'))){throw 'Native checkpoint receipt escapes its asset owner.'}
  $runtimeOwnerManifest=Join-Path $runtimeOwnerRun 'run_manifest.json'
  if((Get-Content -LiteralPath $runtimeOwnerManifest -Raw|ConvertFrom-Json).status-ne'checkpoint'){throw 'Native runtime owner is already terminal.'}
  & $python (Join-Path $repoRoot 'common/contracts/verify_run_manifest.py') $runtimeOwnerManifest `
    --require-status checkpoint --require-project $project --require-mode downstream_fixed_grid_workpoint_iteration `
    --consumer-projection-id mrtof_native_runtime_reuse_v1 --consumed-output $resumeNativeCheckpoint
  if($LASTEXITCODE-ne0){throw 'Native runtime reuse checkpoint manifest binding differs.'}
}

$package = New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot `
  -RunId $RunId -Project $project -Mode downstream_fixed_grid_workpoint_iteration `
  -Software @('SIMION 2020', 'Python 3.11', 'NumPy') -RetentionContractEnabled -RetentionClass compact `
  -CapacityLedgerLifecycleEnabled
$terminalized = $false
$failureStage = 'freeze_inputs'
$protectionReceipts = @()
$protectionLeaseOwner = "mrtof-downstream-workpoint:$RunId"
$protectionTtlSeconds = 0
$finalCacheKey = $null
$capacitySession = $null
$nativeRuntimeSession = $null
try {
  $protectionTtlSeconds = [int]((Get-Content -LiteralPath $contract -Raw | ConvertFrom-Json).downstream_fixed_grid_workpoint_profile.automatic_iteration.capacity_protection_ttl_seconds)
  if ($protectionTtlSeconds -le 0) { throw 'Capacity protection TTL must be positive.' }
  $workflowInputPaths = @(
    $(if($InitialWorkpointManifest){Split-Path -Parent (Resolve-Path -LiteralPath $InitialWorkpointManifest).Path}else{Split-Path -Parent (Resolve-Path -LiteralPath $SeedTrialManifest).Path}),
    $GeometryReviewRunPath,$MirrorRunPath,$StripeRunPath,$AcceleratorProviderReceiptPath,$NativeCorridorBankRunPath,
    $NativeSystemRuntimeBundlePath
  )
  if($resumeParentRun){$workflowInputPaths+=@($resumeParentRun,$runtimeOwnerRun)}
  $workflowInputPaths = @($workflowInputPaths | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
    ForEach-Object { (Resolve-Path -LiteralPath $_).Path } | Select-Object -Unique)
  $failureStage = 'capacity_startup'
  Write-Host 'MRTOF_WORKPOINT_STAGE=capacity_startup'
  if($runtimeOwnerRun){
    $null=Invoke-RunCapacityLifecycleAdapter -Python $python -RepoRoot $repoRoot -Action register-writing `
      -ArtifactRoot $artifactWorkspaceRoot -RunConfig (Join-Path $runtimeOwnerRun 'run_config.json')
  }
  $capacitySession = Enter-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot `
    -ArtifactRoot $artifactWorkspaceRoot -RunDirectory $package.artifact_run_dir `
    -CommittedNewBytes 26214400 -ProtectedPaths $workflowInputPaths `
    -Owner $protectionLeaseOwner -LeaseTtlSeconds $protectionTtlSeconds
  Write-Host 'MRTOF_WORKPOINT_STAGE=capacity_ready'
  $capacityStartupPath = Join-Path $package.result_dir 'artifact_capacity_gate_startup.json'
  Write-RunJson -Path $capacityStartupPath -Depth 20 -Value $capacitySession
  $protectionReceipts += $capacityStartupPath
  Write-Host 'MRTOF_WORKPOINT_STAGE=native_runtime_resume'
  $ownerRun=if($runtimeOwnerRun){$runtimeOwnerRun}else{$package.artifact_run_dir}
  $nativeRuntimeSession=[pscustomobject]@{
    lease_id=$capacitySession.lease_id;directory=(Join-Path $ownerRun 'runtime/native_corridor_family');runtime=$null
    owner_run_directory=$ownerRun;owner_run_config=(Join-Path $ownerRun 'run_config.json');resident_bytes=[int64]0
    checkpoint_path=(Join-Path $ownerRun 'results/native_corridor_runtime_checkpoint.json')
  }
  if($resumeNativeCheckpoint){
    $bank=Get-Content -LiteralPath (Join-Path $NativeCorridorBankRunPath 'results/pa_family_cache_publication.json') -Raw|ConvertFrom-Json
    $runtimeSimion=if($SimionExe){$SimionExe}else{Join-Path $env:ProgramFiles 'SIMION-2020/simion.exe'}
    Open-NativeCorridorRuntimeCheckpoint -Session $nativeRuntimeSession -CapacityWorkflowSession $capacitySession `
      -BankGenerationDirectory $bank.generation_directory -CacheKey $bank.cache_key -GenerationSha256 $bank.generation_sha256 `
      -Python $python -RepoRoot $repoRoot -SimionExe $runtimeSimion
    Write-Host 'MRTOF_WORKPOINT_STAGE=native_runtime_ready'
  }

  $failureStage = 'freeze_inputs'
  $frozenContract = Copy-VerifiedRunInput -Source $contract -Destination (Join-Path $package.input_dir 'contract.json')
  # The base bundle owns the already prepared MR fallback and detector PAs.
  # Replace only its obsolete accelerator record with the OA provider receipt;
  # this is a compact identity projection and never materializes a PA.
  $failureStage = 'bind_provider_accelerator'
  $baseNativeSystemRuntimeBundle = (Resolve-Path -LiteralPath $NativeSystemRuntimeBundlePath).Path
  $bankForProviderBinding = Get-Content -LiteralPath (Join-Path $NativeCorridorBankRunPath 'results/pa_family_cache_publication.json') -Raw | ConvertFrom-Json
  $nativeIdentityPath = Join-Path ([IO.Path]::GetTempPath()) ('mrtof_native_provider_identity_'+[guid]::NewGuid().ToString('N')+'.json')
  $providerBoundBundle = Join-Path $package.input_dir 'native_system_runtime_bundle.json'
  try {
    [IO.File]::WriteAllText($nativeIdentityPath, (([ordered]@{schema_version=1;role='mrtof_private_native_corridor_family';status='prepared';response_refine_performed=$false;published_native_members_opened=$false;controller_refine='solutions={0}';cache_key=[string]$bankForProviderBinding.cache_key;generation_sha256=[string]$bankForProviderBinding.generation_sha256}|ConvertTo-Json -Compress)), [Text.UTF8Encoding]::new($false))
    Push-Location $repoRoot
    try {
      & $python -m projects.parallel_mirror_dual_stripe_mr_tof.analysis.native_system_runtime rebind-accelerator `
        --native-corridor-runtime-receipt $nativeIdentityPath --base-bundle $baseNativeSystemRuntimeBundle `
        --accelerator-provider-receipt $AcceleratorProviderReceiptPath --bundle-output $providerBoundBundle
      if($LASTEXITCODE-ne0){throw 'OA provider accelerator binding failed.'}
    } finally { Pop-Location }
  } finally { Remove-Item -LiteralPath $nativeIdentityPath -Force -ErrorAction SilentlyContinue }
  $NativeSystemRuntimeBundlePath = $providerBoundBundle
  $nativeRecoveryProblem=[ordered]@{
      contract_sha256=(Get-FileHash -LiteralPath $frozenContract -Algorithm SHA256).Hash
      geometry=(Resolve-Path -LiteralPath $GeometryReviewRunPath).Path;mirror=(Resolve-Path -LiteralPath $MirrorRunPath).Path
      stripe=(Resolve-Path -LiteralPath $StripeRunPath).Path
      accelerator_provider_receipt=(Resolve-Path -LiteralPath $AcceleratorProviderReceiptPath).Path
      native_system_runtime_bundle=(Resolve-Path -LiteralPath $NativeSystemRuntimeBundlePath).Path
      trajectory_profile=$TrajectoryProfileId;trajectory_step_scale=$TrajectoryStepScale;source_y_offset_mm=$AcceleratorSourceYOffsetMm
      pulse_initial_exit=[bool]$PulseAcceleratorUntilInitialExit
      pulse_schedule_sha256=$(if($AcceleratorPulseSchedulePath){(Get-FileHash -LiteralPath $AcceleratorPulseSchedulePath -Algorithm SHA256).Hash}else{$null})
    }
  if($resumeParentRun){
      $priorProblem=(Get-Content -LiteralPath (Join-Path $resumeParentRun 'run_config.json') -Raw|ConvertFrom-Json -AsHashtable).parameters.native_recovery_problem
      if(($priorProblem|ConvertTo-Json -Compress)-ne($nativeRecoveryProblem|ConvertTo-Json -Compress)){throw 'Native recovery scientific problem differs; retained family is not rebuilt.'}
    }
  # Direct NativeRuntimeCheckpoint reuse is limited to the already verified
  # native corridor PA family. Open-NativeCorridorRuntimeCheckpoint binds its
  # cache key, generation and member hashes above. Static PA choices, IOB
  # poses, trajectory settings and acceptance contracts are flight inputs,
  # not PA-producing identities, so they must not force a corridor rebuild.
  $earlyConfig=Get-Content -LiteralPath $package.run_config -Raw|ConvertFrom-Json -AsHashtable
  $earlyConfig.parameters.native_recovery_problem=$nativeRecoveryProblem
  Write-RunJson -Path $package.run_config -Depth 30 -Value $earlyConfig
  $controllerSource = Copy-VerifiedRunInput `
    -Source (Join-Path $PSScriptRoot 'downstream_workpoint_iteration.py') `
    -Destination (Join-Path $package.input_dir 'downstream_workpoint_iteration.py')
  $workflowSource = Copy-VerifiedRunInput -Source $PSCommandPath `
    -Destination (Join-Path $package.input_dir 'run_downstream_workpoint_iteration.ps1')
  $checkpointSource = Copy-VerifiedRunInput `
    -Source (Join-Path $PSScriptRoot 'downstream_workpoint_checkpoint.py') `
    -Destination (Join-Path $package.input_dir 'downstream_workpoint_checkpoint.py')
  $bootstrapPath = $null
  if($SeedTrialManifest){
    $seedManifest=(Resolve-Path -LiteralPath $SeedTrialManifest).Path
    $seedMaterialization=Get-ManifestOutputPath -ManifestPath $seedManifest -FileName 'two_prism_trial_materialization.json'
    $seedProjection=[ordered]@{
      projection_id='mrtof_downstream_voltage_seed_v1';manifest=$seedManifest
      consumed_output=$seedMaterialization
      assertion_scope='run_config_and_voltage_materialization_only__other_historical_records_not_asserted'
    }
    & $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') $seedManifest `
      --require-status success --require-project $project --require-mode finite_3d_two_prism_voltage_trial `
      --consumer-projection-id $seedProjection.projection_id --consumed-output $seedMaterialization
    if($LASTEXITCODE-ne0){throw 'Bootstrap voltage seed manifest is invalid.'}
    $frozenSeedManifest=Copy-VerifiedRunInput -Source $seedManifest -Destination (Join-Path $package.input_dir 'voltage_seed_manifest.json')
    $frozenSeedMaterialization=Copy-VerifiedRunInput -Source $seedMaterialization -Destination (Join-Path $package.input_dir 'voltage_seed_materialization.json')
    $seed=Get-Content -LiteralPath $frozenSeedMaterialization -Raw|ConvertFrom-Json
    $seedVoltages=@(@($seed.stripe_biases_v)+@($seed.prism_voltages_v)|ForEach-Object{[double]$_})
    $steps=@((Get-Content -LiteralPath $frozenContract -Raw|ConvertFrom-Json).downstream_fixed_grid_workpoint_profile.forward_stencil_steps_v)
    if($seedVoltages.Count-ne4-or@($seedVoltages|Where-Object{-not[double]::IsFinite([double]$_)}).Count-or$steps.Count-ne4-or@($steps|Where-Object{[double]$_-le0-or-not[double]::IsFinite([double]$_)}).Count){throw 'Bootstrap requires four finite seed voltages and four positive stencil steps.'}
    $bootstrap=[ordered]@{schema_version=1;role='mrtof_native_workpoint_bootstrap';seed_manifest=$seedManifest;seed_voltages_v=$seedVoltages;forward_steps_v=$steps;children=@()}
    if($resumeBootstrapPath){
      $priorBootstrap=Get-Content -LiteralPath $resumeBootstrapPath -Raw|ConvertFrom-Json -AsHashtable
      if($priorBootstrap.schema_version-ne1-or$priorBootstrap.role-ne'mrtof_native_workpoint_bootstrap'){throw 'Resumed bootstrap schema or role differs.'}
      if(($priorBootstrap.seed_voltages_v-join',')-ne($seedVoltages-join',')-or($priorBootstrap.forward_steps_v-join',')-ne($steps-join',')){
        throw 'Resumed bootstrap seed or stencil steps differ.'
      }
      $bootstrap.children=@($priorBootstrap.children)
      if($priorBootstrap.ContainsKey('attempts')){$bootstrap['attempts']=@($priorBootstrap.attempts)}
      if($priorBootstrap.ContainsKey('resume_children')){$bootstrap['resume_children']=@($priorBootstrap.resume_children)}
    }
    $bootstrapPath=Join-Path $package.result_dir 'workpoint_bootstrap.json'
    Write-RunJson -Path $bootstrapPath -Depth 20 -Value $bootstrap
    $bootstrapConfig=Get-Content -LiteralPath $package.run_config -Raw|ConvertFrom-Json -AsHashtable
    $bootstrapConfig.inputs.contract=$frozenContract
    $bootstrapConfig.inputs.workflow_source=$workflowSource
    $bootstrapConfig.inputs.workpoint_bootstrap=$bootstrapPath
    $bootstrapConfig.inputs.voltage_seed_manifest=$frozenSeedManifest
    $bootstrapConfig.inputs.voltage_seed_materialization=$frozenSeedMaterialization
    $bootstrapConfig.parameters.voltage_seed_consumer_projection=$seedProjection
    Write-RunJson -Path $package.run_config -Depth 20 -Value $bootstrapConfig
    $auditRunner=Join-Path $PSScriptRoot 'run_downstream_fixed_grid_workpoint.ps1'
    $InitialWorkpointManifest=Invoke-WorkpointStencil -Bootstrap $bootstrap -BootstrapPath $bootstrapPath -RetainBaselineGuiWorkbench:$RetainBaselineGuiWorkbench
  }
  $initialManifest = (Resolve-Path -LiteralPath $InitialWorkpointManifest).Path
  & $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') $initialManifest `
    --require-status success --require-project $project --require-mode downstream_fixed_grid_workpoint
  if ($LASTEXITCODE -ne 0) { throw 'Initial downstream workpoint manifest is not verified success.' }
  $initialProposal = Get-ManifestOutputPath -ManifestPath $initialManifest -FileName 'downstream_fixed_grid_workpoint.json'
  $frozenProposal = Copy-VerifiedRunInput -Source $initialProposal -Destination (Join-Path $package.input_dir 'initial_workpoint.json')
  $frozenInitialManifest = Copy-VerifiedRunInput -Source $initialManifest -Destination (Join-Path $package.input_dir 'initial_workpoint_manifest.json')
  $resumeChildManifest = $null
  $frozenResumeChildManifest = $null
  if ($ResumeSuccessfulChildManifest) {
    $resumeChildManifest = (Resolve-Path -LiteralPath $ResumeSuccessfulChildManifest).Path
    & $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') $resumeChildManifest `
      --require-status success --require-project $project --require-mode finite_3d_two_prism_voltage_trial
    if ($LASTEXITCODE -ne 0) { throw 'Resume child manifest is not verified success.' }
    $frozenResumeChildManifest = Copy-VerifiedRunInput -Source $resumeChildManifest `
      -Destination (Join-Path $package.input_dir 'resume_successful_child_manifest.json')
  }
  $proposal = Get-Content -LiteralPath $frozenProposal -Raw | ConvertFrom-Json -AsHashtable
  $bankPublication=Get-Content -LiteralPath (Join-Path $NativeCorridorBankRunPath 'results\pa_family_cache_publication.json') -Raw|ConvertFrom-Json
  if(-not $proposal.ContainsKey('native_bank_identity') -or $null-eq$proposal.native_bank_identity -or
    $proposal.native_bank_identity.cache_key-ne$bankPublication.cache_key -or
    $proposal.native_bank_identity.generation_sha256-ne$bankPublication.generation_sha256){
    throw 'Initial Jacobian was not measured on the selected native bank.'
  }
  # A fresh chain begins at the measured baseline.  The controller therefore
  # closes P1/P2 before it ever proposes an S1/S2 perturbation.
  $current = @($proposal.baseline_voltages_v | ForEach-Object { [double]$_ })
  if ($current.Count -ne 4) { throw 'Initial workpoint baseline must contain S1/S2/P1/P2.' }
  $historyPath = Join-Path $package.result_dir 'iteration_history.json'
  $lineagePath = Join-Path $package.result_dir 'iteration_lineage.json'
  $recoveryStatePath = Join-Path $package.result_dir 'iteration_recovery_state.json'
  $history = [ordered]@{schema_version=1;role='mrtof_downstream_workpoint_iteration_history';decisions=@()}
  $lineage = [ordered]@{
    schema_version=1;role='mrtof_downstream_workpoint_iteration_lineage'
    root_workpoint_manifest=[ordered]@{
      path=$initialManifest;bytes=(Get-Item -LiteralPath $initialManifest).Length
      sha256=(Get-FileHash -LiteralPath $initialManifest -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    children=@()
  }
  Write-RunJson -Path $historyPath -Depth 20 -Value $history
  $configuration = Get-Content -LiteralPath $package.run_config -Raw | ConvertFrom-Json -AsHashtable
  $configuration.inputs = [ordered]@{
    contract=$frozenContract;initial_workpoint=$frozenProposal
    initial_workpoint_manifest=$frozenInitialManifest
    controller_source=$controllerSource;workflow_source=$workflowSource
    checkpoint_source=$checkpointSource
  }
  if($bootstrapPath){$configuration.inputs.workpoint_bootstrap=$bootstrapPath}
  if ($frozenResumeChildManifest) { $configuration.inputs.resume_successful_child_manifest=$frozenResumeChildManifest }
  $configuration.parameters = [ordered]@{
    execution='real_single_center_child_flights'
    corridor_field='native_full_corridor_at_0p25_mm'
    field_update='native_fast_adjust'
    child_runner='projects/parallel_mirror_dual_stripe_mr_tof/simion/run_two_prism_trial.ps1'
    stopping_authority='contract.downstream_fixed_grid_workpoint_profile.automatic_iteration'
  }
  if($nativeRecoveryProblem){$configuration.parameters.native_recovery_problem=$nativeRecoveryProblem}
  if($bootstrapPath){
    $configuration.inputs.voltage_seed_manifest=$frozenSeedManifest
    $configuration.inputs.voltage_seed_materialization=$frozenSeedMaterialization
    $configuration.parameters.voltage_seed_consumer_projection=$seedProjection
  }
  Write-RunJson -Path $package.run_config -Depth 20 -Value $configuration

  $terminalDecision = $null
  $pendingRecoveryDecision = $null
  $previousManifest = $initialManifest
  $startIteration = 1
  if ($ResumeParentCheckpoint -and -not $SeedTrialManifest) {
    $resumeParentResolved = (Resolve-Path -LiteralPath $ResumeParentCheckpoint).Path
    $resumeParentRun = if (Test-Path -LiteralPath $resumeParentResolved -PathType Leaf) {
      Split-Path -Parent $resumeParentResolved
    } else { $resumeParentResolved }
    $resumeParentManifest = Join-Path $resumeParentRun 'run_manifest.json'
    if (-not (Test-Path -LiteralPath $resumeParentManifest -PathType Leaf)) {
      throw "Resume parent checkpoint lacks run_manifest.json: $resumeParentRun"
    }
    $frozenResumeParentManifest = Copy-VerifiedRunInput -Source $resumeParentManifest `
      -Destination (Join-Path $package.input_dir 'resume_parent_checkpoint_manifest.json')
    $checkpointPath = Join-Path $package.result_dir 'reconstructed_checkpoint.json'
    Invoke-RunToolRootContext -RepoRoot $repoRoot -Operation {
      & $python -m projects.parallel_mirror_dual_stripe_mr_tof.analysis.downstream_workpoint_checkpoint `
        --old-parent-run $resumeParentRun --latest-child-manifest $resumeChildManifest `
        --current-initial-manifest $frozenInitialManifest --current-proposal $frozenProposal `
        --current-contract $frozenContract --artifact-project-runs (Join-Path $artifactRoot 'runs') `
        --output $checkpointPath
      if ($LASTEXITCODE -ne 0) { throw 'Previous automatic-workpoint checkpoint reconstruction failed.' }
    }
    $checkpoint = Get-Content -LiteralPath $checkpointPath -Raw | ConvertFrom-Json -AsHashtable
    $history = $checkpoint.history
    $lineage.children = @($checkpoint.lineage_children)
    foreach ($replayedDecision in $history.decisions) {
      if ($replayedDecision.role -eq 'mrtof_downstream_workpoint_iteration_recovery_model') { continue }
      $replayedIteration = [int]$replayedDecision.iteration
      if ($replayedIteration -lt 1 -or $replayedIteration -gt $lineage.children.Count) {
        throw "Replayed decision iteration is outside its child lineage: $replayedIteration"
      }
      $lineageIndex = $replayedIteration - 1
      if ([int]$lineage.children[$lineageIndex].iteration -ne $replayedIteration) {
        throw "Replayed decision iteration does not match its child lineage: $replayedIteration"
      }
      $replayedDecisionPath = Join-Path $package.result_dir ('iteration_{0:D2}_decision.json' -f $replayedIteration)
      Write-RunJson -Path $replayedDecisionPath -Depth 30 -Value $replayedDecision
      $lineage.children[$lineageIndex].decision = $replayedDecisionPath
      $lineage.children[$lineageIndex].decision_sha256 = `
        (Get-FileHash -LiteralPath $replayedDecisionPath -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    $current = @($checkpoint.current_voltages_v | ForEach-Object { [double]$_ })
    $startIteration = [int]$checkpoint.next_iteration
    $previousManifest = [string]$checkpoint.latest_child_manifest
    $pendingRecoveryDecision=$checkpoint.recovery_required_decision
    if($checkpoint.recovery_state_path){
      $priorRecovery=(Resolve-Path -LiteralPath ([string]$checkpoint.recovery_state_path)).Path
      Copy-Item -LiteralPath $priorRecovery -Destination $recoveryStatePath -Force
    }
    Write-RunJson -Path $historyPath -Depth 30 -Value $history
    Write-RunJson -Path $lineagePath -Depth 30 -Value $lineage
    # Bind the exact parent evidence file into this run.  The original run
    # directory is still passed to the replay tool above, but a directory is
    # not a valid manifest input and cannot be content verified.
    $configuration.inputs.resume_parent_checkpoint=$frozenResumeParentManifest
    $configuration.inputs.reconstructed_checkpoint=$checkpointPath
    Write-RunJson -Path $package.run_config -Depth 20 -Value $configuration
  }
  if($null-eq$pendingRecoveryDecision){
    $pendingRecoveryDecision=Get-InterruptedSOnlyTopologyRecoveryDecision -History $history
    if($null-ne$pendingRecoveryDecision){Write-Host "MRTOF_WORKPOINT_RECOVERY status=reconstructed reason=s_only_topology_loss"}
  }
  $maximumIterations = [int]((Get-Content -LiteralPath $frozenContract -Raw | ConvertFrom-Json).downstream_fixed_grid_workpoint_profile.automatic_iteration.maximum_iterations)
  if($null-ne$pendingRecoveryDecision){
    do{
      $recovery=Invoke-SLocalModelRecovery -Decision $pendingRecoveryDecision -History $history -Lineage $lineage `
        -StatePath $recoveryStatePath -HistoryPath $historyPath `
        -ContractDocument (Get-Content -LiteralPath $frozenContract -Raw|ConvertFrom-Json -AsHashtable)
    }while($recovery.status-eq'retry')
    if($recovery.status-eq'terminal'){
      $terminalDecision=[ordered]@{schema_version=1;role='mrtof_downstream_workpoint_iteration_decision';state='terminal';terminal_reason=$recovery.terminal_reason;iteration=$pendingRecoveryDecision.iteration;detail='resumed local S derivative recovery could not establish a history-validated model';best_accepted_workpoint=$recovery.accepted_anchor.record;recovery_state=$recovery}
    }else{
      $history.decisions += [ordered]@{schema_version=1;role='mrtof_downstream_workpoint_iteration_recovery_model';state='continue';recovery_after_iteration=$pendingRecoveryDecision.iteration;coordinate_group='stripe_1_stripe_2';accepted_workpoint=$recovery.accepted_anchor.record;local_s_physical_jacobian_columns=$recovery.model.local_s_physical_jacobian_columns;local_s_model_validation=$recovery.history_validation;recovery_state=$recovery;next_action='run_bounded_real_center_flight_from_accepted_anchor'}
      Write-RunJson -Path $historyPath -Depth 40 -Value $history
      $recoveryProposalPath=Join-Path $package.result_dir ('iteration_{0:D2}_recovery_first_candidate.json' -f $startIteration)
      $recoveryProposal=New-RecoveredSFirstCandidate -Recovery $recovery -History $history -Iteration $startIteration -OutputPath $recoveryProposalPath
      $history.decisions += $recoveryProposal
      Write-RunJson -Path $historyPath -Depth 40 -Value $history
      $current=@($recoveryProposal.proposed_voltages_v|ForEach-Object{[double]$_})
      $previousManifest=[string]$recovery.accepted_anchor.evidence.child_manifest
    }
  }
  # P1/P2, S1/S2, and invalid-topology backtracks each have an independent
  # bounded budget.  The hard attempt cap is therefore three contract budgets.
  $maximumFlightAttempts = 3 * $maximumIterations
  for ($iteration = $startIteration; $null-eq$terminalDecision-and$iteration -le $maximumFlightAttempts; $iteration++) {
    $failureStage = "real_center_flight_$iteration"
    $resumeThisIteration = (-not $ResumeParentCheckpoint -and $iteration -eq 1 -and $null -ne $resumeChildManifest)
    if ($resumeThisIteration) {
      $childManifest = $resumeChildManifest
      $childRunDir = Split-Path -Parent $childManifest
      $resumeManifestDocument = Get-Content -LiteralPath $childManifest -Raw | ConvertFrom-Json -AsHashtable
      $childRunId = [string]$resumeManifestDocument.run_id
      if ([string]::IsNullOrWhiteSpace($childRunId)) { throw 'Resume child manifest lacks run_id.' }
    } else {
      $childRunId = '{0}-iter-{1:D2}' -f $RunId,$iteration
      $childRunDir = Join-Path $artifactRoot "runs\$childRunId"
      $childManifest = Join-Path $childRunDir 'run_manifest.json'
    }
    $finalCacheKey = $null
    $trialArguments = New-CenterTrialArguments -Voltages $current -ChildRunId $childRunId

    $solverError = $null
    if (-not $resumeThisIteration) {
      try { & $trialRunner @trialArguments }
      catch { $solverError = $_.Exception.Message }
    }
    if ($solverError) {
      $terminalDecision = [ordered]@{
        schema_version=1;role='mrtof_downstream_workpoint_iteration_decision'
        state='terminal';terminal_reason='solver_failure';iteration=$iteration;detail=$solverError
      }
      $decisionPath = Join-Path $package.result_dir ('iteration_{0:D2}_decision.json' -f $iteration)
      Write-RunJson -Path $decisionPath -Depth 20 -Value $terminalDecision
      $childRecord = [ordered]@{
        iteration=$iteration;run_id=$childRunId;parent_manifest=$previousManifest
        parent_manifest_sha256=(Get-FileHash -LiteralPath $previousManifest -Algorithm SHA256).Hash.ToLowerInvariant()
        decision=$decisionPath;operating_cache_key=$finalCacheKey
      }
      if (Test-Path -LiteralPath $childManifest -PathType Leaf) {
        $childRecord.child_manifest=$childManifest
        $childRecord.child_manifest_sha256=(Get-FileHash -LiteralPath $childManifest -Algorithm SHA256).Hash.ToLowerInvariant()
      }
      $lineage.children += $childRecord
      break
    }
    $observation = Get-ManifestOutputPath -ManifestPath $childManifest -FileName 'two_prism_trial_observation.json'
    $materialization = Get-ManifestOutputPath -ManifestPath $childManifest -FileName 'two_prism_trial_materialization.json'
    $cacheIdentity = Get-ManifestOutputPath -ManifestPath $childManifest -FileName 'native_corridor_runtime_family.json'
    $childProtectionPath = Get-ManifestOutputPath -ManifestPath $childManifest -FileName 'native_corridor_protection_renewal.json'
    # The parent consumes these four compact, named records.  The child has
    # already performed its own full publication validation, so rehashing every
    # child PA here would only repeat multi-GiB reads without strengthening this
    # controller's evidence binding.
    $childProjectionArgs=@($childManifest,'--require-status','success','--require-project',$project,
      '--require-mode','finite_3d_two_prism_voltage_trial','--consumer-projection-id','mrtof_downstream_iteration_child_v1',
      '--consumed-output',$observation,'--consumed-output',$materialization,
      '--consumed-output',$cacheIdentity,'--consumed-output',$childProtectionPath)
    & $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') @childProjectionArgs
    if ($LASTEXITCODE -ne 0) { throw "Child flight manifest projection is invalid: $childManifest" }
    $cacheBindingPath = Join-Path $package.result_dir ('iteration_{0:D2}_cache_binding.json' -f $iteration)
    $cacheBindingArguments = @(
      '-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.downstream_workpoint_iteration',
      '--cache-identity',$cacheIdentity,
      '--cache-protection-renewal',$childProtectionPath,
      '--output',$cacheBindingPath
    )
    if (-not $resumeThisIteration) {
      $cacheBindingArguments += @(
        '--expected-lease-id',([string]$capacitySession.lease_id),
        '--expected-lease-owner',$protectionLeaseOwner
      )
    }
    Invoke-RunToolRootContext -RepoRoot $repoRoot -Operation {
      & $python @cacheBindingArguments
      if ($LASTEXITCODE -ne 0) { throw "Child operating-cache binding is invalid: $childManifest" }
    }
    $cacheBinding = Get-Content -LiteralPath $cacheBindingPath -Raw | ConvertFrom-Json -AsHashtable
    if(-not $proposal.ContainsKey('native_bank_identity') -or $null-eq$proposal.native_bank_identity -or
      $proposal.native_bank_identity.cache_key-ne$cacheBinding.native_bank_identity.cache_key -or
      $proposal.native_bank_identity.generation_sha256-ne$cacheBinding.native_bank_identity.generation_sha256){
      throw 'Native child field differs from the measured Jacobian bank.'
    }
    $operatingCacheKey = [string]$cacheBinding.cache_key
    $operatingGenerationDirectory = [string]$cacheBinding.generation_directory
    if (-not (Test-Path -LiteralPath $operatingGenerationDirectory -PathType Container)) {
      throw "Child operating-cache generation is missing: $operatingGenerationDirectory"
    }
    $childProtection = Get-Content -LiteralPath $childProtectionPath -Raw | ConvertFrom-Json -AsHashtable
    if ($resumeThisIteration) {
      $resumeProtection = Update-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot `
        -Session $capacitySession -ProtectedCacheKeys @($operatingCacheKey) `
        -ProtectedPaths @($operatingGenerationDirectory)
      $capacitySession = $resumeProtection.session
      $resumeProtectionPath = Join-Path $package.result_dir ('capacity_protection_iteration_{0:D2}_resume_renew.json' -f $iteration)
      Write-RunJson -Path $resumeProtectionPath -Depth 20 -Value $resumeProtection
      $protectionReceipts += $resumeProtectionPath
    }
    $finalCacheKey = $operatingCacheKey
    $materializationDocument = Get-Content -LiteralPath $materialization -Raw | ConvertFrom-Json -AsHashtable
    $materializedVoltages = @(
      @($materializationDocument.stripe_biases_v) + @($materializationDocument.prism_voltages_v) |
        ForEach-Object { [double]$_ }
    )
    if ($materializedVoltages.Count -ne 4 -or
        @(0..3 | Where-Object { [math]::Abs($materializedVoltages[$_] - $current[$_]) -gt 1e-10 }).Count -ne 0) {
      throw "Child materialization does not match the controller's requested voltage vector: $childManifest"
    }
    $childConfig = Get-Content -LiteralPath (Join-Path $childRunDir 'run_config.json') -Raw | ConvertFrom-Json -Depth 50
    $expectedBinding='native_corridor_private_fast_adjust_family__four_instances__n1'
    if ([string]$childConfig.parameters.pa_binding_mode -ne $expectedBinding) {
      throw "Child flight did not use scoped fixed-grid response composition: $childManifest"
    }
    $decisionPath = Join-Path $package.result_dir ('iteration_{0:D2}_decision.json' -f $iteration)
    $failureStage = "decide_iteration_$iteration"
    Push-Location -LiteralPath $repoRoot
    try {
      & $python -m projects.parallel_mirror_dual_stripe_mr_tof.analysis.downstream_workpoint_iteration `
        --prior $frozenProposal --observation $observation --materialization $materialization `
        --child-manifest $childManifest --contract $frozenContract --history $historyPath --iteration $iteration --output $decisionPath
      if ($LASTEXITCODE -ne 0) { throw "Iteration controller failed at iteration $iteration." }
    } finally { Pop-Location }
    $decision = Get-Content -LiteralPath $decisionPath -Raw | ConvertFrom-Json -AsHashtable
    $history.decisions += $decision
    Write-RunJson -Path $historyPath -Depth 30 -Value $history
    $lineage.children += [ordered]@{
      iteration=$iteration;run_id=$childRunId;parent_manifest=$previousManifest
      parent_manifest_sha256=(Get-FileHash -LiteralPath $previousManifest -Algorithm SHA256).Hash.ToLowerInvariant()
      child_manifest=$childManifest
      child_manifest_sha256=(Get-FileHash -LiteralPath $childManifest -Algorithm SHA256).Hash.ToLowerInvariant()
      observation=$observation;materialization=$materialization;decision=$decisionPath
      decision_sha256=(Get-FileHash -LiteralPath $decisionPath -Algorithm SHA256).Hash.ToLowerInvariant()
      operating_cache_identity=$cacheIdentity
      operating_cache_identity_sha256=(Get-FileHash -LiteralPath $cacheIdentity -Algorithm SHA256).Hash.ToLowerInvariant()
      operating_cache_binding=$cacheBindingPath
      operating_cache_binding_sha256=(Get-FileHash -LiteralPath $cacheBindingPath -Algorithm SHA256).Hash.ToLowerInvariant()
      operating_cache_key=$operatingCacheKey
      operating_cache_protection_renewal=$childProtectionPath
      operating_cache_protection_renewal_sha256=(Get-FileHash -LiteralPath $childProtectionPath -Algorithm SHA256).Hash.ToLowerInvariant()
      capacity_protection_lease_id=[string]$capacitySession.lease_id
      resumed_successful_child=$resumeThisIteration
      pa_binding_mode=[string]$childConfig.parameters.pa_binding_mode
    }
    Write-RunJson -Path $lineagePath -Depth 30 -Value $lineage
    if($decision.state-eq'recovery_required'){
      do{
        $recovery=Invoke-SLocalModelRecovery -Decision $decision -History $history -Lineage $lineage `
          -StatePath $recoveryStatePath -HistoryPath $historyPath `
          -ContractDocument (Get-Content -LiteralPath $frozenContract -Raw|ConvertFrom-Json -AsHashtable)
      }while($recovery.status-eq'retry')
      if($recovery.status-eq'terminal'){
        $terminalDecision=[ordered]@{schema_version=1;role='mrtof_downstream_workpoint_iteration_decision';state='terminal';terminal_reason=$recovery.terminal_reason;iteration=$iteration;detail='automatic local S derivative recovery could not establish a history-validated model';best_accepted_workpoint=$recovery.accepted_anchor.record;recovery_state=$recovery}
        break
      }
      $history.decisions += [ordered]@{
        schema_version=1;role='mrtof_downstream_workpoint_iteration_recovery_model';state='continue'
        recovery_after_iteration=$iteration;coordinate_group='stripe_1_stripe_2';accepted_workpoint=$recovery.accepted_anchor.record
        local_s_physical_jacobian_columns=$recovery.model.local_s_physical_jacobian_columns
        local_s_model_validation=$recovery.history_validation;recovery_state=$recovery
        next_action='run_bounded_real_center_flight_from_accepted_anchor'
      }
      Write-RunJson -Path $historyPath -Depth 40 -Value $history
      $recoveryProposalPath=Join-Path $package.result_dir ('iteration_{0:D2}_recovery_first_candidate.json' -f ($iteration+1))
      $recoveryProposal=New-RecoveredSFirstCandidate -Recovery $recovery -History $history -Iteration ($iteration+1) -OutputPath $recoveryProposalPath
      $history.decisions += $recoveryProposal
      Write-RunJson -Path $historyPath -Depth 40 -Value $history
      $current=@($recoveryProposal.proposed_voltages_v|ForEach-Object{[double]$_})
      $previousManifest=[string]$recovery.accepted_anchor.evidence.child_manifest
      Write-Host "MRTOF_WORKPOINT_RECOVERY status=validated next_action=run_bounded_real_center_flight_from_accepted_anchor remaining_probe_budget=$($recovery.probe_budget_remaining)"
      continue
    }
    $previousManifest = $childManifest
    if ($decision.state -eq 'terminal') {
      $terminalDecision = $decision
      break
    }
    Write-RunJson -Path $package.summary -Depth 20 -Value ([ordered]@{
      schema_version=1;role='mrtof_downstream_workpoint_iteration_summary';status='checkpoint'
      workflow_outcome='continue';completed_iterations=$iteration;next_iteration=($iteration + 1)
      latest_child_manifest=$childManifest
    })
    $checkpointOutputs = @($package.summary,$historyPath,$lineagePath) + @($protectionReceipts) + @(
      Get-ChildItem -LiteralPath $package.result_dir -Filter 'iteration_*_decision.json' -File | ForEach-Object { $_.FullName }
    ) + @(
      Get-ChildItem -LiteralPath $package.result_dir -Filter 'iteration_*_cache_binding.json' -File | ForEach-Object { $_.FullName }
    )
    if(Test-Path -LiteralPath $recoveryStatePath -PathType Leaf){$checkpointOutputs += $recoveryStatePath}
    $reconstructedCheckpointPath = Join-Path $package.result_dir 'reconstructed_checkpoint.json'
    if (Test-Path -LiteralPath $reconstructedCheckpointPath -PathType Leaf) { $checkpointOutputs += $reconstructedCheckpointPath }
    if($null-ne$nativeRuntimeSession-and(Test-Path -LiteralPath $nativeRuntimeSession.checkpoint_path)){$checkpointOutputs+=$nativeRuntimeSession.checkpoint_path}
    Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config `
      -Status checkpoint -Software @('SIMION 2020','Python 3.11','NumPy') -Outputs $checkpointOutputs
    $current = @($decision.proposed_voltages_v | ForEach-Object { [double]$_ })
  }
  if ($null -eq $terminalDecision) { throw 'Iteration loop exhausted without a terminal decision.' }
  Write-RunJson -Path $lineagePath -Depth 30 -Value $lineage
  $failureStage = 'publish'
  if($null-ne$nativeRuntimeSession){
    $bestPhysicalHandoffPath=Join-Path $package.result_dir 'best_physical_workpoint_handoff.json'
    Push-Location -LiteralPath $repoRoot
    try {
      & $python -m projects.parallel_mirror_dual_stripe_mr_tof.analysis.downstream_workpoint_iteration `
        --select-best-physical-workpoint --history $historyPath --output $bestPhysicalHandoffPath | Out-Host
      if($LASTEXITCODE-ne0){throw 'Could not select the best complete physical workpoint for downstream screening.'}
    } finally { Pop-Location }
    $terminalDecision.best_physical_workpoint_handoff=$bestPhysicalHandoffPath
    $nativeOutcome=if($terminalDecision.terminal_reason-eq'success'){'workpoint_complete_downstream_pending'}else{'workpoint_warning_downstream_authorized'}
    Save-NativeWorkflowCheckpoint -Reason ([string]$terminalDecision.terminal_reason) -WorkflowOutcome $nativeOutcome -FinalDecision $terminalDecision
    $terminalized=$true
    Write-Host "MRTOF_DOWNSTREAM_AUTO_WORKPOINT=$($terminalDecision.terminal_reason) CHECKPOINT=$nativeOutcome RUN_ID=$RunId"
    if($terminalDecision.terminal_reason-eq'success'-and-not[string]::IsNullOrWhiteSpace($BunchSourceReceiptPath)){
      # Release the workpoint owner's runtime and capacity lease before the
      # downstream workflow reopens the same checkpointed family.  The handoff
      # therefore remains one-way and never nests two owners of the large PA set.
      Suspend-NativeCorridorRuntimeSession -Session $nativeRuntimeSession
      $nativeRuntimeSession=$null
      $null=Exit-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $capacitySession
      $capacitySession=$null
      $screeningArguments=@{
        WorkpointRunPath=$package.artifact_run_dir
        NativeCorridorBankRunPath=$NativeCorridorBankRunPath
        BunchSourceReceiptPath=$BunchSourceReceiptPath
        RunId=$RunId+'-bunch'
        PythonExe=$python
      }
      if($SimionExe){$screeningArguments.SimionExe=$SimionExe}
      & $bunchScreeningRunner @screeningArguments
    }
    return
  }
  Write-RunJson -Path $package.summary -Depth 20 -Value ([ordered]@{
    schema_version=1;role='mrtof_downstream_workpoint_iteration_summary';status='success'
    workflow_outcome=$terminalDecision.terminal_reason;iteration_count=$lineage.children.Count
    contract_satisfied=($terminalDecision.terminal_reason -eq 'success')
    final_decision=$terminalDecision
    qualification=$(if($terminalDecision.terminal_reason -eq 'success'){'real_center_fixed_grid_workpoint'}else{'stopped_without_workpoint_qualification'})
  })
  $retention = Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config
  $capacityTerminal = Update-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot `
    -Session $capacitySession -RemainingCommittedNewBytes 0
  $capacitySession = $capacityTerminal.session
  $capacityTerminalPath = Join-Path $package.result_dir 'artifact_capacity_gate_terminal.json'
  Write-RunJson -Path $capacityTerminalPath -Depth 20 -Value $capacityTerminal
  $protectionReceipts += $capacityTerminalPath
  $outputs = @($package.summary,$historyPath,$lineagePath,$retention) + @($protectionReceipts) + @(
    Get-ChildItem -LiteralPath $package.result_dir -Filter 'iteration_*_decision.json' -File | ForEach-Object { $_.FullName }
  ) + @(
    Get-ChildItem -LiteralPath $package.result_dir -Filter 'iteration_*_cache_binding.json' -File | ForEach-Object { $_.FullName }
  )
  Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config `
    -Status success -Software @('SIMION 2020','Python 3.11','NumPy') -Outputs $outputs
  $terminalized = $true
  Write-Host "MRTOF_DOWNSTREAM_AUTO_WORKPOINT=$($terminalDecision.terminal_reason) RUN_ID=$RunId"
} catch {
  Write-Host "MRTOF_WORKPOINT_FAILURE stage=$failureStage reason=$($_.Exception.Message)"
  if($null-ne$nativeRuntimeSession-and$nativeRuntimeSession.directory-and(Test-Path -LiteralPath $nativeRuntimeSession.directory)){
    Save-NativeWorkflowCheckpoint -Reason $_.Exception.Message
    $terminalized=$true
  }
  if (-not $terminalized) {
    Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config -Summary $package.summary `
      -SummaryRole mrtof_downstream_workpoint_iteration_summary -Reason $_.Exception.Message `
      -Software @('SIMION 2020','Python 3.11','NumPy') -Status failed -FailureStage $failureStage
    $terminalized = $true
  }
  throw
} finally {
  if($null-ne$nativeRuntimeSession){Suspend-NativeCorridorRuntimeSession -Session $nativeRuntimeSession}
  if(-not$terminalized-and$null-ne$nativeRuntimeSession-and$nativeRuntimeSession.directory-and(Test-Path -LiteralPath $nativeRuntimeSession.directory)){
    Save-NativeWorkflowCheckpoint -Reason 'Automatic workpoint workflow externally interrupted; retained for a new parent run.' -ExternalInterruption
    $terminalized=$true
  }
  if (-not $terminalized) {
    Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config -Summary $package.summary `
      -SummaryRole mrtof_downstream_workpoint_iteration_summary -Reason 'Automatic workpoint workflow interrupted.' `
      -Software @('SIMION 2020','Python 3.11','NumPy') -Status interrupted -FailureStage $failureStage
  }
  if ($null -ne $capacitySession) {
    $null = Exit-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $capacitySession
  }
}

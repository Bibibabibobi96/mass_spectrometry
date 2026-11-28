[CmdletBinding(DefaultParameterSetName='Legacy')]
param(
  [Parameter(Mandatory,ParameterSetName='Legacy')][string]$AcceleratorComponentContractPath,
  [Parameter(Mandatory,ParameterSetName='Legacy')][string]$AcceleratorGeometryProfileId,
  [string]$InitialWorkpointManifest = '',
  [string]$SeedTrialManifest = '',
  [string]$Stripe1PerturbationManifest = '',
  [string]$Stripe2PerturbationManifest = '',
  [string]$PrismHandoffReplayManifest = '',
  [string]$PriorPrismDecisionManifest = '',
  [string]$ContinuationRunManifest = '',
  [string]$NativeCorridorBankRunPath = '',
  [Parameter(Mandatory,ParameterSetName='Legacy')][string]$GeometryReviewRunPath,
  [Parameter(Mandatory,ParameterSetName='Legacy')][string]$MirrorRunPath,
  [Parameter(Mandatory,ParameterSetName='Legacy')][string]$StripeRunPath,
  [Parameter(Mandatory,ParameterSetName='Legacy')][string]$AcceleratorProviderReceiptPath,
  [Parameter(Mandatory,ParameterSetName='Legacy')][string]$CompositionPlanPath,
  [string]$LocalScopePath='',
  [string]$NativeSystemRuntimeBundlePath = '',
  [string]$BunchSourceReceiptPath = '',
  [string]$FieldProviderRequestPath = '',
  [string]$CompletedFieldProviderManifest = '',
  [string]$ResponseFieldBindingPath = '',
  [string]$CenterSourceReceiptPath = '',
  [switch]$PulseAcceleratorUntilInitialExit,
  [string]$AcceleratorPulseSchedulePath = '',
  [string]$MirrorVoltageVariationPath = '',
  [string]$TrajectoryProfileId = '',
  [double]$TrajectoryStepScale = 1.0,
  [double]$AcceleratorSourceYOffsetMm = 0.0,
  [Nullable[double]]$AcceleratorYAnchorMm = $null,
  [Nullable[double]]$Prism1SearchMinimumV = $null,
  [Nullable[double]]$Prism1SearchMaximumV = $null,
  [Nullable[double]]$Prism2SearchMinimumV = $null,
  [Nullable[double]]$Prism2SearchMaximumV = $null,
  [switch]$RetainBaselineGuiWorkbench,
  [string]$ResumeParentCheckpoint = '',
  # A new controller contract may alter acceptance tolerances without changing
  # any PA-producing input.  Reuse only a checkpointed private runtime family;
  # it never imports the prior controller state or iteration evidence.
  [string]$NativeRuntimeCheckpoint = '',
  [string]$ResumeSuccessfulChildManifest = '',
  [string]$ContractPath = '',
  [string]$PrismControllerPolicyPath = '',
  [string]$LocalModelRecoveryPolicyPath = '',
  [string]$RunId = '',
  [string]$SimionExe = '',
  [Parameter(Mandatory)][string]$WorkspaceRoot,
  [Parameter(Mandatory)][string]$ArtifactRoot,
  [Parameter(Mandatory)][string]$PythonExe
)

# Production workflow: each iteration is a separately manifested real N=1
# flight.  This parent owns only the finite-state decisions and lineage chain.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$workspaceRoot = (Resolve-Path -LiteralPath $WorkspaceRoot).Path
$artifactWorkspaceRoot = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($ArtifactRoot)
$repoRoot = $workspaceRoot
$python = [IO.Path]::GetFullPath($PythonExe)
$packageRootText = & $python -I -B -c 'from pathlib import Path;import msplatform;print(Path(msplatform.__file__).resolve().parent)'
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace([string]$packageRootText)) { throw 'Installed msplatform package is unavailable.' }
$packageRoot = (Resolve-Path -LiteralPath ([string]$packageRootText).Trim()).Path
$executionResources = Join-Path $packageRoot 'execution/resources'
. (Join-Path $executionResources 'run_artifact_support.ps1')
. (Join-Path $packageRoot 'backends/simion/resources/native_corridor_runtime_support.ps1')
$project = 'multi_reflection_tof'
$projectRoot = Join-Path $packageRoot 'components/multi_reflection_tof'
$pathContext = Resolve-WorkspacePaths -SourceRoot $workspaceRoot -ArtifactRoot $artifactWorkspaceRoot -Python $python
$artifactWorkspaceRoot = [string]$pathContext.artifact_root
$hostContext = @{workspace=$workspaceRoot;python_executable=$python;host_state_path=[string]$pathContext.host_resource_state_path;policy_path=(Join-Path $executionResources 'host_resource_policy.json')}
. (Join-Path $executionResources 'host_execution_lease.ps1') -HostContext $hostContext
$contract = if ($ContractPath) { (Resolve-Path -LiteralPath $ContractPath).Path } else { Join-Path $projectRoot 'simion_candidate_two_zone.json' }
$frozenPrismControllerPolicyPath=''
$recoveryPolicySource=if($LocalModelRecoveryPolicyPath){(Resolve-Path -LiteralPath $LocalModelRecoveryPolicyPath).Path}else{Join-Path $projectRoot 'config/local_model_recovery_policy.json'}
if($PrismControllerPolicyPath){$PrismControllerPolicyPath=(Resolve-Path -LiteralPath $PrismControllerPolicyPath).Path}
$trialRunner = Join-Path $packageRoot 'workflows/resources/oa_mr.ps1'
$auditRunner = Join-Path $packageRoot 'workflows/resources/run_downstream_fixed_grid_workpoint.ps1'
$bunchScreeningRunner = Join-Path $packageRoot 'workflows/resources/run_native_corridor_bunch_screening.ps1'
$artifactRoot = Resolve-RunArtifactRoot -ArtifactRoot $artifactWorkspaceRoot -OwnerKind component -OwnerId $project -Python $python
$trialArtifactRoot = Resolve-RunArtifactRoot -ArtifactRoot $artifactWorkspaceRoot -OwnerKind assembly -OwnerId instrument_assembly -Python $python

$mirrorVoltageVariation=if([string]::IsNullOrWhiteSpace($MirrorVoltageVariationPath)){$null}else{(Resolve-Path -LiteralPath $MirrorVoltageVariationPath).Path}
if (-not $RunId) { $RunId = (Get-Date -Format 'yyyyMMdd_HHmmss') + '__sim__simion__mrtof-downstream-auto-workpoint' }
$staticFieldMode=-not[string]::IsNullOrWhiteSpace($FieldProviderRequestPath)
if($CompletedFieldProviderManifest-and-not$staticFieldMode){throw 'Completed field provider requires static field iteration.'}
if($CompletedFieldProviderManifest){$CompletedFieldProviderManifest=(Resolve-Path -LiteralPath $CompletedFieldProviderManifest).Path}
$fieldProviderRunner=Join-Path $packageRoot 'backends/comsol/launcher/run_corridor_field_provider.ps1'
$fieldProviderRequest=$null;$staticBinding=$null
$staticBindingMode='comsol_static_scalar_v'
$responseBinding=$null;$responseDeclaration=$null
if($ResponseFieldBindingPath-and-not$staticFieldMode){throw 'Response field binding requires static field iteration.'}
if($ResponseFieldBindingPath){
  $ResponseFieldBindingPath=(Resolve-Path -LiteralPath $ResponseFieldBindingPath).Path
  $responseDeclaration=Get-Content -LiteralPath $ResponseFieldBindingPath -Raw|ConvertFrom-Json -AsHashtable
  & {
    $script:responseBinding=((& $python -I -B -m msplatform.backends.comsol.static_field_binding --binding $ResponseFieldBindingPath)-join"`n")|ConvertFrom-Json -AsHashtable
    if($LASTEXITCODE-ne0){throw 'Declared response field binding is invalid.'}
  }
  if($responseDeclaration.schema_version-ne2-or$responseBinding.representation-ne'exploratory_affine_ps_responses'){throw 'Active response input must declare the version-two exploratory PS basis.'}
}
if($staticFieldMode){
  if($NativeCorridorBankRunPath-or$NativeSystemRuntimeBundlePath-or$NativeRuntimeCheckpoint){throw 'Static field iteration does not consume a native bank/family/checkpoint.'}
  if($PulseAcceleratorUntilInitialExit-or$AcceleratorPulseSchedulePath){throw 'Static field iteration cannot consume an OA pulse.'}
  if(-not$CenterSourceReceiptPath){throw 'Static field iteration requires the frozen common centre receipt.'}
  $fieldProviderRequest=Get-Content -LiteralPath (Resolve-Path $FieldProviderRequestPath).Path -Raw|ConvertFrom-Json -AsHashtable
  if($fieldProviderRequest.schema_version-ne1-or$fieldProviderRequest.role-notin@('mrtof_same_mesh_field_provider_request','mrtof_native_static_field_provider_request')){throw 'Invalid static field provider request.'}
  if($fieldProviderRequest.role-eq'mrtof_native_static_field_provider_request'){
    $staticBindingMode='native_static_pa'
    $fieldProviderRunner=Join-Path $packageRoot 'backends/simion/resources/run_native_static_field_provider.ps1'
    if($ResponseFieldBindingPath){throw 'Native static field production does not consume COMSOL response fields.'}
    if($CompletedFieldProviderManifest){throw 'Native static provider replay is not yet supported; unchanged voltages reuse the source binding.'}
  }
  & {
    $script:staticBinding=((& $python -I -B -m msplatform.backends.comsol.static_field_binding --binding $fieldProviderRequest.source_binding_path)-join"`n")|ConvertFrom-Json -AsHashtable
    if($LASTEXITCODE-ne0){throw 'Static source binding is invalid.'}
  }
  if($staticBinding.mode-ne$staticBindingMode){throw 'Static field request and source solver modes differ.'}
}else{
  if ([string]::IsNullOrWhiteSpace($NativeCorridorBankRunPath)) { throw 'NativeCorridorBankRunPath is required.' }
  if ([string]::IsNullOrWhiteSpace($NativeSystemRuntimeBundlePath)) { throw 'NativeCorridorBankRunPath requires NativeSystemRuntimeBundlePath.' }
}
$startInputs=@(@($InitialWorkpointManifest,$SeedTrialManifest,$ContinuationRunManifest)|Where-Object{-not[string]::IsNullOrWhiteSpace($_)})
if($startInputs.Count-ne1){throw 'Supply exactly one InitialWorkpointManifest, SeedTrialManifest, or ContinuationRunManifest.'}
$freshBootstrap=[bool]($SeedTrialManifest-or$ContinuationRunManifest)
$stagedBootstrap=$staticFieldMode-and$freshBootstrap
if($PrismControllerPolicyPath-and-not$stagedBootstrap){throw 'Prism controller policy requires the existing staged static-field workflow.'}
$stripeSeedColumns=[ordered]@{}
foreach($pair in @(@('0',$Stripe1PerturbationManifest),@('1',$Stripe2PerturbationManifest))){
  if($pair[1]){$stripeSeedColumns[$pair[0]]=(Resolve-Path -LiteralPath $pair[1]).Path}
}
if($stripeSeedColumns.Count-and(-not$staticFieldMode-or-not$SeedTrialManifest-or$ResumeParentCheckpoint)){
  throw 'Explicit Stripe columns require a fresh static-field SeedTrialManifest.'
}
if($stripeSeedColumns.Count-eq2-and$stripeSeedColumns['0']-eq$stripeSeedColumns['1']){throw 'Explicit Stripe columns must be distinct children.'}
if($PrismHandoffReplayManifest-and-not$stagedBootstrap){throw 'P handoff replay requires static-field seed preclosure.'}
if($PrismHandoffReplayManifest){$PrismHandoffReplayManifest=(Resolve-Path -LiteralPath $PrismHandoffReplayManifest).Path}
if($PriorPrismDecisionManifest-and-not$stagedBootstrap){throw 'Prior prism model requires static-field seed preclosure.'}
if($PriorPrismDecisionManifest){$PriorPrismDecisionManifest=(Resolve-Path -LiteralPath $PriorPrismDecisionManifest).Path}
if ($freshBootstrap -and $ResumeSuccessfulChildManifest) { throw 'Fresh bootstrap does not accept an iteration child override.' }
if ($ResumeParentCheckpoint -and -not $ResumeSuccessfulChildManifest -and -not $freshBootstrap) {
  throw 'ResumeParentCheckpoint requires ResumeSuccessfulChildManifest as the retained replay tip.'
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

function New-InitialGroupedWorkpointDecision {
  param(
    [Parameter(Mandatory)][Collections.IDictionary]$Proposal,
    [Parameter(Mandatory)][string]$ProposalPath,
    [Parameter(Mandatory)][string]$ContractPath,
    [Parameter(Mandatory)][string]$HistoryPath,
    [Parameter(Mandatory)][string]$OutputPath
  )
  $baselineManifest = (Resolve-Path -LiteralPath ([string]$Proposal.baseline_manifest)).Path
  $baselineObservation = Get-ManifestOutputPath -ManifestPath $baselineManifest -FileName 'two_prism_trial_observation.json'
  $baselineMaterialization = Get-ManifestOutputPath -ManifestPath $baselineManifest -FileName 'two_prism_trial_materialization.json'
  & {
    & $python -I -B -m msplatform.workflows.mr_design.downstream_workpoint `
      --prior $ProposalPath --observation $baselineObservation --materialization $baselineMaterialization `
      --child-manifest $baselineManifest --contract $ContractPath --history $HistoryPath --iteration 1 --output $OutputPath
    if ($LASTEXITCODE -ne 0) { throw 'Initial grouped workpoint decision failed.' }
  } | Out-Host
  $decision = Get-Content -LiteralPath $OutputPath -Raw | ConvertFrom-Json -AsHashtable
  if ($decision.state -eq 'continue') {
    $materialization = Get-Content -LiteralPath $baselineMaterialization -Raw | ConvertFrom-Json -AsHashtable
    $baselineVoltages = @(
      @($materialization.stripe_biases_v) + @($materialization.prism_voltages_v) |
        ForEach-Object { [double]$_ }
    )
    $proposedVoltages = @($decision.proposed_voltages_v | ForEach-Object { [double]$_ })
    if ($baselineVoltages.Count -ne 4 -or $proposedVoltages.Count -ne 4) {
      throw 'Initial grouped workpoint decision must bind four voltages.'
    }
    $inactiveIndices = switch ([string]$decision.coordinate_group) {
      'prism_1_prism_2' { @(0,1); break }
      'stripe_1_stripe_2' { @(2,3); break }
      default { throw "Initial grouped workpoint decision selected an unsupported coordinate group: $($decision.coordinate_group)" }
    }
    if (@($inactiveIndices | Where-Object {
      [math]::Abs($proposedVoltages[$_] - $baselineVoltages[$_]) -gt 1e-10
    }).Count -ne 0) {
      throw 'Initial grouped workpoint decision changed an inactive voltage coordinate.'
    }
  } elseif ($decision.state -ne 'terminal') {
    throw "Initial grouped workpoint decision returned unsupported state: $($decision.state)"
  }
  return $decision
}

function Read-ContinuationVoltageSeed {
  param([Parameter(Mandatory)][string]$ManifestPath)
  $resolved=(Resolve-Path -LiteralPath $ManifestPath).Path
  $manifest=Get-Content -LiteralPath $resolved -Raw|ConvertFrom-Json -AsHashtable
  if($manifest.status-ne'success'-or$manifest.project-ne$project-or
    $manifest.mode-ne'two_prism_segmented_voltage_branch_continuation'){
    throw 'Continuation seed must be a successful managed two-prism continuation run.'
  }
  $summaryPath=Get-ManifestOutputPath -ManifestPath $resolved -FileName 'summary.json'
  $summary=Get-Content -LiteralPath $summaryPath -Raw|ConvertFrom-Json -AsHashtable
  $continuation=$summary.continuation
  $candidates=@($continuation.joint_root_candidates)
  if($summary.schema_version-ne1-or
    $summary.role-ne'mrtof_two_prism_segmented_voltage_branch_continuation'-or
    $summary.status-ne'continuation_complete'-or$continuation.solve_mode-ne'angle_then_y'-or
    $continuation.joint_root_tolerance_reached-isnot[bool]-or-not$continuation.joint_root_tolerance_reached-or
    $candidates.Count-ne1){
    throw 'Continuation must publish exactly one tolerance-qualified angle-then-y joint root.'
  }
  $candidate=$candidates[0]
  $p1=[double]$candidate.p1_voltage_v;$p2=[double]$candidate.p2_voltage_v
  if(-not[double]::IsFinite($p1)-or-not[double]::IsFinite($p2)){
    throw 'Continuation joint-root prism voltages must be finite.'
  }
  $p1Bounds=@($summary.controls.continuation.p1_bounds_v|ForEach-Object{[double]$_})
  $p2Bounds=@($summary.controls.continuation.p2_bounds_v|ForEach-Object{[double]$_})
  if($p1Bounds.Count-ne2-or$p2Bounds.Count-ne2-or$p1Bounds[0]-ge$p1Bounds[1]-or$p2Bounds[0]-ge$p2Bounds[1]){
    throw 'Continuation voltage bounds are invalid.'
  }
  return [pscustomobject]@{
    manifest=$resolved;summary=$summaryPath;prism_voltages_v=@($p1,$p2)
    prism_voltage_bounds_v=@($p1Bounds,$p2Bounds)
    topology_signature_sha256=[string]$continuation.expected_topology_signature_sha256
  }
}

function Resolve-RunRecordPath {
  param([Parameter(Mandatory)]$Record,[Parameter(Mandatory)][string]$BaseDirectory,[Parameter(Mandatory)][string]$Label)
  if($Record-isnot[Collections.IDictionary]-or-not$Record.Contains('path')-or[string]::IsNullOrWhiteSpace([string]$Record.path)){
    throw "$Label record is incomplete."
  }
  $declared=[string]$Record.path
  $candidate=if([IO.Path]::IsPathRooted($declared)){$declared}else{Join-Path $BaseDirectory $declared}
  return (Resolve-Path -LiteralPath $candidate).Path
}

function Assert-ContinuationPairIdentity {
  param(
    [Parameter(Mandatory)][string]$ContinuationManifestPath,
    [Parameter(Mandatory)][string]$ResolvedContractPath,
    [Parameter(Mandatory)][string]$StripeRunDirectory
  )
  $continuationManifest=(Resolve-Path -LiteralPath $ContinuationManifestPath).Path
  $continuationRoot=Split-Path -Parent $continuationManifest
  $manifest=Get-Content -LiteralPath $continuationManifest -Raw|ConvertFrom-Json -AsHashtable
  foreach($name in @('parent_coverage_run_manifest','downstream_contract','parent_fixed_mirror_stripe_run_manifest')){
    if(-not$manifest.inputs.Contains($name)){throw "Continuation is missing its frozen $name identity."}
  }
  $coverageManifestPath=Resolve-RunRecordPath -Record $manifest.inputs.parent_coverage_run_manifest -BaseDirectory $continuationRoot -Label 'coverage manifest'
  $coverageManifest=Get-Content -LiteralPath $coverageManifestPath -Raw|ConvertFrom-Json -AsHashtable
  if($coverageManifest.status-ne'success'-or$coverageManifest.project-ne$project-or
    $coverageManifest.mode-ne'two_prism_segmented_voltage_branch_coverage'){
    throw 'Continuation parent is not a successful segmented coverage run.'
  }
  $frozenContractPath=Resolve-RunRecordPath -Record $manifest.inputs.downstream_contract -BaseDirectory $continuationRoot -Label 'continuation contract'
  $frozenStripeManifestPath=Resolve-RunRecordPath -Record $manifest.inputs.parent_fixed_mirror_stripe_run_manifest -BaseDirectory $continuationRoot -Label 'continuation Stripe authority'
  $currentContract=Get-Content -LiteralPath $ResolvedContractPath -Raw|ConvertFrom-Json -AsHashtable
  $frozenContract=Get-Content -LiteralPath $frozenContractPath -Raw|ConvertFrom-Json -AsHashtable
  $currentK=[double]$currentContract.nominal.target_drift_period_ratio
  $frozenK=[double]$frozenContract.nominal.target_drift_period_ratio
  $currentY=[double]$currentContract.accelerator.focus_y_anchor.project_y_mm
  $frozenY=[double]$frozenContract.accelerator.focus_y_anchor.project_y_mm
  if(-not[double]::IsFinite($currentK)-or-not[double]::IsFinite($frozenK)-or$currentK-ne$frozenK){
    throw 'Continuation target K differs from the current resolved contract.'
  }
  if(-not[double]::IsFinite($currentY)-or-not[double]::IsFinite($frozenY)-or$currentY-ne$frozenY){
    throw 'Continuation accelerator y anchor differs from the current resolved contract.'
  }
  $summaryRecords=@($manifest.outputs|Where-Object{[IO.Path]::GetFileName([string]$_.path)-eq'summary.json'})
  if($summaryRecords.Count-ne1){throw 'Continuation must bind exactly one summary.json output.'}
  $continuationSummaryPath=Resolve-RunRecordPath -Record $summaryRecords[0] -BaseDirectory $continuationRoot -Label 'continuation summary'
  $continuationSummary=Get-Content -LiteralPath $continuationSummaryPath -Raw|ConvertFrom-Json -AsHashtable
  $pairIdentity=$continuationSummary.inputs.accelerator_exit_source_receipt.pair_identity
  if($pairIdentity-isnot[Collections.IDictionary]-or
    [double]$pairIdentity.target_drift_period_ratio-ne$currentK-or
    [double]$pairIdentity.accelerator_y_anchor_mm-ne$currentY){
    throw 'Continuation lacks a matching pair-qualified accelerator-exit identity.'
  }
  $currentStripeManifest=Join-Path (Resolve-Path -LiteralPath $StripeRunDirectory).Path 'run_manifest.json'
  $currentStripe=Get-Content -LiteralPath $currentStripeManifest -Raw|ConvertFrom-Json -AsHashtable
  $frozenStripe=Get-Content -LiteralPath $frozenStripeManifestPath -Raw|ConvertFrom-Json -AsHashtable
  if($currentStripe.status-ne'success'-or$currentStripe.project-ne$project-or
    $currentStripe.mode-ne'dual_stripe_fixed_grid_native_downstream_seed'){
    throw 'Current Stripe authority is not a successful fixed-grid operating seed.'
  }
  if($frozenStripe.run_id-ne$currentStripe.run_id-or$frozenStripe.mode-ne$currentStripe.mode){
    throw 'Continuation Stripe authority differs from the current StripeRunPath.'
  }
  if([string]$continuationSummary.inputs.stripe_seed.source_stripe_run_id-ne[string]$currentStripe.run_id){
    throw 'Continuation summary Stripe authority differs from the current StripeRunPath.'
  }
  return [ordered]@{
    target_drift_period_ratio=$currentK;accelerator_y_anchor_mm=$currentY
    stripe_run_id=[string]$currentStripe.run_id;coverage_run_id=[string]$coverageManifest.run_id
  }
}

function Invoke-WorkpointControllerRequest {
  param([Parameter(Mandatory)][System.Collections.IDictionary]$Request,
    [Parameter(Mandatory)][string]$Python,[Parameter(Mandatory)][string]$RepoRoot)
  Push-Location -LiteralPath $RepoRoot
  try{
    $PSNativeCommandUseErrorActionPreference=$false
    $captured=@($Request|ConvertTo-Json -Depth 100 -Compress|& $Python -I -B -X utf8 -m msplatform.workflows.mr_design.workpoint_controller --controller-request - --output - 2>&1)
    $exitCode=$LASTEXITCODE
    $output=@($captured|Where-Object{$_-isnot[Management.Automation.ErrorRecord]})
    $stderr=@($captured|Where-Object{$_-is[Management.Automation.ErrorRecord]})
    if($exitCode-ne0){
      $stage='unspecified'
      if($Request.Contains('state')-and$Request.state-is[System.Collections.IDictionary]-and$Request.state.Contains('stage')){$stage=[string]$Request.state.stage}
      elseif($Request.Contains('phase')){$stage=[string]$Request.phase}
      $details=@{stdout=($output-join"`n");stderr=($stderr-join"`n")}
      foreach($stream in @('stdout','stderr')){
        if($details[$stream].Length-gt4096){$details[$stream]='[truncated tail] '+$details[$stream].Substring($details[$stream].Length-4096)}
      }
      throw "Controller decision failed: action=$($Request.action) stage=$stage exit_code=$exitCode; stdout=$($details.stdout); stderr=$($details.stderr)"
    }
    foreach($errorLine in $stderr){Write-Error -Message ([string]$errorLine) -ErrorAction Continue}
    return ($output-join"`n")|ConvertFrom-Json -AsHashtable -Depth 100
  }finally{Pop-Location}
}

function New-CenterTrialArguments {
  param([double[]]$Voltages,[Parameter(Mandatory)][string]$ChildRunId,[double[]]$PrismVoltages)
  if(([bool]$Voltages)-eq([bool]$PrismVoltages)){throw 'Supply full voltages or prism-only authority, exclusively.'}
  if($Voltages-and$Voltages.Count-ne4){throw 'Full centre-trial voltage vector must contain S1/S2/P1/P2.'}
  if($PrismVoltages-and$PrismVoltages.Count-ne2){throw 'Prism-only centre-trial voltage vector must contain P1/P2.'}
  $prisms=if($PrismVoltages){$PrismVoltages}else{@($Voltages[2],$Voltages[3])}
  $arguments = @{
    GeometryReviewRunPath=$GeometryReviewRunPath;MirrorRunPath=$MirrorRunPath
    StripeRunPath=$StripeRunPath
    Prism1VoltageV=$prisms[0];Prism2VoltageV=$prisms[1]
    TrajectoryStepScale=$TrajectoryStepScale;AcceleratorSourceYOffsetMm=$AcceleratorSourceYOffsetMm
    RunId=$ChildRunId;PythonExe=$python;RepoRoot=$repoRoot;CapacityWorkflowSession=$capacitySession
  }
  if($Voltages){$arguments.Stripe1VoltageV=$Voltages[0];$arguments.Stripe2VoltageV=$Voltages[1]}
  if(Get-Variable -Name contract -Scope Script -ErrorAction SilentlyContinue){$arguments.ContractPath=$script:contract}
  $arguments.AcceleratorComponentContractPath=$script:oaComponentContractFrozen
  $arguments.AcceleratorGeometryProfileId=$AcceleratorGeometryProfileId
  $arguments.AcceleratorProviderReceiptPath=$AcceleratorProviderReceiptPath
  $arguments.CompositionPlanPath=$CompositionPlanPath
  if($LocalScopePath){$arguments.LocalScopePath=$LocalScopePath}
  if($staticFieldMode){
    $arguments.BunchSourceReceiptPath=$CenterSourceReceiptPath
    $arguments.BunchParticleIdMin=1;$arguments.BunchParticleIdMax=1
  }else{
    $arguments.NativeCorridorBankRunPath=$NativeCorridorBankRunPath
    $arguments.NativeSystemRuntimeBundlePath=$NativeSystemRuntimeBundlePath
    $arguments.NativeCorridorRuntimeSession=$nativeRuntimeSession
    if(Get-Variable -Name resourceLease -Scope Script -ErrorAction SilentlyContinue){$arguments.InheritedHostResourceLease=$script:resourceLease}
  }
  if ($SimionExe) { $arguments.SimionExe = $SimionExe }
  if ($PulseAcceleratorUntilInitialExit) { $arguments.PulseAcceleratorUntilInitialExit = $true }
  if ($AcceleratorPulseSchedulePath) { $arguments.AcceleratorPulseSchedulePath = $AcceleratorPulseSchedulePath }
  if ($TrajectoryProfileId) { $arguments.TrajectoryProfileId = $TrajectoryProfileId }
  $variationVariable=Get-Variable -Name mirrorVoltageVariation -Scope Script -ErrorAction SilentlyContinue
  if ($null-ne$variationVariable-and$null-ne$variationVariable.Value) {
    $arguments.MirrorVoltageVariationPath = $variationVariable.Value
  }
  return $arguments
}

function Assert-ResponseFieldResumeDeclaration {
  param([string]$ParentRun,[string]$BindingPath,[Collections.IDictionary]$Declaration)
  $priorPath=Join-Path $ParentRun 'inputs/response_field_binding.json'
  if(Test-Path -LiteralPath $priorPath){
    if(-not$BindingPath){throw 'Static recovery must retain its explicitly declared response basis.'}
    $prior=Get-Content -LiteralPath $priorPath -Raw|ConvertFrom-Json -AsHashtable
    # Targets belong to the trial; every declared axis remains part of the basis.
    if($prior.schema_version-ne2-or$Declaration.schema_version-ne2){throw 'Static recovery response basis differs: use a new parent for the response format migration.'}
    $priorAxes=@($prior.voltage_responses.Keys|Sort-Object)
    $currentAxes=@($Declaration.voltage_responses.Keys|Sort-Object)
    if(($priorAxes-join',')-ne($currentAxes-join',')){throw 'Static recovery response basis differs.'}
    $priorRefs=@($prior.baseline_binding)+@($priorAxes|ForEach-Object{
      $spec=$prior.voltage_responses[$_];$spec.binding
      if($spec.Contains('baseline_binding')){$spec.baseline_binding}else{$prior.baseline_binding}
    })
    $currentRefs=@($Declaration.baseline_binding)+@($currentAxes|ForEach-Object{
      $spec=$Declaration.voltage_responses[$_];$spec.binding
      if($spec.Contains('baseline_binding')){$spec.baseline_binding}else{$Declaration.baseline_binding}
    })
    foreach($index in 0..($priorRefs.Count-1)){
      if([IO.Path]::GetFullPath([string]$priorRefs[$index])-ne[IO.Path]::GetFullPath([string]$currentRefs[$index])){throw 'Static recovery response basis differs.'}
    }
  }elseif($BindingPath){Write-Warning 'New parent explicitly enables exploratory response consumption; prior frozen run is unchanged.'}
}

function Invoke-CenterTrial {
  param([Parameter(Mandatory)][Collections.IDictionary]$Arguments,$StagedPending,$Bootstrap,[string]$BootstrapPath='')
  if($staticFieldMode){
    # Same source mesh and absolute mirror target throughout this P/S family.
    $request=$fieldProviderRequest|ConvertTo-Json -Depth 100|ConvertFrom-Json -AsHashtable
    if($request.role-eq'mrtof_native_static_field_provider_request'-and-not$staticBinding.Contains('consumer_view')){$request.numerical_contract_path=[string]$Arguments.ContractPath}
    $s1=if($Arguments.Contains('Stripe1VoltageV')){$Arguments.Stripe1VoltageV}else{$staticBinding.authority.analyzer_electrode_voltages_v[10]}
    $s2=if($Arguments.Contains('Stripe2VoltageV')){$Arguments.Stripe2VoltageV}else{$staticBinding.authority.analyzer_electrode_voltages_v[12]}
    $request.candidate_voltages_v=[ordered]@{s1=[double]$s1;s2=[double]$s2;p1=[double]$Arguments.Prism1VoltageV;p2=[double]$Arguments.Prism2VoltageV}
    if($Arguments.Contains('MirrorVoltageVariationPath')){
      $request.mirror_voltage_variation_path=[string]$Arguments.MirrorVoltageVariationPath
      $request.mirror_contract_path=[string]$Arguments.ContractPath
      if(-not$request.Contains('mirror_reference_trial_manifest')){throw 'Mirror field update requires its frozen reference trial manifest.'}
    }elseif($request.Contains('mirror_voltage_variation_path')){
      throw 'Provider mirror variation must also be consumed by the actual centre trial.'
    }
    # Reuse complete voltage/mirror derivation without preparing an unconsumed solve.
    # The explicit direct-field branch still uses the provider's full source checks.
    $authorityCode="import json,sys; from pathlib import Path; from msplatform.backends.comsol.static_field_binding import load_binding,native_numerics_match; from msplatform.backends.comsol.candidate_authority import derive_candidate_authority; r=json.loads(sys.argv[1]); s=load_binding(Path(r['source_binding_path']),_allow_responses=False); a,_=derive_candidate_authority(r,s['authority']); profiles=[json.loads(Path(p).read_text(encoding='utf-8-sig'))['simion']['numerical_profiles']['native_static_field'] for p in (r['numerical_contract_path'],sys.argv[2])] if s.get('consumer_view') else []; [p.pop('consumer_view',None) for p in profiles]; assert not profiles or profiles[0]==profiles[1], 'provider storage and trajectory field numerics differ'; print(json.dumps(a==s['authority'] and (r['role']!='mrtof_native_static_field_provider_request' or native_numerics_match(s,r['numerical_contract_path']))))"
    $sameSourceField=& {
      $resolved=((& $python -I -B -c $authorityCode ($request|ConvertTo-Json -Depth 100 -Compress) ([string]$Arguments.ContractPath))-join"`n")
      if($LASTEXITCODE-ne0){throw 'Candidate field authority preflight failed.'}
      $reuse=$resolved|ConvertFrom-Json
      if($reuse-isnot[bool]){throw 'Candidate field authority preflight did not return a boolean.'}
      return $reuse
    }
    $Arguments.Stripe1VoltageV=[double]$s1;$Arguments.Stripe2VoltageV=[double]$s2
    $retainedBinding=$null
    if($null-ne$StagedPending-and$StagedPending.Contains('provider_reference')-and
       $request.role-eq'mrtof_native_static_field_provider_request'){
      # A provider may finish before the trial's source preflight fails. Reuse
      # that sealed field, not a failed flight, under the new child identity.
      $retainedCode=@'
import hashlib,json,sys
from pathlib import Path
from msplatform.backends.comsol.static_field_binding import load_binding,native_numerics_match,native_response_operator,_record
from msplatform.backends.comsol.candidate_authority import derive_candidate_authority
from msplatform.execution.retention import verify_record
r,ref=json.loads(sys.argv[1]),json.loads(sys.argv[2])
m=Path(ref['provider_manifest']); old_request=Path(ref['request_path'])
assert ref['operation'] in ('compose','refine') and m.parent.name==ref['child_run_id']+'-field', 'Retained provider ownership differs'
if ref['operation']=='refine':
    assert not any(k in r for k in ('response_basis_paths','response_axis','te1_reference_path','consumer_view_source_path','reuse_source_levels')), 'Retained direct request contains response/reuse/view instructions'
    cfg=m.with_name('run_config.json')
    assert json.loads(cfg.read_text(encoding='utf-8-sig'))['parameters']['operation']=='refine', 'Retained direct provider operation differs'
old_trial=m.parent.parent/ref['child_run_id']/'run_manifest.json'
if old_trial.exists():
    old=json.loads(old_trial.read_text(encoding='utf-8-sig'))
    assert sys.argv[3]=='prepared' and old.get('run_id')==ref['child_run_id'] and old.get('status') in ('failed','interrupted'), 'Retained provider already has a successful or incompatible trial result'
assert hashlib.sha256(m.read_bytes()).hexdigest()==ref['provider_manifest_sha256'] and hashlib.sha256(old_request.read_bytes()).hexdigest()==ref['request_sha256'], 'Retained provider reference changed'
d=json.loads(m.read_text(encoding='utf-8-sig')); assert d['status']=='success' and d['mode']=='native_static_field_provider' and d['run_id']==ref['child_run_id']+'-field', 'Retained provider is not successful'
if ref['operation']=='refine':
    assert hashlib.sha256(cfg.read_bytes()).hexdigest()==d['run_config']['sha256'].lower(), 'Retained direct provider configuration changed'
assert d['inputs']['request']['sha256'].lower()==ref['request_sha256'], 'Retained provider request differs'
summary=m.with_name('summary.json'); verify_record('retained_provider_summary',_record(m,summary),base_dir=m.parent)
p=Path(json.loads(summary.read_text(encoding='utf-8-sig'))['field_binding']); verify_record('retained_provider_binding',_record(m,p),base_dir=m.parent)
b=load_binding(p,_allow_responses=False); s=load_binding(Path(r['source_binding_path']),_allow_responses=False); a,_=derive_candidate_authority(r,s['authority'])
assert b['authority']==a and native_numerics_match(b,r['numerical_contract_path']) and native_response_operator(b,a)==native_response_operator(s,a), 'Retained provider target or operator differs'
print(json.dumps(str(p)))
'@
      $retainedBinding=& {
        $consumer='legacy'
        $value=((& $python -I -B -c $retainedCode ($request|ConvertTo-Json -Depth 100 -Compress) ($StagedPending.provider_reference|ConvertTo-Json -Depth 100 -Compress) $consumer)-join"`n")
        if($LASTEXITCODE-ne0){throw 'Retained pending provider validation failed.'}
        return ($value|ConvertFrom-Json)
      }
    }
    if($retainedBinding){
      $Arguments.FieldBindingPath=[string]$retainedBinding
      $renewal=Update-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $capacitySession -ProtectedPaths @((Split-Path -Parent $StagedPending.provider_reference.provider_manifest))
      $script:capacitySession=$renewal.session
      $Arguments.CapacityWorkflowSession=$script:capacitySession
    }elseif($sameSourceField){
      # All other voltages/geometry remain the validated binding authority.
      $Arguments.FieldBindingPath=[string]$fieldProviderRequest.source_binding_path
    }else{
    $providerId=[string]$Arguments.RunId+'-field'
    $request.run_id=$providerId
    $requestPath=Join-Path $package.input_dir ($providerId+'_request.json')
    Write-RunJson -Path $requestPath -Depth 100 -Value $request
    $completedBinding=$null
    if($CompletedFieldProviderManifest){
      $completed=& {
        $resolved=((& $python -I -B -m msplatform.backends.comsol.corridor_field `
          --resolve-completed-request $requestPath --completed-provider-manifest $CompletedFieldProviderManifest)-join"`n")
        if($LASTEXITCODE-ne0){throw 'Completed field provider validation failed.'}
        return ($resolved|ConvertFrom-Json)
      }
      $completedBinding=$completed.binding
    }
    if($completedBinding){
      $providerRun=Split-Path -Parent $CompletedFieldProviderManifest
      $Arguments.FieldBindingPath=[string]$completedBinding
    }elseif($ResponseFieldBindingPath){
      # No field materialization: coefficients are derived by the existing binding
      # compiler.  This remains exploratory until direct/combined flight comparison.
      $descriptor=$responseDeclaration|ConvertTo-Json -Depth 100|ConvertFrom-Json -AsHashtable
      $descriptor.target_ps_voltages_v=@{s1=[double]$s1;s2=[double]$s2;p1=[double]$Arguments.Prism1VoltageV;p2=[double]$Arguments.Prism2VoltageV}
      $bindingPath=Join-Path $package.input_dir ($providerId+'_response_binding.json')
      Write-RunJson -Path $bindingPath -Depth 100 -Value $descriptor
      $resolved=& {
        $output=((& $python -I -B -m msplatform.backends.comsol.static_field_binding --binding $bindingPath)-join"`n")
        if($LASTEXITCODE-ne0){throw 'Candidate response field binding is invalid.'}
        return ($output|ConvertFrom-Json -AsHashtable)
      }
      $checkCode="import json,sys; from pathlib import Path; from msplatform.backends.comsol.static_field_binding import load_binding,validate_response_candidate; validate_response_candidate(load_binding(Path(sys.argv[2])),json.loads(sys.argv[1]))"
      & {
        & $python -I -B -c $checkCode ($request|ConvertTo-Json -Depth 100 -Compress) $bindingPath
        if($LASTEXITCODE-ne0){throw 'Declared response basis cannot supply this candidate; use an explicit direct-field configuration.'}
      }
      $Arguments.FieldBindingPath=$bindingPath
      $providerRun=$null
      Write-Host ('MRTOF_FIELD_REPRESENTATION=exploratory_affine_ps_responses G='+$resolved.response_weight_l1_norm)
    }else{
      $providerRun=Join-Path $artifactRoot "runs/$providerId"
      if($request.role-eq'mrtof_native_static_field_provider_request'){
        & $fieldProviderRunner -RequestPath $requestPath -RunDirectory $providerRun -Approved -PythonExe $python -HostContextJson ($hostContext|ConvertTo-Json -Compress) | Out-Host
      }else{
        & $fieldProviderRunner -RequestPath $requestPath -RunDirectory $providerRun -Approved -WorkspaceRoot $workspaceRoot -ArtifactRoot $artifactWorkspaceRoot -PythonExe $python | Out-Host
      }
    }
    if($providerRun){
      $renewal=Update-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $capacitySession -ProtectedPaths @($providerRun)
      $script:capacitySession=$renewal.session
    }
    $Arguments.CapacityWorkflowSession=$script:capacitySession
    }
  }
  & $trialRunner @Arguments
}

function Find-ContinuationTransportSeed {
  param([Parameter(Mandatory)]$ContinuationSeed,[Parameter(Mandatory)]$Profile)
  $candidates=@(Invoke-WorkpointControllerRequest -Python $python -RepoRoot $repoRoot -Request @{
    action='continuation_transport_candidates';seed=$ContinuationSeed;profile=$Profile
  })
  $attempts=@()
  for($index=0;$index-lt$candidates.Count;$index++){
    $prisms=$candidates[$index]
    $childRunId=if($index-eq0){$RunId+'-baseline'}else{$RunId+('-transport-seed-{0:D2}'-f$index)}
    $arguments=New-CenterTrialArguments -PrismVoltages $prisms -ChildRunId $childRunId
    if($index-eq0-and$RetainBaselineGuiWorkbench){$arguments.RetainGuiWorkbench=$true}
    Invoke-CenterTrial -Arguments $arguments | Out-Host
    $manifest=Join-Path $trialArtifactRoot "runs\$childRunId\run_manifest.json"
    $materialization=Get-ManifestOutputPath -ManifestPath $manifest -FileName 'two_prism_trial_materialization.json'
    $receipt=Get-Content -LiteralPath $materialization -Raw|ConvertFrom-Json
    $voltages=@(@($receipt.stripe_biases_v)+@($receipt.prism_voltages_v)|ForEach-Object{[double]$_})
    if($voltages.Count-ne4-or$voltages[2]-ne$prisms[0]-or$voltages[3]-ne$prisms[1]){
      throw 'Continuation transport-seed trial materialized different prism voltages.'
    }
    $evidence=Get-WorkpointBootstrapEvidence -Manifest $manifest -Voltages $voltages
    $attempts+=,[ordered]@{prism_voltages_v=@($prisms);child_manifest=$manifest;passed=[bool]$evidence.passed;reasons=@($evidence.reasons)}
    if($evidence.passed-or$stagedBootstrap){return [pscustomobject]@{manifest=$manifest;materialization=$materialization;voltages_v=$voltages;attempts=$attempts}}
  }
  throw 'No physical transport seed was found within the contract relative tiers and continuation voltage bounds.'
}

function Get-WorkpointBootstrapEvidence {
  param([string]$Manifest,[double[]]$Voltages)
  & $python -I -B -c 'from msplatform.execution.manifest_verification import main; from msplatform.backends.simion.native_completion import retention_api; main(retention_api=retention_api)' $Manifest --require-status success `
    --require-project instrument_assembly --require-mode oa_mr | Out-Host
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
  # Preserve the existing JSON-to-double conversion before the pure classifier.
  $residuals=$observation['residuals']
  $target='Stripe_target_phase_y_minus_origin_mm'
  if($residuals-is[Collections.IDictionary]-and$residuals.Contains($target)-and$null-ne$residuals[$target]){
    $residuals[$target]=[double]$residuals[$target]
  }
  $physical=Invoke-WorkpointControllerRequest -Python $python -RepoRoot $repoRoot -Request @{
    action='center_trial_physical_gate';observation=$observation
  }
  return [ordered]@{
    passed=$physical.passed;reasons=@($physical.reasons);actual_voltages_v=$actual
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
  if($staticFieldMode-or((Get-Variable nativeRuntimeSession -ErrorAction SilentlyContinue)-and$null-ne$nativeRuntimeSession-and
     (Test-Path -LiteralPath $nativeRuntimeSession.checkpoint_path))){
    Save-NativeWorkflowCheckpoint -Reason 'Bootstrap physical attempt recorded.' -WorkflowOutcome bootstrap_in_progress
  }
}
function Invoke-WorkpointStencil {
  param([Parameter(Mandatory)]$Bootstrap,[Parameter(Mandatory)][string]$BootstrapPath,[switch]$RetainBaselineGuiWorkbench)
  $seedVoltages=[double[]]$Bootstrap.seed_voltages_v
  $steps=[double[]]$Bootstrap.forward_steps_v
  [double[]]$stepScales=if($Bootstrap.Contains('stencil_step_scales')){@($Bootstrap.stencil_step_scales|ForEach-Object{[double]$_})}else{@(1.0)}
  $stencilPlan=Invoke-WorkpointControllerRequest -Python $python -RepoRoot $repoRoot -Request @{
    action='plan_bootstrap_stencil';voltages_v=@($seedVoltages);forward_steps_v=@($steps);step_scales=@($stepScales)
  }
  if(-not$Bootstrap.Contains('attempts')){$Bootstrap['attempts']=@()}
  foreach($attempt in $Bootstrap.attempts){
    if(-not($attempt-is[Collections.IDictionary])-or
      @('axis','direction','signed_step_v','child_manifest','child_manifest_sha256','observation_sha256','materialization_sha256','passed'|Where-Object{-not$attempt.Contains($_)}).Count){throw 'Bootstrap attempt schema is incomplete.'}
    $attemptScale=if($attempt.Contains('step_scale')){[double]$attempt.step_scale}else{1.0}
    if($attemptScale-notin$stepScales){throw 'Bootstrap attempt step scale is invalid.'}
    if([int]$attempt.axis-lt-1-or[int]$attempt.axis-gt3-or$attempt.passed-isnot[bool]-or
      ([int]$attempt.axis-eq-1-and[int]$attempt.direction-ne0)-or
      ([int]$attempt.axis-ge0-and[int]$attempt.direction-notin@(1,-1))){throw 'Bootstrap attempt axis or direction is invalid.'}
    if([int]$attempt.direction-eq-1){
      $forward=@($Bootstrap.attempts|Where-Object{[int]$_.axis-eq[int]$attempt.axis-and[int]$_.direction-eq1-and$(if($_.Contains('step_scale')){[double]$_.step_scale}else{1.0})-eq$attemptScale})
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
  foreach($group in $stencilPlan.groups){
    $axis=[int]$group.axis
    $script:failureStage='bootstrap_center_'+($axis+1)
    $accepted=$false
    foreach($trial in $group.trials){
      $stepScale=[double]$trial.step_scale;$direction=[int]$trial.direction
      $signedStep=[double]$trial.signed_step_v;$voltages=[double[]]$trial.voltages_v
      $recorded=@($Bootstrap.attempts|Where-Object{[int]$_.axis-eq$axis-and[int]$_.direction-eq$direction-and$(if($_.Contains('step_scale')){[double]$_.step_scale}else{1.0})-eq$stepScale})
      if($recorded.Count-gt1){throw 'Bootstrap has duplicate physical attempt identities.'}
      if($recorded.Count){
        if([double]$recorded[0].signed_step_v-ne$signedStep){throw 'Bootstrap recorded signed step differs.'}
        $manifest=[string]$recorded[0].child_manifest
      }elseif($direction-ne-1-and$priorChildren.Count-gt($axis+1)){
        $manifest=[string]$priorChildren[$axis+1]
      }else{
        $tierSuffix=if($trial.tier_index-eq0){''}else{'-tier-'+$trial.tier_index}
        $bootstrapId=$RunId+$(if($axis-lt0){'-baseline'}else{'-stencil-'+($axis+1)})+$tierSuffix+$(if($direction-eq-1){'-reverse'}else{''})
        $arguments=New-CenterTrialArguments -Voltages $voltages -ChildRunId $bootstrapId
        if($axis-lt0-and$RetainBaselineGuiWorkbench){$arguments.RetainGuiWorkbench=$true}
        Invoke-CenterTrial -Arguments $arguments | Out-Host
        $manifest=Join-Path $trialArtifactRoot "runs\$bootstrapId\run_manifest.json"
      }
      $evidence=Get-WorkpointBootstrapEvidence -Manifest $manifest -Voltages $voltages
      if($recorded.Count){
        foreach($field in @('observation_sha256','materialization_sha256','child_manifest_sha256','passed')){
          if($recorded[0][$field]-ne$evidence[$field]){throw "Bootstrap attempt evidence changed: $field"}
        }
      }else{
        $attempt=[ordered]@{axis=$axis;direction=$direction;step_scale=$stepScale;signed_step_v=$signedStep}
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
    -ContractPath $frozenContract -RunId $auditId -WorkspaceRoot $workspaceRoot -ArtifactRoot $artifactWorkspaceRoot -PythonExe $python -CapacityWorkflowSession $capacitySession | Out-Host
  return Join-Path $artifactRoot "runs\$auditId\run_manifest.json"
}

function Invoke-PreclosureDecision {
  param([string]$Stage,[string]$Anchor,[Collections.IDictionary]$Columns,[string]$OutputPath,[string]$PriorPrismDecisionManifest='',[string]$ControllerPolicyPath='',
    [Parameter(Mandatory)][System.Collections.IDictionary]$Context)
  $repoRoot=[string]$Context.repo_root;$python=[string]$Context.python;$frozenContract=[string]$Context.contract_path
  $arguments=@('--control-stage',$Stage,'--child-manifest',$Anchor,'--contract',$frozenContract,'--output',$OutputPath)
  if($Context.prism_handoff_replay_manifest){$arguments+=@('--prism-handoff-replay-manifest',$Context.prism_handoff_replay_manifest)}
  if($PriorPrismDecisionManifest){$arguments+=@('--prior-prism-decision-manifest',$PriorPrismDecisionManifest)}
  if($Stage-eq'prism_preclosure'-and$ControllerPolicyPath){$arguments+=@('--prism-controller-policy',$ControllerPolicyPath)}
  foreach($entry in @(@(0,'--s1-child-manifest'),@(1,'--s2-child-manifest'),@(2,'--p1-child-manifest'),@(3,'--p2-child-manifest'))){
    if($Columns.Contains([string]$entry[0])){$arguments+=@($entry[1],[string]$Columns[[string]$entry[0]])}
  }
  & {
    & $python -I -B -m msplatform.workflows.mr_design.downstream_workpoint @arguments | Out-Host
    if($LASTEXITCODE-ne0){throw 'Stage preclosure decision failed.'}
  }
  return Get-Content -LiteralPath $OutputPath -Raw|ConvertFrom-Json -AsHashtable
}

function Publish-StagedPrismModel {
  param($State,$Decision)
  # Seal the original measured model once.  The existing Python consumer needs
  # successful evidence, not a mutable parent checkpoint or a transported fit.
  # This light child uses the parent's capacity reservation; no field payloads.
  $modelId=('{0}__analysis__python__mrtof-prism-model-{1:D3}'-f (Get-Date -Format 'yyyyMMdd_HHmmss'),$State.flight_count)
  $modelPackage=New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot `
    -RunId $modelId -Project $project -Mode prism_preclosure_analysis -Software @('Python 3.11','NumPy') `
    -RetentionContractEnabled -CapacityLedgerLifecycleEnabled -CapacityLedgerArtifactRoot $artifactWorkspaceRoot
  $modelPath=Join-Path $modelPackage.result_dir 'prism_preclosure_decision.json'
  try{
    $configuration=Get-Content -LiteralPath $modelPackage.run_config -Raw|ConvertFrom-Json -AsHashtable
    $configuration.inputs=[ordered]@{baseline_manifest=$State.anchor_manifest;workpoint_contract=$frozenContract;controller_source=$controllerSource;controller_state_source=$controllerStateSource}
    if($Decision.Contains('prism_controller_policy')){$configuration.inputs.prism_controller_policy=$Decision.prism_controller_policy.path}
    foreach($axis in 2,3){$configuration.inputs[('p{0}_child_manifest'-f($axis-1))]=[string]$State.columns[[string]$axis]}
    $configuration.parameters=[ordered]@{control_stage='prism_preclosure';measured_model_only=$true;full_workpoint_qualified=$false}
    Write-RunJson -Path $modelPackage.run_config -Depth 100 -Value $configuration
    Write-RunJson -Path $modelPath -Depth 100 -Value $Decision
    Write-RunJson -Path $modelPackage.summary -Value ([ordered]@{schema_version=1;role='mrtof_prism_model_summary';status='success';full_workpoint_qualified=$false})
    $retention=Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $modelPackage.run_config
    Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $modelPackage.run_config `
      -Status success -Software @('Python 3.11','NumPy') -Outputs @($modelPackage.summary,$modelPath,$retention) | Out-Host
  }catch{
    Write-RunJson -Path $modelPackage.summary -Value ([ordered]@{schema_version=1;role='mrtof_prism_model_summary';status='failed';reason=$_.Exception.Message})
    $retention=Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $modelPackage.run_config
    $outputs=@($modelPackage.summary,$retention)
    if(Test-Path -LiteralPath $modelPath){$outputs+=$modelPath}
    Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $modelPackage.run_config `
      -Status failed -Software @('Python 3.11','NumPy') -Outputs $outputs | Out-Host
    throw
  }
  return Join-Path $modelPackage.artifact_run_dir 'run_manifest.json'
}

function Invoke-StagedPreclosureDecision {
  param($State,[string]$OutputPath,[string]$ControllerPolicyPath='')
  $prior=if($State.stage-eq'prism_preclosure'-and$State.columns.Count-eq0-and$State.Contains('prism_model_manifest')){[string]$State.prism_model_manifest}else{''}
  $decision=Invoke-PreclosureDecision -Context $controllerContext -Stage $State.stage -Anchor $State.anchor_manifest -Columns $State.columns -OutputPath $OutputPath -PriorPrismDecisionManifest $prior -ControllerPolicyPath $ControllerPolicyPath
  if($prior-and$decision.status-eq'needs_stencil'){$State.Remove('prism_model_manifest')|Out-Null}
  if($State.stage-eq'prism_preclosure'-and$decision.status-eq'proposed'-and$decision.Contains('physical_jacobian_rows')-and
     (-not$decision.Contains('model_representation')-or$decision.model_representation-ne'transported_local_approximation')-and
     -not$State.Contains('prism_model_manifest')){
    $State['prism_model_manifest']=Publish-StagedPrismModel -State $State -Decision $decision
  }
  return $decision
}

function New-StagedComposeProviderReference {
  param([string]$ChildRunId,[string]$ProviderRun,[string]$RequestPath,[string]$ParentRunId=$RunId)
  # The sealed provider remains authoritative; this reference is transported
  # only by the existing pending/lineage checkpoint, not a second owner.
  $cfg=Get-Content -LiteralPath (Join-Path $ProviderRun 'run_config.json') -Raw|ConvertFrom-Json -AsHashtable
  $operation=[string]$cfg.parameters.operation
  if($operation-ne'compose'){return}
  if(-not$ChildRunId.StartsWith($ParentRunId+'-stage-',[StringComparison]::Ordinal)){return}
  $expected=Join-Path $artifactRoot ('runs/'+$ChildRunId+'-field')
  $parentInputs=if($ParentRunId-eq$RunId){$package.input_dir}else{Join-Path $artifactRoot ('runs/'+$ParentRunId+'/inputs')}
  $expectedRequest=Join-Path $parentInputs ($ChildRunId+'-field_request.json')
  if([IO.Path]::GetFullPath($ProviderRun)-ne[IO.Path]::GetFullPath($expected)-or
     [IO.Path]::GetFullPath($RequestPath)-ne[IO.Path]::GetFullPath($expectedRequest)){throw 'Staged compose ownership paths differ.'}
  $manifest=Join-Path $ProviderRun 'run_manifest.json'
  $doc=Get-Content -LiteralPath $manifest -Raw|ConvertFrom-Json -AsHashtable
  $requestSha=(Get-FileHash -LiteralPath $RequestPath -Algorithm SHA256).Hash.ToLowerInvariant()
  if($doc.status-ne'success'-or$doc.project-ne$project-or$doc.mode-ne'native_static_field_provider'-or
     $doc.run_id-ne($ChildRunId+'-field')-or
     ([string]$doc.inputs.request.sha256).ToLowerInvariant()-ne$requestSha-or
     (Get-FileHash -LiteralPath $doc.inputs.request.path -Algorithm SHA256).Hash.ToLowerInvariant()-ne$requestSha-or
     (Get-FileHash -LiteralPath (Join-Path $ProviderRun 'run_config.json') -Algorithm SHA256).Hash.ToLowerInvariant()-ne([string]$doc.run_config.sha256).ToLowerInvariant()){
    throw 'Staged compose provider source/terminal identity differs.'
  }
  return [ordered]@{
    parent_run_id=$ParentRunId;child_run_id=$ChildRunId;provider_run=$ProviderRun;provider_manifest=$manifest
    provider_manifest_sha256=(Get-FileHash -LiteralPath $manifest -Algorithm SHA256).Hash.ToLowerInvariant()
    request_path=$RequestPath;request_sha256=$requestSha;operation=$operation
  }
}

function Assert-StagedComposeProviderReference {
  param($Reference,[string]$ChildRunId,[Parameter(Mandatory)][System.Collections.IDictionary]$Context)
  $RunId=[string]$Context.run_id;$artifactRoot=[string]$Context.artifact_root
  if($null-eq$Reference-or$Reference.parent_run_id-ne$RunId){return $null}
  $owner=$Reference
  $allowed=$owner.operation-eq'compose'
  if($owner.child_run_id-ne$ChildRunId-or-not$allowed-or
     -not$ChildRunId.StartsWith($RunId+'-stage-',[StringComparison]::Ordinal)-or
     [IO.Path]::GetFullPath($owner.provider_run)-ne[IO.Path]::GetFullPath((Join-Path $artifactRoot ('runs/'+$ChildRunId+'-field')))-or
     (Get-FileHash -LiteralPath $owner.provider_manifest -Algorithm SHA256).Hash.ToLowerInvariant()-ne$owner.provider_manifest_sha256-or
     (Get-FileHash -LiteralPath $owner.request_path -Algorithm SHA256).Hash.ToLowerInvariant()-ne$owner.request_sha256){throw 'Staged compose provider reference differs.'}
  return $owner
}

function Resolve-StagedComposeRetirementOwner {
  param($Reference,[string]$ChildRunId)
  $current=Assert-StagedComposeProviderReference -Context $controllerContext -Reference $Reference -ChildRunId $ChildRunId
  if($null-ne$current-or$null-eq$Reference){return $current}
  # A restored lineage retains the original sealed owner, not ownership of the
  # new parent. Reconstruct its small reference under that parent's authority.
  $parent=[string]$Reference.parent_run_id
  if(-not$ChildRunId.StartsWith($parent+'-stage-',[StringComparison]::Ordinal)){return $null}
  if([IO.Path]::GetFileName($parent)-ne$parent){throw 'Restored compose parent identity differs.'}
  $parentRun=Join-Path $artifactRoot ('runs/'+$parent)
  $doc=Get-Content -LiteralPath (Join-Path $parentRun 'run_manifest.json') -Raw|ConvertFrom-Json -AsHashtable
  if($doc.run_id-ne$parent-or$doc.project-ne$project-or$doc.mode-ne'downstream_fixed_grid_workpoint_iteration'-or
     (Get-FileHash -LiteralPath (Join-Path $parentRun 'run_config.json') -Algorithm SHA256).Hash.ToLowerInvariant()-ne([string]$doc.run_config.sha256).ToLowerInvariant()){
    throw 'Restored compose parent authority differs.'
  }
  $owner=New-StagedComposeProviderReference -ChildRunId $ChildRunId -ProviderRun $Reference.provider_run -RequestPath $Reference.request_path -ParentRunId $parent
  if($null-eq$owner-or@($owner.Keys|Where-Object{[string]$owner[$_]-cne[string]$Reference[$_]}).Count){throw 'Restored compose provider reference differs.'}
  return $owner
}

function Invoke-StagedComposeRetirement {
  param($Owner,[string]$Disposition)
  $reason="Staged $($Owner.operation) $Disposition consumed by $RunId/$($Owner.child_run_id); sealed trial, controller checkpoint and rebuild inputs retained; no future field/GUI use."
  $receipt=Join-Path $Owner.provider_run 'solver_review_retirement_receipt.json'
  $complete=(Test-Path -LiteralPath $receipt)-and
    (Get-Content -LiteralPath $receipt -Raw|ConvertFrom-Json).lifecycle_status-eq'completed_experiment_payload_retired'
  if(-not$complete){
    $arguments=@{ArtifactRoot=$artifactWorkspaceRoot;RepositoryRoot=$repoRoot;TargetRun=$Owner.provider_run;Owner=$project;OwnerAbandonmentReason=$reason}
    & {
      & (Join-Path $executionResources 'invoke_solver_review_retirement.ps1') @arguments -Apply -Confirm:$false | Out-Host
      if($LASTEXITCODE-ne0){throw 'Staged compose public retirement apply failed.'}
    }
  }
  $finalized=& {
    & $python -I -B -m msplatform.execution.solver_review_retirement --verify $Owner.provider_run | Out-Host
    if($LASTEXITCODE-ne0){throw 'Staged compose public retirement verification failed.'}
    $result=@(& $python -I -B -m msplatform.execution.run_capacity_lifecycle --action finalize-ready --artifact-root $artifactWorkspaceRoot --run-config (Join-Path $Owner.provider_run 'run_config.json'))
    if($LASTEXITCODE-ne0){throw 'Staged compose public retirement finalize failed.'}
    return (($result-join"`n")|ConvertFrom-Json -AsHashtable)
  }
  return @{retirement_receipt=@{path=$receipt;bytes=(Get-Item -LiteralPath $receipt).Length;sha256=(Get-FileHash -LiteralPath $receipt -Algorithm SHA256).Hash.ToLowerInvariant()};capacity_finalization=$finalized}
}

function Reclaim-StagedComposeProviders {
  param($State,$Lineage)
  if(-not$staticFieldMode-or$staticBindingMode-ne'native_static_pa'){return}
  $targets=@()
  foreach($entry in $Lineage.children){
    if(-not$entry.Contains('compose_payload_use')-or$entry.compose_payload_use-notin@('stencil','rejected_candidate','keep')){continue}
    if(-not$entry.Contains('provider_reference')){continue}
    $owner=Resolve-StagedComposeRetirementOwner -Reference $entry.provider_reference -ChildRunId ([string]$entry.run_id)
    if($null-eq$owner){continue}
    if($entry.Contains('compose_payload_retirement')){
      $record=$entry.compose_payload_retirement.retirement_receipt
      if([IO.Path]::GetFullPath($record.path)-ne[IO.Path]::GetFullPath((Join-Path $owner.provider_run 'solver_review_retirement_receipt.json'))-or
         (Get-Item -LiteralPath $record.path).Length-ne$record.bytes-or
         (Get-FileHash -LiteralPath $record.path -Algorithm SHA256).Hash.ToLowerInvariant()-ne$record.sha256){throw 'Persisted public compose retirement receipt differs.'}
      continue
    }
    # Historical parent links consume sealed trial metadata, not the old PA.
    # Current rollback and pending anchors still require their live fields.
    $anchorUse=$State.anchor_manifest-eq$entry.child_manifest
    $pendingUse=$State.Contains('pending_trial')-and(
      $State.pending_trial.child_manifest-eq$entry.child_manifest-or
      ($State.pending_trial.Contains('anchor_manifest')-and$State.pending_trial.anchor_manifest-eq$entry.child_manifest))
    if($anchorUse-or$pendingUse){continue}
    $childCfgPath=Join-Path (Split-Path $entry.child_manifest) 'run_config.json'
    $childDocument=Get-Content -LiteralPath $entry.child_manifest -Raw|ConvertFrom-Json -AsHashtable
    if((Get-FileHash -LiteralPath $entry.child_manifest -Algorithm SHA256).Hash.ToLowerInvariant()-ne$entry.child_manifest_sha256-or
       (Get-FileHash -LiteralPath $childCfgPath -Algorithm SHA256).Hash.ToLowerInvariant()-ne([string]$childDocument.run_config.sha256).ToLowerInvariant()){throw 'Staged compose child GUI identity differs.'}
    $childCfg=Get-Content -LiteralPath $childCfgPath -Raw|ConvertFrom-Json -AsHashtable
    if($childCfg.parameters-isnot[Collections.IDictionary]){continue}
    if($childCfg.parameters.Contains('gui_workbench_retained')-and$childCfg.parameters.gui_workbench_retained-is[bool]-and$childCfg.parameters.gui_workbench_retained){continue}
    $declaredPrivate=$childCfg.parameters.Contains('gui_workbench_retained')-and$childCfg.parameters.gui_workbench_retained-is[bool]-and-not$childCfg.parameters.gui_workbench_retained
    if(-not$declaredPrivate){continue}
    $disposition=$entry.compose_payload_use
    if($disposition-eq'keep'){
      # Preserve every physically qualified point eligible for the existing best
      # handoff selector. Only an explicitly unqualified superseded point retires.
      $full=Invoke-PreclosureDecision -Context $controllerContext -Stage stripe_preclosure -Anchor $entry.child_manifest -Columns ([ordered]@{}) -OutputPath (Join-Path $package.result_dir ('iteration_staged_payload_{0:D3}_decision.json'-f$entry.iteration))
      if($full-isnot[Collections.IDictionary]-or-not$full.Contains('full_workpoint_qualified')-or
         $full.full_workpoint_qualified-isnot[bool]-or$full.full_workpoint_qualified){continue}
      $disposition='superseded_anchor'
    }
    $targets+=,@{owner=$owner;disposition=$disposition;entry=$entry}
  }
  $releasePaths=@();$releaseGroups=@()
  if($script:restoredAnchorFieldProtection){
    $retiringChildren=@($targets|ForEach-Object{$_.entry.child_manifest})
    $consumers=@($State.anchor_manifest)+@($State.columns.Values|Where-Object{$_-notin$retiringChildren})
    if($State.Contains('pending_trial')){$consumers+=@($State.pending_trial.child_manifest,$State.pending_trial.anchor_manifest)}
    foreach($restored in $script:restoredAnchorFieldProtection.groups){
    if($restored.anchor_manifest-notin$consumers){
      $childDocument=Get-Content -LiteralPath $restored.anchor_manifest -Raw|ConvertFrom-Json -AsHashtable
      $childCfgPath=Join-Path (Split-Path $restored.anchor_manifest) 'run_config.json'
      if((Get-FileHash $restored.anchor_manifest -Algorithm SHA256).Hash.ToLowerInvariant()-ne$restored.manifest_sha256-or
         (Get-FileHash $childCfgPath -Algorithm SHA256).Hash.ToLowerInvariant()-ne([string]$childDocument.run_config.sha256).ToLowerInvariant()){throw 'Restored anchor GUI identity differs.'}
      $cfg=Get-Content -LiteralPath $childCfgPath -Raw|ConvertFrom-Json -AsHashtable
      if($cfg.parameters-is[Collections.IDictionary]-and$cfg.parameters.Contains('gui_workbench_retained')-and$cfg.parameters.gui_workbench_retained-is[bool]-and-not$cfg.parameters.gui_workbench_retained){
        $full=Invoke-PreclosureDecision -Context $controllerContext -Stage stripe_preclosure -Anchor $restored.anchor_manifest -Columns ([ordered]@{}) -OutputPath (Join-Path $package.result_dir 'iteration_restored_anchor_payload_decision.json')
        if($full-is[Collections.IDictionary]-and$full.Contains('full_workpoint_qualified')-and$full.full_workpoint_qualified-is[bool]-and-not$full.full_workpoint_qualified){$releaseGroups+=,$restored}
      }
    }
    }
    $releaseIds=@($releaseGroups|ForEach-Object{$_.anchor_manifest})
    $livePaths=@($script:restoredAnchorFieldProtection.groups|Where-Object{$_.anchor_manifest-notin$releaseIds}|ForEach-Object{$_.all_paths})
    $releasePaths=@($releaseGroups|ForEach-Object{$_.paths}|Where-Object{$_-notin$livePaths}|Select-Object -Unique)
  }
  if(-not$targets.Count-and-not$releaseGroups.Count){return}
  # Callers have already published the ordinary checkpoint. Never edit the
  # union-only public Update API or withdraw protection before new admission.
  $keep=@($capacitySession.protected_paths|Where-Object{
    $candidate=[IO.Path]::GetFullPath($_)
    $candidate-notin$releasePaths-and-not@($targets|Where-Object{
      $target=[IO.Path]::GetFullPath($_.owner.provider_run).TrimEnd('\','/')
      $candidate-eq$target-or$candidate.StartsWith($target+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)
    }).Count
  })
  $old=$capacitySession
  $script:failureStage='staged_compose_payload_retirement'
  $new=Enter-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactWorkspaceRoot -RunDirectory $package.artifact_run_dir -Owner $old.owner -LeaseTtlSeconds $old.lease_ttl_seconds -CommittedNewBytes $old.committed_new_bytes -ProtectedPaths $keep -ProtectedCacheKeys @($old.protected_cache_keys)
  $script:capacitySession=$new
  $rotation=Join-Path $package.result_dir 'iteration_compose_capacity_rotation.json'
  Write-RunJson -Path $rotation -Depth 30 -Value @{previous_session=$old;current_session=$new;retirement_targets=@($targets|ForEach-Object{$_.owner.provider_run})}
  $script:protectionReceipts+=,$rotation
  $null=Exit-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $old
  if($releaseGroups.Count){$script:restoredAnchorFieldProtection.groups=@($script:restoredAnchorFieldProtection.groups|Where-Object{$_.anchor_manifest-notin$releaseIds})}
  foreach($target in $targets){
    $target.entry['compose_payload_retirement']=Invoke-StagedComposeRetirement -Owner $target.owner -Disposition $target.disposition
    Write-RunJson -Path (Join-Path $package.result_dir 'iteration_lineage.json') -Depth 100 -Value $Lineage
    Save-NativeWorkflowCheckpoint -Reason 'Consumed compose payload retired through public owner; lineage binds its public receipts.' -WorkflowOutcome bootstrap_in_progress
  }
}

function Complete-StagedTrial {
  param($State,$History,$Lineage,$Pending,$Loop,$Tiers,[string]$ControllerPolicyPath='',
    [Parameter(Mandatory)][System.Collections.IDictionary]$Context)
  $repoRoot=[string]$Context.repo_root;$python=[string]$Context.python
  $frozenContract=[string]$Context.contract_path;$resultDirectory=[string]$Context.result_directory
  if(-not$State.Contains('local_model_tier_index')){$State['local_model_tier_index']=0}
  if(-not$State.Contains('consecutive_candidate_rejections')){$State['consecutive_candidate_rejections']=0}
  $child=[string]$Pending.child_manifest
  $childDocument=Get-Content -LiteralPath $child -Raw|ConvertFrom-Json
  if($childDocument.status-ne'success'-or$childDocument.run_id-ne$Pending.child_run_id){throw 'Pending stage child is not the declared successful run.'}
  $materialization=Get-Content -LiteralPath (Get-ManifestOutputPath -ManifestPath $child -FileName 'two_prism_trial_materialization.json') -Raw|ConvertFrom-Json
  $actual=@($materialization.stripe_biases_v)+@($materialization.prism_voltages_v)
  if($actual.Count-ne4-or@((0..3)|Where-Object{-not[double]::IsFinite([double]$actual[$_])-or[double]$actual[$_]-ne[double]$Pending.voltages_v[$_]}).Count){throw 'Pending stage child voltages differ from the persisted trial.'}
  $identityCode="import sys; from pathlib import Path; from msplatform.workflows.mr_design.downstream_workpoint import _load_stage_trial; a=_load_stage_trial(Path(sys.argv[1])); c=_load_stage_trial(Path(sys.argv[2])); assert a['frozen_problem']==c['frozen_problem'], 'Pending stage child frozen problem differs'"
  $predictionAssessment=@{status='unmeasured';reason='no_quality_authority_or_prediction'}
  if($ControllerPolicyPath){
    # Full measured geometry in a decision can exceed Windows argv limits.
    # Preserve the same input as a checkpoint-bound file, never an argv blob.
    $predictionInput=Join-Path $resultDirectory ('iteration_prediction_input_{0:D3}.json'-f$State.flight_count)
    Write-RunJson -Path $predictionInput -Depth 100 -Value $Pending.decision
    $predictionBytes=(Get-Item -LiteralPath $predictionInput).Length
    $predictionSha=(Get-FileHash -LiteralPath $predictionInput -Algorithm SHA256).Hash
    $identityCode+="; import json; from msplatform.execution.retention import verify_record; verify_record('staged prediction input',dict(path=sys.argv[3],bytes=int(sys.argv[6]),sha256=sys.argv[7])); from msplatform.workflows.mr_design.downstream_workpoint import assess_staged_prediction,resolve_prism_controller_policy; print(json.dumps(assess_staged_prediction(json.loads(Path(sys.argv[3]).read_text(encoding='utf-8-sig')),a,c,json.loads(Path(sys.argv[4]).read_text(encoding='utf-8-sig')),resolve_prism_controller_policy(Path(sys.argv[5])))))"
  }
  $identityArguments=@('-c',$identityCode,([string]$Pending.anchor_manifest),$child)
  if($ControllerPolicyPath){$identityArguments+=@($predictionInput,$frozenContract,$ControllerPolicyPath,([string]$predictionBytes),$predictionSha)}
  $identityOutput=& {
    & $python -I -B @identityArguments
    if($LASTEXITCODE-ne0){throw 'Pending stage child identity validation failed.'}
  }
  if($ControllerPolicyPath){$predictionAssessment=($identityOutput-join"`n")|ConvertFrom-Json -AsHashtable}
  if($State.anchor_manifest-ne$Pending.anchor_manifest-or$State.stage-ne$Pending.stage){throw 'Pending stage anchor or stage differs from checkpoint.'}
  $decision=$Pending.decision
  $entry=[ordered]@{iteration=$State.flight_count;run_id=$Pending.child_run_id;parent_manifest=$Pending.anchor_manifest;child_manifest=$child;child_manifest_sha256=(Get-FileHash $child -Algorithm SHA256).Hash.ToLowerInvariant()}
  if($decision.Contains('prism_controller_policy')){$entry['prism_controller_policy']=$decision.prism_controller_policy}
  if($Pending.Contains('imported_stencil_axis')){$entry['imported_stencil_axis']=$Pending.imported_stencil_axis}
  if($State.Contains('prism_model_manifest')){$entry['prism_model_manifest']=$State.prism_model_manifest}
  $composeOwner=if($Pending.Contains('provider_reference')){Assert-StagedComposeProviderReference -Context $Context -Reference $Pending.provider_reference -ChildRunId ([string]$Pending.child_run_id)}else{$null}
  if($composeOwner){$entry['provider_reference']=$composeOwner;$entry['compose_payload_use']='keep'}
  # Scientific acceptance and state transitions share the Python controller.
  # PowerShell validates identities above and publishes the resulting projections.
  if($decision.status-eq'needs_stencil'){
    $checked=Invoke-PreclosureDecision -Context $Context -Stage stripe_preclosure -Anchor $child -Columns ([ordered]@{}) -OutputPath (Join-Path $resultDirectory ('iteration_staged_payload_{0:D3}_decision.json'-f$State.flight_count))
  }else{
    $checked=Invoke-PreclosureDecision -Context $Context -Stage $State.stage -Anchor $child -Columns ([ordered]@{}) -OutputPath (Join-Path $resultDirectory ('iteration_stage_candidate_{0:D3}_decision.json'-f$State.flight_count))
  }
  $completed=Invoke-WorkpointControllerRequest -Python $python -RepoRoot $repoRoot -Request @{
    action='complete_staged_trial';state=$State;pending=$Pending;checked=$checked;prediction=$predictionAssessment;loop=$Loop
  }
  if($composeOwner){$entry.compose_payload_use=$completed.compose_payload_use}
  $Lineage.children+=,$entry
  if($null-ne$completed.history_decision){$History.decisions+=,$completed.history_decision}
  $State.Clear()
  foreach($key in $completed.state.Keys){$State[$key]=$completed.state[$key]}
}

function Update-StagedAnchorFieldProtection {
  param($State)
  if(-not$staticFieldMode-or$staticBindingMode-ne'native_static_pa'){return}
  if(-not$script:restoredAnchorFieldProtection){$script:restoredAnchorFieldProtection=@{initial_paths=@($capacitySession.protected_paths);groups=@()}}
  $consumers=@($State.anchor_manifest)
  if($State.Contains('pending_trial')-and(Test-Path -LiteralPath $State.pending_trial.child_manifest -PathType Leaf)){
    $pendingDocument=Get-Content -LiteralPath $State.pending_trial.child_manifest -Raw|ConvertFrom-Json
    if($pendingDocument.status-eq'success'){$consumers+=,$State.pending_trial.child_manifest}
  }
  foreach($consumer in @($consumers|Select-Object -Unique)){
  if($consumer-in@($script:restoredAnchorFieldProtection.groups|ForEach-Object{$_.anchor_manifest})){continue}
  $materializationPath=Get-ManifestOutputPath -ManifestPath $consumer -FileName 'two_prism_trial_materialization.json'
  $materialization=Get-Content -LiteralPath $materializationPath -Raw|ConvertFrom-Json
  # Only the replayed live anchor needs payloads; historical columns remain
  # sealed metadata consumers even after their owner has retired the PA.
  $protectionCode=@'
import json, sys
from pathlib import Path
from msplatform.backends.comsol.static_field_binding import load_binding
binding = load_binding(Path(sys.argv[1]))
if binding['mode'] != 'native_static_pa':
    raise ValueError('Recovered anchor field mode differs')
paths = [binding['manifest'], *binding['sources'].values()]
for window in binding['refinement_windows']:
    paths.extend([window['manifest'], *window['sources'].values()])
for instance in binding['instances']:
    paths.extend([instance['manifest'], instance['pa_path']])
print(json.dumps(list(dict.fromkeys(p for p in paths if p))))
'@
  $protectedPaths=& {
    $resolved=((& $python -I -B -c $protectionCode ([string]$materialization.field_binding.path))-join"`n")
    if($LASTEXITCODE-ne0){throw 'Recovered anchor field protection preflight failed.'}
    return @($resolved|ConvertFrom-Json)
  }
  $addedPaths=@($protectedPaths|Where-Object{$_-notin$script:restoredAnchorFieldProtection.initial_paths})
  $renewal=Update-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $capacitySession -ProtectedPaths @($protectedPaths)
  $script:capacitySession=$renewal.session
  # Ephemeral consumer tracking only; this grants no foreign retirement right.
  $script:restoredAnchorFieldProtection.groups+=,@{anchor_manifest=$consumer;manifest_sha256=(Get-FileHash $consumer -Algorithm SHA256).Hash.ToLowerInvariant();paths=$addedPaths;all_paths=@($protectedPaths)}
  }
}

function Get-ActiveStripeAxisIndices {
  param($Profile)
  $names=@($Profile.active_stripe_axes)
  if(($names-join',')-notin@('stripe_1_voltage_v','stripe_1_voltage_v,stripe_2_voltage_v')){
    throw 'Active Stripe axes must explicitly declare S1 or S1/S2 in canonical order.'
  }
  foreach($name in $names){[array]::IndexOf(@('stripe_1_voltage_v','stripe_2_voltage_v'),[string]$name)}
}

function Assert-ActiveStripeVoltages {
  param($Voltages,$ActiveAxes)
  if(@($ActiveAxes).Count-eq1-and(@($Voltages).Count-ne4-or[double]$Voltages[1]-ne0.0)){
    throw 'Inactive S2 must remain at the authored zero-volt seed.'
  }
}

function Get-StagedColumnAxisIndices {
  param([string]$Stage,$Profile)
  return Invoke-WorkpointControllerRequest -Python $python -RepoRoot $repoRoot -Request @{
    action='restored_stage_columns';stage=$Stage;profile=$Profile
  }
}

function Restore-StagedWorkpointChildren {
  param($Bootstrap,$SourceLineage,[string]$BootstrapPath,$PriorState=$null,[switch]$DeferSave)
  if((Get-FileHash $seedManifest -Algorithm SHA256).Hash.ToLowerInvariant()-ne([string]$SourceLineage.root_workpoint_manifest.sha256).ToLowerInvariant()){
    throw 'Stage replay seed manifest differs.'
  }
  # The parent manifest seals the complete controller checkpoint. Inherit its
  # decisions and debits; recalculating old proposals can change accepted history.
  if(-not$Bootstrap.Contains('stage_history')-or-not$Bootstrap.Contains('stage_lineage')-or
     $PriorState-isnot[Collections.IDictionary]){throw 'Saved stage checkpoint is incomplete.'}
  $state=$PriorState;$history=$Bootstrap.stage_history;$lineage=$Bootstrap.stage_lineage
  $profile=(Get-Content -LiteralPath $frozenContract -Raw|ConvertFrom-Json).downstream_fixed_grid_workpoint_profile
  $activeAxes=@(Get-ActiveStripeAxisIndices -Profile $profile)
  if($history.schema_version-ne1-or$history.role-ne'mrtof_downstream_workpoint_iteration_history'-or
     $lineage.schema_version-ne1-or$lineage.role-ne'mrtof_downstream_workpoint_iteration_lineage'-or
     $state.stage-notin@('prism_preclosure','stripe_preclosure')){throw 'Saved stage checkpoint identity differs.'}
  $abandonedFlight=0
  if($state.Contains('target_reanchor')-and$state.target_reanchor.Contains('abandoned_pending')){
    $abandoned=$state.target_reanchor.abandoned_pending
    foreach($key in @('source_checkpoint','stopped_parent_summary')){
      $record=$abandoned[$key]
      if((Get-Item -LiteralPath $record.path).Length-ne$record.bytes-or
         (Get-FileHash -LiteralPath $record.path -Algorithm SHA256).Hash-ne$record.sha256){throw 'Abandoned pending evidence changed.'}
    }
    $checkpoint=Get-Content -LiteralPath $abandoned.source_checkpoint.path -Raw|ConvertFrom-Json -AsHashtable -Depth 100
    $stop=Get-Content -LiteralPath $abandoned.stopped_parent_summary.path -Raw|ConvertFrom-Json -AsHashtable
    if(-not$stop.stopped_parent_verified_absent-or-not$stop.stopped_children_verified_absent-or$stop.pending_trial_executed-ne$false-or
       [int]$abandoned.flight_count-ne[int]$checkpoint.stage_state.flight_count-or
       ($abandoned.pending_trial|ConvertTo-Json -Depth 100 -Compress)-cne($checkpoint.stage_state.pending_trial|ConvertTo-Json -Depth 100 -Compress)-or
       (Test-Path -LiteralPath (Split-Path -Parent ([string]$abandoned.pending_trial.child_manifest)))){throw 'Abandoned pending debit lacks stopped unflown evidence.'}
    $abandonedFlight=[int]$abandoned.flight_count
    if($abandonedFlight-le0){throw 'Abandoned flight debit is invalid.'}
  }
  $known=[ordered]@{};$known[$seedManifest]=$null;$runIds=@{};$iteration=0;$policies=@{}
  foreach($entry in @($SourceLineage.children)){
    if($entry.PSObject.Properties['prism_controller_policy']){
      $policy=$entry.prism_controller_policy
      if(-not$policy.path-or-not$policy.sha256){throw 'Stage replay controller policy differs.'}
      if(-not$policies.ContainsKey([string]$policy.path)){$policies[[string]$policy.path]=(Get-FileHash -LiteralPath $policy.path -Algorithm SHA256).Hash.ToLowerInvariant()}
      if($policies[[string]$policy.path]-ne([string]$policy.sha256).ToLowerInvariant()){throw 'Stage replay controller policy differs.'}
    }
    $iteration++
    if($iteration-eq$abandonedFlight){$iteration++}
    if([int]$entry.iteration-ne$iteration-or-not$known.Contains([string]$entry.parent_manifest)-or
       $known.Contains([string]$entry.child_manifest)-or$runIds.ContainsKey([string]$entry.run_id)-or
       (Get-FileHash $entry.child_manifest -Algorithm SHA256).Hash.ToLowerInvariant()-ne([string]$entry.child_manifest_sha256).ToLowerInvariant()){
      throw 'Stage replay child sequence or manifest binding differs.'
    }
    $document=Get-Content -LiteralPath $entry.child_manifest -Raw|ConvertFrom-Json
    if($document.status-ne'success'-or$document.run_id-ne$entry.run_id){throw 'Stage replay child identity differs.'}
    $known[[string]$entry.child_manifest]=$entry;$runIds[[string]$entry.run_id]=$true
  }
  if(-not$known.Contains([string]$state.anchor_manifest)){throw 'Saved stage anchor is not in its lineage.'}
  if($state.columns.Count){
    $axes=@(Get-StagedColumnAxisIndices -Stage $state.stage -Profile $profile|ForEach-Object{[string]$_})
  }
  foreach($axis in $state.columns.Keys){
    $column=[string]$state.columns[$axis]
    if($axis-notin$axes-or-not$known.Contains($column)-or$null-eq$known[$column]-or$known[$column].parent_manifest-ne$state.anchor_manifest){throw 'Saved stage column differs from its anchor lineage.'}
  }
  if($state.Contains('prism_model_manifest')){
    $null=Get-ManifestOutputPath -ManifestPath $state.prism_model_manifest -FileName 'prism_preclosure_decision.json'
  }
  $hasPending=$state.Contains('pending_trial')
  if($iteration+1-eq$abandonedFlight){$iteration++}
  if([int]$state.flight_count-ne($iteration+[int]$hasPending)-or
     [int]$state.candidate_count-lt0-or[int]$state.candidate_count-gt[int]$state.flight_count){throw 'Saved stage budget differs from its lineage.'}
  if($hasPending){
    $pending=$state.pending_trial
    Assert-ActiveStripeVoltages -Voltages $pending.voltages_v -ActiveAxes $activeAxes
    if($pending.anchor_manifest-ne$state.anchor_manifest-or$pending.stage-ne$state.stage-or
       $known.Contains([string]$pending.child_manifest)-or$runIds.ContainsKey([string]$pending.child_run_id)){throw 'Saved pending stage identity differs or already occurs in lineage.'}
    if(@($pending.voltages_v).Count-ne4-or@($pending.voltages_v|Where-Object{-not[double]::IsFinite([double]$_)}).Count){throw 'Saved pending stage voltages differ.'}
    $expected=[double[]]$pending.decision.voltages_v
    if($pending.decision.status-eq'proposed'){
      $expected=@(0..3|ForEach-Object{$expected[$_]+[double]$state.step_factor*([double]$pending.decision.next_voltages_v[$_]-$expected[$_])})
    }elseif($pending.decision.status-eq'needs_stencil'){
      $axis=[int]$pending.selected.axis
      if($axis-notin@($pending.decision.required_axes)){throw 'Saved pending stencil axis differs.'}
      $expected[$axis]+=[double]$pending.selected.signed_step_v
    }elseif($pending.decision.next_action-ne'complete_N1'){throw 'Saved pending stage decision differs.'}
    if($expected.Count-ne4-or@(0..3|Where-Object{$expected[$_]-ne[double]$pending.voltages_v[$_]}).Count){throw 'Saved pending stage voltages differ.'}
    if(Test-Path -LiteralPath $pending.child_manifest -PathType Leaf){
      $document=Get-Content -LiteralPath $pending.child_manifest -Raw|ConvertFrom-Json
      if($document.run_id-ne$pending.child_run_id){throw 'Published pending stage child identity differs.'}
    }
  }
  $Bootstrap['stage_state']=$state;$Bootstrap['stage_history']=$history;$Bootstrap['stage_lineage']=$lineage
  if(-not$DeferSave){Save-WorkpointBootstrap -Bootstrap $Bootstrap -BootstrapPath $BootstrapPath}
}

function Import-StagedStripeColumns {
  param($State,$History,$Lineage,$Columns,$Loop,$Tiers)
  if($State.stage-ne'stripe_preclosure'-or$State.anchor_manifest-ne$seedManifest){throw 'Explicit Stripe columns require the P-qualified seed anchor.'}
  $empty=Invoke-PreclosureDecision -Context $controllerContext -Stage 'stripe_preclosure' -Anchor $seedManifest -Columns ([ordered]@{}) -OutputPath (Join-Path $package.result_dir 'iteration_seed_stripe_decision.json')
  $activeAxes=@(Get-ActiveStripeAxisIndices -Profile (Get-Content -LiteralPath $frozenContract -Raw|ConvertFrom-Json).downstream_fixed_grid_workpoint_profile)
  if(@($Columns.Keys|Where-Object{[int]$_-notin$activeAxes}).Count){throw 'Explicit Stripe column is inactive.'}
  if($empty.status-ne'needs_stencil'){throw 'Explicit Stripe columns require a measurable S seed needing a stencil.'}
  $checked=Invoke-PreclosureDecision -Context $controllerContext -Stage 'stripe_preclosure' -Anchor $seedManifest -Columns $Columns -OutputPath (Join-Path $package.result_dir 'iteration_imported_stripe_decision.json')
  foreach($axis in $Columns.Keys){
    if($checked.status-notin@('needs_stencil','proposed')-or
       ($checked.Contains('stencil_rejections')-and$checked.stencil_rejections.Contains([string]$axis))-or
       ($checked.status-eq'needs_stencil'-and[int]$axis-in@($checked.required_axes))){
      throw "Explicit Stripe column $axis was not accepted by the seed stage controller."
    }
  }
  $History.decisions+=,$empty;$History.decisions+=,$checked
  foreach($axis in $Columns.Keys){
    $child=[string]$Columns[$axis]
    $document=Get-Content -LiteralPath $child -Raw|ConvertFrom-Json
    $material=Get-Content -LiteralPath (Get-ManifestOutputPath -ManifestPath $child -FileName 'two_prism_trial_materialization.json') -Raw|ConvertFrom-Json
    $actual=[double[]](@($material.stripe_biases_v)+@($material.prism_voltages_v))
    $anchor=[double[]]$empty.voltages_v
    $changed=@(0..3|Where-Object{$actual[$_]-ne$anchor[$_]})
    if($actual.Count-ne4-or$changed.Count-ne1-or$changed[0]-ne[int]$axis){throw 'Explicit Stripe child must change only its declared seed axis.'}
    $prepared=Invoke-WorkpointControllerRequest -Python $controllerContext.python -RepoRoot $controllerContext.repo_root -Request @{
      action='prepare_imported_stencil_column';state=$State;axis=[int]$axis;anchor_v=@($anchor);actual_v=@($actual);tiers=@($Tiers)
    }
    $State.Clear();foreach($key in $prepared.state.Keys){$State[$key]=$prepared.state[$key]}
    $pending=[ordered]@{child_manifest=$child;child_run_id=$document.run_id;anchor_manifest=$seedManifest;stage='stripe_preclosure';voltages_v=@($actual);decision=$empty;selected=$prepared.selected;imported_stencil_axis=[int]$axis}
    Complete-StagedTrial -Context $controllerContext -State $State -History $History -Lineage $Lineage -Pending $pending -Loop $Loop -Tiers $Tiers
  }
}

function Invoke-StagedWorkpointBootstrap {
  param([Collections.IDictionary]$Bootstrap,[string]$BootstrapPath,[string]$ControllerPolicyPath='')
  # Same workflow and physics controller; no fabricated four-axis Jacobian.
  $profile=(Get-Content -LiteralPath $frozenContract -Raw|ConvertFrom-Json).downstream_fixed_grid_workpoint_profile
  $activeAxes=@(Get-ActiveStripeAxisIndices -Profile $profile)
  $loop=$profile.automatic_iteration
  $tiers=@($profile.jacobian_relative_step_tiers.coarse,$profile.jacobian_relative_step_tiers.medium,$profile.jacobian_relative_step_tiers.fine)
  $state=if($Bootstrap.Contains('stage_state')){$Bootstrap.stage_state}else{
    [ordered]@{stage='prism_preclosure';anchor_manifest=$seedManifest;columns=[ordered]@{};attempts=@();flight_count=0;candidate_count=0;step_factor=1.0;completion_attempted=$false}
  }
  if(-not$Bootstrap.Contains('stage_state')-and$PriorPrismDecisionManifest){$state['prism_model_manifest']=$PriorPrismDecisionManifest}
  if(-not$state.Contains('completion_attempted')){$state['completion_attempted']=$false}
  if(-not$state.Contains('local_model_tier_index')){$state['local_model_tier_index']=0}
  if(-not$state.Contains('consecutive_candidate_rejections')){$state['consecutive_candidate_rejections']=0}
  $history=if($Bootstrap.Contains('stage_history')){$Bootstrap.stage_history}else{[ordered]@{schema_version=1;role='mrtof_downstream_workpoint_iteration_history';decisions=@()}}
  $lineage=if($Bootstrap.Contains('stage_lineage')){$Bootstrap.stage_lineage}else{
    [ordered]@{schema_version=1;role='mrtof_downstream_workpoint_iteration_lineage';root_workpoint_manifest=[ordered]@{path=$seedManifest;bytes=(Get-Item $seedManifest).Length;sha256=(Get-FileHash $seedManifest -Algorithm SHA256).Hash.ToLowerInvariant()};children=@()}
  }
  $terminal=$null
  if($Bootstrap.Contains('stage_lineage')){Reclaim-StagedComposeProviders -State $state -Lineage $lineage}
  while($null-eq$terminal){
    if($state.Contains('capacity_lifecycle_blocked')){
      $terminal=[ordered]@{state='checkpoint';status='checkpoint';terminal_reason='capacity_lifecycle_blocked'
        detail=$state.capacity_lifecycle_blocked;full_workpoint_qualified=$false};break
    }
    if($state.Contains('pending_trial')){
      $pending=$state.pending_trial
      Assert-ActiveStripeVoltages -Voltages $pending.voltages_v -ActiveAxes $activeAxes
      $success=(Test-Path -LiteralPath $pending.child_manifest -PathType Leaf)-and
        (Get-Content -LiteralPath $pending.child_manifest -Raw|ConvertFrom-Json).status-eq'success'
      if($PrismHandoffReplayManifest-and-not$success-and$pending.decision.status-eq'needs_stencil'-and
         $pending.child_run_id-ne($RunId+('-stage-{0:D3}'-f$state.flight_count))){
        if($state.anchor_manifest-ne$pending.anchor_manifest-or$state.stage-ne$pending.stage){throw 'Pending stage anchor or stage differs from checkpoint.'}
        $axis=[string]$pending.selected.axis
        if($state.columns.Contains($axis)){
          $refreshed=Invoke-PreclosureDecision -Context $controllerContext -Stage $state.stage -Anchor $state.anchor_manifest -Columns $state.columns -OutputPath (Join-Path $package.result_dir 'iteration_restored_pending_decision.json')
          if($refreshed.status-in@('needs_stencil','proposed')-and$refreshed.Contains('replayed_stage_axes')-and
             [int]$axis-in@($refreshed.replayed_stage_axes)-and
             ($refreshed.status-eq'proposed'-or[int]$axis-notin@($refreshed.required_axes))-and
             (-not$refreshed.Contains('stencil_rejections')-or-not$refreshed.stencil_rejections.Contains($axis))){
            $remainingAxes=if($refreshed.status-eq'proposed'){@()}else{@($refreshed.required_axes)}
            $history.decisions+=,[ordered]@{status='pending_plan_not_executed';reason='verified_stage_column_already_available';pending_trial=$pending;required_axes=@($remainingAxes);full_workpoint_qualified=$false}
            $state.Remove('pending_trial')|Out-Null
            $Bootstrap['stage_state']=$state;$Bootstrap['stage_history']=$history;$Bootstrap['stage_lineage']=$lineage
            Write-RunJson -Path (Join-Path $package.result_dir 'iteration_history.json') -Depth 100 -Value $history
            Save-WorkpointBootstrap -Bootstrap $Bootstrap -BootstrapPath $BootstrapPath
            continue
          }
        }
      }
      if(-not$success){
        if($pending.child_run_id-eq($RunId+('-stage-{0:D3}'-f$state.flight_count))){throw 'Unfinished stage trial requires a new parent RunId.'}
        $pending.child_run_id=$RunId+('-stage-{0:D3}'-f$state.flight_count)
        $pending.child_manifest=Join-Path $trialArtifactRoot ('runs/'+$pending.child_run_id+'/run_manifest.json')
        Save-WorkpointBootstrap -Bootstrap $Bootstrap -BootstrapPath $BootstrapPath
        $arguments=New-CenterTrialArguments -Voltages ([double[]]$pending.voltages_v) -ChildRunId $pending.child_run_id
        Invoke-CenterTrial -Arguments $arguments -StagedPending $pending -Bootstrap $Bootstrap -BootstrapPath $BootstrapPath | Out-Host
        if($state.Contains('capacity_lifecycle_blocked')){continue}
      }
      Complete-StagedTrial -Context $controllerContext -State $state -History $history -Lineage $lineage -Pending $pending -Loop $loop -Tiers $tiers -ControllerPolicyPath $ControllerPolicyPath
      Write-RunJson -Path (Join-Path $package.result_dir 'iteration_history.json') -Depth 100 -Value $history
      Write-RunJson -Path (Join-Path $package.result_dir 'iteration_lineage.json') -Depth 100 -Value $lineage
      Save-WorkpointBootstrap -Bootstrap $Bootstrap -BootstrapPath $BootstrapPath
      $restoredProtection=Get-Variable -Name restoredAnchorFieldProtection -Scope Script -ErrorAction SilentlyContinue
      if($restoredProtection-and$restoredProtection.Value){Update-StagedAnchorFieldProtection -State $state}
      Reclaim-StagedComposeProviders -State $state -Lineage $lineage
      continue
    }
    if($state.stage-eq'stripe_preclosure'-and$state.consecutive_candidate_rejections-ge[int]$loop.maximum_consecutive_non_improving_iterations){
      # Reset is saved before reading a new scientific decision, as on resume.
      $prepared=Invoke-WorkpointControllerRequest -Python $python -RepoRoot $repoRoot -Request @{
        action='plan_staged_trial';phase='prepare';state=$state;profile=$profile
      }
      $state.Clear();foreach($key in $prepared.state.Keys){$state[$key]=$prepared.state[$key]}
      if($prepared.terminal){$terminal=$prepared.terminal;break}
      if($prepared.history_decision){$history.decisions+=,$prepared.history_decision}
      $Bootstrap['stage_state']=$state;$Bootstrap['stage_history']=$history;$Bootstrap['stage_lineage']=$lineage
      Save-WorkpointBootstrap -Bootstrap $Bootstrap -BootstrapPath $BootstrapPath
    }
    $decisionPath=Join-Path $package.result_dir ('iteration_stage_{0:D3}_decision.json'-f$history.decisions.Count)
    $decision=Invoke-StagedPreclosureDecision -State $state -OutputPath $decisionPath -ControllerPolicyPath $ControllerPolicyPath
    if($decision.Contains('voltages_v')){Assert-ActiveStripeVoltages -Voltages $decision.voltages_v -ActiveAxes $activeAxes}
    if($decision.Contains('next_voltages_v')){Assert-ActiveStripeVoltages -Voltages $decision.next_voltages_v -ActiveAxes $activeAxes}
    $history.decisions+=,$decision
    $Bootstrap['stage_state']=$state;$Bootstrap['stage_history']=$history;$Bootstrap['stage_lineage']=$lineage
    Write-RunJson -Path (Join-Path $package.result_dir 'iteration_history.json') -Depth 100 -Value $history
    Write-RunJson -Path (Join-Path $package.result_dir 'iteration_lineage.json') -Depth 100 -Value $lineage
    Save-WorkpointBootstrap -Bootstrap $Bootstrap -BootstrapPath $BootstrapPath
    if($decision.status-eq'terminal'){$terminal=$decision;break}
    if($stripeSeedColumns.Count-and-not$Bootstrap.Contains('imported_stripe_columns')-and
       ($state.stage-ne'prism_preclosure'-or$decision.next_action-ne'stripe_preclosure')){
      throw 'Explicit Stripe columns cannot be used before the seed P stage passes.'
    }
    # One whole-round request owns numerical planning and both trial debits.
    $planned=Invoke-WorkpointControllerRequest -Python $python -RepoRoot $repoRoot -Request @{
      action='plan_staged_trial';state=$state;decision=$decision;profile=$profile
    }
    $state.Clear();foreach($key in $planned.state.Keys){$state[$key]=$planned.state[$key]}
    if($planned.terminal){$terminal=$planned.terminal;break}
    if($planned.action-eq'stage_transition'){
      if($stripeSeedColumns.Count-and-not$Bootstrap.Contains('imported_stripe_columns')){
        Import-StagedStripeColumns -State $state -History $history -Lineage $lineage -Columns $stripeSeedColumns -Loop $loop -Tiers $tiers
        $Bootstrap['imported_stripe_columns']=$stripeSeedColumns
        Save-WorkpointBootstrap -Bootstrap $Bootstrap -BootstrapPath $BootstrapPath
      }
      continue
    }
    $voltages=[double[]]$planned.voltages_v
    $childId=$RunId+('-stage-{0:D3}'-f$state.flight_count)
    $script:failureStage='stage_'+$state.stage
    $selectedStep=$planned.selected
    $state['pending_trial']=[ordered]@{child_run_id=$childId;child_manifest=(Join-Path $trialArtifactRoot "runs/$childId/run_manifest.json");voltages_v=@($voltages);anchor_manifest=$state.anchor_manifest;stage=$state.stage;decision=$decision;selected=$selectedStep}
    Save-WorkpointBootstrap -Bootstrap $Bootstrap -BootstrapPath $BootstrapPath
    $arguments=New-CenterTrialArguments -Voltages $voltages -ChildRunId $childId
    Invoke-CenterTrial -Arguments $arguments -StagedPending $state.pending_trial -Bootstrap $Bootstrap -BootstrapPath $BootstrapPath | Out-Host
    if($state.Contains('capacity_lifecycle_blocked')){continue}
    Complete-StagedTrial -Context $controllerContext -State $state -History $history -Lineage $lineage -Pending $state.pending_trial -Loop $loop -Tiers $tiers -ControllerPolicyPath $ControllerPolicyPath
    Write-RunJson -Path (Join-Path $package.result_dir 'iteration_history.json') -Depth 100 -Value $history
    Write-RunJson -Path (Join-Path $package.result_dir 'iteration_lineage.json') -Depth 100 -Value $lineage
    Save-WorkpointBootstrap -Bootstrap $Bootstrap -BootstrapPath $BootstrapPath
    $restoredProtection=Get-Variable -Name restoredAnchorFieldProtection -Scope Script -ErrorAction SilentlyContinue
    if($restoredProtection-and$restoredProtection.Value){Update-StagedAnchorFieldProtection -State $state}
    Reclaim-StagedComposeProviders -State $state -Lineage $lineage
  }
  $history.decisions+=,$terminal
  $Bootstrap.stage_state=$state;$Bootstrap.stage_history=$history;$Bootstrap.stage_lineage=$lineage
  Write-RunJson -Path (Join-Path $package.result_dir 'iteration_history.json') -Depth 100 -Value $history
  Write-RunJson -Path (Join-Path $package.result_dir 'iteration_lineage.json') -Depth 100 -Value $lineage
  Save-WorkpointBootstrap -Bootstrap $Bootstrap -BootstrapPath $BootstrapPath
  return [pscustomobject]@{terminal_decision=$terminal;history=$history;lineage=$lineage}
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

function Get-InterruptedSOnlyTopologyRecoveryDecision {
  param([Parameter(Mandatory)]$History)
  Invoke-WorkpointControllerRequest -Python $python -RepoRoot $repoRoot -Request @{
    action='interrupted_topology_recovery_decision';history=$History
  }
}

function Invoke-SLocalModelRecovery {
  param([Parameter(Mandatory)]$Decision,[Parameter(Mandatory)]$History,[Parameter(Mandatory)]$Lineage,
    [Parameter(Mandatory)][string]$StatePath,[Parameter(Mandatory)][string]$HistoryPath,[Parameter(Mandatory)]$ContractDocument,
    [Parameter(Mandatory)][System.Collections.IDictionary]$RecoveryPolicy)
  $anchor=$Decision.recovery_state.accepted_anchor
  if($anchor-isnot[Collections.IDictionary]){throw 'Recovery decision lacks accepted anchor.'}
  $anchorV=@($anchor.voltages_v|ForEach-Object{[double]$_})
  if($anchorV.Count-ne4){throw 'Recovery decision anchor must contain S1/S2/P1/P2.'}
  $anchorEvidence=Find-AcceptedRecoveryAnchorEvidence -History $History -Lineage $Lineage -Anchor $anchor
  $stored=$null
  if(Test-Path -LiteralPath $StatePath){$stored=Get-Content -LiteralPath $StatePath -Raw|ConvertFrom-Json -AsHashtable -Depth 100}
  $prepared=Invoke-WorkpointControllerRequest -Python $python -RepoRoot $repoRoot -Request @{
    action='prepare_recovery_state';decision=$Decision;evidence=$anchorEvidence;stored=$stored;history=$History
    profile=$ContractDocument.downstream_fixed_grid_workpoint_profile;policy=$RecoveryPolicy;include_probe_directions=$true
  }
  $state=$prepared.state;$requiredDirections=@($prepared.required_directions)
  if($state.status-eq'validated'){return $state}
  if($state.status-eq'terminal'){return $state}
  Save-IterationRecoveryState -State $state -Path $StatePath
  while($true){
    $planned=Invoke-WorkpointControllerRequest -Python $python -RepoRoot $repoRoot -Request @{
      action='plan_recovery_probe';state=$state;directions=$requiredDirections;profile=$ContractDocument.downstream_fixed_grid_workpoint_profile
    }
    $state=$planned.state
    if($planned.action-eq'return'){Save-IterationRecoveryState -State $state -Path $StatePath;return $state}
    if($planned.action-eq'refresh'){break}
    $probe=$state.probes[-1];$trial=@($planned.voltages_v)
    $label=if($probe.axis-eq0){'s1'}else{'s2'}
    $directionLabel=if($probe.direction-eq1){'p'}else{'n'}
    $probeId='{0}-ri{1:D2}r{2}-{3}{4}' -f $RunId,[int]$state.trigger.iteration,[int]$state.recovery_round,$label,$directionLabel
    $probe.run_id=$probeId
    Save-IterationRecoveryState -State $state -Path $StatePath
    try{
      $arguments=New-CenterTrialArguments -Voltages $trial -ChildRunId $probeId
      Invoke-CenterTrial -Arguments $arguments | Out-Host
      $manifest=Join-Path $trialArtifactRoot "runs\$probeId\run_manifest.json"
      $evidence=Get-CenterTrialPhysicalEvidence -Manifest $manifest -Voltages $trial
      foreach($key in $evidence.Keys){$probe[$key]=$evidence[$key]}
      $probe.status=if($evidence.passed){'accepted_physical_probe'}else{'rejected_physical_probe'}
    }catch{$probe.status='failed';$probe.failure_reason=$_.Exception.Message}
    Save-IterationRecoveryState -State $state -Path $StatePath
  }
  $s1=$planned.columns[0];$s2=$planned.columns[1]
  $usedDirections=@($planned.supported_directions)
  $modelPath=Join-Path (Split-Path -Parent $StatePath) 'iteration_local_s_model.json'
  Push-Location -LiteralPath $repoRoot
  try{
    & $python -I -B -m msplatform.workflows.mr_design.downstream_workpoint `
      --prior $frozenProposal --contract $frozenContract --refresh-history $historyPath --refresh-anchor-observation $anchorEvidence.observation `
      --refresh-anchor-materialization $anchorEvidence.materialization --refresh-s1-observation $s1.observation_path `
      --refresh-s1-materialization $s1.materialization_path --refresh-s2-observation $s2.observation_path `
      --refresh-s2-materialization $s2.materialization_path --refresh-history-window 2 `
      --refresh-trusted-radius-linf-v $planned.trusted_radius_linf_v `
      --refresh-supported-directions $usedDirections[0] $usedDirections[1] `
      --refresh-position-tolerance-mm ([double]$ContractDocument.downstream_fixed_grid_workpoint_profile.automatic_iteration.acceptance_tolerances.Stripe_target_phase_y_minus_origin_mm) `
      --output $modelPath | Out-Host
    if($LASTEXITCODE-ne0){throw 'Local S Jacobian refresh failed.'}
  }finally{Pop-Location}
  $model=Get-Content -LiteralPath $modelPath -Raw|ConvertFrom-Json -AsHashtable
  $completed=Invoke-WorkpointControllerRequest -Python $python -RepoRoot $repoRoot -Request @{
    action='complete_recovery_model';state=$state;model=$model;profile=$ContractDocument.downstream_fixed_grid_workpoint_profile
  }
  if($completed.publish_model){Write-RunJson -Path $modelPath -Depth 30 -Value $completed.model}
  $state=$completed.state
  if($null-ne$completed.model_projection){
    $state.model=$completed.model_projection
    $state.model.path=$modelPath
    $state.model.sha256=(Get-FileHash -LiteralPath $modelPath -Algorithm SHA256).Hash.ToLowerInvariant()
  }
  Save-IterationRecoveryState -State $state -Path $StatePath
  return $state
}

function Save-NativeWorkflowCheckpoint {
  param([Parameter(Mandatory)][string]$Reason,[switch]$ExternalInterruption,
    [string]$WorkflowOutcome='execution_failed_recovery_pending',$FinalDecision=$null)
  if($null-ne$nativeRuntimeSession-and$nativeRuntimeSession.directory-and(Test-Path -LiteralPath $nativeRuntimeSession.directory)){
    $ownerManifest=Join-Path $nativeRuntimeSession.owner_run_directory 'run_manifest.json'
    $ownerStatus=if(Test-Path -LiteralPath $ownerManifest -PathType Leaf){
      [string](Get-Content -LiteralPath $ownerManifest -Raw|ConvertFrom-Json).status
    }else{''}
    if($ownerStatus-notin@('checkpoint','success')){
      $null=Invoke-RunCapacityLifecycleAdapter -Python $python -RepoRoot $repoRoot -Action register-writing `
        -ArtifactRoot $artifactWorkspaceRoot -RunConfig $nativeRuntimeSession.owner_run_config
    }
  }
  $checkpointOutputs=@()
  if($null-ne$nativeRuntimeSession-and(Test-Path -LiteralPath $nativeRuntimeSession.checkpoint_path)){$checkpointOutputs+=$nativeRuntimeSession.checkpoint_path}
  foreach($name in @('workpoint_bootstrap.json','initial_grouped_workpoint_decision.json','iteration_history.json','iteration_lineage.json','iteration_recovery_state.json')){
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
    native_runtime_owner_run=$(if($null-ne$nativeRuntimeSession){$nativeRuntimeSession.owner_run_directory}else{$null})
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
    & $python -I -B -m msplatform.workflows.mr_design.downstream_workpoint `
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
$frozenResumeParentManifest=$null
$resumeIterationCheckpoint=[bool]($ResumeParentCheckpoint-and-not$freshBootstrap)
$replayTerminalStages=$false
if($ResumeParentCheckpoint){
  $resumePath=(Resolve-Path -LiteralPath $ResumeParentCheckpoint).Path
  $resumeParentRun=if(Test-Path -LiteralPath $resumePath -PathType Leaf){Split-Path -Parent $resumePath}else{$resumePath}
  if((Split-Path $resumeParentRun -Leaf)-eq$RunId){throw 'Checkpoint recovery requires a new parent RunId, including external interruption.'}
  $resumeManifest=Join-Path $resumeParentRun 'run_manifest.json'
  $resumeStatus=[string](Get-Content -LiteralPath $resumeManifest -Raw|ConvertFrom-Json).status
  $replayTerminalStages=$stagedBootstrap-and$resumeStatus-in@('checkpoint','success','failed','interrupted')
  if($resumeStatus-ne'checkpoint'-and-not$replayTerminalStages){throw 'Native execution assets can resume only from a nonterminal checkpoint.'}
  if(-not$staticFieldMode){
  $resumeNativeCheckpoint=Get-ManifestOutputPath -ManifestPath $resumeManifest -FileName 'native_corridor_runtime_checkpoint.json'
  $savedRuntime=Get-Content -LiteralPath $resumeNativeCheckpoint -Raw|ConvertFrom-Json
  $runtimeOwnerRun=Split-Path (Split-Path ([string]$savedRuntime.directory) -Parent) -Parent
  if([IO.Path]::GetFullPath($resumeNativeCheckpoint)-ne[IO.Path]::GetFullPath((Join-Path $runtimeOwnerRun 'results/native_corridor_runtime_checkpoint.json'))){throw 'Native checkpoint receipt escapes its asset owner.'}
  $runtimeOwnerStatus=[string](Get-Content -LiteralPath (Join-Path $runtimeOwnerRun 'run_manifest.json') -Raw|ConvertFrom-Json).status
  if($runtimeOwnerStatus-notin@('checkpoint','success')){throw 'Native runtime owner did not reach a reusable checkpoint or success state.'}
  if($freshBootstrap){$resumeBootstrapPath=Get-ManifestOutputPath -ManifestPath $resumeManifest -FileName 'workpoint_bootstrap.json'}
  $projectionArgs=@($resumeManifest,'--require-status','checkpoint','--require-project',$project,
    '--require-mode','downstream_fixed_grid_workpoint_iteration','--consumer-projection-id','mrtof_native_execution_resume_v1',
    '--consumed-output',$resumeNativeCheckpoint)
  if($resumeBootstrapPath){$projectionArgs+=@('--consumed-output',$resumeBootstrapPath)}
  & $python -I -B -c 'from msplatform.execution.manifest_verification import main; from msplatform.backends.simion.native_completion import retention_api; main(retention_api=retention_api)' @projectionArgs
  if($LASTEXITCODE-ne0){throw 'Native recovery checkpoint manifest binding differs.'}
  }else{
    if($freshBootstrap){$resumeBootstrapPath=Get-ManifestOutputPath -ManifestPath $resumeManifest -FileName 'workpoint_bootstrap.json'}
    $priorStatic=Get-Content -LiteralPath (Join-Path $resumeParentRun 'inputs/field_provider_request.json') -Raw|ConvertFrom-Json -AsHashtable
    if(($priorStatic|ConvertTo-Json -Depth 100 -Compress)-ne($fieldProviderRequest|ConvertTo-Json -Depth 100 -Compress)){
      $storageResumeCode="import json,sys; from msplatform.workflows.mr_design.fixed_grid_workpoint import assert_native_provider_storage_resume; assert_native_provider_storage_resume(json.loads(sys.argv[1]),json.loads(sys.argv[2]))"
      & {
        & $python -I -B -c $storageResumeCode ($priorStatic|ConvertTo-Json -Depth 100 -Compress) ($fieldProviderRequest|ConvertTo-Json -Depth 100 -Compress)
        if($LASTEXITCODE-ne0){throw 'Static recovery field provider inputs differ beyond the exact sealed storage view.'}
      }
    }
    Assert-ResponseFieldResumeDeclaration -ParentRun $resumeParentRun -BindingPath $ResponseFieldBindingPath -Declaration $responseDeclaration
  }
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
  $runtimeOwnerStatus=[string](Get-Content -LiteralPath $runtimeOwnerManifest -Raw|ConvertFrom-Json).status
  if($runtimeOwnerStatus-notin@('checkpoint','success')){throw 'Native runtime owner did not reach a reusable checkpoint or success state.'}
  & $python -I -B -c 'from msplatform.execution.manifest_verification import main; from msplatform.backends.simion.native_completion import retention_api; main(retention_api=retention_api)' $runtimeOwnerManifest `
    --require-status $runtimeOwnerStatus --require-project $project --require-mode downstream_fixed_grid_workpoint_iteration `
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
$restoredAnchorFieldProtection = $null
$nativeRuntimeSession = $null
$resourceLease = $null
$hostOutcome = 'failed'
try {
  $protectionTtlSeconds = [int]((Get-Content -LiteralPath $contract -Raw | ConvertFrom-Json).downstream_fixed_grid_workpoint_profile.automatic_iteration.capacity_protection_ttl_seconds)
  $activeAxes=@(Get-ActiveStripeAxisIndices -Profile (Get-Content -LiteralPath $contract -Raw|ConvertFrom-Json).downstream_fixed_grid_workpoint_profile)
  if($activeAxes.Count-eq1-and-not$stagedBootstrap){throw 'Single-Stripe control requires the existing staged workflow.'}
  if(@($stripeSeedColumns.Keys|Where-Object{[int]$_-notin$activeAxes}).Count){throw 'Explicit Stripe column is inactive.'}
  if ($protectionTtlSeconds -le 0) { throw 'Capacity protection TTL must be positive.' }
  $workflowInputPaths = @(
    $(if($InitialWorkpointManifest){Split-Path -Parent (Resolve-Path -LiteralPath $InitialWorkpointManifest).Path}elseif($SeedTrialManifest){Split-Path -Parent (Resolve-Path -LiteralPath $SeedTrialManifest).Path}else{Split-Path -Parent (Resolve-Path -LiteralPath $ContinuationRunManifest).Path}),
    $GeometryReviewRunPath,$MirrorRunPath,$StripeRunPath,$AcceleratorProviderReceiptPath,$NativeCorridorBankRunPath,
    $NativeSystemRuntimeBundlePath,$mirrorVoltageVariation
  )
  if($staticFieldMode){
    $workflowInputPaths+=@($FieldProviderRequestPath,$CenterSourceReceiptPath,$fieldProviderRequest.source_binding_path)
    $workflowInputPaths+=@($stripeSeedColumns.Values)
    if($staticBindingMode-eq'native_static_pa'){
      $workflowInputPaths+=@($staticBinding.manifest)+@($staticBinding.sources.Values)
      foreach($window in $staticBinding.refinement_windows){$workflowInputPaths+=@($window.manifest)+@($window.sources.Values)}
      foreach($instance in $staticBinding.instances){$workflowInputPaths+=@($instance.manifest,$instance.pa_path)}
      if($fieldProviderRequest.Contains('response_basis_paths')){
        # Keep the immutable bank protected between serial provider children.
        $protectionRequest=$fieldProviderRequest|ConvertTo-Json -Depth 100|ConvertFrom-Json -AsHashtable
        if(-not$staticBinding.Contains('consumer_view')){$protectionRequest.numerical_contract_path=[string]$contract}
        $bankProtectionCode="import json,sys; from msplatform.backends.simion.native_static_field_provider import compile_request; print(json.dumps(compile_request(json.loads(sys.argv[1]))['protected_paths']))"
        $bankProtectedPaths=& {
          $resolved=((& $python -I -B -c $bankProtectionCode ($protectionRequest|ConvertTo-Json -Depth 100 -Compress))-join"`n")
          if($LASTEXITCODE-ne0){throw 'Native response bank protection preflight failed.'}
          return @($resolved|ConvertFrom-Json)
        }
        $workflowInputPaths+=@($bankProtectedPaths)
      }
    }else{$workflowInputPaths+=@($fieldProviderRequest.source_field_manifest)}
  }
  if($CompletedFieldProviderManifest){$workflowInputPaths+=@(Split-Path -Parent $CompletedFieldProviderManifest)}
  if($PriorPrismDecisionManifest){
    $modelRoot=Split-Path -Parent $PriorPrismDecisionManifest
    $modelManifest=Get-Content -LiteralPath $PriorPrismDecisionManifest -Raw|ConvertFrom-Json
    $modelAnchor=Resolve-RunRecordPath -Record $modelManifest.inputs.baseline_manifest -BaseDirectory $modelRoot -Label 'prior prism model anchor'
    $workflowInputPaths+=@($modelRoot,(Split-Path -Parent $modelAnchor))
  }
  if($ResponseFieldBindingPath){
    foreach($term in $responseBinding.response_terms){
      $workflowInputPaths+=@($term.binding_path,$term.binding.export_manifest,$term.binding.assembly_manifest,$term.binding.collision_manifest)
      $workflowInputPaths+=@($term.binding.sources.Values)
      if($term.binding.Contains('refinement_windows')){
        foreach($window in $term.binding.refinement_windows){$workflowInputPaths+=@($window.sources.Values)}
      }
    }
  }
  if($resumeParentRun){$workflowInputPaths+=@($resumeParentRun,$runtimeOwnerRun)}
  $workflowInputPaths = @($workflowInputPaths | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
    ForEach-Object { (Resolve-Path -LiteralPath $_).Path } | Select-Object -Unique)
  $failureStage = 'capacity_startup'
  Write-Host 'MRTOF_WORKPOINT_STAGE=capacity_startup'
  if($runtimeOwnerRun-and$runtimeOwnerStatus-ne'success'){
    $null=Invoke-RunCapacityLifecycleAdapter -Python $python -RepoRoot $repoRoot -Action register-writing `
      -ArtifactRoot $artifactWorkspaceRoot -RunConfig (Join-Path $runtimeOwnerRun 'run_config.json')
  }
  $capacityArguments=@{}
  $capacitySession = Enter-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot `
    -ArtifactRoot $artifactWorkspaceRoot -RunDirectory $package.artifact_run_dir `
    -CommittedNewBytes 26214400 -ProtectedPaths $workflowInputPaths `
    -Owner $protectionLeaseOwner -LeaseTtlSeconds $protectionTtlSeconds @capacityArguments
  Write-Host 'MRTOF_WORKPOINT_STAGE=capacity_ready'
  $capacityStartupPath = Join-Path $package.result_dir 'artifact_capacity_gate_startup.json'
  Write-RunJson -Path $capacityStartupPath -Depth 20 -Value $capacitySession
  $protectionReceipts += $capacityStartupPath
  $failureStage = 'host_resource_startup'
  if(-not$staticFieldMode){
  $resourceLease=Enter-HostResourceStage -Role SIMION -Stage 'mrtof_prepare' `
    -Budget (Get-HostResourceBudget -Role SIMION -Stage 'mrtof_prepare') -RunId $RunId
  Write-Host 'MRTOF_WORKPOINT_STAGE=native_runtime_resume'
  $ownerRun=if($runtimeOwnerRun){$runtimeOwnerRun}else{$package.artifact_run_dir}
  $nativeRuntimeSession=[pscustomobject]@{
    lease_id=$capacitySession.lease_id;directory=(Join-Path $ownerRun 'runtime/native_corridor_family');runtime=$null
    owner_run_directory=$ownerRun;owner_run_config=(Join-Path $ownerRun 'run_config.json');resident_bytes=[int64]0
    checkpoint_path=(Join-Path $ownerRun 'results/native_corridor_runtime_checkpoint.json')
  }
  }
  $failureStage = 'freeze_inputs'
  if($staticFieldMode){
    $FieldProviderRequestPath=Copy-VerifiedRunInput -Source $FieldProviderRequestPath -Destination (Join-Path $package.input_dir 'field_provider_request.json')
    if($ResponseFieldBindingPath){$ResponseFieldBindingPath=Copy-VerifiedRunInput -Source $ResponseFieldBindingPath -Destination (Join-Path $package.input_dir 'response_field_binding.json')}
    # The child resolves its producer manifest relative to the original receipt.
    $frozenCenterSourceReceipt=Copy-VerifiedRunInput -Source $CenterSourceReceiptPath -Destination (Join-Path $package.input_dir 'center_source_receipt.json')
  }
  $frozenCompletedProviderManifest=$null
  if($CompletedFieldProviderManifest){
    $frozenCompletedProviderManifest=Copy-VerifiedRunInput -Source $CompletedFieldProviderManifest `
      -Destination (Join-Path $package.input_dir 'completed_field_provider_manifest.json')
  }
  $frozenContract = Copy-VerifiedRunInput -Source $contract -Destination (Join-Path $package.input_dir 'contract.json')
  $controllerContext=@{repo_root=$repoRoot;python=$python;contract_path=$frozenContract;result_directory=$package.result_dir;prism_handoff_replay_manifest=$PrismHandoffReplayManifest;run_id=$RunId;artifact_root=$artifactRoot}
  $frozenRecoveryPolicy=Copy-VerifiedRunInput -Source $recoveryPolicySource -Destination (Join-Path $package.input_dir 'local_model_recovery_policy.json')
  $recoveryPolicy=Invoke-WorkpointControllerRequest -Python $python -RepoRoot $repoRoot -Request @{action='validate_recovery_policy';policy=(Get-Content -LiteralPath $frozenRecoveryPolicy -Raw|ConvertFrom-Json -AsHashtable)}
  if($PrismControllerPolicyPath){
    $frozenPrismControllerPolicyPath=Copy-VerifiedRunInput -Source $PrismControllerPolicyPath -Destination (Join-Path $package.input_dir 'prism_controller_policy.json')
    & {
      & $python -I -B -c 'import sys; from pathlib import Path; from msplatform.workflows.mr_design.downstream_workpoint import resolve_prism_controller_policy; resolve_prism_controller_policy(Path(sys.argv[1]))' $frozenPrismControllerPolicyPath
      if($LASTEXITCODE-ne0){throw 'Prism controller policy is invalid.'}
    }
  }
  if($null-ne$mirrorVoltageVariation){
    $mirrorVoltageVariation=Copy-VerifiedRunInput -Source $mirrorVoltageVariation `
      -Destination (Join-Path $package.input_dir 'terminal_time_mirror_voltage_variation.json')
  }
  if($null-ne$AcceleratorYAnchorMm){
    if(-not[double]::IsFinite([double]$AcceleratorYAnchorMm)){throw 'AcceleratorYAnchorMm must be finite.'}
    $resolvedContract=Get-Content -LiteralPath $frozenContract -Raw|ConvertFrom-Json -AsHashtable
    $resolvedContract.accelerator.focus_y_anchor.project_y_mm=[double]$AcceleratorYAnchorMm
    Write-RunJson -Path $frozenContract -Depth 100 -Value $resolvedContract
  }
  $prismSearchBounds=@($Prism1SearchMinimumV,$Prism1SearchMaximumV,$Prism2SearchMinimumV,$Prism2SearchMaximumV)
  $specifiedPrismSearchBounds=@($prismSearchBounds|Where-Object{$null-ne$_}).Count
  if($specifiedPrismSearchBounds-ne0){
    if($specifiedPrismSearchBounds-ne4-or@($prismSearchBounds|Where-Object{-not[double]::IsFinite([double]$_)}).Count){
      throw 'Prism search-window override requires four finite bounds.'
    }
    if([double]$Prism1SearchMinimumV-ge[double]$Prism1SearchMaximumV-or
       [double]$Prism2SearchMinimumV-ge[double]$Prism2SearchMaximumV){
      throw 'Prism search-window override bounds must be increasing.'
    }
    $resolvedContract=Get-Content -LiteralPath $frozenContract -Raw|ConvertFrom-Json -AsHashtable
    $window=$resolvedContract.prism_transport.two_prism_injection_l0.voltage_polarity_contract.current_initial_search_window_v
    $window.prism_1=@([double]$Prism1SearchMinimumV,[double]$Prism1SearchMaximumV)
    $window.prism_2=@([double]$Prism2SearchMinimumV,[double]$Prism2SearchMaximumV)
    Write-RunJson -Path $frozenContract -Depth 100 -Value $resolvedContract
  }
  # Every child consumes the run-local resolved contract.  Changing only the
  # accelerator rigid-body y anchor therefore rebuilds no PA and remains fully
  # visible in the frozen GUI-equivalent flight inputs.
  $script:contract=$frozenContract
  $script:oaComponentContractFrozen=Copy-VerifiedRunInput -Source $AcceleratorComponentContractPath -Destination (Join-Path $package.input_dir 'oa_component_contract.json')
  # The base bundle owns the already prepared MR fallback and detector PAs.
  # Replace only its obsolete accelerator record with the OA provider receipt;
  # this is a compact identity projection and never materializes a PA.
  $failureStage = 'bind_provider_accelerator'
  $nativeRecoveryProblem=$null
  if(-not$staticFieldMode){
  $baseNativeSystemRuntimeBundle = (Resolve-Path -LiteralPath $NativeSystemRuntimeBundlePath).Path
  $bankForProviderBinding = Get-Content -LiteralPath (Join-Path $NativeCorridorBankRunPath 'results/pa_family_cache_publication.json') -Raw | ConvertFrom-Json
  $nativeIdentityPath = Join-Path ([IO.Path]::GetTempPath()) ('mrtof_native_provider_identity_'+[guid]::NewGuid().ToString('N')+'.json')
  $providerBoundBundle = Join-Path $package.input_dir 'native_system_runtime_bundle.json'
  try {
    [IO.File]::WriteAllText($nativeIdentityPath, (([ordered]@{schema_version=1;role='mrtof_private_native_corridor_family';status='prepared';response_refine_performed=$false;published_native_members_opened=$false;controller_refine='solutions={0}';cache_key=[string]$bankForProviderBinding.cache_key;generation_sha256=[string]$bankForProviderBinding.generation_sha256}|ConvertTo-Json -Compress)), [Text.UTF8Encoding]::new($false))
    Push-Location $repoRoot
    try {
      & $python -I -B -m msplatform.workflows.oa_mr.native_system_runtime rebind-accelerator `
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
      accelerator_component_contract_sha256=(Get-FileHash -LiteralPath $script:oaComponentContractFrozen -Algorithm SHA256).Hash
      accelerator_geometry_profile_id=$AcceleratorGeometryProfileId
      accelerator_provider_receipt=(Resolve-Path -LiteralPath $AcceleratorProviderReceiptPath).Path
      native_system_runtime_bundle=(Resolve-Path -LiteralPath $NativeSystemRuntimeBundlePath).Path
      trajectory_profile=$TrajectoryProfileId;trajectory_step_scale=$TrajectoryStepScale;source_y_offset_mm=$AcceleratorSourceYOffsetMm
      pulse_initial_exit=[bool]$PulseAcceleratorUntilInitialExit
      pulse_schedule_sha256=$(if($AcceleratorPulseSchedulePath){(Get-FileHash -LiteralPath $AcceleratorPulseSchedulePath -Algorithm SHA256).Hash}else{$null})
      mirror_voltage_variation_sha256=$(if($null-ne$mirrorVoltageVariation){(Get-FileHash -LiteralPath $mirrorVoltageVariation -Algorithm SHA256).Hash}else{$null})
    }
  if($resumeParentRun){
      $priorProblem=(Get-Content -LiteralPath (Join-Path $resumeParentRun 'run_config.json') -Raw|ConvertFrom-Json -AsHashtable).parameters.native_recovery_problem
      $priorBundle=[string]$priorProblem.native_system_runtime_bundle
      $currentBundle=[string]$nativeRecoveryProblem.native_system_runtime_bundle
      $priorComparable=[ordered]@{};$currentComparable=[ordered]@{}
      foreach($key in $priorProblem.Keys){if($key-ne'native_system_runtime_bundle'){$priorComparable[$key]=$priorProblem[$key]}}
      foreach($key in $nativeRecoveryProblem.Keys){if($key-ne'native_system_runtime_bundle'){$currentComparable[$key]=$nativeRecoveryProblem[$key]}}
      if(($priorComparable|ConvertTo-Json -Compress)-ne($currentComparable|ConvertTo-Json -Compress)-or
        -not(Test-RunFilesIdentical -Left $priorBundle -Right $currentBundle)){
        throw 'Native recovery scientific problem differs; retained family is not rebuilt.'
      }
    }
  }
  # Direct NativeRuntimeCheckpoint reuse is limited to the already verified
  # native corridor PA family. Open-NativeCorridorRuntimeCheckpoint binds its
  # cache key, generation and member hashes before the first child. Static PA choices, IOB
  # poses, trajectory settings and acceptance contracts are flight inputs,
  # not PA-producing identities, so they must not force a corridor rebuild.
  $earlyConfig=Get-Content -LiteralPath $package.run_config -Raw|ConvertFrom-Json -AsHashtable
  $earlyConfig.inputs.accelerator_component_contract=$script:oaComponentContractFrozen
  $earlyConfig.parameters.accelerator_geometry_profile_id=$AcceleratorGeometryProfileId
  $earlyConfig.parameters.native_recovery_problem=$nativeRecoveryProblem
  if($frozenCompletedProviderManifest){
    $earlyConfig.inputs.completed_field_provider_manifest=$frozenCompletedProviderManifest
    $earlyConfig.parameters.completed_field_provider_manifest_source=$CompletedFieldProviderManifest
  }
  if($staticFieldMode){
    $earlyConfig.inputs.field_provider_request=$FieldProviderRequestPath
    if($ResponseFieldBindingPath){$earlyConfig.inputs.response_field_binding=$ResponseFieldBindingPath}
    $earlyConfig.inputs.center_source_receipt=$frozenCenterSourceReceipt
  }
  Write-RunJson -Path $package.run_config -Depth 30 -Value $earlyConfig
  $controllerStateSource=Copy-VerifiedRunInput -Source (Join-Path $packageRoot 'workflows/mr_design/workpoint_controller_state.py') -Destination (Join-Path $package.input_dir 'workpoint_controller_state.py')
  $controllerSource = Copy-VerifiedRunInput `
    -Source (Join-Path $packageRoot 'workflows/mr_design/downstream_workpoint_iteration.py') `
    -Destination (Join-Path $package.input_dir 'downstream_workpoint_iteration.py')
  $workflowSource = Copy-VerifiedRunInput -Source (Join-Path $packageRoot 'workflows/resources/run_downstream_workpoint_iteration.ps1') `
    -Destination (Join-Path $package.input_dir 'run_downstream_workpoint_iteration.ps1')
  $checkpointSource = Copy-VerifiedRunInput `
    -Source (Join-Path $packageRoot 'workflows/mr_design/downstream_workpoint_checkpoint.py') `
    -Destination (Join-Path $package.input_dir 'downstream_workpoint_checkpoint.py')
  # Resolve and protect the one runtime before any child trial.  After the
  # single transition to the heavy flight stage, shared children perform no
  # scheduler transactions, so completed SIMION PIDs cannot accumulate as
  # stale process identities on this long-lived lease.
  if(-not$staticFieldMode){
  $bank=Get-Content -LiteralPath (Join-Path $NativeCorridorBankRunPath 'results/pa_family_cache_publication.json') -Raw|ConvertFrom-Json
  $runtimeSimion=if($SimionExe){$SimionExe}else{Join-Path $env:ProgramFiles 'SIMION-2020/simion.exe'}
  if($resumeNativeCheckpoint){
    Open-NativeCorridorRuntimeCheckpoint -Session $nativeRuntimeSession -CapacityWorkflowSession $capacitySession `
      -BankGenerationDirectory $bank.generation_directory -CacheKey $bank.cache_key -GenerationSha256 $bank.generation_sha256 `
      -Python $python -RepoRoot $repoRoot -SimionExe $runtimeSimion
  }
  $preparedRuntime=Get-NativeCorridorRuntimeFamily -Session $nativeRuntimeSession `
    -CapacityWorkflowSession $capacitySession -BankGenerationDirectory $bank.generation_directory `
    -CacheKey $bank.cache_key -GenerationSha256 $bank.generation_sha256 `
    -Python $python -RepoRoot $repoRoot -SimionExe $runtimeSimion -ResourceLease $resourceLease -RunId $RunId
  $resourceLease=$preparedRuntime.resource_lease
  $resourceLease=Update-HostResourceStage -Lease $resourceLease -Stage 'mrtof_flight' `
    -Budget (Get-HostResourceBudget -Role SIMION -Stage 'mrtof_flight') -RetainedMemoryBytes 0
  Write-Host 'MRTOF_WORKPOINT_STAGE=native_runtime_ready'
  }
  $bootstrapPath = $null
  $seedProjection=$null;$frozenSeedManifest=$null;$frozenSeedMaterialization=$null
  $frozenContinuationManifest=$null;$frozenContinuationSummary=$null
  if($ContinuationRunManifest){
    $continuationSeed=Read-ContinuationVoltageSeed -ManifestPath $ContinuationRunManifest
    $continuationPairIdentity=Assert-ContinuationPairIdentity -ContinuationManifestPath $continuationSeed.manifest `
      -ResolvedContractPath $frozenContract -StripeRunDirectory $StripeRunPath
    $frozenContinuationManifest=Copy-VerifiedRunInput -Source $continuationSeed.manifest -Destination (Join-Path $package.input_dir 'parent_continuation_run_manifest.json')
    $frozenContinuationSummary=Copy-VerifiedRunInput -Source $continuationSeed.summary -Destination (Join-Path $package.input_dir 'parent_continuation_summary.json')
    if($resumeBootstrapPath){
      $priorContinuationBootstrap=Get-Content -LiteralPath $resumeBootstrapPath -Raw|ConvertFrom-Json -AsHashtable
      $seedManifest=[string]$priorContinuationBootstrap.seed_manifest
      $initialChildren=@($priorContinuationBootstrap.children)
      $transportSeedAttempts=@($priorContinuationBootstrap.transport_seed_attempts)
    }else{
      $profile=(Get-Content -LiteralPath $frozenContract -Raw|ConvertFrom-Json).downstream_fixed_grid_workpoint_profile
      $transportSeed=Find-ContinuationTransportSeed -ContinuationSeed $continuationSeed -Profile $profile
      $seedManifest=$transportSeed.manifest
      $transportSeedAttempts=@($transportSeed.attempts)
      $initialChildren=@($seedManifest)
    }
    $seedMaterialization=Get-ManifestOutputPath -ManifestPath $seedManifest -FileName 'two_prism_trial_materialization.json'
    $seed=Get-Content -LiteralPath $seedMaterialization -Raw|ConvertFrom-Json
    $seedVoltages=@(@($seed.stripe_biases_v)+@($seed.prism_voltages_v)|ForEach-Object{[double]$_})
    if($seedVoltages.Count-ne4-or@($seedVoltages|Where-Object{-not[double]::IsFinite([double]$_)}).Count){
      throw 'Real continuation seed trial did not materialize four finite voltages.'
    }
    $seedProjection=[ordered]@{
      projection_id='mrtof_continuation_to_real_workpoint_v1';manifest=$continuationSeed.manifest
      consumed_output=$continuationSeed.summary;generated_seed_trial_manifest=$seedManifest
      assertion_scope='unique_joint_root_prism_voltages__stripe_voltage_and_incidence_authority_remain_with_stripe_receipt'
      pair_identity=$continuationPairIdentity
    }
  }elseif($SeedTrialManifest){
    $seedManifest=(Resolve-Path -LiteralPath $SeedTrialManifest).Path
    $seedIdentity=Get-Content -LiteralPath $seedManifest -Raw|ConvertFrom-Json -AsHashtable
    if(-not(($seedIdentity.project-eq'instrument_assembly'-and$seedIdentity.mode-eq'oa_mr')-or
      ($seedIdentity.project-eq$project-and$seedIdentity.mode-eq'finite_3d_two_prism_voltage_trial'))){
      throw 'Voltage seed has an unsupported flight owner/mode pair.'
    }
    $seedMaterialization=Get-ManifestOutputPath -ManifestPath $seedManifest -FileName 'two_prism_trial_materialization.json'
    $seedProjection=[ordered]@{
      projection_id='mrtof_downstream_voltage_seed_v1';manifest=$seedManifest
      consumed_output=$seedMaterialization
      assertion_scope='run_config_and_voltage_materialization_only__other_historical_records_not_asserted'
    }
    & $python -I -B -c 'from msplatform.execution.manifest_verification import main; from msplatform.backends.simion.native_completion import retention_api; main(retention_api=retention_api)' $seedManifest `
      --require-status success --require-project $seedIdentity.project --require-mode $seedIdentity.mode `
      --consumer-projection-id $seedProjection.projection_id --consumed-output $seedMaterialization
    if($LASTEXITCODE-ne0){throw 'Bootstrap voltage seed manifest is invalid.'}
    $seed=Get-Content -LiteralPath $seedMaterialization -Raw|ConvertFrom-Json
    $seedVoltages=@(@($seed.stripe_biases_v)+@($seed.prism_voltages_v)|ForEach-Object{[double]$_})
    $initialChildren=@()
  }
  if($freshBootstrap){
    $frozenSeedManifest=Copy-VerifiedRunInput -Source $seedManifest -Destination (Join-Path $package.input_dir 'voltage_seed_manifest.json')
    $frozenSeedMaterialization=Copy-VerifiedRunInput -Source $seedMaterialization -Destination (Join-Path $package.input_dir 'voltage_seed_materialization.json')
    $profile=(Get-Content -LiteralPath $frozenContract -Raw|ConvertFrom-Json).downstream_fixed_grid_workpoint_profile
    Assert-ActiveStripeVoltages -Voltages $seedVoltages -ActiveAxes $activeAxes
    $stencilConfiguration=Invoke-WorkpointControllerRequest -Python $python -RepoRoot $repoRoot -Request @{
      action='bootstrap_stencil_configuration';voltages_v=@($seedVoltages);profile=$profile
    }
    $steps=@($stencilConfiguration.forward_steps_v)
    if($seedVoltages.Count-ne4-or@($seedVoltages|Where-Object{-not[double]::IsFinite([double]$_)}).Count-or$steps.Count-ne4-or@($steps|Where-Object{[double]$_-le0-or-not[double]::IsFinite([double]$_)}).Count){throw 'Bootstrap requires four finite seed voltages and four positive stencil steps.'}
    $stepScales=@($stencilConfiguration.stencil_step_scales)
    $bootstrap=[ordered]@{schema_version=1;role='mrtof_native_workpoint_bootstrap';seed_manifest=$seedManifest;seed_voltages_v=$seedVoltages;forward_steps_v=$steps;stencil_step_scales=$stepScales;children=$initialChildren}
    if($ContinuationRunManifest){$bootstrap.transport_seed_attempts=$transportSeedAttempts}
    if($resumeBootstrapPath){
      # Consume historical state without duplicating the sealed child field trees.
      $stateCode='import json,sys; from pathlib import Path; from msplatform.workflows.mr_design.downstream_workpoint import compact_saved_iteration_state; print(json.dumps(compact_saved_iteration_state(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8-sig")))))'
      $priorBootstrap=& {
        $output=((& $python -I -B -c $stateCode $resumeBootstrapPath)-join"`n")
        if($LASTEXITCODE-ne0){throw 'Saved workpoint state could not be read.'}
        return ($output|ConvertFrom-Json -AsHashtable -Depth 100)
      }
      if($priorBootstrap.schema_version-ne1-or$priorBootstrap.role-ne'mrtof_native_workpoint_bootstrap'){throw 'Resumed bootstrap schema or role differs.'}
      if(($priorBootstrap.seed_voltages_v-join',')-ne($seedVoltages-join',')-or($priorBootstrap.forward_steps_v-join',')-ne($steps-join',')){
        throw 'Resumed bootstrap seed or stencil steps differ.'
      }
      $bootstrap.children=@($priorBootstrap.children)
      if($priorBootstrap.ContainsKey('attempts')){$bootstrap['attempts']=@($priorBootstrap.attempts)}
      if($priorBootstrap.ContainsKey('resume_children')){$bootstrap['resume_children']=@($priorBootstrap.resume_children)}
      if($priorBootstrap.ContainsKey('transport_seed_attempts')){$bootstrap['transport_seed_attempts']=@($priorBootstrap.transport_seed_attempts)}
      foreach($name in @('stage_state','stage_history','stage_lineage')){
        if($priorBootstrap.ContainsKey($name)){$bootstrap[$name]=$priorBootstrap[$name]}
      }
    }
    $bootstrapPath=Join-Path $package.result_dir 'workpoint_bootstrap.json'
    Write-RunJson -Path $bootstrapPath -Depth 20 -Value $bootstrap
    $bootstrapConfig=Get-Content -LiteralPath $package.run_config -Raw|ConvertFrom-Json -AsHashtable
    $bootstrapConfig.inputs.contract=$frozenContract
    $bootstrapConfig.inputs.workflow_source=$workflowSource
    $bootstrapConfig.inputs.workpoint_bootstrap=$bootstrapPath
    $bootstrapConfig.inputs.voltage_seed_manifest=$frozenSeedManifest
    $bootstrapConfig.inputs.voltage_seed_materialization=$frozenSeedMaterialization
    if($frozenContinuationManifest){
      $bootstrapConfig.inputs.parent_continuation_run_manifest=$frozenContinuationManifest
      $bootstrapConfig.inputs.parent_continuation_summary=$frozenContinuationSummary
    }
    $bootstrapConfig.parameters.voltage_seed_consumer_projection=$seedProjection
    Write-RunJson -Path $package.run_config -Depth 20 -Value $bootstrapConfig
    if($resumeBootstrapPath-and-not$stagedBootstrap){
      $resumeManifestDocument=Get-Content -LiteralPath $resumeManifest -Raw|ConvertFrom-Json
      $resumeLineageOutputs=@($resumeManifestDocument.outputs|Where-Object{[IO.Path]::GetFileName([string]$_.path)-eq'iteration_lineage.json'})
      if($resumeLineageOutputs.Count-gt1){throw 'Resume parent checkpoint binds multiple iteration lineages.'}
      if($resumeLineageOutputs.Count-eq0){
        $InitialWorkpointManifest=Invoke-WorkpointStencil -Bootstrap $bootstrap -BootstrapPath $bootstrapPath -RetainBaselineGuiWorkbench:$RetainBaselineGuiWorkbench
      }else{
        $resumeIterationCheckpoint=$true
        $parentLineagePath=Get-ManifestOutputPath -ManifestPath $resumeManifest -FileName 'iteration_lineage.json'
      $parentLineage=Get-Content -LiteralPath $parentLineagePath -Raw|ConvertFrom-Json
      $InitialWorkpointManifest=[string]$parentLineage.root_workpoint_manifest.path
      if(-not(Test-Path -LiteralPath $InitialWorkpointManifest -PathType Leaf)-or
         (Get-FileHash -LiteralPath $InitialWorkpointManifest -Algorithm SHA256).Hash.ToLowerInvariant()-ne([string]$parentLineage.root_workpoint_manifest.sha256).ToLowerInvariant()){
        throw 'Resume parent root workpoint manifest binding differs.'
      }
      }
    }elseif(-not$stagedBootstrap){
      $InitialWorkpointManifest=Invoke-WorkpointStencil -Bootstrap $bootstrap -BootstrapPath $bootstrapPath -RetainBaselineGuiWorkbench:$RetainBaselineGuiWorkbench
    }
  }
  if($stagedBootstrap){
    if($PriorPrismDecisionManifest){
      # Keep the original authority path for relative manifest records; freeze
      # a copy as the parent input, without rebasing its recorded dependencies.
      $frozenPrismModel=Copy-VerifiedRunInput -Source $PriorPrismDecisionManifest -Destination (Join-Path $package.input_dir 'prior_prism_decision_manifest.json')
    }
    if($PrismHandoffReplayManifest){
      $PrismHandoffReplayManifest=Copy-VerifiedRunInput -Source $PrismHandoffReplayManifest -Destination (Join-Path $package.input_dir 'prism_handoff_replay_manifest.json')
      $controllerContext.prism_handoff_replay_manifest=$PrismHandoffReplayManifest
    }
    $configuration=Get-Content -LiteralPath $package.run_config -Raw|ConvertFrom-Json -AsHashtable
    $configuration.inputs.controller_source=$controllerSource
    $configuration.inputs.controller_state_source=$controllerStateSource
    $configuration.inputs.local_model_recovery_policy=$frozenRecoveryPolicy
    if($frozenPrismControllerPolicyPath){$configuration.inputs.prism_controller_policy=$frozenPrismControllerPolicyPath}
    $configuration.inputs.checkpoint_source=$checkpointSource
    if($PrismHandoffReplayManifest){$configuration.inputs.prism_handoff_replay_manifest=$PrismHandoffReplayManifest}
    if($PriorPrismDecisionManifest){$configuration.inputs.prior_prism_decision_manifest=$frozenPrismModel}
    $configuration.parameters.execution='real_single_center_stage_preclosure'
    $configuration.parameters.corridor_field=$staticBindingMode
    $configuration.parameters.field_update=if($staticBindingMode-eq'native_static_pa'){if($fieldProviderRequest.Contains('response_basis_paths')){'fixed_bank_native_axis_response_composition'}else{'same_geometry_candidate_voltage_parent_and_local_refine'}}else{'same_saved_mesh_candidate_voltage_solve_and_export'}
    $configuration.parameters.stopping_authority='contract.downstream_fixed_grid_workpoint_profile.automatic_iteration'
    foreach($axis in $stripeSeedColumns.Keys){
      $child=[string]$stripeSeedColumns[$axis]
      $configuration.inputs['stripe_'+$axis+'_child_manifest']=Copy-VerifiedRunInput -Source $child -Destination (Join-Path $package.input_dir ('stripe_'+$axis+'_child_manifest.json'))
      $childDocument=Get-Content -LiteralPath $child -Raw|ConvertFrom-Json
      foreach($record in $childDocument.outputs){
        $name=[IO.Path]::GetFileName([string]$record.path)
        if($name-in@('two_prism_trial_materialization.json','two_prism_trial_observation.json')-or[IO.Path]::GetExtension($name)-eq'.log'){
          $source=Get-ManifestOutputPath -ManifestPath $child -FileName $name
          $configuration.inputs['stripe_'+$axis+'_'+$name]=Copy-VerifiedRunInput -Source $source -Destination (Join-Path $package.input_dir ('stripe_'+$axis+'_'+$name))
        }
      }
    }
    Write-RunJson -Path $package.run_config -Depth 100 -Value $configuration
    $historyPath=Join-Path $package.result_dir 'iteration_history.json'
    $lineagePath=Join-Path $package.result_dir 'iteration_lineage.json'
    $recoveryStatePath=Join-Path $package.result_dir 'iteration_recovery_state.json'
    $initialGroupedDecisionPath=Join-Path $package.result_dir 'initial_grouped_workpoint_decision.json'
    if($replayTerminalStages){
      $oldConfig=Get-Content -LiteralPath (Join-Path $resumeParentRun 'run_config.json') -Raw|ConvertFrom-Json
      if($oldConfig.inputs.PSObject.Properties['prior_prism_decision_manifest']-or$PriorPrismDecisionManifest){
        $oldModel=if($oldConfig.inputs.PSObject.Properties['prior_prism_decision_manifest']){[string]$oldConfig.inputs.prior_prism_decision_manifest}else{''}
        if(-not$oldModel-or-not$PriorPrismDecisionManifest-or(Get-FileHash $oldModel -Algorithm SHA256).Hash-ne(Get-FileHash $frozenPrismModel -Algorithm SHA256).Hash){throw 'Stage replay prior prism model differs.'}
      }
      foreach($pair in @(@('contract',$frozenContract),@('center_source_receipt',$frozenCenterSourceReceipt),@('prism_handoff_replay_manifest',$PrismHandoffReplayManifest))){
        $oldProperty=$oldConfig.inputs.PSObject.Properties[$pair[0]]
        $oldPath=if($oldProperty){[string]$oldProperty.Value}else{''}
        if($pair[0]-eq'prism_handoff_replay_manifest'-and-not$oldPath-and-not$pair[1]){continue}
        if(-not$oldPath-or-not$pair[1]){throw 'Stage replay source, contract or stage replay evidence differs.'}
        if((Get-FileHash $oldPath -Algorithm SHA256).Hash-ne(Get-FileHash $pair[1] -Algorithm SHA256).Hash){
          if($pair[0]-ne'contract'){throw 'Stage replay source, contract or stage replay evidence differs.'}
          $controllerResumeCode='import json,sys; from pathlib import Path; from msplatform.workflows.mr_design.downstream_workpoint import assert_bounded_controller_resume; read=lambda p:json.loads(Path(p).read_text(encoding="utf-8-sig")); print(json.dumps(assert_bounded_controller_resume(read(sys.argv[1]),read(sys.argv[2]),read(sys.argv[3])["stage_state"])))'
          $resumeChanges=& {
            $value=((& $python -I -B -c $controllerResumeCode $oldPath $pair[1] $resumeBootstrapPath)-join"`n")
            if($LASTEXITCODE-ne0){throw 'Stage replay controller change is outside the bounded resume scope.'}
            return ($value|ConvertFrom-Json -AsHashtable)
          }
          $configuration.inputs.previous_controller_contract=$oldPath
          $configuration.parameters.controller_resume_changes=$resumeChanges
          Write-RunJson -Path $package.run_config -Depth 100 -Value $configuration
        }
      }
      # The verified bootstrap is saved after every accepted child and may be
      # the only sealed lineage when a parent fails before terminal publication.
      $sourceLineage=$priorBootstrap.stage_lineage|ConvertTo-Json -Depth 100|ConvertFrom-Json -Depth 100
      $priorStageState=if($priorBootstrap.ContainsKey('stage_state')){$priorBootstrap.stage_state}else{$null}
      Restore-StagedWorkpointChildren -Bootstrap $bootstrap -SourceLineage $sourceLineage -BootstrapPath $bootstrapPath -PriorState $priorStageState
      Update-StagedAnchorFieldProtection -State $bootstrap.stage_state
    }
    $staged=Invoke-StagedWorkpointBootstrap -Bootstrap $bootstrap -BootstrapPath $bootstrapPath -ControllerPolicyPath $frozenPrismControllerPolicyPath
    $terminalDecision=$staged.terminal_decision;$history=$staged.history;$lineage=$staged.lineage
  }else{
  $initialManifest = (Resolve-Path -LiteralPath $InitialWorkpointManifest).Path
  & $python -I -B -c 'from msplatform.execution.manifest_verification import main; from msplatform.backends.simion.native_completion import retention_api; main(retention_api=retention_api)' $initialManifest `
    --require-status success --require-project $project --require-mode downstream_fixed_grid_workpoint
  if ($LASTEXITCODE -ne 0) { throw 'Initial downstream workpoint manifest is not verified success.' }
  $initialProposal = Get-ManifestOutputPath -ManifestPath $initialManifest -FileName 'downstream_fixed_grid_workpoint.json'
  $frozenProposal = Copy-VerifiedRunInput -Source $initialProposal -Destination (Join-Path $package.input_dir 'initial_workpoint.json')
  $frozenInitialManifest = Copy-VerifiedRunInput -Source $initialManifest -Destination (Join-Path $package.input_dir 'initial_workpoint_manifest.json')
  $resumeChildManifest = $null
  $frozenResumeChildManifest = $null
  if ($ResumeSuccessfulChildManifest) {
    $resumeChildManifest = (Resolve-Path -LiteralPath $ResumeSuccessfulChildManifest).Path
    & $python -I -B -c 'from msplatform.execution.manifest_verification import main; from msplatform.backends.simion.native_completion import retention_api; main(retention_api=retention_api)' $resumeChildManifest `
      --require-status success --require-project instrument_assembly --require-mode oa_mr
    if ($LASTEXITCODE -ne 0) { throw 'Resume child manifest is not verified success.' }
    $frozenResumeChildManifest = Copy-VerifiedRunInput -Source $resumeChildManifest `
      -Destination (Join-Path $package.input_dir 'resume_successful_child_manifest.json')
  }
  $proposal = Get-Content -LiteralPath $frozenProposal -Raw | ConvertFrom-Json -AsHashtable
  if(-not$staticFieldMode){
  $bankPublication=Get-Content -LiteralPath (Join-Path $NativeCorridorBankRunPath 'results\pa_family_cache_publication.json') -Raw|ConvertFrom-Json
  if(-not $proposal.ContainsKey('native_bank_identity') -or $null-eq$proposal.native_bank_identity -or
    $proposal.native_bank_identity.cache_key-ne$bankPublication.cache_key -or
    $proposal.native_bank_identity.generation_sha256-ne$bankPublication.generation_sha256){
    throw 'Initial Jacobian was not measured on the selected native bank.'
  }
  }else{
    $baselineMaterialization=Get-ManifestOutputPath -ManifestPath $proposal.baseline_manifest -FileName 'two_prism_trial_materialization.json'
    $baselineField=Get-Content -LiteralPath $baselineMaterialization -Raw|ConvertFrom-Json
    if($baselineField.field_binding.mode-ne$staticBindingMode){throw 'Static iteration requires a measured matching static-field Jacobian.'}
  }
  # The measured baseline is already a real child of the initial stencil.  A
  # fresh chain reuses that observation to derive its first grouped candidate;
  # it must not spend iter-01 flying the same baseline a second time.
  $current = $null
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
  if($ResumeParentCheckpoint){
    $frozenResumeParentManifest=Copy-VerifiedRunInput -Source $resumeManifest `
      -Destination (Join-Path $package.input_dir 'resume_parent_checkpoint_manifest.json')
  }
  $configuration = Get-Content -LiteralPath $package.run_config -Raw | ConvertFrom-Json -AsHashtable
  $configuration.inputs = [ordered]@{
    local_model_recovery_policy=$frozenRecoveryPolicy
    contract=$frozenContract;initial_workpoint=$frozenProposal
    initial_workpoint_manifest=$frozenInitialManifest
    controller_source=$controllerSource;controller_state_source=$controllerStateSource;workflow_source=$workflowSource
    checkpoint_source=$checkpointSource
  }
  if($bootstrapPath){$configuration.inputs.workpoint_bootstrap=$bootstrapPath}
  if($null-ne$mirrorVoltageVariation){$configuration.inputs.terminal_time_mirror_voltage_variation=$mirrorVoltageVariation}
  if($frozenContinuationManifest){
    $configuration.inputs.parent_continuation_run_manifest=$frozenContinuationManifest
    $configuration.inputs.parent_continuation_summary=$frozenContinuationSummary
  }
  if ($frozenResumeChildManifest) { $configuration.inputs.resume_successful_child_manifest=$frozenResumeChildManifest }
  if ($frozenResumeParentManifest) { $configuration.inputs.resume_parent_checkpoint=$frozenResumeParentManifest }
  $configuration.parameters = [ordered]@{
    execution='real_single_center_child_flights'
    corridor_field='native_full_corridor_at_0p25_mm'
    field_update='native_fast_adjust'
    child_runner='src/msplatform/workflows/resources/oa_mr.ps1'
    stopping_authority='contract.downstream_fixed_grid_workpoint_profile.automatic_iteration'
  }
  if($staticFieldMode){
    $configuration.inputs.field_provider_request=$FieldProviderRequestPath
    if($ResponseFieldBindingPath){$configuration.inputs.response_field_binding=$ResponseFieldBindingPath}
    $configuration.inputs.center_source_receipt=$frozenCenterSourceReceipt
    $configuration.parameters.corridor_field=$staticBindingMode
    $configuration.parameters.field_update=if($staticBindingMode-eq'native_static_pa'){if($fieldProviderRequest.Contains('response_basis_paths')){'fixed_bank_native_axis_response_composition'}else{'same_geometry_candidate_voltage_parent_and_local_refine'}}else{'same_saved_mesh_candidate_voltage_solve_and_export'}
  }
  if($frozenCompletedProviderManifest){
    $configuration.inputs.completed_field_provider_manifest=$frozenCompletedProviderManifest
    $configuration.parameters.completed_field_provider_manifest_source=$CompletedFieldProviderManifest
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
  $initialGroupedDecisionPath = Join-Path $package.result_dir 'initial_grouped_workpoint_decision.json'
  if (-not $resumeIterationCheckpoint) {
    $initialGroupedDecision = New-InitialGroupedWorkpointDecision -Proposal $proposal -ProposalPath $frozenProposal `
      -ContractPath $frozenContract -HistoryPath $historyPath -OutputPath $initialGroupedDecisionPath
    if ($initialGroupedDecision.state -eq 'terminal') {
      $terminalDecision = $initialGroupedDecision
    } else {
      $current = @($initialGroupedDecision.proposed_voltages_v | ForEach-Object { [double]$_ })
    }
  }
  if ($resumeIterationCheckpoint) {
    $resumeParentResolved = (Resolve-Path -LiteralPath $ResumeParentCheckpoint).Path
    $resumeParentRun = if (Test-Path -LiteralPath $resumeParentResolved -PathType Leaf) {
      Split-Path -Parent $resumeParentResolved
    } else { $resumeParentResolved }
    $resumeParentManifest = Join-Path $resumeParentRun 'run_manifest.json'
    if (-not (Test-Path -LiteralPath $resumeParentManifest -PathType Leaf)) {
      throw "Resume parent checkpoint lacks run_manifest.json: $resumeParentRun"
    }
    $checkpointLatestChild=$resumeChildManifest
    if(-not$checkpointLatestChild){
      $parentLineagePath=Get-ManifestOutputPath -ManifestPath $resumeParentManifest -FileName 'iteration_lineage.json'
      $parentLineage=Get-Content -LiteralPath $parentLineagePath -Raw|ConvertFrom-Json
      if(-not$parentLineage.children-or@($parentLineage.children).Count-lt1){throw 'Resume parent checkpoint has no completed child lineage.'}
      $checkpointLatestChild=[string](@($parentLineage.children)[-1].child_manifest)
    }
    $checkpointPath = Join-Path $package.result_dir 'reconstructed_checkpoint.json'
    & {
      & $python -I -B -m msplatform.workflows.mr_design.downstream_workpoint_checkpoint `
        --old-parent-run $resumeParentRun --latest-child-manifest $checkpointLatestChild `
        --current-initial-manifest $frozenInitialManifest --current-proposal $frozenProposal `
        --current-contract $frozenContract --artifact-project-runs (Join-Path $trialArtifactRoot 'runs') `
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
    if($checkpoint.terminal_decision){
      $terminalDecision=$checkpoint.terminal_decision
    }
    if($checkpoint.recovery_state_path){
      $priorRecovery=(Resolve-Path -LiteralPath ([string]$checkpoint.recovery_state_path)).Path
      $recoveryImportSource=Copy-VerifiedRunInput -Source $priorRecovery -Destination (Join-Path $package.input_dir 'imported_recovery_checkpoint.json')
      $configuration.inputs.imported_recovery_checkpoint=$recoveryImportSource
      $importDecision=if($pendingRecoveryDecision){$pendingRecoveryDecision}else{Get-InterruptedSOnlyTopologyRecoveryDecision -History $history}
      $importEvidence=if($importDecision){Find-AcceptedRecoveryAnchorEvidence -History $history -Lineage $lineage -Anchor $importDecision.recovery_state.accepted_anchor}else{$null}
      $importedRecovery=Invoke-WorkpointControllerRequest -Python $python -RepoRoot $repoRoot -Request @{
        action='import_recovery_checkpoint';stored=(Get-Content -LiteralPath $recoveryImportSource -Raw|ConvertFrom-Json -AsHashtable -Depth 100);decision=$importDecision;evidence=$importEvidence
        history=$history;profile=(Get-Content -LiteralPath $frozenContract -Raw|ConvertFrom-Json -AsHashtable).downstream_fixed_grid_workpoint_profile;policy=$recoveryPolicy
      }
      Write-RunJson -Path $recoveryStatePath -Depth 100 -Value $importedRecovery
    }
    Write-RunJson -Path $historyPath -Depth 30 -Value $history
    Write-RunJson -Path $lineagePath -Depth 30 -Value $lineage
    # Bind the exact parent evidence file into this run.  The original run
    # directory is still passed to the replay tool above, but a directory is
    # not a valid manifest input and cannot be content verified.
    $configuration.inputs.reconstructed_checkpoint=$checkpointPath
    Write-RunJson -Path $package.run_config -Depth 20 -Value $configuration
  }
  if ($null -eq $terminalDecision -and ($null -eq $current -or @($current).Count -ne 4)) {
    throw 'Initial grouped workpoint decision must provide four S1/S2/P1/P2 voltages.'
  }
  if($null-eq$terminalDecision-and$null-eq$pendingRecoveryDecision){
    $pendingRecoveryDecision=Get-InterruptedSOnlyTopologyRecoveryDecision -History $history
    if($null-ne$pendingRecoveryDecision){Write-Host "MRTOF_WORKPOINT_RECOVERY status=reconstructed reason=s_only_topology_loss"}
  }
  $maximumIterations = [int]((Get-Content -LiteralPath $frozenContract -Raw | ConvertFrom-Json).downstream_fixed_grid_workpoint_profile.automatic_iteration.maximum_iterations)
  $budget=Invoke-WorkpointControllerRequest -Python $python -RepoRoot $repoRoot -Request @{
    action='main_iteration_budget';phase='start';maximum_iterations=$maximumIterations
    next_iteration=$startIteration;terminal_decision=$terminalDecision
  }
  $maximumFlightAttempts=$budget.maximum_flight_attempts
  if($null-eq$terminalDecision){$terminalDecision=$budget.terminal_decision}
  if($null-eq$terminalDecision-and$null-ne$pendingRecoveryDecision){
    do{
      $recovery=Invoke-SLocalModelRecovery -Decision $pendingRecoveryDecision -History $history -Lineage $lineage `
        -StatePath $recoveryStatePath -HistoryPath $historyPath -RecoveryPolicy $recoveryPolicy `
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
      $recoveryCapacity=Update-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $capacitySession
      $capacitySession=$recoveryCapacity.session
      $recoveryCapacityPath=Join-Path $package.result_dir ('capacity_protection_recovery_{0:D2}_renew.json' -f $startIteration)
      Write-RunJson -Path $recoveryCapacityPath -Depth 20 -Value $recoveryCapacity
      $protectionReceipts += $recoveryCapacityPath
    }
  }
  for ($iteration = $startIteration; $null-eq$terminalDecision-and$iteration -le $maximumFlightAttempts; $iteration++) {
    $failureStage = "real_center_flight_$iteration"
    $resumeThisIteration = (-not $resumeIterationCheckpoint -and $iteration -eq 1 -and $null -ne $resumeChildManifest)
    if ($resumeThisIteration) {
      $childManifest = $resumeChildManifest
      $childRunDir = Split-Path -Parent $childManifest
      $resumeManifestDocument = Get-Content -LiteralPath $childManifest -Raw | ConvertFrom-Json -AsHashtable
      $childRunId = [string]$resumeManifestDocument.run_id
      if ([string]::IsNullOrWhiteSpace($childRunId)) { throw 'Resume child manifest lacks run_id.' }
    } else {
      $childRunId = '{0}-iter-{1:D2}' -f $RunId,$iteration
      $childRunDir = Join-Path $trialArtifactRoot "runs\$childRunId"
      $childManifest = Join-Path $childRunDir 'run_manifest.json'
    }
    $finalCacheKey = $null
    $trialArguments = New-CenterTrialArguments -Voltages $current -ChildRunId $childRunId

    $solverError = $null
    if (-not $resumeThisIteration) {
      try { Invoke-CenterTrial -Arguments $trialArguments }
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
    if($staticFieldMode){
      # The controller's existing assert_trial_matches_jacobian consumes the
      # independently sealed binding and the saved-mesh/numerics family below.
      $cacheIdentity=$materialization
      $childProtectionPath=Get-ManifestOutputPath -ManifestPath $childManifest -FileName 'native_corridor_protection_renewal.json'
      $childField=Get-Content -LiteralPath $materialization -Raw|ConvertFrom-Json -AsHashtable
      if($childField.field_binding.mode-ne$staticBindingMode){throw 'Static child lacks its actual field binding.'}
      $cacheBindingPath=Join-Path $package.result_dir ('iteration_{0:D2}_cache_binding.json' -f $iteration)
      Write-RunJson -Path $cacheBindingPath -Depth 100 -Value ([ordered]@{
        schema_version=1;role='mrtof_static_field_iteration_binding';field_binding=$childField.field_binding
        trajectory_profile=$childField.trajectory_profile
      })
      $operatingCacheKey=$null
      $fieldRenewal=Update-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $capacitySession `
        -ProtectedPaths @($childField.field_binding.path)
      $capacitySession=$fieldRenewal.session
    }else{
    $cacheIdentity = Get-ManifestOutputPath -ManifestPath $childManifest -FileName 'native_corridor_runtime_family.json'
    $childProtectionPath = Get-ManifestOutputPath -ManifestPath $childManifest -FileName 'native_corridor_protection_renewal.json'
    # The parent consumes these four compact, named records.  The child has
    # already performed its own full publication validation, so rehashing every
    # child PA here would only repeat multi-GiB reads without strengthening this
    # controller's evidence binding.
    $childProjectionArgs=@($childManifest,'--require-status','success','--require-project','instrument_assembly',
      '--require-mode','oa_mr','--consumer-projection-id','mrtof_downstream_iteration_child_v1',
      '--consumed-output',$observation,'--consumed-output',$materialization,
      '--consumed-output',$cacheIdentity,'--consumed-output',$childProtectionPath)
    & $python -I -B -c 'from msplatform.execution.manifest_verification import main; from msplatform.backends.simion.native_completion import retention_api; main(retention_api=retention_api)' @childProjectionArgs
    if ($LASTEXITCODE -ne 0) { throw "Child flight manifest projection is invalid: $childManifest" }
    $cacheBindingPath = Join-Path $package.result_dir ('iteration_{0:D2}_cache_binding.json' -f $iteration)
    $cacheBindingArguments = @(
      '-m','msplatform.workflows.mr_design.downstream_workpoint',
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
    & {
      & $python -I -B @cacheBindingArguments
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
    }
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
    $expectedBinding=if($staticFieldMode){$staticBindingMode+'__four_read_only_collision_instances'}else{'native_corridor_private_fast_adjust_family__four_instances__n1'}
    if ([string]$childConfig.parameters.pa_binding_mode -ne $expectedBinding) {
      throw "Child flight did not use scoped fixed-grid response composition: $childManifest"
    }
    $decisionPath = Join-Path $package.result_dir ('iteration_{0:D2}_decision.json' -f $iteration)
    $failureStage = "decide_iteration_$iteration"
    Push-Location -LiteralPath $repoRoot
    try {
      & $python -I -B -m msplatform.workflows.mr_design.downstream_workpoint `
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
          -StatePath $recoveryStatePath -HistoryPath $historyPath -RecoveryPolicy $recoveryPolicy `
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
      $recoveryCapacity=Update-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $capacitySession
      $capacitySession=$recoveryCapacity.session
      $recoveryCapacityPath=Join-Path $package.result_dir ('capacity_protection_recovery_{0:D2}_renew.json' -f $iteration)
      Write-RunJson -Path $recoveryCapacityPath -Depth 20 -Value $recoveryCapacity
      $protectionReceipts += $recoveryCapacityPath
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
    if(Test-Path -LiteralPath $initialGroupedDecisionPath -PathType Leaf){$checkpointOutputs += $initialGroupedDecisionPath}
    if(Test-Path -LiteralPath $recoveryStatePath -PathType Leaf){$checkpointOutputs += $recoveryStatePath}
    $reconstructedCheckpointPath = Join-Path $package.result_dir 'reconstructed_checkpoint.json'
    if (Test-Path -LiteralPath $reconstructedCheckpointPath -PathType Leaf) { $checkpointOutputs += $reconstructedCheckpointPath }
    if($null-ne$nativeRuntimeSession-and(Test-Path -LiteralPath $nativeRuntimeSession.checkpoint_path)){$checkpointOutputs+=$nativeRuntimeSession.checkpoint_path}
    Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config `
      -Status checkpoint -Software @('SIMION 2020','Python 3.11','NumPy') -Outputs $checkpointOutputs
    $current = @($decision.proposed_voltages_v | ForEach-Object { [double]$_ })
  }
  if ($null -eq $terminalDecision) {
    $budget=Invoke-WorkpointControllerRequest -Python $python -RepoRoot $repoRoot -Request @{
      action='main_iteration_budget';phase='exhausted';maximum_iterations=$maximumFlightAttempts;terminal_decision=$terminalDecision
    }
    $terminalDecision=$budget.terminal_decision
  }
  } # Existing measured-Jacobian route remains for explicit initial workpoints.
  Write-RunJson -Path $lineagePath -Depth 100 -Value $lineage
  $failureStage = 'publish'
  if($staticFieldMode-and$terminalDecision.terminal_reason-eq'success'){
    $bestPhysicalHandoffPath=Join-Path $package.result_dir 'best_physical_workpoint_handoff.json'
    & {
      & $python -I -B -m msplatform.workflows.mr_design.downstream_workpoint `
        --select-best-physical-workpoint --history $historyPath --output $bestPhysicalHandoffPath | Out-Host
      if($LASTEXITCODE-ne0){throw 'Could not select the complete static physical workpoint.'}
    }
    $terminalDecision.best_physical_workpoint_handoff=$bestPhysicalHandoffPath
  }
  if($null-ne$nativeRuntimeSession){
    if($terminalDecision.terminal_reason-ne'success'){
      Save-NativeWorkflowCheckpoint -Reason ([string]$terminalDecision.terminal_reason) `
        -WorkflowOutcome 'workpoint_incomplete_downstream_blocked' -FinalDecision $terminalDecision
      $terminalized=$true
      Write-Host "MRTOF_DOWNSTREAM_AUTO_WORKPOINT=$($terminalDecision.terminal_reason) CHECKPOINT=workpoint_incomplete_downstream_blocked RUN_ID=$RunId"
      $hostOutcome='success'
      return
    }
    $bestPhysicalHandoffPath=Join-Path $package.result_dir 'best_physical_workpoint_handoff.json'
    Push-Location -LiteralPath $repoRoot
    try {
      & $python -I -B -m msplatform.workflows.mr_design.downstream_workpoint `
        --select-best-physical-workpoint --history $historyPath --output $bestPhysicalHandoffPath | Out-Host
      if($LASTEXITCODE-ne0){throw 'Could not select the best complete physical workpoint for downstream screening.'}
    } finally { Pop-Location }
    $terminalDecision.best_physical_workpoint_handoff=$bestPhysicalHandoffPath
    $nativeOutcome='workpoint_complete_downstream_pending'
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
        CompositionPlanPath=$CompositionPlanPath
        RunId=$RunId+'-bunch'
        WorkspaceRoot=$workspaceRoot
        ArtifactRoot=$artifactWorkspaceRoot
        PythonExe=$python
      }
      if($SimionExe){$screeningArguments.SimionExe=$SimionExe}
      & $bunchScreeningRunner @screeningArguments
    }
    $hostOutcome='success'
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
  if(Test-Path -LiteralPath $initialGroupedDecisionPath -PathType Leaf){$outputs += $initialGroupedDecisionPath}
  foreach($name in @('workpoint_bootstrap.json','iteration_recovery_state.json','best_physical_workpoint_handoff.json')){
    $path=Join-Path $package.result_dir $name
    if(Test-Path -LiteralPath $path -PathType Leaf){$outputs+=$path}
  }
  Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config `
    -Status success -Software @('SIMION 2020','Python 3.11','NumPy') -Outputs $outputs
  $terminalized = $true
  $hostOutcome = 'success'
  Write-Host "MRTOF_DOWNSTREAM_AUTO_WORKPOINT=$($terminalDecision.terminal_reason) RUN_ID=$RunId"
} catch {
  Write-Host "MRTOF_WORKPOINT_FAILURE stage=$failureStage reason=$($_.Exception.Message)"
  if($staticFieldMode-or($null-ne$nativeRuntimeSession-and$nativeRuntimeSession.directory-and(Test-Path -LiteralPath $nativeRuntimeSession.directory))){
    $caughtDecisionVariable=Get-Variable terminalDecision -ErrorAction SilentlyContinue
    $caughtDecision=if($null-ne$caughtDecisionVariable){$caughtDecisionVariable.Value}else{$null}
    Save-NativeWorkflowCheckpoint -Reason $_.Exception.Message -FinalDecision $caughtDecision
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
  if(-not$terminalized-and($staticFieldMode-or($null-ne$nativeRuntimeSession-and$nativeRuntimeSession.directory-and(Test-Path -LiteralPath $nativeRuntimeSession.directory)))){
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
  if($null-ne$resourceLease){
    $topLevelLease=-not[bool]$resourceLease.inherited
    Exit-HostResourceStage -Lease $resourceLease
    if($topLevelLease){Invoke-HostExecutionCompletionNotification -Outcome $hostOutcome -RunId $RunId}
  }
}

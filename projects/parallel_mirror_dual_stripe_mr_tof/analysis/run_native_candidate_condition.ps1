[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$ConditionPath,
  [Parameter(Mandatory)][string]$ContextPath,
  [Parameter(Mandatory)][string]$RunId,
  [string]$ProviderReusePath='',
  [string]$StripeReuseRunManifest='',
  [string]$ContinuationReuseRunManifest='',
  [string]$CandidateReuseRunManifest='',
  [string]$QualifiedWorkpointRunPath='',
  [string]$AcceleratorRuntimeCheckpoint='',
  [string]$WorkpointResumeInitialManifest='',
  [string]$WorkpointResumeParentCheckpoint='',
  [string]$WorkpointResumeSuccessfulChildManifest='',
  [string]$PythonExe='',
  [string]$SimionExe=''
)

# Thin single-condition orchestration.  Physics and resource scheduling remain
# in the existing Stripe, SIMION, coverage, continuation, N=1, and Candidate runners.
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$project='parallel_mirror_dual_stripe_mr_tof'
$repoRoot=(Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$workspaceRoot=Split-Path -Parent $repoRoot
$artifactProject=Join-Path $workspaceRoot "artifacts\projects\$project"
$artifactRuns=Join-Path $artifactProject 'runs'
$oaArtifactRuns=Join-Path $workspaceRoot 'artifacts\projects\orthogonal_accelerator\runs'
$python=if($PythonExe){[IO.Path]::GetFullPath($PythonExe)}else{Join-Path $repoRoot '.venv\Scripts\python.exe'}
$conditionSource=(Resolve-Path -LiteralPath $ConditionPath).Path
$contextSource=(Resolve-Path -LiteralPath $ContextPath).Path
$contextDirectory=Split-Path -Parent $contextSource

. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')

function Resolve-ContextPath {
  param([Parameter(Mandatory)][string]$Value)
  $candidate=if([IO.Path]::IsPathRooted($Value)){$Value}else{Join-Path $contextDirectory $Value}
  return (Resolve-Path -LiteralPath $candidate).Path
}

function Copy-ArgumentMap {
  param([Parameter(Mandatory)]$Source,[Parameter(Mandatory)][string[]]$Forbidden)
  if($Source-isnot[Collections.IDictionary]){throw 'Condition context argument map is invalid.'}
  $target=@{}
  foreach($entry in $Source.GetEnumerator()){
    if([string]$entry.Key-in$Forbidden){throw "Condition context may not override orchestrator argument: $($entry.Key)"}
    $target[[string]$entry.Key]=$entry.Value
  }
  return $target
}

function Get-RunManifest {
  param([Parameter(Mandatory)][string]$ChildRunId)
  $path=Join-Path (Join-Path $artifactRuns $ChildRunId) 'run_manifest.json'
  if(-not(Test-Path -LiteralPath $path -PathType Leaf)){throw "Child run manifest is missing: $path"}
  return $path
}

function Assert-ReusedStripeAndContinuation {
  param(
    [Parameter(Mandatory)][string]$StripeManifestPath,
    [Parameter(Mandatory)][string]$ContinuationManifestPath,
    [Parameter(Mandatory)][double]$ExpectedK,
    [Parameter(Mandatory)][double]$ExpectedAcceleratorY
  )
  $stripePath=(Resolve-Path -LiteralPath $StripeManifestPath).Path
  $stripe=Get-Content -LiteralPath $stripePath -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  if($stripe.project-ne$project-or$stripe.mode-ne'dual_stripe_fixed_grid_native_downstream_seed'-or
     $stripe.status-ne'success'-or[string]::IsNullOrWhiteSpace([string]$stripe.run_id)){
    throw 'Reused Stripe manifest is not a successful fixed-grid operating seed.'
  }
  $continuationPath=(Resolve-Path -LiteralPath $ContinuationManifestPath).Path
  $continuation=Get-Content -LiteralPath $continuationPath -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  if($continuation.project-ne$project-or$continuation.mode-ne'two_prism_segmented_voltage_branch_continuation'-or
     $continuation.status-ne'success'){
    throw 'Reused continuation manifest is not a successful segmented continuation.'
  }
  $summaryPath=Join-Path (Split-Path -Parent $continuationPath) 'summary.json'
  if(-not(Test-Path -LiteralPath $summaryPath -PathType Leaf)){throw 'Reused continuation summary is missing.'}
  $summary=Get-Content -LiteralPath $summaryPath -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  $pair=$summary.inputs.accelerator_exit_source_receipt.pair_identity
  if($summary.role-ne'mrtof_two_prism_segmented_voltage_branch_continuation'-or
     $summary.status-ne'continuation_complete'-or
     $summary.continuation.joint_root_tolerance_reached-ne$true-or
     @($summary.continuation.joint_root_candidates).Count-ne1-or
     $pair-isnot[Collections.IDictionary]-or
     [double]$pair.target_drift_period_ratio-ne$ExpectedK-or
     [double]$pair.accelerator_y_anchor_mm-ne$ExpectedAcceleratorY-or
     [string]$summary.inputs.stripe_seed.source_stripe_run_id-ne[string]$stripe.run_id){
    throw 'Reused Stripe and continuation do not form the requested qualified K/y pair.'
  }
  return [ordered]@{stripe_manifest=$stripePath;continuation_manifest=$continuationPath}
}

function Assert-ReusedCandidate {
  param(
    [Parameter(Mandatory)][string]$CandidateManifestPath,
    [Parameter(Mandatory)][double]$ExpectedK,
    [Parameter(Mandatory)][double]$ExpectedAcceleratorY,
    [Parameter(Mandatory)][string]$ExpectedProviderReceipt,
    [Parameter(Mandatory)][double]$ExpectedSourceYOffset
  )
  $manifestPath=(Resolve-Path -LiteralPath $CandidateManifestPath).Path
  $manifest=Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  if($manifest.project-ne$project-or$manifest.mode-ne'native_candidate_end_to_end_chain'-or
     $manifest.status-ne'success'){
    throw 'Reused Candidate manifest is not a successful native Candidate chain.'
  }
  $summaryPath=Join-Path (Split-Path -Parent $manifestPath) 'summary.json'
  if(-not(Test-Path -LiteralPath $summaryPath -PathType Leaf)){throw 'Reused Candidate summary is missing.'}
  $summary=Get-Content -LiteralPath $summaryPath -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  $outcome=[string]$summary.workflow_outcome
  if($summary.role-ne'mrtof_native_candidate_end_to_end_chain_summary'-or$summary.status-ne'success'-or
     ($outcome-ne'within_tolerance'-and$outcome-notlike'warning_*__continue_parameter_scan')){
    throw 'Reused Candidate summary is not a supported terminal outcome.'
  }
  $workpointManifestPath=(Resolve-Path -LiteralPath ([string]$summary.workpoint_run_manifest)).Path
  $workpointManifest=Get-Content -LiteralPath $workpointManifestPath -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  if($workpointManifest.project-ne$project-or$workpointManifest.mode-ne'downstream_fixed_grid_workpoint_iteration'-or
     $workpointManifest.status-notin@('checkpoint','success')){
    throw 'Reused Candidate workpoint manifest is invalid.'
  }
  $workpointRun=Split-Path -Parent $workpointManifestPath
  $workpointConfig=Get-Content -LiteralPath (Join-Path $workpointRun 'run_config.json') -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  $workpointContractPath=(Resolve-Path -LiteralPath ([string]$workpointConfig.inputs.contract)).Path
  $workpointContract=Get-Content -LiteralPath $workpointContractPath -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  $recovery=$workpointConfig.parameters.native_recovery_problem
  if([double]$workpointContract.nominal.target_drift_period_ratio-ne$ExpectedK-or
     [double]$workpointContract.accelerator.focus_y_anchor.project_y_mm-ne$ExpectedAcceleratorY){
    throw 'Reused Candidate K or accelerator_y differs from the requested condition.'
  }
  $providerReceipt=(Resolve-Path -LiteralPath ([string]$recovery.accelerator_provider_receipt)).Path
  $expectedReceipt=(Resolve-Path -LiteralPath $ExpectedProviderReceipt).Path
  if(-not[string]::Equals($providerReceipt,$expectedReceipt,[StringComparison]::OrdinalIgnoreCase)-or
     [math]::Abs([double]$recovery.source_y_offset_mm-$ExpectedSourceYOffset)-gt1e-12){
    throw 'Reused Candidate provider receipt or source y offset differs from the requested condition.'
  }
  return [ordered]@{
    manifest=$manifestPath;summary=$summary;workpoint_manifest=$workpointManifestPath
  }
}

function Complete-PhysicalConditionWarning {
  param(
    [Parameter(Mandatory)]$Package,
    [Parameter(Mandatory)][string]$Outcome,
    [Parameter(Mandatory)][string]$Stage,
    [Parameter(Mandatory)][string]$Reason,
    [Parameter(Mandatory)]$Provider,
    [Parameter(Mandatory)][string]$ProviderManifest,
    [Parameter(Mandatory)][string]$ProviderReceipt,
    [Parameter(Mandatory)][double]$SlowEnergy,
    [Parameter(Mandatory)][double]$SourceYOffset,
    [Parameter(Mandatory)][double]$K,
    [Parameter(Mandatory)][double]$AcceleratorY,
    [Parameter(Mandatory)]$ChildRunManifests
  )
  if($Outcome-notlike'warning_*__continue_parameter_scan'){
    throw 'Physical condition warning outcome must request the next campaign condition.'
  }
  Write-RunJson -Path $Package.summary -Depth 20 -Value ([ordered]@{
    schema_version=1;role='mrtof_native_candidate_single_condition_summary';status='success'
    workflow_outcome=$Outcome;K=$K;accelerator_y_mm=$AcceleratorY
    condition_disposition='physical_nonqualification'
    physical_nonqualification=[ordered]@{stage=$Stage;reason=$Reason}
    provider_run_manifest=$ProviderManifest;provider_runtime_receipt=$ProviderReceipt
    provider_release_slow_energy_per_charge_v=$SlowEnergy
    provider_required_source_y_offset_mm=$SourceYOffset
    provider_exit_energy_acceptance=$Provider.exit_energy_acceptance
    child_run_manifests=$ChildRunManifests
  })
  $retention=Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $Package.run_config
  Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $Package.run_config -Status success `
    -Software @('SIMION 2020','Python 3.11') -Outputs @($Package.summary,$retention)
}

function Assert-ProviderAuthority {
  param(
    [Parameter(Mandatory)][string]$ManifestPath,
    [Parameter(Mandatory)][string]$ReceiptPath,
    [Parameter(Mandatory)][double]$ExpectedSlowEnergyPerChargeV,
    [Parameter(Mandatory)]$ExpectedRelease
  )
  $manifest=Get-Content -LiteralPath $ManifestPath -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  if($manifest.project-ne'orthogonal_accelerator'-or$manifest.mode-ne'component_focus_workflow'-or
     $manifest.status-ne'success'-or[string]::IsNullOrWhiteSpace([string]$manifest.run_id)){
    throw 'OA provider manifest is not a successful component-focus workflow.'
  }
  $receipt=Get-Content -LiteralPath $ReceiptPath -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  $projection=$receipt.mrtof_projection;$accepted=$projection.accepted_release
  $energyAcceptance=$projection.provider_exit_energy_acceptance
  $transverseTolerance=[double]$energyAcceptance.tolerances.maximum_exit_transverse_energy_error_per_charge_v
  $velocityBiasTolerance=[double]$energyAcceptance.tolerances.maximum_exit_transverse_velocity_bias_mm_per_us
  if($receipt.role-ne'orthogonal_accelerator_mrtof_runtime_receipt'-or
     $receipt.status-ne'published_standalone_response_bank'-or$projection-isnot[Collections.IDictionary]-or
     $accepted-isnot[Collections.IDictionary]-or$energyAcceptance-isnot[Collections.IDictionary]-or
     $energyAcceptance.passed-ne$true-or-not[double]::IsFinite($transverseTolerance)-or
     $transverseTolerance-lt0-or-not[double]::IsFinite($velocityBiasTolerance)-or
     $velocityBiasTolerance-lt0-or$energyAcceptance.center_particle.transverse_energy_passed-ne$true-or
     $energyAcceptance.center_particle.transverse_velocity_bias_passed-ne$true-or
     $energyAcceptance.cohort.transverse_energy_passed-ne$true-or
     $energyAcceptance.cohort.transverse_velocity_bias_passed-ne$true){
    throw 'OA provider runtime receipt lacks the accepted MR-TOF release authority.'
  }
  $slow=[double]$accepted.slow_energy_center_per_charge_v
  $width=[double]$accepted.slow_energy_full_width_per_charge_v
  $mass=[double]$accepted.mass_th;$charge=[int]$accepted.charge_e
  $direction=@($accepted.nominal_direction)
  $angularWidth=[double]$accepted.angular_full_width_deg
  $acceptedGeometry=$accepted.geometry
  $offset=[double]$projection.required_source_y_offset_from_accelerator_axis_mm
  $expectedCharge=[int]$ExpectedRelease.species.charge_state
  $expectedWidth=[double]$ExpectedRelease.sampling.kinetic_energy.full_width_ev/[math]::Abs($expectedCharge)
  $expectedMass=[double]$ExpectedRelease.species.mass_amu
  $expectedDirection=@($ExpectedRelease.sampling.nominal_direction)
  $expectedAngularWidth=[double]$ExpectedRelease.sampling.angular_full_width_deg
  $expectedCenter=@($ExpectedRelease.geometry.center_mm)
  if(-not[double]::IsFinite($slow)-or[math]::Abs($slow-$ExpectedSlowEnergyPerChargeV)-gt1e-12-or
     -not[double]::IsFinite($width)-or$width-lt0-or-not[double]::IsFinite($mass)-or$mass-le0-or
     $charge-ne$expectedCharge-or[math]::Abs($width-$expectedWidth)-gt1e-12-or
     [math]::Abs($mass-$expectedMass)-gt1e-12-or$direction.Count-ne3-or
     $expectedDirection.Count-ne3-or-not[double]::IsFinite($angularWidth)-or
     [math]::Abs($angularWidth-$expectedAngularWidth)-gt1e-12-or$angularWidth-ne0-or
     $acceptedGeometry.shape-ne'cylinder'-or$acceptedGeometry.axis-ne'y'-or
     [double]$acceptedGeometry.radius_mm-ne0.5-or[double]$acceptedGeometry.height_mm-ne1.0-or
     @($acceptedGeometry.center_mm).Count-ne3-or$expectedCenter.Count-ne3-or
     -not[double]::IsFinite($offset)){
    throw 'OA provider accepted release differs from the exact-K Stripe seed.'
  }
  for($index=0;$index-lt3;$index++){
    if(-not[double]::IsFinite([double]$direction[$index])-or
       [math]::Abs([double]$direction[$index]-[double]$expectedDirection[$index])-gt1e-12){
      throw 'OA provider direction differs from the run-local release spec.'
    }
    if([math]::Abs([double]$acceptedGeometry.center_mm[$index]-[double]$expectedCenter[$index])-gt1e-12){
      throw 'OA provider geometry differs from the run-local release spec.'
    }
  }
  return [ordered]@{manifest=$manifest;receipt=$receipt;slow_energy=$slow;source_y_offset=$offset
    exit_energy_acceptance=$energyAcceptance}
}

if($RunId-notmatch'^(?<stamp>\d{8}_\d{6})__'){throw 'RunId must begin with YYYYMMDD_HHMMSS__.'}
$stamp=[string]$Matches.stamp
$condition=Get-Content -LiteralPath $conditionSource -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
$context=Get-Content -LiteralPath $contextSource -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
if($condition.schema_version-ne1-or$condition.role-ne'mrtof_native_candidate_campaign_condition'){
  throw 'Condition identity is invalid.'
}
if($context.schema_version-ne1-or$context.role-ne'mrtof_native_candidate_condition_context'){
  throw 'Condition context identity is invalid.'
}
$reuseArguments=@(@($StripeReuseRunManifest,$ContinuationReuseRunManifest)|Where-Object{-not[string]::IsNullOrWhiteSpace($_)})
if($reuseArguments.Count-ne0-and$reuseArguments.Count-ne2){
  throw 'StripeReuseRunManifest and ContinuationReuseRunManifest must be supplied together.'
}
if($CandidateReuseRunManifest-and($reuseArguments.Count-ne2-or-not$ProviderReusePath)){
  throw 'CandidateReuseRunManifest requires Stripe/Continuation reuse and ProviderReusePath.'
}
$workpointResumeArguments=@(@(
  $WorkpointResumeInitialManifest,$WorkpointResumeParentCheckpoint,$WorkpointResumeSuccessfulChildManifest
)|Where-Object{-not[string]::IsNullOrWhiteSpace($_)})
if($workpointResumeArguments.Count-ne0-and$workpointResumeArguments.Count-ne3){
  throw 'Workpoint resume requires initial manifest, parent checkpoint, and successful child together.'
}
if($workpointResumeArguments.Count-eq3-and($reuseArguments.Count-ne2-or$CandidateReuseRunManifest)){
  throw 'Workpoint resume requires Stripe/Continuation reuse and cannot reuse a completed Candidate.'
}
if($QualifiedWorkpointRunPath-and(
   $reuseArguments.Count-ne2-or$CandidateReuseRunManifest-or$workpointResumeArguments.Count-ne0)){
  throw 'Qualified workpoint reuse requires Stripe/Continuation reuse and excludes Candidate or checkpoint resume.'
}
$k=[double]$condition.K;$acceleratorY=[double]$condition.accelerator_y
if(-not[double]::IsFinite($k)-or-not[double]::IsFinite($acceleratorY)){throw 'Condition K and accelerator y must be finite.'}

$baseContract=Resolve-ContextPath -Value ([string]$context.contract_path)
$fixedMirrorManifest=Resolve-ContextPath -Value ([string]$context.fixed_grid_mirror_run_manifest)
if([IO.Path]::GetFileName($fixedMirrorManifest)-ne'run_manifest.json'){
  throw 'fixed_grid_mirror_run_manifest must name run_manifest.json.'
}
$mirrorRun=Split-Path -Parent $fixedMirrorManifest
$mirrorPeriod=Join-Path $mirrorRun 'results\mirror_real_field_period_comparison.json'
if(-not(Test-Path -LiteralPath $mirrorPeriod -PathType Leaf)){throw 'Fixed-grid mirror period evidence is missing.'}
$geometryRun=Resolve-ContextPath -Value ([string]$context.geometry_review_run_path)
$nativeBank=Resolve-ContextPath -Value ([string]$context.native_corridor_bank_run_path)
$nativeBundle=Resolve-ContextPath -Value ([string]$context.native_system_runtime_bundle_path)
$nativeRuntimeCheckpoint=if([string]::IsNullOrWhiteSpace([string]$context.native_runtime_checkpoint_path)){''}else{Resolve-ContextPath -Value ([string]$context.native_runtime_checkpoint_path)}
$sourceDefinition=Resolve-ContextPath -Value ([string]$context.source_definition_path)
$oaBaseReleaseSpec=Resolve-ContextPath -Value ([string]$context.oa_base_release_spec_path)
$oaRequest=Resolve-ContextPath -Value ([string]$context.oa_request_path)

$package=New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactProject `
  -RunId $RunId -Project $project -Mode 'native_candidate_single_condition' `
  -Software @('SIMION 2020','Python 3.11') -RetentionContractEnabled -RetentionClass compact `
  -CapacityLedgerLifecycleEnabled
$terminalized=$false;$failureStage='freeze_inputs'
try{
  $frozenCondition=Copy-VerifiedRunInput -Source $conditionSource -Destination (Join-Path $package.input_dir 'condition.json')
  $frozenContext=Copy-VerifiedRunInput -Source $contextSource -Destination (Join-Path $package.input_dir 'context.json')
  $conditionContract=Copy-VerifiedRunInput -Source $baseContract -Destination (Join-Path $package.input_dir 'condition_contract.json')
  $contract=Get-Content -LiteralPath $conditionContract -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  $contract.nominal.target_drift_period_ratio=$k
  $contract.accelerator.focus_y_anchor.project_y_mm=$acceleratorY
  Write-RunJson -Path $conditionContract -Depth 100 -Value $contract
  $runConfig=Get-Content -LiteralPath $package.run_config -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  $runConfig.inputs=[ordered]@{condition=$frozenCondition;context=$frozenContext;condition_contract=$conditionContract}
  $runConfig.parameters=[ordered]@{K=$k;accelerator_y_mm=$acceleratorY;execution='strict_serial_existing_runners'}
  Write-RunJson -Path $package.run_config -Depth 12 -Value $runConfig

  $reusedPair=$null
  if($reuseArguments.Count-eq2){
    $failureStage='reuse_stripe_continuation'
    $reusedPair=Assert-ReusedStripeAndContinuation -StripeManifestPath $StripeReuseRunManifest `
      -ContinuationManifestPath $ContinuationReuseRunManifest -ExpectedK $k -ExpectedAcceleratorY $acceleratorY
    $stripeManifest=[string]$reusedPair.stripe_manifest
  }else{
    $failureStage='fixed_grid_stripe_seed'
    $stripeId=$stamp+'__analysis__python__mrtof-condition-stripe'
    $stripeArgs=@{FixedGridRunManifest=$fixedMirrorManifest;ContractPath=$conditionContract;RunId=$stripeId}
    if($PythonExe){$stripeArgs.PythonExe=$PythonExe}
    & (Join-Path $PSScriptRoot 'run_dual_stripe_operating_seed.ps1') @stripeArgs|Out-Host
    $stripeManifest=Get-RunManifest -ChildRunId $stripeId
  }
  $stripeRun=Split-Path -Parent $stripeManifest

  $stripeSummary=Get-Content -LiteralPath (Join-Path $stripeRun 'summary.json') -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  $slowEnergy=[double]$stripeSummary.selected_seed.selected_exact_K_slow_energy_per_charge_v
  if(-not[double]::IsFinite($slowEnergy)-or$slowEnergy-le0){throw 'Stripe seed lacks a positive exact-K slow release energy.'}

  $failureStage='k_specific_oa_provider'
  $releaseSpec=Copy-VerifiedRunInput -Source $oaBaseReleaseSpec -Destination (Join-Path $package.input_dir 'oa_release_spec.json')
  $release=Get-Content -LiteralPath $releaseSpec -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  if($release.role-ne'repository_ion_release'-or$release.sampling.kinetic_energy-isnot[Collections.IDictionary]){
    throw 'OA base release spec is not a repository ion release.'
  }
  if($release.geometry.shape-ne'cylinder'-or$release.geometry.axis-ne'y'-or
     [double]$release.geometry.radius_mm-ne0.5-or[double]$release.geometry.height_mm-ne1.0){
    throw 'OA base release must be the shared y-height 1 mm, x-z radius 0.5 mm cylinder.'
  }
  $charge=[int]$release.species.charge_state
  if($charge-eq0){throw 'OA base release spec has zero charge.'}
  $release.sampling.kinetic_energy.center_ev=$slowEnergy*[math]::Abs($charge)
  $release.sampling.nominal_direction=@(0.0,1.0,0.0)
  $release.sampling.angular_full_width_deg=0.0
  Write-RunJson -Path $releaseSpec -Depth 30 -Value $release
  $frozenOaRequest=Copy-VerifiedRunInput -Source $oaRequest -Destination (Join-Path $package.input_dir 'oa_request.json')

  $acceleratorReceipt=$null;$providerManifest=$null
  if($ProviderReusePath){
    $reusePath=(Resolve-Path -LiteralPath $ProviderReusePath).Path
    $reuse=Get-Content -LiteralPath $reusePath -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
    if($reuse.role-ne'mrtof_native_candidate_oa_provider_cache_entry'-or[double]$reuse.K-ne$k){
      throw 'OA provider reuse entry belongs to a different K.'
    }
    $providerManifest=(Resolve-Path -LiteralPath ([string]$reuse.run_manifest)).Path
    $acceleratorReceipt=(Resolve-Path -LiteralPath ([string]$reuse.runtime_receipt)).Path
  }else{
    $providerId=$stamp+'__sim__simion__mrtof-condition-oa-provider'
    $providerArgs=@{RunId=$providerId;RequestPath=$frozenOaRequest;ReleaseSpecPath=$releaseSpec}
    if($AcceleratorRuntimeCheckpoint){$providerArgs.RuntimeCheckpointPath=(Resolve-Path -LiteralPath $AcceleratorRuntimeCheckpoint).Path}
    if($SimionExe){$providerArgs.SimionExe=$SimionExe}
    & (Join-Path $repoRoot 'projects\orthogonal_accelerator\simion\run_component_focus_workflow.ps1') @providerArgs|Out-Host
    $providerRun=Join-Path $oaArtifactRuns $providerId
    $providerManifest=Join-Path $providerRun 'run_manifest.json'
    $acceleratorReceipt=Join-Path $providerRun 'results\mrtof_runtime_receipt.json'
  }
  $provider=Assert-ProviderAuthority -ManifestPath $providerManifest -ReceiptPath $acceleratorReceipt `
    -ExpectedSlowEnergyPerChargeV $slowEnergy -ExpectedRelease $release
  $sourceYOffset=[double]$provider.source_y_offset

  # Keep the already published MR fallback/corridor/detector and replace only
  # the standalone accelerator binding.  This writes one small identity file;
  # it does not copy, build, or Refine a PA.
  $failureStage='bind_provider_accelerator'
  $bankPublication=Get-Content -LiteralPath (Join-Path $nativeBank 'results\pa_family_cache_publication.json') -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  $nativeIdentityPath=Join-Path ([IO.Path]::GetTempPath()) ('mrtof_native_provider_identity_'+[guid]::NewGuid().ToString('N')+'.json')
  $providerBoundBundle=Join-Path $package.input_dir 'native_system_runtime_bundle.json'
  try{
    Write-RunJson -Path $nativeIdentityPath -Depth 5 -Value ([ordered]@{
      schema_version=1;role='mrtof_private_native_corridor_family';status='prepared'
      response_refine_performed=$false;published_native_members_opened=$false;controller_refine='solutions={0}'
      cache_key=[string]$bankPublication.cache_key;generation_sha256=[string]$bankPublication.generation_sha256
    })
    Push-Location $repoRoot
    try{
      & $python -m projects.parallel_mirror_dual_stripe_mr_tof.analysis.native_system_runtime rebind-accelerator `
        --native-corridor-runtime-receipt $nativeIdentityPath --base-bundle $nativeBundle `
        --accelerator-provider-receipt $acceleratorReceipt --bundle-output $providerBoundBundle
      if($LASTEXITCODE-ne0){throw 'OA provider accelerator binding failed.'}
    }finally{Pop-Location}
  }finally{Remove-Item -LiteralPath $nativeIdentityPath -Force -ErrorAction SilentlyContinue}
  $nativeBundle=$providerBoundBundle

  $conditionSourceDefinition=Copy-VerifiedRunInput -Source $sourceDefinition -Destination (Join-Path $package.input_dir 'condition_source_definition.json')
  $sourceDefinitionData=Get-Content -LiteralPath $conditionSourceDefinition -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  $sourceDefinitionData.source_y_offset_mm=$sourceYOffset
  $sourceDefinitionData.kinetic_energy_center_ev=$slowEnergy*[math]::Abs($charge)
  $sourceDefinitionData.nominal_direction_workbench=@(0.0,1.0,0.0)
  $sourceDefinitionData.angular_full_width_deg=0.0
  Write-RunJson -Path $conditionSourceDefinition -Depth 30 -Value $sourceDefinitionData
  $runConfig=Get-Content -LiteralPath $package.run_config -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  $runConfig.inputs.oa_release_spec=$releaseSpec;$runConfig.inputs.oa_request=$frozenOaRequest
  $runConfig.inputs.condition_source_definition=$conditionSourceDefinition
  $runConfig.parameters.accelerator_source_y_offset_mm=$sourceYOffset
  $runConfig.parameters.accelerator_source_y_offset_authority='provider_receipt.mrtof_projection.required_source_y_offset_from_accelerator_axis_mm'
  Write-RunJson -Path $package.run_config -Depth 12 -Value $runConfig

  $safeExitManifest=$null;$coverageManifest=$null
  if($null-ne$reusedPair){
    $continuationManifest=[string]$reusedPair.continuation_manifest
  }else{
    $failureStage='accelerator_safe_exit'
    $safeExitId=$stamp+'__sim__simion__mrtof-condition-safe-exit'
    $safeExitArgs=@{
      GeometryReviewRunPath=$geometryRun;MirrorRunPath=$mirrorRun;StripeRunPath=$stripeRun
      AcceleratorProviderReceiptPath=$acceleratorReceipt;NativeCorridorBankRunPath=$nativeBank
      NativeSystemRuntimeBundlePath=$nativeBundle
      Prism1VoltageV=[double]$context.accelerator_safe_exit.prism_1_placeholder_v
      Prism2VoltageV=[double]$context.accelerator_safe_exit.prism_2_placeholder_v
      AcceleratorSafeExitOnly=$true;AcceleratorSourceYOffsetMm=$sourceYOffset
      AcceleratorYAnchorMm=$acceleratorY;ContractPath=$conditionContract;RunId=$safeExitId
    }
    if($nativeRuntimeCheckpoint){$safeExitArgs.NativeRuntimeCheckpoint=$nativeRuntimeCheckpoint}
    if($PythonExe){$safeExitArgs.PythonExe=$PythonExe};if($SimionExe){$safeExitArgs.SimionExe=$SimionExe}
    & (Join-Path $PSScriptRoot '..\simion\run_two_prism_trial.ps1') @safeExitArgs|Out-Host
    $safeExitManifest=Get-RunManifest -ChildRunId $safeExitId

    $failureStage='pair_specific_coverage'
    $coverageId=$stamp+'__analysis__python__mrtof-condition-prism-coverage'
    $coverageArgs=Copy-ArgumentMap -Source $context.coverage_arguments -Forbidden @(
      'ExactKRunManifest','StripeSeedRunManifest','FixedMirrorStripeRunManifest','AcceleratorExitRunManifest',
      'ContractPath','RunId','PythonExe')
    $coverageArgs.FixedMirrorStripeRunManifest=$stripeManifest
    $coverageArgs.AcceleratorExitRunManifest=$safeExitManifest
    $coverageArgs.ContractPath=$conditionContract;$coverageArgs.RunId=$coverageId
    if($PythonExe){$coverageArgs.PythonExe=$PythonExe}
    & (Join-Path $PSScriptRoot 'run_two_prism_segmented_coverage.ps1') @coverageArgs|Out-Host
    $coverageManifest=Get-RunManifest -ChildRunId $coverageId

    $failureStage='pair_specific_continuation'
    $continuationId=$stamp+'__analysis__python__mrtof-condition-prism-continuation'
    $continuationArgs=Copy-ArgumentMap -Source $context.continuation_arguments -Forbidden @(
      'CoverageRunManifest','ExpectedTopologySignatureSha256','SolveMode','InitialP1V','InitialP2LowerV','InitialP2UpperV',
      'P1MinimumV','P1MaximumV','P2MinimumV','P2MaximumV','RunId','PythonExe')
    $continuationArgs.CoverageRunManifest=$coverageManifest
    $continuationArgs.RunId=$continuationId;if($PythonExe){$continuationArgs.PythonExe=$PythonExe}
    & (Join-Path $PSScriptRoot 'run_two_prism_segmented_continuation.ps1') @continuationArgs|Out-Host
    $continuationManifest=Get-RunManifest -ChildRunId $continuationId
  }
  $continuationSummary=Get-Content -LiteralPath (Join-Path (Split-Path -Parent $continuationManifest) 'summary.json') -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  if($continuationSummary.role-ne'mrtof_two_prism_segmented_voltage_branch_continuation'-or
     $continuationSummary.status-ne'continuation_complete'-or
     $continuationSummary.continuation-isnot[Collections.IDictionary]-or
     $continuationSummary.continuation.joint_root_tolerance_reached-isnot[bool]){
    throw 'Continuation child did not publish a supported qualification result.'
  }
  $continuationCandidates=@($continuationSummary.continuation.joint_root_candidates)
  $continuationQualified=[bool]$continuationSummary.continuation.joint_root_tolerance_reached
  if(($continuationQualified-and$continuationCandidates.Count-ne1)-or
     (-not$continuationQualified-and$continuationCandidates.Count-ne0)){
    throw 'Continuation child root qualification is internally inconsistent.'
  }
  if(-not$continuationQualified){
    $failureStage='publish_physical_nonqualification'
    Complete-PhysicalConditionWarning -Package $package `
      -Outcome 'warning_prism_continuation_not_qualified__continue_parameter_scan' `
      -Stage 'pair_specific_continuation' -Reason 'Continuation completed without a tolerance-qualified joint prism root.' `
      -Provider $provider -ProviderManifest $providerManifest -ProviderReceipt $acceleratorReceipt `
      -SlowEnergy $slowEnergy -SourceYOffset $sourceYOffset -K $k -AcceleratorY $acceleratorY `
      -ChildRunManifests ([ordered]@{stripe=$stripeManifest;accelerator_safe_exit=$safeExitManifest;coverage=$coverageManifest;continuation=$continuationManifest})
    $terminalized=$true
    return
  }

  if($CandidateReuseRunManifest){
    $failureStage='reuse_native_candidate'
    $reusedCandidate=Assert-ReusedCandidate -CandidateManifestPath $CandidateReuseRunManifest `
      -ExpectedK $k -ExpectedAcceleratorY $acceleratorY -ExpectedProviderReceipt $acceleratorReceipt `
      -ExpectedSourceYOffset $sourceYOffset
    $candidateManifest=[string]$reusedCandidate.manifest
    $candidateSummary=$reusedCandidate.summary
    $workpointManifest=[string]$reusedCandidate.workpoint_manifest
  }else{
    if($QualifiedWorkpointRunPath){
      $failureStage='reuse_n1_workpoint'
      $workpointRun=(Resolve-Path -LiteralPath $QualifiedWorkpointRunPath).Path
      $workpointManifest=Join-Path $workpointRun 'run_manifest.json'
      $workpointManifestData=Get-Content -LiteralPath $workpointManifest -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
      $workpointContractPath=Join-Path $workpointRun 'inputs\contract.json'
      $workpointHandoffPath=Join-Path $workpointRun 'results\best_physical_workpoint_handoff.json'
      $workpointContract=Get-Content -LiteralPath $workpointContractPath -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
      $workpointHandoff=Get-Content -LiteralPath $workpointHandoffPath -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
      if($workpointManifestData.project-ne$project-or
         $workpointManifestData.mode-ne'downstream_fixed_grid_workpoint_iteration'-or
         $workpointManifestData.status-ne'checkpoint'-or
         [double]$workpointContract.nominal.target_drift_period_ratio-ne$k-or
         [double]$workpointContract.accelerator.focus_y_anchor.project_y_mm-ne$acceleratorY-or
         $workpointHandoff.role-ne'mrtof_best_physical_workpoint_handoff'-or
         $workpointHandoff.status-ne'within_tolerance'-or
         $workpointHandoff.qualification-ne'candidate_bunch_screening_authorized'){
        throw 'Qualified N=1 workpoint does not match this K/y condition.'
      }
    }else{
      $failureStage='n1_workpoint'
      $workpointId=$stamp+'__sim__simion__mrtof-condition-n1-workpoint'
      $workpointArgs=@{
      NativeCorridorBankRunPath=$nativeBank
      GeometryReviewRunPath=$geometryRun;MirrorRunPath=$mirrorRun;StripeRunPath=$stripeRun
      AcceleratorProviderReceiptPath=$acceleratorReceipt;NativeSystemRuntimeBundlePath=$nativeBundle
      AcceleratorSourceYOffsetMm=$sourceYOffset;AcceleratorYAnchorMm=$acceleratorY
      RetainBaselineGuiWorkbench=$true;ContractPath=$conditionContract;RunId=$workpointId
      }
      if($workpointResumeArguments.Count-eq3){
      $workpointArgs.InitialWorkpointManifest=(Resolve-Path -LiteralPath $WorkpointResumeInitialManifest).Path
      $workpointArgs.ResumeParentCheckpoint=(Resolve-Path -LiteralPath $WorkpointResumeParentCheckpoint).Path
      $workpointArgs.ResumeSuccessfulChildManifest=(Resolve-Path -LiteralPath $WorkpointResumeSuccessfulChildManifest).Path
      }else{
      $workpointArgs.ContinuationRunManifest=$continuationManifest
      if($nativeRuntimeCheckpoint){$workpointArgs.NativeRuntimeCheckpoint=$nativeRuntimeCheckpoint}
      }
      if($PythonExe){$workpointArgs.PythonExe=$PythonExe};if($SimionExe){$workpointArgs.SimionExe=$SimionExe}
      & (Join-Path $PSScriptRoot 'run_downstream_workpoint_iteration.ps1') @workpointArgs|Out-Host
      $workpointManifest=Get-RunManifest -ChildRunId $workpointId
      $workpointRun=Split-Path -Parent $workpointManifest
      if(-not(Test-Path -LiteralPath (Join-Path $workpointRun 'results\best_physical_workpoint_handoff.json') -PathType Leaf)){
      $workpointManifestData=Get-Content -LiteralPath $workpointManifest -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
      $workpointSummaryPath=Join-Path $workpointRun 'summary.json'
      if(-not(Test-Path -LiteralPath $workpointSummaryPath -PathType Leaf)){
        throw 'N=1 iteration did not publish a summary or a qualified physical workpoint.'
      }
      $workpointSummary=Get-Content -LiteralPath $workpointSummaryPath -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
      if($workpointManifestData.status-eq'checkpoint'-and
         $workpointSummary.role-eq'mrtof_downstream_workpoint_iteration_summary'-and
         $workpointSummary.status-eq'checkpoint'-and
         $workpointSummary.workflow_outcome-eq'workpoint_incomplete_downstream_blocked'-and
         $workpointSummary.external_interruption-eq$false){
        $failureStage='publish_physical_nonqualification'
        Complete-PhysicalConditionWarning -Package $package `
          -Outcome 'warning_n1_workpoint_not_qualified__continue_parameter_scan' `
          -Stage 'n1_workpoint' -Reason ([string]$workpointSummary.reason) `
          -Provider $provider -ProviderManifest $providerManifest -ProviderReceipt $acceleratorReceipt `
          -SlowEnergy $slowEnergy -SourceYOffset $sourceYOffset -K $k -AcceleratorY $acceleratorY `
          -ChildRunManifests ([ordered]@{stripe=$stripeManifest;accelerator_safe_exit=$safeExitManifest;coverage=$coverageManifest;continuation=$continuationManifest;workpoint=$workpointManifest})
        $terminalized=$true
        return
      }
        throw 'N=1 iteration did not publish a qualified physical workpoint.'
      }
    }

    $failureStage='native_candidate'
    $candidateId=$stamp+'__sim__simion__mrtof-condition-candidate'
    $candidateArgs=@{
      QualifiedWorkpointRunPath=$workpointRun;GeometryReviewRunPath=$geometryRun
      MirrorRunPath=$mirrorRun;StripeRunPath=$stripeRun;AcceleratorProviderReceiptPath=$acceleratorReceipt
      NativeCorridorBankRunPath=$nativeBank;NativeSystemRuntimeBundlePath=$nativeBundle
      SourceDefinitionPath=$conditionSourceDefinition;AcceleratorYAnchorMm=$acceleratorY
      ContractPath=$conditionContract;RunId=$candidateId
    }
    if($nativeRuntimeCheckpoint){$candidateArgs.NativeRuntimeCheckpoint=$nativeRuntimeCheckpoint}
    if($PythonExe){$candidateArgs.PythonExe=$PythonExe};if($SimionExe){$candidateArgs.SimionExe=$SimionExe}
    & (Join-Path $PSScriptRoot 'run_native_candidate_chain.ps1') @candidateArgs|Out-Host
    $candidateManifest=Get-RunManifest -ChildRunId $candidateId
    $candidateSummary=Get-Content -LiteralPath (Join-Path (Split-Path -Parent $candidateManifest) 'summary.json') -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
    if($candidateSummary.status-ne'success'-or[string]::IsNullOrWhiteSpace([string]$candidateSummary.workflow_outcome)){
      throw 'Native Candidate child did not publish a supported terminal outcome.'
    }
  }

  $failureStage='publish'
  Write-RunJson -Path $package.summary -Depth 20 -Value ([ordered]@{
    schema_version=1;role='mrtof_native_candidate_single_condition_summary';status='success'
    workflow_outcome=[string]$candidateSummary.workflow_outcome;K=$k;accelerator_y_mm=$acceleratorY
    provider_run_manifest=$providerManifest;provider_runtime_receipt=$acceleratorReceipt
    provider_release_slow_energy_per_charge_v=$slowEnergy
    provider_required_source_y_offset_mm=$sourceYOffset
    provider_exit_energy_acceptance=$provider.exit_energy_acceptance
    stripe_run_manifest=$stripeManifest;accelerator_safe_exit_run_manifest=$safeExitManifest
    coverage_run_manifest=$coverageManifest;continuation_run_manifest=$continuationManifest
    workpoint_run_manifest=$workpointManifest;candidate_run_manifest=$candidateManifest
  })
  $retention=Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config
  Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config -Status success `
    -Software @('SIMION 2020','Python 3.11') -Outputs @($package.summary,$retention)
  $terminalized=$true
}catch{
  if(-not$terminalized){
    Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config -Summary $package.summary `
      -SummaryRole 'mrtof_native_candidate_single_condition_summary' -Reason $_.Exception.Message `
      -Software @('SIMION 2020','Python 3.11') -Status failed -FailureStage $failureStage
    $terminalized=$true
  }
  throw
}finally{
  if(-not$terminalized-and(Test-Path -LiteralPath $package.run_config -PathType Leaf)){
    Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config -Summary $package.summary `
      -SummaryRole 'mrtof_native_candidate_single_condition_summary' `
      -Reason 'Single-condition workflow stopped before terminal publication.' `
      -Software @('SIMION 2020','Python 3.11') -Status interrupted -FailureStage $failureStage
  }
}

[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$CampaignPath,
  [Parameter(Mandatory)][string]$CheckpointPath,
  [string]$ConditionRunnerPath='',
  [Parameter(Mandatory)][string]$ConditionContextPath,
  [string]$InitialProviderReuseMapPath='',
  [string]$ConditionReuseMapPath='',
  [string]$CampaignStamp='',
  [string]$PythonExe='',
  [string]$SimionExe=''
)

# This controller intentionally knows nothing about MR-TOF physics.  The
# condition runner owns the complete theory -> P/S -> N=100 chain and accepts:
#   -ConditionPath <JSON> -ContextPath <JSON> -RunId <managed run id>
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$project='parallel_mirror_dual_stripe_mr_tof'
$repoRoot=(Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$workspaceRoot=Split-Path -Parent $repoRoot
$artifactRuns=Join-Path $workspaceRoot "artifacts\projects\$project\runs"
$campaign=(Resolve-Path -LiteralPath $CampaignPath).Path
$conditionRunner=if($ConditionRunnerPath){
  (Resolve-Path -LiteralPath $ConditionRunnerPath).Path
}else{
  Join-Path $PSScriptRoot 'run_native_candidate_condition.ps1'
}
$conditionContext=(Resolve-Path -LiteralPath $ConditionContextPath).Path
$initialProviderReuseMap=if($InitialProviderReuseMapPath){(Resolve-Path -LiteralPath $InitialProviderReuseMapPath).Path}else{$null}
$conditionReuseMap=if($ConditionReuseMapPath){(Resolve-Path -LiteralPath $ConditionReuseMapPath).Path}else{$null}
if(-not(Test-Path -LiteralPath $conditionRunner -PathType Leaf)){throw 'ConditionRunnerPath must be a file.'}
if(-not(Test-Path -LiteralPath $conditionContext -PathType Leaf)){throw 'ConditionContextPath must be a file.'}
$checkpoint=[IO.Path]::GetFullPath($CheckpointPath)
$checkpointParent=Split-Path -Parent $checkpoint
$supportRoot=Join-Path $checkpointParent (([IO.Path]::GetFileNameWithoutExtension($checkpoint))+'.d')

function Read-ConditionList {
  param([Parameter(Mandatory)][string]$Path)
  $raw=Get-Content -LiteralPath $Path -Raw -Encoding UTF8
  if(-not$raw.TrimStart().StartsWith('[')){throw 'Campaign JSON must be an ordered array.'}
  $items=@($raw|ConvertFrom-Json -AsHashtable)
  if($items.Count-eq0){throw 'Campaign JSON must contain at least one condition.'}
  $result=@()
  for($index=0;$index-lt$items.Count;$index++){
    $item=$items[$index]
    if($item-isnot[Collections.IDictionary]-or(@($item.Keys|Sort-Object)-join',')-ne'accelerator_y,K'){
      throw "Campaign condition $($index+1) must contain exactly K and accelerator_y."
    }
    if($item.K-isnot[ValueType]-or$item.K-is[bool]-or
       $item.accelerator_y-isnot[ValueType]-or$item.accelerator_y-is[bool]){
      throw "Campaign condition $($index+1) values must be numeric."
    }
    $k=[double]$item.K;$acceleratorY=[double]$item.accelerator_y
    if(-not[double]::IsFinite($k)-or-not[double]::IsFinite($acceleratorY)){
      throw "Campaign condition $($index+1) values must be finite."
    }
    $result+=,[ordered]@{K=$k;accelerator_y=$acceleratorY}
  }
  return @($result)
}

function Write-Checkpoint {
  param([Parameter(Mandatory)]$Value)
  Write-JsonAtomically -Value $Value -Path $checkpoint -Depth 12
}

function Write-JsonAtomically {
  param([Parameter(Mandatory)]$Value,[Parameter(Mandatory)][string]$Path,[int]$Depth=12)
  $temporary=$Path+'.tmp'
  $Value|ConvertTo-Json -Depth $Depth|Set-Content -LiteralPath $temporary -Encoding UTF8
  Move-Item -LiteralPath $temporary -Destination $Path -Force
}

function Write-ConditionInput {
  param([Parameter(Mandatory)]$Condition,[Parameter(Mandatory)][string]$Path)
  Write-JsonAtomically -Path $Path -Depth 4 -Value ([ordered]@{
    schema_version=1;role='mrtof_native_candidate_campaign_condition'
    K=[double]$Condition.K;accelerator_y=[double]$Condition.accelerator_y
  })
}

function Get-ProviderRuntimeCheckpoint {
  param([Parameter(Mandatory)][string]$ReceiptPath)
  $receipt=Get-Content -LiteralPath (Resolve-Path -LiteralPath $ReceiptPath).Path -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  if(-not$receipt.Contains('private_runtime_checkpoint')){return ''}
  $record=$receipt.private_runtime_checkpoint
  if($record-isnot[Collections.IDictionary]-or-not$record.Contains('checkpoint')-or
     $record.checkpoint-isnot[Collections.IDictionary]-or-not$record.checkpoint.Contains('path')-or
     [string]::IsNullOrWhiteSpace([string]$record.checkpoint.path)){return ''}
  $checkpointPath=[string]$record.checkpoint.path
  return (Resolve-Path -LiteralPath $checkpointPath).Path
}

function Get-RunnerIdentity {
  param([Parameter(Mandatory)][string]$Path)
  $item=Get-Item -LiteralPath $Path
  return [ordered]@{path=$item.FullName;bytes=[int64]$item.Length;last_write_time_utc_ticks=[int64]$item.LastWriteTimeUtc.Ticks}
}

function Assert-RunnerIdentity {
  param([Parameter(Mandatory)]$Expected,[Parameter(Mandatory)]$Actual)
  if(-not(Test-RunnerIdentity -Expected $Expected -Actual $Actual)){
    throw 'Condition runner identity differs from the campaign checkpoint.'
  }
}

function Test-RunnerIdentity {
  param([Parameter(Mandatory)]$Expected,[Parameter(Mandatory)]$Actual)
  return [string]::Equals([string]$Expected.path,[string]$Actual.path,[StringComparison]::OrdinalIgnoreCase)-and
    [int64]$Expected.bytes-eq[int64]$Actual.bytes-and
    [int64]$Expected.last_write_time_utc_ticks-eq[int64]$Actual.last_write_time_utc_ticks
}

function Get-ConditionAttemptRunId {
  param(
    [Parameter(Mandatory)][datetime]$Origin,
    [Parameter(Mandatory)][int]$ConditionIndex,
    [Parameter(Mandatory)][int]$ConditionCount,
    [Parameter(Mandatory)][int]$Attempt
  )
  $stamp=$Origin.AddSeconds($ConditionIndex+(($Attempt-1)*$ConditionCount)).ToString('yyyyMMdd_HHmmss')
  return $stamp+'__sim__simion__mrtof-native-condition'
}

function Get-NonterminalWorkpointResume {
  param(
    [Parameter(Mandatory)]$Condition,
    [Parameter(Mandatory)][string]$ConditionRunId
  )
  $conditionManifest=Join-Path (Join-Path $artifactRuns $ConditionRunId) 'run_manifest.json'
  if(-not(Test-Path -LiteralPath $conditionManifest -PathType Leaf)){return $null}
  $conditionRecord=Get-Content -LiteralPath $conditionManifest -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  if($conditionRecord.project-ne$project-or$conditionRecord.mode-ne'native_candidate_single_condition'-or
     $conditionRecord.run_id-ne$ConditionRunId-or$conditionRecord.status-notin@('checkpoint','interrupted')){return $null}
  $conditionConfig=Get-Content -LiteralPath (Join-Path (Split-Path -Parent $conditionManifest) 'run_config.json') -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  $conditionInput=Get-Content -LiteralPath ([string]$conditionConfig.inputs.condition) -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  if([double]$conditionInput.K-ne[double]$Condition.K-or
     [double]$conditionInput.accelerator_y-ne[double]$Condition.accelerator_y){
    throw 'Previous nonterminal condition differs from checkpoint K/y.'
  }

  $stamp=$ConditionRunId.Substring(0,15)
  $workpointRun=Join-Path $artifactRuns ($stamp+'__sim__simion__mrtof-condition-n1-workpoint')
  $parentManifest=Join-Path $workpointRun 'run_manifest.json'
  if(-not(Test-Path -LiteralPath $parentManifest -PathType Leaf)){return $null}
  $parent=Get-Content -LiteralPath $parentManifest -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  if($parent.project-ne$project-or$parent.mode-ne'downstream_fixed_grid_workpoint_iteration'-or
     $parent.status-ne'checkpoint'){
    throw 'Previous condition N=1 workpoint is not a resumable checkpoint.'
  }
  $workpointConfig=Get-Content -LiteralPath (Join-Path $workpointRun 'run_config.json') -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  $workpointContract=Get-Content -LiteralPath ([string]$workpointConfig.inputs.contract) -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  if([double]$workpointContract.nominal.target_drift_period_ratio-ne[double]$Condition.K-or
     [double]$workpointContract.accelerator.focus_y_anchor.project_y_mm-ne[double]$Condition.accelerator_y){
    throw 'Previous condition N=1 workpoint differs from checkpoint K/y.'
  }
  $lineagePath=Join-Path $workpointRun 'results\iteration_lineage.json'
  if(-not(Test-Path -LiteralPath $lineagePath -PathType Leaf)){return $null}
  $lineage=Get-Content -LiteralPath $lineagePath -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  $children=@($lineage.children)
  if($lineage.role-ne'mrtof_downstream_workpoint_iteration_lineage'-or$children.Count-lt1){return $null}
  $rootManifest=(Resolve-Path -LiteralPath ([string]$lineage.root_workpoint_manifest.path)).Path
  $root=Get-Content -LiteralPath $rootManifest -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  if($root.project-ne$project-or$root.status-ne'success'){
    throw 'Previous condition N=1 lineage root is not successful.'
  }
  $latestChild=$null
  for($index=$children.Count-1;$index-ge0;$index--){
    $candidatePath=[string]$children[$index].child_manifest
    if(-not(Test-Path -LiteralPath $candidatePath -PathType Leaf)){continue}
    $candidate=(Resolve-Path -LiteralPath $candidatePath).Path
    $manifest=Get-Content -LiteralPath $candidate -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
    if($manifest.project-eq$project-and$manifest.status-eq'success'){$latestChild=$candidate;break}
  }
  if(-not$latestChild){return $null}
  $recovery=$workpointConfig.parameters.native_recovery_problem
  $stripeManifest=Join-Path ([string]$recovery.stripe) 'run_manifest.json'
  $continuationManifest=(Resolve-Path -LiteralPath ([string]$workpointConfig.parameters.voltage_seed_consumer_projection.manifest)).Path
  if(-not(Test-Path -LiteralPath $stripeManifest -PathType Leaf)){
    throw 'Previous condition N=1 checkpoint lacks its Stripe authority manifest.'
  }
  return [ordered]@{
    initial_workpoint_manifest=$rootManifest
    parent_checkpoint=$parentManifest
    successful_child_manifest=$latestChild
    stripe_run_manifest=(Resolve-Path -LiteralPath $stripeManifest).Path
    continuation_run_manifest=$continuationManifest
  }
}

function Assert-ConditionInput {
  param([Parameter(Mandatory)]$Condition)
  $path=[string]$Condition.condition_path
  if(-not(Test-Path -LiteralPath $path -PathType Leaf)){throw "Condition input is missing: $path"}
  $input=Get-Content -LiteralPath $path -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  if($input.schema_version-ne1-or$input.role-ne'mrtof_native_candidate_campaign_condition'-or
     [double]$input.K-ne[double]$Condition.K-or
     [double]$input.accelerator_y-ne[double]$Condition.accelerator_y){
    throw "Condition input differs from checkpoint K/y: $path"
  }
  # Rewrite the validated two-field contract atomically to keep recovery deterministic.
  Write-ConditionInput -Condition $Condition -Path $path
}

function Get-KCacheKey {
  param([Parameter(Mandatory)][double]$K)
  return $K.ToString('R',[Globalization.CultureInfo]::InvariantCulture)
}

function Get-ConditionReuseKey {
  param([Parameter(Mandatory)][double]$K,[Parameter(Mandatory)][double]$AcceleratorY)
  return (Get-KCacheKey -K $K)+'|'+$AcceleratorY.ToString('R',[Globalization.CultureInfo]::InvariantCulture)
}

function Assert-ProviderCacheEntry {
  param([Parameter(Mandatory)]$Entry,[Parameter(Mandatory)][double]$ExpectedK)
  if($Entry-isnot[Collections.IDictionary]-or$Entry.role-ne'mrtof_native_candidate_oa_provider_cache_entry'-or
     [double]$Entry.K-ne$ExpectedK){throw 'OA provider cache entry belongs to a different K.'}
  $manifestPath=(Resolve-Path -LiteralPath ([string]$Entry.run_manifest)).Path
  $receiptPath=(Resolve-Path -LiteralPath ([string]$Entry.runtime_receipt)).Path
  $manifest=Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  if($manifest.project-ne'orthogonal_accelerator'-or$manifest.mode-ne'component_focus_workflow'-or
     $manifest.status-ne'success'-or[string]::IsNullOrWhiteSpace([string]$manifest.run_id)){
    throw 'Cached OA provider manifest is invalid.'
  }
  $receipt=Get-Content -LiteralPath $receiptPath -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  $projection=$receipt.mrtof_projection;$accepted=$projection.accepted_release
  $energyAcceptance=$projection.provider_exit_energy_acceptance
  $transverseTolerance=[double]$energyAcceptance.tolerances.maximum_exit_transverse_energy_error_per_charge_v
  $velocityBiasTolerance=[double]$energyAcceptance.tolerances.maximum_exit_transverse_velocity_bias_mm_per_us
  $direction=@($accepted.nominal_direction);$angularWidth=[double]$accepted.angular_full_width_deg
  $releaseGeometry=$accepted.geometry
  if($receipt.role-ne'orthogonal_accelerator_mrtof_runtime_receipt'-or$receipt.status-ne'published_standalone_response_bank'-or
     $accepted-isnot[Collections.IDictionary]-or$energyAcceptance-isnot[Collections.IDictionary]-or
     $energyAcceptance.passed-ne$true-or-not[double]::IsFinite($transverseTolerance)-or
     $transverseTolerance-lt0-or-not[double]::IsFinite($velocityBiasTolerance)-or
     $velocityBiasTolerance-lt0-or$energyAcceptance.center_particle.transverse_energy_passed-ne$true-or
     $energyAcceptance.center_particle.transverse_velocity_bias_passed-ne$true-or
     $energyAcceptance.cohort.transverse_energy_passed-ne$true-or
     $energyAcceptance.cohort.transverse_velocity_bias_passed-ne$true-or
     $direction.Count-ne3-or[double]$direction[0]-ne0-or[double]$direction[1]-ne1-or
     [double]$direction[2]-ne0-or-not[double]::IsFinite($angularWidth)-or$angularWidth-ne0-or
     $releaseGeometry.shape-ne'cylinder'-or$releaseGeometry.axis-ne'y'-or
     [double]$releaseGeometry.radius_mm-ne0.5-or[double]$releaseGeometry.height_mm-ne1.0-or
     [double]$accepted.slow_energy_center_per_charge_v-ne[double]$Entry.release_slow_energy_per_charge_v-or
     [double]$projection.required_source_y_offset_from_accelerator_axis_mm-ne[double]$Entry.required_source_y_offset_mm){
    throw 'Cached OA provider receipt differs from its checkpoint entry.'
  }
  return [ordered]@{
    schema_version=1;role='mrtof_native_candidate_oa_provider_cache_entry';K=$ExpectedK
    run_manifest=$manifestPath;runtime_receipt=$receiptPath
    release_slow_energy_per_charge_v=[double]$Entry.release_slow_energy_per_charge_v
    required_source_y_offset_mm=[double]$Entry.required_source_y_offset_mm
  }
}

function Read-InitialProviderReuseMap {
  param([Parameter(Mandatory)][string]$Path)
  $document=Get-Content -LiteralPath $Path -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  if($document.schema_version-ne1-or$document.role-ne'mrtof_native_candidate_provider_reuse_map'-or
     @($document.Keys|Sort-Object)-join','-ne'providers,role,schema_version'){
    throw 'Initial provider reuse map identity is invalid.'
  }
  $directory=Split-Path -Parent $Path;$result=@{}
  foreach($item in @($document.providers)){
    if($item-isnot[Collections.IDictionary]-or(@($item.Keys|Sort-Object)-join',')-ne'K,runtime_receipt'){
      throw 'Each initial provider reuse item must contain exactly K and runtime_receipt.'
    }
    $k=[double]$item.K
    if(-not[double]::IsFinite($k)){throw 'Initial provider reuse K must be finite.'}
    $key=Get-KCacheKey -K $k
    if($result.ContainsKey($key)){throw "Initial provider reuse map repeats K=$key."}
    $declared=[string]$item.runtime_receipt
    $receiptPath=(Resolve-Path -LiteralPath $(if([IO.Path]::IsPathRooted($declared)){$declared}else{Join-Path $directory $declared})).Path
    if([IO.Path]::GetFileName($receiptPath)-ne'mrtof_runtime_receipt.json'){
      throw 'Initial provider reuse item must name mrtof_runtime_receipt.json.'
    }
    $manifestPath=Join-Path (Split-Path -Parent (Split-Path -Parent $receiptPath)) 'run_manifest.json'
    $receipt=Get-Content -LiteralPath $receiptPath -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
    $result[$key]=Assert-ProviderCacheEntry -ExpectedK $k -Entry ([ordered]@{
      schema_version=1;role='mrtof_native_candidate_oa_provider_cache_entry';K=$k
      run_manifest=$manifestPath;runtime_receipt=$receiptPath
      release_slow_energy_per_charge_v=[double]$receipt.mrtof_projection.accepted_release.slow_energy_center_per_charge_v
      required_source_y_offset_mm=[double]$receipt.mrtof_projection.required_source_y_offset_from_accelerator_axis_mm
    })
  }
  return $result
}

function Read-ConditionReuseMap {
  param([Parameter(Mandatory)][string]$Path)
  $document=Get-Content -LiteralPath $Path -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  if($document.schema_version-ne1-or$document.role-ne'mrtof_native_candidate_condition_reuse_map'-or
     @($document.Keys|Sort-Object)-join','-ne'conditions,role,schema_version'){
    throw 'Condition reuse map identity is invalid.'
  }
  $directory=Split-Path -Parent $Path;$result=@{}
  foreach($item in @($document.conditions)){
    $keys=if($item-is[Collections.IDictionary]){@($item.Keys|Sort-Object)-join','}else{''}
    if($keys-notin@(
        'accelerator_y,continuation_run_manifest,K,stripe_run_manifest',
        'accelerator_y,candidate_run_manifest,continuation_run_manifest,K,stripe_run_manifest'
      )){
      throw 'Each condition reuse item must contain K, accelerator_y, stripe_run_manifest, continuation_run_manifest, and optionally candidate_run_manifest.'
    }
    $k=[double]$item.K;$acceleratorY=[double]$item.accelerator_y
    if(-not[double]::IsFinite($k)-or-not[double]::IsFinite($acceleratorY)){
      throw 'Condition reuse K and accelerator_y must be finite.'
    }
    $key=Get-ConditionReuseKey -K $k -AcceleratorY $acceleratorY
    if($result.ContainsKey($key)){throw "Condition reuse map repeats K/y=$key."}
    $stripe=[string]$item.stripe_run_manifest;$continuation=[string]$item.continuation_run_manifest
    $candidate=if($item.Contains('candidate_run_manifest')){[string]$item.candidate_run_manifest}else{''}
    if($item.Contains('candidate_run_manifest')-and[string]::IsNullOrWhiteSpace($candidate)){
      throw 'candidate_run_manifest must not be empty when supplied.'
    }
    $result[$key]=[ordered]@{
      stripe_run_manifest=(Resolve-Path -LiteralPath $(if([IO.Path]::IsPathRooted($stripe)){$stripe}else{Join-Path $directory $stripe})).Path
      continuation_run_manifest=(Resolve-Path -LiteralPath $(if([IO.Path]::IsPathRooted($continuation)){$continuation}else{Join-Path $directory $continuation})).Path
      candidate_run_manifest=$(if($candidate){
        (Resolve-Path -LiteralPath $(if([IO.Path]::IsPathRooted($candidate)){$candidate}else{Join-Path $directory $candidate})).Path
      }else{$null})
    }
  }
  return $result
}

function Read-ConditionTerminal {
  param(
    [Parameter(Mandatory)]$Condition,
    [Parameter(Mandatory)][string]$ManifestPath,
    [Parameter(Mandatory)][string]$ExpectedRunId
  )
  if(-not(Test-Path -LiteralPath $ManifestPath -PathType Leaf)){throw "Condition manifest is missing: $ManifestPath"}
  $manifest=Get-Content -LiteralPath $ManifestPath -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  if($manifest.project-ne$project-or$manifest.mode-ne'native_candidate_single_condition'-or
     $manifest.run_id-ne$ExpectedRunId-or$manifest.status-notin@('success','failed','interrupted','checkpoint')){
    throw "Condition manifest identity is invalid: $ManifestPath"
  }
  if($manifest.status-ne'success'){
    return [pscustomobject]@{status=[string]$manifest.status;workflow_outcome=$null;summary=$null;provider=$null}
  }
  $summaryPath=Join-Path (Split-Path -Parent $ManifestPath) 'summary.json'
  if(-not(Test-Path -LiteralPath $summaryPath -PathType Leaf)){throw "Condition summary is missing: $summaryPath"}
  $summary=Get-Content -LiteralPath $summaryPath -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  $outcome=[string]$summary.workflow_outcome
  if($summary.status-ne'success'-or[double]$summary.K-ne[double]$Condition.K-or
     [double]$summary.accelerator_y_mm-ne[double]$Condition.accelerator_y-or
     ($outcome-ne'within_tolerance'-and$outcome-notlike'warning_*')){
    throw "Condition summary identity or outcome is invalid: $summaryPath"
  }
  $provider=Assert-ProviderCacheEntry -ExpectedK ([double]$Condition.K) -Entry ([ordered]@{
    schema_version=1;role='mrtof_native_candidate_oa_provider_cache_entry';K=[double]$Condition.K
    run_manifest=[string]$summary.provider_run_manifest;runtime_receipt=[string]$summary.provider_runtime_receipt
    release_slow_energy_per_charge_v=[double]$summary.provider_release_slow_energy_per_charge_v
    required_source_y_offset_mm=[double]$summary.provider_required_source_y_offset_mm
  })
  return [pscustomobject]@{status='success';workflow_outcome=$outcome;summary=$summaryPath;provider=$provider}
}

function Get-CandidateSample {
  param([Parameter(Mandatory)]$Candidate,[Parameter(Mandatory)][string]$Label)
  if(-not$Candidate.Contains('comparison')-or$Candidate.comparison-isnot[Collections.IDictionary]){return $null}
  $matches=@($Candidate.comparison.samples|Where-Object{$_.label-eq$Label})
  if($matches.Count-ne1){return $null}
  return $matches[0]
}

function Get-OptionalDictionaryValue {
  param($Dictionary,[Parameter(Mandatory)][string]$Name)
  if($Dictionary-is[Collections.IDictionary]-and$Dictionary.Contains($Name)){return $Dictionary[$Name]}
  return $null
}

function Read-CandidateDiagnostic {
  param([Parameter(Mandatory)]$Sample,[switch]$Focus)
  $field=if($Focus){'focus_diagnostic_path'}else{'diagnostic_path'}
  if(-not$Sample.Contains($field)-or[string]::IsNullOrWhiteSpace([string]$Sample[$field])){return $null}
  $path=[string]$Sample[$field]
  if(-not(Test-Path -LiteralPath $path -PathType Leaf)){return $null}
  return Get-Content -LiteralPath $path -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
}

function New-InitialZSlopeProjection {
  param([Parameter(Mandatory)]$Sample)
  $diagnostic=Read-CandidateDiagnostic -Sample $Sample -Focus
  $controlled=if($null-ne$diagnostic-and$diagnostic.controlled_detector_focus-is[Collections.IDictionary]){
    $diagnostic.controlled_detector_focus
  }else{$null}
  if($null-ne$controlled-and$controlled.status-eq'observed'){
    return [ordered]@{
      value_us_per_mm=$Sample.detector_dt_d_initial_z_us_per_mm
      measurement_basis='controlled_symmetric_initial_z_pair'
      sample_particle_count=$(Get-OptionalDictionaryValue -Dictionary $Sample -Name 'focus_particle_count')
      scope=[string]$controlled.scope
    }
  }
  return [ordered]@{
    value_us_per_mm=$Sample.detector_dt_d_initial_z_us_per_mm
    measurement_basis='descriptive_linear_regression_over_detector_hits'
    sample_particle_count=$(Get-OptionalDictionaryValue -Dictionary $Sample -Name 'focus_particle_count')
    scope='detector_hits_in_focus_diagnostic'
  }
}

function New-Z0TargetReturnProjection {
  param([Parameter(Mandatory)]$Sample)
  $diagnostic=Read-CandidateDiagnostic -Sample $Sample
  $history=if($null-ne$diagnostic-and$diagnostic.central_plane_focus_history-is[Collections.IDictionary]){
    $diagnostic.central_plane_focus_history
  }else{$null}
  $target=if($null-ne$history-and$history.target_return_crossing-is[Collections.IDictionary]){
    $history.target_return_crossing
  }else{$null}
  return [ordered]@{
    status=$(if($null-ne$target){$target.status}else{$null})
    plane_z_mm=$(if($null-ne$history-and$history.Contains('plane_z_mm')){$history.plane_z_mm}else{0.0})
    crossing_index=$(if($null-ne$target-and$target.status-eq'observed'){$target.crossing_index}else{$null})
    direction_z=$(if($null-ne$target-and$target.status-eq'observed'){$target.direction_z}else{$null})
    source_particle_count=$Sample.particle_count
    reached_particle_count=$(Get-OptionalDictionaryValue -Dictionary $Sample -Name 'z0_reached_particle_count')
    reached_fraction=$(Get-OptionalDictionaryValue -Dictionary $Sample -Name 'z0_reached_fraction')
    tof_median_us=$(Get-OptionalDictionaryValue -Dictionary $Sample -Name 'z0_tof_median_us')
    tof_fwhm_us=$(Get-OptionalDictionaryValue -Dictionary $Sample -Name 'z0_tof_fwhm_us')
    mass_resolution_t_over_2fwhm=$(Get-OptionalDictionaryValue -Dictionary $Sample -Name 'z0_mass_resolution_t_over_2fwhm')
    initial_z_time_slope=[ordered]@{
      value_us_per_mm=$(Get-OptionalDictionaryValue -Dictionary $Sample -Name 'z0_dt_d_initial_z_us_per_mm')
      measurement_basis='descriptive_linear_regression_over_all_particles_reaching_target_return_z0'
      sample_particle_count=$(Get-OptionalDictionaryValue -Dictionary $Sample -Name 'z0_reached_particle_count')
      scope=$(if($null-ne$target-and$target.Contains('scope')){[string]$target.scope}else{'all_particles_reaching_target_return_z0__no_detector_hit_filter'})
    }
    controlled_z_only_focus=$(Get-OptionalDictionaryValue -Dictionary $target -Name 'controlled_z_only_focus')
    qualification='diagnostic_only__not_a_z0_resolution_gate'
  }
}

function New-DetectorSampleProjection {
  param($Candidate,$Sample,[Parameter(Mandatory)][string]$Phase)
  if($null-eq$Sample){
    return [ordered]@{
      source_particle_count=$null;detector_hit_count=$null;detection_rate=$null
      tof_median_us=$null;tof_fwhm_us=$null;mass_resolution_t_over_2fwhm=$null
      initial_z_time_slope=$null;z0_target_return=$null
      peak_method_id=$null;peak_analysis_contract=$null
    }
  }
  $collection=$Candidate.collection[$Phase]
  return [ordered]@{
    source_particle_count=$Sample.particle_count
    detector_hit_count=$Sample.detector_hit_count
    detection_rate=$(if($collection-is[Collections.IDictionary]){$collection.detection_rate}else{$null})
    tof_median_us=$Sample.detector_tof_median_us
    tof_mean_us=$(Get-OptionalDictionaryValue -Dictionary $Sample -Name 'detector_tof_mean_us')
    peak_method_id=$(if($Sample.Contains('peak_method_id')){$Sample.peak_method_id}else{'legacy_histogram_unversioned'})
    peak_analysis_contract=$(Get-OptionalDictionaryValue -Dictionary $Sample -Name 'peak_analysis_contract')
    tof_fwhm_us=$Sample.detector_tof_fwhm_us
    mass_resolution_t_over_2fwhm=$Sample.mass_resolution_t_over_2fwhm
    initial_z_time_slope=$(New-InitialZSlopeProjection -Sample $Sample)
    z0_target_return=$(New-Z0TargetReturnProjection -Sample $Sample)
  }
}

function New-CampaignComparison {
  $rows=@()
  foreach($condition in @($state.conditions)){
    $conditionSummary=Get-Content -LiteralPath (Join-Path (Split-Path -Parent ([string]$condition.run_manifest)) 'summary.json') `
      -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
    $candidateManifest=$null;$candidate=$null
    if($conditionSummary.Contains('candidate_run_manifest')-and
       -not[string]::IsNullOrWhiteSpace([string]$conditionSummary.candidate_run_manifest)){
      $candidateManifest=(Resolve-Path -LiteralPath ([string]$conditionSummary.candidate_run_manifest)).Path
      $candidateSummary=Join-Path (Split-Path -Parent $candidateManifest) 'summary.json'
      $candidate=Get-Content -LiteralPath $candidateSummary -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
      if($candidate.role-ne'mrtof_native_candidate_end_to_end_chain_summary'-or$candidate.status-ne'success'){
        throw "Candidate summary is not a successful terminal record: $candidateSummary"
      }
      if([string]$candidate.workflow_outcome-ne[string]$condition.workflow_outcome){
        throw "Candidate and condition outcomes differ: $candidateSummary"
      }
    }
    $baselineSample=if($null-ne$candidate){Get-CandidateSample -Candidate $candidate -Label 'baseline'}else{$null}
    $focusedSample=if($null-ne$candidate){Get-CandidateSample -Candidate $candidate -Label 'root'}else{$null}
    $terminalStage=if($conditionSummary.Contains('physical_nonqualification')){
      [string]$conditionSummary.physical_nonqualification.stage
    }elseif($null-ne$candidate){'native_candidate'}else{'condition'}
    $rows+=,[ordered]@{
      ordinal=[int]$condition.ordinal;K=[double]$condition.K
      accelerator_y_mm=[double]$condition.accelerator_y
      workflow_outcome=[string]$condition.workflow_outcome;terminal_stage=$terminalStage
      condition_run_manifest=[string]$condition.run_manifest
      candidate_run_manifest=$candidateManifest
      baseline=$(New-DetectorSampleProjection -Candidate $candidate -Sample $baselineSample -Phase 'baseline')
      focused=$(New-DetectorSampleProjection -Candidate $candidate -Sample $focusedSample -Phase 'focused')
      detector_plane_focus=[ordered]@{
        convergence_status=$(if($null-ne$candidate){$candidate.detector_plane_focus.status}else{$null})
        te1_coordinate=$(if($null-ne$focusedSample){$focusedSample.te1_coordinate}else{$null})
      }
      center_gate=[ordered]@{
        baseline_passed=$(if($null-ne$candidate-and$candidate.center_workpoint.baseline-is[Collections.IDictionary]){
          $candidate.center_workpoint.baseline.passed
        }else{$null})
        focused_passed=$(if($null-ne$candidate-and$candidate.center_workpoint.focused-is[Collections.IDictionary]){
          $candidate.center_workpoint.focused.passed
        }else{$null})
        satisfied=$(if($null-ne$candidate){$candidate.center_workpoint.satisfied}else{$null})
      }
    }
  }
  $eligible=@($rows|Where-Object{
    $_.workflow_outcome-eq'within_tolerance'-and
    $_.focused.peak_method_id-eq'common_gaussian_kde_time_v1'-and
    $null-ne$_.focused.peak_analysis_contract
  })
  $peakContracts=@($eligible|ForEach-Object{
    $_.focused.peak_analysis_contract|ConvertTo-Json -Depth 10 -Compress
  }|Select-Object -Unique)
  $rankingStatus=if($peakContracts.Count-gt1){'unavailable_mixed_peak_settings'}else{'same_frozen_peak_contract'}
  if($peakContracts.Count-gt1){$eligible=@()}
  $ranked=@($eligible|Sort-Object `
    @{Expression={if($null-eq$_.focused.mass_resolution_t_over_2fwhm){[double]::NegativeInfinity}else{[double]$_.focused.mass_resolution_t_over_2fwhm}};Descending=$true}, `
    @{Expression={if($null-eq$_.focused.detection_rate){[double]::NegativeInfinity}else{[double]$_.focused.detection_rate}};Descending=$true}, `
    @{Expression={$_.ordinal};Descending=$false})
  $best=if($ranked.Count){[ordered]@{
    ordinal=[int]$ranked[0].ordinal;K=[double]$ranked[0].K
    accelerator_y_mm=[double]$ranked[0].accelerator_y_mm
  }}else{$null}
  return [ordered]@{
    schema_version=2;role='mrtof_native_candidate_campaign_comparison';status='complete'
    metric_scope=[ordered]@{
      detector_plane='FWHM and resolution use detector hits; the reported slope states whether it uses a controlled z pair or a descriptive regression.'
      z0_target_return='FWHM, resolution, and descriptive slope use all source particles reaching the named z=0 crossing; no detector-hit filter is applied.'
      cross_plane_comparison='The two planes may contain different particle sets. Their FWHM values are reported independently and do not by themselves attribute downstream causal broadening.'
      z0_is_qualification_gate=$false
    }
    selection=[ordered]@{
      eligibility='workflow_outcome == within_tolerance and current common KDE method with identical frozen contract'
      status=$rankingStatus
      ordering=@('focused mass_resolution_t_over_2fwhm descending','focused detection_rate descending','campaign ordinal ascending')
      qualified_condition_count=$ranked.Count;best_qualified_condition=$best
    }
    conditions=$rows
  }
}

$requested=@(Read-ConditionList -Path $campaign)
$runnerIdentity=Get-RunnerIdentity -Path $conditionRunner
if(Test-Path -LiteralPath $checkpoint -PathType Leaf){
  $state=Get-Content -LiteralPath $checkpoint -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  if($state.schema_version-ne1-or$state.role-ne'mrtof_native_candidate_campaign_checkpoint'){
    throw 'Campaign checkpoint identity is invalid.'
  }
  if($CampaignStamp-and$CampaignStamp-ne[string]$state.campaign_stamp){
    throw 'CampaignStamp differs from the existing checkpoint.'
  }
  if(-not[string]::Equals([string]$state.context_source_path,$conditionContext,[StringComparison]::OrdinalIgnoreCase)){
    throw 'ConditionContextPath differs from the campaign checkpoint.'
  }
  $savedProviderReuseSource=if($state.Contains('initial_provider_reuse_source_path')){[string]$state.initial_provider_reuse_source_path}else{''}
  $savedConditionReuseSource=if($state.Contains('condition_reuse_source_path')){[string]$state.condition_reuse_source_path}else{''}
  if(-not[string]::Equals($savedProviderReuseSource,[string]$initialProviderReuseMap,[StringComparison]::OrdinalIgnoreCase)){
    throw 'InitialProviderReuseMapPath differs from the campaign checkpoint.'
  }
  if(-not[string]::Equals($savedConditionReuseSource,[string]$conditionReuseMap,[StringComparison]::OrdinalIgnoreCase)){
    throw 'ConditionReuseMapPath differs from the campaign checkpoint.'
  }
  if(-not(Test-RunnerIdentity -Expected $state.condition_runner_identity -Actual $runnerIdentity)){
    $wiringVersion=if($state.Contains('condition_runner_resume_wiring_version')){[int]$state.condition_runner_resume_wiring_version}else{0}
    if($wiringVersion-ge2){
      throw 'Condition runner identity differs from the campaign checkpoint.'
    }
    $migrationCount=0
    if($wiringVersion-eq1){
      foreach($saved in @($state.conditions)){
        if($saved.Contains('workpoint_qualified_run_path')-and
           -not[string]::IsNullOrWhiteSpace([string]$saved.workpoint_qualified_run_path)){
          if($saved.terminal_state-eq'failed'){$saved.terminal_state='pending'}
          $migrationCount++
        }
      }
    }else{
      $migrationOrigin=[datetime]::ParseExact([string]$state.campaign_stamp,'yyyyMMdd_HHmmss',[Globalization.CultureInfo]::InvariantCulture)
      for($index=0;$index-lt@($state.conditions).Count;$index++){
        $saved=$state.conditions[$index]
        if($saved.terminal_state-ne'pending'-or[int]$saved.attempt_count-lt1){continue}
        $previousRunId=Get-ConditionAttemptRunId -Origin $migrationOrigin -ConditionIndex $index -ConditionCount (@($state.conditions).Count) -Attempt ([int]$saved.attempt_count)
        $resume=Get-NonterminalWorkpointResume -Condition $saved -ConditionRunId $previousRunId
        if($null-eq$resume){continue}
        $saved.workpoint_resume_initial_manifest=[string]$resume.initial_workpoint_manifest
        $saved.workpoint_resume_parent_checkpoint=[string]$resume.parent_checkpoint
        $saved.workpoint_resume_successful_child_manifest=[string]$resume.successful_child_manifest
        $saved.stripe_reuse_run_manifest=[string]$resume.stripe_run_manifest
        $saved.continuation_reuse_run_manifest=[string]$resume.continuation_run_manifest
        $migrationCount++
      }
    }
    if($migrationCount-lt1){throw 'Condition runner identity differs from the campaign checkpoint.'}
    $state.condition_runner_identity=$runnerIdentity
    $state.condition_runner_resume_wiring_version=2
    Write-Checkpoint -Value $state
  }
  Assert-RunnerIdentity -Expected $state.condition_runner_identity -Actual $runnerIdentity
  if(-not(Test-Path -LiteralPath ([string]$state.frozen_context) -PathType Leaf)){
    throw 'Frozen condition context is missing.'
  }
  if(@($state.conditions).Count-ne$requested.Count){throw 'Campaign condition count differs from the checkpoint.'}
  if(-not$state.Contains('provider_cache')){$state.provider_cache=@{}}
  if(-not$state.Contains('accelerator_runtime_checkpoint')){$state.accelerator_runtime_checkpoint=$null}
  for($index=0;$index-lt$requested.Count;$index++){
    $saved=$state.conditions[$index];$current=$requested[$index]
    if([double]$saved.K-ne[double]$current.K-or[double]$saved.accelerator_y-ne[double]$current.accelerator_y){
      throw "Campaign condition $($index+1) differs from the checkpoint."
    }
  }
}else{
  if(Test-Path -LiteralPath $supportRoot){throw "Campaign support directory exists without its checkpoint: $supportRoot"}
  if(-not$CampaignStamp){$CampaignStamp=Get-Date -Format 'yyyyMMdd_HHmmss'}
  if($CampaignStamp-notmatch'^\d{8}_\d{6}$'){throw 'CampaignStamp must be YYYYMMDD_HHMMSS.'}
  New-Item -ItemType Directory -Path $checkpointParent,$supportRoot -Force|Out-Null
  $frozenContext=Join-Path $supportRoot 'context.json'
  $contextTemporary=$frozenContext+'.tmp'
  Copy-Item -LiteralPath $conditionContext -Destination $contextTemporary
  Move-Item -LiteralPath $contextTemporary -Destination $frozenContext
  $frozenProviderReuseMap=$null;$providerCache=@{}
  if($null-ne$initialProviderReuseMap){
    $providerCache=Read-InitialProviderReuseMap -Path $initialProviderReuseMap
    $frozenProviderReuseMap=Join-Path $supportRoot 'initial_provider_reuse_map.json'
    Copy-Item -LiteralPath $initialProviderReuseMap -Destination $frozenProviderReuseMap
  }
  $frozenConditionReuseMap=$null;$conditionReuse=@{}
  if($null-ne$conditionReuseMap){
    $conditionReuse=Read-ConditionReuseMap -Path $conditionReuseMap
    $frozenConditionReuseMap=Join-Path $supportRoot 'condition_reuse_map.json'
    Copy-Item -LiteralPath $conditionReuseMap -Destination $frozenConditionReuseMap
  }
  $requestedKKeys=@($requested|ForEach-Object{Get-KCacheKey -K ([double]$_.K)})
  foreach($key in @($providerCache.Keys)){
    if($key-notin$requestedKKeys){throw "Initial provider reuse K is absent from the campaign: $key"}
  }
  $requestedConditionKeys=@($requested|ForEach-Object{Get-ConditionReuseKey -K ([double]$_.K) -AcceleratorY ([double]$_.accelerator_y)})
  foreach($key in @($conditionReuse.Keys)){
    if($key-notin$requestedConditionKeys){throw "Condition reuse K/y is absent from the campaign: $key"}
  }
  $conditions=@()
  for($index=0;$index-lt$requested.Count;$index++){
    $conditionPath=Join-Path $supportRoot ('condition_{0:D3}.json'-f($index+1))
    Write-ConditionInput -Condition $requested[$index] -Path $conditionPath
    $reuseKey=Get-ConditionReuseKey -K ([double]$requested[$index].K) -AcceleratorY ([double]$requested[$index].accelerator_y)
    $reuse=if($conditionReuse.ContainsKey($reuseKey)){$conditionReuse[$reuseKey]}else{$null}
    $conditions+=,[ordered]@{
      ordinal=$index+1;K=[double]$requested[$index].K
      accelerator_y=[double]$requested[$index].accelerator_y
      condition_path=$conditionPath;terminal_state='pending';attempt_count=0
      run_manifest=$null;workflow_outcome=$null
      stripe_reuse_run_manifest=$(if($null-ne$reuse){[string]$reuse.stripe_run_manifest}else{$null})
      continuation_reuse_run_manifest=$(if($null-ne$reuse){[string]$reuse.continuation_run_manifest}else{$null})
      candidate_reuse_run_manifest=$(if($null-ne$reuse){[string]$reuse.candidate_run_manifest}else{$null})
      workpoint_qualified_run_path=$null
    }
  }
  $state=[ordered]@{
    schema_version=1;role='mrtof_native_candidate_campaign_checkpoint';status='checkpoint'
    campaign_stamp=$CampaignStamp;context_source_path=$conditionContext;frozen_context=$frozenContext
    initial_provider_reuse_source_path=$initialProviderReuseMap;frozen_initial_provider_reuse_map=$frozenProviderReuseMap
    condition_reuse_source_path=$conditionReuseMap;frozen_condition_reuse_map=$frozenConditionReuseMap
    condition_runner_identity=$runnerIdentity;conditions=$conditions
    provider_cache=$providerCache;accelerator_runtime_checkpoint=$null
  }
  Write-Checkpoint -Value $state
}

$conditionContext=[string]$state.frozen_context
$origin=[datetime]::ParseExact([string]$state.campaign_stamp,'yyyyMMdd_HHmmss',[Globalization.CultureInfo]::InvariantCulture)
$conditionCount=@($state.conditions).Count
for($index=0;$index-lt$conditionCount;$index++){
  $condition=$state.conditions[$index]
  Assert-ConditionInput -Condition $condition
  if($condition.terminal_state-in@('success','warning')){
    $expectedRunId=Split-Path -Leaf (Split-Path -Parent ([string]$condition.run_manifest))
    $terminal=Read-ConditionTerminal -Condition $condition -ManifestPath ([string]$condition.run_manifest) -ExpectedRunId $expectedRunId
    $expectedState=if($terminal.workflow_outcome-eq'within_tolerance'){'success'}else{'warning'}
    if($terminal.status-ne'success'-or$condition.terminal_state-ne$expectedState-or
       $condition.workflow_outcome-ne$terminal.workflow_outcome){
      throw "Completed condition checkpoint differs from its terminal records: $($condition.ordinal)"
    }
    $cacheKey=Get-KCacheKey -K ([double]$condition.K)
    if(-not$state.provider_cache.ContainsKey($cacheKey)){throw "Completed condition lacks its K-specific OA provider cache: $cacheKey"}
    $cached=Assert-ProviderCacheEntry -ExpectedK ([double]$condition.K) -Entry $state.provider_cache[$cacheKey]
    if(-not[string]::Equals([string]$cached.run_manifest,[string]$terminal.provider.run_manifest,[StringComparison]::OrdinalIgnoreCase)-or
       -not[string]::Equals([string]$cached.runtime_receipt,[string]$terminal.provider.runtime_receipt,[StringComparison]::OrdinalIgnoreCase)-or
       [double]$cached.release_slow_energy_per_charge_v-ne[double]$terminal.provider.release_slow_energy_per_charge_v-or
       [double]$cached.required_source_y_offset_mm-ne[double]$terminal.provider.required_source_y_offset_mm){
      throw "Completed condition OA provider differs from the K-specific cache: $cacheKey"
    }
    continue
  }
  if([int]$condition.attempt_count-ge1){
    if(-not($condition.Contains('workpoint_qualified_run_path')-and
       -not[string]::IsNullOrWhiteSpace([string]$condition.workpoint_qualified_run_path))){
      $previousRunId=Get-ConditionAttemptRunId -Origin $origin -ConditionIndex $index -ConditionCount $conditionCount -Attempt ([int]$condition.attempt_count)
      $resume=Get-NonterminalWorkpointResume -Condition $condition -ConditionRunId $previousRunId
      if($null-ne$resume){
        $condition.workpoint_resume_initial_manifest=[string]$resume.initial_workpoint_manifest
        $condition.workpoint_resume_parent_checkpoint=[string]$resume.parent_checkpoint
        $condition.workpoint_resume_successful_child_manifest=[string]$resume.successful_child_manifest
        $condition.stripe_reuse_run_manifest=[string]$resume.stripe_run_manifest
        $condition.continuation_reuse_run_manifest=[string]$resume.continuation_run_manifest
      }
    }
  }
  if($condition.terminal_state-eq'failed'-and$condition.Contains('workpoint_qualified_run_path')-and
     -not[string]::IsNullOrWhiteSpace([string]$condition.workpoint_qualified_run_path)){
    $condition.terminal_state='pending'
  }
  if($condition.terminal_state-eq'failed'){
    throw "Campaign remains stopped at failed condition $($condition.ordinal): $($condition.run_manifest)"
  }
  $attempt=[int]$condition.attempt_count+1
  $runId=Get-ConditionAttemptRunId -Origin $origin -ConditionIndex $index -ConditionCount $conditionCount -Attempt $attempt
  $condition.attempt_count=$attempt;$condition.run_manifest=$null;$condition.workflow_outcome=$null
  Write-Checkpoint -Value $state

  $arguments=@{ConditionPath=[string]$condition.condition_path;ContextPath=$conditionContext;RunId=$runId}
  if(-not[string]::IsNullOrWhiteSpace([string]$state.accelerator_runtime_checkpoint)){
    $arguments.AcceleratorRuntimeCheckpoint=[string]$state.accelerator_runtime_checkpoint
  }
  if($condition.Contains('stripe_reuse_run_manifest')-and
     -not[string]::IsNullOrWhiteSpace([string]$condition.stripe_reuse_run_manifest)){
    $arguments.StripeReuseRunManifest=[string]$condition.stripe_reuse_run_manifest
    $arguments.ContinuationReuseRunManifest=[string]$condition.continuation_reuse_run_manifest
  }
  if($condition.Contains('candidate_reuse_run_manifest')-and
     -not[string]::IsNullOrWhiteSpace([string]$condition.candidate_reuse_run_manifest)){
    $arguments.CandidateReuseRunManifest=[string]$condition.candidate_reuse_run_manifest
  }
  if($condition.Contains('workpoint_qualified_run_path')-and
     -not[string]::IsNullOrWhiteSpace([string]$condition.workpoint_qualified_run_path)){
    $arguments.QualifiedWorkpointRunPath=[string]$condition.workpoint_qualified_run_path
  }elseif($condition.Contains('workpoint_resume_parent_checkpoint')-and
     -not[string]::IsNullOrWhiteSpace([string]$condition.workpoint_resume_parent_checkpoint)){
    $arguments.WorkpointResumeInitialManifest=[string]$condition.workpoint_resume_initial_manifest
    $arguments.WorkpointResumeParentCheckpoint=[string]$condition.workpoint_resume_parent_checkpoint
    $arguments.WorkpointResumeSuccessfulChildManifest=[string]$condition.workpoint_resume_successful_child_manifest
  }
  $cacheKey=Get-KCacheKey -K ([double]$condition.K)
  if($state.provider_cache.ContainsKey($cacheKey)){
    $reuse=Assert-ProviderCacheEntry -ExpectedK ([double]$condition.K) -Entry $state.provider_cache[$cacheKey]
    $reusePath=Join-Path $supportRoot ('provider_reuse_{0:D3}.json'-f([int]$condition.ordinal))
    Write-JsonAtomically -Value $reuse -Path $reusePath -Depth 6
    $arguments.ProviderReusePath=$reusePath
  }
  if($PythonExe){$arguments.PythonExe=$PythonExe}
  if($SimionExe){$arguments.SimionExe=$SimionExe}
  $invocationError=$null
  try{& $conditionRunner @arguments|Out-Host}catch{$invocationError=$_.Exception}

  $runPath=Join-Path $artifactRuns $runId
  $manifestPath=Join-Path $runPath 'run_manifest.json'
  if(-not(Test-Path -LiteralPath $manifestPath -PathType Leaf)){
    if($null-ne$invocationError){throw $invocationError}
    throw "Condition runner did not publish a run manifest: $manifestPath"
  }
  $condition.run_manifest=$manifestPath
  $terminal=$null
  try{$terminal=Read-ConditionTerminal -Condition $condition -ManifestPath $manifestPath -ExpectedRunId $runId}
  catch{Write-Checkpoint -Value $state;throw}
  if($terminal.status-in@('checkpoint','interrupted')){
    $resume=Get-NonterminalWorkpointResume -Condition $condition -ConditionRunId $runId
    if($null-ne$resume){
      $condition.workpoint_resume_initial_manifest=[string]$resume.initial_workpoint_manifest
      $condition.workpoint_resume_parent_checkpoint=[string]$resume.parent_checkpoint
      $condition.workpoint_resume_successful_child_manifest=[string]$resume.successful_child_manifest
      $condition.stripe_reuse_run_manifest=[string]$resume.stripe_run_manifest
      $condition.continuation_reuse_run_manifest=[string]$resume.continuation_run_manifest
    }
    $condition.terminal_state='pending'
    Write-Checkpoint -Value $state
    throw "Condition run remains nonterminal and will receive a new identity on restart: $manifestPath"
  }
  if($terminal.status-eq'failed'){
    $condition.terminal_state='failed';Write-Checkpoint -Value $state
    throw "Condition run terminated with status failed: $manifestPath"
  }
  $condition.workflow_outcome=$terminal.workflow_outcome
  $condition.terminal_state=if($terminal.workflow_outcome-eq'within_tolerance'){'success'}else{'warning'}
  $state.provider_cache[$cacheKey]=$terminal.provider
  $state.accelerator_runtime_checkpoint=Get-ProviderRuntimeCheckpoint -ReceiptPath ([string]$terminal.provider.runtime_receipt)
  Write-Checkpoint -Value $state
}

$comparisonPath=Join-Path $supportRoot 'comparison.json'
Write-JsonAtomically -Value (New-CampaignComparison) -Path $comparisonPath -Depth 12
$state.comparison_path=$comparisonPath
$state.status='success'
Write-Checkpoint -Value $state
$state|ConvertTo-Json -Depth 12

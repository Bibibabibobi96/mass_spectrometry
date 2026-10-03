[CmdletBinding()]
param(
  [string]$ContinuationRunManifest='',
  [string]$QualifiedWorkpointRunPath='',
  [string]$BaselineEnvelopeScreeningRunPath='',
  [string]$BaselineScreeningRunPath='',
  [string]$BaselineCohortRunPath='',
  [string]$ProbeScreeningRunPath='',
  [string]$RootScreeningRunPath='',
  [string[]]$RootScreeningRunPaths=@(),
  [string]$CompletedTe1WorkpointReclosureRunPath='',
  [string]$ReclosedRootScreeningRunPath='',
  [string]$FinalScreeningRunPath='',
  [string]$PublishedSourceReceiptPath='',
  [string]$PublishedFormalSourceReceiptPath='',
  [string]$NativeRuntimeCheckpoint='',
  [Parameter(Mandatory)][string]$GeometryReviewRunPath,
  [Parameter(Mandatory)][string]$MirrorRunPath,
  [Parameter(Mandatory)][string]$StripeRunPath,
  [Parameter(Mandatory)][string]$AcceleratorProviderReceiptPath,
  [Parameter(Mandatory)][string]$NativeCorridorBankRunPath,
  [Parameter(Mandatory)][string]$NativeSystemRuntimeBundlePath,
  [Parameter(Mandatory)][string]$SourceDefinitionPath,
  [Parameter(Mandatory)][double]$AcceleratorYAnchorMm,
  [ValidateRange(1,3)][int]$MaximumTe1RootFlights=3,
  [ValidateRange(0,2)][int]$MaximumTe1WorkpointReclosures=2,
  [string]$ContractPath='',
  [string]$RunId='',
  [string]$SimionExe='',
  [string]$PythonExe=''
)

# Thin fail-fast orchestration only.  Physics, solver execution, source
# materialization, and detector diagnostics remain in their existing runners.
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$project='parallel_mirror_dual_stripe_mr_tof'
$repoRoot=(Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$workspaceRoot=Split-Path -Parent $repoRoot
$python=if($PythonExe){[IO.Path]::GetFullPath($PythonExe)}else{Join-Path $repoRoot '.venv\Scripts\python.exe'}
$artifactRoot=Join-Path $workspaceRoot "artifacts\projects\$project"
if(-not$RunId){$RunId=(Get-Date -Format 'yyyyMMdd_HHmmss')+'__sim__simion__mrtof-native-candidate-chain'}
if(-not[double]::IsFinite($AcceleratorYAnchorMm)){throw 'AcceleratorYAnchorMm must be finite.'}
if([bool]$ContinuationRunManifest-eq[bool]$QualifiedWorkpointRunPath){
  throw 'Supply exactly one ContinuationRunManifest or QualifiedWorkpointRunPath.'
}
if($RootScreeningRunPath-and$RootScreeningRunPaths.Count){
  throw 'Supply RootScreeningRunPath or RootScreeningRunPaths, not both.'
}
$completedRootScreeningRuns=@(if($RootScreeningRunPaths.Count){
  @($RootScreeningRunPaths)
}elseif($RootScreeningRunPath){
  @($RootScreeningRunPath)
})
if($completedRootScreeningRuns.Count-gt$MaximumTe1RootFlights){
  throw 'Completed root screening runs exceed MaximumTe1RootFlights.'
}

. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')
$workpointRunner=Join-Path $PSScriptRoot 'run_downstream_workpoint_iteration.ps1'
$sourceRunner=Join-Path $PSScriptRoot 'run_publish_bunch_source.ps1'
$screeningRunner=Join-Path $PSScriptRoot 'run_native_corridor_bunch_screening.ps1'
$diagnosticRunner=Join-Path $PSScriptRoot 'run_source_z_energy_timing_diagnostic.ps1'
$analysisModule='projects.parallel_mirror_dual_stripe_mr_tof.analysis.source_z_energy_timing_diagnostic'
$focusFallbackSources=@{}

function Assert-Manifest {
  param([Parameter(Mandatory)][string]$RunPath,[Parameter(Mandatory)][string]$Status,[Parameter(Mandatory)][string]$Mode)
  $manifest=Join-Path $RunPath 'run_manifest.json'
  & $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') $manifest `
    --require-status $Status --require-project $project --require-mode $Mode|Out-Host
  if($LASTEXITCODE-ne0){throw "Run manifest verification failed: $manifest"}
  return $manifest
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

function Invoke-ProjectPython {
  param([Parameter(Mandatory)][string[]]$Arguments)
  Push-Location -LiteralPath $repoRoot;$saved=$env:PYTHONPATH
  try{
    $env:PYTHONPATH=$repoRoot
    & $python @Arguments
    if($LASTEXITCODE-ne0){throw "Python stage failed: $($Arguments -join ' ')"}
  }finally{$env:PYTHONPATH=$saved;Pop-Location}
}

function New-StageRunId {
  param(
    [Parameter(Mandatory)][ValidateSet('sim','analysis')][string]$Activity,
    [Parameter(Mandatory)][ValidateSet('simion','python')][string]$Scope,
    [Parameter(Mandatory)][string]$Subject
  )
  if($RunId-notmatch'^(?<stamp>\d{8}_\d{6})__'){throw 'Parent run_id has no valid timestamp prefix.'}
  $stamp=[string]$Matches.stamp
  $revision=if($RunId-match'__r(?<retry>\d{2})$'){"__r$($Matches.retry)"}else{''}
  return "$stamp`__$Activity`__$Scope`__$Subject$revision"
}

function Read-ScreeningResult {
  param([Parameter(Mandatory)][string]$RunPath)
  $null=Assert-Manifest -RunPath $RunPath -Status success -Mode native_corridor_candidate_bunch_screening
  $path=Join-Path $RunPath 'results\bunch_screening_result.json'
  if(-not(Test-Path -LiteralPath $path -PathType Leaf)){throw "Screening result is missing: $path"}
  $value=Get-Content -LiteralPath $path -Raw|ConvertFrom-Json -AsHashtable
  if($value.status-notin@('complete','hard_stop')){throw "Screening result is incomplete: $path"}
  return $value
}

function Test-SameResolvedPath {
  param([Parameter(Mandatory)][string]$First,[Parameter(Mandatory)][string]$Second)
  return [string]::Equals(
    (Resolve-Path -LiteralPath $First).Path,(Resolve-Path -LiteralPath $Second).Path,
    [StringComparison]::OrdinalIgnoreCase
  )
}

function Test-SameVoltageVector {
  param([Parameter(Mandatory)]$First,[Parameter(Mandatory)]$Second)
  $left=@($First);$right=@($Second)
  if($left.Count-ne$right.Count-or$left.Count-eq0){return $false}
  for($index=0;$index-lt$left.Count;$index++){
    $leftValue=[double]$left[$index];$rightValue=[double]$right[$index]
    if(-not[double]::IsFinite($leftValue)-or-not[double]::IsFinite($rightValue)-or$leftValue-ne$rightValue){
      return $false
    }
  }
  return $true
}

function Assert-WorkpointPhysicalBinding {
  param(
    [Parameter(Mandatory)][string]$WorkpointRun,
    [Parameter(Mandatory)][string]$ExpectedGeometryRun,
    [Parameter(Mandatory)][string]$ExpectedMirrorRun,
    [Parameter(Mandatory)][string]$ExpectedStripeRun,
    [Parameter(Mandatory)][string]$ExpectedProviderReceipt,
    [Parameter(Mandatory)][string]$ExpectedRuntimeBundle,
    [string]$ExpectedContract=''
  )
  $config=Get-Content -LiteralPath (Join-Path $WorkpointRun 'run_config.json') -Raw|ConvertFrom-Json -AsHashtable
  $problem=$config.parameters.native_recovery_problem
  foreach($binding in @(
    @('geometry',[string]$problem.geometry,$ExpectedGeometryRun),
    @('mirror',[string]$problem.mirror,$ExpectedMirrorRun),
    @('stripe',[string]$problem.stripe,$ExpectedStripeRun),
    @('accelerator provider',[string]$problem.accelerator_provider_receipt,$ExpectedProviderReceipt)
  )){
    if(-not(Test-SameResolvedPath -First $binding[1] -Second $binding[2])){
      throw "Qualified workpoint uses a different $($binding[0]) authority."
    }
  }
  $actualBundle=(Get-FileHash -LiteralPath ([string]$problem.native_system_runtime_bundle) -Algorithm SHA256).Hash
  $expectedBundle=(Get-FileHash -LiteralPath $ExpectedRuntimeBundle -Algorithm SHA256).Hash
  if($actualBundle-ne$expectedBundle){throw 'Qualified workpoint uses a different native field bundle.'}
  if($ExpectedContract){
    $contractHash=(Get-FileHash -LiteralPath $ExpectedContract -Algorithm SHA256).Hash
    if($contractHash-ne[string]$problem.contract_sha256){throw 'Qualified workpoint uses a different condition contract.'}
  }
}

function Assert-ScreeningEvidenceBinding {
  param(
    [Parameter(Mandatory)][string]$CohortRun,
    [Parameter(Mandatory)][string]$ExpectedWorkpointRun,
    [Parameter(Mandatory)][string]$ExpectedSourceReceipt,
    [Parameter(Mandatory)][string]$ExpectedNativeBankRun,
    [string]$ExpectedVariation=''
  )
  $cohortConfig=Get-Content -LiteralPath (Join-Path $CohortRun 'run_config.json') -Raw|ConvertFrom-Json -AsHashtable
  $cohortSummary=Get-Content -LiteralPath (Join-Path $CohortRun 'summary.json') -Raw|ConvertFrom-Json -AsHashtable
  $workpointConfig=Get-Content -LiteralPath (Join-Path $ExpectedWorkpointRun 'run_config.json') -Raw|ConvertFrom-Json -AsHashtable
  $workpointHandoff=Get-Content -LiteralPath (Join-Path $ExpectedWorkpointRun 'results\best_physical_workpoint_handoff.json') -Raw|ConvertFrom-Json -AsHashtable
  $problem=$workpointConfig.parameters.native_recovery_problem
  $expectedVoltages=@($workpointHandoff.selected_workpoint.voltages_v)
  $actualVoltages=@($cohortSummary.stripe_biases_v)+@($cohortSummary.prism_voltages_v)
  if(-not(Test-SameVoltageVector -First $actualVoltages -Second $expectedVoltages)){
    throw 'Screening evidence uses different P/S workpoint voltages.'
  }
  $expectedSourceManifest=Join-Path (Split-Path -Parent (Split-Path -Parent $ExpectedSourceReceipt)) 'run_manifest.json'
  $expectedProviderManifest=Join-Path (Split-Path -Parent (Split-Path -Parent ([string]$problem.accelerator_provider_receipt))) 'run_manifest.json'
  foreach($binding in @(
    @('source',[string]$cohortConfig.inputs.bunch_source_run_manifest,$expectedSourceManifest),
    @('native field bank',[string]$cohortConfig.inputs.geometry_run_manifest,(Join-Path $ExpectedNativeBankRun 'run_manifest.json')),
    @('mirror authority',[string]$cohortConfig.inputs.mirror_run_manifest,(Join-Path ([string]$problem.mirror) 'run_manifest.json')),
    @('stripe authority',[string]$cohortConfig.inputs.stripe_run_manifest,(Join-Path ([string]$problem.stripe) 'run_manifest.json')),
    @('accelerator provider',[string]$cohortConfig.inputs.accelerator_run_manifest,$expectedProviderManifest)
  )){
    if(-not(Test-SameResolvedPath -First $binding[1] -Second $binding[2])){
      throw "Screening evidence uses a different $($binding[0])."
    }
  }
  foreach($binding in @(
    @('native field bundle',[string]$cohortConfig.inputs.native_system_runtime_bundle,[string]$problem.native_system_runtime_bundle),
    @('condition contract',[string]$cohortConfig.inputs.trajectory_contract,(Join-Path $ExpectedWorkpointRun 'inputs\contract.json'))
  )){
    $actualHash=(Get-FileHash -LiteralPath $binding[1] -Algorithm SHA256).Hash
    $expectedHash=(Get-FileHash -LiteralPath $binding[2] -Algorithm SHA256).Hash
    if($actualHash-ne$expectedHash){throw "Screening evidence uses a different $($binding[0])."}
  }
  $workpointVariation=if($workpointConfig.inputs.ContainsKey('terminal_time_mirror_voltage_variation')){
    [string]$workpointConfig.inputs.terminal_time_mirror_voltage_variation
  }else{''}
  $expectedVariationPath=if($ExpectedVariation){$ExpectedVariation}else{$workpointVariation}
  $cohortVariation=if($cohortConfig.inputs.ContainsKey('terminal_time_mirror_voltage_variation')){
    [string]$cohortConfig.inputs.terminal_time_mirror_voltage_variation
  }else{''}
  if($expectedVariationPath){
    if(-not$cohortVariation){throw 'Screening evidence omits the selected mirror-voltage variation.'}
    $expectedMirror=@((Get-Content -LiteralPath $expectedVariationPath -Raw|ConvertFrom-Json -AsHashtable).target_mirror_voltages_v)
    $actualMirror=@((Get-Content -LiteralPath $cohortVariation -Raw|ConvertFrom-Json -AsHashtable).target_mirror_voltages_v)
  }else{
    if($cohortVariation){throw 'Screening evidence adds an unexpected mirror-voltage variation.'}
    $expectedMirror=@((Get-Content -LiteralPath (Join-Path ([string]$problem.mirror) 'results\fixed_grid_voltage_point.json') -Raw|ConvertFrom-Json -AsHashtable).mirror_voltages_v)
    $actualMirror=@((Get-Content -LiteralPath ([string]$cohortConfig.inputs.fixed_mirror_stripe_downstream_authority) -Raw|ConvertFrom-Json -AsHashtable).mirror_voltages_v)
  }
  if(-not(Test-SameVoltageVector -First $actualMirror -Second $expectedMirror)){
    throw 'Screening evidence uses different mirror voltages.'
  }
}

function Read-ScreeningEvidence {
  param(
    [Parameter(Mandatory)][string]$RunPath,
    [Parameter(Mandatory)][ValidateSet('formal','focus','envelope')][string]$Scope,
    [Parameter(Mandatory)][string]$ExpectedWorkpointRun,
    [Parameter(Mandatory)][string]$ExpectedSourceReceipt,
    [Parameter(Mandatory)][string]$ExpectedNativeBankRun,
    [string]$ExpectedVariation='',
    [string]$ExpectedSourceStatesSha256=''
  )
  $childRun=(Resolve-Path -LiteralPath $RunPath).Path
  $result=Read-ScreeningResult -RunPath $childRun
  $cohortRun=Split-Path -Parent ([string]$result.cohort_run_manifest)
  $summaryPath=Join-Path $cohortRun 'summary.json'
  if(-not(Test-Path -LiteralPath $summaryPath -PathType Leaf)){
    throw "Screening cohort summary is missing: $summaryPath"
  }
  $summary=Get-Content -LiteralPath $summaryPath -Raw|ConvertFrom-Json -AsHashtable
  Assert-ScreeningEvidenceBinding -CohortRun $cohortRun -ExpectedWorkpointRun $ExpectedWorkpointRun `
    -ExpectedSourceReceipt $ExpectedSourceReceipt -ExpectedNativeBankRun $ExpectedNativeBankRun `
    -ExpectedVariation $ExpectedVariation
  $variationPath=Join-Path $cohortRun 'simion\terminal_time_mirror_voltage_variation.json'
  $te1Coordinate=0.0
  if(Test-Path -LiteralPath $variationPath -PathType Leaf){
    $variation=Get-Content -LiteralPath $variationPath -Raw|ConvertFrom-Json -AsHashtable
    $te1Coordinate=[double]$variation.coordinate
    if(-not[double]::IsFinite($te1Coordinate)){throw 'Screening TE1 coordinate is invalid.'}
  }else{$variationPath=''}
  $particleCount=[int]$summary.source_particle_count
  $purpose=[string]$result.purpose
  $evidenceScope=switch($particleCount){
    3 {
      if($purpose-ne'focus_z'){throw 'N=3 screening evidence must be a focus_z diagnostic.'}
      'focus_only_n3'
    }
    13 {
      if($purpose-ne'controlled_aberration'){
        throw 'N=13 screening evidence must be a controlled_aberration diagnostic.'
      }
      'controlled_envelope_n13'
    }
    100 {
      if($purpose-ne'candidate_bunch_metrics'){
        throw 'N=100 screening evidence must contain candidate bunch metrics.'
      }
      'complete_n100_formal_volume'
    }
    default {throw 'Screening evidence must contain N=3, N=13, or N=100.'}
  }
  if($Scope-eq'formal'-and$particleCount-ne100){throw 'Formal screening evidence must contain N=100.'}
  if($Scope-eq'focus'-and$particleCount-ne3){throw 'Focus screening evidence must contain N=3.'}
  if($ExpectedSourceStatesSha256){
    $actualSourceStatesSha256=[string]$summary.source_cohort.selection.parent_particle_states_sha256
    if($actualSourceStatesSha256-ne$ExpectedSourceStatesSha256){
      throw 'Screening evidence does not use the current frozen source sequence.'
    }
  }
  return [pscustomobject]@{
    run=$childRun;result=$result;particle_count=$particleCount;purpose=$purpose
    evidence_scope=$evidenceScope;envelope_available=($particleCount-in@(13,100))
    te1_coordinate=$te1Coordinate;variation_path=$variationPath
  }
}

function Read-CollectionGate {
  param([Parameter(Mandatory)]$ScreeningResult)
  $path=(Resolve-Path -LiteralPath ([string]$ScreeningResult.cohort_collection_gate)).Path
  $gate=Get-Content -LiteralPath $path -Raw|ConvertFrom-Json -AsHashtable
  if($gate.role-ne'mrtof_bunch_collection_gate'-or$null-eq$gate.hard_stop-or$null-eq$gate.continue_downstream){
    throw "Bunch collection gate is invalid: $path"
  }
  return $gate
}

function Test-CollectionAccepted {
  param([Parameter(Mandatory)]$Gate)
  return $Gate.status-eq'accepted'-and-not[bool]$Gate.warning-and
    -not[bool]$Gate.hard_stop-and[bool]$Gate.continue_downstream-and
    [double]$Gate.detection_rate-ge[double]$Gate.preferred_minimum
}

function Read-CenterWorkpointGate {
  param([Parameter(Mandatory)]$ScreeningResult,[Parameter(Mandatory)]$ContractDocument)
  $cohortRun=Split-Path -Parent ([string]$ScreeningResult.cohort_run_manifest)
  $observationPath=Join-Path $cohortRun 'results\two_prism_trial_observation.json'
  if(-not(Test-Path -LiteralPath $observationPath -PathType Leaf)){
    throw "Cohort centre observation is missing: $observationPath"
  }
  $observation=Get-Content -LiteralPath $observationPath -Raw|ConvertFrom-Json -AsHashtable
  $validation=$observation.center_particle_workpoint_validation
  $tolerances=$ContractDocument.downstream_fixed_grid_workpoint_profile.automatic_iteration.acceptance_tolerances
  $names=@(
    'P1_P2_positive_mirror_turn_y_mm',
    'P1_P2_P2_shield_low_field_angle_degrees',
    'Stripe_slow_turn_y_minus_L_mm',
    'Stripe_target_phase_y_minus_origin_mm'
  )
  $failed=@()
  if(-not($validation-is[Collections.IDictionary])-or$validation.status-ne'observed'){
    $failed+='center_particle_workpoint_observation_incomplete'
  }else{
    foreach($name in $names){
      $value=[double]$validation.physical_acceptance_residuals[$name]
      $limit=[double]$tolerances[$name]
      if(-not[double]::IsFinite($value)-or-not[double]::IsFinite($limit)-or$limit-le0-or[math]::Abs($value)-gt$limit){
        $failed+=$name
      }
    }
  }
  return [ordered]@{
    passed=($failed.Count-eq0);failed=@($failed);validation=$validation
    observation=$observationPath
  }
}

function Invoke-Screening {
  param(
    [Parameter(Mandatory)][string]$Stage,
    [Parameter(Mandatory)][string]$WorkpointRun,
    [Parameter(Mandatory)][string]$SourceReceipt,
    [string]$Variation='',
    [string]$ExistingCohortRun='',
    [ValidateSet(3,13,100)][int]$ParticleCount=100,
    [switch]$FocusDiagnosticOnly,
    [ValidateSet('','controlled_aberration')][string]$DiagnosticPurpose=''
  )
  $childId=New-StageRunId -Activity sim -Scope simion -Subject "mrtof-$Stage-screen"
  $arguments=@{
    WorkpointRunPath=$WorkpointRun;NativeCorridorBankRunPath=$NativeCorridorBankRunPath
    BunchSourceReceiptPath=$SourceReceipt;CohortParticleCount=$ParticleCount;RunId=$childId;PythonExe=$python
  }
  if($FocusDiagnosticOnly){$arguments.FocusDiagnosticOnly=$true}
  if($DiagnosticPurpose){$arguments.DiagnosticPurpose=$DiagnosticPurpose}
  if($Variation){$arguments.MirrorVoltageVariationPath=$Variation}
  if($ExistingCohortRun){$arguments.InitialCohortRunPath=$ExistingCohortRun}
  if($SimionExe){$arguments.SimionExe=$SimionExe}
  & $screeningRunner @arguments|Out-Host
  $childRun=Join-Path $artifactRoot "runs\$childId"
  $scope=if($FocusDiagnosticOnly){'focus'}elseif($DiagnosticPurpose){'envelope'}else{'formal'}
  return Read-ScreeningEvidence -RunPath $childRun -Scope $scope -ExpectedWorkpointRun $WorkpointRun `
    -ExpectedSourceReceipt $SourceReceipt -ExpectedNativeBankRun $NativeCorridorBankRunPath `
    -ExpectedVariation $Variation
}

function Get-FocusFallbackSourceReceipt {
  param(
    [Parameter(Mandatory)][ValidateSet(10,5)][int]$HalfSpanPercent,
    [Parameter(Mandatory)][string]$BaseDefinition,
    [Parameter(Mandatory)][string]$GeometryContract
  )
  $key=[string]$HalfSpanPercent
  if($focusFallbackSources.ContainsKey($key)){return [string]$focusFallbackSources[$key]}
  $definition=Get-Content -LiteralPath $BaseDefinition -Raw|ConvertFrom-Json -AsHashtable
  $null=$definition.Remove('controlled_focus_half_span_mm')
  $definition.controlled_focus_half_span_fraction_of_radius=$HalfSpanPercent/100.0
  $definitionPath=Join-Path $package.input_dir "focus_source_definition_p${HalfSpanPercent}.json"
  Write-RunJson -Path $definitionPath -Depth 30 -Value $definition
  $sourceId=New-StageRunId -Activity analysis -Scope python -Subject "mrtof-focus-source-p${HalfSpanPercent}"
  & $sourceRunner -SourceDefinitionPath $definitionPath -GeometryContractPath $GeometryContract `
    -AcceleratorProviderReceiptPath $AcceleratorProviderReceiptPath -RunId $sourceId -PythonExe $python|Out-Host
  $sourceRun=Join-Path $artifactRoot "runs\$sourceId"
  $null=Assert-Manifest -RunPath $sourceRun -Status success -Mode deterministic_bunch_source_materialization
  $receipt=Join-Path $sourceRun 'results\bunch_source_receipt.json'
  $focusFallbackSources[$key]=$receipt
  return $receipt
}

function Resolve-DetectorFocusSample {
  param(
    [Parameter(Mandatory)][string]$Stage,
    [Parameter(Mandatory)]$FormalSample,
    [Parameter(Mandatory)][string]$FormalDiagnostic,
    [Parameter(Mandatory)][string]$WorkpointRun,
    [Parameter(Mandatory)][string]$BaseDefinition,
    [Parameter(Mandatory)][string]$GeometryContract,
    [string]$Variation=''
  )
  if([bool]$FormalSample.available){
    return [pscustomobject]@{
      sample=$FormalSample;diagnostic=$FormalDiagnostic;formal_diagnostic=$FormalDiagnostic
      half_span_percent=20;particle_count=[int]$FormalSample.particle_count;fallback_runs=@()
    }
  }
  $fallbackRuns=@();$lastSample=$FormalSample;$lastDiagnostic=$FormalDiagnostic
  foreach($percent in @(10,5)){
    $receipt=Get-FocusFallbackSourceReceipt -HalfSpanPercent $percent `
      -BaseDefinition $BaseDefinition -GeometryContract $GeometryContract
    $micro=Invoke-Screening -Stage "$Stage-focus-p${percent}" -WorkpointRun $WorkpointRun `
      -SourceReceipt $receipt -Variation $Variation -ParticleCount 3 -FocusDiagnosticOnly
    $microDiagnostic=Invoke-Diagnostic -Stage "$Stage-focus-p${percent}" `
      -FlightManifest ([string]$micro.result.cohort_run_manifest)
    $microSample=Read-DetectorFocusSample -Path $microDiagnostic
    $fallbackRuns+=,[ordered]@{
      half_span_percent=$percent;screening_run_manifest=(Join-Path $micro.run 'run_manifest.json')
      diagnostic=$microDiagnostic;available=[bool]$microSample.available
    }
    $lastSample=$microSample;$lastDiagnostic=$microDiagnostic
    if([bool]$microSample.available){
      return [pscustomobject]@{
        sample=$microSample;diagnostic=$microDiagnostic;formal_diagnostic=$FormalDiagnostic
        half_span_percent=$percent;particle_count=3;fallback_runs=@($fallbackRuns)
      }
    }
  }
  $lastSample.reason='minimum_5_percent_pair_did_not_both_reach_detector__condition_unsuitable_for_te1_focus'
  return [pscustomobject]@{
    sample=$lastSample;diagnostic=$lastDiagnostic;formal_diagnostic=$FormalDiagnostic
    half_span_percent=5;particle_count=3;fallback_runs=@($fallbackRuns)
  }
}

function Invoke-Diagnostic {
  param([Parameter(Mandatory)][string]$Stage,[Parameter(Mandatory)][string]$FlightManifest)
  $flightRun=Split-Path -Parent $FlightManifest
  $childId=New-StageRunId -Activity analysis -Scope python -Subject "mrtof-$Stage-diagnostic"
  & $diagnosticRunner -FlightRunPath $flightRun -RunId $childId -PythonExe $python|Out-Host
  $childRun=Join-Path $artifactRoot "runs\$childId"
  $null=Assert-Manifest -RunPath $childRun -Status success -Mode source_z_energy_timing_diagnostic
  return Join-Path $childRun 'results\source_z_energy_timing_diagnostic.json'
}

function Read-DetectorFocusSample {
  param([Parameter(Mandatory)][string]$Path)
  $value=Get-Content -LiteralPath $Path -Raw|ConvertFrom-Json -AsHashtable
  $controlled=$value.controlled_detector_focus
  $timing=$value.terminal_plane_diagnostic.detector_plane.absolute_time
  if(-not($controlled-is[Collections.IDictionary])){
    throw 'Controlled detector-focus response is missing from the diagnostic.'
  }
  $median=[double]$timing.median
  $particleCount=[int]$value.cohort.particle_count
  $hits=[int]$value.cohort.detector_hit_count
  if($controlled.status-eq'unavailable'){
    if($controlled.reason-ne'one_or_both_controlled_z_particles_did_not_reach_detector'){
      throw 'Controlled detector-focus unavailable reason is invalid.'
    }
    return [pscustomobject]@{
      diagnostic=$Path;available=$false;slope_us_per_mm=$null;median_tof_us=$median;detector_hits=$hits
      particle_count=$particleCount
      controlled_particle_ids=@($controlled.particle_ids);reason=[string]$controlled.reason
    }
  }
  if($controlled.status-ne'observed'){
    throw 'Controlled detector-focus status is invalid.'
  }
  $slope=[double]$controlled.dt_d_initial_z_us_per_mm
  if($hits-lt2-or-not[double]::IsFinite($slope)-or-not[double]::IsFinite($median)-or$median-le0){
    throw 'Detector focus sample lacks a finite controlled detector-plane response.'
  }
  return [pscustomobject]@{
    diagnostic=$Path;available=$true;slope_us_per_mm=$slope;median_tof_us=$median;detector_hits=$hits
    particle_count=$particleCount
    controlled_particle_ids=@($controlled.particle_ids)
  }
}

function Read-Z0FocusClassification {
  param(
    [Parameter(Mandatory)][string]$Path,
    [Parameter(Mandatory)][double]$SlopeToleranceUsPerMm,
    [Parameter(Mandatory)][double]$MinimumMassResolution
  )
  $value=Get-Content -LiteralPath $Path -Raw|ConvertFrom-Json -AsHashtable
  $z0=$value.central_plane_focus_history.target_return_crossing
  if(-not($z0-is[Collections.IDictionary])-or$z0.status-ne'observed'){
    return [ordered]@{
      primary='topology_or_upstream_loss';labels=@('topology_or_upstream_loss')
      status=$(if($z0-is[Collections.IDictionary]){[string]$z0.status}else{'missing'})
      reason=$(if($z0-is[Collections.IDictionary]){[string]$z0.reason}else{'target_z0_diagnostic_missing'})
    }
  }
  $slope=[double]$z0.focus_residual_us_per_mm
  $median=[double]$z0.absolute_time.median
  $fwhm=if($null-eq$z0.absolute_time.fwhm){$null}else{[double]$z0.absolute_time.fwhm}
  if(-not[double]::IsFinite($slope)-or-not[double]::IsFinite($median)-or$median-le0-or
    ($null-ne$fwhm-and(-not[double]::IsFinite($fwhm)-or$fwhm-le0))){
    throw 'Observed z=0 focus diagnostic is numerically invalid.'
  }
  $resolution=$z0.absolute_time.time_equivalent_resolution
  $labels=[Collections.Generic.List[string]]::new()
  if([math]::Abs($slope)-gt$SlopeToleranceUsPerMm){
    $labels.Add('first_order_broadening_enter_te1')
  }elseif($null-eq$resolution-or$resolution-lt$MinimumMassResolution){
    $labels.Add('higher_order_or_phase_space_warning')
  }else{
    $labels.Add('z0_focus_response_within_current_diagnostic_budget')
  }
  $detectorFwhm=$value.terminal_plane_diagnostic.detector_plane.absolute_time.fwhm
  if($null-ne$fwhm-and$null-ne$detectorFwhm-and[double]$detectorFwhm-gt$fwhm){
    $labels.Add('downstream_detector_leg_contribution')
  }
  return [ordered]@{
    primary=$labels[0];labels=@($labels);status='observed';reached_particle_count=[int]$z0.reached_particle_count
    dt_d_initial_z_us_per_mm=$slope;slope_tolerance_us_per_mm=$SlopeToleranceUsPerMm
    mass_resolution_t_over_2fwhm=$resolution
    qualification='diagnostic_classification_only__not_a_te1_precondition'
  }
}

function Get-QualifiedCenterSeedManifest {
  param([Parameter(Mandatory)][string]$WorkpointRun,[Parameter(Mandatory)]$Handoff)
  $ordinal=[int]$Handoff.selected_history_ordinal
  $lineagePath=Join-Path $WorkpointRun 'results\iteration_lineage.json'
  $lineage=Get-Content -LiteralPath $lineagePath -Raw|ConvertFrom-Json -AsHashtable
  $matches=@($lineage.children|Where-Object{[int]$_.iteration-eq$ordinal})
  if($ordinal-ge1-and$matches.Count-eq1){
    return (Resolve-Path -LiteralPath ([string]$matches[0].child_manifest)).Path
  }
  # Recovery probes are included in the handoff history ordinal but not in the
  # accepted-iteration lineage. Resolve that case by the selected four voltages.
  $target=@($Handoff.selected_workpoint.voltages_v|ForEach-Object{[double]$_})
  $matches=@($lineage.children|Where-Object{
    $materialization=[string]$_.materialization
    if(-not(Test-Path -LiteralPath $materialization -PathType Leaf)){return $false}
    $value=Get-Content -LiteralPath $materialization -Raw|ConvertFrom-Json -AsHashtable
    $actual=@($value.stripe_biases_v)+@($value.prism_voltages_v)
    if($target.Count-ne4-or$actual.Count-ne4){return $false}
    for($index=0;$index-lt4;$index++){
      if([math]::Abs([double]$actual[$index]-$target[$index])-gt1e-9){return $false}
    }
    return $true
  })
  if($matches.Count-ne1){
    throw 'Qualified workpoint handoff does not identify one centre-flight manifest.'
  }
  return (Resolve-Path -LiteralPath ([string]$matches[0].child_manifest)).Path
}

function Invoke-Te1WorkpointReclosure {
  param(
    [Parameter(Mandatory)][int]$Attempt,
    [Parameter(Mandatory)][string]$SeedManifest,
    [Parameter(Mandatory)][string]$Variation,
    [Parameter(Mandatory)][string]$CurrentContractPath,
    [Parameter(Mandatory)][string]$RuntimeCheckpoint
  )
  $childId=New-StageRunId -Activity sim -Scope simion -Subject ('mrtof-te1-reclose-{0:D2}'-f$Attempt)
  $arguments=@{
    SeedTrialManifest=$SeedManifest;MirrorVoltageVariationPath=$Variation
    NativeCorridorBankRunPath=$NativeCorridorBankRunPath;GeometryReviewRunPath=$GeometryReviewRunPath
    MirrorRunPath=$MirrorRunPath;StripeRunPath=$StripeRunPath
    AcceleratorProviderReceiptPath=$AcceleratorProviderReceiptPath
    NativeSystemRuntimeBundlePath=$NativeSystemRuntimeBundlePath
    AcceleratorYAnchorMm=$AcceleratorYAnchorMm;AcceleratorSourceYOffsetMm=$sourceYOffsetMm
    ContractPath=$CurrentContractPath;RunId=$childId;PythonExe=$python
    NativeRuntimeCheckpoint=$RuntimeCheckpoint
  }
  if($SimionExe){$arguments.SimionExe=$SimionExe}
  & $workpointRunner @arguments|Out-Host
  $childRun=Join-Path $artifactRoot "runs\$childId"
  $manifest=Assert-Manifest -RunPath $childRun -Status checkpoint -Mode downstream_fixed_grid_workpoint_iteration
  $handoffPath=Join-Path $childRun 'results\best_physical_workpoint_handoff.json'
  if(-not(Test-Path -LiteralPath $handoffPath -PathType Leaf)){
    throw 'TE1 workpoint reclosure did not publish a qualified centre handoff.'
  }
  $handoff=Get-Content -LiteralPath $handoffPath -Raw|ConvertFrom-Json -AsHashtable
  if($handoff.status-ne'within_tolerance'-or$handoff.qualification-ne'candidate_bunch_screening_authorized'){
    throw 'TE1 workpoint reclosure did not satisfy every centre tolerance.'
  }
  return [pscustomobject]@{run=$childRun;manifest=$manifest;handoff=$handoff}
}

function Read-CompletedTe1WorkpointReclosure {
  param(
    [Parameter(Mandatory)][string]$RunPath,
    [Parameter(Mandatory)][string]$Variation
  )
  $childRun=(Resolve-Path -LiteralPath $RunPath).Path
  $manifest=Assert-Manifest -RunPath $childRun -Status checkpoint -Mode downstream_fixed_grid_workpoint_iteration
  $handoffPath=Join-Path $childRun 'results\best_physical_workpoint_handoff.json'
  if(-not(Test-Path -LiteralPath $handoffPath -PathType Leaf)){
    throw 'Completed TE1 workpoint reclosure lacks a qualified centre handoff.'
  }
  $handoff=Get-Content -LiteralPath $handoffPath -Raw|ConvertFrom-Json -AsHashtable
  if($handoff.status-ne'within_tolerance'-or$handoff.qualification-ne'candidate_bunch_screening_authorized'){
    throw 'Completed TE1 workpoint reclosure did not satisfy every centre tolerance.'
  }
  $centerManifest=Get-QualifiedCenterSeedManifest -WorkpointRun $childRun -Handoff $handoff
  $centerMaterialization=Get-Content -LiteralPath (Join-Path (Split-Path -Parent $centerManifest) `
    'results\two_prism_trial_materialization.json') -Raw|ConvertFrom-Json -AsHashtable
  $variationData=Get-Content -LiteralPath $Variation -Raw|ConvertFrom-Json -AsHashtable
  $expectedMirror=@($variationData.target_mirror_voltages_v|ForEach-Object{[double]$_})
  $actualMirror=@($centerMaterialization.mirror_voltages_v|ForEach-Object{[double]$_})
  $actualCoordinate=[double]$centerMaterialization.terminal_time_mirror_variation.coordinate
  if($expectedMirror.Count-ne5-or$actualMirror.Count-ne$expectedMirror.Count-or
    [math]::Abs($actualCoordinate-[double]$variationData.coordinate)-gt1e-12-or
    @((0..($expectedMirror.Count-1))|Where-Object{
      [math]::Abs($actualMirror[$_]-$expectedMirror[$_])-gt1e-9
    }).Count-ne0){
    throw 'Completed TE1 workpoint reclosure belongs to different mirror voltages.'
  }
  return [pscustomobject]@{run=$childRun;manifest=$manifest;handoff=$handoff}
}

$package=New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot `
  -RunId $RunId -Project $project -Mode 'native_candidate_end_to_end_chain' `
  -Software @('SIMION 2020','Python 3.11') -RetentionContractEnabled -RetentionClass compact `
  -CapacityLedgerLifecycleEnabled
$terminalized=$false;$failureStage='preflight';$repairedHandoff=$null;$capacitySession=$null

function Complete-FocusResponseUnavailable {
  param(
    [Parameter(Mandatory)][string]$Stage,
    [Parameter(Mandatory)]$Sample,
    [Parameter(Mandatory)]$Baseline,
    $Probe=$null,
    $Root=$null
  )
  Write-RunJson -Path $package.summary -Depth 30 -Value ([ordered]@{
    schema_version=1;role='mrtof_native_candidate_end_to_end_chain_summary';status='success'
    workflow_outcome='warning_focus_response_unavailable__continue_parameter_scan'
    qualification='paired_n100_candidate_warning__continue_parameter_scan'
    workpoint_run_manifest=$workpointManifest
    diagnostic_source_receipt=$diagnosticSourceReceipt;formal_volume_source_receipt=$formalSourceReceipt
    baseline_screening_run_manifest=(Join-Path $Baseline.run 'run_manifest.json')
    probe_screening_run_manifest=$(if($null-ne$Probe){Join-Path $Probe.run 'run_manifest.json'}else{$null})
    root_screening_run_manifest=$(if($null-ne$Root){Join-Path $Root.run 'run_manifest.json'}else{$null})
    detector_plane_focus=[ordered]@{
      status='unavailable';stage=$Stage;diagnostic=$Sample.diagnostic;reason=$Sample.reason
      detector_hits=$Sample.detector_hits;controlled_particle_ids=@($Sample.controlled_particle_ids)
      iterations=@();workpoint_reclosures=@()
    }
    z0_focus_classification=$baselineZ0Classification
    collection=[ordered]@{baseline=$baselineCollectionGate;focused=$null;satisfied=$false}
    center_workpoint=[ordered]@{baseline=$baselineCenterGate;focused=$null;satisfied=$false}
  })
  $retention=Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config
  $terminal=Update-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot `
    -Session $capacitySession -RemainingCommittedNewBytes 0
  $script:capacitySession=$terminal.session
  $terminalPath=Join-Path $package.result_dir 'artifact_capacity_gate_terminal.json'
  Write-RunJson -Path $terminalPath -Depth 14 -Value $terminal
  $outputs=@($package.summary,$startup,$terminalPath,$retention)
  if($null-ne$repairedHandoff){$outputs+=$repairedHandoff}
  Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config -Status success `
    -Software @('SIMION 2020','Python 3.11') -Outputs $outputs
  $script:terminalized=$true
  Write-Warning 'warning_focus_response_unavailable__continue_parameter_scan'
}

function Complete-BaselineCollectionHardStop {
  param([Parameter(Mandatory)]$Baseline)
  Write-RunJson -Path $package.summary -Depth 30 -Value ([ordered]@{
    schema_version=1;role='mrtof_native_candidate_end_to_end_chain_summary';status='success'
    workflow_outcome='warning_collection_below_hard_minimum__continue_parameter_scan'
    qualification='baseline_n100_collection_hard_stop__continue_parameter_scan'
    workpoint_run_manifest=$workpointManifest
    diagnostic_source_receipt=$diagnosticSourceReceipt;formal_volume_source_receipt=$formalSourceReceipt
    baseline_screening_run_manifest=(Join-Path $Baseline.run 'run_manifest.json')
    baseline_diagnostic=$baselineDiagnostic
    prism_observation=$baselineCenterGate.observation
    detector_plane_focus=[ordered]@{
      status='diagnostic_only__te1_not_started';baseline=$baselineFocusSample;iterations=@();workpoint_reclosures=@()
    }
    z0_focus_classification=$baselineZ0Classification
    collection=[ordered]@{baseline=$baselineCollectionGate;focused=$null;satisfied=$false}
    center_workpoint=[ordered]@{baseline=$baselineCenterGate;focused=$null;satisfied=[bool]$baselineCenterGate.passed}
  })
  $retention=Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config
  $terminal=Update-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot `
    -Session $capacitySession -RemainingCommittedNewBytes 0
  $script:capacitySession=$terminal.session
  $terminalPath=Join-Path $package.result_dir 'artifact_capacity_gate_terminal.json'
  Write-RunJson -Path $terminalPath -Depth 14 -Value $terminal
  $outputs=@($package.summary,$startup,$terminalPath,$retention)
  if($null-ne$repairedHandoff){$outputs+=$repairedHandoff}
  Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config -Status success `
    -Software @('SIMION 2020','Python 3.11') -Outputs $outputs
  $script:terminalized=$true
  Write-Warning 'warning_collection_below_hard_minimum__continue_parameter_scan'
}
try{
  $failureStage='capacity_startup'
  $protectedPaths=@($package.artifact_run_dir,$QualifiedWorkpointRunPath,$ContinuationRunManifest,
    $BaselineEnvelopeScreeningRunPath,$BaselineScreeningRunPath,$BaselineCohortRunPath,
    $ProbeScreeningRunPath,$completedRootScreeningRuns,
    $CompletedTe1WorkpointReclosureRunPath,$ReclosedRootScreeningRunPath,$FinalScreeningRunPath,
    $PublishedSourceReceiptPath,$PublishedFormalSourceReceiptPath,$NativeCorridorBankRunPath)|
    Where-Object{-not[string]::IsNullOrWhiteSpace([string]$_)}
  $capacitySession=Enter-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot `
    -ArtifactRoot (Join-Path $workspaceRoot 'artifacts') -RunDirectory $package.artifact_run_dir `
    -CommittedNewBytes 10485760 -ProtectedPaths $protectedPaths -Owner "mrtof-native-candidate-chain:$RunId"
  $startup=Join-Path $package.result_dir 'artifact_capacity_gate_startup.json'
  Write-RunJson -Path $startup -Depth 20 -Value $capacitySession

  $failureStage='freeze_inputs'
  $sourceDefinition=Copy-VerifiedRunInput -Source (Resolve-Path -LiteralPath $SourceDefinitionPath).Path `
    -Destination (Join-Path $package.input_dir 'bunch_source_definition.json')
  $sourceDefinitionData=Get-Content -LiteralPath $sourceDefinition -Raw|ConvertFrom-Json -AsHashtable
  $providerReceipt=(Resolve-Path -LiteralPath $AcceleratorProviderReceiptPath).Path
  $providerData=Get-Content -LiteralPath $providerReceipt -Raw|ConvertFrom-Json -AsHashtable
  $providerProjection=$providerData.mrtof_projection
  if($providerProjection-isnot[Collections.IDictionary]-or
    -not$providerProjection.Contains('required_source_y_offset_from_accelerator_axis_mm')){
    throw 'Accelerator provider receipt must publish required_source_y_offset_from_accelerator_axis_mm.'
  }
  $sourceYOffsetMm=[double]$providerProjection.required_source_y_offset_from_accelerator_axis_mm
  if(-not[double]::IsFinite($sourceYOffsetMm)){
    throw 'Accelerator provider source y offset must be finite.'
  }
  # The source definition is a reusable shape/dispersion template.  Its
  # condition centre is owned by the current OA receipt, then by the qualified
  # N=1 release state below; a stale template offset must not require manual
  # recalibration or break the automatic chain.
  $sourceDefinitionData.source_y_offset_mm=$sourceYOffsetMm
  Write-RunJson -Path $sourceDefinition -Depth 30 -Value $sourceDefinitionData
  $config=Get-Content -LiteralPath $package.run_config -Raw|ConvertFrom-Json -AsHashtable
  $config.inputs=[ordered]@{bunch_source_definition=$sourceDefinition}
  $config.parameters=[ordered]@{
    accelerator_y_anchor_mm=$AcceleratorYAnchorMm;cohort_particle_count=100
    accelerator_source_y_offset_mm=$sourceYOffsetMm
    accelerator_source_y_offset_authority='provider_receipt.mrtof_projection.required_source_y_offset_from_accelerator_axis_mm'
    source_definition_condition_center='auto_matched_to_current_oa_then_qualified_n1'
    source_selection='controlled_n13_diagnostic_and_independent_pure_volume_n100'
    workflow='N1_P_then_S_iteration__common_source__baseline__TE1_probe__continuous_root__comparison'
    completed_te1_workpoint_reclosure_run_path=$CompletedTe1WorkpointReclosureRunPath
    reclosed_root_screening_run_path=$ReclosedRootScreeningRunPath
    final_screening_run_path=$FinalScreeningRunPath
  }
  Write-RunJson -Path $package.run_config -Depth 20 -Value $config

  $failureStage='n1_workpoint'
  if($QualifiedWorkpointRunPath){
    $workpointRun=(Resolve-Path -LiteralPath $QualifiedWorkpointRunPath).Path
  }else{
    $workpointId=New-StageRunId -Activity sim -Scope simion -Subject 'mrtof-n1-workpoint'
    $arguments=@{
      ContinuationRunManifest=(Resolve-Path -LiteralPath $ContinuationRunManifest).Path
      NativeCorridorBankRunPath=$NativeCorridorBankRunPath;GeometryReviewRunPath=$GeometryReviewRunPath
      MirrorRunPath=$MirrorRunPath;StripeRunPath=$StripeRunPath
      AcceleratorProviderReceiptPath=$AcceleratorProviderReceiptPath
      NativeSystemRuntimeBundlePath=$NativeSystemRuntimeBundlePath
      AcceleratorYAnchorMm=$AcceleratorYAnchorMm;AcceleratorSourceYOffsetMm=$sourceYOffsetMm
      RetainBaselineGuiWorkbench=$true
      RunId=$workpointId;PythonExe=$python
    }
    if($ContractPath){$arguments.ContractPath=$ContractPath}
    if($NativeRuntimeCheckpoint){$arguments.NativeRuntimeCheckpoint=$NativeRuntimeCheckpoint}
    if($SimionExe){$arguments.SimionExe=$SimionExe}
    & $workpointRunner @arguments
    $workpointRun=Join-Path $artifactRoot "runs\$workpointId"
  }
  $workpointManifest=Assert-Manifest -RunPath $workpointRun -Status checkpoint -Mode downstream_fixed_grid_workpoint_iteration
  Assert-WorkpointPhysicalBinding -WorkpointRun $workpointRun `
    -ExpectedGeometryRun $GeometryReviewRunPath -ExpectedMirrorRun $MirrorRunPath `
    -ExpectedStripeRun $StripeRunPath -ExpectedProviderReceipt $providerReceipt `
    -ExpectedRuntimeBundle $NativeSystemRuntimeBundlePath -ExpectedContract $ContractPath
  # The qualified N=1 manifest is the runtime-family authority for every
  # downstream stage.  It may point at an earlier owner run after a resume;
  # consumers must follow that declared output instead of relying on the
  # optional top-level transport argument.
  $activeNativeRuntimeCheckpoint=Get-ManifestOutputPath -ManifestPath $workpointManifest `
    -FileName 'native_corridor_runtime_checkpoint.json'
  $handoffPath=Join-Path $workpointRun 'results\best_physical_workpoint_handoff.json'
  $handoff=Get-Content -LiteralPath $handoffPath -Raw|ConvertFrom-Json -AsHashtable
  if($handoff.status-ne'within_tolerance'){
    $handoffPath=Join-Path $package.result_dir 'qualified_workpoint_handoff.json'
    Invoke-ProjectPython -Arguments @(
      '-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.downstream_workpoint_iteration',
      '--select-best-physical-workpoint','--history',(Join-Path $workpointRun 'results\iteration_history.json'),
      '--output',$handoffPath
    )
    $handoff=Get-Content -LiteralPath $handoffPath -Raw|ConvertFrom-Json -AsHashtable
    $repairedHandoff=$handoffPath
  }
  if($handoff.status-ne'within_tolerance'-or$handoff.qualification-ne'candidate_bunch_screening_authorized'){
    throw 'N=1 workpoint does not satisfy every downstream tolerance.'
  }
  $qualifiedCenterSeedManifest=Get-QualifiedCenterSeedManifest -WorkpointRun $workpointRun -Handoff $handoff
  # The accepted centre child is the source-state authority.  A resumed parent
  # need not retain its original bootstrap file, and the bootstrap may predate
  # the final P/S correction that actually met every tolerance.
  $seedManifestPath=$qualifiedCenterSeedManifest
  $seedRun=Split-Path -Parent $seedManifestPath
  $null=Assert-Manifest -RunPath $seedRun -Status success -Mode finite_3d_two_prism_voltage_trial
  $seedManifest=Get-Content -LiteralPath $seedManifestPath -Raw|ConvertFrom-Json -AsHashtable
  $sourceObservations=@($seedManifest.outputs|Where-Object{[IO.Path]::GetFileName([string]$_.path)-eq'two_prism_trial_observation.json'})
  if($sourceObservations.Count-ne1){throw 'N=1 workpoint seed must bind one source-state observation.'}
  $sourceObservationPath=(Resolve-Path -LiteralPath ([string]$sourceObservations[0].path)).Path
  $n1Source=(Get-Content -LiteralPath $sourceObservationPath -Raw|ConvertFrom-Json -AsHashtable).source_release_state
  $sourceEnergyEv=[double]$n1Source.kinetic_energy_ev
  if(-not[double]::IsFinite($sourceEnergyEv)-or$sourceEnergyEv-le0){throw 'Qualified N=1 release energy is invalid.'}
  $sourceDefinitionData.kinetic_energy_center_ev=$sourceEnergyEv
  $sourceDefinitionData.nominal_direction_workbench=@($n1Source.direction_project|ForEach-Object{[double]$_})
  $sourceDefinitionData.mass_th=[double]$n1Source.particle_mass_th
  $sourceDefinitionData.charge_e=[int]$n1Source.charge_state
  $sourceDefinitionData.common_time_of_birth_us=[double]$n1Source.time_us
  $sourceDefinitionData.condition_center_authority=[ordered]@{
    method='inherit_complete_qualified_n1_release_state'
    source_y_offset='source_definition.source_y_offset_mm'
    n1_observation=$sourceObservationPath
  }
  Write-RunJson -Path $sourceDefinition -Depth 30 -Value $sourceDefinitionData

  $failureStage='common_sources'
  $diagnosticSourceDefinition=$sourceDefinition
  $formalSourceDefinition=Join-Path $package.input_dir 'formal_volume_source_definition.json'
  $formalSourceDefinitionData=Get-Content -LiteralPath $diagnosticSourceDefinition -Raw|ConvertFrom-Json -AsHashtable
  $formalSourceDefinitionData.cohort_role='formal_volume'
  $formalSourceDefinitionData.source_profile_id=([string]$formalSourceDefinitionData.source_profile_id)+'__formal_volume'
  foreach($name in @(
    'controlled_focus_half_span_mm','controlled_focus_half_span_fraction_of_radius',
    'controlled_envelope_half_span_fraction','controlled_slow_energy_half_span_ev_per_charge'
  )){$null=$formalSourceDefinitionData.Remove($name)}
  Write-RunJson -Path $formalSourceDefinition -Depth 30 -Value $formalSourceDefinitionData
  $config=Get-Content -LiteralPath $package.run_config -Raw|ConvertFrom-Json -AsHashtable
  $config.inputs.formal_volume_source_definition=$formalSourceDefinition
  Write-RunJson -Path $package.run_config -Depth 20 -Value $config

  if($PublishedSourceReceiptPath){
    $diagnosticSourceReceipt=(Resolve-Path -LiteralPath $PublishedSourceReceiptPath).Path
    $diagnosticSourceRun=Split-Path -Parent (Split-Path -Parent $diagnosticSourceReceipt)
    $null=Assert-Manifest -RunPath $diagnosticSourceRun -Status success -Mode deterministic_bunch_source_materialization
  }else{
    $diagnosticSourceId=New-StageRunId -Activity analysis -Scope python -Subject 'mrtof-source-diagnostic'
    & $sourceRunner -SourceDefinitionPath $diagnosticSourceDefinition `
      -GeometryContractPath (Join-Path $workpointRun 'inputs\contract.json') `
      -AcceleratorProviderReceiptPath $AcceleratorProviderReceiptPath -RunId $diagnosticSourceId -PythonExe $python
    $diagnosticSourceRun=Join-Path $artifactRoot "runs\$diagnosticSourceId"
    $null=Assert-Manifest -RunPath $diagnosticSourceRun -Status success -Mode deterministic_bunch_source_materialization
    $diagnosticSourceReceipt=Join-Path $diagnosticSourceRun 'results\bunch_source_receipt.json'
  }
  if($PublishedFormalSourceReceiptPath){
    $formalSourceReceipt=(Resolve-Path -LiteralPath $PublishedFormalSourceReceiptPath).Path
    $formalSourceRun=Split-Path -Parent (Split-Path -Parent $formalSourceReceipt)
    $null=Assert-Manifest -RunPath $formalSourceRun -Status success -Mode deterministic_bunch_source_materialization
  }else{
    $formalSourceId=New-StageRunId -Activity analysis -Scope python -Subject 'mrtof-source-formal-volume-n100'
    & $sourceRunner -SourceDefinitionPath $formalSourceDefinition `
      -GeometryContractPath (Join-Path $workpointRun 'inputs\contract.json') `
      -AcceleratorProviderReceiptPath $AcceleratorProviderReceiptPath -RunId $formalSourceId -PythonExe $python
    $formalSourceRun=Join-Path $artifactRoot "runs\$formalSourceId"
    $null=Assert-Manifest -RunPath $formalSourceRun -Status success -Mode deterministic_bunch_source_materialization
    $formalSourceReceipt=Join-Path $formalSourceRun 'results\bunch_source_receipt.json'
  }
  $diagnosticSource=Get-Content -LiteralPath $diagnosticSourceReceipt -Raw|ConvertFrom-Json -AsHashtable
  $formalSource=Get-Content -LiteralPath $formalSourceReceipt -Raw|ConvertFrom-Json -AsHashtable
  if([int]$diagnosticSource.particle_count-ne100-or[int]$diagnosticSource.mother_particle_count-ne1000-or
    [string]$diagnosticSource.cohort_role-ne'controlled_diagnostic'){
    throw 'Diagnostic source must publish the controlled N=13 head in the deterministic mother sequence.'
  }
  if([int]$formalSource.particle_count-ne100-or[int]$formalSource.mother_particle_count-ne1000-or
    [string]$formalSource.cohort_role-ne'formal_volume'){
    throw 'Formal source must publish an independent pure-volume N=100 prefix.'
  }
  $publishedDefinition=Get-Content -LiteralPath ([string]$diagnosticSource.definition.path) -Raw|ConvertFrom-Json -AsHashtable
  $publishedCenter=@($diagnosticSource.geometry_contract.derived_center_workbench_mm|ForEach-Object{[double]$_})
  $n1Center=@($n1Source.position_mm|ForEach-Object{[double]$_})
  $publishedCenterState=Import-Csv -LiteralPath ([string]$diagnosticSource.state_table.path)|Select-Object -First 1
  $publishedDirection=@('direction_x','direction_y','direction_z'|ForEach-Object{[double]$publishedCenterState.$_})
  $n1Direction=@($n1Source.direction_project|ForEach-Object{[double]$_})
  if([math]::Abs([double]$publishedDefinition.source_y_offset_mm-$sourceYOffsetMm)-gt1e-12-or
    [math]::Abs([double]$publishedDefinition.kinetic_energy_center_ev-$sourceEnergyEv)-gt1e-12-or
    $publishedCenter.Count-ne3-or@(0..2|Where-Object{[math]::Abs($publishedCenter[$_]-$n1Center[$_])-gt1e-12}).Count){
    throw 'Published diagnostic source does not share the current N=1 centre condition.'
  }
  if($null-eq$publishedCenterState-or[int]$publishedCenterState.particle_id-ne1-or
    @(0..2|Where-Object{[math]::Abs(@([double]$publishedCenterState.x_mm,[double]$publishedCenterState.y_mm,[double]$publishedCenterState.z_mm)[$_]-$n1Center[$_])-gt1e-12}).Count-or
    @(0..2|Where-Object{[math]::Abs($publishedDirection[$_]-$n1Direction[$_])-gt1e-12}).Count-or
    [math]::Abs([double]$publishedCenterState.kinetic_energy_ev-$sourceEnergyEv)-gt1e-12-or
    [math]::Abs([double]$publishedCenterState.mass_th-[double]$n1Source.particle_mass_th)-gt1e-12-or
    [int]$publishedCenterState.charge_e-ne[int]$n1Source.charge_state-or
    [math]::Abs([double]$publishedCenterState.tob_us-[double]$n1Source.time_us)-gt1e-12){
    throw 'Diagnostic source particle 1 does not inherit the complete qualified N=1 release state.'
  }
  $formalNominal=$formalSource.nominal_center_state
  if($formalSource.Contains('center_particle_state')-or
    @(0..2|Where-Object{[math]::Abs([double]$formalNominal.position_workbench_mm[$_]-$n1Center[$_])-gt1e-12}).Count-or
    @(0..2|Where-Object{[math]::Abs([double]$formalNominal.direction_workbench[$_]-$n1Direction[$_])-gt1e-12}).Count-or
    [math]::Abs([double]$formalNominal.kinetic_energy_ev-$sourceEnergyEv)-gt1e-12-or
    [math]::Abs([double]$formalNominal.mass_th-[double]$n1Source.particle_mass_th)-gt1e-12-or
    [int]$formalNominal.charge_e-ne[int]$n1Source.charge_state-or
    [math]::Abs([double]$formalNominal.tob_us-[double]$n1Source.time_us)-gt1e-12){
    throw 'Formal volume source does not inherit the qualified N=1 nominal state.'
  }
  $source=$diagnosticSource
  $sourceReceipt=$diagnosticSourceReceipt
  $sourceDefinitionData=Get-Content -LiteralPath $diagnosticSourceDefinition -Raw|ConvertFrom-Json -AsHashtable
  $sourceZSpanMm=2.0*[double]$sourceDefinitionData.position_radius_mm
  $focusContractPath=Join-Path $workpointRun 'inputs\contract.json'
  $focusContract=Get-Content -LiteralPath $focusContractPath -Raw|ConvertFrom-Json -AsHashtable
  $workpointProfile=$focusContract.downstream_fixed_grid_workpoint_profile
  if(-not($workpointProfile-is[Collections.IDictionary])-or
     -not$workpointProfile.ContainsKey('jacobian_relative_step_tiers')){
    $currentContractPath=Join-Path $PSScriptRoot '..\config\simion_candidate_two_zone.json'
    $currentContract=Get-Content -LiteralPath $currentContractPath -Raw|ConvertFrom-Json -AsHashtable
    $currentTiers=$currentContract.downstream_fixed_grid_workpoint_profile.jacobian_relative_step_tiers
    if(-not($workpointProfile-is[Collections.IDictionary])-or-not($currentTiers-is[Collections.IDictionary])){
      throw 'Current numerical profile cannot upgrade the frozen workpoint contract.'
    }
    $workpointProfile.jacobian_relative_step_tiers=$currentTiers
    $focusContractPath=Join-Path $package.input_dir 'focus_contract.json'
    Write-RunJson -Path $focusContractPath -Depth 100 -Value $focusContract
  }
  $minimumMassResolution=[double]$focusContract.mirror.theory_requirements.l0_acceptance_budget.minimum_mass_resolution
  if(-not[double]::IsFinite($sourceZSpanMm)-or$sourceZSpanMm-le0-or
    -not[double]::IsFinite($minimumMassResolution)-or$minimumMassResolution-le0){
    throw 'Detector focus tolerance inputs are invalid.'
  }
  $mirrorAuthorityRun=(Resolve-Path -LiteralPath $MirrorRunPath).Path
  $mirrorPeriod=Join-Path $mirrorAuthorityRun 'results\mirror_real_field_period_comparison.json'
  $mirrorConfig=Get-Content -LiteralPath (Join-Path $mirrorAuthorityRun 'run_config.json') -Raw|ConvertFrom-Json -AsHashtable
  $mirrorCorrectionManifest=[string]$mirrorConfig.inputs.fixed_grid_voltage_correction_manifest
  if(-not(Test-Path -LiteralPath $mirrorPeriod -PathType Leaf)-or
    -not(Test-Path -LiteralPath $mirrorCorrectionManifest -PathType Leaf)){
    throw 'Mirror authority does not expose its period result and fixed-grid correction lineage.'
  }
  $mirrorCorrection=Join-Path (Split-Path -Parent $mirrorCorrectionManifest) 'results\fixed_grid_multifidelity_voltage_correction.json'
  if(-not(Test-Path -LiteralPath $mirrorCorrection -PathType Leaf)){
    throw 'Mirror fixed-grid correction result is missing.'
  }
  $mirrorPoint=Join-Path $mirrorAuthorityRun 'results\fixed_grid_voltage_point.json'
  $te1Reference=Join-Path $package.input_dir 'te1_reference.json'
  Invoke-ProjectPython -Arguments @(
    '-m',$analysisModule,'--build-te1-reference','--mirror-point',$mirrorPoint,
    '--mirror-correction',$mirrorCorrection,'--contract',$focusContractPath,
    '--output',$te1Reference
  )
  $config=Get-Content -LiteralPath $package.run_config -Raw|ConvertFrom-Json -AsHashtable
  $config.inputs.focus_contract=$focusContractPath;$config.inputs.te1_reference=$te1Reference
  Write-RunJson -Path $package.run_config -Depth 20 -Value $config

  $failureStage='baseline_n13_diagnostic'
  if($BaselineEnvelopeScreeningRunPath){
    $baselineEnvelope=Read-ScreeningEvidence -RunPath $BaselineEnvelopeScreeningRunPath -Scope envelope `
      -ExpectedWorkpointRun $workpointRun -ExpectedSourceReceipt $diagnosticSourceReceipt `
      -ExpectedNativeBankRun $NativeCorridorBankRunPath `
      -ExpectedSourceStatesSha256 ([string]$diagnosticSource.particle_states_sha256)
  }else{
    $baselineEnvelope=Invoke-Screening -Stage 'baseline-envelope' -WorkpointRun $workpointRun `
      -SourceReceipt $diagnosticSourceReceipt -ParticleCount 13 -DiagnosticPurpose controlled_aberration
  }
  $baselineCoordinate=[double]$baselineEnvelope.te1_coordinate
  $baselineDiagnostic=Invoke-Diagnostic -Stage 'baseline-envelope' `
    -FlightManifest ([string]$baselineEnvelope.result.cohort_run_manifest)
  $baselineCenterGate=Read-CenterWorkpointGate -ScreeningResult $baselineEnvelope.result -ContractDocument $focusContract
  $baselineFormalFocusSample=Read-DetectorFocusSample -Path $baselineDiagnostic
  $baselineFocusResult=Resolve-DetectorFocusSample -Stage 'baseline' `
    -FormalSample $baselineFormalFocusSample -FormalDiagnostic $baselineDiagnostic `
    -WorkpointRun $workpointRun -BaseDefinition $diagnosticSourceDefinition -GeometryContract $focusContractPath
  $baselineFocusSample=$baselineFocusResult.sample
  $baselineFocusDiagnostic=[string]$baselineFocusResult.diagnostic
  $baselineFocusTolerance=$baselineFocusSample.median_tof_us/(2.0*$minimumMassResolution*$sourceZSpanMm)
  $baselineZ0Classification=Read-Z0FocusClassification -Path $baselineDiagnostic `
    -SlopeToleranceUsPerMm $baselineFocusTolerance -MinimumMassResolution $minimumMassResolution

  $failureStage='baseline_n100_formal_volume'
  if($BaselineScreeningRunPath){
    $baseline=Read-ScreeningEvidence -RunPath $BaselineScreeningRunPath -Scope formal `
      -ExpectedWorkpointRun $workpointRun -ExpectedSourceReceipt $formalSourceReceipt `
      -ExpectedNativeBankRun $NativeCorridorBankRunPath `
      -ExpectedSourceStatesSha256 ([string]$formalSource.particle_states_sha256)
  }else{
    $baseline=Invoke-Screening -Stage 'baseline' -WorkpointRun $workpointRun -SourceReceipt $formalSourceReceipt `
      -ExistingCohortRun $BaselineCohortRunPath
  }
  if([math]::Abs([double]$baseline.te1_coordinate-$baselineCoordinate)-gt1e-12){
    throw 'Baseline diagnostic and formal-volume screening use different TE1 coordinates.'
  }
  $baselineFlight=[string]$baseline.result.cohort_run_manifest
  $baselineCollectionGate=Read-CollectionGate -ScreeningResult $baseline.result
  $baselineVolumeDiagnostic=Invoke-Diagnostic -Stage 'baseline' -FlightManifest $baselineFlight
  if([bool]$baselineCollectionGate.hard_stop-or-not[bool]$baselineCollectionGate.continue_downstream){
    Complete-BaselineCollectionHardStop -Baseline $baseline
    return
  }
  if(-not$baselineFocusSample.available){
    Complete-FocusResponseUnavailable -Stage baseline -Sample $baselineFocusSample -Baseline $baseline -Root $baselineEnvelope
    return
  }
  $failureStage='te1_probe'
  $reference=Get-Content -LiteralPath $te1Reference -Raw|ConvertFrom-Json -AsHashtable
  $referenceCoordinate=[double]$reference.coordinate
  $referenceBase=@($reference.base_mirror_voltages_v)
  $referenceDelta=@($reference.voltage_delta_v)
  $relativePerCoordinate=@(for($index=0;$index-lt4;$index++){
    [math]::Abs(([double]$referenceDelta[$index]/$referenceCoordinate)/[double]$referenceBase[$index+1])
  })
  $fineRelativeStep=[double]$focusContract.downstream_fixed_grid_workpoint_profile.jacobian_relative_step_tiers.fine
  $probeCoordinate=-1.0*$fineRelativeStep/($relativePerCoordinate|Measure-Object -Maximum).Maximum
  if(-not[double]::IsFinite($probeCoordinate)-or$probeCoordinate-eq0.0){throw 'TE1 reference coordinate is invalid.'}
  $probeVariation=Join-Path $package.result_dir 'te1_probe_variation.json'
  Invoke-ProjectPython -Arguments @(
    '-m',$analysisModule,'--te1-reference',$te1Reference,'--te1-coordinate',[string]$probeCoordinate,
    '--mirror-period',$mirrorPeriod,'--mirror-correction',$mirrorCorrection,
    '--contract',$focusContractPath,
    '--output',$probeVariation
  )
  $probeVariationData=Get-Content -LiteralPath $probeVariation -Raw|ConvertFrom-Json -AsHashtable
  if($probeVariationData.status-ne'screening_candidate_materialized'){
    throw 'Fine TE1 probe variation is invalid.'
  }
  if($ProbeScreeningRunPath){
    $probe=Read-ScreeningEvidence -RunPath $ProbeScreeningRunPath -Scope focus `
      -ExpectedWorkpointRun $workpointRun -ExpectedSourceReceipt $sourceReceipt `
      -ExpectedNativeBankRun $NativeCorridorBankRunPath -ExpectedVariation $probeVariation `
      -ExpectedSourceStatesSha256 ([string]$source.particle_states_sha256)
    $probeCoordinate=[double]$probe.te1_coordinate
    $probeVariation=[string]$probe.variation_path
    if(-not$probeVariation){throw 'Resumed TE1 probe lacks its voltage variation.'}
  }else{
    $probe=Invoke-Screening -Stage 'te1-probe' -WorkpointRun $workpointRun -SourceReceipt $sourceReceipt `
      -Variation $probeVariation -ParticleCount 3 -FocusDiagnosticOnly
  }
  $probeStepCoordinate=$probeCoordinate-$baselineCoordinate
  if(-not[double]::IsFinite($probeStepCoordinate)-or$probeStepCoordinate-eq0.0){
    throw 'Baseline and probe TE1 coordinates must be distinct.'
  }
  $probeDiagnostic=Invoke-Diagnostic -Stage 'te1-probe' -FlightManifest ([string]$probe.result.cohort_run_manifest)
  $probeFormalFocusSample=Read-DetectorFocusSample -Path $probeDiagnostic
  $probeFocusResult=Resolve-DetectorFocusSample -Stage 'te1-probe' `
    -FormalSample $probeFormalFocusSample -FormalDiagnostic $probeDiagnostic `
    -WorkpointRun $workpointRun -BaseDefinition $sourceDefinition -GeometryContract $focusContractPath `
    -Variation $probeVariation
  $probeFocusSample=$probeFocusResult.sample
  $probeFocusDiagnostic=[string]$probeFocusResult.diagnostic
  if(-not$probeFocusSample.available){
    Complete-FocusResponseUnavailable -Stage probe -Sample $probeFocusSample -Baseline $baseline -Probe $probe
    return
  }

  $failureStage='te1_continuous_root'
  $focusCoordinates=[Collections.Generic.List[double]]::new();$focusCoordinates.Add($baselineCoordinate);$focusCoordinates.Add($probeCoordinate)
  $focusDiagnostics=[Collections.Generic.List[string]]::new();$focusDiagnostics.Add($baselineFocusDiagnostic);$focusDiagnostics.Add($probeFocusDiagnostic)
  $rootVariations=@();$focusIterations=@();$focusConverged=$false;$focused=$null;$rootDiagnostic='';$rootCoordinate=0.0
  $workpointReclosures=@();$reclosureCount=0;$reclosureExhausted=$false
  $bestFocused=$null;$bestRootDiagnostic='';$bestRootFocusDiagnostic='';$bestRootCoordinate=0.0
  $bestRootVariation=''
  $bestWorkpointRun='';$bestWorkpointManifest='';$bestHandoff=$null
  $bestNativeRuntimeCheckpoint='';$bestFocusContractPath='';$bestFocusContract=$null
  $bestQualifiedCenterSeedManifest=''
  $bestFocusMetric=[double]::PositiveInfinity
  for($rootAttempt=1;$rootAttempt-le$MaximumTe1RootFlights;$rootAttempt++){
    $suffix=if($rootAttempt-eq1){''}else{'_'+('{0:D2}'-f$rootAttempt)}
    $rootVariation=Join-Path $package.result_dir "te1_detector_plane_root_variation$suffix.json"
    $last=$focusCoordinates.Count-1;$previous=$last-1
    Invoke-ProjectPython -Arguments @(
      '-m',$analysisModule,'--te1-reference',$te1Reference,
      '--first-diagnostic',$focusDiagnostics[$previous],'--first-coordinate',[string]$focusCoordinates[$previous],
      '--second-diagnostic',$focusDiagnostics[$last],'--second-coordinate',[string]$focusCoordinates[$last],
      '--mirror-period',$mirrorPeriod,'--mirror-correction',$mirrorCorrection,
      '--contract',$focusContractPath,
      '--output',$rootVariation
    )
    $rootVariations+=,$rootVariation
    $rootVariationData=Get-Content -LiteralPath $rootVariation -Raw|ConvertFrom-Json -AsHashtable
    $rootCoordinate=[double]$rootVariationData.coordinate
    if($rootVariationData.status-ne'screening_candidate_materialized'){
      throw 'TE1 detector-plane root variation is invalid.'
    }
    if($rootAttempt-le$completedRootScreeningRuns.Count){
      $focused=Read-ScreeningEvidence -RunPath $completedRootScreeningRuns[$rootAttempt-1] -Scope envelope `
        -ExpectedWorkpointRun $workpointRun -ExpectedSourceReceipt $sourceReceipt `
        -ExpectedNativeBankRun $NativeCorridorBankRunPath -ExpectedVariation $rootVariation `
        -ExpectedSourceStatesSha256 ([string]$source.particle_states_sha256)
    }elseif($rootAttempt-eq1){
      $focused=Invoke-Screening -Stage 'te1-root' -WorkpointRun $workpointRun -SourceReceipt $sourceReceipt `
        -Variation $rootVariation -ParticleCount 13 -DiagnosticPurpose controlled_aberration
    }else{
      $focused=Invoke-Screening -Stage ('te1-root-{0:D2}'-f$rootAttempt) -WorkpointRun $workpointRun -SourceReceipt $sourceReceipt `
        -Variation $rootVariation -ParticleCount 13 -DiagnosticPurpose controlled_aberration
    }
    $diagnosticStage=if($rootAttempt-eq1){'te1-root'}else{('te1-root-{0:D2}'-f$rootAttempt)}
    if([math]::Abs([double]$focused.te1_coordinate-$rootCoordinate)-gt1e-12){
      throw 'Root screening evidence belongs to a different TE1 coordinate.'
    }
    $rootDiagnostic=Invoke-Diagnostic -Stage $diagnosticStage -FlightManifest ([string]$focused.result.cohort_run_manifest)
    $rootFormalFocusSample=Read-DetectorFocusSample -Path $rootDiagnostic
    $rootFocusResult=Resolve-DetectorFocusSample -Stage $diagnosticStage `
      -FormalSample $rootFormalFocusSample -FormalDiagnostic $rootDiagnostic `
      -WorkpointRun $workpointRun -BaseDefinition $sourceDefinition -GeometryContract $focusContractPath `
      -Variation $rootVariation
    $sample=$rootFocusResult.sample
    $rootFocusDiagnostic=[string]$rootFocusResult.diagnostic
    if(-not$sample.available){
      Complete-FocusResponseUnavailable -Stage root -Sample $sample -Baseline $baseline -Probe $probe -Root $focused
      return
    }
    $focusTolerance=$sample.median_tof_us/(2.0*$minimumMassResolution*$sourceZSpanMm)
    $responseConverged=[math]::Abs($sample.slope_us_per_mm)-le$focusTolerance
    $candidateCenterGate=Read-CenterWorkpointGate -ScreeningResult $focused.result -ContractDocument $focusContract
    $candidateEnvelopeAvailable=[bool]$focused.envelope_available
    $focusConverged=$responseConverged-and[bool]$candidateCenterGate.passed-and$candidateEnvelopeAvailable
    $focusIterations+=,[ordered]@{
        attempt=$rootAttempt;te1_coordinate=$rootCoordinate;diagnostic=$rootFocusDiagnostic
        formal_diagnostic=$rootDiagnostic;focus_half_span_percent=$rootFocusResult.half_span_percent
      detector_hits=$sample.detector_hits;detector_dt_d_initial_z_us_per_mm=$sample.slope_us_per_mm
      tolerance_us_per_mm=$focusTolerance;response_converged=$responseConverged;converged=$focusConverged
      center_workpoint_satisfied=[bool]$candidateCenterGate.passed
      screening_particle_count=[int]$focused.particle_count;evidence_scope=[string]$focused.evidence_scope
      envelope_available=$candidateEnvelopeAvailable
    }
    if($candidateCenterGate.passed-and$candidateEnvelopeAvailable-and
      [math]::Abs($sample.slope_us_per_mm)-lt$bestFocusMetric){
      $bestFocusMetric=[math]::Abs($sample.slope_us_per_mm);$bestFocused=$focused
      $bestRootDiagnostic=$rootDiagnostic;$bestRootFocusDiagnostic=$rootFocusDiagnostic;$bestRootCoordinate=$rootCoordinate
      $bestRootVariation=$rootVariation
      $bestWorkpointRun=$workpointRun;$bestWorkpointManifest=$workpointManifest;$bestHandoff=$handoff
      $bestNativeRuntimeCheckpoint=$activeNativeRuntimeCheckpoint;$bestFocusContractPath=$focusContractPath
      $bestFocusContract=$focusContract;$bestQualifiedCenterSeedManifest=$qualifiedCenterSeedManifest
    }
    if(-not$candidateCenterGate.passed){
      if($reclosureCount-ge$MaximumTe1WorkpointReclosures){
        $reclosureExhausted=$true;$focusConverged=$false;break
      }
      $reclosureCount++
      $reclosed=if($reclosureCount-eq1-and$CompletedTe1WorkpointReclosureRunPath){
        Read-CompletedTe1WorkpointReclosure -RunPath $CompletedTe1WorkpointReclosureRunPath `
          -Variation $rootVariation
      }else{
        Invoke-Te1WorkpointReclosure -Attempt $reclosureCount `
          -SeedManifest $qualifiedCenterSeedManifest -Variation $rootVariation `
          -CurrentContractPath $focusContractPath -RuntimeCheckpoint $activeNativeRuntimeCheckpoint
      }
      $workpointRun=$reclosed.run;$workpointManifest=$reclosed.manifest;$handoff=$reclosed.handoff
      $activeNativeRuntimeCheckpoint=Get-ManifestOutputPath -ManifestPath $workpointManifest `
        -FileName 'native_corridor_runtime_checkpoint.json'
      $focusContractPath=Join-Path $workpointRun 'inputs\contract.json'
      $focusContract=Get-Content -LiteralPath $focusContractPath -Raw|ConvertFrom-Json -AsHashtable
      $qualifiedCenterSeedManifest=Get-QualifiedCenterSeedManifest -WorkpointRun $workpointRun -Handoff $handoff
      # A TE1 candidate and its reclosed P/S workpoint are one inseparable state.
      # Do not compare or restore a candidate measured against the previous workpoint.
      $bestFocused=$null;$bestRootDiagnostic='';$bestRootFocusDiagnostic='';$bestRootCoordinate=0.0
      $bestRootVariation='';$bestFocusMetric=[double]::PositiveInfinity
      $bestWorkpointRun='';$bestWorkpointManifest='';$bestHandoff=$null
      $bestNativeRuntimeCheckpoint='';$bestFocusContractPath='';$bestFocusContract=$null
      $bestQualifiedCenterSeedManifest=''
      $workpointReclosures+=,[ordered]@{
        attempt=$reclosureCount;trigger_root_attempt=$rootAttempt;te1_coordinate=$rootCoordinate
        variation=$rootVariation;workpoint_run_manifest=$workpointManifest
      }
      $focused=if($reclosureCount-eq1-and$ReclosedRootScreeningRunPath){
        Read-ScreeningEvidence -RunPath $ReclosedRootScreeningRunPath -Scope envelope `
          -ExpectedWorkpointRun $workpointRun -ExpectedSourceReceipt $sourceReceipt `
          -ExpectedNativeBankRun $NativeCorridorBankRunPath -ExpectedVariation $rootVariation `
          -ExpectedSourceStatesSha256 ([string]$source.particle_states_sha256)
      }else{
        Invoke-Screening -Stage ('te1-reclosed-root-{0:D2}'-f$reclosureCount) `
          -WorkpointRun $workpointRun -SourceReceipt $sourceReceipt -Variation $rootVariation `
          -ParticleCount 13 -DiagnosticPurpose controlled_aberration
      }
      if([math]::Abs([double]$focused.te1_coordinate-$rootCoordinate)-gt1e-12){
        throw 'Reclosed root screening evidence belongs to a different TE1 coordinate.'
      }
      $rootDiagnostic=Invoke-Diagnostic -Stage ('te1-reclosed-root-{0:D2}'-f$reclosureCount) `
        -FlightManifest ([string]$focused.result.cohort_run_manifest)
      $rootFormalFocusSample=Read-DetectorFocusSample -Path $rootDiagnostic
      $rootFocusResult=Resolve-DetectorFocusSample -Stage ('te1-reclosed-root-{0:D2}'-f$reclosureCount) `
        -FormalSample $rootFormalFocusSample -FormalDiagnostic $rootDiagnostic `
        -WorkpointRun $workpointRun -BaseDefinition $sourceDefinition -GeometryContract $focusContractPath `
        -Variation $rootVariation
      $sample=$rootFocusResult.sample
      $rootFocusDiagnostic=[string]$rootFocusResult.diagnostic
      if(-not$sample.available){
        Complete-FocusResponseUnavailable -Stage reclosed_root -Sample $sample -Baseline $baseline -Probe $probe -Root $focused
        return
      }
      $focusTolerance=$sample.median_tof_us/(2.0*$minimumMassResolution*$sourceZSpanMm)
      $responseConverged=[math]::Abs($sample.slope_us_per_mm)-le$focusTolerance
      $candidateCenterGate=Read-CenterWorkpointGate -ScreeningResult $focused.result -ContractDocument $focusContract
      $candidateEnvelopeAvailable=[bool]$focused.envelope_available
      $focusConverged=$responseConverged-and[bool]$candidateCenterGate.passed-and$candidateEnvelopeAvailable
      $focusIterations+=,[ordered]@{
        attempt=$rootAttempt;reclosure=$reclosureCount;te1_coordinate=$rootCoordinate;diagnostic=$rootFocusDiagnostic
        formal_diagnostic=$rootDiagnostic;focus_half_span_percent=$rootFocusResult.half_span_percent
        detector_hits=$sample.detector_hits;detector_dt_d_initial_z_us_per_mm=$sample.slope_us_per_mm
        tolerance_us_per_mm=$focusTolerance;response_converged=$responseConverged;converged=$focusConverged
        center_workpoint_satisfied=[bool]$candidateCenterGate.passed
        screening_particle_count=[int]$focused.particle_count;evidence_scope=[string]$focused.evidence_scope
        envelope_available=$candidateEnvelopeAvailable
      }
      if(-not$candidateCenterGate.passed){throw 'Reclosed TE1 centre failed its screening centre-particle verification.'}
      if($candidateEnvelopeAvailable-and[math]::Abs($sample.slope_us_per_mm)-lt$bestFocusMetric){
        $bestFocusMetric=[math]::Abs($sample.slope_us_per_mm);$bestFocused=$focused
        $bestRootDiagnostic=$rootDiagnostic;$bestRootFocusDiagnostic=$rootFocusDiagnostic;$bestRootCoordinate=$rootCoordinate
        $bestRootVariation=$rootVariation
        $bestWorkpointRun=$workpointRun;$bestWorkpointManifest=$workpointManifest;$bestHandoff=$handoff
        $bestNativeRuntimeCheckpoint=$activeNativeRuntimeCheckpoint;$bestFocusContractPath=$focusContractPath
        $bestFocusContract=$focusContract;$bestQualifiedCenterSeedManifest=$qualifiedCenterSeedManifest
      }
      if($focusConverged){break}
      $remeasureCoordinate=$rootCoordinate+$probeStepCoordinate
      $remeasureVariation=Join-Path $package.result_dir ('te1_reclosed_response_variation_{0:D2}.json'-f$reclosureCount)
      Invoke-ProjectPython -Arguments @(
        '-m',$analysisModule,'--te1-reference',$te1Reference,'--te1-coordinate',[string]$remeasureCoordinate,
        '--mirror-period',$mirrorPeriod,'--mirror-correction',$mirrorCorrection,
        '--contract',$focusContractPath,'--output',$remeasureVariation
      )
      $remeasureVariationData=Get-Content -LiteralPath $remeasureVariation -Raw|ConvertFrom-Json -AsHashtable
      if($remeasureVariationData.status-ne'screening_candidate_materialized'){
        throw 'Reclosed TE1 response variation is invalid.'
      }
      $rootVariations+=,$remeasureVariation
      $remeasured=Invoke-Screening -Stage ('te1-reclosed-response-{0:D2}'-f$reclosureCount) `
        -WorkpointRun $workpointRun -SourceReceipt $sourceReceipt -Variation $remeasureVariation `
        -ParticleCount 3 -FocusDiagnosticOnly
      $remeasureDiagnostic=Invoke-Diagnostic -Stage ('te1-reclosed-response-{0:D2}'-f$reclosureCount) `
        -FlightManifest ([string]$remeasured.result.cohort_run_manifest)
      $remeasureCenterGate=Read-CenterWorkpointGate -ScreeningResult $remeasured.result -ContractDocument $focusContract
      if(-not$remeasureCenterGate.passed){
        # The TE1 coordinate and its P/S-closed centre state are inseparable. Measure
        # the response on that constrained workpoint, not at the previous point's P/S.
        if($reclosureCount-ge$MaximumTe1WorkpointReclosures){
          $reclosureExhausted=$true;$focusConverged=$false;break
        }
        $reclosureCount++
        $responseReclosed=Invoke-Te1WorkpointReclosure -Attempt $reclosureCount `
          -SeedManifest $qualifiedCenterSeedManifest -Variation $remeasureVariation `
          -CurrentContractPath $focusContractPath -RuntimeCheckpoint $activeNativeRuntimeCheckpoint
        $workpointRun=$responseReclosed.run;$workpointManifest=$responseReclosed.manifest;$handoff=$responseReclosed.handoff
        $activeNativeRuntimeCheckpoint=Get-ManifestOutputPath -ManifestPath $workpointManifest `
          -FileName 'native_corridor_runtime_checkpoint.json'
        $focusContractPath=Join-Path $workpointRun 'inputs\contract.json'
        $focusContract=Get-Content -LiteralPath $focusContractPath -Raw|ConvertFrom-Json -AsHashtable
        $qualifiedCenterSeedManifest=Get-QualifiedCenterSeedManifest -WorkpointRun $workpointRun -Handoff $handoff
        $workpointReclosures+=,[ordered]@{
          attempt=$reclosureCount;trigger_root_attempt=$rootAttempt;te1_coordinate=$remeasureCoordinate
          variation=$remeasureVariation;workpoint_run_manifest=$workpointManifest;response_point=$true
        }
        $remeasured=Invoke-Screening -Stage ('te1-reclosed-response-reclosed-{0:D2}'-f$reclosureCount) `
          -WorkpointRun $workpointRun -SourceReceipt $sourceReceipt -Variation $remeasureVariation `
          -ParticleCount 3 -FocusDiagnosticOnly
        $remeasureDiagnostic=Invoke-Diagnostic -Stage ('te1-reclosed-response-reclosed-{0:D2}'-f$reclosureCount) `
          -FlightManifest ([string]$remeasured.result.cohort_run_manifest)
        $remeasureCenterGate=Read-CenterWorkpointGate -ScreeningResult $remeasured.result -ContractDocument $focusContract
        if(-not$remeasureCenterGate.passed){
          throw 'Reclosed controlled TE1 response point failed its centre verification.'
        }
      }
      $remeasureFormalFocusSample=Read-DetectorFocusSample -Path $remeasureDiagnostic
      $remeasureFocusResult=Resolve-DetectorFocusSample -Stage ('te1-reclosed-response-{0:D2}'-f$reclosureCount) `
        -FormalSample $remeasureFormalFocusSample -FormalDiagnostic $remeasureDiagnostic `
        -WorkpointRun $workpointRun -BaseDefinition $sourceDefinition -GeometryContract $focusContractPath `
        -Variation $remeasureVariation
      $remeasureSample=$remeasureFocusResult.sample
      $remeasureFocusDiagnostic=[string]$remeasureFocusResult.diagnostic
      if(-not$remeasureSample.available){
        Complete-FocusResponseUnavailable -Stage reclosed_response -Sample $remeasureSample `
          -Baseline $baseline -Probe $probe -Root $remeasured
        return
      }
      $remeasureTolerance=$remeasureSample.median_tof_us/(2.0*$minimumMassResolution*$sourceZSpanMm)
      $remeasureResponseConverged=[math]::Abs($remeasureSample.slope_us_per_mm)-le$remeasureTolerance
      $focusCoordinates.Clear();$focusDiagnostics.Clear()
      $focusCoordinates.Add($rootCoordinate);$focusDiagnostics.Add($rootFocusDiagnostic)
      $focusCoordinates.Add($remeasureCoordinate);$focusDiagnostics.Add($remeasureFocusDiagnostic)
      $focusIterations+=,[ordered]@{
        attempt=$rootAttempt;reclosure=$reclosureCount;response_remeasurement=$true
        te1_coordinate=$remeasureCoordinate;diagnostic=$remeasureFocusDiagnostic
        formal_diagnostic=$remeasureDiagnostic;focus_half_span_percent=$remeasureFocusResult.half_span_percent
        detector_hits=$remeasureSample.detector_hits
        detector_dt_d_initial_z_us_per_mm=$remeasureSample.slope_us_per_mm
        tolerance_us_per_mm=$remeasureTolerance;response_converged=$remeasureResponseConverged
        converged=$false;focus_probe_only=$true;envelope_available=$candidateEnvelopeAvailable
        center_workpoint_satisfied=$true
      }
      continue
    }
    if($focusConverged){break}
    $focusCoordinates.Add($rootCoordinate);$focusDiagnostics.Add($rootFocusDiagnostic)
  }

  if(-not$focusConverged-and$null-ne$bestFocused){
    $focused=$bestFocused;$rootDiagnostic=$bestRootDiagnostic;$rootFocusDiagnostic=$bestRootFocusDiagnostic;$rootCoordinate=$bestRootCoordinate
    $rootVariation=$bestRootVariation
    $workpointRun=$bestWorkpointRun;$workpointManifest=$bestWorkpointManifest;$handoff=$bestHandoff
    $activeNativeRuntimeCheckpoint=$bestNativeRuntimeCheckpoint;$focusContractPath=$bestFocusContractPath
    $focusContract=$bestFocusContract;$qualifiedCenterSeedManifest=$bestQualifiedCenterSeedManifest
  }

  if($null-eq$focused-or-not[bool]$focused.envelope_available){
    throw 'No TE1 root candidate has controlled envelope evidence.'
  }
  $selectedEnvelope=$focused
  $selectedEnvelopeDiagnostic=$rootDiagnostic
  $selectedEnvelopeFocusDiagnostic=$rootFocusDiagnostic

  $failureStage='te1_final_n100'
  $focused=if($FinalScreeningRunPath){
    Read-ScreeningEvidence -RunPath $FinalScreeningRunPath -Scope formal `
      -ExpectedWorkpointRun $workpointRun -ExpectedSourceReceipt $formalSourceReceipt `
      -ExpectedNativeBankRun $NativeCorridorBankRunPath -ExpectedVariation $rootVariation `
      -ExpectedSourceStatesSha256 ([string]$formalSource.particle_states_sha256)
  }else{
    Invoke-Screening -Stage 'te1-final' -WorkpointRun $workpointRun -SourceReceipt $formalSourceReceipt `
      -Variation $rootVariation
  }
  if([math]::Abs([double]$focused.te1_coordinate-$rootCoordinate)-gt1e-12){
    throw 'Final screening evidence belongs to a different TE1 coordinate.'
  }
  $rootVolumeDiagnostic=Invoke-Diagnostic -Stage 'te1-final' `
    -FlightManifest ([string]$focused.result.cohort_run_manifest)
  $rootDiagnostic=$selectedEnvelopeDiagnostic
  $rootFocusDiagnostic=$selectedEnvelopeFocusDiagnostic
  $sample=Read-DetectorFocusSample -Path $rootFocusDiagnostic
  if(-not$sample.available){
    Complete-FocusResponseUnavailable -Stage final_n100 -Sample $sample -Baseline $baseline -Probe $probe -Root $selectedEnvelope
    return
  }
  $focusTolerance=$sample.median_tof_us/(2.0*$minimumMassResolution*$sourceZSpanMm)
  $responseConverged=[math]::Abs($sample.slope_us_per_mm)-le$focusTolerance
  $candidateCenterGate=Read-CenterWorkpointGate -ScreeningResult $selectedEnvelope.result -ContractDocument $focusContract
  $focusConverged=$responseConverged-and[bool]$candidateCenterGate.passed

  $failureStage='compare'
  $comparison=$null;$comparisonData=$null;$measuredResolution=$null;$rootCollectionGate=$null;$rootCenterGate=$null
  $comparison=Join-Path $package.result_dir 'te1_detector_plane_comparison.json'
  # Probe is focus-only; formal collection/FWHM comparison uses baseline and root N=100.
  Invoke-ProjectPython -Arguments @(
    '-m',$analysisModule,'--compare-baseline',$baselineVolumeDiagnostic,'--compare-probe',$probeDiagnostic,
    '--compare-root',$rootVolumeDiagnostic,'--baseline-coordinate',[string]$baselineCoordinate,
    '--probe-coordinate',[string]$probeCoordinate,
    '--root-coordinate',[string]$rootCoordinate,
    '--baseline-focus-diagnostic',$baselineFocusDiagnostic,
    '--probe-focus-diagnostic',$probeFocusDiagnostic,
    '--root-focus-diagnostic',$rootFocusDiagnostic,'--output',$comparison
  )
  $comparisonData=Get-Content -LiteralPath $comparison -Raw|ConvertFrom-Json -AsHashtable
  $rootComparison=@($comparisonData.samples|Where-Object{$_.label-eq'root'})[-1]
  if($rootComparison.peak_method_id-ne'common_gaussian_kde_time_v1'){
    throw 'Candidate resolution requires current frozen common KDE metrics.'
  }
  $measuredResolution=if($null-ne$rootComparison.mass_resolution_t_over_2fwhm){
    [double]$rootComparison.mass_resolution_t_over_2fwhm
  }else{$null}
  $rootCollectionGate=Read-CollectionGate -ScreeningResult $focused.result
  $rootCenterGate=$candidateCenterGate
  $rootFocusSample=Read-DetectorFocusSample -Path $rootFocusDiagnostic
  $rootZ0Classification=Read-Z0FocusClassification -Path $rootDiagnostic `
    -SlopeToleranceUsPerMm ($rootFocusSample.median_tof_us/(2.0*$minimumMassResolution*$sourceZSpanMm)) `
    -MinimumMassResolution $minimumMassResolution
  $resolutionSatisfied=$null-ne$measuredResolution-and$measuredResolution-ge$minimumMassResolution
  $collectionSatisfied=$null-ne$rootCollectionGate-and(Test-CollectionAccepted -Gate $rootCollectionGate)
  $centerWorkpointSatisfied=$null-ne$rootCenterGate-and[bool]$rootCenterGate.passed
  $workflowOutcome=if($reclosureExhausted){'warning_center_workpoint_reclosure_exhausted__continue_parameter_scan'}
    elseif(-not$centerWorkpointSatisfied){'warning_center_workpoint_shifted__reclose_required'}
    elseif(-not$collectionSatisfied){'warning_collection_below_preferred__continue_parameter_scan'}
    elseif(-not$focusConverged){'warning_focus_not_converged__continue_parameter_scan'}
    elseif(-not$resolutionSatisfied){'warning_resolution_below_target__continue_parameter_scan'}
    else{'within_tolerance'}
  if($workflowOutcome-ne'within_tolerance'){Write-Warning $workflowOutcome}
  Write-RunJson -Path $package.summary -Depth 30 -Value ([ordered]@{
    schema_version=1;role='mrtof_native_candidate_end_to_end_chain_summary';status='success'
    workflow_outcome=$workflowOutcome
    qualification=$(if($workflowOutcome-eq'within_tolerance'){'paired_n100_candidate_within_tolerance'}else{'paired_n100_candidate_warning__continue_parameter_scan'})
    workpoint_run_manifest=$workpointManifest
    diagnostic_source_receipt=$diagnosticSourceReceipt;formal_volume_source_receipt=$formalSourceReceipt
    baseline_screening_run_manifest=(Join-Path $baseline.run 'run_manifest.json')
    probe_screening_run_manifest=(Join-Path $probe.run 'run_manifest.json')
    root_screening_run_manifest=$(if($null-ne$focused){Join-Path $focused.run 'run_manifest.json'}else{$null})
    selected_envelope_screening=[ordered]@{
      run_manifest=(Join-Path $selectedEnvelope.run 'run_manifest.json')
      particle_count=[int]$selectedEnvelope.particle_count;evidence_scope=[string]$selectedEnvelope.evidence_scope
      diagnostic=$selectedEnvelopeDiagnostic;focus_diagnostic=$selectedEnvelopeFocusDiagnostic
    }
    detector_plane_focus=[ordered]@{
      status=$(if($focusConverged){'converged'}else{'warning_not_converged'})
      minimum_mass_resolution=$minimumMassResolution;measured_mass_resolution=$measuredResolution
      resolution_satisfied=$resolutionSatisfied;source_z_span_mm=$sourceZSpanMm
      baseline=[ordered]@{
        diagnostic=$baselineFocusDiagnostic;formal_diagnostic=$baselineDiagnostic
        half_span_percent=$baselineFocusResult.half_span_percent
        particle_count=$baselineFocusResult.particle_count;fallback_runs=@($baselineFocusResult.fallback_runs)
      }
      probe=[ordered]@{
        diagnostic=$probeFocusDiagnostic;formal_diagnostic=$probeDiagnostic
        half_span_percent=$probeFocusResult.half_span_percent
        particle_count=$probeFocusResult.particle_count;fallback_runs=@($probeFocusResult.fallback_runs)
      }
      iterations=$focusIterations
      workpoint_reclosures=$workpointReclosures
    }
    z0_focus_classification=[ordered]@{baseline=$baselineZ0Classification;focused=$rootZ0Classification}
    comparison=$comparisonData
    collection=[ordered]@{baseline=$baselineCollectionGate;focused=$rootCollectionGate;satisfied=$collectionSatisfied}
    center_workpoint=[ordered]@{baseline=$baselineCenterGate;focused=$rootCenterGate;satisfied=$centerWorkpointSatisfied}
  })
  $retention=Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config
  $terminal=Update-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $capacitySession -RemainingCommittedNewBytes 0
  $capacitySession=$terminal.session
  $terminalPath=Join-Path $package.result_dir 'artifact_capacity_gate_terminal.json'
  Write-RunJson -Path $terminalPath -Depth 14 -Value $terminal
  $outputs=@($package.summary,$probeVariation,$startup,$terminalPath,$retention)+$rootVariations
  if($null-ne$comparison){$outputs+=$comparison}
  if($null-ne$repairedHandoff){$outputs+=$repairedHandoff}
  Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config -Status success `
    -Software @('SIMION 2020','Python 3.11') -Outputs $outputs
  $terminalized=$true
  Write-Host "MRTOF_NATIVE_CANDIDATE_CHAIN=PASS RUN_ID=$RunId"
}catch{
  if(-not$terminalized){
    Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config -Summary $package.summary `
      -SummaryRole 'mrtof_native_candidate_end_to_end_chain_summary' -Reason $_.Exception.Message `
      -Software @('SIMION 2020','Python 3.11') -Status failed -FailureStage $failureStage
    $terminalized=$true
  }
  throw
}finally{
  if(-not$terminalized-and(Test-Path -LiteralPath $package.run_config)){
    Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config -Summary $package.summary `
      -SummaryRole 'mrtof_native_candidate_end_to_end_chain_summary' `
      -Reason 'Native Candidate chain stopped before terminal publication.' `
      -Software @('SIMION 2020','Python 3.11') -Status interrupted -FailureStage $failureStage
  }
  if($null-ne$capacitySession){$null=Exit-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $capacitySession}
}

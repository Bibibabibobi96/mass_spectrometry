[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$OperatingRunPath,
  [Parameter(Mandatory)][string]$NegativeMirrorRunPath,
  [Parameter(Mandatory)][string]$NegativeBridgeRunPath,
  [Parameter(Mandatory)][string]$CentralRunPath,
  [Parameter(Mandatory)][string]$PositiveBridgeRunPath,
  [Parameter(Mandatory)][string]$PositiveMirrorRunPath,
  [ValidateSet(0.5,1.0)][double]$ScaleFactor=0.5,
  [string]$RunId='',
  [string]$SimionExe='',
  [string]$PythonExe=''
)

Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'

function Invoke-SimionStage {
  param([Parameter(Mandatory)][string]$Stage,[Parameter(Mandatory)][string[]]$Arguments)
  Push-Location -LiteralPath $solverDir
  try {
    & $simion @Arguments 2>&1|Tee-Object -FilePath (Join-Path $logDir "$Stage.log")
    if($LASTEXITCODE-ne 0){throw "SIMION stage failed: $Stage"}
  } finally {Pop-Location}
}

function Copy-Input {
  param([string]$Source,[string]$Name)
  if(-not(Test-Path -LiteralPath $Source -PathType Leaf)){throw "Required input is missing: $Source"}
  Copy-VerifiedRunInput -Source $Source -Destination (Join-Path $solverDir $Name)
}
function Format-InvariantNumber {
  param([double]$Value)
  [string]::Format([Globalization.CultureInfo]::InvariantCulture,'{0:R}',$Value)
}
function New-LuaHandoffPlane {
  param([string]$Name,[double]$Z,[object[]]$LeftBox,[object[]]$RightBox)
  $xMin=[Math]::Max([double]$LeftBox[0],[double]$RightBox[0]);$xMax=[Math]::Min([double]$LeftBox[3],[double]$RightBox[3])
  $yMin=[Math]::Max([double]$LeftBox[1],[double]$RightBox[1]);$yMax=[Math]::Min([double]$LeftBox[4],[double]$RightBox[4])
  if($xMin-ge$xMax-or$yMin-ge$yMax){throw "Local handoff $Name has no transverse overlap."}
  "{ name='$Name', region='local_handoff', face='z_plane', axis='z', coordinate_mm=$(Format-InvariantNumber $Z), u_axis='x', u_min_mm=$(Format-InvariantNumber $xMin), u_max_mm=$(Format-InvariantNumber $xMax), v_axis='y', v_min_mm=$(Format-InvariantNumber $yMin), v_max_mm=$(Format-InvariantNumber $yMax) }"
}

$projectId='parallel_mirror_dual_stripe_mr_tof'
$repoRoot=(Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$workspaceRoot=Split-Path -Parent $repoRoot
$python=if($PythonExe){[IO.Path]::GetFullPath($PythonExe)}else{Join-Path $repoRoot '.venv\Scripts\python.exe'}
$simion=if($SimionExe){[IO.Path]::GetFullPath($SimionExe)}else{Join-Path $env:ProgramFiles 'SIMION-2020\simion.exe'}
foreach($path in @($python,$simion)){if(-not(Test-Path -LiteralPath $path -PathType Leaf)){throw "Executable is missing: $path"}}
$operatingRun=(Resolve-Path -LiteralPath $OperatingRunPath).Path
$operatingManifest=Join-Path $operatingRun 'run_manifest.json'
& $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') $operatingManifest --require-status success --require-project $projectId
if($LASTEXITCODE-ne 0){throw 'Operating run manifest verification failed.'}
$operatingConfig=Get-Content -Raw -LiteralPath (Join-Path $operatingRun 'run_config.json')|ConvertFrom-Json -Depth 40
$materializationSource=Join-Path $operatingRun 'results\two_prism_trial_materialization.json'
$materialization=Get-Content -Raw -LiteralPath $materializationSource|ConvertFrom-Json -Depth 30
$reviewedContractSource=Join-Path $operatingRun 'simion\simion_prototype_contract.json'
$sourceProgram=Join-Path $PSScriptRoot 'mrtof_candidate.lua'
$sourceCounter=Join-Path $PSScriptRoot 'mirror_cycle_counter.lua'
$sourceMap=Join-Path $PSScriptRoot 'candidate_voltage_map.lua'
$sourceOperatingPoint=Join-Path $operatingRun 'simion\mrtof_three_component_candidate.operating_point.lua'
$sourceFly2=Join-Path $operatingRun 'simion\downstream_trial_source.input.fly2'
if(-not(Test-Path -LiteralPath $sourceFly2 -PathType Leaf)){$sourceFly2=Join-Path $operatingRun 'simion\mrtof_three_component_candidate.fly2'}
$sourceAnalyzer=[string]$operatingConfig.inputs.read_only_analyzer_pa0
$sourceAccelerator=[string]$operatingConfig.inputs.read_only_accelerator_pa0
$sourceDetector=[string]$operatingConfig.inputs.read_only_detector_pa
foreach($path in @($materializationSource,$reviewedContractSource,$sourceProgram,$sourceCounter,$sourceMap,$sourceOperatingPoint,$sourceFly2,$sourceAnalyzer,$sourceAccelerator,$sourceDetector)){
  if(-not(Test-Path -LiteralPath $path -PathType Leaf)){throw "Operating assembly input is missing: $path"}
}
$baseLocalWorkbench=$null;$baseLocalWorkbenchManifest=$null;$baseMaterializationSource=$null;$baseMaterialization=$null
$declaredBaseLocalManifest=[string]$operatingConfig.inputs.local_workbench_run_manifest
if(-not[string]::IsNullOrWhiteSpace($declaredBaseLocalManifest)-and(Test-Path -LiteralPath $declaredBaseLocalManifest -PathType Leaf)){
  & $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') $declaredBaseLocalManifest --require-status success --require-project $projectId --require-mode analyzer_local_replacement_workbench
  if($LASTEXITCODE-ne0){throw 'Declared base local workbench manifest verification failed.'}
  $baseLocalWorkbenchManifest=(Resolve-Path -LiteralPath $declaredBaseLocalManifest).Path
  $baseLocalWorkbench=Split-Path -Parent $baseLocalWorkbenchManifest
  $baseMaterializationSource=Join-Path $baseLocalWorkbench 'inputs\two_prism_trial_materialization.json'
  if(-not(Test-Path -LiteralPath $baseMaterializationSource -PathType Leaf)){throw 'Base local workbench lacks its frozen operating-point materialization.'}
  $baseMaterialization=Get-Content -Raw -LiteralPath $baseMaterializationSource|ConvertFrom-Json -Depth 30
}
if([string]::IsNullOrWhiteSpace($RunId)){$RunId=(Get-Date -Format 'yyyyMMdd_HHmmss')+'__build__simion__mrtof-local-replacement-iob'}

. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')
. (Join-Path $repoRoot 'common\host_execution_lease.ps1')
. (Join-Path $repoRoot 'common\parallel_gate_support.ps1')
. (Join-Path $PSScriptRoot 'analyzer_local_family_support.ps1')
$package=New-RunPackage -Python $python -RepoRoot $repoRoot `
  -ArtifactRoot (Join-Path $workspaceRoot "artifacts\projects\$projectId") `
  -RunId $RunId -Project $projectId -Mode 'analyzer_local_replacement_workbench' `
  -Software @('SIMION 2020','Python 3.11') -RetentionContractEnabled -RetentionClass solver_review `
  -RetentionReason 'GUI-reviewable eight-instance IOB retains five voltageized local replacement PA0s.' `
  -AdditionalDirectories @('simion') -UseShortExecutionPath
$runDir=$package.run_dir;$inputDir=$package.input_dir;$resultDir=$package.result_dir
$logDir=$package.log_dir;$solverDir=Join-Path $runDir 'simion';$runConfig=$package.run_config;$summary=$package.summary
$artifactRoot=Join-Path $workspaceRoot 'artifacts';$cacheRoot=Join-Path $artifactRoot 'common\simion\pa_family_cache'
$lease=$null;$terminalized=$false;$hostOutcome='failed';$failureStage='preflight';$temporaryBasisDir=$null
try {
  $families=@(
    Get-VerifiedAnalyzerLocalFamily -SourceRunPath $NegativeMirrorRunPath -ExpectedRegion mirror_turn_negative -ExpectedScale $ScaleFactor -Label negative_mirror -PythonExe $python -RepoRoot $repoRoot
    Get-VerifiedAnalyzerLocalFamily -SourceRunPath $NegativeBridgeRunPath -ExpectedRegion stripe_mirror_bridge_negative -ExpectedScale $ScaleFactor -Label negative_bridge -PythonExe $python -RepoRoot $repoRoot
    Get-VerifiedAnalyzerLocalFamily -SourceRunPath $CentralRunPath -ExpectedRegion central_transport -ExpectedScale $ScaleFactor -Label central -PythonExe $python -RepoRoot $repoRoot
    Get-VerifiedAnalyzerLocalFamily -SourceRunPath $PositiveBridgeRunPath -ExpectedRegion stripe_mirror_bridge_positive -ExpectedScale $ScaleFactor -Label positive_bridge -PythonExe $python -RepoRoot $repoRoot
    Get-VerifiedAnalyzerLocalFamily -SourceRunPath $PositiveMirrorRunPath -ExpectedRegion mirror_turn_positive -ExpectedScale $ScaleFactor -Label positive_mirror -PythonExe $python -RepoRoot $repoRoot
  )
  $failureStage='freeze_inputs'
  foreach($family in $families){
    $family.frozen_contract=Copy-VerifiedRunInput -Source $family.contract_source -Destination (Join-Path $inputDir "$($family.label)_family_contract.json")
    $family.frozen_identity=Copy-VerifiedRunInput -Source $family.identity_source -Destination (Join-Path $inputDir "$($family.label)_cache_identity.json")
    $family.frozen_publication=Copy-VerifiedRunInput -Source $family.publication_source -Destination (Join-Path $inputDir "$($family.label)_cache_publication.json")
    Resolve-AnalyzerLocalFamilyCacheGeneration -Family $family -PythonExe $python -RepoRoot $repoRoot -CacheRoot $cacheRoot|Out-Null
    Assert-AnalyzerLocalFamilyCacheReadOnly -Family $family
  }
  $planSource=Join-Path $families[0].source_run 'results\analyzer_local_refinement_plan.json'
  $frozenPlan=Copy-VerifiedRunInput -Source $planSource -Destination (Join-Path $inputDir 'analyzer_local_refinement_plan.json')
  $plan=Get-Content -Raw -LiteralPath $frozenPlan|ConvertFrom-Json -Depth 40
  $handoff=$plan.handoff_planes_project_mm
  $boxes=$plan.patches
  foreach($name in @('negative_central_to_bridge','positive_central_to_bridge','negative_bridge_to_mirror','positive_bridge_to_mirror')){
    if($null-eq$handoff.$name){throw "Local refinement plan lacks handoff $name."}
  }
  $frozenReviewed=Copy-VerifiedRunInput -Source $reviewedContractSource -Destination (Join-Path $inputDir 'simion_prototype_contract.json')
  $frozenMaterialization=Copy-VerifiedRunInput -Source $materializationSource -Destination (Join-Path $inputDir 'two_prism_trial_materialization.json')
  $frozenBaseLocalManifest=$null;$frozenBaseMaterialization=$null
  if($null-ne$baseLocalWorkbench){
    $frozenBaseLocalManifest=Copy-VerifiedRunInput -Source $baseLocalWorkbenchManifest -Destination (Join-Path $inputDir 'base_local_workbench_manifest.json')
    $frozenBaseMaterialization=Copy-VerifiedRunInput -Source $baseMaterializationSource -Destination (Join-Path $inputDir 'base_local_workbench_materialization.json')
  }
  foreach($copy in @(
    @($sourceProgram,'mrtof_local_replacement.lua'),@($sourceCounter,'mrtof_local_replacement.mirror_cycle_counter.lua'),
    @($sourceMap,'mrtof_local_replacement.voltage_map.lua'),@($sourceOperatingPoint,'mrtof_local_replacement.operating_point.lua'),
    @($sourceFly2,'mrtof_local_replacement_source.fly2'),
    @((Join-Path $PSScriptRoot 'voltageize_analyzer_pa0.lua'),'voltageize_analyzer_pa0.lua'),
    @((Join-Path $repoRoot 'common\simion\adjust_operating_pa_from_basis.lua'),'adjust_operating_pa_from_basis.lua'),
    @((Join-Path $repoRoot 'common\simion\measure_pa_basis_voltage.lua'),'measure_pa_basis_voltage.lua'),
    @((Join-Path $PSScriptRoot 'build_local_refinement_iob.lua'),'build_local_refinement_iob.lua'),
    @((Join-Path $PSScriptRoot 'inspect_local_refinement_iob.lua'),'inspect_local_refinement_iob.lua')
  )){Copy-Input -Source $copy[0] -Name $copy[1]|Out-Null}
  $seedRoot=Join-Path $repoRoot 'common\simion\assets\iob_instance_seeds'
  Copy-Input -Source (Join-Path $seedRoot '8_instance_seed.iob') -Name '8_instance_seed.iob'|Out-Null
  foreach($index in 1..10){$name=('iob_seed_placeholder_{0:D2}.pa0'-f$index);Copy-Input -Source (Join-Path $seedRoot $name) -Name $name|Out-Null}

  $localVoltages=@($materialization.mirror_voltages_v[1..4]) + @($materialization.stripe_biases_v) + @($materialization.prism_voltages_v)
  $analyzerVoltageArguments=@($materialization.analyzer_electrode_voltages_v|ForEach-Object{[string]::Format([Globalization.CultureInfo]::InvariantCulture,'{0:R}',[double]$_)})
  $localNames=@('local_negative_mirror.pa0','local_negative_bridge.pa0','local_central.pa0','local_positive_bridge.pa0','local_positive_mirror.pa0')
  $baseLocalVoltages=if($null-eq$baseMaterialization){@(1..8|ForEach-Object{0.0})}else{@($baseMaterialization.mirror_voltages_v[1..4])+@($baseMaterialization.stripe_biases_v)+@($baseMaterialization.prism_voltages_v)}
  $localVoltageDeltas=@(for($index=0;$index-lt 8;$index++){[double]$localVoltages[$index]-[double]$baseLocalVoltages[$index]})
  $changedLocalIndices=@(for($index=0;$index-lt 8;$index++){if([Math]::Abs([double]$localVoltageDeltas[$index])-gt1e-12){$index}})
  $failureStage='capacity_preflight'
  [int64]$requiredBytes=0
  $requiredBytes=[int64](Get-Item -LiteralPath $sourceAnalyzer).Length+[int64](Get-Item -LiteralPath $sourceAccelerator).Length+[int64](Get-Item -LiteralPath $sourceDetector).Length
  $requiredBytes+=[int64](Get-Item -LiteralPath ([IO.Path]::ChangeExtension($sourceAnalyzer,'.pa2'))).Length+[int64](Get-Item -LiteralPath ([IO.Path]::ChangeExtension($sourceAnalyzer,'.pa#'))).Length
  foreach($family in $families){
    $prefix=[string]$family.contract.family_prefix
    $basePaSource=if($null-eq$baseLocalWorkbench){Join-Path $family.generation_directory "$prefix.pa0"}else{Join-Path $baseLocalWorkbench ("simion\{0}"-f$localNames[[array]::IndexOf($families,$family)])}
    $requiredBytes+=2*[int64](Get-Item -LiteralPath $basePaSource).Length
    foreach($changedIndex in $changedLocalIndices){$requiredBytes+=[int64](Get-Item -LiteralPath (Join-Path $family.generation_directory ("{0}.pa{1}"-f$prefix,($changedIndex+1)))).Length}
  }
  $startup=Invoke-ArtifactCapacityGate -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot -RequiredHeadroomBytes $requiredBytes -ProtectedPaths @($package.artifact_run_dir,$operatingRun)
  $startupPath=Join-Path $resultDir 'artifact_capacity_gate_startup.json';Write-RunJson -Path $startupPath -Depth 14 -Value $startup

  $failureStage='materialize_reused_components'
  $localAccelerator=Copy-VerifiedRunInput -Source $sourceAccelerator -Destination (Join-Path $solverDir 'mrtof_accelerator.pa0')
  $localDetector=Copy-VerifiedRunInput -Source $sourceDetector -Destination (Join-Path $solverDir 'mrtof_detector.pa#')
  $failureStage='voltageize_global_analyzer';$lease=Enter-HostExecutionLease -Role SIMION -RunId $RunId
  $temporaryBasisDir=Join-Path ([IO.Path]::GetTempPath()) ('mrtof_local_workbench_basis_'+[guid]::NewGuid().ToString('N'))
  New-Item -ItemType Directory -Path $temporaryBasisDir|Out-Null
  # Freeze the basis/raw arrays before opening the source `.pa0` family in
  # SIMION.  Fast Adjust needs its sibling `.paN` files, while a concurrent
  # family bookkeeping write must never race these frozen-input copies.
  $globalBasisStandalone=Join-Path $temporaryBasisDir 'global_basis.pa'
  $globalRawStandalone=Join-Path $temporaryBasisDir 'global_raw.pa'
  Copy-VerifiedRunInput -Source ([IO.Path]::ChangeExtension($sourceAnalyzer,'.pa2')) -Destination $globalBasisStandalone -VerificationAttempts 3|Out-Null
  Copy-VerifiedRunInput -Source ([IO.Path]::ChangeExtension($sourceAnalyzer,'.pa#')) -Destination $globalRawStandalone -VerificationAttempts 3|Out-Null
  $globalAnalyzer=Join-Path $solverDir 'mrtof_analyzer.pa0'
  Invoke-SimionStage -Stage 'voltageize_global_analyzer' -Arguments (@('--nogui','--noprompt','lua',(Join-Path $solverDir 'voltageize_analyzer_pa0.lua'),$sourceAnalyzer,$globalAnalyzer)+$analyzerVoltageArguments)
  $normalizationCsv=Join-Path $resultDir 'global_basis_voltage.csv'
  Invoke-SimionStage -Stage 'measure_global_basis_voltage' -Arguments @('--nogui','--noprompt','lua',(Join-Path $solverDir 'measure_pa_basis_voltage.lua'),$globalBasisStandalone,$globalRawStandalone,2,$normalizationCsv)
  $basisVoltage=[double](Import-Csv -LiteralPath $normalizationCsv).basis_voltage_V
  $basisText=(@($changedLocalIndices|ForEach-Object{[string]::Format([Globalization.CultureInfo]::InvariantCulture,'{0:R}',$basisVoltage)})-join',')
  $deltaText=(@($changedLocalIndices|ForEach-Object{[string]::Format([Globalization.CultureInfo]::InvariantCulture,'{0:R}',[double]$localVoltageDeltas[$_])})-join',')
  $failureStage='combine_local_operating_replacements_without_refine'
  for($index=0;$index-lt$families.Count;$index++){
    $prefix=[string]$families[$index].contract.family_prefix
    $privateBase=Join-Path $temporaryBasisDir ("family{0}_base.pa0"-f($index+1))
    $basePaSource=if($null-eq$baseLocalWorkbench){Join-Path $families[$index].generation_directory "$prefix.pa0"}else{Join-Path $baseLocalWorkbench "simion\$($localNames[$index])"}
    Copy-VerifiedRunInput -Source $basePaSource -Destination $privateBase -VerificationAttempts 3|Out-Null
    $privateResponses=@()
    foreach($changedIndex in $changedLocalIndices){
      $responseId=$changedIndex+1
      $privateResponse=Join-Path $temporaryBasisDir ("family{0}_response{1}.pa"-f($index+1),$responseId)
      Copy-VerifiedRunInput -Source (Join-Path $families[$index].generation_directory ("{0}.pa{1}"-f$prefix,$responseId)) -Destination $privateResponse -VerificationAttempts 3|Out-Null
      $privateResponses+=$privateResponse
    }
    if($changedLocalIndices.Count-eq0){
      Copy-VerifiedRunInput -Source $privateBase -Destination (Join-Path $solverDir $localNames[$index]) -VerificationAttempts 3|Out-Null
    }else{
      Invoke-SimionStage -Stage ("combine_local_operating_{0}"-f$families[$index].label) -Arguments @('--nogui','--noprompt','lua',(Join-Path $solverDir 'adjust_operating_pa_from_basis.lua'),$privateBase,(Join-Path $solverDir $localNames[$index]),($privateResponses-join'|'),$basisText,$deltaText)
    }
  }
  foreach($family in $families){Resolve-AnalyzerLocalFamilyCacheGeneration -Family $family -PythonExe $python -RepoRoot $repoRoot -CacheRoot $cacheRoot|Out-Null}
  Remove-GateTemporaryDirectory -Path $temporaryBasisDir -ExpectedNamePrefix 'mrtof_local_workbench_basis_';$temporaryBasisDir=$null

  $posePath=Join-Path $resultDir 'resolved_iob_pose.json'
  $poseCode="import json,sys; from pathlib import Path; from projects.parallel_mirror_dual_stripe_mr_tof.analysis.split_candidate_geometry import resolve_split_iob_origins; p=Path(sys.argv[1]); c=json.loads(p.read_text(encoding='utf-8')); Path(sys.argv[2]).write_text(json.dumps({'origins_mm':resolve_split_iob_origins(p),'mesh_mm_per_gu':c['simion']['component_mesh_mm_per_gu']},indent=2)+chr(10),encoding='utf-8')"
  Push-Location $repoRoot;try{$saved=$env:PYTHONPATH;$env:PYTHONPATH=$repoRoot;& $python -c $poseCode $frozenReviewed $posePath;if($LASTEXITCODE-ne 0){throw 'Pose derivation failed.'}}finally{$env:PYTHONPATH=$saved;Pop-Location}
  $pose=Get-Content -Raw -LiteralPath $posePath|ConvertFrom-Json
  $origins=@();$origins+=,@($pose.origins_mm.analyzer)
  foreach($family in $families){$origins+=,@($family.contract.patch_origin_project_mm)}
  $origins+=,@($pose.origins_mm.accelerator);$origins+=,@($pose.origins_mm.detector)
  $localConfig=Join-Path $solverDir 'local_refinement.input.lua'
  $planeTexts=@(
    New-LuaHandoffPlane -Name 'handoff_negative_central_to_bridge__z_plane' -Z $handoff.negative_central_to_bridge -LeftBox @($boxes.central_transport) -RightBox @($boxes.stripe_mirror_bridge_negative)
    New-LuaHandoffPlane -Name 'handoff_positive_central_to_bridge__z_plane' -Z $handoff.positive_central_to_bridge -LeftBox @($boxes.central_transport) -RightBox @($boxes.stripe_mirror_bridge_positive)
    New-LuaHandoffPlane -Name 'handoff_negative_bridge_to_mirror__z_plane' -Z $handoff.negative_bridge_to_mirror -LeftBox @($boxes.stripe_mirror_bridge_negative) -RightBox @($boxes.mirror_turn_negative)
    New-LuaHandoffPlane -Name 'handoff_positive_bridge_to_mirror__z_plane' -Z $handoff.positive_bridge_to_mirror -LeftBox @($boxes.stripe_mirror_bridge_positive) -RightBox @($boxes.mirror_turn_positive)
  )
  $configText="return { enabled=true, static_injection_only=true, global_analyzer_instance=1, accelerator_instance=7, detector_instance=8, instances={ {instance=2,name='negative_mirror',z_max_mm=$(Format-InvariantNumber $handoff.negative_bridge_to_mirror)}, {instance=3,name='negative_bridge',z_min_mm=$(Format-InvariantNumber $handoff.negative_bridge_to_mirror),z_max_mm=$(Format-InvariantNumber $handoff.negative_central_to_bridge)}, {instance=4,name='central',z_min_mm=$(Format-InvariantNumber $handoff.negative_central_to_bridge),z_max_mm=$(Format-InvariantNumber $handoff.positive_central_to_bridge)}, {instance=5,name='positive_bridge',z_min_mm=$(Format-InvariantNumber $handoff.positive_central_to_bridge),z_max_mm=$(Format-InvariantNumber $handoff.positive_bridge_to_mirror)}, {instance=6,name='positive_mirror',z_min_mm=$(Format-InvariantNumber $handoff.positive_bridge_to_mirror)} }, patch_interface_planes_project={ $($planeTexts-join', ') } }`n"
  [IO.File]::WriteAllText($localConfig,$configText,[Text.UTF8Encoding]::new($false))
  $iob=Join-Path $solverDir 'mrtof_local_replacement.iob'
  $paths=@($globalAnalyzer)+@($localNames|ForEach-Object{Join-Path $solverDir $_})+@($localAccelerator,$localDetector)
  $originArguments=@();foreach($origin in $origins){foreach($value in $origin){$originArguments+=[string]::Format([Globalization.CultureInfo]::InvariantCulture,'{0:R}',[double]$value)}}
  $failureStage='build_local_replacement_iob'
  Invoke-SimionStage -Stage 'build_local_replacement_iob' -Arguments (@('--nogui','--noprompt','lua',(Join-Path $solverDir 'build_local_refinement_iob.lua'),'--',(Join-Path $solverDir '8_instance_seed.iob'))+$paths+@($iob,(Join-Path $solverDir 'mrtof_local_replacement.lua'),(Join-Path $solverDir 'mrtof_local_replacement_source.fly2'),$localConfig)+$originArguments)
  $meshArguments=@()
  for($index=0;$index-lt 8;$index++){
    foreach($value in $origins[$index]){$meshArguments+=[string]::Format([Globalization.CultureInfo]::InvariantCulture,'{0:R}',[double]$value)}
    $mesh=if($index -eq 0){@($pose.mesh_mm_per_gu.analyzer)}elseif($index -ge 1 -and $index -le 5){@($families[$index-1].contract.identity.mesh.mm_per_gu)}elseif($index -eq 6){@($pose.mesh_mm_per_gu.accelerator)}else{@($pose.mesh_mm_per_gu.detector)}
    foreach($value in $mesh){$meshArguments+=[string]::Format([Globalization.CultureInfo]::InvariantCulture,'{0:R}',[double]$value)}
  }
  $report=Join-Path $resultDir 'local_replacement_iob_structure.txt'
  $failureStage='inspect_local_replacement_iob'
  Invoke-SimionStage -Stage 'inspect_local_replacement_iob' -Arguments (@('--nogui','--noprompt','lua',(Join-Path $solverDir 'inspect_local_refinement_iob.lua'),'--',$iob,$report)+$meshArguments)
  $relocatedReport=Join-Path $resultDir 'local_replacement_iob_relocated_structure.txt'
  $artifactIob=Join-Path $package.artifact_run_dir 'simion\mrtof_local_replacement.iob'
  $failureStage='inspect_relocated_local_replacement_iob'
  Invoke-SimionStage -Stage 'inspect_relocated_local_replacement_iob' -Arguments (@('--nogui','--noprompt','lua',(Join-Path $solverDir 'inspect_local_refinement_iob.lua'),'--',$artifactIob,$relocatedReport)+$meshArguments)

  $configuration=Get-Content -Raw -LiteralPath $runConfig|ConvertFrom-Json -AsHashtable
  $localOperatingPaMethod=if($null-eq$baseLocalWorkbench){'verified zero-base standalone basis superposition; no Refine'}else{'verified prior-workbench delta basis superposition; no Refine'}
  # Run config is part of the permanent evidence chain.  Never publish the
  # short execution alias: it is deliberately removed after terminalization.
  $artifactReviewed=Join-Path $package.artifact_run_dir 'inputs\simion_prototype_contract.json'
  $artifactMaterialization=Join-Path $package.artifact_run_dir 'inputs\two_prism_trial_materialization.json'
  $configuration.inputs=[ordered]@{operating_run_manifest=$operatingManifest;reviewed_geometry_contract=$artifactReviewed;operating_point_materialization=$artifactMaterialization;base_local_workbench_manifest=$frozenBaseLocalManifest;base_local_workbench_materialization=$frozenBaseMaterialization;local_family_manifests=@($families.manifest);global_analyzer_pa0=$sourceAnalyzer;accelerator_pa0=$sourceAccelerator;detector_pa=$sourceDetector;operating_iob=Join-Path $package.artifact_run_dir 'simion\mrtof_local_replacement.iob'}
  $configuration.parameters=[ordered]@{global_analyzer_mesh_mm_per_gu=@($pose.mesh_mm_per_gu.analyzer);local_mesh_mm_per_gu=@($ScaleFactor,$ScaleFactor,$ScaleFactor);local_operating_pa_method=if($null-eq$baseLocalWorkbench){'verified zero-base standalone basis superposition; no Refine'}else{'verified prior-workbench delta basis superposition; no Refine'};changed_local_voltage_indices=@($changedLocalIndices);local_voltage_deltas_v=@($localVoltageDeltas);basis_voltage_v=$basisVoltage;handoff_z_mm=@($handoff.negative_bridge_to_mirror,$handoff.negative_central_to_bridge,$handoff.positive_central_to_bridge,$handoff.positive_bridge_to_mirror);instance_priority='higher_instance_wins; local instance_adjust suppression falls back toward global instance 1'}
  Write-RunJson -Path $runConfig -Depth 20 -Value $configuration
  Write-RunJson -Path $summary -Depth 20 -Value ([ordered]@{schema_version=1;role='mrtof_analyzer_local_replacement_workbench';status='success';qualification='gui_reviewable_local_replacement_assembly__flight_pending';instance_count=8;global_analyzer_mesh_mm_per_gu=@($pose.mesh_mm_per_gu.analyzer);local_mesh_mm_per_gu=@($ScaleFactor,$ScaleFactor,$ScaleFactor);local_operating_pa_method=$localOperatingPaMethod;changed_local_voltage_indices=@($changedLocalIndices);basis_voltage_v=$basisVoltage;iob_path=Join-Path $package.artifact_run_dir 'simion\mrtof_local_replacement.iob';reason='The global analyser remains the fallback at its resolved isotropic mesh. Five higher-priority local PA0s replace only their contract-owned z responsibility intervals.'})
  $retention=Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $runConfig
  $failureStage='capacity_terminal';[int64]$maximum=[int64](Get-ChildItem -LiteralPath $package.artifact_run_dir -Recurse -File|Measure-Object Length -Sum).Sum
  $terminal=Invoke-ArtifactCapacityGate -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot -ProtectedPaths @($package.artifact_run_dir,$operatingRun) -KnownMeasuredBytes ([int64]$startup.measured_after_bytes) -MaximumNewArtifactBytes $maximum
  $terminalPath=Join-Path $resultDir 'artifact_capacity_gate_terminal.json';Write-RunJson -Path $terminalPath -Depth 14 -Value $terminal
  Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Status success -Software @('SIMION 2020','Python 3.11') -Outputs (@($summary,$report,$relocatedReport,$posePath,$startupPath,$terminalPath,$retention,$iob)+$paths+@((Join-Path $solverDir 'mrtof_local_replacement.lua'),(Join-Path $solverDir 'mrtof_local_replacement.operating_point.lua'),(Join-Path $solverDir 'mrtof_local_replacement.local_refinement.lua'),(Join-Path $solverDir 'mrtof_local_replacement.fly2')))
  $terminalized=$true;$hostOutcome='success';Write-Host "MRTOF_LOCAL_REPLACEMENT_WORKBENCH=PASS RUN_ID=$RunId IOB=$iob"
} catch {
  if(-not$terminalized){Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Summary $summary -SummaryRole 'mrtof_analyzer_local_replacement_workbench' -Reason $_.Exception.Message -Software @('SIMION 2020','Python 3.11') -Status failed -FailureStage $failureStage;$terminalized=$true}
  throw
} finally {
  if($null-ne$temporaryBasisDir){Remove-GateTemporaryDirectory -Path $temporaryBasisDir -ExpectedNamePrefix 'mrtof_local_workbench_basis_'}
  if($null-ne$lease){Exit-HostExecutionLease -Lease $lease -Outcome $hostOutcome -RunId $RunId}
  Remove-RunPackageExecutionAlias -Package $package
}

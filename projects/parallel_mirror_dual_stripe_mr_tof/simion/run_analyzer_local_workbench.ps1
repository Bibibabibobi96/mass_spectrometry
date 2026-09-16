[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$OperatingRunPath,
  [Parameter(Mandatory)][string]$NegativeMirrorRunPath,
  [Parameter(Mandatory)][string]$NegativeBridgeRunPath,
  [Parameter(Mandatory)][string]$CentralRunPath,
  [Parameter(Mandatory)][string]$PositiveBridgeRunPath,
  [Parameter(Mandatory)][string]$PositiveMirrorRunPath,
  [ValidateSet(0.5,1.0)][double]$ScaleFactor=0.5,
  [switch]$RebuildFromFamilyZeroBase,
  [string]$ContractPath='',
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

function Invoke-ParallelSimionStageBatch {
  param(
    [Parameter(Mandatory)][object[]]$Jobs,
    [Parameter(Mandatory)][string]$BatchName
  )
  if($Jobs.Count-eq0){return}
  $records=@()
  try {
    foreach($job in $Jobs){
      $stdoutPath=Join-Path $logDir ("{0}.stdout.log"-f$job.Stage)
      $stderrPath=Join-Path $logDir ("{0}.stderr.log"-f$job.Stage)
      $startInfo=[Diagnostics.ProcessStartInfo]::new()
      $startInfo.FileName=if($null-ne$job.PSObject.Properties['FileName']){[string]$job.FileName}else{$simion}
      $startInfo.WorkingDirectory=if($null-ne$job.PSObject.Properties['WorkingDirectory']){[string]$job.WorkingDirectory}else{$solverDir}
      $startInfo.UseShellExecute=$false
      $startInfo.CreateNoWindow=$true
      $startInfo.RedirectStandardOutput=$true
      $startInfo.RedirectStandardError=$true
      foreach($argument in @($job.Arguments)){$startInfo.ArgumentList.Add([string]$argument)}
      $process=[Diagnostics.Process]::new()
      $process.StartInfo=$startInfo
      if(-not$process.Start()){throw "SIMION parallel stage did not start: $($job.Stage)"}
      $records+=,[pscustomobject]@{
        Stage=[string]$job.Stage
        Process=$process
        StdoutPath=$stdoutPath
        StderrPath=$stderrPath
        StdoutTask=$process.StandardOutput.ReadToEndAsync()
        StderrTask=$process.StandardError.ReadToEndAsync()
      }
    }
    $failures=@()
    foreach($record in $records){
      $record.Process.WaitForExit()
      $stdout=$record.StdoutTask.GetAwaiter().GetResult()
      $stderr=$record.StderrTask.GetAwaiter().GetResult()
      [IO.File]::WriteAllText($record.StdoutPath,$stdout,[Text.UTF8Encoding]::new($false))
      [IO.File]::WriteAllText($record.StderrPath,$stderr,[Text.UTF8Encoding]::new($false))
      if(-not[string]::IsNullOrWhiteSpace($stdout)){Write-Host $stdout.TrimEnd()}
      if(-not[string]::IsNullOrWhiteSpace($stderr)){Write-Warning $stderr.TrimEnd()}
      if($record.Process.ExitCode-ne0){$failures+="$($record.Stage) (exit $($record.Process.ExitCode))"}
      $record.Process.Dispose()
    }
    if($failures.Count-gt0){throw "SIMION parallel batch failed: $BatchName`: $($failures-join'; ')"}
  } catch {
    foreach($record in $records){
      if($null-ne$record.Process){
        try {if(-not$record.Process.HasExited){$record.Process.Kill($true);$record.Process.WaitForExit()}}catch{}
        try {$record.Process.Dispose()}catch{}
      }
    }
    throw
  }
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
function Convert-OperatingPointFieldGateContract {
  param(
    [Parameter(Mandatory)][string]$Path,
    [Parameter(Mandatory)][ValidateSet('static','initial_exit_triggered_single_center','fixed_global_time')][string]$PulseMode
  )
  $text=[IO.File]::ReadAllText($Path)
  $legacyFieldName='runtime_fast_adjust_accelerator_enable'
  $currentFieldName='runtime_accelerator_field_gate_enable'
  $legacyMatches=[regex]::Matches($text,"\b$legacyFieldName\s*=\s*(true|false)\b")
  $currentMatches=[regex]::Matches($text,"\b$currentFieldName\s*=\s*(true|false)\b")
  if($legacyMatches.Count-and$currentMatches.Count){throw 'Operating point declares both legacy and current accelerator pulse implementation fields.'}
  $gateRequired=$PulseMode-ne'static'
  if($currentMatches.Count){
    if($currentMatches.Count-ne1){throw 'Operating point accelerator field-gate declaration is not unique.'}
    $declared=[string]::Equals($currentMatches[0].Groups[1].Value,'true',[StringComparison]::Ordinal)
    if($declared-ne$gateRequired){throw 'Operating point accelerator field-gate declaration conflicts with its pulse mode.'}
    return 'current_accelerator_field_gate_contract'
  }
  if($legacyMatches.Count){
    if($legacyMatches.Count-ne1){throw 'Legacy operating point accelerator pulse declaration is not unique.'}
    $declared=[string]::Equals($legacyMatches[0].Groups[1].Value,'true',[StringComparison]::Ordinal)
    if($declared-ne$gateRequired){throw 'Legacy operating point accelerator pulse declaration conflicts with its pulse mode.'}
    $updated=$text.Replace($legacyFieldName,$currentFieldName)
    [IO.File]::WriteAllText($Path,$updated,[Text.UTF8Encoding]::new($false))
    return 'legacy_accelerator_fast_adjust_authorization_renamed_to_field_gate'
  }
  if($gateRequired){throw 'Pulsed operating point lacks an accelerator field-gate authorization.'}
  return 'static_operating_point_requires_no_field_gate'
}
function Assert-ManifestOutputIdentity {
  param([Parameter(Mandatory)]$Manifest,[Parameter(Mandatory)][string]$Path,[Parameter(Mandatory)][string]$Label)
  $resolved=(Resolve-Path -LiteralPath $Path).Path
  $records=@($Manifest.outputs|Where-Object{[string]::Equals([IO.Path]::GetFullPath([string]$_.path),$resolved,[StringComparison]::OrdinalIgnoreCase)})
  if($records.Count-ne1){throw "$Label is not uniquely bound as an output of its verified run manifest: $resolved"}
  $item=Get-Item -LiteralPath $resolved -Force
  $actualHash=(Get-FileHash -LiteralPath $resolved -Algorithm SHA256).Hash
  if([int64]$records[0].bytes-ne[int64]$item.Length-or[string]$records[0].sha256-ne$actualHash){
    throw "$Label differs from the bytes frozen by its verified run manifest: $resolved"
  }
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
$currentContractSource=if([string]::IsNullOrWhiteSpace($ContractPath)){
  Join-Path $repoRoot 'projects\parallel_mirror_dual_stripe_mr_tof\config\simion_candidate_two_zone.json'
}else{(Resolve-Path -LiteralPath $ContractPath).Path}
$operatingRun=(Resolve-Path -LiteralPath $OperatingRunPath).Path
$operatingManifest=Join-Path $operatingRun 'run_manifest.json'
& $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') $operatingManifest --require-status success --require-project $projectId
if($LASTEXITCODE-ne 0){throw 'Operating run manifest verification failed.'}
$operatingManifestRecord=Get-Content -Raw -LiteralPath $operatingManifest|ConvertFrom-Json -Depth 40
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
$sourceAnalyzer=if($null-ne$operatingConfig.inputs.PSObject.Properties['read_only_analyzer_pa']){[string]$operatingConfig.inputs.read_only_analyzer_pa}else{[string]$operatingConfig.inputs.read_only_analyzer_pa0}
$sourceAccelerator=if($null-ne$operatingConfig.inputs.PSObject.Properties['read_only_accelerator_pa']){[string]$operatingConfig.inputs.read_only_accelerator_pa}else{[string]$operatingConfig.inputs.read_only_accelerator_pa0}
$sourceDetector=[string]$operatingConfig.inputs.read_only_detector_pa
$retainedGuiDirectory=Join-Path $operatingRun 'simion\gui_workbench'
$retainedGuiInputs=@{
  analyzer=Join-Path $retainedGuiDirectory 'iob_input_analyzer.pa'
  accelerator=Join-Path $retainedGuiDirectory 'iob_input_accelerator.pa'
  detector=Join-Path $retainedGuiDirectory 'iob_input_detector.pa'
}
if(Test-Path -LiteralPath $retainedGuiInputs.analyzer -PathType Leaf){
  foreach($entry in @(
    @('analyzer',$retainedGuiInputs.analyzer),
    @('accelerator',$retainedGuiInputs.accelerator),
    @('detector',$retainedGuiInputs.detector)
  )){
    Assert-ManifestOutputIdentity -Manifest $operatingManifestRecord -Path $entry[1] -Label "retained GUI $($entry[0]) PA"
  }
  $sourceAnalyzer=$retainedGuiInputs.analyzer
  $sourceAccelerator=$retainedGuiInputs.accelerator
  $sourceDetector=$retainedGuiInputs.detector
}
foreach($path in @($materializationSource,$reviewedContractSource,$sourceProgram,$sourceCounter,$sourceMap,$sourceOperatingPoint,$sourceFly2,$sourceAnalyzer,$sourceAccelerator,$sourceDetector)){
  if(-not(Test-Path -LiteralPath $path -PathType Leaf)){throw "Operating assembly input is missing: $path"}
}
$baseLocalWorkbench=$null;$baseLocalWorkbenchManifest=$null;$baseLocalWorkbenchManifestRecord=$null;$baseLocalWorkbenchConfig=$null;$baseMaterializationSource=$null;$baseMaterialization=$null
$declaredBaseLocalManifest=[string]$operatingConfig.inputs.local_workbench_run_manifest
if(-not[string]::IsNullOrWhiteSpace($declaredBaseLocalManifest)){
  if(-not(Test-Path -LiteralPath $declaredBaseLocalManifest -PathType Leaf)){
    throw "Operating run declares a missing base local workbench manifest: $declaredBaseLocalManifest"
  }
  & $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') $declaredBaseLocalManifest --require-status success --require-project $projectId --require-mode analyzer_local_replacement_workbench
  if($LASTEXITCODE-ne0){throw 'Declared base local workbench manifest verification failed.'}
  $baseLocalWorkbenchManifest=(Resolve-Path -LiteralPath $declaredBaseLocalManifest).Path
  $baseLocalWorkbenchManifestRecord=Get-Content -Raw -LiteralPath $baseLocalWorkbenchManifest|ConvertFrom-Json -Depth 40
  $baseLocalWorkbench=Split-Path -Parent $baseLocalWorkbenchManifest
  $baseLocalWorkbenchConfig=Get-Content -Raw -LiteralPath (Join-Path $baseLocalWorkbench 'run_config.json')|ConvertFrom-Json -Depth 40
  $baseMaterializationSource=Join-Path $baseLocalWorkbench 'inputs\two_prism_trial_materialization.json'
  if(-not(Test-Path -LiteralPath $baseMaterializationSource -PathType Leaf)){throw 'Base local workbench lacks its frozen operating-point materialization.'}
  $baseMaterialization=Get-Content -Raw -LiteralPath $baseMaterializationSource|ConvertFrom-Json -Depth 30
}
if($RebuildFromFamilyZeroBase){
  $baseLocalWorkbench=$null
  $baseLocalWorkbenchManifest=$null
  $baseLocalWorkbenchManifestRecord=$null
  $baseLocalWorkbenchConfig=$null
  $baseMaterializationSource=$null
  $baseMaterialization=$null
}
if([string]::IsNullOrWhiteSpace($RunId)){$RunId=(Get-Date -Format 'yyyyMMdd_HHmmss')+'__build__simion__mrtof-local-replacement-iob'}

. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')
. (Join-Path $repoRoot 'common\host_execution_lease.ps1')
. (Join-Path $repoRoot 'common\parallel_gate_support.ps1')
. (Join-Path $repoRoot 'common\simion\short_pa_path_support.ps1')
. (Join-Path $PSScriptRoot 'analyzer_local_family_support.ps1')
$package=New-RunPackage -Python $python -RepoRoot $repoRoot `
  -ArtifactRoot (Join-Path $workspaceRoot "artifacts\projects\$projectId") `
  -RunId $RunId -Project $projectId -Mode 'analyzer_local_replacement_workbench' `
  -Software @('SIMION 2020','Python 3.11') -RetentionContractEnabled -RetentionClass solver_review `
  -RetentionReason 'GUI-reviewable eight-instance IOB retains five detached standalone local operating PAs.' `
  -AdditionalDirectories @('simion') -UseShortExecutionPath
$runDir=$package.run_dir;$inputDir=$package.input_dir;$resultDir=$package.result_dir
$logDir=$package.log_dir;$solverDir=Join-Path $runDir 'simion';$runConfig=$package.run_config;$summary=$package.summary
$artifactRoot=Join-Path $workspaceRoot 'artifacts';$cacheRoot=Join-Path $artifactRoot 'common\simion\pa_family_cache'
$lease=$null;$terminalized=$false;$hostOutcome='failed';$failureStage='preflight';$basisLinkDir=$null;$parallelBasisLinkDirs=@();$iobProjectionDir=$null
$basisMeasurementReceipts=@();$basisInventoryReceipts=@();$compositionPlanPaths=@();$frozenBasisMeasurement=$null;$frozenElectrodeInventory=$null
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
  }
  $baselineSources=@($families|ForEach-Object{Join-Path $_.source_run 'inputs\simion_candidate_two_zone.json'})
  foreach($path in $baselineSources){
    if(-not(Test-Path -LiteralPath $path -PathType Leaf)){throw "Local-family frozen baseline is missing: $path"}
  }
  $baselineHashes=@($baselineSources|ForEach-Object{(Get-FileHash -LiteralPath $_ -Algorithm SHA256).Hash}|Select-Object -Unique)
  $familyCanonicalAnalyzers=@($families|ForEach-Object{Join-Path $_.source_run 'simion\canonical_global_mrtof_analyzer.gem'})
  $familyRefinementPlans=@($families|ForEach-Object{Join-Path $_.source_run 'results\analyzer_local_refinement_plan.json'})
  foreach($path in @($familyCanonicalAnalyzers)+@($familyRefinementPlans)){
    if(-not(Test-Path -LiteralPath $path -PathType Leaf)){throw "Local-family projected geometry evidence is missing: $path"}
  }
  $familyCanonicalHashes=@($familyCanonicalAnalyzers|ForEach-Object{(Get-FileHash -LiteralPath $_ -Algorithm SHA256).Hash}|Select-Object -Unique)
  $familyPlanHashes=@($familyRefinementPlans|ForEach-Object{(Get-FileHash -LiteralPath $_ -Algorithm SHA256).Hash}|Select-Object -Unique)
  if($familyCanonicalHashes.Count-ne1){throw 'Local PA families do not share one identical canonical analyser GEM projection.'}
  if($familyPlanHashes.Count-ne1){throw 'Local PA families do not share one identical local-refinement partition projection.'}
  $frozenFamilyBaselines=@()
  for($index=0;$index-lt$families.Count;$index++){
    $frozenFamilyBaselines+=Copy-VerifiedRunInput -Source $baselineSources[$index] `
      -Destination (Join-Path $inputDir "$($families[$index].label)_family_build_baseline_contract.json")
  }
  $frozenFamilyBaseline=Copy-VerifiedRunInput -Source $baselineSources[0] -Destination (Join-Path $inputDir 'family_build_baseline_contract.json')
  $familyBaselineEquivalence=[ordered]@{
    raw_contracts_identical=($baselineHashes.Count-eq1)
    raw_contract_sha256=@($baselineHashes)
    canonical_analyzer_gem_sha256=[string]$familyCanonicalHashes[0]
    local_refinement_plan_sha256=[string]$familyPlanHashes[0]
    acceptance_rule='raw baseline text may differ only when canonical analyser GEM and local-refinement partition are byte-identical'
  }
  $frozenBaseline=Copy-VerifiedRunInput -Source $currentContractSource -Destination (Join-Path $inputDir 'simion_candidate_two_zone.json')
  $planSource=$familyRefinementPlans[0]
  $frozenPlan=Copy-VerifiedRunInput -Source $planSource -Destination (Join-Path $inputDir 'analyzer_local_refinement_plan.json')
  $frozenBasisMeasurement=Copy-VerifiedRunInput `
    -Source (Join-Path $repoRoot 'common\simion\measure_pa_basis_voltage.lua') `
    -Destination (Join-Path $inputDir 'measure_pa_basis_voltage.lua')
  $frozenElectrodeInventory=Copy-VerifiedRunInput `
    -Source (Join-Path $repoRoot 'common\simion\inspect_pa_electrode_ids.lua') `
    -Destination (Join-Path $inputDir 'inspect_pa_electrode_ids.lua')
  $currentCanonicalAnalyzer=Join-Path $solverDir 'current_contract_mrtof_analyzer.gem'
  Push-Location $repoRoot
  try{
    $saved=$env:PYTHONPATH;$env:PYTHONPATH=$repoRoot
    & $python -m projects.parallel_mirror_dual_stripe_mr_tof.analysis.split_candidate_geometry `
      --contract $frozenBaseline --component analyzer --output $currentCanonicalAnalyzer
    if($LASTEXITCODE-ne0){throw 'Current baseline analyser GEM derivation failed.'}
  }finally{$env:PYTHONPATH=$saved;Pop-Location}
  $familyCanonicalAnalyzer=$familyCanonicalAnalyzers[0]
  if(-not(Test-RunFilesIdentical -Left $currentCanonicalAnalyzer -Right $familyCanonicalAnalyzer)){
    throw 'Current baseline changes the analyser GEM used to build the local PA families.'
  }
  $currentPlan=Join-Path $resultDir 'current_analyzer_local_refinement_plan.json'
  Push-Location $repoRoot
  try{
    $saved=$env:PYTHONPATH;$env:PYTHONPATH=$repoRoot
    & $python -m projects.parallel_mirror_dual_stripe_mr_tof.analysis.analyzer_local_refinement_plan `
      --contract $frozenBaseline --output $currentPlan
    if($LASTEXITCODE-ne0){throw 'Current baseline local refinement plan derivation failed.'}
  }finally{$env:PYTHONPATH=$saved;Pop-Location}
  if(-not(Test-RunFilesIdentical -Left $currentPlan -Right $frozenPlan)){
    throw 'Current baseline changes the local PA partition used by the cached families.'
  }
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
    @((Join-Path $repoRoot 'common\simion\compose_standalone_pa.lua'),'compose_standalone_pa.lua'),
    @((Join-Path $repoRoot 'common\simion\export_detached_standalone_pa.lua'),'export_detached_standalone_pa.lua'),
    @((Join-Path $PSScriptRoot 'compose_local_operating_pa_lane.ps1'),'compose_local_operating_pa_lane.ps1'),
    @((Join-Path $PSScriptRoot 'build_local_refinement_iob.lua'),'build_local_refinement_iob.lua'),
    @((Join-Path $PSScriptRoot 'inspect_local_refinement_iob.lua'),'inspect_local_refinement_iob.lua')
  )){Copy-Input -Source $copy[0] -Name $copy[1]|Out-Null}
  $pulseMode=[string]$materialization.accelerator_pulse.mode
  $operatingPointProjection=Convert-OperatingPointFieldGateContract `
    -Path (Join-Path $solverDir 'mrtof_local_replacement.operating_point.lua') `
    -PulseMode $pulseMode
  $seedRoot=Join-Path $repoRoot 'common\simion\assets\iob_instance_seeds'
  Copy-Input -Source (Join-Path $seedRoot '8_instance_seed.iob') -Name '8_instance_seed.iob'|Out-Null
  foreach($index in 1..10){$name=('iob_seed_placeholder_{0:D2}.pa0'-f$index);Copy-Input -Source (Join-Path $seedRoot $name) -Name $name|Out-Null}

  $localVoltages=@($materialization.mirror_voltages_v[1..4]) + @($materialization.stripe_biases_v) + @($materialization.prism_voltages_v)
  $localNames=@(1..5|ForEach-Object{"iob_input_local_$_.pa"})
  $legacySemanticLocalNames=@('local_negative_mirror.pa','local_negative_bridge.pa','local_central.pa','local_positive_bridge.pa','local_positive_mirror.pa')
  $legacyLocalNames=@('local_negative_mirror.pa0','local_negative_bridge.pa0','local_central.pa0','local_positive_bridge.pa0','local_positive_mirror.pa0')
  $baseLocalPaths=@()
  $baseFamilyCacheKeys=@()
  if($null-ne$baseLocalWorkbench){
    $declaredBaseLocalPaths=@()
    if($null-ne$baseLocalWorkbenchConfig.inputs.PSObject.Properties['local_operating_pas']){
      $declaredBaseLocalPaths=@($baseLocalWorkbenchConfig.inputs.local_operating_pas)
      if($declaredBaseLocalPaths.Count-ne 5){throw 'Base local workbench declares an invalid local_operating_pas inventory.'}
    }
    for($index=0;$index-lt$localNames.Count;$index++){
      $standaloneCandidate=if($declaredBaseLocalPaths.Count-eq 5){[string]$declaredBaseLocalPaths[$index]}else{Join-Path $baseLocalWorkbench "simion\$($legacySemanticLocalNames[$index])"}
      $legacyCandidate=Join-Path $baseLocalWorkbench "simion\$($legacyLocalNames[$index])"
      if(Test-Path -LiteralPath $standaloneCandidate -PathType Leaf){$baseLocalPaths+=$standaloneCandidate}
      elseif(Test-Path -LiteralPath $legacyCandidate -PathType Leaf){$baseLocalPaths+=$legacyCandidate}
      else{throw "Base local workbench lacks region PA $index in standalone or legacy form."}
      Assert-ManifestOutputIdentity -Manifest $baseLocalWorkbenchManifestRecord -Path $baseLocalPaths[-1] -Label "base local region $index"
    }
    $declaredBaseFamilyPublications=@($baseLocalWorkbenchConfig.inputs.local_family_cache_publications_frozen)
    if($declaredBaseFamilyPublications.Count-ne 5){
      throw 'Base local workbench does not declare exactly five frozen local-family cache publications.'
    }
    for($index=0;$index-lt$declaredBaseFamilyPublications.Count;$index++){
      $publicationPath=[string]$declaredBaseFamilyPublications[$index]
      Assert-ManifestOutputIdentity -Manifest $baseLocalWorkbenchManifestRecord -Path $publicationPath -Label "base local-family publication $index"
      $publication=Get-Content -Raw -LiteralPath $publicationPath|ConvertFrom-Json
      if([string]$publication.cache_key-notmatch'^[0-9A-Fa-f]{64}$'){
        throw "Base local-family publication has an invalid cache key: $publicationPath"
      }
      $baseFamilyCacheKeys+=[string]$publication.cache_key
    }
  }
  $baseLocalVoltages=if($null-eq$baseMaterialization){@(1..8|ForEach-Object{0.0})}else{@($baseMaterialization.mirror_voltages_v[1..4])+@($baseMaterialization.stripe_biases_v)+@($baseMaterialization.prism_voltages_v)}
  $localVoltageDeltas=@(for($index=0;$index-lt 8;$index++){[double]$localVoltages[$index]-[double]$baseLocalVoltages[$index]})
  $changedLocalIndices=@(for($index=0;$index-lt 8;$index++){if([Math]::Abs([double]$localVoltageDeltas[$index])-gt1e-12){$index}})
  $changedFamilyIndices=@(if($null-ne$baseLocalWorkbench){
    for($index=0;$index-lt$families.Count;$index++){
      if(-not[string]::Equals([string]$families[$index].cache_key,[string]$baseFamilyCacheKeys[$index],[StringComparison]::OrdinalIgnoreCase)){$index}
    }
  })
  $localFamilyResponsesRequired=($null-eq$baseLocalWorkbench-or$changedLocalIndices.Count-gt0-or$changedFamilyIndices.Count-gt0)
  $requiredResponseIdsByFamily=@()
  for($familyIndex=0;$familyIndex-lt$families.Count;$familyIndex++){
    $requiresAbsoluteResponses=($null-eq$baseLocalWorkbench-or$changedFamilyIndices-contains$familyIndex)
    $requiredResponseIdsByFamily+=,@(if($requiresAbsoluteResponses){1..8}else{@($changedLocalIndices|ForEach-Object{$_+1})})
  }
  if($localFamilyResponsesRequired){
    for($familyIndex=0;$familyIndex-lt$families.Count;$familyIndex++){
      $requiredResponseIds=@($requiredResponseIdsByFamily[$familyIndex])
      if($requiredResponseIds.Count-gt0){
        Resolve-AnalyzerLocalStandaloneResponseSubset -Family $families[$familyIndex] -ResponseIds $requiredResponseIds -CacheRoot $cacheRoot|Out-Null
      }
    }
  }
  $failureStage='capacity_preflight'
  [int64]$requiredBytes=0
  $requiredBytes=[int64](Get-Item -LiteralPath $sourceAnalyzer).Length+[int64](Get-Item -LiteralPath $sourceAccelerator).Length+[int64](Get-Item -LiteralPath $sourceDetector).Length
  for($index=0;$index-lt$families.Count;$index++){
    if($null-ne$baseLocalWorkbench){
      $sizeSource=$baseLocalPaths[$index]
    }else{
      $recipe=@($families[$index].contract.response_recipes|Where-Object{[int]$_.local_id-eq 1})
      if($recipe.Count-ne 1){throw "Local family $index lacks standalone response 1."}
      $sizeSource=Join-Path $families[$index].generation_directory ([string]$recipe[0].standalone_response_filename)
    }
    $requiredBytes+=[int64](Get-Item -LiteralPath $sizeSource).Length
  }
  $transientMeasure=(@($sourceAnalyzer,$sourceAccelerator)+@($baseLocalPaths)|ForEach-Object{[int64](Get-Item -LiteralPath $_).Length}|Measure-Object -Maximum)
  [int64]$transientBytes=[int64]$transientMeasure.Maximum
  if($localFamilyResponsesRequired){
    [int64]$largestCompositionWorkingSet=0
    for($index=0;$index-lt$families.Count;$index++){
      $requiresAbsoluteResponses=($null-eq$baseLocalWorkbench-or$changedFamilyIndices-contains$index)
      $capacityResponseIndices=if($requiresAbsoluteResponses){@(0..7)}else{@($changedLocalIndices)}
      [int64]$workingSetBytes=if($requiresAbsoluteResponses){0}else{[int64](Get-Item -LiteralPath $baseLocalPaths[$index]).Length}
      foreach($responseIndex in $capacityResponseIndices){
        $responseId=$responseIndex+1
        $recipe=@($families[$index].contract.response_recipes|Where-Object{[int]$_.local_id-eq$responseId})
        if($recipe.Count-ne 1){throw "Local family $index lacks standalone response $responseId."}
        $workingSetBytes+=[int64](Get-Item -LiteralPath (Join-Path $families[$index].generation_directory ([string]$recipe[0].standalone_response_filename))).Length
      }
      $largestCompositionWorkingSet=[math]::Max($largestCompositionWorkingSet,$workingSetBytes)
    }
    $transientBytes=[math]::Max($transientBytes,$largestCompositionWorkingSet)
  }
  # The run-private IOB projection is the one canonical standalone operating
  # set.  Downstream processes never open it directly: they first make a
  # verified disposable short copy, so a second retained multi-GiB set is not
  # needed for immutability.
  $capacityProtectedPaths=@($package.artifact_run_dir,$operatingRun)
  if($localFamilyResponsesRequired){$capacityProtectedPaths+=@($families.generation_directory)}
  if($null-ne$baseLocalWorkbench){$capacityProtectedPaths+=@($baseLocalWorkbench)}
  $startup=Invoke-ArtifactCapacityGate -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot `
    -MinimumFreeGiB ([double]([int64](500GB)+$requiredBytes+$transientBytes)/1GB) `
    -RequiredHeadroomBytes $requiredBytes -ProtectedPaths $capacityProtectedPaths `
    -ProtectedCacheKeys @($families.cache_key)
  $startupPath=Join-Path $resultDir 'artifact_capacity_gate_startup.json';Write-RunJson -Path $startupPath -Depth 14 -Value $startup

  # This workflow only copies/detaches already solved PAs, composes linear
  # standalone responses, and assembles/inspects an IOB.  None of its SIMION
  # Lua paths calls refine or flies ions, so the whole workbench is light.
  $failureStage='materialize_accelerator_operating_pa';$lease=Enter-HostExecutionLease -Role SIMION -Stage prepare -RunId $RunId
  $localAccelerator=Join-Path $solverDir 'iob_input_accelerator.pa'
  if([IO.Path]::GetExtension($sourceAccelerator)-ieq'.pa'){
    Copy-VerifiedRunInput -Source $sourceAccelerator -Destination $localAccelerator -VerificationAttempts 3|Out-Null
  }else{
    $basisLinkDir=Join-Path ([IO.Path]::GetTempPath()) ('simion_pa_links_'+[guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $basisLinkDir|Out-Null
    $privateAccelerator=New-ShortPaCopy -Source $sourceAccelerator -Destination (Join-Path $basisLinkDir 'accelerator.pa0')
    Invoke-SimionStage -Stage 'detach_accelerator_operating_pa' -Arguments @(
      '--nogui','--noprompt','lua',(Join-Path $solverDir 'export_detached_standalone_pa.lua'),
      $privateAccelerator,$localAccelerator)
    Remove-ShortPaCopyDirectory -Path $basisLinkDir
    $basisLinkDir=$null
  }
  $failureStage='materialize_reused_components'
  $localDetector=Copy-VerifiedRunInput -Source $sourceDetector -Destination (Join-Path $solverDir 'iob_input_detector.pa')
  $failureStage='detach_global_operating_analyzer'
  $globalAnalyzer=Join-Path $solverDir 'iob_input_analyzer.pa'
  if([IO.Path]::GetExtension($sourceAnalyzer)-ieq'.pa'){
    Copy-VerifiedRunInput -Source $sourceAnalyzer -Destination $globalAnalyzer -VerificationAttempts 3|Out-Null
  }else{
    $basisLinkDir=Join-Path ([IO.Path]::GetTempPath()) ('simion_pa_links_'+[guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $basisLinkDir|Out-Null
    $privateGlobalBase=New-ShortPaCopy -Source $sourceAnalyzer -Destination (Join-Path $basisLinkDir 'legacy_global.pa0')
    Invoke-SimionStage -Stage 'detach_global_operating_analyzer' -Arguments @(
      '--nogui','--noprompt','lua',(Join-Path $solverDir 'export_detached_standalone_pa.lua'),
      $privateGlobalBase,$globalAnalyzer)
    Remove-ShortPaCopyDirectory -Path $basisLinkDir
    $basisLinkDir=$null
  }
  if($null-ne$baseLocalWorkbenchConfig){
    $basisVoltage=[double]$baseLocalWorkbenchConfig.parameters.basis_voltage_v
  }else{
    $measuredBasisVoltages=@()
    $normalizationContexts=@()
    try {
      foreach($family in $families){
        $raw=Resolve-AnalyzerLocalRawGeometry -Family $family -CacheRoot $cacheRoot
        $privateDirectory=Join-Path ([IO.Path]::GetTempPath()) ('simion_pa_links_'+[guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Path $privateDirectory|Out-Null
        $parallelBasisLinkDirs+=,$privateDirectory
        # A disposable `.pa#` name can be noticed and rewritten by SIMION's
        # family machinery before our hash gate completes.  The PA API opens by
        # content, so use a neutral extension for this read-only raw mask.
        $privateRaw=New-ShortPaCopy -Source $raw.path -Destination (Join-Path $privateDirectory 'raw_geometry.bin')
        $inventoryReceipt=Join-Path $resultDir ("electrode_inventory_{0}.csv"-f$family.label)
        $normalizationContexts+=,[pscustomobject]@{Family=$family;Directory=$privateDirectory;Raw=$privateRaw;InventoryReceipt=$inventoryReceipt}
      }
      $inventoryJobs=@($normalizationContexts|ForEach-Object{[pscustomobject]@{
        Stage=("inventory_geometry_electrodes_{0}"-f$_.Family.label)
        Arguments=@('--nogui','--noprompt','lua',$frozenElectrodeInventory,$_.Raw,$_.InventoryReceipt)
      }})
      Invoke-ParallelSimionStageBatch -Jobs $inventoryJobs -BatchName 'five_local_electrode_inventories'
      $measurementJobs=@()
      foreach($context in $normalizationContexts){
        $presentIds=@(Import-Csv -LiteralPath $context.InventoryReceipt|ForEach-Object{[int]$_.electrode_id}|Where-Object{$_-ge1-and$_-le8})
        if($presentIds.Count-eq0){throw "Local raw PA has no voltage-bearing electrode group: $($context.Family.label)"}
        [int]$activeId=$presentIds[0]
        $recipe=@($context.Family.contract.response_recipes|Where-Object{[int]$_.local_id-eq$activeId})
        if($recipe.Count-ne1){throw "Local family lacks the selected normalization response: $($context.Family.label) id=$activeId"}
        $responseSource=Join-Path $context.Family.generation_directory ([string]$recipe[0].standalone_response_filename)
        $privateResponse=New-ShortPaCopy -Source $responseSource -Destination (Join-Path $context.Directory 'response.bin')
        $receipt=Join-Path $resultDir ("basis_normalization_{0}.csv"-f$context.Family.label)
        $context|Add-Member -NotePropertyName MeasurementReceipt -NotePropertyValue $receipt
        $measurementJobs+=,[pscustomobject]@{
          Stage=("measure_basis_normalization_{0}"-f$context.Family.label)
          Arguments=@('--nogui','--noprompt','lua',$frozenBasisMeasurement,$privateResponse,$context.Raw,([string]$activeId),$receipt)
        }
      }
      Invoke-ParallelSimionStageBatch -Jobs $measurementJobs -BatchName 'five_local_basis_normalizations'
      foreach($context in $normalizationContexts){
        $rows=@(Import-Csv -LiteralPath $context.MeasurementReceipt)
        if($rows.Count-ne1){throw "Basis normalization receipt is not singular: $($context.Family.label)"}
        [double]$measured=[double]$rows[0].basis_voltage_V
        if([double]::IsNaN($measured)-or[double]::IsInfinity($measured)-or$measured-eq0){throw "Measured basis normalization is invalid: $($context.Family.label)"}
        $measuredBasisVoltages+=$measured
        $basisMeasurementReceipts+=$context.MeasurementReceipt
        $basisInventoryReceipts+=$context.InventoryReceipt
      }
    } finally {
      foreach($privateDirectory in @($normalizationContexts.Directory)){Remove-ShortPaCopyDirectory -Path $privateDirectory}
      $parallelBasisLinkDirs=@()
    }
    $declaredBasisVoltages=@($measuredBasisVoltages|Select-Object -Unique)
    if($declaredBasisVoltages.Count-ne1){throw 'Measured local-family basis normalization differs across regions.'}
    $basisVoltage=[double]$declaredBasisVoltages[0]
  }
  if([double]::IsNaN($basisVoltage)-or[double]::IsInfinity($basisVoltage)-or$basisVoltage-eq 0){throw 'Local response basis voltage must be finite and nonzero.'}
  $failureStage='combine_local_operating_replacements_without_refine'
  $compositionJobs=@()
  $laneScript=Join-Path $solverDir 'compose_local_operating_pa_lane.ps1'
  $pwshExe=(Get-Process -Id $PID).Path
  for($index=0;$index-lt$families.Count;$index++){
    $operatingLocal=Join-Path $solverDir $localNames[$index]
    $familyIdentityChanged=($changedFamilyIndices-contains$index)
    if($null-ne$baseLocalWorkbench-and$changedLocalIndices.Count-eq0-and-not$familyIdentityChanged){
      $basePaSource=$baseLocalPaths[$index]
      if([IO.Path]::GetExtension($basePaSource)-ieq'.pa'){
        Copy-VerifiedRunInput -Source $basePaSource -Destination $operatingLocal -VerificationAttempts 3|Out-Null
      }else{
        $privateDirectory=Join-Path ([IO.Path]::GetTempPath()) ('simion_pa_links_'+[guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Path $privateDirectory|Out-Null
        $basisLinkDir=$privateDirectory
        $privateLegacyBase=New-ShortPaCopy -Source $basePaSource -Destination (Join-Path $privateDirectory 'legacy.pa0')
        Invoke-SimionStage -Stage ("detach_local_{0}"-f$families[$index].label) -Arguments @(
          '--nogui','--noprompt','lua',(Join-Path $solverDir 'export_detached_standalone_pa.lua'),
          $privateLegacyBase,$operatingLocal)
        Remove-ShortPaCopyDirectory -Path $privateDirectory
        $basisLinkDir=$null
      }
    }else{
      $requiresAbsoluteResponses=($null-eq$baseLocalWorkbench-or$familyIdentityChanged)
      $responseIndices=if($requiresAbsoluteResponses){@(0..7)}else{@($changedLocalIndices)}
      $responseSpecifications=@()
      foreach($responseIndex in $responseIndices){
        $responseId=$responseIndex+1
        $recipe=@($families[$index].contract.response_recipes|Where-Object{[int]$_.local_id-eq$responseId})
        if($recipe.Count-ne1){throw "Standalone response recipe did not resolve uniquely: $($families[$index].label) id=$responseId"}
        $responseSource=Join-Path $families[$index].generation_directory ([string]$recipe[0].standalone_response_filename)
        $voltageIndex=[int]$responseIndex
        $numerator=if($requiresAbsoluteResponses){[double]$localVoltages[$voltageIndex]}else{[double]$localVoltageDeltas[$voltageIndex]}
        $coefficient=$numerator/$basisVoltage
        if($requiresAbsoluteResponses-and$voltageIndex-eq 0){$coefficient-=1.0}
        $responseSpecifications+=,[ordered]@{source=$responseSource;coefficient=(Format-InvariantNumber $coefficient)}
      }
      $baseMode=if($requiresAbsoluteResponses){'first_response'}elseif([IO.Path]::GetExtension($baseLocalPaths[$index])-ieq'.pa'){'standalone'}else{'legacy_family'}
      $planPath=Join-Path $resultDir ("composition_lane_{0}.json"-f$families[$index].label)
      $compositionPlanPaths+=,$planPath
      Write-RunJson -Path $planPath -Depth 12 -Value ([ordered]@{
        schema_version=1;label=[string]$families[$index].label;simion_exe=$simion;solver_dir=$solverDir;
        short_pa_support=Join-Path $repoRoot 'common\simion\short_pa_path_support.ps1';
        compose_lua=Join-Path $solverDir 'compose_standalone_pa.lua';export_lua=Join-Path $solverDir 'export_detached_standalone_pa.lua';
        output_pa=$operatingLocal;base_mode=$baseMode;base_source=if($requiresAbsoluteResponses){$null}else{$baseLocalPaths[$index]};
        responses=$responseSpecifications
      })
      $compositionJobs+=,[pscustomobject]@{
        Stage=("compose_local_operating_{0}"-f$families[$index].label)
        FileName=$pwshExe
        WorkingDirectory=$solverDir
        Arguments=@('-NoLogo','-NoProfile','-NonInteractive','-File',$laneScript,'-PlanPath',$planPath)
      }
    }
  }
  Invoke-ParallelSimionStageBatch -Jobs $compositionJobs -BatchName 'five_complete_local_operating_pa_lanes'
  if($localFamilyResponsesRequired){
    for($familyIndex=0;$familyIndex-lt$families.Count;$familyIndex++){
      $requiredResponseIds=@($requiredResponseIdsByFamily[$familyIndex])
      if($requiredResponseIds.Count-gt0){
        Resolve-AnalyzerLocalStandaloneResponseSubset -Family $families[$familyIndex] -ResponseIds $requiredResponseIds -CacheRoot $cacheRoot|Out-Null
      }
    }
  }
  $posePath=Join-Path $resultDir 'resolved_iob_pose.json'
  $poseCode="import json,sys; from pathlib import Path; from projects.parallel_mirror_dual_stripe_mr_tof.analysis.split_candidate_geometry import resolve_split_iob_origins; p=Path(sys.argv[1]); c=json.loads(p.read_text(encoding='utf-8')); Path(sys.argv[2]).write_text(json.dumps({'origins_mm':resolve_split_iob_origins(p),'mesh_mm_per_gu':c['simion']['component_mesh_mm_per_gu']},indent=2)+chr(10),encoding='utf-8')"
  Push-Location $repoRoot;try{$saved=$env:PYTHONPATH;$env:PYTHONPATH=$repoRoot;& $python -c $poseCode $frozenBaseline $posePath;if($LASTEXITCODE-ne 0){throw 'Pose derivation failed.'}}finally{$env:PYTHONPATH=$saved;Pop-Location}
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
  # The 8-instance seed is an internal binary template only.  Publish the
  # completed assembly under a physical, user-facing name so it cannot be
  # mistaken for a placeholder IOB whose PA inputs are disposable.
  $iob=Join-Path $solverDir 'mrtof_complete_3d_candidate_gui_review.iob'
  $paths=@($globalAnalyzer)+@($localNames|ForEach-Object{Join-Path $solverDir $_})+@($localAccelerator,$localDetector)
  $iobPaths=@($paths)
  $originArguments=@();foreach($origin in $origins){foreach($value in $origin){$originArguments+=[string]::Format([Globalization.CultureInfo]::InvariantCulture,'{0:R}',[double]$value)}}
  $failureStage='build_local_replacement_iob'
  Invoke-SimionStage -Stage 'build_local_replacement_iob' -Arguments (@('--nogui','--noprompt','lua',(Join-Path $solverDir 'build_local_refinement_iob.lua'),'--',(Join-Path $solverDir '8_instance_seed.iob'))+$iobPaths+@($iob,(Join-Path $solverDir 'mrtof_local_replacement.lua'),(Join-Path $solverDir 'mrtof_local_replacement_source.fly2'),$localConfig)+$originArguments)
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
  $artifactIob=Join-Path $package.artifact_run_dir 'simion\mrtof_complete_3d_candidate_gui_review.iob'
  $failureStage='inspect_relocated_local_replacement_iob'
  Invoke-SimionStage -Stage 'inspect_relocated_local_replacement_iob' -Arguments (@('--nogui','--noprompt','lua',(Join-Path $solverDir 'inspect_local_refinement_iob.lua'),'--',$artifactIob,$relocatedReport)+$meshArguments)
  # The ten PA companions exist only so SIMION can load the canonical seed.
  # Both the original and relocated saved IOB now point at the eight verified
  # operating PAs, so retaining the companions would preserve redundant heavy
  # files without adding reproducibility evidence.
  $seedPlaceholderCleanup=Remove-IobSeedPlaceholderCompanions -Directory $solverDir -Count 10

  $configuration=Get-Content -Raw -LiteralPath $runConfig|ConvertFrom-Json -AsHashtable
  $localOperatingPaMethod=if($null-eq$baseLocalWorkbench){
    'complete absolute standalone response composition; no Refine'
  }elseif($changedFamilyIndices.Count-gt0){
    'family-identity-aware absolute replacement plus verified prior-workbench reuse; no Refine'
  }elseif($changedLocalIndices.Count-eq 0){
    'verified prior-workbench standalone detachment or copy; no Refine'
  }else{
    'verified prior-workbench standalone delta-response composition; no Refine'
  }
  # Run config is part of the permanent evidence chain.  Never publish the
  # short execution alias: it is deliberately removed after terminalization.
  $artifactReviewed=Join-Path $package.artifact_run_dir 'inputs\simion_prototype_contract.json'
  $artifactMaterialization=Join-Path $package.artifact_run_dir 'inputs\two_prism_trial_materialization.json'
  $artifactInputDir=Join-Path $package.artifact_run_dir 'inputs'
  $artifactSimionDir=Join-Path $package.artifact_run_dir 'simion'
  $artifactOperatingPaths=@((@('iob_input_analyzer.pa')+@($localNames)+@('iob_input_accelerator.pa','iob_input_detector.pa'))|ForEach-Object{Join-Path $artifactSimionDir $_})
  $configuration.inputs=[ordered]@{operating_run_manifest=$operatingManifest;baseline_contract=Join-Path $artifactInputDir 'simion_candidate_two_zone.json';family_build_baseline_contract=Join-Path $artifactInputDir 'family_build_baseline_contract.json';family_build_baseline_contracts=@($families|ForEach-Object{Join-Path $artifactInputDir "$($_.label)_family_build_baseline_contract.json"});reviewed_geometry_contract=$artifactReviewed;operating_point_materialization=$artifactMaterialization;base_local_workbench_manifest=if($null-eq$frozenBaseLocalManifest){$null}else{Join-Path $artifactInputDir 'base_local_workbench_manifest.json'};base_local_workbench_materialization=if($null-eq$frozenBaseMaterialization){$null}else{Join-Path $artifactInputDir 'base_local_workbench_materialization.json'};local_refinement_plan=Join-Path $artifactInputDir 'analyzer_local_refinement_plan.json';current_local_refinement_plan=Join-Path $package.artifact_run_dir 'results\current_analyzer_local_refinement_plan.json';electrode_inventory_implementation=Join-Path $artifactInputDir 'inspect_pa_electrode_ids.lua';electrode_inventory_receipts=@($basisInventoryReceipts|ForEach-Object{Join-Path $package.artifact_run_dir ('results\'+(Split-Path $_ -Leaf))});basis_normalization_measurement_implementation=Join-Path $artifactInputDir 'measure_pa_basis_voltage.lua';basis_normalization_receipts=@($basisMeasurementReceipts|ForEach-Object{Join-Path $package.artifact_run_dir ('results\'+(Split-Path $_ -Leaf))});local_operating_lane_implementation=Join-Path $artifactSimionDir 'compose_local_operating_pa_lane.ps1';local_operating_lane_plans=@($compositionPlanPaths|ForEach-Object{Join-Path $package.artifact_run_dir ('results\'+(Split-Path $_ -Leaf))});local_family_manifests=@($families.manifest);local_family_contracts_frozen=@($families|ForEach-Object{Join-Path $artifactInputDir "$($_.label)_family_contract.json"});local_family_cache_identities_frozen=@($families|ForEach-Object{Join-Path $artifactInputDir "$($_.label)_cache_identity.json"});local_family_cache_publications_frozen=@($families|ForEach-Object{Join-Path $artifactInputDir "$($_.label)_cache_publication.json"});global_analyzer_pa=Join-Path $artifactSimionDir 'iob_input_analyzer.pa';local_operating_pas=@($localNames|ForEach-Object{Join-Path $artifactSimionDir $_});accelerator_pa=Join-Path $artifactSimionDir 'iob_input_accelerator.pa';detector_pa=Join-Path $artifactSimionDir 'iob_input_detector.pa';iob_input_pas=@($artifactOperatingPaths);operating_iob=Join-Path $artifactSimionDir 'mrtof_complete_3d_candidate_gui_review.iob'}
  $configuration.parameters=[ordered]@{global_analyzer_mesh_mm_per_gu=@($pose.mesh_mm_per_gu.analyzer);local_mesh_mm_per_gu=@($ScaleFactor,$ScaleFactor,$ScaleFactor);rebuild_from_family_zero_base=[bool]$RebuildFromFamilyZeroBase;local_operating_pa_method=$localOperatingPaMethod;local_region_execution='parallel_batches_within_one_prepare_lease';local_region_batch_width=$families.Count;family_baseline_equivalence=$familyBaselineEquivalence;basis_voltage_source=if($null-ne$baseLocalWorkbenchConfig){'verified_base_local_workbench_receipt'}else{'five_current_immutable_family_measurements'};operating_point_field_gate_projection=$operatingPointProjection;iob_seed_placeholder_cleanup=$seedPlaceholderCleanup;changed_local_voltage_indices=@($changedLocalIndices);changed_local_family_indices=@($changedFamilyIndices);changed_local_family_labels=@($changedFamilyIndices|ForEach-Object{[string]$families[$_].label});local_voltage_deltas_v=@($localVoltageDeltas);basis_voltage_v=$basisVoltage;handoff_z_mm=@($handoff.negative_bridge_to_mirror,$handoff.negative_central_to_bridge,$handoff.positive_central_to_bridge,$handoff.positive_bridge_to_mirror);instance_priority='higher_instance_wins; local instance_adjust suppression falls back toward global instance 1'}
  Write-RunJson -Path $runConfig -Depth 20 -Value $configuration
  Write-RunJson -Path $summary -Depth 20 -Value ([ordered]@{schema_version=1;role='mrtof_analyzer_local_replacement_workbench';status='success';qualification='gui_reviewable_local_replacement_assembly__flight_pending';instance_count=8;global_analyzer_mesh_mm_per_gu=@($pose.mesh_mm_per_gu.analyzer);local_mesh_mm_per_gu=@($ScaleFactor,$ScaleFactor,$ScaleFactor);local_operating_pa_method=$localOperatingPaMethod;family_baseline_equivalence=$familyBaselineEquivalence;operating_point_field_gate_projection=$operatingPointProjection;iob_seed_placeholder_cleanup=$seedPlaceholderCleanup;changed_local_voltage_indices=@($changedLocalIndices);changed_local_family_indices=@($changedFamilyIndices);changed_local_family_labels=@($changedFamilyIndices|ForEach-Object{[string]$families[$_].label});basis_voltage_v=$basisVoltage;iob_path=Join-Path $package.artifact_run_dir 'simion\mrtof_complete_3d_candidate_gui_review.iob';reason='The global analyser remains the fallback at its resolved isotropic mesh. Five higher-priority detached standalone local PAs replace only their contract-owned z responsibility intervals.'})
  $retention=Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $runConfig
  $failureStage='capacity_terminal';[int64]$maximum=[int64](Get-ChildItem -LiteralPath $package.artifact_run_dir -Recurse -File|Measure-Object Length -Sum).Sum
  $terminal=Invoke-ArtifactCapacityGate -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot `
    -ProtectedPaths $capacityProtectedPaths -ProtectedCacheKeys @($families.cache_key) `
    -KnownMeasuredBytes ([int64]$startup.measured_after_bytes) -MaximumNewArtifactBytes $maximum
  $terminalPath=Join-Path $resultDir 'artifact_capacity_gate_terminal.json';Write-RunJson -Path $terminalPath -Depth 14 -Value $terminal
  $frozenEvidenceOutputs=@($frozenBaseline,$frozenFamilyBaseline,$frozenPlan,$currentPlan,$currentCanonicalAnalyzer,$frozenReviewed,$frozenMaterialization)+@($families.frozen_contract)+@($families.frozen_identity)+@($families.frozen_publication)
  if($null-ne$frozenBaseLocalManifest){$frozenEvidenceOutputs+=@($frozenBaseLocalManifest,$frozenBaseMaterialization)}
  $publishedIobBase=Join-Path $solverDir 'mrtof_complete_3d_candidate_gui_review'
  $publishedIobCompanions=@(
    "$publishedIobBase.lua",
    "$publishedIobBase.mirror_cycle_counter.lua",
    "$publishedIobBase.operating_point.lua",
    "$publishedIobBase.voltage_map.lua",
    "$publishedIobBase.local_refinement.lua",
    "$publishedIobBase.fly2"
  )
  Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Status success -Software @('SIMION 2020','Python 3.11') -Outputs (@($summary,$report,$relocatedReport,$posePath,$startupPath,$terminalPath,$retention,$iob,$frozenBasisMeasurement,$frozenElectrodeInventory)+$basisInventoryReceipts+$basisMeasurementReceipts+$compositionPlanPaths+$frozenEvidenceOutputs+$paths+@((Join-Path $solverDir 'compose_local_operating_pa_lane.ps1'))+$publishedIobCompanions)
  $terminalized=$true;$hostOutcome='success';Write-Host "MRTOF_LOCAL_REPLACEMENT_WORKBENCH=PASS RUN_ID=$RunId IOB=$iob"
} catch {
  if(-not$terminalized){Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Summary $summary -SummaryRole 'mrtof_analyzer_local_replacement_workbench' -Reason $_.Exception.Message -Software @('SIMION 2020','Python 3.11') -Status failed -FailureStage $failureStage;$terminalized=$true}
  throw
} finally {
  if($null-ne$basisLinkDir){Remove-ShortPaCopyDirectory -Path $basisLinkDir}
  foreach($privateDirectory in @($parallelBasisLinkDirs)){Remove-ShortPaCopyDirectory -Path $privateDirectory}
  if($null-ne$lease){Exit-HostExecutionLease -Lease $lease -Outcome $hostOutcome -RunId $RunId}
  Remove-RunPackageExecutionAlias -Package $package
}

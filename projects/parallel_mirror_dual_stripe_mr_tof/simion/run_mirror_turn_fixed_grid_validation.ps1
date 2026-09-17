[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$ExactKRunPath,
  [Parameter(Mandatory)][string]$HalfMillimeterWorkbenchRunPath,
  [Parameter(Mandatory)][string]$HalfMillimeterPrewarmRunPath,
  [Parameter(Mandatory)][string]$GeometryReviewRunPath,
  [Parameter(Mandatory)][string]$PreparedAnalyzerSourceRunPath,
  [string]$RealFieldL1RunPath='',
  [string]$AxisResponseRunPath='',
  [string]$FixedGridVoltageCorrectionRunPath='',
  [switch]$NativeTransverseL1,
  [double]$ProbeYmm=280.0,
  [ValidateSet(0.25)][double]$MirrorTurnMeshMm=0.25,
  [string]$RunId='',
  [string]$SimionExe='',
  [string]$PythonExe=''
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$projectId='parallel_mirror_dual_stripe_mr_tof'
$repoRoot=(Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$workspaceRoot=Split-Path -Parent $repoRoot
$python=if($PythonExe){[IO.Path]::GetFullPath($PythonExe)}else{Join-Path $repoRoot '.venv\Scripts\python.exe'}
$simion=if($SimionExe){[IO.Path]::GetFullPath($SimionExe)}else{Join-Path $env:ProgramFiles 'SIMION-2020\simion.exe'}
if([string]::IsNullOrWhiteSpace($RunId)){$RunId=(Get-Date -Format 'yyyyMMdd_HHmmss')+'__sim__simion__mrtof-mirror-turn-fixed-0p25mm'}
. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')
. (Join-Path $repoRoot 'common\host_execution_lease.ps1')
. (Join-Path $repoRoot 'common\simion\short_pa_path_support.ps1')
. (Join-Path $repoRoot 'common\multipole\resource_budget_support.ps1')
$artifactRoot=Join-Path $workspaceRoot 'artifacts'
$package=New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot (Join-Path $artifactRoot "projects\$projectId") `
  -RunId $RunId -Project $projectId -Mode 'mirror_turn_fixed_operating_grid_validation' `
  -Software @('SIMION 2020','Python 3.11') -RetentionContractEnabled -RetentionClass compact `
  -AdditionalDirectories @('simion') -UseShortExecutionPath
$runDir=$package.run_dir;$inputDir=$package.input_dir;$resultDir=$package.result_dir;$logDir=$package.log_dir
$solverDir=Join-Path $runDir 'simion';$runConfig=$package.run_config;$summary=$package.summary
$terminalized=$false;$lease=$null;$failureStage='preflight';$hostOutcome='failed';$shortCopies=@()
$fixedFormalRecord=$null;$fixedResourceProfile=$null
function Invoke-ProjectPython([string[]]$Arguments){Push-Location $repoRoot;$saved=$env:PYTHONPATH;try{$env:PYTHONPATH=$repoRoot;& $python @Arguments;if($LASTEXITCODE-ne0){throw "Python failed: $($Arguments-join' ')"}}finally{$env:PYTHONPATH=$saved;Pop-Location}}
function Invoke-Simion([string]$Stage,[string[]]$Arguments){$out=& $simion @Arguments 2>&1;$text=$out|Out-String;[IO.File]::WriteAllText((Join-Path $logDir "$Stage.log"),$text,[Text.UTF8Encoding]::new($false));if($text){Write-Host $text.TrimEnd()};if($LASTEXITCODE-ne0){throw "SIMION stage failed: $Stage"}}
function Number([double]$Value){[string]::Format([Globalization.CultureInfo]::InvariantCulture,'{0:R}',$Value)}
function ArtifactPath([string]$Path){$full=[IO.Path]::GetFullPath($Path);$exec=[IO.Path]::GetFullPath([string]$package.run_dir).TrimEnd([char[]]@(92,47));$artifact=[IO.Path]::GetFullPath([string]$package.artifact_run_dir).TrimEnd([char[]]@(92,47));if($full.StartsWith($exec,[StringComparison]::OrdinalIgnoreCase)){return $artifact+$full.Substring($exec.Length)};$full}
function Assert-FrozenOutputRecord([object]$Manifest,[string]$Path,[string]$Label){
  $full=[IO.Path]::GetFullPath($Path)
  $matches=@($Manifest.outputs|Where-Object{[IO.Path]::GetFullPath([string]$_.path)-eq$full})
  if($matches.Count-ne1){throw "Prewarm manifest must record exactly one $Label output: $full"}
  $record=$matches[0]
  if([int64]$record.bytes-lt0-or[string]$record.sha256-notmatch'^[0-9A-Fa-f]{64}$'){
    throw "Prewarm manifest has an invalid $Label content record: $full"
  }
  if(-not[bool]$record.exists-or-not(Test-Path -LiteralPath $full -PathType Leaf)){throw "Frozen $Label output is unavailable: $full"}
  $item=Get-Item -LiteralPath $full
  if([int64]$item.Length-ne[int64]$record.bytes){throw "Frozen $Label byte count changed: $full"}
  $actual=(Get-FileHash -LiteralPath $full -Algorithm SHA256).Hash
  if($actual-ne[string]$record.sha256){throw "Frozen $Label SHA-256 changed: $full"}
  return $record
}
function Assert-FileMatchesRecord([string]$Path,[object]$Record,[string]$Label){
  if(-not(Test-Path -LiteralPath $Path -PathType Leaf)){throw "Frozen $Label copy is unavailable: $Path"}
  $item=Get-Item -LiteralPath $Path
  if([int64]$item.Length-ne[int64]$Record.bytes){throw "Frozen $Label copy byte count changed: $Path"}
  if((Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash-ne[string]$Record.sha256){throw "Frozen $Label copy SHA-256 changed: $Path"}
}
try{
  $exactK=(Resolve-Path $ExactKRunPath).Path;$workbench=(Resolve-Path $HalfMillimeterWorkbenchRunPath).Path
  $prewarm=(Resolve-Path $HalfMillimeterPrewarmRunPath).Path;$geometry=(Resolve-Path $GeometryReviewRunPath).Path
  $preparedSource=(Resolve-Path $PreparedAnalyzerSourceRunPath).Path
  $useRealField=-not[string]::IsNullOrWhiteSpace($RealFieldL1RunPath)
  if($useRealField-ne(-not[string]::IsNullOrWhiteSpace($AxisResponseRunPath))){throw 'RealFieldL1RunPath and AxisResponseRunPath must be supplied together.'}
  $useVoltagePoint=-not[string]::IsNullOrWhiteSpace($FixedGridVoltageCorrectionRunPath)
  if($useVoltagePoint-and-not$useRealField){throw 'FixedGridVoltageCorrectionRunPath requires the real-field L1 and axis-response inputs.'}
  $realFieldL1=if($useRealField){(Resolve-Path $RealFieldL1RunPath).Path}else{$null}
  $axisResponse=if($useRealField){(Resolve-Path $AxisResponseRunPath).Path}else{$null}
  $voltageCorrection=if($useVoltagePoint){(Resolve-Path $FixedGridVoltageCorrectionRunPath).Path}else{$null}
  $inputRoots=@($exactK,$workbench,$geometry,$preparedSource)+$(if($useRealField){@($realFieldL1,$axisResponse)}else{@()})+$(if($useVoltagePoint){@($voltageCorrection)}else{@()})
  $fullyVerifiedRoots=@($exactK,$workbench,$preparedSource)+$(if($useRealField){@($realFieldL1,$axisResponse)}else{@()})+$(if($useVoltagePoint){@($voltageCorrection)}else{@()})
  $capacityProtectedRoots=@($exactK,$workbench)+$(if($useRealField){@($realFieldL1,$axisResponse)}else{@()})+$(if($useVoltagePoint){@($voltageCorrection)}else{@()})
  foreach($root in $fullyVerifiedRoots){& $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') (Join-Path $root 'run_manifest.json') --require-status success;if($LASTEXITCODE-ne0){throw "Input manifest failed: $root"}}
  # The reviewed GUI run contains mutable native PA-family members that are no
  # longer consumed here.  Bind only its canonical analyzer GEM; the detached
  # reviewed-source receipt below owns the PA response identity.  This prevents
  # an irrelevant GUI write-back to PA0 from invalidating a fixed-grid solve.
  $geometryManifestSource=Join-Path $geometry 'run_manifest.json'
  $geometryManifestSnapshot=Copy-VerifiedRunInput -Source $geometryManifestSource -Destination (Join-Path $inputDir 'geometry_review_run_manifest.json')
  $geometryManifest=Get-Content -LiteralPath $geometryManifestSnapshot -Raw|ConvertFrom-Json -AsHashtable -Depth 40
  if([string]$geometryManifest.status-ne'success'-or[string]$geometryManifest.project-ne$projectId-or[string]$geometryManifest.mode-ne'three_component_candidate_iob_assembly'){
    throw 'Geometry review manifest identity differs.'
  }
  $reviewedGemRecord=Get-VerifiedRunManifestInputRecord -Records $geometryManifest.inputs -Name 'analyzer_gem' -Label 'reviewed analyzer GEM'
  $reviewedGemSource=[string]$reviewedGemRecord.path
  Assert-VerifiedRunRecordHash -Path $reviewedGemSource -Record $reviewedGemRecord -Label 'reviewed analyzer GEM'
  $reviewedGem=Copy-VerifiedRunInput -Source $reviewedGemSource -Destination (Join-Path $inputDir 'reviewed_mrtof_analyzer.gem')

  $preparedSourceManifestPath=Copy-VerifiedRunInput -Source (Join-Path $preparedSource 'run_manifest.json') -Destination (Join-Path $inputDir 'prepared_analyzer_source_run_manifest.json')
  $preparedSourceManifest=Get-Content -LiteralPath $preparedSourceManifestPath -Raw|ConvertFrom-Json -Depth 40
  if([string]$preparedSourceManifest.status-ne'success'-or[string]$preparedSourceManifest.project-ne$projectId-or[string]$preparedSourceManifest.mode-ne'reviewed_analyzer_source_prepare'){
    throw 'Prepared analyzer-source manifest identity differs.'
  }
  $preparedReceiptSource=Join-Path $preparedSource 'results\reviewed_analyzer_source_cache_receipt.json'
  $preparedReceiptRecord=Assert-FrozenOutputRecord -Manifest $preparedSourceManifest -Path $preparedReceiptSource -Label 'prepared analyzer-source receipt'
  $preparedReceipt=Copy-VerifiedRunInput -Source $preparedReceiptSource -Destination (Join-Path $inputDir 'prepared_analyzer_source_receipt.json')
  Assert-FileMatchesRecord -Path $preparedReceipt -Record $preparedReceiptRecord -Label 'prepared analyzer-source receipt'
  $prewarmManifestSource=Join-Path $prewarm 'run_manifest.json'
  $prewarmManifestPath=Copy-VerifiedRunInput -Source $prewarmManifestSource -Destination (Join-Path $inputDir 'half_mm_prewarm_run_manifest.json')
  $prewarmManifest=Get-Content -LiteralPath $prewarmManifestPath -Raw|ConvertFrom-Json -Depth 40
  if([string]$prewarmManifest.status-ne'success'-or[string]$prewarmManifest.project-ne$projectId-or[string]$prewarmManifest.mode-ne'local_operating_pa_cache_prewarm'){
    throw 'Half-millimeter prewarm manifest is not a successful local operating-PA prewarm.'
  }
  $operatingCacheIdentitySource=Join-Path $prewarm 'results\local_operating_pa_cache_identity.json'
  $identityRecord=Assert-FrozenOutputRecord -Manifest $prewarmManifest -Path $operatingCacheIdentitySource -Label 'operating-PA identity'
  $operatingCacheIdentity=Copy-VerifiedRunInput -Source $operatingCacheIdentitySource -Destination (Join-Path $inputDir 'half_mm_operating_pa_cache_identity.json')
  Assert-FileMatchesRecord -Path $operatingCacheIdentity -Record $identityRecord -Label 'operating-PA identity'
  $operatingCacheRoot=Join-Path $artifactRoot 'common\simion\pa_family_cache'
  $prewarmFinalProbeSource=Join-Path $prewarm 'results\local_operating_pa_cache_final_probe.json'
  $finalProbeRecord=Assert-FrozenOutputRecord -Manifest $prewarmManifest -Path $prewarmFinalProbeSource -Label 'operating-PA final probe'
  $prewarmFinalProbePath=Copy-VerifiedRunInput -Source $prewarmFinalProbeSource -Destination (Join-Path $inputDir 'half_mm_operating_pa_cache_final_probe.json')
  Assert-FileMatchesRecord -Path $prewarmFinalProbePath -Record $finalProbeRecord -Label 'operating-PA final probe'
  $prewarmFinalProbe=Get-Content -LiteralPath $prewarmFinalProbePath -Raw|ConvertFrom-Json -Depth 20
  if([string]$prewarmFinalProbe.disposition-ne'hit'){throw 'Half-millimeter prewarm final operating-PA receipt is not an exact hit.'}
  $recordedCacheKey=[string]$prewarmFinalProbe.cache_key
  if($recordedCacheKey-notmatch'^[0-9A-Fa-f]{64}$'){throw 'Half-millimeter prewarm final receipt has no canonical cache key.'}
  $prewarmGenerationDirectory=[string]$prewarmFinalProbe.generation_directory
  if([string]::IsNullOrWhiteSpace($prewarmGenerationDirectory)){throw 'Half-millimeter prewarm final receipt records no operating-PA generation.'}
  $pinnedGenerationSha256=Split-Path -Leaf ([IO.Path]::GetFullPath($prewarmGenerationDirectory))
  if($pinnedGenerationSha256-notmatch'^[0-9A-Fa-f]{64}$'){
    throw 'Half-millimeter prewarm final receipt has no canonical frozen operating-PA generation identity.'
  }
  $expectedRecordedGeneration=[IO.Path]::GetFullPath((Join-Path (Join-Path (Join-Path $operatingCacheRoot $recordedCacheKey) 'generations') $pinnedGenerationSha256))
  if(-not([IO.Path]::GetFullPath($prewarmGenerationDirectory).Equals($expectedRecordedGeneration,[StringComparison]::OrdinalIgnoreCase))){
    throw 'Half-millimeter prewarm final receipt generation path does not match its cache key and generation identity.'
  }
  $operatingCacheProbe=(@(Invoke-ProjectPython -Arguments @(
    '-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.local_operating_pa_cache',
    '--action','probe','--identity-input',$operatingCacheIdentity,'--cache-root',$operatingCacheRoot,
    '--expected-generation-sha256',$pinnedGenerationSha256
  ))-join"`n")|ConvertFrom-Json -Depth 20
  if([string]$operatingCacheProbe.disposition-ne'hit'){throw "Frozen half-millimeter operating PA generation is unavailable: $($operatingCacheProbe.detail)"}
  if([string]$operatingCacheProbe.cache_key-notmatch'^[0-9A-Fa-f]{64}$'){throw 'Half-millimeter operating PA cache probe did not return a canonical cache key.'}
  if([string]$operatingCacheProbe.cache_key-ne$recordedCacheKey){throw 'Frozen operating-PA identity and final receipt have different cache keys.'}
  if([string]$operatingCacheProbe.generation_sha256-ne$pinnedGenerationSha256){throw 'Pinned half-millimeter operating PA generation did not round-trip exactly.'}
  $operatingCacheKey=[string]$operatingCacheProbe.cache_key
  $prewarmProjection=Join-Path $resultDir 'prewarm_operating_pa_generation_projection.json'
  Write-RunJson -Path $prewarmProjection -Depth 20 -Value ([ordered]@{
    schema_version=1;role='mrtof_prewarm_operating_pa_generation_projection';status='verified'
    source_run_id=[string]$prewarmManifest.run_id
    source_manifest_sha256=(Get-FileHash -LiteralPath $prewarmManifestPath -Algorithm SHA256).Hash
    identity_output=[ordered]@{bytes=[int64]$identityRecord.bytes;sha256=[string]$identityRecord.sha256}
    final_probe_output=[ordered]@{bytes=[int64]$finalProbeRecord.bytes;sha256=[string]$finalProbeRecord.sha256}
    cache_key=$operatingCacheKey;generation_sha256=$pinnedGenerationSha256
    verification_scope='source_manifest_selected_outputs_plus_current_complete_generation_probe'
  })
  $failureStage='capacity_preflight'
  [int64]$headroom=16GB
  $startup=Invoke-ArtifactCapacityGate -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot -RequiredHeadroomBytes $headroom -ProtectedPaths (@($package.artifact_run_dir)+$capacityProtectedRoots) -ProtectedCacheKeys @($operatingCacheKey)
  $startupPath=Join-Path $resultDir 'artifact_capacity_gate_startup.json';Write-RunJson -Path $startupPath -Depth 14 -Value $startup
  $contract=Copy-VerifiedRunInput -Source (Join-Path $repoRoot "projects\$projectId\config\simion_candidate_two_zone.json") -Destination (Join-Path $inputDir 'simion_candidate_two_zone.json')
  $canonical=Join-Path $solverDir 'canonical_mrtof_analyzer.gem'
  Invoke-ProjectPython -Arguments @('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.split_candidate_geometry','--contract',$contract,'--component','analyzer','--output',$canonical)
  if(-not(Test-RunFilesIdentical -Left $canonical -Right $reviewedGem)){throw 'Current baseline differs from reviewed analyzer geometry.'}
  $failureStage='materialize_half_millimeter_parent'
  $halfDir=Join-Path $solverDir 'half_mm';New-Item -ItemType Directory -Path $halfDir -Force|Out-Null
  $operatingMaterialization=(@(Invoke-ProjectPython -Arguments @('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.local_operating_pa_cache','--action','materialize',
    '--identity-input',$operatingCacheIdentity,'--cache-root',$operatingCacheRoot,'--expected-generation-sha256',$pinnedGenerationSha256,'--destination-directory',$halfDir
  ))-join"`n")|ConvertFrom-Json -Depth 30
  if([string]$operatingMaterialization.generation_sha256-ne$pinnedGenerationSha256){throw 'Materialized half-millimeter parents do not match their frozen generation.'}
  $parentGenerationContract=Join-Path $resultDir 'parent_operating_pa_generation.json'
  Write-RunJson -Path $parentGenerationContract -Depth 30 -Value ([ordered]@{
    schema_version=1;role='mrtof_fixed_grid_parent_operating_pa_generation';status='bound'
    prewarm_run_manifest_sha256=(Get-FileHash -LiteralPath $prewarmManifestPath -Algorithm SHA256).Hash
    prewarm_final_probe_sha256=(Get-FileHash -LiteralPath $prewarmFinalProbePath -Algorithm SHA256).Hash
    workbench_run_manifest_sha256=(Get-FileHash -LiteralPath (Join-Path $workbench 'run_manifest.json') -Algorithm SHA256).Hash
    operating_pa_identity_sha256=(Get-FileHash -LiteralPath $operatingCacheIdentity -Algorithm SHA256).Hash
    cache_key=$operatingCacheKey;generation_sha256=$pinnedGenerationSha256
    prewarm_generation_directory=$prewarmGenerationDirectory
    generation_directory=[string]$operatingMaterialization.generation_directory
    members=@($operatingMaterialization.files)
  })
  $failureStage='prepare_period_and_field_probes'
  $probeContract=Join-Path $resultDir 'mirror_period_probe_contract.json';$fly2=Join-Path $solverDir 'mirror_period.fly2';$probeSidecar=Join-Path $solverDir 'mirror_period.probe.lua'
  $selectionReceipt=$null
  if($useRealField){
    if($useVoltagePoint){
      $selectionReceipt=Join-Path $resultDir 'fixed_grid_voltage_point.json'
      Invoke-ProjectPython -Arguments @('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_fixed_grid_voltage_point',
        '--correction',(Join-Path $voltageCorrection 'results\fixed_grid_multifidelity_voltage_correction.json'),
        '--family',(Join-Path $realFieldL1 'inputs\real_3d_mirror_l0_voltage_family.json'),
        '--contract',$contract,'--output',$selectionReceipt)
    }else{
      $selectionReceipt=Join-Path $resultDir 'fixed_0p25mm_validation_selection.json'
      Invoke-ProjectPython -Arguments @('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_real_field_l1_refine','select-fixed-grid',
        '--refinement',(Join-Path $realFieldL1 'results\real_3d_mirror_l1_continuous_refinement.json'),'--contract',$contract,'--output',$selectionReceipt)
    }
    Invoke-ProjectPython -Arguments @('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_real_field_period','prepare-real-field',
      '--refinement-run',$realFieldL1,'--axis-response-run',$axisResponse,'--selection-receipt',$selectionReceipt,
      '--probe-y-mm',(Number $ProbeYmm),'--contract-output',$probeContract,'--fly2-output',$fly2)
  }else{
    Invoke-ProjectPython -Arguments @('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_real_field_period','prepare','--exact-k-run',$exactK,'--probe-y-mm',(Number $ProbeYmm),'--contract-output',$probeContract,'--fly2-output',$fly2)
  }
  Invoke-ProjectPython -Arguments @('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_real_field_profile','prepare','--coarse-workbench',$workbench,'--fine-workbench',$workbench,
    '--output-directory',$resultDir,'--probe-y-mm',(Number $ProbeYmm),'--fine-mirror-mesh-mm',(Number $MirrorTurnMeshMm))
  $probe=Get-Content $probeContract -Raw|ConvertFrom-Json -Depth 30
  $probeEntries=@($probe.particles|ForEach-Object{'  [{0}]={1:R}'-f[int]$_.particle_id,[double]$_.target_energy_ev})
  [IO.File]::WriteAllText($probeSidecar,"return {`n"+($probeEntries-join",`n")+"`n}`n",[Text.UTF8Encoding]::new($false))
  $mirrorVoltages=@($probe.mirror_voltages_v|ForEach-Object{[double]$_})
  $localVoltages=(@($mirrorVoltages[1],$mirrorVoltages[2],$mirrorVoltages[3],$mirrorVoltages[4],0,0,0,0)|ForEach-Object{Number $_})-join','
  $plan=Get-Content (Join-Path $workbench 'results\current_analyzer_local_refinement_plan.json') -Raw|ConvertFrom-Json -Depth 30
  $fixedDir=Join-Path $solverDir 'quarter_mm';New-Item -ItemType Directory -Path $fixedDir -Force|Out-Null
  $familyContracts=@();$fixedCacheReceipts=@();$quarter=@{};$fixedMisses=@();$fixedCacheKeys=@()
  $fixedDispatchArtifacts=@()
  $fixedCacheRoot=Join-Path $artifactRoot 'common\simion\pa_family_cache'
  $fixedCacheAdapter='projects.parallel_mirror_dual_stripe_mr_tof.analysis.fixed_dirichlet_operating_pa_cache'
  $dirichletBuilder=Join-Path $repoRoot 'common\simion\build_dirichlet_patch_operating_pa.lua'
  $targetMirrorVoltages=(@($mirrorVoltages[1],$mirrorVoltages[2],$mirrorVoltages[3],$mirrorVoltages[4])|ForEach-Object{Number $_})-join','
  $failureStage='fixed_pa_contracts'
  $lease=Enter-HostExecutionLease -Role SIMION -Stage pa_refine -RunId $RunId
  foreach($entry in @(@('negative_mirror','mirror_turn_negative','local_negative_mirror.pa'),@('positive_mirror','mirror_turn_positive','local_positive_mirror.pa'))){
    $label=$entry[0];$region=$entry[1];$sourceName=$entry[2]
    $stage=Join-Path $solverDir ("fixed_{0}"-f$label);New-Item -ItemType Directory -Path $stage|Out-Null
    $gem=Join-Path $stage "$region.gem";$physical=Join-Path $stage 'physical.pa#';$grouped=Join-Path $stage 'grouped.pa#'
    Invoke-ProjectPython -Arguments @('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.analyzer_local_patch_geometry','--contract',$contract,'--region',$region,'--scale-factor',(Number $MirrorTurnMeshMm),'--output',$gem)
    $familyContract=Join-Path $resultDir ("fixed_{0}_contract.json"-f$label);$familyContracts+=$familyContract
    Invoke-ProjectPython -Arguments @('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.analyzer_local_pa_family','--contract',$contract,'--region',$region,'--scale-factor',(Number $MirrorTurnMeshMm),
      '--local-gem',$gem,'--global-family-directory',(Join-Path $geometry 'simion'),'--simion-executable',$simion,'--simion-release','SIMION 2020',
      '--prepared-source-receipt',$preparedReceipt,'--output',$familyContract)
    $fc=Get-Content $familyContract -Raw|ConvertFrom-Json -Depth 30
    $source=Join-Path $halfDir $sourceName;$sourcePa0=Join-Path $halfDir ("parent_{0}.pa"-f$label);Move-Item $source $sourcePa0
    # The native Dirichlet solve writes a fixed-voltage PA0.  Keep that suffix
    # through cache publication/materialization instead of disguising it as a PA.
    $outputName="local_{0}.pa0"-f$label;$output=Join-Path $fixedDir $outputName
    $cacheArguments=@('-m',$fixedCacheAdapter,'--cache-root',$fixedCacheRoot,'--local-family-contract',$familyContract,
      '--parent-half-mm-pa',$sourcePa0,("--target-mirror-voltages-v={0}"-f$targetMirrorVoltages),
      '--dirichlet-builder',$dirichletBuilder,'--output-name',$outputName)
    $probe=(@(Invoke-ProjectPython -Arguments (@($cacheArguments)+@('--action','probe')))-join"`n")|ConvertFrom-Json -Depth 30
    if([string]$probe.cache_key-notmatch'^[0-9A-Fa-f]{64}$'){throw "Fixed operating PA cache probe did not return a canonical cache key for $label."}
    $fixedCacheKeys+=,[string]$probe.cache_key
    if([string]$probe.disposition-eq'hit'){
      $generationSha256=Split-Path -Leaf ([string]$probe.generation_directory)
      $cacheResult=(@(Invoke-ProjectPython -Arguments (@($cacheArguments)+@('--action','materialize','--destination-directory',$fixedDir,'--expected-generation-sha256',$generationSha256)))-join"`n")|ConvertFrom-Json -Depth 30
    }elseif([string]$probe.disposition-eq'miss'){
      $mapping=(@($fc.raw_physical_to_local_electrode_id.PSObject.Properties|Sort-Object {[int]$_.Name}|ForEach-Object{"$($_.Name):$($_.Value)"}))-join','
      $origin=((@($fc.patch_origin_project_mm) | ForEach-Object { Number ([double]$_) }) -join ',')
      $workerOutputDir=Join-Path $stage 'output';New-Item -ItemType Directory -Path $workerOutputDir -Force|Out-Null
      $workerOutput=Join-Path $workerOutputDir $outputName
      $workerReceipt=Join-Path $resultDir ("fixed_{0}_worker.json"-f$label)
      $fixedMisses+=,[pscustomobject]@{
        label=$label;stage=$stage;gem=$gem;physical=$physical;grouped=$grouped
        output=$workerOutput;output_directory=$workerOutputDir;destination=$output
        source_pa0=$sourcePa0;origin=$origin;mapping=$mapping;receipt=$workerReceipt
        cache_arguments=$cacheArguments;cache_key=[string]$probe.cache_key
      }
      continue
    }else{throw "Fixed operating PA cache is corrupt for $label`: $($probe.detail)"}
    $cacheReceipt=Join-Path $resultDir ("fixed_{0}_cache.json"-f$label);Write-RunJson -Path $cacheReceipt -Depth 30 -Value $cacheResult;$fixedCacheReceipts+=$cacheReceipt
    $origin=((@($fc.patch_origin_project_mm) | ForEach-Object { Number ([double]$_) }) -join ',')
    $quarter[$label]=$output
    if(Test-Path -LiteralPath $stage -PathType Container){Get-ChildItem $stage -Recurse -File|ForEach-Object{[IO.File]::SetAttributes($_.FullName,[IO.FileAttributes]::Normal)};Remove-Item -LiteralPath $stage -Recurse -Force}
  }
  if($fixedMisses.Count-gt0){
    $failureStage='fixed_pa_dispatch'
    # At 0.25 mm, one output PA is about eight times its 0.5-mm parent. During
    # solve the grouped and output PA coexist; reserve twice that output estimate
    # per miss before the scheduler is allowed to launch a two-lane wave.
    [int64]$fixedTransientBytes=0
    foreach($miss in $fixedMisses){[int64]$parentBytes=(Get-Item -LiteralPath $miss.source_pa0).Length;$fixedTransientBytes+=$parentBytes*16}
    $fixedCapacity=Invoke-ArtifactCapacityGate -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot `
      -RequiredHeadroomBytes ($headroom+$fixedTransientBytes) -ProtectedPaths (@($package.artifact_run_dir)+$capacityProtectedRoots) `
      -ProtectedCacheKeys (@($operatingCacheKey)+$fixedCacheKeys)
    $fixedCapacityPath=Join-Path $resultDir 'artifact_capacity_gate_fixed_pa_dispatch.json'
    Write-RunJson -Path $fixedCapacityPath -Depth 14 -Value $fixedCapacity
    $fixedDispatchArtifacts=@($fixedCapacityPath)
    $worker=Join-Path $PSScriptRoot 'run_fixed_dirichlet_mirror_worker.ps1'
    $fixedResourceIdentity=Join-Path $resultDir 'fixed_mirror_resource_identity.json'
    Write-RunJson -Path $fixedResourceIdentity -Depth 12 -Value ([ordered]@{
      schema_version=1;role='mrtof_fixed_dirichlet_mirror_resource_identity'
      voltage_independent=$true;reason='Compile, electrode remap, and fixed-grid Laplace iteration use the same mesh and topology regardless of the Dirichlet voltage values.'
      canonical_geometry_sha256=(Get-FileHash -LiteralPath $canonical -Algorithm SHA256).Hash
      worker_sha256=(Get-FileHash -LiteralPath $worker -Algorithm SHA256).Hash
      dirichlet_builder_sha256=(Get-FileHash -LiteralPath $dirichletBuilder -Algorithm SHA256).Hash
      remapper_sha256=(Get-FileHash -LiteralPath (Join-Path $repoRoot 'common\simion\remap_pa_electrode_ids.lua') -Algorithm SHA256).Hash
    })
    $pwsh=(Get-Process -Id $PID).Path
    $specifications=@(for($missIndex=0;$missIndex-lt$fixedMisses.Count;$missIndex++){
      $miss=$fixedMisses[$missIndex]
      [pscustomobject]@{
        name=("mrtof_fixed_dirichlet_{0}"-f$miss.label);file_path=$pwsh;working_directory=$repoRoot
        stdout=Join-Path $logDir ("fixed_{0}_worker.stdout.log"-f$miss.label)
        stderr=Join-Path $logDir ("fixed_{0}_worker.stderr.log"-f$miss.label)
        environment=@{MRTOF_SIMION_EXE=$simion}
        argument_list=[string[]]@('-NoProfile','-File',$worker,'-RepoRoot',$repoRoot,'-GemPath',$miss.gem,
          '-PhysicalPaPath',$miss.physical,'-GroupedPaPath',$miss.grouped,'-OutputPaPath',$miss.output,
          '-ParentHalfMillimeterPaPath',$miss.source_pa0,'-PatchOriginCsv',$miss.origin,
          '-LocalVoltagesCsv',$localVoltages,'-ElectrodeMappingCsv',$miss.mapping,'-ReceiptPath',$miss.receipt)
      }
    })
    $oneMiss=$fixedMisses.Count-eq1
    $dispatchRequest=Join-Path $resultDir 'fixed_mirror_dispatch_request.json'
    $resourceProfiles=Join-Path $resultDir 'fixed_mirror_resource_profiles.json'
    $dispatchPlan=Join-Path $resultDir 'fixed_mirror_dispatch_plan.json'
    $resourceUsage=Join-Path $logDir 'fixed_mirror_resource_usage.json'
    $fixedDispatchArtifacts+=@($fixedResourceIdentity,$dispatchRequest,$resourceProfiles,$dispatchPlan,$resourceUsage)
    Write-RunJson -Path $dispatchRequest -Depth 10 -Value ([ordered]@{
        solver='SIMION';field_kind='electrostatic';work_item_count=$fixedMisses.Count;independent_work_items=$true
        frontend_grid_profile_id='mrtof_fixed_dirichlet_mirror_0p25mm';oatof_numerical_profile_id=$null
        trajectory_quality_profile_id=$null;time_integration_profile_id=$null;frontend_cell_mm_xyz=@(0.25,0.25,0.25)
        accelerator_overlay_cell_mm_xyz=$null;reflectron_cell_mm=$null;trajectory_quality=$null;rf_steps_per_period=$null
        accelerator_field_profile_id=$null;frontend_pa0_sha256=(Get-FileHash -LiteralPath $canonical -Algorithm SHA256).Hash
        accelerator_overlay_pa0_sha256=$null;reflectron_pa0_sha256=$null
        case_input_sha256=(Get-FileHash -LiteralPath $fixedResourceIdentity -Algorithm SHA256).Hash
        workload_topology_id='mrtof_two_independent_fixed_dirichlet_mirror_builds'
        field_loading_policy_id='private_compile_remap_solve_then_serial_cache_publish'
    })
    Invoke-ProjectPython -Arguments @('-m','common.simion.resource_profile','discover','--runs-root',(Join-Path $artifactRoot "projects\$projectId\runs"),'--output',$resourceProfiles)
    Invoke-ProjectPython -Arguments @('-m','common.simion.resource_scheduler','--request',$dispatchRequest,'--profiles',$resourceProfiles,'--output',$dispatchPlan)
    $planned=Get-Content $dispatchPlan -Raw|ConvertFrom-Json -Depth 20
    $existing=@();$pending=$specifications;$didFormalObservation=$false
    if([string]$planned.estimation.kind-eq'formal_first_batch_observation'){
      $specifications[0]|Add-Member -NotePropertyName scheduler_batch -NotePropertyValue $planned.waves[0].batches[0] -Force
      $formal=Start-ObservedFormalProcess -DispatchPlanPath $dispatchPlan -ProcessSpecification $specifications[0] -WaitForNaturalCompletionAfterObservation:$oneMiss
      $fixedFormalRecord=$formal.process_record
      if($formal.resource_budget_exceeded){throw 'Fixed-mirror formal worker exceeded the repository resource budget.'}
      if($formal.process_record.completed-and(-not$formal.completed_naturally-or$null-eq$formal.exit_code-or[int]$formal.exit_code-ne0)){
        throw 'Fixed-mirror formal worker failed before dispatch replanning; sibling work will not start.'
      }
      $replan=@('-m','common.simion.resource_scheduler','--request',$dispatchRequest,'--profiles',$resourceProfiles,'--output',$dispatchPlan,
        '--observed-formal-peak-bytes',([string]$formal.observed_peak_process_tree_working_set_bytes),
        '--observed-formal-cpu-percent',([string]$formal.observed_process_cpu_percent),
        '--observed-background-cpu-percent',([string]$formal.observed_background_cpu_percent),
        '--available-memory-bytes',([string]$formal.available_memory_bytes),'--total-physical-memory-bytes',([string]$formal.total_physical_memory_bytes))
      if($formal.process_record.completed){$replan+='--first-batch-completed'}
      Invoke-ProjectPython -Arguments $replan
      $didFormalObservation=$true;$existing=@($fixedFormalRecord);$pending=if($oneMiss){@()}else{@($specifications[1])}
    }
    $finalPlan=Get-Content $dispatchPlan -Raw|ConvertFrom-Json -Depth 20
    $batches=@($finalPlan.waves[0].batches)
    for($index=0;$index-lt$specifications.Count;$index++){
      if(-not($specifications[$index].PSObject.Properties.Name-contains'scheduler_batch')){
        $batch=@($batches|Where-Object{[int]$_.work_item_id_min-le($index+1)-and[int]$_.work_item_id_max-ge($index+1)})[0]
        $specifications[$index]|Add-Member -NotePropertyName scheduler_batch -NotePropertyValue $batch -Force
      }
    }
    $wave=Invoke-ResourceBudgetedProcesses -DispatchPlanPath $dispatchPlan -RunDir $runDir -UsagePath $resourceUsage -ProcessSpecifications $pending -ExistingProcessRecords $existing
    $fixedFormalRecord=$null
    if($wave.resource_budget_exceeded-or@($wave.processes|Where-Object{[int]$_.exit_code-ne0}).Count-ne0){throw 'Fixed-mirror parallel worker wave failed or exceeded the repository resource budget.'}
    Complete-ResourceUsage -RunDir $runDir -UsagePath $resourceUsage|Out-Null
    if($didFormalObservation){
      $fixedResourceProfile=Join-Path $resultDir 'simion_resource_profile.json'
      Invoke-ProjectPython -Arguments @('-m','common.simion.resource_profile','publish','--run-id',$RunId,
        '--resource-usage',$resourceUsage,'--resource-usage-relative-path','logs/fixed_mirror_resource_usage.json',
        '--dispatch-plan',$dispatchPlan,'--dispatch-plan-relative-path','results/fixed_mirror_dispatch_plan.json','--output',$fixedResourceProfile)
      $fixedDispatchArtifacts+=$fixedResourceProfile
    }
    $failureStage='fixed_pa_cache_publish'
    foreach($miss in $fixedMisses){
      $workerReceipt=Get-Content $miss.receipt -Raw|ConvertFrom-Json -Depth 10
      if([string]$workerReceipt.status-ne'success'){throw "Fixed operating PA worker receipt failed for $($miss.label)."}
      $cacheResult=(@(Invoke-ProjectPython -Arguments (@($miss.cache_arguments)+@('--action','publish','--source-directory',$miss.output_directory)))-join"`n")|ConvertFrom-Json -Depth 30
      $materialization=(@(Invoke-ProjectPython -Arguments (@($miss.cache_arguments)+@('--action','materialize','--destination-directory',$fixedDir,
        '--expected-generation-sha256',[string]$cacheResult.generation_sha256)))-join"`n")|ConvertFrom-Json -Depth 30
      if([string]$materialization.generation_sha256-ne[string]$cacheResult.generation_sha256){throw "Fixed operating PA materialization generation differs from publication for $($miss.label)."}
      $cacheReceipt=Join-Path $resultDir ("fixed_{0}_cache.json"-f$miss.label);Write-RunJson -Path $cacheReceipt -Depth 30 -Value $cacheResult
      $materializationReceipt=Join-Path $resultDir ("fixed_{0}_materialization.json"-f$miss.label);Write-RunJson -Path $materializationReceipt -Depth 30 -Value $materialization
      $fixedCacheReceipts+=@($cacheReceipt,$materializationReceipt);$quarter[$miss.label]=$miss.destination
      if(Test-Path -LiteralPath $miss.stage -PathType Container){Get-ChildItem $miss.stage -Recurse -File|ForEach-Object{[IO.File]::SetAttributes($_.FullName,[IO.FileAttributes]::Normal)};Remove-Item -LiteralPath $miss.stage -Recurse -Force}
    }
  }
  Exit-HostExecutionLease -Lease $lease -Outcome success -RunId $RunId;$lease=$null
  $failureStage='sample_half_vs_quarter_fields'
  $profile=Get-Content (Join-Path $resultDir 'profile_contract.json') -Raw|ConvertFrom-Json -Depth 20
  $files=@{negative_mirror='parent_negative_mirror.pa';negative_bridge='local_negative_bridge.pa';central='local_central.pa';positive_bridge='local_positive_bridge.pa';positive_mirror='parent_positive_mirror.pa'}
  $compare=Join-Path $repoRoot 'common\simion\compare_pa_fields_at_samples.lua';$lease=Enter-HostExecutionLease -Role SIMION -Stage mirror_field_sampling -RunId $RunId
  foreach($region in $profile.regions){
    $label=[string]$region.label
    $origin=((@($region.coarse_origin_mm) | ForEach-Object { Number ([double]$_) }) -join ',')
    $coarse=Join-Path $halfDir $files[$label]
    $fine=if($quarter.ContainsKey($label)){$quarter[$label]}else{$coarse}
    $out=Join-Path $resultDir ("comparison_{0}.csv"-f$label)
    Invoke-Simion "sample_$label" @('--nogui','--noprompt','lua',$compare,$coarse,$origin,$fine,$origin,'identity','identity',([string]$region.sample_csv),$out)
  }
  $fixedL1Plan=$null;$fixedL1Spec=$null;$fixedL1Csv=$null;$fixedL1Analysis=$null
  if($useRealField -and -not $NativeTransverseL1){
    $sourceSamplingPlan=Get-Content (Join-Path $realFieldL1 'inputs\mirror_l1_response_sampling_plan.json') -Raw|ConvertFrom-Json -Depth 30
    $operatingPaths=@{
      mirror_turn_negative=$quarter.negative_mirror
      stripe_mirror_bridge_negative=Join-Path $halfDir 'local_negative_bridge.pa'
      central_transport=Join-Path $halfDir 'local_central.pa'
      stripe_mirror_bridge_positive=Join-Path $halfDir 'local_positive_bridge.pa'
      mirror_turn_positive=$quarter.positive_mirror
    }
    $fixedSampleStep=[double]$MirrorTurnMeshMm
    $sourceRegions=@($sourceSamplingPlan.regions)
    $fixedRegions=@(for($regionIndex=0;$regionIndex-lt$sourceRegions.Count;$regionIndex++){
      $sourceRegion=$sourceRegions[$regionIndex]
      $regionId=[string]$sourceRegion.region_id
      # The retained 0.5-mm responsibility nodes leave one 0.25-mm midpoint
      # between adjacent regions.  Assign that midpoint to the preceding PA;
      # no PA geometry or physical overlap is changed.
      $responsibilityMaximum=if($regionIndex-lt($sourceRegions.Count-1)){
        [double]$sourceRegions[$regionIndex+1].z_range_mm[0]-$fixedSampleStep
      }else{[double]$sourceRegion.z_range_mm[1]}
      [ordered]@{
        region_id=$regionId;standalone_pa_path=[string]$operatingPaths[$regionId]
        region_origin_project_mm=@($sourceRegion.region_origin_project_mm|ForEach-Object{[double]$_})
        mesh_mm_per_gu=if($regionId-like'mirror_turn_*'){@(0.25,0.25,0.25)}else{@(0.5,0.5,0.5)}
        z_range_mm=@([double]$sourceRegion.z_range_mm[0],$responsibilityMaximum)
      }
    })
    $fixedL1Plan=Join-Path $resultDir 'fixed_operating_field_sampling_plan.json'
    Write-RunJson -Path $fixedL1Plan -Depth 20 -Value ([ordered]@{
      schema_version=1;role='mrtof_fixed_operating_field_slice';project_frame=[string]$sourceSamplingPlan.project_frame
      slice_y_mm=[double]$sourceSamplingPlan.slice_y_mm;sample_step_mm=$fixedSampleStep
      x_range_mm=@([double]$sourceSamplingPlan.x_range_mm[0],[double]$sourceSamplingPlan.x_range_mm[1]);regions=$fixedRegions
    })
    $fixedL1Spec=Join-Path $solverDir 'fixed_operating_field_slice.spec.lua'
    Invoke-ProjectPython -Arguments @('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_fixed_operating_field_l1','spec','--plan',$fixedL1Plan,'--output',$fixedL1Spec)
    $fixedL1Csv=Join-Path $resultDir 'fixed_operating_field_slice.csv'
    Invoke-Simion 'sample_fixed_operating_l1_field' @('--nogui','--noprompt','lua',(Join-Path $PSScriptRoot 'sample_fixed_operating_field_slice.lua'),$fixedL1Spec,$fixedL1Csv)
  }
  Exit-HostExecutionLease -Lease $lease -Outcome success -RunId $RunId;$lease=$null
  $fieldAnalysis=Join-Path $resultDir 'mirror_axis_field_comparison.json'
  $profileArguments=@('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_real_field_profile','analyze','--contract',(Join-Path $resultDir 'profile_contract.json'),'--exact-k-run',$exactK,'--samples-directory',$resultDir,'--output',$fieldAnalysis)
  if($useRealField){$profileArguments+=@('--voltage-contract',$probeContract)}
  Invoke-ProjectPython -Arguments $profileArguments
  if($useRealField -and -not $NativeTransverseL1){
    $fixedL1Analysis=Join-Path $resultDir 'fixed_operating_field_l1.json'
    Invoke-ProjectPython -Arguments @('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_fixed_operating_field_l1','analyze',
      '--basis',$fixedL1Csv,'--probe-contract',$probeContract,'--project-contract',$contract,'--output',$fixedL1Analysis)
  }
  $failureStage='fly_half_quarter_hybrid'
  $wb=Get-Content (Join-Path $workbench 'run_config.json') -Raw|ConvertFrom-Json -Depth 30;$paDir=Join-Path $solverDir 'pa';New-Item -ItemType Directory -Path $paDir|Out-Null
  $global=New-ShortPaCopy -Source ([string]$wb.inputs.global_analyzer_pa) -Destination (Join-Path $paDir 'analyzer.pa') -MarkDestinationReadOnly
  $accelerator=New-ShortPaCopy -Source ([string]$wb.inputs.accelerator_pa) -Destination (Join-Path $paDir 'accelerator.pa') -MarkDestinationReadOnly
  $detector=New-ShortPaCopy -Source ([string]$wb.inputs.detector_pa) -Destination (Join-Path $paDir 'detector.pa') -MarkDestinationReadOnly;$shortCopies=@($global,$accelerator,$detector)
  $locals=@($quarter.negative_mirror,(Join-Path $halfDir 'local_negative_bridge.pa'),(Join-Path $halfDir 'local_central.pa'),(Join-Path $halfDir 'local_positive_bridge.pa'),$quarter.positive_mirror)
  $seedRoot=Join-Path $repoRoot 'common\simion\assets\iob_instance_seeds';$seed=Join-Path $solverDir '8_instance_seed.iob';Copy-Item (Join-Path $seedRoot '8_instance_seed.iob') $seed
  foreach($index in 1..8){Copy-Item (Join-Path $seedRoot ('iob_seed_placeholder_{0:D2}.pa0'-f$index)) (Join-Path $solverDir ('iob_seed_placeholder_{0:D2}.pa0'-f$index))}
  $pose=Get-Content (Join-Path $workbench 'results\resolved_iob_pose.json') -Raw|ConvertFrom-Json -Depth 10
  $origins=@(@([double]$pose.origins_mm.analyzer[0],[double]$pose.origins_mm.analyzer[1],[double]$pose.origins_mm.analyzer[2]),@($plan.patches.mirror_turn_negative[0..2]),@($plan.patches.stripe_mirror_bridge_negative[0..2]),@($plan.patches.central_transport[0..2]),@($plan.patches.stripe_mirror_bridge_positive[0..2]),@($plan.patches.mirror_turn_positive[0..2]),@([double]$pose.origins_mm.accelerator[0],[double]$pose.origins_mm.accelerator[1],[double]$pose.origins_mm.accelerator[2]),@([double]$pose.origins_mm.detector[0],[double]$pose.origins_mm.detector[1],[double]$pose.origins_mm.detector[2]))
  $iob=Join-Path $solverDir 'mirror_turn_0p25.iob';$builder=Join-Path $PSScriptRoot 'build_mirror_period_iob.lua';$program=Join-Path $PSScriptRoot 'mrtof_mirror_period_validation.lua';$launcher=Join-Path $PSScriptRoot 'run_mirror_period_iob.lua';$localConfig=Join-Path $workbench 'simion\local_refinement.input.lua'
  $args=@('--nogui','--noprompt','lua',$builder,$seed,$global)+$locals+@($accelerator,$detector,$iob,$program,$fly2,$localConfig);foreach($origin in $origins){foreach($value in $origin){$args+=Number ([double]$value)}};$args+=$probeSidecar
  $lease=Enter-HostExecutionLease -Role SIMION -Stage mirror_period_flight -RunId $RunId;Invoke-Simion 'build_iob' $args;foreach($copy in $shortCopies){Protect-ShortPaCopyDestination $copy|Out-Null};$flightLog=Join-Path $logDir 'mirror_period_flight.log';$flight=& $simion --nogui --noprompt lua $launcher $iob 2>&1;$flightText=$flight|Out-String;[IO.File]::WriteAllText($flightLog,$flightText,[Text.UTF8Encoding]::new($false));if($flightText){Write-Host $flightText.TrimEnd()};if($LASTEXITCODE-ne0){throw 'Hybrid mirror flight failed'};Exit-HostExecutionLease -Lease $lease -Outcome success -RunId $RunId;$lease=$null
  $periodAnalysis=Join-Path $resultDir 'mirror_real_field_period_comparison.json';Invoke-ProjectPython -Arguments @('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_real_field_period','analyze','--contract',$probeContract,'--log',$flightLog,'--output',$periodAnalysis)
  $nativeL1Contract=$null;$nativeL1Log=$null;$nativeL1Analysis=$null
  if($NativeTransverseL1){
    $failureStage='native_transverse_l1_prepare'
    $nativeL1Contract=Join-Path $resultDir 'native_transverse_l1_probe_contract.json'
    $nativeFly2=Join-Path $solverDir 'mirror_turn_0p25.native_l1.fly2'
    $nativeSidecar=Join-Path $solverDir 'mirror_turn_0p25.native_l1.lua'
    $nativeProjectContract=Get-Content $contract -Raw|ConvertFrom-Json -Depth 30
    $l1=$nativeProjectContract.mirror.theory_requirements.l1_screen_profile
    Invoke-ProjectPython -Arguments @('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_native_transverse_l1','prepare',
      '--period-probe-contract',$probeContract,'--position-probe-mm',(Number ([double]$l1.position_probe_mm)),
      '--angle-probe-rad',(Number ([double]$l1.angle_probe_rad)),'--contract-output',$nativeL1Contract,
      '--fly2-output',$nativeFly2,'--lua-source-output',$nativeSidecar)
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'mrtof_mirror_transverse_l1_validation.lua') -Destination ($iob-replace'\.iob$','.lua') -Force
    Copy-Item -LiteralPath $nativeFly2 -Destination ($iob-replace'\.iob$','.fly2') -Force
    $failureStage='native_transverse_l1_flight'
    $lease=Enter-HostExecutionLease -Role SIMION -Stage mirror_period_flight -RunId $RunId
    $nativeL1Log=Join-Path $logDir 'native_transverse_l1.log';$nativeFlight=& $simion --nogui --noprompt lua $launcher $iob 2>&1;$nativeFlightText=$nativeFlight|Out-String;[IO.File]::WriteAllText($nativeL1Log,$nativeFlightText,[Text.UTF8Encoding]::new($false));if($nativeFlightText){Write-Host $nativeFlightText.TrimEnd()};if($LASTEXITCODE-ne0){throw 'Native transverse mirror L1 flight failed'};Exit-HostExecutionLease -Lease $lease -Outcome success -RunId $RunId;$lease=$null
    $failureStage='native_transverse_l1_analyze'
    $nativeL1Analysis=Join-Path $resultDir 'native_transverse_l1.json'
    Invoke-ProjectPython -Arguments @('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_native_transverse_l1','analyze','--contract',$nativeL1Contract,'--log',$nativeL1Log,'--output',$nativeL1Analysis)
  }
  foreach($copy in $shortCopies){Remove-ShortPaCopy $copy};$shortCopies=@()
  $field=Get-Content $fieldAnalysis -Raw|ConvertFrom-Json -Depth 40;$period=Get-Content $periodAnalysis -Raw|ConvertFrom-Json -Depth 40
  $fixedL1=if($fixedL1Analysis){Get-Content $fixedL1Analysis -Raw|ConvertFrom-Json -Depth 40}else{$null}
  $nativeL1=if($nativeL1Analysis){Get-Content $nativeL1Analysis -Raw|ConvertFrom-Json -Depth 40}else{$null}
  Write-RunJson -Path $summary -Depth 40 -Value ([ordered]@{schema_version=1;role='mrtof_mirror_turn_fixed_grid_validation';status='success';qualification='two_mirror_turn_regions_at_0p25mm__other_regions_at_0p5mm__validation_diagnostic__acceptance_gates_remain_open';probe_y_mm=$ProbeYmm;mesh_by_region_mm_per_gu=$field.mesh_by_region_mm_per_gu;global_field_metrics=$field.global_metrics;region_field_metrics=$field.region_metrics;theory_normalized_period_slopes_per_v=$period.theory_normalized_period_slopes_per_v;simion_normalized_period_slopes_per_v=$period.simion_normalized_period_slopes_per_v;center_period_residual_ppm=$period.center_period_residual_ppm;fixed_operating_l1_status=if($fixedL1){[string]$fixedL1.status}else{$null};fixed_operating_l1_hard_gate_failures=if($fixedL1){@($fixedL1.hard_gate_failures)}else{@()};fixed_operating_l1_selection_metrics=if($fixedL1){$fixedL1.selection_metrics}else{$null};native_transverse_l1_status=if($nativeL1){[string]$nativeL1.status}else{$null};native_transverse_l1_directions=if($nativeL1){$nativeL1.directions}else{$null}})
  $config=Get-Content $runConfig -Raw|ConvertFrom-Json -AsHashtable;$config.inputs=[ordered]@{exact_k_geometry_theory_manifest=Join-Path $exactK 'run_manifest.json';half_mm_workbench_manifest=Join-Path $workbench 'run_manifest.json';half_mm_prewarm_run_manifest=$prewarmManifestPath;half_mm_operating_pa_cache_identity=$operatingCacheIdentity;half_mm_operating_pa_cache_final_probe=$prewarmFinalProbePath;prewarm_operating_pa_generation_projection=$prewarmProjection;parent_operating_pa_generation=$parentGenerationContract;geometry_review_manifest_snapshot=$geometryManifestSnapshot;reviewed_analyzer_gem=$reviewedGem;prepared_analyzer_source_manifest=$preparedSourceManifestPath;prepared_analyzer_source_receipt=$preparedReceipt;real_field_l1_manifest=if($useRealField){Join-Path $realFieldL1 'run_manifest.json'}else{$null};axis_response_manifest=if($useRealField){Join-Path $axisResponse 'run_manifest.json'}else{$null};fixed_grid_voltage_correction_manifest=if($useVoltagePoint){Join-Path $voltageCorrection 'run_manifest.json'}else{$null};fixed_grid_selection_receipt=$selectionReceipt};$config.parameters=[ordered]@{probe_y_mm=$ProbeYmm;mirror_turn_mesh_mm=$MirrorTurnMeshMm;other_local_mesh_mm=0.5;mirror_voltage_source=if($useVoltagePoint){'fixed_grid_secant_diagnostic_point'}elseif($useRealField){'selected_real_field_l1_root'}else{'exact_k_analytic_2d'};fixed_operating_pa=$true;response_family_not_built=$true;estimated_avoided_full_0p25_family_bytes=119167084800;native_transverse_l1=[bool]$NativeTransverseL1;lifecycle_stage='terminal'};Write-RunJson -Path $runConfig -Depth 20 -Value $config
  $retention=Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $runConfig;$terminal=Invoke-ArtifactCapacityGate -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot -ProtectedPaths (@($package.artifact_run_dir)+$capacityProtectedRoots) -ProtectedCacheKeys @($operatingCacheKey);$terminalPath=Join-Path $resultDir 'artifact_capacity_gate_terminal.json';Write-RunJson -Path $terminalPath -Depth 14 -Value $terminal
  $outputs=@($summary,$probeContract,$fieldAnalysis,$periodAnalysis,$flightLog,$startupPath,$terminalPath,$retention,$prewarmProjection,$parentGenerationContract)+$(if($selectionReceipt){@($selectionReceipt)}else{@()})+$(if($fixedL1Analysis){@($fixedL1Plan,$fixedL1Csv,$fixedL1Analysis)}else{@()})+$(if($nativeL1Analysis){@($nativeL1Contract,$nativeL1Analysis,$nativeL1Log)}else{@()})+$familyContracts+$fixedCacheReceipts+@($fixedDispatchArtifacts|Where-Object{Test-Path -LiteralPath $_ -PathType Leaf})+@(Get-ChildItem $resultDir -Filter 'fixed_*_worker.json'|ForEach-Object{$_.FullName})+@(Get-ChildItem $resultDir -Filter 'comparison_*.csv'|ForEach-Object{$_.FullName});Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -Status success -Software @('SIMION 2020','Python 3.11') -RunConfig $runConfig -Outputs ($outputs|ForEach-Object{ArtifactPath $_})|Out-Null
  $terminalized=$true;$hostOutcome='success';Write-Host "MRTOF_MIRROR_TURN_FIXED_GRID=PASS RUN_ID=$RunId"
}catch{if($null-ne$fixedFormalRecord-and-not[bool]$fixedFormalRecord.completed){try{Stop-ManagedSolverProcesses -ProcessIds @($fixedFormalRecord.tracked_process_ids)}catch{}};if($null-ne$lease){Exit-HostExecutionLease -Lease $lease -Outcome failed -RunId $RunId;$lease=$null};foreach($copy in $shortCopies){try{Remove-ShortPaCopy $copy}catch{}};if(-not$terminalized){Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Summary $summary -SummaryRole 'mrtof_mirror_turn_fixed_grid_validation' -Reason $_.Exception.Message -Software @('SIMION 2020','Python 3.11') -FailureStage $failureStage;$terminalized=$true};throw
}finally{if($null-ne$lease){Exit-HostExecutionLease -Lease $lease -Outcome $hostOutcome -RunId $RunId};Remove-RunPackageExecutionAlias -Package $package}

[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$ExactKRunPath,
  [Parameter(Mandatory)][string]$HalfMillimeterWorkbenchRunPath,
  [Parameter(Mandatory)][string]$HalfMillimeterPrewarmRunPath,
  [Parameter(Mandatory)][string]$GeometryReviewRunPath,
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
$artifactRoot=Join-Path $workspaceRoot 'artifacts'
$package=New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot (Join-Path $artifactRoot "projects\$projectId") `
  -RunId $RunId -Project $projectId -Mode 'mirror_turn_fixed_operating_grid_validation' `
  -Software @('SIMION 2020','Python 3.11') -RetentionContractEnabled -RetentionClass compact `
  -AdditionalDirectories @('simion') -UseShortExecutionPath
$runDir=$package.run_dir;$inputDir=$package.input_dir;$resultDir=$package.result_dir;$logDir=$package.log_dir
$solverDir=Join-Path $runDir 'simion';$runConfig=$package.run_config;$summary=$package.summary
$terminalized=$false;$lease=$null;$failureStage='preflight';$hostOutcome='failed';$shortCopies=@()
function Invoke-ProjectPython([string[]]$Arguments){Push-Location $repoRoot;$saved=$env:PYTHONPATH;try{$env:PYTHONPATH=$repoRoot;& $python @Arguments;if($LASTEXITCODE-ne0){throw "Python failed: $($Arguments-join' ')"}}finally{$env:PYTHONPATH=$saved;Pop-Location}}
function Invoke-Simion([string]$Stage,[string[]]$Arguments){$out=& $simion @Arguments 2>&1;$text=$out|Out-String;[IO.File]::WriteAllText((Join-Path $logDir "$Stage.log"),$text,[Text.UTF8Encoding]::new($false));if($text){Write-Host $text.TrimEnd()};if($LASTEXITCODE-ne0){throw "SIMION stage failed: $Stage"}}
function Number([double]$Value){[string]::Format([Globalization.CultureInfo]::InvariantCulture,'{0:R}',$Value)}
function ArtifactPath([string]$Path){$full=[IO.Path]::GetFullPath($Path);$exec=[IO.Path]::GetFullPath([string]$package.run_dir).TrimEnd([char[]]@(92,47));$artifact=[IO.Path]::GetFullPath([string]$package.artifact_run_dir).TrimEnd([char[]]@(92,47));if($full.StartsWith($exec,[StringComparison]::OrdinalIgnoreCase)){return $artifact+$full.Substring($exec.Length)};$full}
try{
  $exactK=(Resolve-Path $ExactKRunPath).Path;$workbench=(Resolve-Path $HalfMillimeterWorkbenchRunPath).Path
  $prewarm=(Resolve-Path $HalfMillimeterPrewarmRunPath).Path;$geometry=(Resolve-Path $GeometryReviewRunPath).Path
  foreach($root in @($exactK,$workbench,$prewarm,$geometry)){& $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') (Join-Path $root 'run_manifest.json') --require-status success;if($LASTEXITCODE-ne0){throw "Input manifest failed: $root"}}
  $failureStage='capacity_preflight'
  [int64]$headroom=16GB
  $startup=Invoke-ArtifactCapacityGate -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot -RequiredHeadroomBytes $headroom -ProtectedPaths @($package.artifact_run_dir,$exactK,$workbench,$prewarm,$geometry)
  $startupPath=Join-Path $resultDir 'artifact_capacity_gate_startup.json';Write-RunJson -Path $startupPath -Depth 14 -Value $startup
  $contract=Copy-VerifiedRunInput -Source (Join-Path $repoRoot "projects\$projectId\config\simion_candidate_two_zone.json") -Destination (Join-Path $inputDir 'simion_candidate_two_zone.json')
  $canonical=Join-Path $solverDir 'canonical_mrtof_analyzer.gem'
  Invoke-ProjectPython -Arguments @('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.split_candidate_geometry','--contract',$contract,'--component','analyzer','--output',$canonical)
  $reviewedGem=Join-Path $geometry 'simion\mrtof_analyzer.gem'
  if(-not(Test-RunFilesIdentical -Left $canonical -Right $reviewedGem)){throw 'Current baseline differs from reviewed analyzer geometry.'}
  $failureStage='materialize_half_millimeter_parent'
  $halfDir=Join-Path $solverDir 'half_mm';New-Item -ItemType Directory -Path $halfDir -Force|Out-Null
  Invoke-ProjectPython -Arguments @('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.local_operating_pa_cache','--action','materialize',
    '--identity-input',(Join-Path $prewarm 'results\local_operating_pa_cache_identity.json'),'--cache-root',(Join-Path $artifactRoot 'common\simion\pa_family_cache'),'--destination-directory',$halfDir)
  $failureStage='prepare_period_and_field_probes'
  $probeContract=Join-Path $resultDir 'mirror_period_probe_contract.json';$fly2=Join-Path $solverDir 'mirror_period.fly2';$probeSidecar=Join-Path $solverDir 'mirror_period.probe.lua'
  Invoke-ProjectPython -Arguments @('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_real_field_period','prepare','--exact-k-run',$exactK,'--probe-y-mm',(Number $ProbeYmm),'--contract-output',$probeContract,'--fly2-output',$fly2)
  Invoke-ProjectPython -Arguments @('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_real_field_profile','prepare','--coarse-workbench',$workbench,'--fine-workbench',$workbench,
    '--output-directory',$resultDir,'--probe-y-mm',(Number $ProbeYmm),'--fine-mirror-mesh-mm',(Number $MirrorTurnMeshMm))
  $probe=Get-Content $probeContract -Raw|ConvertFrom-Json -Depth 30
  $probeEntries=@($probe.particles|ForEach-Object{'  [{0}]={1:R}'-f[int]$_.particle_id,[double]$_.target_energy_ev})
  [IO.File]::WriteAllText($probeSidecar,"return {`n"+($probeEntries-join",`n")+"`n}`n",[Text.UTF8Encoding]::new($false))
  $mirrorVoltages=@($probe.mirror_voltages_v|ForEach-Object{[double]$_})
  $localVoltages=(@($mirrorVoltages[1],$mirrorVoltages[2],$mirrorVoltages[3],$mirrorVoltages[4],0,0,0,0)|ForEach-Object{Number $_})-join','
  $plan=Get-Content (Join-Path $workbench 'results\current_analyzer_local_refinement_plan.json') -Raw|ConvertFrom-Json -Depth 30
  $fixedDir=Join-Path $solverDir 'quarter_mm';New-Item -ItemType Directory -Path $fixedDir -Force|Out-Null
  $familyContracts=@();$quarter=@{}
  $lease=Enter-HostExecutionLease -Role SIMION -Stage pa_refine -RunId $RunId
  foreach($entry in @(@('negative_mirror','mirror_turn_negative','local_negative_mirror.pa'),@('positive_mirror','mirror_turn_positive','local_positive_mirror.pa'))){
    $label=$entry[0];$region=$entry[1];$sourceName=$entry[2]
    $stage=Join-Path $solverDir ("fixed_{0}"-f$label);New-Item -ItemType Directory -Path $stage|Out-Null
    $gem=Join-Path $stage "$region.gem";$physical=Join-Path $stage 'physical.pa#';$grouped=Join-Path $stage 'grouped.pa#'
    Invoke-ProjectPython -Arguments @('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.analyzer_local_patch_geometry','--contract',$contract,'--region',$region,'--scale-factor',(Number $MirrorTurnMeshMm),'--output',$gem)
    $familyContract=Join-Path $resultDir ("fixed_{0}_contract.json"-f$label);$familyContracts+=$familyContract
    Invoke-ProjectPython -Arguments @('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.analyzer_local_pa_family','--contract',$contract,'--region',$region,'--scale-factor',(Number $MirrorTurnMeshMm),
      '--local-gem',$gem,'--global-family-directory',(Join-Path $geometry 'simion'),'--simion-executable',$simion,'--simion-release','SIMION 2020','--output',$familyContract)
    $fc=Get-Content $familyContract -Raw|ConvertFrom-Json -Depth 30
    Invoke-Simion "compile_$label" @('--nogui','--noprompt','gem2pa',$gem,$physical)
    $mapping=(@($fc.raw_physical_to_local_electrode_id.PSObject.Properties|Sort-Object {[int]$_.Name}|ForEach-Object{"$($_.Name):$($_.Value)"}))-join','
    Invoke-Simion "remap_$label" @('--nogui','--noprompt','lua',(Join-Path $repoRoot 'common\simion\remap_pa_electrode_ids.lua'),$physical,$grouped,$mapping)
    $source=Join-Path $halfDir $sourceName;$sourcePa0=Join-Path $halfDir ("parent_{0}.pa"-f$label);Move-Item $source $sourcePa0
    $output=Join-Path $fixedDir ("local_{0}.pa0"-f$label)
    $origin=((@($fc.patch_origin_project_mm) | ForEach-Object { Number ([double]$_) }) -join ',')
    Invoke-Simion "solve_$label" @('--nogui','--noprompt','lua',(Join-Path $repoRoot 'common\simion\build_dirichlet_patch_operating_pa.lua'),$grouped,$output,$sourcePa0,$origin,$origin,$localVoltages)
    $quarter[$label]=$output
    Get-ChildItem $stage -Recurse -File|ForEach-Object{[IO.File]::SetAttributes($_.FullName,[IO.FileAttributes]::Normal)}
    Remove-Item -LiteralPath $stage -Recurse -Force
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
  Exit-HostExecutionLease -Lease $lease -Outcome success -RunId $RunId;$lease=$null
  $fieldAnalysis=Join-Path $resultDir 'mirror_axis_field_comparison.json'
  Invoke-ProjectPython -Arguments @('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_real_field_profile','analyze','--contract',(Join-Path $resultDir 'profile_contract.json'),'--exact-k-run',$exactK,'--samples-directory',$resultDir,'--output',$fieldAnalysis)
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
  foreach($copy in $shortCopies){Remove-ShortPaCopy $copy};$shortCopies=@()
  $field=Get-Content $fieldAnalysis -Raw|ConvertFrom-Json -Depth 40;$period=Get-Content $periodAnalysis -Raw|ConvertFrom-Json -Depth 40
  Write-RunJson -Path $summary -Depth 30 -Value ([ordered]@{schema_version=1;role='mrtof_mirror_turn_fixed_grid_validation';status='success';qualification='two_mirror_turn_regions_at_0p25mm__other_regions_at_0p5mm__candidate';probe_y_mm=$ProbeYmm;mesh_by_region_mm_per_gu=$field.mesh_by_region_mm_per_gu;global_field_metrics=$field.global_metrics;region_field_metrics=$field.region_metrics;theory_normalized_period_slopes_per_v=$period.theory_normalized_period_slopes_per_v;simion_normalized_period_slopes_per_v=$period.simion_normalized_period_slopes_per_v;center_period_residual_ppm=$period.center_period_residual_ppm})
  $config=Get-Content $runConfig -Raw|ConvertFrom-Json -AsHashtable;$config.inputs=[ordered]@{exact_k_manifest=Join-Path $exactK 'run_manifest.json';half_mm_workbench_manifest=Join-Path $workbench 'run_manifest.json';half_mm_prewarm_manifest=Join-Path $prewarm 'run_manifest.json';geometry_review_manifest=Join-Path $geometry 'run_manifest.json'};$config.parameters=[ordered]@{probe_y_mm=$ProbeYmm;mirror_turn_mesh_mm=$MirrorTurnMeshMm;other_local_mesh_mm=0.5;fixed_operating_pa=$true;response_family_not_built=$true;estimated_avoided_full_0p25_family_bytes=119167084800;lifecycle_stage='terminal'};Write-RunJson -Path $runConfig -Depth 20 -Value $config
  $retention=Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $runConfig;$terminal=Invoke-ArtifactCapacityGate -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot -ProtectedPaths @($package.artifact_run_dir,$exactK,$workbench,$prewarm,$geometry);$terminalPath=Join-Path $resultDir 'artifact_capacity_gate_terminal.json';Write-RunJson -Path $terminalPath -Depth 14 -Value $terminal
  $outputs=@($summary,$probeContract,$fieldAnalysis,$periodAnalysis,$flightLog,$startupPath,$terminalPath,$retention)+$familyContracts+@(Get-ChildItem $resultDir -Filter 'comparison_*.csv'|ForEach-Object{$_.FullName});Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Status success -Software @('SIMION 2020','Python 3.11') -Outputs ($outputs|ForEach-Object{ArtifactPath $_})|Out-Null
  $terminalized=$true;$hostOutcome='success';Write-Host "MRTOF_MIRROR_TURN_FIXED_GRID=PASS RUN_ID=$RunId"
}catch{if($null-ne$lease){Exit-HostExecutionLease -Lease $lease -Outcome failed -RunId $RunId;$lease=$null};foreach($copy in $shortCopies){try{Remove-ShortPaCopy $copy}catch{}};if(-not$terminalized){Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Summary $summary -SummaryRole 'mrtof_mirror_turn_fixed_grid_validation' -Reason $_.Exception.Message -Software @('SIMION 2020','Python 3.11') -FailureStage $failureStage;$terminalized=$true};throw
}finally{if($null-ne$lease){Exit-HostExecutionLease -Lease $lease -Outcome $hostOutcome -RunId $RunId};Remove-RunPackageExecutionAlias -Package $package}

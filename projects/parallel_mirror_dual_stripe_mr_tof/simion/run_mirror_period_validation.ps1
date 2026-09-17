[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$ExactKRunPath,
  [Parameter(Mandatory)][string]$LocalWorkbenchRunPath,
  [Parameter(Mandatory)][string]$MirrorOnlyPrewarmRunPath,
  [string]$RealFieldL1RunPath='',
  [string]$AxisResponseRunPath='',
  [double]$ProbeYmm=280.0,
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
foreach($path in @($python,$simion)){if(-not(Test-Path -LiteralPath $path -PathType Leaf)){throw "Executable is missing: $path"}}
$exactK=(Resolve-Path -LiteralPath $ExactKRunPath).Path
$workbench=(Resolve-Path -LiteralPath $LocalWorkbenchRunPath).Path
$prewarm=(Resolve-Path -LiteralPath $MirrorOnlyPrewarmRunPath).Path
$useRealField=-not[string]::IsNullOrWhiteSpace($RealFieldL1RunPath)
if($useRealField-ne(-not[string]::IsNullOrWhiteSpace($AxisResponseRunPath))){throw 'RealFieldL1RunPath and AxisResponseRunPath must be supplied together.'}
$realFieldL1=if($useRealField){(Resolve-Path -LiteralPath $RealFieldL1RunPath).Path}else{$null}
$axisResponse=if($useRealField){(Resolve-Path -LiteralPath $AxisResponseRunPath).Path}else{$null}
if([string]::IsNullOrWhiteSpace($RunId)){$RunId=(Get-Date -Format 'yyyyMMdd_HHmmss')+'__sim__simion__mrtof-bare-mirror-real-field-period'}

. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')
. (Join-Path $repoRoot 'common\host_execution_lease.ps1')
. (Join-Path $repoRoot 'common\simion\short_pa_path_support.ps1')
$artifactRoot=Join-Path $workspaceRoot 'artifacts'
$package=New-RunPackage -Python $python -RepoRoot $repoRoot `
  -ArtifactRoot (Join-Path $artifactRoot "projects\$projectId") -RunId $RunId `
  -Project $projectId -Mode 'bare_mirror_real_field_period_validation' `
  -Software @('SIMION 2020','Python 3.11') -RetentionContractEnabled -RetentionClass compact `
  -AdditionalDirectories @('simion') -UseShortExecutionPath
$runDir=$package.run_dir;$inputDir=$package.input_dir;$resultDir=$package.result_dir
$logDir=$package.log_dir;$solverDir=Join-Path $runDir 'simion';$runConfig=$package.run_config;$summary=$package.summary
$terminalized=$false;$lease=$null;$hostOutcome='failed';$failureStage='preflight';$localGuards=@();$shortCopies=@()

function Invoke-ProjectPython([string[]]$Arguments){
  Push-Location $repoRoot;$saved=$env:PYTHONPATH
  try{$env:PYTHONPATH=$repoRoot;& $python @Arguments;if($LASTEXITCODE-ne0){throw "Python command failed: $($Arguments-join' ')"}}
  finally{$env:PYTHONPATH=$saved;Pop-Location}
}
function ConvertTo-ArtifactRunPath([string]$Path){
  $full=[IO.Path]::GetFullPath($Path)
  $execution=[IO.Path]::GetFullPath([string]$package.run_dir).TrimEnd([char[]]@(92,47))
  $artifact=[IO.Path]::GetFullPath([string]$package.artifact_run_dir).TrimEnd([char[]]@(92,47))
  if($full.Equals($execution,[StringComparison]::OrdinalIgnoreCase)){return $artifact}
  if($full.StartsWith($execution+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)){return $artifact+$full.Substring($execution.Length)}
  $full
}
function Invoke-Simion([string]$Stage,[string[]]$Arguments){
  $output=& $simion @Arguments 2>&1
  $text=($output|Out-String)
  [IO.File]::WriteAllText((Join-Path $logDir "$Stage.log"),$text,[Text.UTF8Encoding]::new($false))
  if($text){Write-Host $text.TrimEnd()}
  if($LASTEXITCODE-ne0){throw "SIMION stage failed: $Stage"}
}

try{
  foreach($binding in @(
    @($exactK,'exact-K',''),@($workbench,'local workbench','analyzer_local_replacement_workbench'),
    @($prewarm,'mirror-only prewarm','local_operating_pa_cache_prewarm')
  )+$(if($useRealField){@(@($realFieldL1,'real-field L1 refinement','real_3d_mirror_l1_continuous_refinement'),@($axisResponse,'axis response basis','real_3d_mirror_l0_voltage_family'))}else{@()})
  ){
    $manifest=Join-Path $binding[0] 'run_manifest.json'
    $arguments=@($manifest,'--require-status','success','--require-project',$projectId)
    if($binding[2]){$arguments+=@('--require-mode',$binding[2])}
    $verifyArguments=@((Join-Path $repoRoot 'common\contracts\verify_run_manifest.py'))+$arguments
    Invoke-ProjectPython -Arguments $verifyArguments
  }
  $prewarmConfig=Get-Content -Raw (Join-Path $prewarm 'run_config.json')|ConvertFrom-Json -Depth 30
  if(@($prewarmConfig.parameters.target_voltage_vector_v).Count-ne4-or
     @($prewarmConfig.parameters.target_voltage_vector_v|Where-Object{[math]::Abs([double]$_)-gt1e-15}).Count-ne0){
    throw 'Mirror-only prewarm must bind S1=S2=P1=P2=0 V.'
  }
  $failureStage='capacity_startup'
  $startup=Invoke-ArtifactCapacityGate -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot `
    -ProtectedPaths @($package.artifact_run_dir,$exactK,$workbench,$prewarm) -RequiredHeadroomBytes 4500000000
  $startupPath=Join-Path $resultDir 'artifact_capacity_gate_startup.json';Write-RunJson -Path $startupPath -Depth 14 -Value $startup
  $failureStage='freeze_inputs'
  $exactManifest=Copy-VerifiedRunInput -Source (Join-Path $exactK 'run_manifest.json') -Destination (Join-Path $inputDir 'exact_k_run_manifest.json')
  $workbenchManifest=Copy-VerifiedRunInput -Source (Join-Path $workbench 'run_manifest.json') -Destination (Join-Path $inputDir 'local_workbench_run_manifest.json')
  $prewarmManifest=Copy-VerifiedRunInput -Source (Join-Path $prewarm 'run_manifest.json') -Destination (Join-Path $inputDir 'mirror_only_prewarm_run_manifest.json')
  $probeContract=Join-Path $resultDir 'mirror_period_probe_contract.json'
  $sourceFly2=Join-Path $solverDir 'mirror_period_source.fly2'
  $selectionReceipt=$null
  if($useRealField){
    $selectionReceipt=Join-Path $resultDir 'fixed_grid_validation_selection.json'
    Invoke-ProjectPython -Arguments @('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_real_field_l1_refine','select-fixed-grid',
      '--refinement',(Join-Path $realFieldL1 'results\real_3d_mirror_l1_continuous_refinement.json'),'--contract',(Join-Path $repoRoot "projects\$projectId\config\simion_candidate_two_zone.json"),'--output',$selectionReceipt)
    Invoke-ProjectPython -Arguments @('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_real_field_period','prepare-real-field',
      '--refinement-run',$realFieldL1,'--axis-response-run',$axisResponse,'--selection-receipt',$selectionReceipt,
      '--probe-y-mm',([string]::Format([Globalization.CultureInfo]::InvariantCulture,'{0:R}',$ProbeYmm)),
      '--contract-output',$probeContract,'--fly2-output',$sourceFly2)
  }else{
    Invoke-ProjectPython -Arguments @('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_real_field_period','prepare',
      '--exact-k-run',$exactK,'--probe-y-mm',([string]::Format([Globalization.CultureInfo]::InvariantCulture,'{0:R}',$ProbeYmm)),
      '--contract-output',$probeContract,'--fly2-output',$sourceFly2)
  }
  $contract=Get-Content -Raw $probeContract|ConvertFrom-Json -Depth 30
  $probeSidecar=Join-Path $solverDir 'mirror_period_probe.lua'
  $entries=@($contract.particles|ForEach-Object{'  [{0}]={1:R}'-f[int]$_.particle_id,[double]$_.target_energy_ev})
  [IO.File]::WriteAllText($probeSidecar,"return {`n"+($entries-join",`n")+"`n}`n",[Text.UTF8Encoding]::new($false))

  $failureStage='materialize_mirror_only_field'
  $lease=Enter-HostExecutionLease -Role SIMION -Stage prepare -RunId $RunId
  $cacheRoot=Join-Path $artifactRoot 'common\simion\pa_family_cache'
  $identity=Join-Path $prewarm 'results\local_operating_pa_cache_identity.json'
  $localDir=Join-Path $solverDir 'local';New-Item -ItemType Directory -Path $localDir -Force|Out-Null
  $materializeText=@(Invoke-ProjectPython -Arguments @('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.local_operating_pa_cache',
    '--action','materialize','--identity-input',$identity,'--cache-root',$cacheRoot,'--destination-directory',$localDir))-join"`n"
  $materializeReceipt=Join-Path $resultDir 'mirror_only_local_materialization.json'
  [IO.File]::WriteAllText($materializeReceipt,$materializeText+"`n",[Text.UTF8Encoding]::new($false))
  $localNames=@('local_negative_mirror.pa','local_negative_bridge.pa','local_central.pa','local_positive_bridge.pa','local_positive_mirror.pa')
  $localPaths=@()
  for($index=0;$index-lt5;$index++){
    $source=Join-Path $localDir $localNames[$index]
    $target=Join-Path $localDir ('iob_input_local_{0}.pa'-f($index+1))
    Move-Item -LiteralPath $source -Destination $target
    [IO.File]::SetAttributes($target,[IO.File]::GetAttributes($target)-bor[IO.FileAttributes]::ReadOnly)
    $localGuards+=,[IO.File]::Open($target,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
    $localPaths+=$target
  }
  $workbenchConfig=Get-Content -Raw (Join-Path $workbench 'run_config.json')|ConvertFrom-Json -Depth 50
  $paDir=Join-Path $solverDir 'pa';New-Item -ItemType Directory -Path $paDir -Force|Out-Null
  $global=New-ShortPaCopy -Source ([string]$workbenchConfig.inputs.global_analyzer_pa) -Destination (Join-Path $paDir 'iob_input_analyzer.pa') -MarkDestinationReadOnly
  $accelerator=New-ShortPaCopy -Source ([string]$workbenchConfig.inputs.accelerator_pa) -Destination (Join-Path $paDir 'iob_input_accelerator.pa') -MarkDestinationReadOnly
  $detector=New-ShortPaCopy -Source ([string]$workbenchConfig.inputs.detector_pa) -Destination (Join-Path $paDir 'iob_input_detector.pa') -MarkDestinationReadOnly
  $shortCopies=@($global,$accelerator,$detector)

  $seedRoot=Join-Path $repoRoot 'common\simion\assets\iob_instance_seeds'
  $seed=Join-Path $solverDir '8_instance_seed.iob';Copy-Item (Join-Path $seedRoot '8_instance_seed.iob') $seed
  foreach($index in 1..8){Copy-Item (Join-Path $seedRoot ('iob_seed_placeholder_{0:D2}.pa0'-f$index)) (Join-Path $solverDir ('iob_seed_placeholder_{0:D2}.pa0'-f$index))}
  $program=Join-Path $repoRoot 'projects\parallel_mirror_dual_stripe_mr_tof\simion\mrtof_mirror_period_validation.lua'
  $builder=Join-Path $repoRoot 'projects\parallel_mirror_dual_stripe_mr_tof\simion\build_mirror_period_iob.lua'
  $launcher=Join-Path $repoRoot 'projects\parallel_mirror_dual_stripe_mr_tof\simion\run_mirror_period_iob.lua'
  $localConfig=Join-Path $workbench 'simion\local_refinement.input.lua'
  $plan=Get-Content -Raw (Join-Path $workbench 'results\current_analyzer_local_refinement_plan.json')|ConvertFrom-Json -Depth 30
  $pose=Get-Content -Raw (Join-Path $workbench 'results\resolved_iob_pose.json')|ConvertFrom-Json -Depth 10
  $globalOrigin=@([double]$pose.origins_mm.analyzer[0],[double]$pose.origins_mm.analyzer[1],[double]$pose.origins_mm.analyzer[2])
  $patchOrigins=@(
    @([double]$plan.patches.mirror_turn_negative[0],[double]$plan.patches.mirror_turn_negative[1],[double]$plan.patches.mirror_turn_negative[2]),
    @([double]$plan.patches.stripe_mirror_bridge_negative[0],[double]$plan.patches.stripe_mirror_bridge_negative[1],[double]$plan.patches.stripe_mirror_bridge_negative[2]),
    @([double]$plan.patches.central_transport[0],[double]$plan.patches.central_transport[1],[double]$plan.patches.central_transport[2]),
    @([double]$plan.patches.stripe_mirror_bridge_positive[0],[double]$plan.patches.stripe_mirror_bridge_positive[1],[double]$plan.patches.stripe_mirror_bridge_positive[2]),
    @([double]$plan.patches.mirror_turn_positive[0],[double]$plan.patches.mirror_turn_positive[1],[double]$plan.patches.mirror_turn_positive[2])
  )
  $acceleratorOrigin=@([double]$pose.origins_mm.accelerator[0],[double]$pose.origins_mm.accelerator[1],[double]$pose.origins_mm.accelerator[2])
  $detectorOrigin=@([double]$pose.origins_mm.detector[0],[double]$pose.origins_mm.detector[1],[double]$pose.origins_mm.detector[2])
  $origins=@($globalOrigin)+$patchOrigins+@($acceleratorOrigin,$detectorOrigin)
  $iob=Join-Path $solverDir 'mirror_period.iob'
  $builderArgs=@('--nogui','--noprompt','lua',$builder,$seed,$global)+$localPaths+@($accelerator,$detector,$iob,$program,$sourceFly2,$localConfig)
  foreach($origin in $origins){foreach($value in $origin){$builderArgs+=[string]::Format([Globalization.CultureInfo]::InvariantCulture,'{0:R}',[double]$value)}}
  $builderArgs+=$probeSidecar
  Invoke-Simion -Stage 'build_mirror_period_iob' -Arguments $builderArgs
  foreach($copy in $shortCopies){Protect-ShortPaCopyDestination -Path $copy|Out-Null}
  $flightLog=Join-Path $logDir 'mirror_period_flight.log'
  $flightOutput=& $simion --nogui --noprompt lua $launcher $iob 2>&1
  $flightText=($flightOutput|Out-String);[IO.File]::WriteAllText($flightLog,$flightText,[Text.UTF8Encoding]::new($false))
  if($flightText){Write-Host $flightText.TrimEnd()};if($LASTEXITCODE-ne0){throw 'SIMION mirror period flight failed.'}
  Exit-HostExecutionLease -Lease $lease -Outcome success -RunId $RunId;$lease=$null

  $failureStage='analyze'
  $analysis=Join-Path $resultDir 'mirror_real_field_period_comparison.json'
  Invoke-ProjectPython -Arguments @('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_real_field_period','analyze',
    '--contract',$probeContract,'--log',$flightLog,'--output',$analysis)
  $comparison=Get-Content -Raw $analysis|ConvertFrom-Json -Depth 30
  Write-RunJson -Path $summary -Depth 20 -Value ([ordered]@{
    schema_version=1;role='mrtof_bare_mirror_real_field_period_validation';status='success';
    qualification=[string]$comparison.qualification;probe_y_mm=[double]$comparison.probe_y_mm;
    energy_centers_ev=@($comparison.energy_centers_ev);theory_normalized_period_slopes_per_v=@($comparison.theory_normalized_period_slopes_per_v);
    simion_normalized_period_slopes_per_v=@($comparison.simion_normalized_period_slopes_per_v);
    center_period_residual_ppm=@($comparison.center_period_residual_ppm)
  })
  $configuration=Get-Content -Raw $runConfig|ConvertFrom-Json -AsHashtable
  $configuration.inputs=[ordered]@{exact_k_run_manifest=$exactManifest;local_workbench_run_manifest=$workbenchManifest;mirror_only_prewarm_run_manifest=$prewarmManifest;real_field_l1_manifest=if($useRealField){Join-Path $realFieldL1 'run_manifest.json'}else{$null};axis_response_manifest=if($useRealField){Join-Path $axisResponse 'run_manifest.json'}else{$null};fixed_grid_selection_receipt=$selectionReceipt}
  $configuration.parameters=[ordered]@{probe_y_mm=$ProbeYmm;particle_count=@($contract.particles).Count;stripe_biases_v=@(0.0,0.0);prism_voltages_v=@(0.0,0.0);mirror_voltage_source=if($useRealField){'selected_real_field_l1_root'}else{'exact_k_analytic_2d'};trajectory_quality=8.0;maximum_step_us=0.00002;lifecycle_stage='terminal'}
  Write-RunJson -Path $runConfig -Depth 20 -Value $configuration
  foreach($guard in $localGuards){$guard.Dispose()}
  $localGuards=@()
  foreach($copy in $shortCopies){Remove-ShortPaCopy -Path $copy}
  $shortCopies=@()
  $retention=Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $runConfig
  $terminal=Invoke-ArtifactCapacityGate -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot -ProtectedPaths @($package.artifact_run_dir,$exactK,$workbench,$prewarm)
  $terminalPath=Join-Path $resultDir 'artifact_capacity_gate_terminal.json';Write-RunJson -Path $terminalPath -Depth 14 -Value $terminal
  $outputs=@($summary,$probeContract,$materializeReceipt,$analysis,$flightLog,$startupPath,$terminalPath,$retention)+$(if($selectionReceipt){@($selectionReceipt)}else{@()})|ForEach-Object{ConvertTo-ArtifactRunPath $_}
  Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Status success -Software @('SIMION 2020','Python 3.11') -Outputs $outputs|Out-Null
  $terminalized=$true;$hostOutcome='success'
  Write-Host "MRTOF_MIRROR_REAL_FIELD_PERIOD=PASS RUN_ID=$RunId"
}catch{
  $failure=$_
  if($null-ne$lease){Exit-HostExecutionLease -Lease $lease -Outcome $hostOutcome -RunId $RunId;$lease=$null}
  foreach($guard in $localGuards){try{$guard.Dispose()}catch{}}
  $localGuards=@()
  foreach($copy in $shortCopies){try{Remove-ShortPaCopy -Path $copy}catch{}}
  $shortCopies=@()
  if(Test-Path -LiteralPath $solverDir){Get-ChildItem -LiteralPath $solverDir -Recurse -File -ErrorAction SilentlyContinue|ForEach-Object{try{[IO.File]::SetAttributes($_.FullName,[IO.FileAttributes]::Normal)}catch{}};Remove-Item -LiteralPath $solverDir -Recurse -Force}
  if(-not$terminalized){Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Summary $summary -SummaryRole 'mrtof_bare_mirror_real_field_period_validation' -Reason $failure.Exception.Message -Software @('SIMION 2020','Python 3.11') -FailureStage $failureStage;$terminalized=$true}
  throw
}finally{
  if($null-ne$lease){Exit-HostExecutionLease -Lease $lease -Outcome $hostOutcome -RunId $RunId}
  foreach($guard in $localGuards){try{$guard.Dispose()}catch{}}
  foreach($copy in $shortCopies){try{Remove-ShortPaCopy -Path $copy}catch{}}
  if(Test-Path -LiteralPath $solverDir){Get-ChildItem -LiteralPath $solverDir -Recurse -File -ErrorAction SilentlyContinue|ForEach-Object{try{[IO.File]::SetAttributes($_.FullName,[IO.FileAttributes]::Normal)}catch{}};Remove-Item -LiteralPath $solverDir -Recurse -Force}
  Remove-RunPackageExecutionAlias -Package $package
}

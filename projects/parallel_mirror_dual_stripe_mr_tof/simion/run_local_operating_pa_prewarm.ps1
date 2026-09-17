[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$LocalWorkbenchRunPath,
  [Parameter(Mandatory)][double]$Stripe1VoltageV,
  [Parameter(Mandatory)][double]$Stripe2VoltageV,
  [Parameter(Mandatory)][double]$Prism1VoltageV,
  [Parameter(Mandatory)][double]$Prism2VoltageV,
  [Nullable[double]]$MirrorBVoltageV=$null,
  [Nullable[double]]$MirrorCVoltageV=$null,
  [Nullable[double]]$MirrorDVoltageV=$null,
  [Nullable[double]]$MirrorEVoltageV=$null,
  [string]$RunId='',
  [string]$SimionExe='',
  [string]$PythonExe=''
)

Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'

function Format-InvariantNumber([double]$Value){
  [string]::Format([Globalization.CultureInfo]::InvariantCulture,'{0:R}',$Value)
}
function Invoke-ProjectPython([string[]]$Arguments){
  Push-Location -LiteralPath $repoRoot
  try{
    $saved=$env:PYTHONPATH;$env:PYTHONPATH=$repoRoot
    & $python @Arguments
    if($LASTEXITCODE-ne0){throw "Python command failed: $($Arguments-join' ')"}
  }finally{$env:PYTHONPATH=$saved;Pop-Location}
}
function Start-LaneBatch([object[]]$Plans){
  $records=@()
  try{
    foreach($plan in $Plans){
      $stdout=Join-Path $logDir ("lane_{0}.stdout.log"-f$plan.label)
      $stderr=Join-Path $logDir ("lane_{0}.stderr.log"-f$plan.label)
      $process=Start-Process -FilePath $pwshExe -ArgumentList @(
        '-NoLogo','-NoProfile','-NonInteractive','-File',$laneScript,'-PlanPath',$plan.path
      ) -WorkingDirectory $solverDir -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput $stdout -RedirectStandardError $stderr
      $records+=,[pscustomobject]@{process=$process;label=$plan.label;stdout=$stdout;stderr=$stderr}
    }
    foreach($record in $records){
      $record.process.WaitForExit()
      if($record.process.ExitCode-ne0){
        $detail=if(Test-Path -LiteralPath $record.stderr){Get-Content -Raw -LiteralPath $record.stderr}else{''}
        throw "Local operating PA lane failed: $($record.label): $detail"
      }
    }
  }catch{
    foreach($record in $records){try{if(-not$record.process.HasExited){$record.process.Kill($true)}}catch{}}
    throw
  }finally{foreach($record in $records){try{$record.process.Dispose()}catch{}}}
}

$projectId='parallel_mirror_dual_stripe_mr_tof'
$repoRoot=(Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$workspaceRoot=Split-Path -Parent $repoRoot
$python=if($PythonExe){[IO.Path]::GetFullPath($PythonExe)}else{Join-Path $repoRoot '.venv\Scripts\python.exe'}
$simion=if($SimionExe){[IO.Path]::GetFullPath($SimionExe)}else{Join-Path $env:ProgramFiles 'SIMION-2020\simion.exe'}
foreach($path in @($python,$simion)){if(-not(Test-Path -LiteralPath $path -PathType Leaf)){throw "Executable is missing: $path"}}
$localWorkbench=(Resolve-Path -LiteralPath $LocalWorkbenchRunPath).Path
$localWorkbenchManifest=Join-Path $localWorkbench 'run_manifest.json'
& $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') $localWorkbenchManifest `
  --require-status success --require-project $projectId --require-mode analyzer_local_replacement_workbench
if($LASTEXITCODE-ne0){throw 'Local workbench manifest verification failed.'}
if([string]::IsNullOrWhiteSpace($RunId)){$RunId=(Get-Date -Format 'yyyyMMdd_HHmmss')+'__build__simion__mrtof-local-operating-pa-prewarm'}

. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')
. (Join-Path $repoRoot 'common\host_execution_lease.ps1')
$pwshExe=(Get-Process -Id $PID).Path
$artifactRoot=Join-Path $workspaceRoot 'artifacts'
$cacheRoot=Join-Path $artifactRoot 'common\simion\pa_family_cache'
$package=New-RunPackage -Python $python -RepoRoot $repoRoot `
  -ArtifactRoot (Join-Path $artifactRoot "projects\$projectId") -RunId $RunId `
  -Project $projectId -Mode 'local_operating_pa_cache_prewarm' -Software @('SIMION 2020','Python 3.11') `
  -RetentionContractEnabled -RetentionClass compact -AdditionalDirectories @('simion') -UseShortExecutionPath
$runDir=$package.run_dir;$inputDir=$package.input_dir;$resultDir=$package.result_dir
$logDir=$package.log_dir;$solverDir=Join-Path $runDir 'simion';$runConfig=$package.run_config;$summary=$package.summary

function ConvertTo-ArtifactRunPath {
  param([Parameter(Mandatory)][string]$Path)
  $full=[IO.Path]::GetFullPath($Path)
  $executionRoot=[IO.Path]::GetFullPath([string]$package.run_dir).TrimEnd([char[]]@(92,47))
  $artifactRunRoot=[IO.Path]::GetFullPath([string]$package.artifact_run_dir).TrimEnd([char[]]@(92,47))
  if($full.Equals($executionRoot,[StringComparison]::OrdinalIgnoreCase)){return $artifactRunRoot}
  if($full.StartsWith($executionRoot+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)){
    return $artifactRunRoot+$full.Substring($executionRoot.Length)
  }
  return $full
}

$terminalized=$false;$lease=$null;$hostOutcome='failed';$failureStage='compile_identity';$staging=$null
$identityPath=Join-Path $resultDir 'local_operating_pa_cache_identity.json'
$sourcePlanPath=Join-Path $resultDir 'local_operating_pa_lane_sources.json'
$initialProbePath=Join-Path $resultDir 'local_operating_pa_cache_initial_probe.json'
$finalProbePath=Join-Path $resultDir 'local_operating_pa_cache_final_probe.json'
$cacheResultPath=Join-Path $resultDir 'local_operating_pa_cache_result.json'
$startupPath=Join-Path $resultDir 'artifact_capacity_gate_startup.json'
$terminalPath=Join-Path $resultDir 'artifact_capacity_gate_terminal.json'
  $lanePlans=@()
  $publication=$null
try{
  $mirrorValues=@($MirrorBVoltageV,$MirrorCVoltageV,$MirrorDVoltageV,$MirrorEVoltageV)
  $mirrorValueCount=@($mirrorValues|Where-Object{$null-ne$_}).Count
  if($mirrorValueCount-notin@(0,4)){throw 'Mirror B--E voltages must be supplied together or omitted together.'}
  $targetText=@($Stripe1VoltageV,$Stripe2VoltageV,$Prism1VoltageV,$Prism2VoltageV)|ForEach-Object{Format-InvariantNumber $_}
  $targetText=$targetText-join','
  $planArguments=@(
    '-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.local_operating_pa_cache',
    '--action','plan','--local-workbench-run',$localWorkbench,"--target-voltages-v=$targetText",
    '--cache-root',$cacheRoot,'--identity-output',$identityPath,'--plan-output',$sourcePlanPath
  )
  if($mirrorValueCount-eq4){
    $mirrorText=(@($mirrorValues)|ForEach-Object{Format-InvariantNumber ([double]$_)})-join','
    $planArguments+="--target-mirror-voltages-v=$mirrorText"
  }
  Invoke-ProjectPython -Arguments $planArguments|Out-Null
  $probe=(@(Invoke-ProjectPython -Arguments @(
    '-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.local_operating_pa_cache',
    '--action','probe','--identity-input',$identityPath,'--cache-root',$cacheRoot
  ))-join"`n")|ConvertFrom-Json
  Write-RunJson -Path $initialProbePath -Depth 10 -Value $probe
  if($probe.disposition-eq'corrupt'){throw "Local operating PA cache is corrupt: $($probe.detail)"}
  if($probe.disposition-notin@('hit','miss')){throw "Unsupported local operating PA cache disposition: $($probe.disposition)"}
  $cacheKey=[string]$probe.cache_key
  $sourcePlan=Get-Content -Raw -LiteralPath $sourcePlanPath|ConvertFrom-Json -Depth 30
  if($sourcePlan.role-ne'mrtof_local_operating_pa_lane_plan'-or@($sourcePlan.lanes).Count-ne5){throw 'Local operating PA plan must contain exactly five lanes.'}
  $expectedNames=@('local_negative_mirror.pa','local_negative_bridge.pa','local_central.pa','local_positive_bridge.pa','local_positive_mirror.pa')
  if(Compare-Object -ReferenceObject $expectedNames -DifferenceObject @($sourcePlan.lanes.output_name)){throw 'Local operating PA plan output names differ from the five cache members.'}
  $sourceFamilyCacheKeys=@($sourcePlan.lanes|ForEach-Object{[string]$_.source_family_cache_key}|Select-Object -Unique)
  if($sourceFamilyCacheKeys.Count-ne5-or@($sourceFamilyCacheKeys|Where-Object{$_-notmatch'^[0-9A-Fa-f]{64}$'}).Count-ne0){
    throw 'Local operating PA plan must bind five distinct canonical source-family cache keys.'
  }
  $protectedCacheKeys=@($cacheKey)+$sourceFamilyCacheKeys
  [int64]$projectedBytes=0
  foreach($lane in @($sourcePlan.lanes)){$projectedBytes+=[int64](Get-Item -LiteralPath ([string]$lane.base_source)).Length}
  $startup=Invoke-ArtifactCapacityGate -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot `
    -RequiredHeadroomBytes $(if($probe.disposition-eq'miss'){2*$projectedBytes}else{0}) `
    -ProtectedPaths @($package.artifact_run_dir,$localWorkbench) -ProtectedCacheKeys $protectedCacheKeys
  Write-RunJson -Path $startupPath -Depth 14 -Value $startup
  $laneScript=Join-Path $PSScriptRoot 'compose_local_operating_pa_lane.ps1'
  $composeLua=Join-Path $repoRoot 'common\simion\compose_standalone_pa.lua'
  $shortSupport=Join-Path $repoRoot 'common\simion\short_pa_path_support.ps1'
  $lease=Enter-HostExecutionLease -Role SIMION -Stage prepare -RunId $RunId
  if($probe.disposition-eq'miss'){
    $failureStage='compose_five_local_operating_pas'
    $staging=Join-Path ([IO.Path]::GetTempPath()) ('mrtof_local_operating_prewarm_'+[guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $staging|Out-Null
    foreach($lane in @($sourcePlan.lanes)){
      $planPath=Join-Path $resultDir ("composition_lane_{0}.json"-f$lane.label)
      $plan=[ordered]@{
        schema_version=1;label=[string]$lane.label;simion_exe=$simion;solver_dir=$solverDir;
        short_pa_support=$shortSupport;compose_lua=$composeLua;output_pa=Join-Path $staging ([string]$lane.output_name);
        base_mode=[string]$lane.base_mode;base_source=[string]$lane.base_source;responses=@($lane.responses)
      }
      Write-RunJson -Path $planPath -Depth 15 -Value $plan
      $lanePlans+=,[pscustomobject]@{label=[string]$lane.label;path=$planPath}
    }
    Start-LaneBatch -Plans $lanePlans
    foreach($name in $expectedNames){
      if(-not(Test-Path -LiteralPath (Join-Path $staging $name) -PathType Leaf)){
        throw "Composition did not create cache member: $name"
      }
    }
    $failureStage='publish_complete_local_operating_pa_group'
    $publication=(@(Invoke-ProjectPython -Arguments @(
      '-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.local_operating_pa_cache',
      '--action','publish','--identity-input',$identityPath,'--cache-root',$cacheRoot,'--source-directory',$staging
    ))-join"`n")|ConvertFrom-Json
    if([string]$publication.cache_key-ne$cacheKey){throw 'Published local operating PA cache key differs from the probed identity.'}
  }
  $failureStage='verify_published_cache_hit'
  $finalProbe=(@(Invoke-ProjectPython -Arguments @(
    '-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.local_operating_pa_cache',
    '--action','probe','--identity-input',$identityPath,'--cache-root',$cacheRoot
  ))-join"`n")|ConvertFrom-Json
  Write-RunJson -Path $finalProbePath -Depth 10 -Value $finalProbe
  if($finalProbe.disposition-ne'hit'-or[string]$finalProbe.cache_key-ne$cacheKey){throw 'Local operating PA cache did not verify as an exact hit after prewarm.'}
  Write-RunJson -Path $cacheResultPath -Depth 12 -Value ([ordered]@{
    initial_probe=$probe
    publication=$publication
    final_probe=$finalProbe
  })
  $configuration=Get-Content -Raw -LiteralPath $runConfig|ConvertFrom-Json -AsHashtable
  $configuration.inputs=[ordered]@{
    local_workbench_run_manifest=$localWorkbenchManifest
    cache_adapter_implementation=Join-Path $repoRoot 'projects\parallel_mirror_dual_stripe_mr_tof\analysis\local_operating_pa_cache.py'
    lane_implementation=$laneScript
    composer_implementation=$composeLua
  }
  $configuration.parameters=[ordered]@{
    target_voltage_vector_v=@($Stripe1VoltageV,$Stripe2VoltageV,$Prism1VoltageV,$Prism2VoltageV)
    target_mirror_voltage_vector_v=$(if($mirrorValueCount-eq4){@($mirrorValues|ForEach-Object{[double]$_})}else{$null})
    initial_disposition=[string]$probe.disposition
    composition_lane_count=$lanePlans.Count
    cache_key=$cacheKey
    source_family_cache_keys=$sourceFamilyCacheKeys
    identity_output=ConvertTo-ArtifactRunPath $identityPath
    lane_source_plan_output=ConvertTo-ArtifactRunPath $sourcePlanPath
    lifecycle_stage='terminal'
  }
  Write-RunJson -Path $runConfig -Depth 20 -Value $configuration
  Write-RunJson -Path $summary -Depth 15 -Value ([ordered]@{
    schema_version=1;role='mrtof_local_operating_pa_cache_prewarm';status='success';
    initial_disposition=[string]$probe.disposition;final_disposition='hit';cache_key=$cacheKey;
    composition_lane_count=$lanePlans.Count;generation_directory=[string]$finalProbe.generation_directory;
    qualification='execution_cache_only__no_physics_or_flight_claim'
  })
  $retention=Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $runConfig
  $terminal=Invoke-ArtifactCapacityGate -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot `
    -ProtectedPaths @($package.artifact_run_dir,$localWorkbench) -ProtectedCacheKeys $protectedCacheKeys
  Write-RunJson -Path $terminalPath -Depth 14 -Value $terminal
  $lanePlanPaths=@($lanePlans|ForEach-Object{[string]$_.path})
  $outputs=@($summary,$identityPath,$sourcePlanPath,$initialProbePath,$finalProbePath,$cacheResultPath,$startupPath,$terminalPath,$retention)+$lanePlanPaths
  $outputs=@($outputs|ForEach-Object{ConvertTo-ArtifactRunPath ([string]$_)})
  Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Status success `
    -Software @('SIMION 2020','Python 3.11') -Outputs $outputs|Out-Null
  $terminalized=$true;$hostOutcome='success'
  Write-Host "MRTOF_LOCAL_OPERATING_PA_PREWARM=PASS RUN_ID=$RunId CACHE_KEY=$cacheKey DISPOSITION=$($probe.disposition)"
}catch{
  if(-not$terminalized){Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Summary $summary `
    -SummaryRole 'mrtof_local_operating_pa_cache_prewarm' -Reason $_.Exception.Message `
    -Software @('SIMION 2020','Python 3.11') -FailureStage $failureStage;$terminalized=$true}
  throw
}finally{
  if($null-ne$lease){Exit-HostExecutionLease -Lease $lease -Outcome $hostOutcome -RunId $RunId}
  if($null-ne$staging-and(Test-Path -LiteralPath $staging)){Remove-Item -LiteralPath $staging -Recurse -Force}
  Remove-RunPackageExecutionAlias -Package $package
}

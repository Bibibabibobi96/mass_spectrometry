[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$L0FamilyRunPath,
  [Parameter(Mandatory)][string]$L0ResponseBasisRunPath,
  [Parameter(Mandatory)][string]$LocalWorkbenchRunPath,
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
if([string]::IsNullOrWhiteSpace($RunId)){$RunId=(Get-Date -Format 'yyyyMMdd_HHmmss')+'__analysis__simion__mrtof-real-field-mirror-l1-screen'}

. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')
. (Join-Path $repoRoot 'common\host_execution_lease.ps1')
. (Join-Path $repoRoot 'common\simion\short_pa_path_support.ps1')
$artifactRoot=Join-Path $workspaceRoot 'artifacts'
$cacheRoot=Join-Path $artifactRoot 'common\simion\pa_family_cache'
$contractSource=Join-Path $repoRoot "projects\$projectId\config\simion_candidate_two_zone.json"
$samplerSource=Join-Path $PSScriptRoot 'sample_mirror_l1_response_slice.lua'
$package=New-RunPackage -Python $python -RepoRoot $repoRoot `
  -ArtifactRoot (Join-Path $artifactRoot "projects\$projectId") -RunId $RunId `
  -Project $projectId -Mode 'real_3d_mirror_l1_response_screen' `
  -Software @('SIMION 2020','Python 3.11') -RetentionContractEnabled `
  -RetentionClass qualification `
  -RetentionReason 'Read-only 0.5-mm real-3-D mirror L1 response screen and member selection evidence.' `
  -AdditionalDirectories @('simion') -UseShortExecutionPath
$runDir=$package.run_dir;$inputDir=$package.input_dir;$resultDir=$package.result_dir
$solverDir=Join-Path $runDir 'simion';$runConfig=$package.run_config;$summary=$package.summary
$terminalized=$false;$lease=$null;$failureStage='preflight';$hostOutcome='failed';$shortCopies=@()

function Invoke-ProjectPython([string[]]$Arguments){
  Push-Location -LiteralPath $repoRoot;$saved=$env:PYTHONPATH
  try{$env:PYTHONPATH=$repoRoot;& $python @Arguments;if($LASTEXITCODE-ne0){throw "Python failed: $($Arguments-join' ')"}}
  finally{$env:PYTHONPATH=$saved;Pop-Location}
}
function ArtifactPath([string]$Path){
  $full=[IO.Path]::GetFullPath($Path);$exec=[IO.Path]::GetFullPath([string]$package.run_dir).TrimEnd([char[]]@(92,47));$artifact=[IO.Path]::GetFullPath([string]$package.artifact_run_dir).TrimEnd([char[]]@(92,47))
  if($full.StartsWith($exec,[StringComparison]::OrdinalIgnoreCase)){return $artifact+$full.Substring($exec.Length)}
  $full
}
function Remove-RegionCopies {
  foreach($copy in @($script:shortCopies)){try{Remove-ShortPaCopy -Path $copy}catch{}}
  $script:shortCopies=@()
}

try{
  $familyRun=(Resolve-Path -LiteralPath $L0FamilyRunPath).Path
  $basisRun=(Resolve-Path -LiteralPath $L0ResponseBasisRunPath).Path
  $workbench=(Resolve-Path -LiteralPath $LocalWorkbenchRunPath).Path
  foreach($binding in @(@($familyRun,'real_3d_mirror_l0_voltage_family'),@($basisRun,'real_3d_mirror_l0_voltage_family'),@($workbench,'analyzer_local_replacement_workbench'))){
    Invoke-ProjectPython -Arguments @(
      (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py'),
      (Join-Path $binding[0] 'run_manifest.json'),'--require-status','success',
      '--require-project',$projectId,'--require-mode',$binding[1]
    )
  }
  $failureStage='capacity_startup'
  $protectedPaths=@($package.artifact_run_dir,$familyRun,$basisRun,$workbench)
  $startup=Invoke-ArtifactCapacityGate -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot `
    -ProtectedPaths $protectedPaths -RequiredHeadroomBytes 3500000000
  $startupPath=Join-Path $resultDir 'artifact_capacity_gate_startup.json';Write-RunJson -Path $startupPath -Depth 14 -Value $startup
  $failureStage='freeze_inputs'
  $familyManifest=Copy-VerifiedRunInput -Source (Join-Path $familyRun 'run_manifest.json') -Destination (Join-Path $inputDir 'l0_family_run_manifest.json')
  $basisManifest=Copy-VerifiedRunInput -Source (Join-Path $basisRun 'run_manifest.json') -Destination (Join-Path $inputDir 'l0_response_basis_run_manifest.json')
  $workbenchManifest=Copy-VerifiedRunInput -Source (Join-Path $workbench 'run_manifest.json') -Destination (Join-Path $inputDir 'local_workbench_run_manifest.json')
  $frozenContract=Copy-VerifiedRunInput -Source $contractSource -Destination (Join-Path $inputDir 'simion_candidate_two_zone.json')
  $frozenSampler=Copy-VerifiedRunInput -Source $samplerSource -Destination (Join-Path $inputDir 'sample_mirror_l1_response_slice.lua')
  $familySource=Join-Path $familyRun 'results\real_3d_mirror_l0_voltage_family.json'
  if(-not(Test-Path -LiteralPath $familySource -PathType Leaf)){throw "L0 family result is missing: $familySource"}
  $frozenFamily=Copy-VerifiedRunInput -Source $familySource -Destination (Join-Path $inputDir 'real_3d_mirror_l0_voltage_family.json')
  $failureStage='prepare_read_only_response_plan'
  $planPath=Join-Path $resultDir 'mirror_l1_response_sampling_plan.json'
  Invoke-ProjectPython -Arguments @(
    '-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_real_field_l1_workflow','prepare',
    '--local-workbench-run',$workbench,'--l0-response-basis-run',$basisRun,
    '--cache-root',$cacheRoot,'--contract',$frozenContract,'--output',$planPath
  )
  $plan=Get-Content -Raw -LiteralPath $planPath|ConvertFrom-Json -Depth 30
  $protectedCacheKeys=@($plan.regions|ForEach-Object{[string]$_.cache_key}|Select-Object -Unique)
  $failureStage='sample_real_3d_response_slices'
  $lease=Enter-HostExecutionLease -Role SIMION -Stage mirror_l1_response_sampling -RunId $RunId
  $regionCsvs=@()
  for($regionIndex=0;$regionIndex-lt@($plan.regions).Count;$regionIndex++){
    $region=@($plan.regions)[$regionIndex]
    $regionId=[string]$region.region_id
    $privateDir=Join-Path $solverDir ("r{0:D2}"-f($regionIndex+1));New-Item -ItemType Directory -Path $privateDir -Force|Out-Null
    $responsePaths=@()
    for($responseIndex=0;$responseIndex-lt@($region.responses).Count;$responseIndex++){
      $response=@($region.responses)[$responseIndex]
      $copy=New-ShortPaCopy -Source ([string]$response.source_pa) `
        -Destination (Join-Path $privateDir ("response_{0}.pa"-f([string]$response.group))) `
        -ExpectedBytes ([int64]$response.source_pa_bytes) -MarkDestinationReadOnly
      $script:shortCopies+=$copy;$responsePaths+=$copy
    }
    $specPath=Join-Path $privateDir 'spec.lua'
    $specArguments=@(
      '-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_real_field_l1_workflow','spec',
      '--plan',$planPath,'--region',$regionId,'--output',$specPath
    )
    foreach($responsePath in $responsePaths){$specArguments+=@('--response-pa',$responsePath)}
    Invoke-ProjectPython -Arguments $specArguments
    $csvPath=Join-Path $resultDir ("mirror_l1_response_{0}.csv"-f$regionId)
    & $simion --nogui --noprompt lua $frozenSampler $specPath $csvPath
    if($LASTEXITCODE-ne0){throw "SIMION L1 response sampling failed: $regionId"}
    $regionCsvs+=$csvPath
    Remove-RegionCopies
    Remove-Item -LiteralPath $privateDir -Recurse -Force
  }
  Exit-HostExecutionLease -Lease $lease -Outcome success -RunId $RunId;$lease=$null
  $failureStage='merge_response_basis'
  $basisPath=Join-Path $resultDir 'real_3d_mirror_l1_response_basis.csv'
  $mergeArguments=@(
    '-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_real_field_l1_workflow','merge',
    '--plan',$planPath,'--output',$basisPath
  )
  foreach($csvPath in $regionCsvs){$mergeArguments+=@('--region-csv',$csvPath)}
  Invoke-ProjectPython -Arguments $mergeArguments
  $failureStage='screen_real_3d_l1_family'
  $screenPath=Join-Path $resultDir 'real_3d_mirror_l1_screen.json'
  $lease=Enter-HostExecutionLease -Role GATE -Stage theory_compute -RunId $RunId
  Invoke-ProjectPython -Arguments @(
    '-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_real_field_l1_workflow','analyze',
    '--plan',$planPath,'--basis',$basisPath,'--family',$frozenFamily,
    '--contract',$frozenContract,'--output',$screenPath
  )
  Exit-HostExecutionLease -Lease $lease -Outcome success -RunId $RunId;$lease=$null
  $screen=Get-Content -Raw -LiteralPath $screenPath|ConvertFrom-Json -Depth 100
  Write-RunJson -Path $summary -Depth 20 -Value ([ordered]@{
    schema_version=1;role='mrtof_real_3d_mirror_l1_response_screen';status='success';
    scientific_status=[string]$screen.ranking.status;qualification=[string]$screen.qualification;
    screened_member_count=@($screen.members).Count;
    selected_source_member_indices=@($screen.ranking.selected_source_member_indices);
    primary_member_index=$screen.ranking.primary_member_index;
    native_simion_validation_pending=$true
  })
  $configuration=Get-Content -Raw $runConfig|ConvertFrom-Json -AsHashtable
  $configuration.inputs=[ordered]@{
    l0_family_run_manifest=$familyManifest;l0_response_basis_run_manifest=$basisManifest;
    local_workbench_run_manifest=$workbenchManifest;baseline_contract=(ArtifactPath $frozenContract);
    l0_family_result=(ArtifactPath $frozenFamily);sampler_implementation=(ArtifactPath $frozenSampler)
  }
  $configuration.parameters=[ordered]@{
    sample_step_mm=[double]$plan.sample_step_mm;slice_y_mm=[double]$plan.slice_y_mm;
    x_range_mm=@($plan.x_range_mm);z_range_mm=@($plan.z_range_mm);
    region_count=@($plan.regions).Count;response_group_count=4;
    protected_cache_keys=$protectedCacheKeys;lifecycle_stage='terminal'
  }
  Write-RunJson -Path $runConfig -Depth 30 -Value $configuration
  $retention=Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $runConfig
  $terminal=Invoke-ArtifactCapacityGate -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot `
    -ProtectedPaths $protectedPaths -ProtectedCacheKeys $protectedCacheKeys
  $terminalPath=Join-Path $resultDir 'artifact_capacity_gate_terminal.json';Write-RunJson -Path $terminalPath -Depth 14 -Value $terminal
  $outputs=@($summary,$planPath,$basisPath,$screenPath,$startupPath,$terminalPath,$retention)+$regionCsvs
  $outputs=@($outputs|ForEach-Object{ArtifactPath $_})
  Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Status success `
    -Software @('SIMION 2020','Python 3.11') -Outputs $outputs|Out-Null
  $terminalized=$true;$hostOutcome='success'
  Write-Host "MRTOF_REAL_FIELD_MIRROR_L1_SCREEN=PASS RUN_ID=$RunId SELECTED=$(@($screen.ranking.selected_source_member_indices)-join',')"
}catch{
  $failure=$_
  Remove-RegionCopies
  if($null-ne$lease){Exit-HostExecutionLease -Lease $lease -Outcome failed -RunId $RunId;$lease=$null}
  if(-not$terminalized){Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Summary $summary -SummaryRole 'mrtof_real_3d_mirror_l1_response_screen' -Reason $failure.Exception.Message -Software @('SIMION 2020','Python 3.11') -FailureStage $failureStage;$terminalized=$true}
  throw
}finally{
  Remove-RegionCopies
  if($null-ne$lease){Exit-HostExecutionLease -Lease $lease -Outcome $hostOutcome -RunId $RunId}
  if(Test-Path -LiteralPath $solverDir){Get-ChildItem -LiteralPath $solverDir -Recurse -File -ErrorAction SilentlyContinue|ForEach-Object{try{[IO.File]::SetAttributes($_.FullName,[IO.FileAttributes]::Normal)}catch{}};Remove-Item -LiteralPath $solverDir -Recurse -Force}
  Remove-RunPackageExecutionAlias -Package $package
}

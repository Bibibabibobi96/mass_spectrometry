[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$ExactKRunPath,
  [string]$LocalWorkbenchRunPath='',
  [string]$ResponseBasisRunPath='',
  [string]$BaselinePeriodRunPath='',
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
$reuseBasis=-not[string]::IsNullOrWhiteSpace($ResponseBasisRunPath)
if($reuseBasis -eq (-not[string]::IsNullOrWhiteSpace($LocalWorkbenchRunPath))){throw 'Specify exactly one of LocalWorkbenchRunPath or ResponseBasisRunPath.'}
foreach($path in @($python)+$(if($reuseBasis){@()}else{@($simion)})){if(-not(Test-Path -LiteralPath $path -PathType Leaf)){throw "Executable is missing: $path"}}
if([string]::IsNullOrWhiteSpace($RunId)){$RunId=(Get-Date -Format 'yyyyMMdd_HHmmss')+'__analysis__simion__mrtof-real-field-mirror-l0-family'}

. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')
. (Join-Path $repoRoot 'common\host_execution_lease.ps1')
. (Join-Path $repoRoot 'common\simion\short_pa_path_support.ps1')
$artifactRoot=Join-Path $workspaceRoot 'artifacts'
$cacheRoot=Join-Path $artifactRoot 'common\simion\pa_family_cache'
$contractSource=Join-Path $repoRoot "projects\$projectId\config\simion_candidate_two_zone.json"
$package=New-RunPackage -Python $python -RepoRoot $repoRoot `
  -ArtifactRoot (Join-Path $artifactRoot "projects\$projectId") -RunId $RunId `
  -Project $projectId -Mode 'real_3d_mirror_l0_voltage_family' `
  -Software $(if($reuseBasis){@('Python 3.11')}else{@('SIMION 2020','Python 3.11')}) `
  -RetentionContractEnabled -RetentionClass qualification `
  -RetentionReason 'Real-3-D mirror response basis or derived voltage-family qualification evidence.' `
  -AdditionalDirectories @('simion') -UseShortExecutionPath
$runDir=$package.run_dir;$inputDir=$package.input_dir;$resultDir=$package.result_dir
$solverDir=Join-Path $runDir 'simion';$runConfig=$package.run_config;$summary=$package.summary
$terminalized=$false;$lease=$null;$failureStage='preflight';$hostOutcome='failed';$activeCopy=$null

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
function Invariant([double]$Value){[string]::Format([Globalization.CultureInfo]::InvariantCulture,'{0:R}',$Value)}

try{
  $exactK=(Resolve-Path -LiteralPath $ExactKRunPath).Path
  if($reuseBasis){
    $basisRun=(Resolve-Path -LiteralPath $ResponseBasisRunPath).Path
    foreach($binding in @(@($exactK,''),@($basisRun,'real_3d_mirror_l0_voltage_family'))){
      $arguments=@((Join-Path $repoRoot 'common\contracts\verify_run_manifest.py'),(Join-Path $binding[0] 'run_manifest.json'),'--require-status','success','--require-project',$projectId)
      if($binding[1]){$arguments+=@('--require-mode',$binding[1])}
      Invoke-ProjectPython -Arguments $arguments
    }
    $failureStage='capacity_startup'
    $protectedPaths=@($package.artifact_run_dir,$exactK,$basisRun)
    $startup=Invoke-ArtifactCapacityGate -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot `
      -ProtectedPaths $protectedPaths -RequiredHeadroomBytes 100000000
    $startupPath=Join-Path $resultDir 'artifact_capacity_gate_startup.json';Write-RunJson -Path $startupPath -Depth 14 -Value $startup
    $failureStage='freeze_inputs'
    $exactManifest=Copy-VerifiedRunInput -Source (Join-Path $exactK 'run_manifest.json') -Destination (Join-Path $inputDir 'exact_k_run_manifest.json')
    $basisManifest=Copy-VerifiedRunInput -Source (Join-Path $basisRun 'run_manifest.json') -Destination (Join-Path $inputDir 'response_basis_run_manifest.json')
    $frozenContract=Copy-VerifiedRunInput -Source $contractSource -Destination (Join-Path $inputDir 'simion_candidate_two_zone.json')
    $failureStage='solve_reused_real_field_l0_family'
    $familyPath=Join-Path $resultDir 'real_3d_mirror_l0_voltage_family.json'
    Invoke-ProjectPython -Arguments @(
      '-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_real_field_voltage_family','reuse',
      '--basis-run',$basisRun,'--exact-k-run',$exactK,'--contract',$frozenContract,'--output',$familyPath
    )
    $family=Get-Content -Raw -LiteralPath $familyPath|ConvertFrom-Json -Depth 40
    Write-RunJson -Path $summary -Depth 20 -Value ([ordered]@{
      schema_version=1;role='mrtof_real_3d_mirror_l0_voltage_family';status='success';
      scientific_status=[string]$family.status;qualification=[string]$family.qualification;
      feasible_member_count=[int]$family.feasible_member_count;member_count=[int]$family.member_count;
      energy_centers_ev=@($family.energy_centers_ev);voltage_bounds_v=$family.voltage_bounds_v;
      axis_period_authority=[string]$family.axis_period_authority;
      axis_basis_schema_version=[int]$family.axis_basis_schema_version;
      uniform_e_slice_count=[int]$family.uniform_e_slice_count;
      actual_e_slice_count=[int]$family.actual_e_slice_count;
      inserted_seed_e_voltage_v=[double]$family.inserted_seed_e_voltage_v;
      response_basis_reused=$true;source_response_basis_run_id=[string]$family.source_response_basis_run_id
    })
    $configuration=Get-Content -Raw $runConfig|ConvertFrom-Json -AsHashtable
    $configuration.inputs=[ordered]@{exact_k_run_manifest=$exactManifest;response_basis_run_manifest=$basisManifest;baseline_contract=(ArtifactPath $frozenContract)}
    $configuration.parameters=[ordered]@{
      response_basis_reused=$true;axis_period_authority=[string]$family.axis_period_authority;
      axis_basis_schema_version=[int]$family.axis_basis_schema_version;
      actual_e_slice_count=[int]$family.actual_e_slice_count;lifecycle_stage='terminal'
    }
    Write-RunJson -Path $runConfig -Depth 20 -Value $configuration
    $retention=Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $runConfig
    $terminal=Invoke-ArtifactCapacityGate -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot -ProtectedPaths $protectedPaths
    $terminalPath=Join-Path $resultDir 'artifact_capacity_gate_terminal.json';Write-RunJson -Path $terminalPath -Depth 14 -Value $terminal
    $outputs=@($summary,$familyPath,$startupPath,$terminalPath,$retention)|ForEach-Object{ArtifactPath $_}
    Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Status success -Software @('Python 3.11') -Outputs $outputs|Out-Null
    $terminalized=$true;$hostOutcome='success'
    Write-Host "MRTOF_REAL_FIELD_MIRROR_L0_FAMILY_REUSE=PASS RUN_ID=$RunId FEASIBLE=$($family.feasible_member_count)"
    return
  }
  $workbench=(Resolve-Path -LiteralPath $LocalWorkbenchRunPath).Path
  $baselinePeriod=if($BaselinePeriodRunPath){(Resolve-Path -LiteralPath $BaselinePeriodRunPath).Path}else{$null}
  $bindings=@(@($exactK,''),@($workbench,'analyzer_local_replacement_workbench'))
  if($baselinePeriod){$bindings+=,@($baselinePeriod,'bare_mirror_real_field_period_validation')}
  foreach($binding in $bindings){
    $arguments=@((Join-Path $repoRoot 'common\contracts\verify_run_manifest.py'),(Join-Path $binding[0] 'run_manifest.json'),'--require-status','success','--require-project',$projectId)
    if($binding[1]){$arguments+=@('--require-mode',$binding[1])}
    Invoke-ProjectPython -Arguments $arguments
  }
  $failureStage='capacity_startup'
  $protectedPaths=@($package.artifact_run_dir,$exactK,$workbench)
  if($baselinePeriod){$protectedPaths+=$baselinePeriod}
  $startup=Invoke-ArtifactCapacityGate -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot `
    -ProtectedPaths $protectedPaths -RequiredHeadroomBytes 1000000000
  $startupPath=Join-Path $resultDir 'artifact_capacity_gate_startup.json';Write-RunJson -Path $startupPath -Depth 14 -Value $startup
  $failureStage='freeze_inputs'
  $exactManifest=Copy-VerifiedRunInput -Source (Join-Path $exactK 'run_manifest.json') -Destination (Join-Path $inputDir 'exact_k_run_manifest.json')
  $workbenchManifest=Copy-VerifiedRunInput -Source (Join-Path $workbench 'run_manifest.json') -Destination (Join-Path $inputDir 'local_workbench_run_manifest.json')
  $frozenContract=Copy-VerifiedRunInput -Source $contractSource -Destination (Join-Path $inputDir 'simion_candidate_two_zone.json')
  $baselinePeriodManifest=if($baselinePeriod){Copy-VerifiedRunInput -Source (Join-Path $baselinePeriod 'run_manifest.json') -Destination (Join-Path $inputDir 'baseline_period_run_manifest.json')}else{$null}
  $samplingDir=Join-Path $solverDir 'sampling';New-Item -ItemType Directory -Path $samplingDir -Force|Out-Null
  Invoke-ProjectPython -Arguments @(
    '-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_real_field_voltage_family','prepare',
    '--local-workbench-run',$workbench,'--exact-k-run',$exactK,'--cache-root',$cacheRoot,
    '--contract',$frozenContract,'--output-directory',$samplingDir
  )
  $planPath=Join-Path $samplingDir 'mirror_response_sampling_plan.json'
  $plan=Get-Content -Raw -LiteralPath $planPath|ConvertFrom-Json -Depth 30
  $protectedCacheKeys=@($plan.regions|ForEach-Object{[string]$_.cache_key}|Select-Object -Unique)
  $failureStage='sample_verified_standalone_responses'
  $lease=Enter-HostExecutionLease -Role SIMION -Stage mirror_field_sampling -RunId $RunId
  $compare=Join-Path $repoRoot 'common\simion\compare_pa_fields_at_samples.lua'
  $shortDir=Join-Path $solverDir 'pa';New-Item -ItemType Directory -Path $shortDir -Force|Out-Null
  $index=0
  foreach($region in @($plan.regions)){
    $origin=(@($region.origin_project_mm)|ForEach-Object{Invariant ([double]$_)})-join','
    foreach($response in @($region.responses)){
      $index++
      $activeCopy=New-ShortPaCopy -Source ([string]$response.source_pa) -Destination (Join-Path $shortDir ("response_{0:D2}.pa"-f$index)) -MarkDestinationReadOnly
      & $simion --nogui --noprompt lua $compare $activeCopy $origin $activeCopy $origin identity identity `
        ([string]$region.sample_csv) ([string]$response.comparison_csv)
      if($LASTEXITCODE-ne0){throw "SIMION response sampling failed: $($region.region)/$($response.group)"}
      Protect-ShortPaCopyDestination -Path $activeCopy|Out-Null
      Remove-ShortPaCopy -Path $activeCopy;$activeCopy=$null
    }
  }
  Exit-HostExecutionLease -Lease $lease -Outcome success -RunId $RunId;$lease=$null
  $failureStage='solve_real_field_l0_family'
  $familyPath=Join-Path $resultDir 'real_3d_mirror_l0_voltage_family.json'
  $analyzeArguments=@(
    '-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_real_field_voltage_family','analyze',
    '--plan',$planPath,'--output',$familyPath
  )
  if($baselinePeriod){$analyzeArguments+=@('--native-period-run',$baselinePeriod)}
  Invoke-ProjectPython -Arguments $analyzeArguments
  $family=Get-Content -Raw -LiteralPath $familyPath|ConvertFrom-Json -Depth 40
  $publishedPlan=Join-Path $resultDir 'mirror_response_sampling_receipt.json'
  $receipt=[ordered]@{
    schema_version=1;role=[string]$plan.role;status='sampled';qualification=[string]$plan.qualification;
    probe_y_mm=[double]$plan.probe_y_mm;sample_step_mm=[double]$plan.sample_step_mm;
    basis_normalization_v=[double]$plan.basis_normalization_v;energy_centers_ev=@($plan.energy_centers_ev);
    period_slope_derivative_step_ev=[double]$plan.period_slope_derivative_step_ev;
    maximum_abs_normalized_period_slope_per_v=[double]$plan.maximum_abs_normalized_period_slope_per_v;
    axis_basis_schema_version=[int]$plan.axis_basis_schema_version;
    axis_period_authority=[string]$plan.axis_period_authority;
    sampled_axis_quantities=@($plan.sampled_axis_quantities);
    source_contract_sha256=[string]$plan.source_contract_sha256;
    cache_generations=@($plan.regions|ForEach-Object{[ordered]@{region=[string]$_.region;cache_key=[string]$_.cache_key;generation_sha256=[string]$_.generation_sha256;sample_count=[int]$_.sample_count}})
  }
  Write-RunJson -Path $publishedPlan -Depth 12 -Value $receipt
  Write-RunJson -Path $summary -Depth 20 -Value ([ordered]@{
    schema_version=1;role='mrtof_real_3d_mirror_l0_voltage_family';status='success';
    scientific_status=[string]$family.status;qualification=[string]$family.qualification;
    feasible_member_count=[int]$family.feasible_member_count;member_count=[int]$family.member_count;
    energy_centers_ev=@($family.energy_centers_ev);voltage_bounds_v=$family.voltage_bounds_v;
    axis_period_authority=[string]$family.axis_period_authority;
    axis_basis_schema_version=[int]$family.axis_basis_schema_version;
    uniform_e_slice_count=[int]$family.uniform_e_slice_count;
    actual_e_slice_count=[int]$family.actual_e_slice_count;
    inserted_seed_e_voltage_v=[double]$family.inserted_seed_e_voltage_v
  })
  $configuration=Get-Content -Raw $runConfig|ConvertFrom-Json -AsHashtable
  $configuration.inputs=[ordered]@{exact_k_run_manifest=$exactManifest;local_workbench_run_manifest=$workbenchManifest;baseline_contract=(ArtifactPath $frozenContract)}
  if($baselinePeriodManifest){$configuration.inputs.baseline_period_run_manifest=$baselinePeriodManifest}
  $configuration.parameters=[ordered]@{
    probe_y_mm=[double]$plan.probe_y_mm;sample_step_mm=[double]$plan.sample_step_mm;
    response_group_count=4;region_count=5;protected_cache_keys=$protectedCacheKeys;
    axis_period_authority=[string]$family.axis_period_authority;
    axis_basis_schema_version=[int]$family.axis_basis_schema_version;
    actual_e_slice_count=[int]$family.actual_e_slice_count;lifecycle_stage='terminal'
  }
  Write-RunJson -Path $runConfig -Depth 20 -Value $configuration
  $basisPath=Join-Path $resultDir 'real_3d_mirror_axis_response_basis.csv'
  $retention=Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $runConfig
  $terminal=Invoke-ArtifactCapacityGate -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot -ProtectedPaths $protectedPaths -ProtectedCacheKeys $protectedCacheKeys
  $terminalPath=Join-Path $resultDir 'artifact_capacity_gate_terminal.json';Write-RunJson -Path $terminalPath -Depth 14 -Value $terminal
  $outputs=@($summary,$familyPath,$basisPath,$publishedPlan,$startupPath,$terminalPath,$retention)|ForEach-Object{ArtifactPath $_}
  Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Status success -Software @('SIMION 2020','Python 3.11') -Outputs $outputs|Out-Null
  $terminalized=$true;$hostOutcome='success'
  Write-Host "MRTOF_REAL_FIELD_MIRROR_L0_FAMILY=PASS RUN_ID=$RunId FEASIBLE=$($family.feasible_member_count)"
}catch{
  $failure=$_
  if($activeCopy){try{Remove-ShortPaCopy -Path $activeCopy}catch{};$activeCopy=$null}
  if($null-ne$lease){Exit-HostExecutionLease -Lease $lease -Outcome failed -RunId $RunId;$lease=$null}
  if(-not$terminalized){Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Summary $summary -SummaryRole 'mrtof_real_3d_mirror_l0_voltage_family' -Reason $failure.Exception.Message -Software $(if($reuseBasis){@('Python 3.11')}else{@('SIMION 2020','Python 3.11')}) -FailureStage $failureStage;$terminalized=$true}
  throw
}finally{
  if($activeCopy){try{Remove-ShortPaCopy -Path $activeCopy}catch{}}
  if($null-ne$lease){Exit-HostExecutionLease -Lease $lease -Outcome $hostOutcome -RunId $RunId}
  if(Test-Path -LiteralPath $solverDir){Get-ChildItem -LiteralPath $solverDir -Recurse -File -ErrorAction SilentlyContinue|ForEach-Object{try{[IO.File]::SetAttributes($_.FullName,[IO.FileAttributes]::Normal)}catch{}};Remove-Item -LiteralPath $solverDir -Recurse -Force}
  Remove-RunPackageExecutionAlias -Package $package
}

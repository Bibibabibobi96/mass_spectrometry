[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$L0FamilyRunPath,
  [Parameter(Mandatory)][string]$AxisResponseRunPath,
  [Parameter(Mandatory)][string]$DiscreteL1ScreenRunPath,
  [string]$RunId='',
  [string]$PythonExe=''
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$projectId='parallel_mirror_dual_stripe_mr_tof'
$repoRoot=(Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$workspaceRoot=Split-Path -Parent $repoRoot
$python=if($PythonExe){[IO.Path]::GetFullPath($PythonExe)}else{Join-Path $repoRoot '.venv\Scripts\python.exe'}
if(-not(Test-Path -LiteralPath $python -PathType Leaf)){throw "Python is missing: $python"}
if([string]::IsNullOrWhiteSpace($RunId)){
  $RunId=(Get-Date -Format 'yyyyMMdd_HHmmss')+'__analysis__python__mrtof-real-field-mirror-l1-continuous-refinement'
}

. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')
. (Join-Path $repoRoot 'common\host_execution_lease.ps1')
$artifactRoot=Join-Path $workspaceRoot 'artifacts'
$contractSource=Join-Path $repoRoot "projects\$projectId\config\simion_candidate_two_zone.json"
$package=New-RunPackage -Python $python -RepoRoot $repoRoot `
  -ArtifactRoot (Join-Path $artifactRoot "projects\$projectId") -RunId $RunId `
  -Project $projectId -Mode 'real_3d_mirror_l1_continuous_refinement' `
  -Software @('Python 3.11') -RetentionContractEnabled -RetentionClass qualification `
  -RetentionReason 'Continuous gamma-root refinement on the frozen 0.5-mm real-3-D mirror response basis.'
$runDir=$package.run_dir;$inputDir=$package.input_dir;$resultDir=$package.result_dir
$runConfig=$package.run_config;$summary=$package.summary
$terminalized=$false;$lease=$null;$failureStage='preflight';$hostOutcome='failed'

function Invoke-ProjectPython([string[]]$Arguments){
  Push-Location -LiteralPath $repoRoot;$saved=$env:PYTHONPATH
  try{
    $env:PYTHONPATH=$repoRoot
    & $python @Arguments
    if($LASTEXITCODE-ne0){throw "Python failed: $($Arguments-join' ')"}
  }finally{$env:PYTHONPATH=$saved;Pop-Location}
}
function ArtifactPath([string]$Path){
  $full=[IO.Path]::GetFullPath($Path)
  $exec=[IO.Path]::GetFullPath([string]$package.run_dir).TrimEnd([char[]]@(92,47))
  $artifact=[IO.Path]::GetFullPath([string]$package.artifact_run_dir).TrimEnd([char[]]@(92,47))
  if($full.StartsWith($exec,[StringComparison]::OrdinalIgnoreCase)){
    return $artifact+$full.Substring($exec.Length)
  }
  $full
}

try{
  $familyRun=(Resolve-Path -LiteralPath $L0FamilyRunPath).Path
  $axisRun=(Resolve-Path -LiteralPath $AxisResponseRunPath).Path
  $screenRun=(Resolve-Path -LiteralPath $DiscreteL1ScreenRunPath).Path
  foreach($sourceRun in @($familyRun,$axisRun,$screenRun)){
    Invoke-ProjectPython -Arguments @(
      (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py'),
      (Join-Path $sourceRun 'run_manifest.json'),'--require-status','success',
      '--require-project',$projectId
    )
  }
  $familySource=Join-Path $familyRun 'results\real_3d_mirror_l0_voltage_family.json'
  $axisSource=Join-Path $axisRun 'results\real_3d_mirror_axis_response_basis.csv'
  $screenSource=Join-Path $screenRun 'results\real_3d_mirror_l1_screen.json'
  $planSource=Join-Path $screenRun 'inputs\mirror_l1_response_sampling_plan.json'
  $basisSource=Join-Path $screenRun 'inputs\real_3d_mirror_l1_response_basis.csv'
  foreach($source in @($familySource,$axisSource,$screenSource,$planSource,$basisSource)){
    if(-not(Test-Path -LiteralPath $source -PathType Leaf)){throw "Required input is missing: $source"}
  }
  $failureStage='capacity_startup'
  $protectedPaths=@($package.artifact_run_dir,$familyRun,$axisRun,$screenRun)
  $startup=Invoke-ArtifactCapacityGate -Python $python -RepoRoot $repoRoot `
    -ArtifactRoot $artifactRoot -ProtectedPaths $protectedPaths -RequiredHeadroomBytes 1000000000
  $startupPath=Join-Path $resultDir 'artifact_capacity_gate_startup.json'
  Write-RunJson -Path $startupPath -Depth 14 -Value $startup
  $failureStage='freeze_inputs'
  $familyManifest=Copy-VerifiedRunInput -Source (Join-Path $familyRun 'run_manifest.json') -Destination (Join-Path $inputDir 'l0_family_run_manifest.json')
  $axisManifest=Copy-VerifiedRunInput -Source (Join-Path $axisRun 'run_manifest.json') -Destination (Join-Path $inputDir 'axis_response_run_manifest.json')
  $screenManifest=Copy-VerifiedRunInput -Source (Join-Path $screenRun 'run_manifest.json') -Destination (Join-Path $inputDir 'discrete_l1_screen_run_manifest.json')
  $contract=Copy-VerifiedRunInput -Source $contractSource -Destination (Join-Path $inputDir 'simion_candidate_two_zone.json')
  $family=Copy-VerifiedRunInput -Source $familySource -Destination (Join-Path $inputDir 'real_3d_mirror_l0_voltage_family.json')
  $axis=Copy-VerifiedRunInput -Source $axisSource -Destination (Join-Path $inputDir 'real_3d_mirror_axis_response_basis.csv')
  $screen=Copy-VerifiedRunInput -Source $screenSource -Destination (Join-Path $inputDir 'real_3d_mirror_l1_discrete_screen.json')
  $plan=Copy-VerifiedRunInput -Source $planSource -Destination (Join-Path $inputDir 'mirror_l1_response_sampling_plan.json')
  $basis=Copy-VerifiedRunInput -Source $basisSource -Destination (Join-Path $inputDir 'real_3d_mirror_l1_response_basis.csv')
  $failureStage='continuous_gamma_root_refinement'
  $output=Join-Path $resultDir 'real_3d_mirror_l1_continuous_refinement.json'
  $lease=Enter-HostExecutionLease -Role GATE -Stage theory_compute -RunId $RunId
  Invoke-ProjectPython -Arguments @(
    '-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_real_field_l1_refine',
    '--family',$family,'--discrete-screen',$screen,'--axis-basis',$axis,
    '--response-basis',$basis,'--sampling-plan',$plan,'--contract',$contract,'--output',$output,
    '--checkpoint-directory',$resultDir
  )
  Exit-HostExecutionLease -Lease $lease -Outcome success -RunId $RunId;$lease=$null
  $result=Get-Content -Raw -LiteralPath $output|ConvertFrom-Json -Depth 100
  Write-RunJson -Path $summary -Depth 20 -Value ([ordered]@{
    schema_version=1;role='mrtof_real_3d_mirror_l1_continuous_refinement';status='success';
    scientific_status=[string]$result.status;qualification=[string]$result.qualification;
    bracket_count=[int]$result.bracket_count;root_count=@($result.roots).Count;
    feasible_root_count=@($result.roots|Where-Object{$_.l0_feasible}).Count;
    selected_source_member_indices=@($result.full_root_screen.ranking.selected_source_member_indices);
    fixed_0p25mm_validation_root_indices=@($result.fixed_0p25mm_validation_candidates.selected_root_indices);
    fixed_candidate_0p25mm_validation_pending=$true
  })
  $configuration=Get-Content -Raw $runConfig|ConvertFrom-Json -AsHashtable
  $configuration.inputs=[ordered]@{
    l0_family_run_manifest=$familyManifest;axis_response_run_manifest=$axisManifest;
    discrete_l1_screen_run_manifest=$screenManifest;baseline_contract=(ArtifactPath $contract);
    l0_family=(ArtifactPath $family);axis_response_basis=(ArtifactPath $axis);
    discrete_l1_screen=(ArtifactPath $screen);response_sampling_plan=(ArtifactPath $plan);
    transverse_response_basis=(ArtifactPath $basis)
  }
  $configuration.parameters=[ordered]@{
    geometry_changed=$false;pa_refined=$false;response_basis_reused=$true;
    lifecycle_stage='terminal'
  }
  Write-RunJson -Path $runConfig -Depth 30 -Value $configuration
  $retention=Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $runConfig
  $terminal=Invoke-ArtifactCapacityGate -Python $python -RepoRoot $repoRoot `
    -ArtifactRoot $artifactRoot -ProtectedPaths $protectedPaths
  $terminalPath=Join-Path $resultDir 'artifact_capacity_gate_terminal.json'
  Write-RunJson -Path $terminalPath -Depth 14 -Value $terminal
  $checkpoints=@(Get-ChildItem -LiteralPath $resultDir -File -Filter 'root_*.checkpoint.json'|ForEach-Object{$_.FullName})
  $outputs=@($summary,$output,$startupPath,$terminalPath,$retention)+$checkpoints
  $outputs=@($outputs|ForEach-Object{ArtifactPath $_})
  Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $runConfig `
    -Status success -Software @('Python 3.11') -Outputs $outputs|Out-Null
  $terminalized=$true;$hostOutcome='success'
  Write-Host "MRTOF_REAL_FIELD_MIRROR_L1_REFINE=PASS RUN_ID=$RunId ROOTS=$(@($result.roots).Count)"
}catch{
  $failure=$_
  if($null-ne$lease){Exit-HostExecutionLease -Lease $lease -Outcome failed -RunId $RunId;$lease=$null}
  if(-not$terminalized){
    Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Summary $summary `
      -SummaryRole 'mrtof_real_3d_mirror_l1_continuous_refinement' -Reason $failure.Exception.Message `
      -Software @('Python 3.11') -FailureStage $failureStage
    $terminalized=$true
  }
  throw
}finally{
  if($null-ne$lease){Exit-HostExecutionLease -Lease $lease -Outcome $hostOutcome -RunId $RunId}
}

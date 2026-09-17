[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$L0FamilyRunPath,
  [Parameter(Mandatory)][string]$SampledResponseRunPath,
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
if([string]::IsNullOrWhiteSpace($RunId)){$RunId=(Get-Date -Format 'yyyyMMdd_HHmmss')+'__analysis__python__mrtof-real-field-mirror-l1-screen-reuse'}

. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')
. (Join-Path $repoRoot 'common\host_execution_lease.ps1')
$artifactRoot=Join-Path $workspaceRoot 'artifacts'
$contractSource=Join-Path $repoRoot "projects\$projectId\config\simion_candidate_two_zone.json"
$package=New-RunPackage -Python $python -RepoRoot $repoRoot `
  -ArtifactRoot (Join-Path $artifactRoot "projects\$projectId") -RunId $RunId `
  -Project $projectId -Mode 'real_3d_mirror_l1_response_screen' `
  -Software @('Python 3.11') -RetentionContractEnabled -RetentionClass qualification `
  -RetentionReason 'Revalidated sampled 0.5-mm real-3-D mirror L1 basis and parallel member screen.'
$runDir=$package.run_dir;$inputDir=$package.input_dir;$resultDir=$package.result_dir
$runConfig=$package.run_config;$summary=$package.summary
$terminalized=$false;$lease=$null;$failureStage='preflight';$hostOutcome='failed'

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

try{
  $familyRun=(Resolve-Path -LiteralPath $L0FamilyRunPath).Path
  $sampledRun=(Resolve-Path -LiteralPath $SampledResponseRunPath).Path
  Invoke-ProjectPython -Arguments @(
    (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py'),
    (Join-Path $familyRun 'run_manifest.json'),'--require-status','success',
    '--require-project',$projectId,'--require-mode','real_3d_mirror_l0_voltage_family'
  )
  $sampledManifest=Get-Content -Raw -LiteralPath (Join-Path $sampledRun 'run_manifest.json')|ConvertFrom-Json
  if([string]$sampledManifest.project-ne$projectId-or[string]$sampledManifest.mode-ne'real_3d_mirror_l1_response_screen'-or@('checkpoint','success')-notcontains[string]$sampledManifest.status){
    throw 'Sampled response run identity is invalid.'
  }
  $sourcePlan=Join-Path $sampledRun 'results\mirror_l1_response_sampling_plan.json'
  $sourceBasis=Join-Path $sampledRun 'results\real_3d_mirror_l1_response_basis.csv'
  $familySource=Join-Path $familyRun 'results\real_3d_mirror_l0_voltage_family.json'
  foreach($source in @($sourcePlan,$sourceBasis,$familySource)){if(-not(Test-Path -LiteralPath $source -PathType Leaf)){throw "Required input is missing: $source"}}
  $failureStage='capacity_startup'
  $protectedPaths=@($package.artifact_run_dir,$familyRun,$sampledRun)
  $startup=Invoke-ArtifactCapacityGate -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot -ProtectedPaths $protectedPaths -RequiredHeadroomBytes 1000000000
  $startupPath=Join-Path $resultDir 'artifact_capacity_gate_startup.json';Write-RunJson -Path $startupPath -Depth 14 -Value $startup
  $failureStage='freeze_and_revalidate_inputs'
  $familyManifest=Copy-VerifiedRunInput -Source (Join-Path $familyRun 'run_manifest.json') -Destination (Join-Path $inputDir 'l0_family_run_manifest.json')
  $sourceManifest=Copy-VerifiedRunInput -Source (Join-Path $sampledRun 'run_manifest.json') -Destination (Join-Path $inputDir 'sampled_response_run_manifest.json')
  $frozenContract=Copy-VerifiedRunInput -Source $contractSource -Destination (Join-Path $inputDir 'simion_candidate_two_zone.json')
  $frozenFamily=Copy-VerifiedRunInput -Source $familySource -Destination (Join-Path $inputDir 'real_3d_mirror_l0_voltage_family.json')
  $frozenPlan=Copy-VerifiedRunInput -Source $sourcePlan -Destination (Join-Path $inputDir 'mirror_l1_response_sampling_plan.json')
  $frozenBasis=Copy-VerifiedRunInput -Source $sourceBasis -Destination (Join-Path $inputDir 'real_3d_mirror_l1_response_basis.csv')
  $failureStage='parallel_screen_real_3d_l1_family'
  $screenPath=Join-Path $resultDir 'real_3d_mirror_l1_screen.json'
  $lease=Enter-HostExecutionLease -Role GATE -Stage theory_compute -RunId $RunId
  Invoke-ProjectPython -Arguments @(
    '-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_real_field_l1_workflow','analyze',
    '--plan',$frozenPlan,'--basis',$frozenBasis,'--family',$frozenFamily,
    '--contract',$frozenContract,'--output',$screenPath
  )
  Exit-HostExecutionLease -Lease $lease -Outcome success -RunId $RunId;$lease=$null
  $screen=Get-Content -Raw -LiteralPath $screenPath|ConvertFrom-Json -Depth 100
  Write-RunJson -Path $summary -Depth 20 -Value ([ordered]@{
    schema_version=1;role='mrtof_real_3d_mirror_l1_response_screen';status='success';
    scientific_status=[string]$screen.ranking.status;qualification=[string]$screen.qualification;
    screened_member_count=@($screen.members).Count;actual_parallel_workers=[int]$screen.actual_parallel_workers;
    selected_source_member_indices=@($screen.ranking.selected_source_member_indices);
    primary_member_index=$screen.ranking.primary_member_index;native_simion_validation_pending=$true;
    source_sampled_run_status=[string]$sampledManifest.status;
    source_sampled_basis_revalidated=$true
  })
  $configuration=Get-Content -Raw $runConfig|ConvertFrom-Json -AsHashtable
  $configuration.inputs=[ordered]@{
    l0_family_run_manifest=$familyManifest;sampled_response_run_manifest=$sourceManifest;
    baseline_contract=(ArtifactPath $frozenContract);l0_family_result=(ArtifactPath $frozenFamily);
    response_sampling_plan=(ArtifactPath $frozenPlan);response_basis=(ArtifactPath $frozenBasis)
  }
  $configuration.parameters=[ordered]@{
    response_basis_reused=$true;source_sampled_run_status=[string]$sampledManifest.status;
    source_basis_complete_regular_grid_revalidated=$true;actual_parallel_workers=[int]$screen.actual_parallel_workers;
    lifecycle_stage='terminal'
  }
  Write-RunJson -Path $runConfig -Depth 30 -Value $configuration
  $retention=Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $runConfig
  $terminal=Invoke-ArtifactCapacityGate -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot -ProtectedPaths $protectedPaths
  $terminalPath=Join-Path $resultDir 'artifact_capacity_gate_terminal.json';Write-RunJson -Path $terminalPath -Depth 14 -Value $terminal
  $outputs=@($summary,$screenPath,$startupPath,$terminalPath,$retention)|ForEach-Object{ArtifactPath $_}
  Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Status success -Software @('Python 3.11') -Outputs $outputs|Out-Null
  $terminalized=$true;$hostOutcome='success'
  Write-Host "MRTOF_REAL_FIELD_MIRROR_L1_SCREEN_REUSE=PASS RUN_ID=$RunId WORKERS=$($screen.actual_parallel_workers) SELECTED=$(@($screen.ranking.selected_source_member_indices)-join',')"
}catch{
  $failure=$_
  if($null-ne$lease){Exit-HostExecutionLease -Lease $lease -Outcome failed -RunId $RunId;$lease=$null}
  if(-not$terminalized){Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Summary $summary -SummaryRole 'mrtof_real_3d_mirror_l1_response_screen' -Reason $failure.Exception.Message -Software @('Python 3.11') -FailureStage $failureStage;$terminalized=$true}
  throw
}finally{
  if($null-ne$lease){Exit-HostExecutionLease -Lease $lease -Outcome $hostOutcome -RunId $RunId}
}

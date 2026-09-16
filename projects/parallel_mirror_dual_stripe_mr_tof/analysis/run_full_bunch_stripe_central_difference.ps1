[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$S1MinusRunPath,
  [Parameter(Mandatory)][string]$S1PlusRunPath,
  [Parameter(Mandatory)][string]$S2MinusRunPath,
  [Parameter(Mandatory)][string]$S2PlusRunPath,
  [string]$RunId='',
  [string]$PythonExe=''
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$projectId='parallel_mirror_dual_stripe_mr_tof'
$repoRoot=(Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$workspaceRoot=Split-Path -Parent $repoRoot
$python=if($PythonExe){[IO.Path]::GetFullPath($PythonExe)}else{Join-Path $repoRoot '.venv\Scripts\python.exe'}
if(-not(Test-Path -LiteralPath $python -PathType Leaf)){throw "Python executable is missing: $python"}
$runs=[ordered]@{
  s1_minus=(Resolve-Path -LiteralPath $S1MinusRunPath).Path
  s1_plus=(Resolve-Path -LiteralPath $S1PlusRunPath).Path
  s2_minus=(Resolve-Path -LiteralPath $S2MinusRunPath).Path
  s2_plus=(Resolve-Path -LiteralPath $S2PlusRunPath).Path
}
if([string]::IsNullOrWhiteSpace($RunId)){$RunId='mrtof-full-bunch-stripe-central-difference'}
. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')
$artifactRoot=Join-Path $workspaceRoot "artifacts\projects\$projectId"
$package=New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot `
  -RunId $RunId -Project $projectId -Mode 'full_bunch_stripe_central_difference' `
  -Software @('Python 3.11') -RetentionContractEnabled -RetentionClass compact
$runConfig=$package.run_config;$summary=$package.summary;$resultDir=$package.result_dir
$analysis=Join-Path $resultDir 'full_bunch_stripe_central_difference.json'
$terminalized=$false
try{
  $arguments=@('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.full_bunch_stripe_central_difference')
  foreach($name in @('s1_minus','s1_plus','s2_minus','s2_plus')){
    $option='--'+$name.Replace('_','-')
    $arguments+=@($option,[string]$runs[$name])
  }
  $arguments+=@('--output',$analysis)
  Push-Location $repoRoot;$saved=$env:PYTHONPATH
  try{$env:PYTHONPATH=$repoRoot;& $python @arguments;if($LASTEXITCODE-ne0){throw 'Central-difference analysis failed.'}}
  finally{$env:PYTHONPATH=$saved;Pop-Location}
  $document=Get-Content -Raw -LiteralPath $analysis|ConvertFrom-Json -Depth 30
  $configuration=Get-Content -Raw -LiteralPath $runConfig|ConvertFrom-Json -AsHashtable
  $configuration.inputs=[ordered]@{}
  foreach($name in $runs.Keys){$configuration.inputs[$name+'_run_manifest']=Join-Path $runs[$name] 'run_manifest.json'}
  $configuration.parameters=[ordered]@{
    center_stripe_biases_v=@($document.center_stripe_biases_v)
    central_difference_step_v=[double]$document.central_difference_step_v
    particle_count=100
    qualification=[string]$document.qualification
    lifecycle_stage='terminal'
  }
  Write-RunJson -Path $runConfig -Depth 20 -Value $configuration
  Write-RunJson -Path $summary -Depth 15 -Value ([ordered]@{
    schema_version=1;role='mrtof_full_bunch_stripe_central_difference';status='success'
    center_stripe_biases_v=@($document.center_stripe_biases_v)
    central_difference_step_v=[double]$document.central_difference_step_v
    local_fwhm_descent_unit_direction_dS1_dS2=@($document.local_fwhm_descent_unit_direction_dS1_dS2)
    qualification=[string]$document.qualification
  })
  $retention=Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $runConfig
  Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Status success `
    -Software @('Python 3.11') -Outputs @($summary,$analysis,$retention)|Out-Null
  $terminalized=$true
  Write-Host "MRTOF_FULL_BUNCH_STRIPE_CENTRAL_DIFFERENCE_RUN=PASS RUN_ID=$RunId"
}catch{
  if(-not$terminalized){Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig `
    -Summary $summary -SummaryRole 'mrtof_full_bunch_stripe_central_difference' `
    -Reason $_.Exception.Message -Software @('Python 3.11') -FailureStage 'analyze';$terminalized=$true}
  throw
}

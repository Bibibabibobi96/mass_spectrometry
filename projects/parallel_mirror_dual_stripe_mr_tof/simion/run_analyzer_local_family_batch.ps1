[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$GeometryReviewRunPath,
  [Parameter(Mandatory)][string]$PreparedSourceReceiptPath,
  [Parameter(Mandatory)][ValidateSet('mirror_turn_positive','mirror_turn_negative','central_transport','stripe_mirror_bridge_positive','stripe_mirror_bridge_negative')][string[]]$Region,
  [ValidateSet(1.0,0.5,0.25)][double]$ScaleFactor=0.5,
  [string]$ContractPath='', [string]$RunId='', [string]$SimionExe='', [string]$PythonExe=''
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$repoRoot=(Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$workspaceRoot=Split-Path -Parent $repoRoot
$python=if($PythonExe){[IO.Path]::GetFullPath($PythonExe)}else{Join-Path $repoRoot '.venv\Scripts\python.exe'}
$simion=if($SimionExe){[IO.Path]::GetFullPath($SimionExe)}else{Join-Path $env:ProgramFiles 'SIMION-2020\simion.exe'}
$receipt=(Resolve-Path -LiteralPath $PreparedSourceReceiptPath).Path
$contract=if($ContractPath){(Resolve-Path -LiteralPath $ContractPath).Path}else{Join-Path $repoRoot 'projects\parallel_mirror_dual_stripe_mr_tof\config\simion_candidate_two_zone.json'}
$cacheRoot=Join-Path $workspaceRoot 'artifacts\common\simion\pa_family_cache'
. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')
. (Join-Path $repoRoot 'common\parallel_gate_support.ps1')
if($null-eq(Get-Command New-ShortPaCopy -ErrorAction SilentlyContinue)){. (Join-Path $repoRoot 'common\simion\short_pa_path_support.ps1')}
. (Join-Path $PSScriptRoot 'analyzer_prepared_source_support.ps1')
$batchId=if($RunId){$RunId}else{(Get-Date -Format 'yyyyMMdd_HHmmss')+'__build__simion__analyzer-local-batch'}
$temporary=$null;$source=$null;$bindingPath=$null;$planPath=$null
function Get-BatchChildRunId {
  param([Parameter(Mandatory)][string]$Batch,[Parameter(Mandatory)][string]$RegionName)
  $token=$RegionName.Replace('_','-')
  if($Batch-match'^(.*)-r([0-9]+)$'){return "$($Matches[1])-$token-r$($Matches[2])"}
  "$Batch-$token"
}
try{
  $planPath=Join-Path ([IO.Path]::GetTempPath()) ('mrtof_local_batch_plan_'+[guid]::NewGuid().ToString('N')+'.json')
  Push-Location $repoRoot
  try{
    & $python -m projects.parallel_mirror_dual_stripe_mr_tof.analysis.analyzer_local_family_batch_plan `
      --contract $contract --prepared-source-receipt $receipt --regions $Region --scale-factor $ScaleFactor `
      --cache-root $cacheRoot --simion-executable $simion --simion-release 'SIMION 2020' --output $planPath
    if($LASTEXITCODE-ne0){throw 'Batch plan derivation failed.'}
  }finally{Pop-Location}
  $plan=Get-Content -Raw -LiteralPath $planPath|ConvertFrom-Json -Depth 50
  $misses=@($plan.regions|Where-Object {[string]$_.cache_disposition-eq'miss'})
  if($misses.Count-eq0){
    foreach($row in @($plan.regions)){
      $childRunId=Get-BatchChildRunId -Batch $batchId -RegionName ([string]$row.region)
      & (Join-Path $PSScriptRoot 'run_analyzer_local_pa_family.ps1') -GeometryReviewRunPath $GeometryReviewRunPath -PreparedSourceReceiptPath $receipt -Region ([string]$row.region) -ScaleFactor $ScaleFactor -RunId $childRunId -SimionExe $simion -PythonExe $python
    }
    return
  }
  $source=Get-PreparedAnalyzerSourceReceipt -Path $receipt
  [int64]$copyBytes=0;foreach($member in @($source.members)){$copyBytes+=[int64]$member.bytes}
  $protected=@($plan.regions|ForEach-Object{[string]$_.cache_key})+@(
    [string]$source.prepared_standalone_generation.cache_key,[string]$source.raw_geometry_generation.cache_key
  )|Sort-Object -Unique
  Invoke-ArtifactCapacityGate -Python $python -RepoRoot $repoRoot -ArtifactRoot (Join-Path $workspaceRoot 'artifacts') `
    -RequiredHeadroomBytes $copyBytes -ProtectedCacheKeys $protected|Out-Null
  $temporary=Join-Path ([IO.Path]::GetTempPath()) ('simion_pa_links_mrtof_prepared_'+[guid]::NewGuid().ToString('N'))
  $bindingPath=Join-Path ([IO.Path]::GetTempPath()) ('mrtof_prepared_analyzer_binding_'+[guid]::NewGuid().ToString('N')+'.json')
  New-PreparedAnalyzerSourceBinding -Receipt $source -Directory $temporary -Output $bindingPath|Out-Null
  Assert-PreparedAnalyzerSourceBinding -Receipt $source -BindingPath $bindingPath
  foreach($row in @($plan.regions)){
    $childRunId=Get-BatchChildRunId -Batch $batchId -RegionName ([string]$row.region)
    & (Join-Path $PSScriptRoot 'run_analyzer_local_pa_family.ps1') -GeometryReviewRunPath $GeometryReviewRunPath -PreparedSourceReceiptPath $receipt -PreparedSourceBindingPath $bindingPath -ProtectedCacheKeys $protected -Region ([string]$row.region) -ScaleFactor $ScaleFactor -RunId $childRunId -SimionExe $simion -PythonExe $python
  }
  Assert-PreparedAnalyzerSourceBinding -Receipt $source -BindingPath $bindingPath
}finally{
  if($null-ne$temporary-and$null-ne$source-and$null-ne$bindingPath-and
     (Test-Path -LiteralPath $temporary -PathType Container)-and(Test-Path -LiteralPath $bindingPath -PathType Leaf)){
    try{Remove-PreparedAnalyzerSourceBinding -Receipt $source -BindingPath $bindingPath -Directory $temporary}finally{if(Test-Path -LiteralPath $bindingPath -PathType Leaf){Remove-Item -LiteralPath $bindingPath -Force}}
  }elseif($null-ne$bindingPath-and(Test-Path -LiteralPath $bindingPath -PathType Leaf)){
    Remove-Item -LiteralPath $bindingPath -Force
  }
  if($null-ne$planPath-and(Test-Path -LiteralPath $planPath -PathType Leaf)){Remove-Item -LiteralPath $planPath -Force}
}

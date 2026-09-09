Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'

function Get-VerifiedAnalyzerLocalFamily {
  param(
    [Parameter(Mandatory)][string]$SourceRunPath,
    [Parameter(Mandatory)][ValidateSet('central_transport','mirror_turn_positive','mirror_turn_negative','stripe_mirror_bridge_positive','stripe_mirror_bridge_negative')][string]$ExpectedRegion,
    [Parameter(Mandatory)][double]$ExpectedScale,
    [Parameter(Mandatory)][string]$Label,
    [Parameter(Mandatory)][string]$PythonExe,
    [Parameter(Mandatory)][string]$RepoRoot
  )
  $sourceRun=(Resolve-Path -LiteralPath $SourceRunPath).Path
  $manifest=Join-Path $sourceRun 'run_manifest.json'
  & $PythonExe (Join-Path $RepoRoot 'common\contracts\verify_run_manifest.py') $manifest --require-status success|Out-Null
  if($LASTEXITCODE-ne 0){throw "Local-family run is not verified success: $sourceRun"}
  $sourceSummary=Get-Content -Raw -LiteralPath (Join-Path $sourceRun 'summary.json')|ConvertFrom-Json
  if($sourceSummary.role-ne'mrtof_analyzer_local_dirichlet_pa_family' -or
     $sourceSummary.region-ne$ExpectedRegion -or
     [double]$sourceSummary.scale_factor-ne$ExpectedScale){
    throw "Local-family run identity differs for $Label."
  }
  $contractSource=Join-Path $sourceRun 'results\analyzer_local_pa_family_contract.json'
  $identitySource=Join-Path $sourceRun 'results\pa_family_cache_identity.json'
  $publicationSource=Join-Path $sourceRun 'results\pa_family_cache_publication.json'
  foreach($path in @($contractSource,$identitySource,$publicationSource)){
    if(-not(Test-Path -LiteralPath $path -PathType Leaf)){throw "Local-family evidence is missing: $path"}
  }
  $contract=Get-Content -Raw -LiteralPath $contractSource|ConvertFrom-Json -Depth 40
  $publication=Get-Content -Raw -LiteralPath $publicationSource|ConvertFrom-Json
  if([string]$publication.cache_key-ne[string]$sourceSummary.cache_key){
    throw "Local-family publication key differs for $Label."
  }
  return [pscustomobject]@{
    label=$Label;source_run=$sourceRun;manifest=$manifest;contract_source=$contractSource
    identity_source=$identitySource;publication_source=$publicationSource
    contract=$contract;cache_key=[string]$publication.cache_key
    region=$ExpectedRegion;scale=$ExpectedScale
    frozen_contract=$null;frozen_identity=$null;frozen_publication=$null
    generation_directory=$null
  }
}

function Resolve-AnalyzerLocalFamilyCacheGeneration {
  param(
    [Parameter(Mandatory)]$Family,
    [Parameter(Mandatory)][string]$PythonExe,
    [Parameter(Mandatory)][string]$RepoRoot,
    [Parameter(Mandatory)][string]$CacheRoot
  )
  $names=@($Family.contract.family_filenames|ForEach-Object{[string]$_})
  Push-Location -LiteralPath $RepoRoot
  $saved=$env:PYTHONPATH
  try {
    $env:PYTHONPATH=$RepoRoot
    $lines=& $PythonExe -m common.simion.pa_family_cache --action probe `
      --cache-root $CacheRoot --identity $Family.frozen_identity --filenames ($names-join ',')
    if($LASTEXITCODE-ne 0){throw "PA-family cache probe failed: $($Family.label)"}
  } finally {$env:PYTHONPATH=$saved;Pop-Location}
  $probe=(@($lines)-join "`n")|ConvertFrom-Json
  if($probe.disposition-ne'hit' -or [string]$probe.cache_key-ne$Family.cache_key){
    throw "Required local PA family is not an intact cache hit: $($Family.label)"
  }
  $Family.generation_directory=[string]$probe.generation_directory
  return $Family.generation_directory
}

function Assert-AnalyzerLocalFamilyCacheReadOnly {
  param([Parameter(Mandatory)]$Family)
  foreach($filename in @($Family.contract.family_filenames)){
    $path=Join-Path $Family.generation_directory ([string]$filename)
    if(-not(Get-Item -LiteralPath $path).IsReadOnly){
      throw "Immutable local PA cache payload is not filesystem read-only: $path"
    }
  }
  $manifest=Join-Path $Family.generation_directory 'cache_manifest.json'
  if(-not(Get-Item -LiteralPath $manifest).IsReadOnly){
    throw "Immutable local PA cache manifest is not filesystem read-only: $manifest"
  }
}

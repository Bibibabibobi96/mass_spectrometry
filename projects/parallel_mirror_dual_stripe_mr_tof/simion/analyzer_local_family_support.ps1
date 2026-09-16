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
    frozen_contract=$contractSource;frozen_identity=$identitySource;frozen_publication=$publicationSource
    generation_directory=[string]$publication.generation_directory
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
    throw "Required local PA family is not an intact cache hit: $($Family.label); disposition=$($probe.disposition); detail=$($probe.detail)"
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

function Resolve-AnalyzerLocalStandaloneResponseSubset {
  <#
    Resolve only the detached response PAs required by one runtime operation.

    Native `.paN` members are build-stage payloads.  SIMION 2020 can finalize
    those members after the visible build process exits, so a later native
    member hash drift does not invalidate an independently exported response
    whose exact bytes remain bound by the same immutable manifest.  This
    selector never calls the full-family cache probe and never opens `.paN`.
  #>
  param(
    [Parameter(Mandatory)]$Family,
    [Parameter(Mandatory)][ValidateCount(1,8)][int[]]$ResponseIds,
    [Parameter(Mandatory)][string]$CacheRoot
  )
  $key=[string]$Family.cache_key
  if($key-notmatch '^[0-9A-Fa-f]{64}$'){throw "Local-family cache key is invalid: $($Family.label)"}
  $keyRoot=Join-Path ([IO.Path]::GetFullPath($CacheRoot)) $key
  $pointerPath=Join-Path $keyRoot 'current_generation.json'
  if(-not(Test-Path -LiteralPath $pointerPath -PathType Leaf)){throw "Local-family current pointer is missing: $($Family.label)"}
  $pointer=Get-Content -Raw -LiteralPath $pointerPath|ConvertFrom-Json
  if([string]$pointer.cache_key-ne$key-or[string]$pointer.generation_sha256-notmatch'^[0-9A-Fa-f]{64}$'){
    throw "Local-family current pointer identity differs: $($Family.label)"
  }
  $generation=Join-Path $keyRoot ("generations\{0}"-f[string]$pointer.generation_sha256)
  $manifestPath=Join-Path $generation 'cache_manifest.json'
  if(-not(Test-Path -LiteralPath $manifestPath -PathType Leaf)){throw "Local-family cache manifest is missing: $($Family.label)"}
  $manifest=Get-Content -Raw -LiteralPath $manifestPath|ConvertFrom-Json -Depth 40
  if([int]$manifest.schema_version-ne1-or[string]$manifest.role-ne'simion_pa_family_cache'-or
     [string]$manifest.cache_key-ne$key-or[string]$manifest.generation_sha256-ne[string]$pointer.generation_sha256){
    throw "Local-family cache manifest identity differs: $($Family.label)"
  }
  $selected=@()
  foreach($responseId in @($ResponseIds|Sort-Object -Unique)){
    if($responseId-lt1){throw 'Local standalone response IDs must be positive.'}
    $recipes=@($Family.contract.response_recipes|Where-Object{[int]$_.local_id-eq$responseId})
    if($recipes.Count-ne1){throw "Local family must declare exactly one standalone response recipe for electrode $responseId"}
    $name=[string]$recipes[0].standalone_response_filename
    if([IO.Path]::GetFileName($name)-ne$name-or$name-notmatch'\.[pP][aA]$'){
      throw "Local response $responseId is not a direct standalone .pa filename."
    }
    $records=@($manifest.files|Where-Object{[string]$_.name-eq$name})
    if($records.Count-ne1){throw "Local response $responseId is not uniquely bound by the cache manifest."
    }
    $path=Join-Path $generation $name
    if(-not(Test-Path -LiteralPath $path -PathType Leaf)){throw "Local standalone response is missing: $path"}
    $item=Get-Item -LiteralPath $path -Force
    $hash=(Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash
    if([int64]$item.Length-ne[int64]$records[0].bytes-or$hash-ne[string]$records[0].sha256){
      throw "Local standalone response differs from its cache manifest: $name"
    }
    if(-not$item.IsReadOnly){throw "Local standalone response is not filesystem read-only: $path"}
    $selected+=[pscustomobject]@{response_id=$responseId;name=$name;path=$path;bytes=[int64]$item.Length;sha256=$hash}
  }
  if(-not(Get-Item -LiteralPath $manifestPath -Force).IsReadOnly){throw "Local response manifest is not filesystem read-only: $manifestPath"}
  $Family.generation_directory=$generation
  [pscustomobject]@{generation_directory=$generation;manifest=$manifestPath;responses=$selected}
}

function Resolve-AnalyzerLocalRawGeometry {
  <#
    Resolve the immutable raw geometry companion needed to distinguish real
    electrode nodes from physical Dirichlet boundary nodes when measuring a
    detached response normalization.  This deliberately validates only the
    requested `.pa#` member instead of reopening every native family member.
  #>
  param(
    [Parameter(Mandatory)]$Family,
    [Parameter(Mandatory)][string]$CacheRoot
  )
  $key=[string]$Family.cache_key
  if($key-notmatch'^[0-9A-Fa-f]{64}$'){throw "Local-family cache key is invalid: $($Family.label)"}
  $keyRoot=Join-Path ([IO.Path]::GetFullPath($CacheRoot)) $key
  $pointerPath=Join-Path $keyRoot 'current_generation.json'
  if(-not(Test-Path -LiteralPath $pointerPath -PathType Leaf)){throw "Local-family current pointer is missing: $($Family.label)"}
  $pointer=Get-Content -Raw -LiteralPath $pointerPath|ConvertFrom-Json
  if([string]$pointer.cache_key-ne$key-or[string]$pointer.generation_sha256-notmatch'^[0-9A-Fa-f]{64}$'){
    throw "Local-family current pointer identity differs: $($Family.label)"
  }
  $generation=Join-Path $keyRoot ("generations\{0}"-f[string]$pointer.generation_sha256)
  $manifestPath=Join-Path $generation 'cache_manifest.json'
  $manifest=Get-Content -Raw -LiteralPath $manifestPath|ConvertFrom-Json -Depth 40
  if([int]$manifest.schema_version-ne1-or[string]$manifest.role-ne'simion_pa_family_cache'-or
     [string]$manifest.cache_key-ne$key-or[string]$manifest.generation_sha256-ne[string]$pointer.generation_sha256){
    throw "Local-family cache manifest identity differs: $($Family.label)"
  }
  $name=([string]$Family.contract.family_prefix)+'.pa#'
  $records=@($manifest.files|Where-Object{[string]$_.name-eq$name})
  if($records.Count-ne1){throw "Local raw geometry is not uniquely bound by the cache manifest: $name"}
  $path=Join-Path $generation $name
  if(-not(Test-Path -LiteralPath $path -PathType Leaf)){throw "Local raw geometry is missing: $path"}
  $item=Get-Item -LiteralPath $path -Force
  $hash=(Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash
  if([int64]$item.Length-ne[int64]$records[0].bytes-or$hash-ne[string]$records[0].sha256){
    throw "Local raw geometry differs from its cache manifest: $name"
  }
  if(-not$item.IsReadOnly){throw "Local raw geometry is not filesystem read-only: $path"}
  if(-not(Get-Item -LiteralPath $manifestPath -Force).IsReadOnly){throw "Local response manifest is not filesystem read-only: $manifestPath"}
  $Family.generation_directory=$generation
  [pscustomobject]@{name=$name;path=$path;bytes=[int64]$item.Length;sha256=$hash;manifest=$manifestPath}
}

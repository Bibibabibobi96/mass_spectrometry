Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'

function Get-PreparedAnalyzerSourceReceipt {
  param([Parameter(Mandatory)][string]$Path)
  $receipt=Get-Content -Raw -LiteralPath $Path|ConvertFrom-Json -Depth 50
  if([string]$receipt.role-ne'mrtof_reviewed_analyzer_source_cache_receipt'-or[string]$receipt.status-ne'success'){
    throw 'Prepared analyzer source receipt is not a successful reviewed cache receipt.'
  }
  $prepared=$receipt.prepared_standalone_generation;$raw=$receipt.raw_geometry_generation
  foreach($generation in @($prepared,$raw)){
    if($null-eq$generation-or[string]$generation.cache_key-notmatch'^[0-9A-Fa-f]{64}$'-or[string]$generation.generation_sha256-notmatch'^[0-9A-Fa-f]{64}$'){
      throw 'Prepared analyzer source receipt has an invalid frozen generation identity.'
    }
  }
  $members=@();$rawRecord=$raw.raw_geometry
  if($null-eq$rawRecord-or[string]$rawRecord.name-ne'mrtof_analyzer.pa#'){throw 'Prepared analyzer source receipt lacks raw geometry.'}
  $members+=[pscustomobject]@{kind='raw';physical_id=$null;name='mrtof_analyzer.pa#';bytes=[int64]$rawRecord.bytes;sha256=[string]$rawRecord.sha256;source_directory=[string]$raw.generation_directory}
  foreach($id in @(2,3,4,5,7,8,9,10,11,12,13,14,16,17)){
    $record=$prepared.responses_by_physical_id.([string]$id)
    if($null-eq$record-or[int]$record.physical_id-ne$id-or[string]$record.name-notmatch'\.pa$'){throw "Prepared analyzer source receipt lacks standalone response $id."}
    $members+=[pscustomobject]@{kind='response';physical_id=$id;name=[string]$record.name;bytes=[int64]$record.bytes;sha256=[string]$record.sha256;source_directory=[string]$prepared.generation_directory}
  }
  if(@($members|ForEach-Object{$_.name}|Sort-Object -Unique).Count-ne15){throw 'Prepared analyzer source receipt has duplicate member names.'}
  [pscustomobject]@{prepared_standalone_generation=$prepared;raw_geometry_generation=$raw;evidence=$receipt.evidence;members=$members}
}

function Assert-PreparedAnalyzerGeometrySource {
  param(
    [Parameter(Mandatory)]$Receipt,
    [Parameter(Mandatory)][string]$GeometryRun,
    [Parameter(Mandatory)][string]$ManifestPath,
    [Parameter(Mandatory)][string]$ReviewedContractPath,
    [Parameter(Mandatory)][string]$GlobalGemPath,
    [Parameter(Mandatory)][string]$GeometryReviewPath
  )
  $provider=$Receipt.evidence.provider
  if($null-eq$provider-or$null-eq$provider.run_manifest){throw 'Prepared analyzer receipt lacks provider geometry evidence.'}
  $resolvedRun=(Resolve-Path -LiteralPath $GeometryRun).Path
  if(-not[string]::Equals([IO.Path]::GetFullPath([string]$provider.run_directory),$resolvedRun,[StringComparison]::OrdinalIgnoreCase)){
    throw 'Geometry review run differs from the prepared analyzer provider.'
  }
  $manifestItem=Get-Item -LiteralPath $ManifestPath -Force
  $manifestHash=(Get-FileHash -LiteralPath $ManifestPath -Algorithm SHA256).Hash
  if([int64]$manifestItem.Length-ne[int64]$provider.run_manifest.bytes-or
     -not[string]::Equals($manifestHash,[string]$provider.run_manifest.sha256,[StringComparison]::OrdinalIgnoreCase)){
    throw 'Geometry provider manifest differs from the prepared analyzer receipt.'
  }
  $manifest=Get-Content -Raw -LiteralPath $ManifestPath|ConvertFrom-Json -AsHashtable -Depth 50
  if([string]$manifest.status-ne'success'-or[string]$manifest.run_id-ne[string]$provider.run_id){throw 'Geometry provider manifest is not the frozen successful provider run.'}
  $reviewRecord=@($manifest.outputs|Where-Object {[IO.Path]::GetFileName([string]$_.path)-eq'three_component_geometry_review.json'})
  $records=@(
    [pscustomobject]@{path=$ReviewedContractPath;record=$manifest.inputs.resolved_prototype_contract;label='resolved prototype contract'},
    [pscustomobject]@{path=$GlobalGemPath;record=$manifest.inputs.analyzer_gem;label='analyzer GEM'},
    [pscustomobject]@{path=$GeometryReviewPath;record=if($reviewRecord.Count-eq1){$reviewRecord[0]}else{$null};label='geometry review'}
  )
  foreach($entry in $records){
    if($null-eq$entry.record-or-not[bool]$entry.record.exists){throw "Geometry provider manifest lacks $($entry.label)."}
    $item=Get-Item -LiteralPath $entry.path -Force;$hash=(Get-FileHash -LiteralPath $entry.path -Algorithm SHA256).Hash
    if([int64]$item.Length-ne[int64]$entry.record.bytes-or-not[string]::Equals($hash,[string]$entry.record.sha256,[StringComparison]::OrdinalIgnoreCase)){
      throw "Geometry provider $($entry.label) differs from its frozen manifest record."
    }
  }
  if(-not[string]::Equals([string]$provider.analyzer_gem.sha256,[string]$manifest.inputs.analyzer_gem.sha256,[StringComparison]::OrdinalIgnoreCase)-or
     -not[string]::Equals([string]$provider.geometry_review.sha256,[string]$reviewRecord[0].sha256,[StringComparison]::OrdinalIgnoreCase)){
    throw 'Prepared analyzer receipt and geometry provider manifest disagree.'
  }
}

function New-PreparedAnalyzerSourceBinding {
  param([Parameter(Mandatory)]$Receipt,[Parameter(Mandatory)][string]$Directory,[Parameter(Mandatory)][string]$Output)
  try{
    New-Item -ItemType Directory -Path $Directory -ErrorAction Stop|Out-Null
    $responses=[ordered]@{};$raw=$null
    foreach($member in @($Receipt.members)){
      $source=Join-Path ([string]$member.source_directory) ([string]$member.name)
      $destination=Join-Path $Directory ([string]$member.name)
      New-ShortPaCopy -Source $source -Destination $destination -ExpectedBytes ([int64]$member.bytes) -ExpectedSha256 ([string]$member.sha256) -GuardDestinationReadOnly|Out-Null
      $identity=Get-ShortPaCopyIdentity -Path $destination
      $record=[ordered]@{name=[string]$member.name;bytes=[int64]$member.bytes;sha256=[string]$member.sha256;binding_path=[string]$identity.path}
      if($member.kind-eq'raw'){$raw=$record}else{$responses[[string]$member.physical_id]=$record}
    }
    $binding=[ordered]@{schema_version=1;role='mrtof_prepared_analyzer_source_binding';status='success';prepared_standalone_generation=[ordered]@{cache_key=[string]$Receipt.prepared_standalone_generation.cache_key;generation_sha256=[string]$Receipt.prepared_standalone_generation.generation_sha256};raw_geometry_generation=[ordered]@{cache_key=[string]$Receipt.raw_geometry_generation.cache_key;generation_sha256=[string]$Receipt.raw_geometry_generation.generation_sha256};responses_by_physical_id=$responses;raw_geometry=$raw}
    Write-RunJson -Path $Output -Depth 20 -Value $binding
    $binding
  }catch{
    $failure=$_
    if(Test-Path -LiteralPath $Output -PathType Leaf){Remove-Item -LiteralPath $Output -Force}
    if(Test-Path -LiteralPath $Directory -PathType Container){
      Remove-ShortPaCopyDirectory -Path $Directory -ExpectedNamePrefix 'simion_pa_links_mrtof_prepared_'
    }
    throw $failure
  }
}

function Assert-PreparedAnalyzerSourceBinding {
  param([Parameter(Mandatory)]$Receipt,[Parameter(Mandatory)][string]$BindingPath)
  $binding=Get-Content -Raw -LiteralPath $BindingPath|ConvertFrom-Json -Depth 40
  if([string]$binding.role-ne'mrtof_prepared_analyzer_source_binding'-or[string]$binding.status-ne'success'){throw 'Prepared analyzer source binding is invalid.'}
  foreach($member in @($Receipt.members)){
    $record=if($member.kind-eq'raw'){$binding.raw_geometry}else{$binding.responses_by_physical_id.([string]$member.physical_id)}
    if($null-eq$record-or[string]$record.name-ne[string]$member.name-or[int64]$record.bytes-ne[int64]$member.bytes-or-not[string]::Equals([string]$record.sha256,[string]$member.sha256,[StringComparison]::OrdinalIgnoreCase)){throw "Prepared analyzer copy metadata differs: $($member.name)"}
    $path=[string]$record.binding_path;$item=Get-Item -LiteralPath $path -Force;$hash=(Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash
    if([int64]$item.Length-ne[int64]$member.bytes-or-not[string]::Equals($hash,[string]$member.sha256,[StringComparison]::OrdinalIgnoreCase)){throw "Prepared analyzer copy identity differs: $($member.name)"}
    Get-ShortPaCopyIdentity -Path $path|Out-Null
  }
}

function Remove-PreparedAnalyzerSourceBinding {
  param([Parameter(Mandatory)]$Receipt,[Parameter(Mandatory)][string]$BindingPath,[Parameter(Mandatory)][string]$Directory)
  Assert-PreparedAnalyzerSourceBinding -Receipt $Receipt -BindingPath $BindingPath
  Remove-ShortPaCopyDirectory -Path $Directory -ExpectedNamePrefix 'simion_pa_links_mrtof_prepared_'
}

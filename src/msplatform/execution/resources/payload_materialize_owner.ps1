<# Private installed JSON transport; the existing RunSession owns this process. #>
param([Parameter(Mandatory)][string]$RequestPath)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
[Console]::InputEncoding=[Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$request=Get-Content -LiteralPath $RequestPath -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
if($request.schema_version-ne1-or-not[IO.Path]::IsPathFullyQualified([string]$request.python_executable)-or
   -not(Test-Path -LiteralPath $request.python_executable -PathType Leaf)-or
   -not[IO.Path]::IsPathFullyQualified([string]$request.receipt_path)-or$request.copies.Count-lt1){
  throw 'Invalid explicit payload materialization request.'
}
$script:PayloadIdentityPython=[string]$request.python_executable
. (Join-Path $PSScriptRoot 'payload_file_support.ps1') -UnbufferedIdentityReader {
  param($Source,$Length)
  $digest=@(& $script:PayloadIdentityPython -I -B -X utf8 -c `
    'import sys;from msplatform.io.file_identity import file_sha256_unbuffered;print(file_sha256_unbuffered(sys.argv[1]))' $Source)
  if($LASTEXITCODE-ne0){throw 'Installed unbuffered payload identity failed.'}
  return $digest
}
$protected=[Collections.Generic.List[string]]::new()
$created=[Collections.Generic.List[string]]::new()
$outputs=[Collections.Generic.List[object]]::new()
$released=[Collections.Generic.List[object]]::new()
$secondary=[Collections.Generic.List[string]]::new()
$primary=$null
try{
  foreach($copy in $request.copies){
    $record=$copy.source_record
    $source=[string]$record.path
    $destination=[string]$copy.destination
    if($record.exists-ne$true-or-not[IO.Path]::IsPathFullyQualified($source)-or
       -not[IO.Path]::IsPathFullyQualified($destination)-or[long]$record.bytes-lt0-or
       [string]$record.sha256-cnotmatch'^[0-9A-Fa-f]{64}$'-or
       $source-eq$destination-or(Test-Path -LiteralPath $destination)){
      throw 'Payload source record or independent new destination is invalid.'
    }
    $identity=Protect-ImmutablePaSource -Source $source -ExpectedBytes ([int64]$record.bytes) -ExpectedSha256 $record.sha256
    $source=[string]$identity.path
    if(-not$protected.Contains($source)){$protected.Add($source)}
    $parent=Split-Path -Parent $destination
    [IO.Directory]::CreateDirectory($parent)|Out-Null
    $stream=[IO.File]::Open($source,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
    try{
      $created.Add($destination)
      Copy-StandalonePaBytes -SourceStream $stream -Destination $destination -Length ([int64]$record.bytes)
    }finally{$stream.Dispose()}
    # The model owns writable independent bytes, never its published source.
    $attributes=[IO.File]::GetAttributes($destination)
    [IO.File]::SetAttributes($destination,$attributes-band(-bnot[IO.FileAttributes]::ReadOnly))
    $destinationIdentity=Protect-ImmutablePaSource -Source $destination -ExpectedBytes ([int64]$record.bytes) -ExpectedSha256 $record.sha256
    if(-not$protected.Contains([string]$destinationIdentity.path)){$protected.Add([string]$destinationIdentity.path)}
    $outputs.Add(@{path=[string]$destinationIdentity.path;exists=$true;bytes=[int64]$destinationIdentity.bytes;
      sha256=[string]$destinationIdentity.sha256;retention_role=[string]$record.retention_role})
  }
}catch{$primary=$_}
finally{
  foreach($source in $protected){
    try{$released.Add((Unprotect-ImmutablePaSource -Source $source))}
    catch{$secondary.Add($_.Exception.Message);if($null-eq$primary){$primary=$_}}
  }
  if($null-ne$primary){
    foreach($destination in $created){
      try{
        if($global:MassSpectrometryImmutablePaSourceGuards.ContainsKey($destination)){continue}
        if(Test-Path -LiteralPath $destination -PathType Leaf){
          $attributes=[IO.File]::GetAttributes($destination)
          [IO.File]::SetAttributes($destination,$attributes-band(-bnot[IO.FileAttributes]::ReadOnly))
          [IO.File]::Delete($destination)
        }
      }catch{$secondary.Add($_.Exception.Message)}
    }
  }
}
$receipt=@{schema_version=1;role='payload_materialization';status=$(if($null-eq$primary){'success'}else{'failed'});
  outputs=@($outputs.ToArray());source_and_destination_releases=@($released.ToArray());
  primary=$(if($null-eq$primary){$null}else{$primary.Exception.Message});secondary_errors=@($secondary.ToArray())}
try{
  $json=$receipt|ConvertTo-Json -Depth 24 -Compress
  $json|& $request.python_executable -I -B -X utf8 -c `
    'import json,sys;from pathlib import Path;from msplatform.execution.recorded_file_removal import write_json_atomic;write_json_atomic(Path(sys.argv[1]),json.load(sys.stdin))' $request.receipt_path
  if($LASTEXITCODE-ne0){throw 'Payload receipt publication failed.'}
}catch{
  if($null-eq$primary){$primary=$_}else{[Console]::Error.WriteLine('SECONDARY_RECEIPT_ERROR='+$_.Exception.Message)}
}
if($null-ne$primary){throw $primary}

Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$nativeFastAdjustRepoRoot=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
. (Join-Path $PSScriptRoot 'short_pa_path_support.ps1')

function New-NativeFastAdjustRuntimeFamily {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$GenerationDirectory,
    [Parameter(Mandatory)][string]$ExpectedCacheKey,
    [Parameter(Mandatory)][string]$ExpectedGenerationSha256,
    [Parameter(Mandatory)][string]$ReceiptName,
    [Parameter(Mandatory)][string]$RawName,
    [Parameter(Mandatory)][string]$FamilyPrefix,
    [Parameter(Mandatory)][int[]]$ExpectedResponseIds,
    [Parameter(Mandatory)][string]$DestinationDirectory,
    [Parameter(Mandatory)][string]$Python,
    [Parameter(Mandatory)][string]$RepoRoot,
    [Parameter(Mandatory)][string]$SimionExe,
    [Parameter(Mandatory)]$ResourceLease,
    [Parameter(Mandatory)][string]$RunId,
    [string]$ReceiptRole='private_native_fast_adjust_family'
  )
  $generation=(Resolve-Path -LiteralPath $GenerationDirectory).Path
  $destination=[IO.Path]::GetFullPath($DestinationDirectory)
  if($ExpectedResponseIds.Count-lt1-or@(Compare-Object @($ExpectedResponseIds) @(1..$ExpectedResponseIds.Count)).Count-ne0){throw 'Expected response IDs must be the complete namespace 1..N.'}
  if([IO.Path]::GetFileName($RawName)-ne$RawName-or-not$RawName.EndsWith('.pa#')){throw 'Raw member name must be one direct .pa# filename.'}
  if([IO.Path]::GetFileName($ReceiptName)-ne$ReceiptName-or-not$ReceiptName.EndsWith('.json')){throw 'Response receipt name must be one direct JSON filename.'}
  if([IO.Path]::GetFileName($FamilyPrefix)-ne$FamilyPrefix-or[string]::IsNullOrWhiteSpace($FamilyPrefix)){throw 'Family prefix must be one direct filename prefix.'}
  $ids=$ExpectedResponseIds-join','
  $code=@'
import json,sys
from pathlib import Path
from common.contracts.file_identity import file_sha256_unbuffered
from common.simion.pa_family_cache import validate_pa_family_cache_generation
from common.simion.standalone_pa_response_set import validate_standalone_pa_response_set
p=Path(sys.argv[1]); receipt=sys.argv[2]; raw_name=sys.argv[3]
ids=tuple(int(value) for value in sys.argv[4].split(','))
m=json.loads((p/'cache_manifest.json').read_text(encoding='utf-8'))
m=validate_pa_family_cache_generation(p,expected_cache_key=sys.argv[5],expected_filenames=[item['name'] for item in m['files']],verify_payload=False)
assert m['generation_sha256']==sys.argv[6], 'sealed generation identity differs'
receipt_record=next((item for item in m['files'] if item['name']==receipt),None)
assert receipt_record is not None, 'standalone response receipt is absent from the sealed generation'
receipt_path=p/receipt
assert receipt_path.stat().st_size==receipt_record['bytes'] and file_sha256_unbuffered(receipt_path)==receipt_record['sha256'], 'standalone response receipt bytes differ from the sealed inventory'
records=validate_standalone_pa_response_set(p,m,receipt,expected_response_ids=ids,inventory_is_verified=True)
raw=next((item for item in m['files'] if item['name']==raw_name),None)
assert raw is not None, 'raw member is absent from the sealed generation'
print(json.dumps({'cache_key':m['cache_key'],'generation_sha256':m['generation_sha256'],'raw':raw,'responses':[vars(item) for item in records]}))
'@
  $text=@(Invoke-RunToolRootContext -RepoRoot $RepoRoot -Operation {
    &$Python -c $code $generation $ReceiptName $RawName $ids $ExpectedCacheKey $ExpectedGenerationSha256
    if($LASTEXITCODE-ne0){throw 'Standalone response generation metadata validation failed.'}
  })
  $bank=($text-join"`n")|ConvertFrom-Json -Depth 40
  New-Item -ItemType Directory -Path $destination -Force|Out-Null
  if(@(Get-ChildItem -LiteralPath $destination -Force).Count-ne0){throw 'Native execution family directory must be empty.'}
  $privateRaw=$null;$privateResponse=$null
  $controller=Join-Path $destination ($FamilyPrefix+'.pa0')
  try {
    $privateRaw=New-ShortPaCopy -Source (Join-Path $generation ([string]$bank.raw.name)) `
      -Destination (Join-Path $destination ($FamilyPrefix+'.pa#')) `
      -ExpectedBytes ([int64]$bank.raw.bytes) -ExpectedSha256 ([string]$bank.raw.sha256)
    $ResourceLease=Update-HostResourceStage -Lease $ResourceLease -Stage pa_refine `
      -Budget (Get-HostResourceBudget -Role SIMION -Stage pa_refine) -RetainedMemoryBytes 0
    &$SimionExe --nogui --noprompt lua (Join-Path $PSScriptRoot 'assemble_native_fast_adjust_family.lua') `
      --controller $privateRaw $controller $ExpectedResponseIds.Count | Out-Host
    if($LASTEXITCODE-ne0){throw 'Native execution controller construction failed.'}
    $ResourceLease=Update-HostResourceStage -Lease $ResourceLease -Stage prepare `
      -Budget (Get-HostResourceBudget -Role SIMION -Stage prepare) -RetainedMemoryBytes 0
    Remove-ShortPaCopy -Path $privateRaw;$privateRaw=$null
    foreach($record in @($bank.responses)){
      $privateResponse=New-ShortPaCopy -Source (Join-Path $generation ([string]$record.name)) `
        -Destination (Join-Path $destination 'source_response.pa') `
        -ExpectedBytes ([int64]$record.bytes) -ExpectedSha256 ([string]$record.sha256) -GuardDestinationReadOnly
      $native=Join-Path $destination ($FamilyPrefix+'.pa'+[int]$record.response_id)
      &$SimionExe --nogui --noprompt lua (Join-Path $PSScriptRoot 'assemble_native_fast_adjust_family.lua') `
        --append $privateResponse $native | Out-Host
      if($LASTEXITCODE-ne0){throw "Native execution response construction failed: $($record.response_id)"}
      Remove-ShortPaCopy -Path $privateResponse;$privateResponse=$null
    }
    return [pscustomobject]@{
      controller_path=$controller;resource_lease=$ResourceLease
      receipt=[ordered]@{schema_version=1;role=$ReceiptRole;status='prepared';run_id=$RunId;
        cache_key=[string]$bank.cache_key;generation_sha256=[string]$bank.generation_sha256;generation_directory=$generation;
        response_ids=@($ExpectedResponseIds);source_responses=@($bank.responses);source_raw=$bank.raw;controller_path=$controller;
        response_refine_performed=$false;controller_refine='solutions={0}';published_native_members_opened=$false}
    }
  } finally {
    if($null-ne$privateResponse){Remove-ShortPaCopy -Path $privateResponse}
    if($null-ne$privateRaw){Remove-ShortPaCopy -Path $privateRaw}
  }
}

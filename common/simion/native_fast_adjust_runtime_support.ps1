Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$nativeFastAdjustRepoRoot=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
. (Join-Path $PSScriptRoot 'short_pa_path_support.ps1')

function New-NativeFastAdjustRuntimeFamily {
  [CmdletBinding(DefaultParameterSetName='Published')]
  param(
    [Parameter(Mandatory,ParameterSetName='Published')][string]$GenerationDirectory,
    [Parameter(Mandatory)][string]$ExpectedCacheKey,
    [Parameter(Mandatory,ParameterSetName='Published')][string]$ExpectedGenerationSha256,
    [Parameter(Mandatory,ParameterSetName='Transaction')][string]$TransactionPath,
    [Parameter(Mandatory,ParameterSetName='Transaction')][string]$ExpectedInventorySha256,
    [Parameter(Mandatory,ParameterSetName='Transaction')][string]$ExpectedOwner,
    [Parameter(Mandatory,ParameterSetName='Transaction')][string]$ProducerRunConfig,
    [Parameter(Mandatory,ParameterSetName='Transaction')][string]$CapacitySessionPath,
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
    [switch]$RequireEmptyFamilyNamespace,
    [Collections.Generic.List[object]]$NativeOperationObservations=$null,
    [scriptblock]$InvokeNativeOperation=$null,
    [scriptblock]$GetResponseVerificationArguments=$null,
    [string]$ReceiptRole='private_native_fast_adjust_family'
  )
  $transactionSource=$PSCmdlet.ParameterSetName-eq'Transaction'
  $sourcePath=if($transactionSource){(Resolve-Path -LiteralPath $TransactionPath).Path}else{(Resolve-Path -LiteralPath $GenerationDirectory).Path}
  $destination=[IO.Path]::GetFullPath($DestinationDirectory)
  if($ExpectedResponseIds.Count-lt1-or@(Compare-Object @($ExpectedResponseIds) @(1..$ExpectedResponseIds.Count)).Count-ne0){throw 'Expected response IDs must be the complete namespace 1..N.'}
  if([IO.Path]::GetFileName($RawName)-ne$RawName-or-not$RawName.EndsWith('.pa#')){throw 'Raw member name must be one direct .pa# filename.'}
  if([IO.Path]::GetFileName($ReceiptName)-ne$ReceiptName-or-not$ReceiptName.EndsWith('.json')){throw 'Response receipt name must be one direct JSON filename.'}
  if([IO.Path]::GetFileName($FamilyPrefix)-ne$FamilyPrefix-or[string]::IsNullOrWhiteSpace($FamilyPrefix)){throw 'Family prefix must be one direct filename prefix.'}
  $ids=$ExpectedResponseIds-join','
  $code=@'
import json,stat,sys
from pathlib import Path
from common.contracts.file_identity import file_sha256_unbuffered
from common.contracts.capacity_protection import load_capacity_protection_leases, path_is_protected
from common.simion.pa_family_cache import validate_pa_family_cache_generation, load_pa_family_cache_transaction
from common.simion.standalone_pa_response_set import validate_standalone_pa_response_set
p=Path(sys.argv[1]); receipt=sys.argv[2]; raw_name=sys.argv[3]
ids=tuple(int(value) for value in sys.argv[4].split(','))
transaction_record=None
if sys.argv[7]=='Transaction':
    session=json.loads(Path(sys.argv[10]).read_text(encoding='utf-8-sig'))
    root=Path(session['artifact_root']).resolve(); cache=root/'common/simion/pa_family_cache'
    assert p.resolve()==cache/'.transactions'/sys.argv[5]/'transaction.json', 'transaction must be the governed cache owner record'
    m=load_pa_family_cache_transaction(cache,sys.argv[5])
    producer=Path(sys.argv[9]).resolve(); run=producer.parent
    assert session['role']=='artifact_workflow_capacity_session' and session['status']=='active', 'transaction session is inactive'
    assert m['owner']==sys.argv[8] and Path(m['producer']['run_config_path']).resolve()==producer, 'transaction producer differs'
    assert m['status'] in {'building','prepared'} and m['files'] and m['inventory_sha256']==sys.argv[6], 'transaction inventory differs'
    leases=load_capacity_protection_leases(root)['audit']
    lease=next((row for row in leases if row['status']=='active' and row['lease_id']==session['lease_id'] and row['owner']==session['owner']),None)
    assert lease and sys.argv[5].lower() in lease['protected_cache_keys'] and path_is_protected(run,[Path(value) for value in lease['protected_paths']]), 'transaction workflow protection differs'
    transaction_record={'path':str(p),'inventory_sha256':m['inventory_sha256'],
        'owner':m['owner'],'producer':m['producer']}
    p=p.parent/'payload'
    for record in m['files']:
        member=p/record['name']
        assert not member.is_symlink() and member.is_file() and member.stat().st_size==record['bytes'], 'transaction member metadata differs'
        assert not member.stat().st_mode & stat.S_IWRITE, 'transaction member is not sealed read-only'
else:
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
print(json.dumps({'source_directory':str(p),'source_transaction':transaction_record,
    'cache_key':m['cache_key'],'generation_sha256':m['generation_sha256'],
    'raw':raw,'responses':[vars(item) for item in records]}))
'@
  $sourceKind=if($transactionSource){'Transaction'}else{'Published'}
  $expectedDigest=if($transactionSource){$ExpectedInventorySha256}else{$ExpectedGenerationSha256}
  $text=@(Invoke-RunToolRootContext -RepoRoot $RepoRoot -Operation {
    &$Python -c $code $sourcePath $ReceiptName $RawName $ids $ExpectedCacheKey $expectedDigest $sourceKind $ExpectedOwner $ProducerRunConfig $CapacitySessionPath
    if($LASTEXITCODE-ne0){throw 'Standalone response owner metadata validation failed.'}
  })
  $bank=($text-join"`n")|ConvertFrom-Json -Depth 40
  $sourceDirectory=[string]$bank.source_directory
  New-Item -ItemType Directory -Path $destination -Force|Out-Null
  $existing=@(Get-ChildItem -LiteralPath $destination -Force)
  if($RequireEmptyFamilyNamespace){
    $collision=@($existing|Where-Object{
      $_.Name.StartsWith(($FamilyPrefix+'.'),[StringComparison]::OrdinalIgnoreCase)-or
      $_.Name.Equals(($FamilyPrefix+'_source_response.pa'),[StringComparison]::OrdinalIgnoreCase)
    })
    if($collision.Count-ne0){throw 'Native execution family namespace must be empty.'}
  }elseif($existing.Count-ne0){throw 'Native execution family directory must be empty.'}
  $privateRaw=$null;$privateResponse=$null;$nativeWritesStopped=$true
  $controller=Join-Path $destination ($FamilyPrefix+'.pa0')
  function Test-NativeRuntimeWriterCompletion {
    param($Completion,$Observation)
    if($null-eq$Completion-or$null-eq$Observation-or-not$Observation.exit_confirmed){return $false}
    # Direct PowerShell owners attest their actual root and drained pipes;
    # they do not have a Python launcher/worker to attest.
    $role=if($Completion-is[Collections.IDictionary]){$Completion['role']}
      elseif($Completion.PSObject.Properties['role']){$Completion.role}else{$null}
    if($role-eq'powershell_process_completion'){
      return $Completion.exit_confirmed-eq$true-and$Completion.stdout_drained-eq$true-and
        $Completion.stderr_drained-eq$true-and
        ($Completion.process_id-is[int]-or$Completion.process_id-is[long])-and$Completion.process_id-gt0-and
        ($Completion.process_started_at_utc_ticks-is[int]-or$Completion.process_started_at_utc_ticks-is[long])-and
        $Completion.process_started_at_utc_ticks-gt0-and
        $Completion.process_id-eq$Observation.process_id-and
        $Completion.process_started_at_utc_ticks-eq$Observation.process_started_at_utc_ticks-and
        ($Completion.returncode-is[int]-or$Completion.returncode-is[long])-and
        $Completion.returncode-eq$Observation.returncode
    }
    return $Completion.ownership_confirmed-and$Completion.worker_exit_confirmed-and
      $Completion.launcher_exit_confirmed-and$Completion.stdout_drained-and$Completion.stderr_drained
  }
  function Invoke-NativeRuntimeCommand {
    param([string[]]$Arguments,[string]$OperationId,[ref]$Stopped)
    $operation=@{operation_id=$OperationId;observation=@{exit_confirmed=$false;returncode=$null}}
    if($null-ne$NativeOperationObservations){$NativeOperationObservations.Add($operation)}
    $Stopped.Value=$false
    if($null-ne$InvokeNativeOperation){
      try{
        $observed=&$InvokeNativeOperation -ArgumentList $Arguments -OperationId $OperationId
        $operation.observation=$observed.observation
        $operation.managed_process_completion=$observed.managed_process_completion
        $completion=$observed.managed_process_completion
        $Stopped.Value=Test-NativeRuntimeWriterCompletion $completion $operation.observation
        if(-not$Stopped.Value){throw 'Native runtime operation has no confirmed owned writer completion.'}
      }catch{
        if($_.Exception.Data.Contains('native_operation_observation')){
          $observed=$_.Exception.Data['native_operation_observation']
          $operation.observation=$observed.observation
          $operation.managed_process_completion=$observed.managed_process_completion
          $completion=$observed.managed_process_completion
          $Stopped.Value=Test-NativeRuntimeWriterCompletion $completion $operation.observation
        }
        throw
      }
    }else{
      &$SimionExe @Arguments|Out-Host
      $operation.observation.exit_confirmed=$true;$operation.observation.returncode=[int]$LASTEXITCODE
      # The original direct-call API has only synchronous root evidence.
      # Managed consumers supply the strict owned-process callback above.
      $Stopped.Value=$true
    }
    if(-not$operation.observation.exit_confirmed-or$operation.observation.returncode-ne0){
      throw "Native runtime operation failed: $OperationId"
    }
  }
  try {
    $privateRaw=New-ShortPaCopy -Source (Join-Path $sourceDirectory ([string]$bank.raw.name)) `
      -Destination (Join-Path $destination ($FamilyPrefix+'.pa#')) `
      -ExpectedBytes ([int64]$bank.raw.bytes) -ExpectedSha256 ([string]$bank.raw.sha256)
    $ResourceLease=Update-HostResourceStage -Lease $ResourceLease -Stage pa_refine `
      -Budget (Get-HostResourceBudget -Role SIMION -Stage pa_refine) -RetainedMemoryBytes 0
    Invoke-NativeRuntimeCommand -Arguments @('--nogui','--noprompt','lua',(Join-Path $PSScriptRoot 'assemble_native_fast_adjust_family.lua'),
      '--controller',$privateRaw,$controller,[string]$ExpectedResponseIds.Count) -OperationId ($FamilyPrefix+'.controller') -Stopped ([ref]$nativeWritesStopped)
    $ResourceLease=Update-HostResourceStage -Lease $ResourceLease -Stage prepare `
      -Budget (Get-HostResourceBudget -Role SIMION -Stage prepare) -RetainedMemoryBytes 0
    Remove-ShortPaCopy -Path $privateRaw;$privateRaw=$null
    foreach($record in @($bank.responses)){
      $privateResponse=New-ShortPaCopy -Source (Join-Path $sourceDirectory ([string]$record.name)) `
        -Destination (Join-Path $destination ($FamilyPrefix+'_source_response.pa')) `
        -ExpectedBytes ([int64]$record.bytes) -ExpectedSha256 ([string]$record.sha256) -GuardDestinationReadOnly
      $native=Join-Path $destination ($FamilyPrefix+'.pa'+[int]$record.response_id)
      Invoke-NativeRuntimeCommand -Arguments @('--nogui','--noprompt','lua',(Join-Path $PSScriptRoot 'assemble_native_fast_adjust_family.lua'),
        '--append',$privateResponse,$native) -OperationId ($FamilyPrefix+'.response.'+$record.response_id) -Stopped ([ref]$nativeWritesStopped)
      if($null-ne$GetResponseVerificationArguments){
        $verificationArguments=@(&$GetResponseVerificationArguments -FamilyStem (Join-Path $destination $FamilyPrefix) `
          -StandalonePath $privateResponse -ResponseId ([int]$record.response_id))
        Invoke-NativeRuntimeCommand -Arguments $verificationArguments `
          -OperationId ($FamilyPrefix+'.verify.response.'+$record.response_id) -Stopped ([ref]$nativeWritesStopped)
      }
      Remove-ShortPaCopy -Path $privateResponse;$privateResponse=$null
    }
    return [pscustomobject]@{
      controller_path=$controller;resource_lease=$ResourceLease
      receipt=[ordered]@{schema_version=1;role=$ReceiptRole;status='prepared';run_id=$RunId;
        cache_key=[string]$bank.cache_key;generation_sha256=$bank.generation_sha256;
        generation_directory=$(if($transactionSource){$null}else{$sourceDirectory});
        source_transaction=$bank.source_transaction;
        verified_response_ids=@(if($null-ne$GetResponseVerificationArguments){$ExpectedResponseIds});
        response_ids=@($ExpectedResponseIds);source_responses=@($bank.responses);source_raw=$bank.raw;controller_path=$controller;
        response_refine_performed=$false;controller_refine='solutions={0}';published_native_members_opened=$false}
    }
  } finally {
    if($nativeWritesStopped){
      if($null-ne$privateResponse){Remove-ShortPaCopy -Path $privateResponse}
      if($null-ne$privateRaw){Remove-ShortPaCopy -Path $privateRaw}
    }
  }
}

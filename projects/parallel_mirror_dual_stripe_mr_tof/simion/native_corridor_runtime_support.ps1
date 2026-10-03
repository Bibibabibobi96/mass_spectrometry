Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$nativeCorridorRepoRoot=(Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
. (Join-Path $nativeCorridorRepoRoot 'common\simion\short_pa_path_support.ps1')
. (Join-Path $nativeCorridorRepoRoot 'common\simion\native_fast_adjust_runtime_support.ps1')

# Production adapter for run_two_prism_trial: only standalone source copies
# enter SIMION; the native family belongs to a flight or its sequential workflow.
function New-NativeCorridorRuntimeFamily {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$BankGenerationDirectory,
    [Parameter(Mandatory)][string]$CacheKey,
    [Parameter(Mandatory)][string]$GenerationSha256,
    [Parameter(Mandatory)][string]$DestinationDirectory,
    [Parameter(Mandatory)][string]$Python,
    [Parameter(Mandatory)][string]$RepoRoot,
    [Parameter(Mandatory)][string]$SimionExe,
    [Parameter(Mandatory)]$ResourceLease,
    [Parameter(Mandatory)][string]$RunId
  )
  return New-NativeFastAdjustRuntimeFamily -GenerationDirectory $BankGenerationDirectory `
    -ExpectedCacheKey $CacheKey -ExpectedGenerationSha256 $GenerationSha256 `
    -ReceiptName 'mrtof_analyzer_corridor.standalone_responses.json' `
    -RawName 'mrtof_analyzer_corridor.pa#' -FamilyPrefix 'mrtof_analyzer_corridor' `
    -ExpectedResponseIds @(1..8) -DestinationDirectory $DestinationDirectory `
    -Python $Python -RepoRoot $RepoRoot -SimionExe $SimionExe -ResourceLease $ResourceLease `
    -RunId $RunId -ReceiptRole 'mrtof_private_native_corridor_family'
}

function Get-NativeAcceleratorRuntimeFamily {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)]$Session,
    [Parameter(Mandatory)][string]$ProviderReceiptPath,
    [Parameter(Mandatory)][string]$Python,
    [Parameter(Mandatory)][string]$RepoRoot,
    [Parameter(Mandatory)][string]$SimionExe,
    [Parameter(Mandatory)]$ResourceLease,
    [Parameter(Mandatory)][string]$RunId
  )
  $provider=Get-Content -LiteralPath $ProviderReceiptPath -Raw -Encoding UTF8|ConvertFrom-Json -Depth 60
  if([string]$provider.role-ne'orthogonal_accelerator_mrtof_runtime_receipt'-or
     [string]$provider.status-ne'published_standalone_response_bank'-or
     $null-eq$provider.standalone_response_bank){throw 'Accelerator provider lacks its standalone response bank.'}
  $bank=$provider.standalone_response_bank
  $ids=@($bank.response_ids|ForEach-Object{[int]$_})
  if($ids.Count-lt1-or@(Compare-Object $ids @(1..$ids.Count)).Count-ne0){throw 'Accelerator response namespace is incomplete.'}
  $binding=$provider.private_runtime_checkpoint
  if($null-eq$binding-or$null-eq$binding.checkpoint){throw 'Accelerator provider lacks its private runtime checkpoint.'}
  $checkpoint=(Resolve-Path -LiteralPath ([string]$binding.checkpoint.path)).Path
  $checkpointFile=Get-Item -LiteralPath $checkpoint
  if([int64]$checkpointFile.Length-ne[int64]$binding.checkpoint.bytes-or
     (Get-FileHash -LiteralPath $checkpoint -Algorithm SHA256).Hash-ne[string]$binding.checkpoint.sha256){throw 'Accelerator private runtime checkpoint record differs.'}
  $saved=Get-Content -LiteralPath $checkpoint -Raw -Encoding UTF8|ConvertFrom-Json -Depth 30
  $directory=(Resolve-Path -LiteralPath ([string]$saved.directory)).Path
  if($null-ne$Session.PSObject.Properties['accelerator_guards']){foreach($guard in $Session.accelerator_guards){$guard.Dispose()}}
  if($null-ne$Session.PSObject.Properties['accelerator_execution_alias']-and$Session.accelerator_execution_alias){Remove-RunExecutionAlias -ExecutionAlias $Session.accelerator_execution_alias -TargetDirectory ([string]$Session.accelerator_runtime_directory)}
  $alias=New-RunExecutionAlias -TargetDirectory $directory
  $Session|Add-Member -NotePropertyName accelerator_execution_alias -NotePropertyValue $alias.execution_alias -Force
  $Session|Add-Member -NotePropertyName accelerator_runtime_directory -NotePropertyValue $directory -Force
  $expected=@(0..$ids.Count|ForEach-Object{'orthogonal_accelerator_focus.pa'+$_})
  if([string]$saved.role-ne'orthogonal_accelerator_shared_runtime_checkpoint'-or[string]$saved.status-ne'prepared'-or
     [string]$saved.generation_sha256-ne[string]$provider.pa_family.generation_sha256-or
     [string]$saved.cache_key-ne[string]$provider.pa_family.cache_key-or
     [IO.Path]::GetFullPath([string]$binding.directory)-ne$directory-or
     [IO.Path]::GetFullPath([string]$binding.controller_path)-ne[IO.Path]::GetFullPath((Join-Path $directory $expected[0]))-or
     @($saved.members).Count-ne$expected.Count-or@(Compare-Object @($saved.members.name) $expected).Count-ne0){throw 'Accelerator runtime checkpoint belongs to another field identity.'}
  foreach($record in @($saved.members)){$file=Get-Item -LiteralPath (Join-Path $directory ([string]$record.name));if($file.Length-ne[int64]$record.bytes-or-not$file.IsReadOnly){throw 'Accelerator runtime checkpoint member differs.'}}
  $guards=@();foreach($name in $expected){$guards+=,[IO.File]::Open((Join-Path $directory $name),[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)}
  $Session|Add-Member -NotePropertyName accelerator_guards -NotePropertyValue $guards -Force
  $Session|Add-Member -NotePropertyName accelerator_checkpoint_path -NotePropertyValue $checkpoint -Force
  return [pscustomobject]@{
    controller_path=(Join-Path ([string]$alias.execution_alias) 'orthogonal_accelerator_focus.pa0')
    persistent_controller_path=(Join-Path $directory 'orthogonal_accelerator_focus.pa0')
    resource_lease=$ResourceLease;checkpoint_path=$checkpoint;reused=$true
  }
}

function Assert-NativeCorridorRuntimeSessionDirectory {
  param([Parameter(Mandatory)]$Session)
  if($null-ne$Session.PSObject.Properties['owner_run_directory']){
    $owner=[IO.Path]::GetFullPath([string]$Session.owner_run_directory)
    if((Split-Path (Split-Path $owner -Parent) -Leaf)-ne'runs'-or
       -not(Test-Path -LiteralPath (Join-Path $owner 'run_config.json') -PathType Leaf)){
      throw 'Managed native family requires its owning run configuration.'
    }
    $expected=Join-Path $owner 'runtime/native_corridor_family'
    if([IO.Path]::GetFullPath([string]$Session.directory)-ne$expected){throw 'Managed native family escapes its owner run.'}
    foreach($path in @($owner,(Join-Path $owner 'runtime'),$expected)){
      if((Test-Path -LiteralPath $path)-and((Get-Item -LiteralPath $path -Force).Attributes-band[IO.FileAttributes]::ReparsePoint)){
        throw 'Managed native family refuses redirected owner paths.'
      }
    }
    if(Test-Path -LiteralPath $expected){
      if(@(Get-ChildItem -LiteralPath $expected -Force|Where-Object{($_.Attributes-band[IO.FileAttributes]::ReparsePoint)-or$_.PSIsContainer}).Count){
        throw 'Managed native family refuses indirect members.'
      }
    }
    return $expected
  }
  throw 'Native workflow shared family requires a managed owner run.'
}

function Get-NativeCorridorRuntimeFamily {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)]$Session,[Parameter(Mandatory)]$CapacityWorkflowSession,
    [Parameter(Mandatory)][string]$BankGenerationDirectory,
    [Parameter(Mandatory)][string]$CacheKey,[Parameter(Mandatory)][string]$GenerationSha256,
    [Parameter(Mandatory)][string]$Python,[Parameter(Mandatory)][string]$RepoRoot,
    [Parameter(Mandatory)][string]$SimionExe,[Parameter(Mandatory)]$ResourceLease,
    [Parameter(Mandatory)][string]$RunId
  )
  if([string]$CapacityWorkflowSession.status-ne'active'-or[string]::IsNullOrWhiteSpace([string]$Session.lease_id)-or
     [string]$Session.lease_id-ne[string]$CapacityWorkflowSession.lease_id){
    throw 'Native workflow runtime requires its active capacity lease.'
  }
  return Get-ManagedNativeCorridorRuntimeFamily @PSBoundParameters
}

function Remove-NativeCorridorRuntimeSession {
  [CmdletBinding()]
  param([Parameter(Mandatory)]$Session)
  if($null-eq$Session.directory){return}
  $directory=Assert-NativeCorridorRuntimeSessionDirectory -Session $Session
  if($null-ne$Session.PSObject.Properties['owner_run_directory']){
    Suspend-NativeCorridorRuntimeSession -Session $Session
  }
  if($null-ne$Session.PSObject.Properties['guards']){
    foreach($guard in $Session.guards){$guard.Dispose()}
    $Session.guards=@()
  }
  if(Test-Path -LiteralPath $directory){Remove-Item -LiteralPath $directory -Recurse -Force -ErrorAction Stop}
  $Session.directory=$null;$Session.runtime=$null
}

function Suspend-NativeCorridorRuntimeSession {
  param([Parameter(Mandatory)]$Session)
  if($null-ne$Session.PSObject.Properties['guards']){
    foreach($guard in $Session.guards){$guard.Dispose()}
    $Session.guards=@()
  }
  if($null-ne$Session.PSObject.Properties['execution_alias']-and$Session.execution_alias){
    Remove-RunExecutionAlias -ExecutionAlias $Session.execution_alias -TargetDirectory $Session.directory
    $Session.execution_alias=$null
  }
  if($null-ne$Session.PSObject.Properties['accelerator_guards']){foreach($guard in $Session.accelerator_guards){$guard.Dispose()};$Session.accelerator_guards=@()}
  if($null-ne$Session.PSObject.Properties['accelerator_execution_alias']-and$Session.accelerator_execution_alias){
    Remove-RunExecutionAlias -ExecutionAlias $Session.accelerator_execution_alias -TargetDirectory ([string]$Session.accelerator_runtime_directory)
    $Session.accelerator_execution_alias=$null
  }
}

function Get-NativeFamilyGeneratorIdentity {
  param([Parameter(Mandatory)][string]$SimionExe)
  $identity=[ordered]@{}
  foreach($name in @('native_fast_adjust_runtime_support.ps1','assemble_native_fast_adjust_family.lua')){
    $identity[$name]=(Get-FileHash -LiteralPath (Join-Path $nativeCorridorRepoRoot 'common\simion' $name) -Algorithm SHA256).Hash
  }
  $identity.simion_binary_sha256=(Get-FileHash -LiteralPath $SimionExe -Algorithm SHA256).Hash
  return $identity
}

function Get-NativeRuntimeInventory {
  param([Parameter(Mandatory)][string]$Directory,[Parameter(Mandatory)][string]$Python,[Parameter(Mandatory)][string]$RepoRoot)
  $code=@'
import json,sys
from pathlib import Path
from common.contracts.file_identity import file_sha256_unbuffered
p=Path(sys.argv[1]); names=[f'mrtof_analyzer_corridor.pa{i}' for i in range(9)]
assert sorted(x.name for x in p.iterdir())==sorted(names), 'native runtime must contain exactly nine arrays'
print(json.dumps([dict(name=n,bytes=(p/n).stat().st_size,sha256=file_sha256_unbuffered(p/n)) for n in names]))
'@
  $text=@(Invoke-RunToolRootContext -RepoRoot $RepoRoot -Operation {
    & $Python -c $code $Directory
    if($LASTEXITCODE-ne0){throw 'Private native family persisted inventory failed.'}
  })
  return @(($text-join"`n")|ConvertFrom-Json)
}

function Protect-ManagedNativeFamily {
  param([Parameter(Mandatory)]$Session,[switch]$FreshGeneration)
  $directory=Assert-NativeCorridorRuntimeSessionDirectory -Session $Session
  if(@(Get-ChildItem -LiteralPath $directory -Force).Count-ne9){throw 'Managed native family is incomplete; retain for owner recovery.'}
  $Session|Add-Member -NotePropertyName guards -NotePropertyValue @() -Force
  foreach($index in 0..8){
    $path=Join-Path $directory ('mrtof_analyzer_corridor.pa'+$index)
    if($FreshGeneration){
      $stream=[IO.File]::Open($path,[IO.FileMode]::Open,[IO.FileAccess]::ReadWrite,[IO.FileShare]::Read)
      try{$stream.Flush($true)}finally{$stream.Dispose()}
      (Get-Item -LiteralPath $path).IsReadOnly=$true
    }elseif(-not(Get-Item -LiteralPath $path).IsReadOnly){throw 'Native checkpoint member is no longer read-only; payload retained.'}
    $Session.guards+=,[IO.File]::Open($path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
  }
}

function Open-NativeCorridorRuntimeCheckpoint {
  param([Parameter(Mandatory)]$Session,[Parameter(Mandatory)]$CapacityWorkflowSession,
    [Parameter(Mandatory)][string]$BankGenerationDirectory,[Parameter(Mandatory)][string]$CacheKey,
    [Parameter(Mandatory)][string]$GenerationSha256,[Parameter(Mandatory)][string]$Python,
    [Parameter(Mandatory)][string]$RepoRoot,[Parameter(Mandatory)][string]$SimionExe)
  if($CapacityWorkflowSession.status-ne'active'-or$Session.lease_id-ne$CapacityWorkflowSession.lease_id){throw 'Native checkpoint requires the current active workflow lease.'}
  $directory=Assert-NativeCorridorRuntimeSessionDirectory -Session $Session
  $checkpoint=Get-Content -LiteralPath $Session.checkpoint_path -Raw|ConvertFrom-Json -AsHashtable
  if($checkpoint.role-ne'mrtof_native_runtime_checkpoint'-or$checkpoint.status-ne'prepared'-or
     [IO.Path]::GetFullPath([string]$checkpoint.directory)-ne$directory-or
     $checkpoint.runtime_receipt.cache_key-ne$CacheKey-or$checkpoint.runtime_receipt.generation_sha256-ne$GenerationSha256-or
     [IO.Path]::GetFullPath([string]$checkpoint.runtime_receipt.generation_directory)-ne[IO.Path]::GetFullPath($BankGenerationDirectory)-or
     $checkpoint.runtime_receipt.controller_refine-ne'solutions={0}'-or
     [bool]$checkpoint.runtime_receipt.response_refine_performed-or
     [bool]$checkpoint.runtime_receipt.published_native_members_opened){
    throw 'Native checkpoint field or PA-family format identity differs; payload retained.'
  }
  try{
    Protect-ManagedNativeFamily -Session $Session
    $members=@($checkpoint.members)
    $expectedNames=@(0..8|ForEach-Object{'mrtof_analyzer_corridor.pa'+$_})
    if($members.Count-ne9-or@(Compare-Object @($members.name) $expectedNames).Count-ne0){throw 'Native checkpoint member inventory differs; payload retained.'}
    foreach($member in $members){
      $file=Get-Item -LiteralPath (Join-Path $directory ([string]$member.name))
      if([int64]$file.Length-ne[int64]$member.bytes){throw 'Native checkpoint member byte count differs; payload retained.'}
    }
    # The creation checkpoint already sealed every member SHA. Resume needs
    # only the consumed family, so byte counts plus read-only live guards are
    # sufficient; rereading roughly 75 GB on every controller start adds no
    # new consumed evidence.
    $Session|Add-Member -NotePropertyName members -NotePropertyValue $members -Force
    # Generator and SIMION hashes are provenance of the one-time materializer,
    # not the identity of an already sealed PA family.  Field identity is the
    # response-bank generation above; format identity is the pa0..pa8 inventory
    # and controller/response semantics.  Editing a generator comment or
    # updating the executable must not invalidate unchanged read-only arrays.
    $Session|Add-Member -NotePropertyName generator_identity -NotePropertyValue $checkpoint.generator_identity -Force
    $Session.runtime=[pscustomobject]@{receipt=$checkpoint.runtime_receipt;controller_path=(Join-Path $directory 'mrtof_analyzer_corridor.pa0')}
    $Session.resident_bytes=[int64](($members|Measure-Object -Property bytes -Sum).Sum)
  }catch{Suspend-NativeCorridorRuntimeSession -Session $Session;throw}
}

function Get-ManagedNativeCorridorRuntimeFamily {
  param([Parameter(Mandatory)]$Session,[Parameter(Mandatory)]$CapacityWorkflowSession,
    [Parameter(Mandatory)][string]$BankGenerationDirectory,[Parameter(Mandatory)][string]$CacheKey,
    [Parameter(Mandatory)][string]$GenerationSha256,[Parameter(Mandatory)][string]$Python,
    [Parameter(Mandatory)][string]$RepoRoot,[Parameter(Mandatory)][string]$SimionExe,
    [Parameter(Mandatory)]$ResourceLease,[Parameter(Mandatory)][string]$RunId)
  $directory=Assert-NativeCorridorRuntimeSessionDirectory -Session $Session
  $reused=$null-ne$Session.runtime
  if(-not$reused-and(Test-Path -LiteralPath $Session.checkpoint_path)){
    $open=@{};foreach($key in $PSBoundParameters.Keys){if($key-notin@('ResourceLease','RunId')){$open[$key]=$PSBoundParameters[$key]}}
    Open-NativeCorridorRuntimeCheckpoint @open
    $reused=$true
  }
  if(-not$reused-and(Test-Path -LiteralPath $directory)-and@(Get-ChildItem -LiteralPath $directory -Force).Count){
    throw 'Incomplete private native family retained for owner recovery; automatic reconstruction forbidden.'
  }
  New-Item -ItemType Directory -Path $directory -Force|Out-Null
  if($null-eq$Session.PSObject.Properties['execution_alias']-or-not$Session.execution_alias){
    $alias=New-RunExecutionAlias -TargetDirectory $directory
    $Session|Add-Member -NotePropertyName execution_alias -NotePropertyValue $alias.execution_alias -Force
  }
  if(-not$reused){
    $runtime=New-NativeCorridorRuntimeFamily -BankGenerationDirectory $BankGenerationDirectory `
      -CacheKey $CacheKey -GenerationSha256 $GenerationSha256 `
      -DestinationDirectory $Session.execution_alias -Python $Python -RepoRoot $RepoRoot -SimionExe $SimionExe `
      -ResourceLease $ResourceLease -RunId $RunId
    $ResourceLease=$runtime.resource_lease
    Protect-ManagedNativeFamily -Session $Session -FreshGeneration
    $members=@(Get-NativeRuntimeInventory -Directory $directory -Python $Python -RepoRoot $RepoRoot)
    $Session|Add-Member -NotePropertyName members -NotePropertyValue $members -Force
    $Session|Add-Member -NotePropertyName generator_identity -NotePropertyValue (Get-NativeFamilyGeneratorIdentity -SimionExe $SimionExe) -Force
    $runtime.receipt.controller_path=Join-Path $directory 'mrtof_analyzer_corridor.pa0'
    $Session.runtime=[pscustomobject]@{receipt=$runtime.receipt;controller_path=$runtime.receipt.controller_path}
    $Session.resident_bytes=[int64](($members|Measure-Object -Property bytes -Sum).Sum)
    Write-RunJson -Path ($Session.checkpoint_path+'.pending') -Depth 30 -Value ([ordered]@{
      schema_version=1;role='mrtof_native_runtime_checkpoint';status='prepared';directory=$directory
      generator_identity=$Session.generator_identity;members=$members;runtime_receipt=$runtime.receipt
    })
    Move-Item -LiteralPath ($Session.checkpoint_path+'.pending') -Destination $Session.checkpoint_path -Force
    $ownerOutputs=@((Join-Path $Session.owner_run_directory 'summary.json'),$Session.checkpoint_path)
    $acceleratorCheckpoint=Join-Path $Session.owner_run_directory 'results/accelerator_runtime_checkpoint.json'
    if(Test-Path -LiteralPath $acceleratorCheckpoint){$ownerOutputs+=$acceleratorCheckpoint}
    $bootstrapPath=Join-Path $Session.owner_run_directory 'results/workpoint_bootstrap.json'
    if(Test-Path -LiteralPath $bootstrapPath){$ownerOutputs+=$bootstrapPath}
    Write-VerifiedRunManifest -Python $Python -RepoRoot $RepoRoot -RunConfig $Session.owner_run_config `
      -Status checkpoint -Software @('SIMION 2020','Python 3.11','NumPy') `
      -Outputs $ownerOutputs | Out-Host
    $null=Invoke-RunCapacityLifecycleAdapter -Python $Python -RepoRoot $RepoRoot -Action register-writing `
      -ArtifactRoot $CapacityWorkflowSession.artifact_root -RunConfig $Session.owner_run_config
    $remaining=[math]::Max([int64]0,[int64]$CapacityWorkflowSession.committed_new_bytes-10*[int64]$runtime.receipt.source_raw.bytes)
    $null=Update-ArtifactWorkflowCapacitySession -Python $Python -RepoRoot $RepoRoot -Session $CapacityWorkflowSession -RemainingCommittedNewBytes $remaining
  }
  $runtime=$Session.runtime
  if($runtime.receipt.cache_key-ne$CacheKey-or$runtime.receipt.generation_sha256-ne$GenerationSha256-or
     [IO.Path]::GetFullPath([string]$runtime.receipt.generation_directory)-ne[IO.Path]::GetFullPath($BankGenerationDirectory)){
    throw 'Managed native family belongs to another bank; payload retained.'
  }
  if($Session.guards.Count-ne9){throw 'Managed native family has lost its guards.'}
  foreach($index in 0..8){
    $member=$Session.members[$index];$file=Get-Item -LiteralPath (Join-Path $directory $member.name)
    if(-not$Session.guards[$index].CanRead-or$file.Length-ne$member.bytes-or-not$file.IsReadOnly){throw 'Managed native family member protection differs.'}
  }
  $receipt=[ordered]@{};foreach($key in $runtime.receipt.Keys){$receipt[$key]=$runtime.receipt[$key]}
  $receipt.created_run_id=$runtime.receipt.run_id;$receipt.run_id=$RunId;$receipt.reused=$reused
  $receipt.capacity_lease_id=$Session.lease_id;$receipt.checkpoint_path=$Session.checkpoint_path
  return [pscustomobject]@{controller_path=(Join-Path $Session.execution_alias 'mrtof_analyzer_corridor.pa0');receipt=$receipt;resource_lease=$ResourceLease}
}

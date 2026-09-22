Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'

# Production adapter for run_two_prism_trial: only standalone source copies
# enter SIMION; the native family belongs to a flight or its sequential workflow.
function New-NativeCorridorRuntimeFamily {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$BankGenerationDirectory,
    [Parameter(Mandatory)][string]$DestinationDirectory,
    [Parameter(Mandatory)][string]$Python,
    [Parameter(Mandatory)][string]$RepoRoot,
    [Parameter(Mandatory)][string]$SimionExe,
    [Parameter(Mandatory)]$ResourceLease,
    [Parameter(Mandatory)][string]$RunId
  )
  $generation=(Resolve-Path -LiteralPath $BankGenerationDirectory).Path
  $destination=[IO.Path]::GetFullPath($DestinationDirectory)
  $code=@'
import json,sys
from pathlib import Path
from common.simion.pa_family_cache import probe_pa_family_cache, CacheDisposition
from common.simion.standalone_pa_response_set import validate_standalone_pa_response_set
p=Path(sys.argv[1]); m=json.loads((p/'cache_manifest.json').read_text())
assert m['identity']['geometry']['component_role']=='mrtof_native_corridor_detached_response_bank'
probe=probe_pa_family_cache(p.parents[2],m['identity'],expected_filenames=[x['name'] for x in m['files']])
assert probe.disposition is CacheDisposition.HIT and probe.generation_directory.resolve()==p.resolve(), 'bank must be the sealed current generation'
records=validate_standalone_pa_response_set(p,m,'mrtof_analyzer_corridor.standalone_responses.json',expected_response_ids=range(1,9),inventory_is_verified=True)
raw=next(x for x in m['files'] if x['name']=='mrtof_analyzer_corridor.pa#')
print(json.dumps({'cache_key':m['cache_key'],'generation_sha256':m['generation_sha256'],'raw':raw,'responses':[vars(x) for x in records]}))
'@
  $text=@(Invoke-RunToolRootContext -RepoRoot $RepoRoot -Operation {
    & $Python -c $code $generation
    if($LASTEXITCODE-ne0){throw 'Native corridor bank metadata validation failed.'}
  })
  $bank=($text-join"`n")|ConvertFrom-Json -Depth 40
  New-Item -ItemType Directory -Path $destination -Force|Out-Null
  if(@(Get-ChildItem -LiteralPath $destination -Force).Count-ne0){throw 'Native execution family directory must be empty.'}
  $controller=Join-Path $destination 'mrtof_analyzer_corridor.pa0'
  $privateRaw=$null;$privateResponse=$null
  try {
    $privateRaw=New-ShortPaCopy -Source (Join-Path $generation ([string]$bank.raw.name)) `
      -Destination (Join-Path $destination 'mrtof_analyzer_corridor.pa#') `
      -ExpectedBytes ([int64]$bank.raw.bytes) -ExpectedSha256 ([string]$bank.raw.sha256)
    $ResourceLease=Update-HostResourceStage -Lease $ResourceLease -Stage pa_refine `
      -Budget (Get-HostResourceBudget -Role SIMION -Stage pa_refine) -RetainedMemoryBytes 0
    & $SimionExe --nogui --noprompt lua (Join-Path $PSScriptRoot 'create_native_corridor_controller.lua') $privateRaw $controller | Out-Host
    if($LASTEXITCODE-ne0){throw 'Native execution controller construction failed.'}
    $ResourceLease=Update-HostResourceStage -Lease $ResourceLease -Stage mrtof_prepare `
      -Budget (Get-HostResourceBudget -Role SIMION -Stage mrtof_prepare) -RetainedMemoryBytes 0
    Remove-ShortPaCopy -Path $privateRaw;$privateRaw=$null
    foreach($record in $bank.responses){
      $privateResponse=New-ShortPaCopy -Source (Join-Path $generation ([string]$record.name)) `
        -Destination (Join-Path $destination 'source_response.pa') `
        -ExpectedBytes ([int64]$record.bytes) -ExpectedSha256 ([string]$record.sha256) -GuardDestinationReadOnly
      $native=Join-Path $destination ('mrtof_analyzer_corridor.pa{0}'-f$record.response_id)
      & $SimionExe --nogui --noprompt lua (Join-Path $PSScriptRoot 'assemble_native_local_family.lua') --append $privateResponse $native | Out-Host
      if($LASTEXITCODE-ne0){throw "Native execution response export failed: $($record.response_id)"}
      Remove-ShortPaCopy -Path $privateResponse;$privateResponse=$null
    }
    return [pscustomobject]@{
      controller_path=$controller;resource_lease=$ResourceLease
      receipt=[ordered]@{schema_version=1;role='mrtof_private_native_corridor_family';status='prepared';run_id=$RunId;
        cache_key=[string]$bank.cache_key;generation_sha256=[string]$bank.generation_sha256;generation_directory=$generation;
        source_responses=@($bank.responses);source_raw=$bank.raw;controller_path=$controller;
        response_refine_performed=$false;controller_refine='solutions={0}';published_native_members_opened=$false}
    }
  } finally {
    if($null-ne$privateResponse){Remove-ShortPaCopy -Path $privateResponse}
    if($null-ne$privateRaw){Remove-ShortPaCopy -Path $privateRaw}
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
}

function Get-NativeFamilyGeneratorIdentity {
  param([Parameter(Mandatory)][string]$SimionExe)
  $identity=[ordered]@{}
  foreach($name in @('create_native_corridor_controller.lua','assemble_native_local_family.lua')){
    $identity[$name]=(Get-FileHash -LiteralPath (Join-Path $PSScriptRoot $name) -Algorithm SHA256).Hash
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
  $generators=Get-NativeFamilyGeneratorIdentity -SimionExe $SimionExe
  if($checkpoint.role-ne'mrtof_native_runtime_checkpoint'-or$checkpoint.status-ne'prepared'-or
     [IO.Path]::GetFullPath([string]$checkpoint.directory)-ne$directory-or
     $checkpoint.runtime_receipt.cache_key-ne$CacheKey-or$checkpoint.runtime_receipt.generation_sha256-ne$GenerationSha256-or
     [IO.Path]::GetFullPath([string]$checkpoint.runtime_receipt.generation_directory)-ne[IO.Path]::GetFullPath($BankGenerationDirectory)-or
     ($checkpoint.generator_identity|ConvertTo-Json -Compress)-ne($generators|ConvertTo-Json -Compress)){
    throw 'Native checkpoint bank or family generator identity differs; payload retained.'
  }
  try{
    Protect-ManagedNativeFamily -Session $Session
    $members=@(Get-NativeRuntimeInventory -Directory $directory -Python $Python -RepoRoot $RepoRoot)
    if(($members|ConvertTo-Json -Compress)-ne($checkpoint.members|ConvertTo-Json -Compress)){throw 'Native checkpoint member SHA differs; payload retained.'}
    $Session|Add-Member -NotePropertyName members -NotePropertyValue $members -Force
    $Session|Add-Member -NotePropertyName generator_identity -NotePropertyValue $generators -Force
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
    $bootstrapPath=Join-Path $Session.owner_run_directory 'results/workpoint_bootstrap.json'
    if(Test-Path -LiteralPath $bootstrapPath){$ownerOutputs+=$bootstrapPath}
    Write-VerifiedRunManifest -Python $Python -RepoRoot $RepoRoot -RunConfig $Session.owner_run_config `
      -Status checkpoint -Software @('SIMION 2020','Python 3.11','NumPy') `
      -Outputs $ownerOutputs | Out-Host
    $null=Invoke-RunCapacityLifecycleAdapter -Python $Python -RepoRoot $RepoRoot -Action register-writing `
      -ArtifactRoot $CapacityWorkflowSession.artifact_root -RunConfig $Session.owner_run_config
    $remaining=[math]::Max(0,[int64]$CapacityWorkflowSession.committed_new_bytes-10*[int64]$runtime.receipt.source_raw.bytes)
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

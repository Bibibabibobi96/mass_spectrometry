Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path (Split-Path -Parent $PSScriptRoot) 'require_powershell7.ps1')
. (Join-Path (Split-Path -Parent $PSScriptRoot) 'host_execution_lease.ps1')

if(-not('RunTerminalSharedReadGuard'-as[type])){
  Add-Type -TypeDefinition @'
using System;
using System.IO;
using System.ComponentModel;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;
public sealed class RunTerminalSharedReadGuard : IDisposable {
  [StructLayout(LayoutKind.Sequential)]
  private struct Overlapped {
    public UIntPtr Internal, InternalHigh;
    public uint Offset, OffsetHigh;
    public IntPtr Event;
  }
  [DllImport("kernel32.dll", SetLastError=true)]
  private static extern bool LockFileEx(SafeFileHandle file, uint flags, uint reserved,
    uint low, uint high, ref Overlapped overlapped);
  [DllImport("kernel32.dll", SetLastError=true)]
  private static extern bool UnlockFileEx(SafeFileHandle file, uint reserved,
    uint low, uint high, ref Overlapped overlapped);
  private FileStream stream;
  private RunTerminalSharedReadGuard(FileStream file) { stream=file; }
  public static RunTerminalSharedReadGuard TryAcquire(FileStream file) {
    var overlapped=new Overlapped();
    // FAIL_IMMEDIATELY without EXCLUSIVE_LOCK requests a shared read lock.
    if(LockFileEx(file.SafeFileHandle,1,0,1,0,ref overlapped))
      return new RunTerminalSharedReadGuard(file);
    int error=Marshal.GetLastWin32Error();
    if(error==33) return null; // ERROR_LOCK_VIOLATION: an active publisher.
    throw new Win32Exception(error);
  }
  public void Dispose() {
    if(stream==null) return;
    var file=stream; stream=null;
    var overlapped=new Overlapped();
    try {
      if(!UnlockFileEx(file.SafeFileHandle,0,1,0,ref overlapped))
        throw new Win32Exception(Marshal.GetLastWin32Error());
    } finally { file.Dispose(); }
  }
}
'@
}

function Invoke-CompiledExecutionPlan {
  <# Execute only an existing owner's declared structured steps; owners retain native/resource lifecycle. #>
  [CmdletBinding()]
  param([Parameter(Mandatory)][string]$PlanPath,[Parameter(Mandatory)][string]$RepoRoot,[switch]$PrepareUnfrozenSources)
  $plan=Get-Content -LiteralPath $PlanPath -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable -Depth 100
  if($plan.role-ne'execution_dry_run'-or(-not$plan.safe_to_execute-and
      -not($PrepareUnfrozenSources-and$plan.status-eq'NEEDS_SOURCE_FREEZE'-and$plan.can_prepare_sources))){throw 'Compiled execution plan is not ready or its source is not frozen.'}
  $repository=[IO.Path]::GetFullPath($RepoRoot)
  $streams=[Collections.Generic.List[object]]::new()
  $directory=Join-Path ([IO.Path]::GetTempPath()) ('compiled_inputs_'+[guid]::NewGuid().ToString('N'))
  try{
    $contractPath=[IO.Path]::GetFullPath([string]$plan.execution_contract.path)
    if(-not$contractPath.StartsWith($repository+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)){throw 'Execution contract is outside the repository.'}
    if($plan.ContainsKey('owner_kind')-and$plan.owner_kind-eq'integration'){
      if($contractPath-ne[IO.Path]::GetFullPath((Join-Path $repository 'integrations/registry.json'))){throw 'Integration execution must use the registered owner contract.'}
    }else{
      $registryPath=Join-Path $repository 'config/project_registry.json'
      $registryStream=[IO.File]::Open($registryPath,'Open','Read','Read');$streams.Add($registryStream)
      $registry=Get-Content -LiteralPath $registryPath -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable -Depth 100
      $owners=@($registry.projects|Where-Object{$_.project_id-eq$plan.project_id})
      if($owners.Count-ne1-or-not$owners[0].contracts.execution){throw 'Project execution owner is not registered.'}
      $registered=Join-Path (Join-Path $repository ('projects/'+$plan.project_id)) ([string]$owners[0].contracts.execution)
      if($contractPath-ne[IO.Path]::GetFullPath($registered)){throw 'Execution contract differs from the registered owner.'}
    }
    $contractStream=[IO.File]::Open($contractPath,'Open','Read','Read');$streams.Add($contractStream)
    $hasher=[Security.Cryptography.SHA256]::Create()
    try{$actual=[Convert]::ToHexString($hasher.ComputeHash($contractStream))}finally{$hasher.Dispose()}
    if($actual-ne$plan.execution_contract.sha256){throw 'Execution profile changed after compilation.'}
    $contract=Get-Content -LiteralPath $contractPath -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable -Depth 100
    $entryRoot=Split-Path -Parent (Split-Path -Parent $contractPath)
    if($plan.ContainsKey('owner_kind')-and$plan.owner_kind-eq'integration'){
      $owners=@($contract.integrations|Where-Object{$_.integration_id-eq$plan.owner_id})
      if($owners.Count-ne1){throw 'Compiled integration owner is not registered.'}
      $workflows=@($owners[0].workflows|Where-Object{$_.workflow_id-eq$plan.profile_id})
      if($workflows.Count-ne1){throw 'Compiled integration workflow is not registered.'}
      $profiles=@(@{profile_id=$plan.profile_id;steps=@(@{step_id=$plan.profile_id;shell='powershell';entrypoint=$workflows[0].entrypoint;arguments=$workflows[0].arguments})})
      $entryRoot=$repository
    }else{$profiles=@($contract.profiles|Where-Object{$_.profile_id-eq$plan.profile_id})}
    if($profiles.Count-ne1){throw 'Compiled execution profile is not unique.'}
    if(@($plan.commands).Count-ne@($profiles[0].steps).Count){throw 'Compiled execution omits or adds owner steps.'}
    foreach($record in @($plan.planning_sources)+@($plan.binding_authorities)){
      $stream=[IO.File]::Open([string]$record.path,'Open','Read','Read');$streams.Add($stream)
      $hasher=[Security.Cryptography.SHA256]::Create()
      try{$actual=[Convert]::ToHexString($hasher.ComputeHash($stream))}finally{$hasher.Dispose()}
      if($stream.Length-ne[long]$record.bytes-or$actual-ne$record.sha256){throw "Compiled authority changed: $($record.path)"}
    }
    foreach($source in @($plan.binding_sources)){
      $streams.Add([IO.File]::Open([string]$source,'Open','Read','Read'))
    }
    New-Item -ItemType Directory -Path $directory|Out-Null
    foreach($record in @($plan.resolved_inputs)){
      if(-not$profiles[0].ContainsKey('fixed_inputs')-or
         $profiles[0].fixed_inputs[[string]$record.name]-ne$record.relative_path){throw 'Compiled fixed input is not declared by the profile.'}
      $stream=[IO.File]::Open([string]$record.path,'Open','Read','Read');$streams.Add($stream)
      $hasher=[Security.Cryptography.SHA256]::Create()
      try{$actual=[Convert]::ToHexString($hasher.ComputeHash($stream))}finally{$hasher.Dispose()}
      if($stream.Length-ne[long]$record.bytes-or$actual-ne$record.sha256){throw "Compiled input changed: $($record.path)"}
      $contentBytes=[Text.UTF8Encoding]::new($false).GetBytes([string]$record.content)
      $hasher=[Security.Cryptography.SHA256]::Create()
      try{$contentHash=[Convert]::ToHexString($hasher.ComputeHash($contentBytes))}finally{$hasher.Dispose()}
      if($contentBytes.Length-ne[long]$record.bytes-or$contentHash-ne$record.sha256){throw 'Compiled resolved definition differs from its frozen source.'}
      $destination=[IO.Path]::GetFullPath((Join-Path $directory ([string]$record.relative_path)))
      if(-not$destination.StartsWith($directory+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)){throw 'Compiled input destination escapes its private directory.'}
      New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination)|Out-Null
      [IO.File]::WriteAllText($destination,[string]$record.content,[Text.UTF8Encoding]::new($false))
    }
    $bundle=Join-Path $directory 'resolved_inputs.json'
    Write-RunJson -Path $bundle -Depth 100 -Value @{schema_version=1;role='compiled_execution_inputs';project_id=$(if($plan.ContainsKey('project_id')){$plan.project_id}else{$null});root=$directory;files=@($plan.resolved_inputs)}
    $runtime=Join-Path $directory 'resolved_runtime.json'
    if($null-ne$plan.resolved_runtime){Write-RunJson -Path $runtime -Depth 100 -Value $plan.resolved_runtime}
    $stepIndex=0
    foreach($command in $plan.commands){
      $steps=@($profiles[0].steps|Where-Object{$_.step_id-eq$command.step_id})
      if($steps.Count-ne1){throw 'Compiled step is not declared by its owner.'}
      $step=$steps[0]
      if($profiles[0].steps[$stepIndex].step_id-ne$command.step_id){throw 'Compiled execution changed owner step order.'}
      $stepIndex++
      $entry=[IO.Path]::GetFullPath((Join-Path $entryRoot ([string]$step.entrypoint)))
      if($entry-ne[IO.Path]::GetFullPath([string]$command.entrypoint)-or$step.shell-ne$command.shell){throw 'Compiled command differs from declared entrypoint.'}
      if(@($step.arguments).Count-ne@($command.arguments).Count){throw 'Compiled arguments differ from the declared owner inputs.'}
      for($argumentIndex=0;$argumentIndex-lt@($step.arguments).Count;$argumentIndex++){
        $template=[string]$step.arguments[$argumentIndex]
        if($template-notmatch'\{[A-Za-z_]\w*\}'-and$template-cne[string]$command.arguments[$argumentIndex]){throw 'Compiled arguments changed a fixed owner input.'}
      }
      $arguments=@($command.arguments|ForEach-Object{
        switch([string]$_){
          '__COMPILED_INPUTS__' {$bundle;break}
          '__COMPILED_CONFIGURATION__' {(Join-Path $directory 'config');break}
          '__COMPILED_RUNTIME__' {$runtime;break}
          default {[string]$_}
        }
      })
      Push-Location -LiteralPath $repository
      try{
        $global:LASTEXITCODE=0
        if($step.shell-eq'powershell'){
          $parameters=(Get-Command -Name $entry -ErrorAction Stop).Parameters
          $named=@{}
          for($index=0;$index-lt$arguments.Count;$index++){
            $name=[string]$arguments[$index]
            if(-not$name.StartsWith('-')-or-not$parameters.ContainsKey($name.Substring(1))){throw "Compiled PowerShell argument is not a declared parameter: $name"}
            $name=$name.Substring(1)
            if($named.ContainsKey($name)){throw "Repeated compiled parameter: $name"}
            if($parameters[$name].ParameterType-eq[Management.Automation.SwitchParameter]){$named[$name]=$true}
            else{
              $index++
              if($index-ge$arguments.Count){throw "Compiled parameter value is missing: $name"}
              $named[$name]=$arguments[$index]
            }
          }
          & $entry @named
        }
        elseif($step.shell-eq'python'){
          $module=[IO.Path]::GetRelativePath($repository,$entry).Replace('\','.').Replace('/','.').Substring(0,[IO.Path]::GetRelativePath($repository,$entry).Length-3)
          if(-not$plan.ContainsKey('python_executable')-or$plan.python_executable-isnot[string]-or
             -not[IO.Path]::IsPathFullyQualified($plan.python_executable)-or
             -not(Test-Path -LiteralPath $plan.python_executable -PathType Leaf)){
            throw 'Compiled Python interpreter is missing or unavailable; recompile with the intended Python executable.'
          }
          & $plan.python_executable -m $module @arguments
        }else{throw 'Unsupported declared execution shell.'}
        if(-not$?-or$LASTEXITCODE-ne0){throw "Compiled owner step failed: $($command.step_id) (exit $LASTEXITCODE)"}
      }finally{Pop-Location}
    }
    Write-Output 'COMPILED_EXECUTION=COMPLETED SCIENCE=not_evaluated__see_owner_results'
  }finally{
    foreach($stream in $streams){$stream.Dispose()}
    if(Test-Path -LiteralPath $directory){Remove-Item -LiteralPath $directory -Recurse -Force}
  }
}

function Enter-RunTerminalConsumptionGuard {
  <# Shared readers and the existing exclusive publisher use the same byte.
     Windows LockFileEx is required because FileStream.Lock is exclusive.
     See Microsoft fileapi/LockFileEx (checked 2026-10-30); no journal or PA
     protection changes are implied by admitting another read-only consumer. #>
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$RunDirectory,
    [ValidateRange(0,3600)][double]$TimeoutSeconds=30
  )
  if(-not$IsWindows){throw 'Terminal consumption guard requires Windows byte-range locking.'}
  $root=(Resolve-Path -LiteralPath $RunDirectory).Path
  $stream=[IO.File]::Open((Join-Path $root '.run_terminal_publication.lock'),
    [IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::ReadWrite)
  $guard=$null
  try{
    # Windows permits locking beyond EOF; readers must not initialize a byte
    # while another shared consumer already owns its read lock.
    $deadline=[DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while($null-eq$guard){
      $guard=[RunTerminalSharedReadGuard]::TryAcquire($stream)
      if($null-eq$guard){
        if([DateTime]::UtcNow-ge$deadline){throw "Terminal publication is busy: $root"}
        Start-Sleep -Milliseconds 50
      }
    }
    if(Test-Path -LiteralPath (Join-Path $root '.run_terminal_publication.json')){
      throw 'Run terminal publication is incomplete; replay its journal.'
    }
    return $guard
  }catch{if($null-ne$guard){$guard.Dispose()}else{$stream.Dispose()};throw}
}

function Invoke-RunToolRootContext {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$RepoRoot,
    [Parameter(Mandatory)][scriptblock]$Operation,
    [Collections.IDictionary]$Environment=@{}
  )
  $root=(Resolve-Path -LiteralPath $RepoRoot).Path
  $names=@(@('PYTHONPATH','PYTHONNOUSERSITE','PYTHONDONTWRITEBYTECODE')+@($Environment.Keys)|Sort-Object -Unique)
  $saved=Save-RunEnvironment -Names $names
  try{
    $env:PYTHONPATH=$root
    $env:PYTHONNOUSERSITE='1'
    $env:PYTHONDONTWRITEBYTECODE='1'
    foreach($name in $Environment.Keys){
      if($null-eq$Environment[$name]){Remove-Item -LiteralPath ('Env:\'+$name) -ErrorAction SilentlyContinue}
      else{[Environment]::SetEnvironmentVariable([string]$name,[string]$Environment[$name],'Process')}
    }
    Push-Location -LiteralPath $root
    try{& $Operation}finally{Pop-Location}
  }finally{
    Restore-RunEnvironment -Names $names -Snapshot $saved
  }
}

function Get-VerifiedRunManifestInputRecord {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][System.Collections.IDictionary]$Records,
    [Parameter(Mandatory)][string]$Name,
    [Parameter(Mandatory)][string]$Label
  )
  if(-not$Records.Contains($Name)-or-not($Records[$Name]-is[System.Collections.IDictionary])){
    throw "Run manifest lacks the required $Label input record."
  }
  $record=$Records[$Name]
  if(-not$record.exists-or[string]::IsNullOrWhiteSpace([string]$record.path)-or
     [string]::IsNullOrWhiteSpace([string]$record.sha256)){
    throw "Run manifest has an incomplete $Label input record."
  }
  return $record
}

function Assert-VerifiedRunRecordHash {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$Path,
    [Parameter(Mandatory)][System.Collections.IDictionary]$Record,
    [Parameter(Mandatory)][string]$Label
  )
  $actual=(Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
  if($actual-ne([string]$Record.sha256).ToUpperInvariant()){
    throw "Frozen $Label differs from the verified parent run manifest."
  }
}

function Invoke-RunCapacityCommand {
  <# Preserve native capacity diagnostics without mixing them into JSON stdout. #>
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$Python,[Parameter(Mandatory)][string]$RepoRoot,
    [Parameter(Mandatory)][string[]]$Arguments,[Parameter(Mandatory)][string]$FailureLabel
  )
  Invoke-RunToolRootContext -RepoRoot $RepoRoot -Operation {
    $PSNativeCommandUseErrorActionPreference=$false
    $captured=@(& $Python @Arguments 2>&1)
    $exitCode=$LASTEXITCODE
    $stdout=@($captured|Where-Object{$_-isnot[Management.Automation.ErrorRecord]})
    $stderr=@($captured|Where-Object{$_-is[Management.Automation.ErrorRecord]})
    if($exitCode-ne0){
      $details=@{stdout=($stdout-join"`n");stderr=($stderr-join"`n")}
      foreach($stream in @('stdout','stderr')){
        if($details[$stream].Length-gt4096){$details[$stream]='[truncated tail] '+$details[$stream].Substring($details[$stream].Length-4096)}
      }
      $failure=[InvalidOperationException]::new("$FailureLabel; exit_code=$exitCode; stdout=$($details.stdout); stderr=$($details.stderr)")
      $failure.Data['native_exit_code']=$exitCode
      throw $failure
    }
    foreach($errorLine in $stderr){Write-Error -Message ([string]$errorLine) -ErrorAction Continue}
    $stdout
  }
}

function Invoke-ArtifactCapacityGate {
  <# Invoke the repository-owned artifact reconciler and require an applied
     receipt.  This is deliberately a lifecycle adapter: projects supply their
     own protected paths and cache identities; global watermarks come only
     from artifact_capacity_policy.json. #>
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$Python,
    [Parameter(Mandatory)][string]$RepoRoot,
    [Parameter(Mandatory)][string]$ArtifactRoot,
    [string[]]$ProtectedPaths=@(),
    [string[]]$ProtectedCacheKeys=@(),
    [string]$CapacityProtectionLeaseId='',
    [ValidateSet('startup','maintenance')][string]$ExecutionMode='startup',
    [Nullable[double]]$MaintenanceTargetGiB=$null
  )
  if($null-ne$MaintenanceTargetGiB-and$ExecutionMode-ne'maintenance'){
    throw 'MaintenanceTargetGiB requires maintenance execution mode.'
  }
  if($ExecutionMode-eq'startup'-and[string]::IsNullOrWhiteSpace($CapacityProtectionLeaseId)){
    throw 'Artifact capacity startup requires CapacityProtectionLeaseId.'
  }
  # Capacity work uses shared host admission and inherits the caller's permit.
  # Light admission is not a cache-consumption or deletion lock; the reconciler
  # must separately enforce artifact protection and retention rules.
  $capacityLease=Enter-HostExecutionLease -Role GATE
  $capacityFailure=$null
  try{
  $arguments=@(
    '-m','common.contracts.reconcile_artifact_capacity',
    '--artifact-root',$ArtifactRoot,
    '--execution-mode',$ExecutionMode,
    '--capacity-ledger',(Join-Path $ArtifactRoot 'common\capacity_ledger.json'),
    '--apply'
  )
  if($null-ne$MaintenanceTargetGiB){
    $arguments+=@('--maintenance-target-gib',([string]$MaintenanceTargetGiB))
  }
  foreach($path in @($ProtectedPaths|Where-Object{ -not [string]::IsNullOrWhiteSpace($_) }|Select-Object -Unique)){
    $arguments+=@('--protect-path',$path)
  }
  foreach($key in @($ProtectedCacheKeys|Select-Object -Unique)){
    if($key-notmatch '^[0-9a-fA-F]{64}$'){throw 'Protected cache key must be one SHA-256 key.'}
    $arguments+=@('--protect-cache-key',$key)
  }
  if(-not[string]::IsNullOrWhiteSpace($CapacityProtectionLeaseId)){
    $arguments+=@('--capacity-protection-lease-id',$CapacityProtectionLeaseId)
  }
  $output=@(Invoke-RunCapacityCommand -Python $Python -RepoRoot $RepoRoot -Arguments $arguments `
    -FailureLabel 'Artifact capacity gate failed')
  $receipt=((@($output)-join "`n")|ConvertFrom-Json)
  if($receipt.satisfied_after_apply -ne $true){
    if($ExecutionMode-eq'maintenance'){
      # The CLI's ordinary maintenance output is aggregate-only; exact disposal
      # records remain in their owner receipts, not on the launcher hot path.
      $message=("Artifact capacity gate blocked maintenance: CAPACITY_TARGET_NOT_MET; resident_bytes={0}; free_bytes={1}; capacity_gap_bytes={2}; target_bytes={3}; removed_bytes={4}" -f $receipt.resident_bytes,$receipt.free_bytes,$receipt.capacity_gap_bytes,$receipt.target_bytes,$receipt.removed.bytes)
    }else{
      $reason=[string]$receipt.blocking_reason
      if([string]::IsNullOrWhiteSpace($reason)){$reason='UNSPECIFIED'}
      $message=("Artifact capacity gate blocked startup: {0}; resident_bytes={1}; active_commitment_bytes={2}; projected_bytes={3}; target_bytes={4}" -f $reason,$receipt.resident_bytes,$receipt.total_active_lease_committed_new_bytes,$receipt.projected_bytes,$receipt.target_bytes)
    }
    $failure=[InvalidOperationException]::new($message)
    $failure.Data['capacity_receipt']=$receipt
    throw $failure
  }
  # The JSON root is one object; NoEnumerate wraps it and changes nested-array access.
  Write-Output $receipt
  }catch{
    $capacityFailure=$_
    throw
  }finally{
    try{Exit-HostExecutionLease -Lease $capacityLease}catch{
      if($null-eq$capacityFailure){throw}
      $capacityFailure.Exception.Data['host_execution_lease_cleanup']=@{status='failed';error=$_.Exception.Message}
      Write-Warning -WarningAction Continue "CAPACITY_HOST_LEASE_CLEANUP_FAILED error=$($_.Exception.Message)"
    }
  }
}

function Invoke-ArtifactWorkflowCapacityAdmission {
  <# A workflow owns the lease, so it can renew that same protection while
     requesting one maintenance pass. A direct gate remains one decision. #>
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$Python,[Parameter(Mandatory)][string]$RepoRoot,
    [Parameter(Mandatory)][pscustomobject]$Session
  )
  $parameters=@{Python=$Python;RepoRoot=$RepoRoot;ArtifactRoot=[string]$Session.artifact_root;
    ProtectedPaths=@($Session.protected_paths);ProtectedCacheKeys=@($Session.protected_cache_keys);
    CapacityProtectionLeaseId=[string]$Session.lease_id}
  try{return (Invoke-ArtifactCapacityGate @parameters -ExecutionMode startup)}catch{
    $initialFailure=$_
    if($null-ne$initialFailure.Exception.Data['host_execution_lease_cleanup']){throw}
    $receipt=$initialFailure.Exception.Data['capacity_receipt']
    if($null-eq$receipt-or
       $null-eq$receipt.PSObject.Properties['role']-or$receipt.role-ne'artifact_capacity_gate'-or
       $null-eq$receipt.PSObject.Properties['execution_mode']-or$receipt.execution_mode-ne'startup'-or
       $null-eq$receipt.PSObject.Properties['capacity_protection_lease_id']-or
       $receipt.capacity_protection_lease_id-ne$Session.lease_id-or
       $null-eq$receipt.PSObject.Properties['blocking_reason']-or
       $receipt.blocking_reason-notin@('TARGET_CAPACITY_EXCEEDED','MINIMUM_FREE_CAPACITY_UNAVAILABLE')){throw}
  }
  $timer=[Diagnostics.Stopwatch]::StartNew()
  $attempt=[ordered]@{trigger_reason=[string]$receipt.blocking_reason;initial_admission=$receipt;
    stage='renew_before_maintenance';maintenance=$null;elapsed_seconds=$null}
  try{
    # Renewal never changes commitment, scope or the original closure deadline.
    Update-ArtifactWorkflowCapacitySession -Python $Python -RepoRoot $RepoRoot -Session $Session|Out-Null
    $attempt.stage='maintenance'
    try{$attempt.maintenance=Invoke-ArtifactCapacityGate @parameters -ExecutionMode maintenance}catch{
      if($null-ne$_.Exception.Data['host_execution_lease_cleanup']){throw}
      $maintenance=$_.Exception.Data['capacity_receipt']
      if($null-eq$maintenance-or
         $null-eq$maintenance.PSObject.Properties['measurement_mode']-or
         $maintenance.measurement_mode-ne'LEDGER_MAINTENANCE'){throw}
      # An applied pass may still lack space. Only a fresh startup decision can
      # admit this workflow; an owner-local failure is retained in the receipt.
      $attempt.maintenance=$maintenance
    }
    $attempt.stage='renew_before_readmission'
    Update-ArtifactWorkflowCapacitySession -Python $Python -RepoRoot $RepoRoot -Session $Session|Out-Null
    $attempt.stage='readmission'
    $admission=Invoke-ArtifactCapacityGate @parameters -ExecutionMode startup
    $attempt.stage='admitted'
    $admission|Add-Member -NotePropertyName pressure_maintenance -NotePropertyValue $attempt
    return $admission
  }catch{
    $failure=[InvalidOperationException]::new(
      "Capacity pressure relief failed at $($attempt.stage) after $($attempt.trigger_reason): $($_.Exception.Message)",
      $_.Exception)
    $failure.Data['pressure_maintenance']=$attempt
    $failure.Data['initial_admission_error']=$initialFailure.Exception.Message
    throw $failure
  }finally{
    $timer.Stop()
    $attempt.elapsed_seconds=$timer.Elapsed.TotalSeconds
  }
}

function Invoke-RunCapacityLifecycleAdapter {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$Python,
    [Parameter(Mandatory)][string]$RepoRoot,
    [Parameter(Mandatory)][ValidateSet('register-writing-range','register-writing','assert-retention','finalize-ready')][string]$Action,
    [Parameter(Mandatory)][string]$ArtifactRoot,
    [string]$RunConfig='',
    [string]$RunDirectory=''
  )
  if($Action-eq'register-writing-range'){
    if([string]::IsNullOrWhiteSpace($RunDirectory)-or-not[string]::IsNullOrWhiteSpace($RunConfig)){
      throw 'register-writing-range requires RunDirectory only.'
    }
    $runArgument=@('--run-directory',$RunDirectory)
  }else{
    if([string]::IsNullOrWhiteSpace($RunConfig)-or-not[string]::IsNullOrWhiteSpace($RunDirectory)){
      throw "$Action requires RunConfig only."
    }
    $runArgument=@('--run-config',$RunConfig)
  }
  $output=@(Invoke-RunToolRootContext -RepoRoot $RepoRoot -Operation {
    & $Python -m common.contracts.run_capacity_lifecycle --action $Action `
      --artifact-root $ArtifactRoot @runArgument
    if($LASTEXITCODE-ne 0){throw "Run capacity lifecycle $Action failed."}
  })
  return ((@($output)-join "`n")|ConvertFrom-Json)
}

function Add-ArtifactWorkflowSourceProtection {
  <# Source references use their frozen owner; they never become new payload
     reservations in the consumer root. Hold publication guards until pinned. #>
  param([string]$Python,[string]$RepoRoot,[pscustomobject]$Session,[object[]]$SourceReferences=@(),
    [Parameter(Mandatory)][AllowEmptyCollection()][Collections.Generic.List[object]]$Guards)
  $groups=@{};$touched=[Collections.Generic.HashSet[string]]::new()
  $resolver=@'
import json,sys
from pathlib import Path
from common.contracts.run_capacity_lifecycle import resolve_consumed_run_capacity_owner
print(json.dumps(resolve_consumed_run_capacity_owner(json.loads(sys.argv[1]),consumer_artifact_root=Path(sys.argv[2]),stopped_receipt_record=json.loads(sys.argv[3]))))
'@
    foreach($reference in $SourceReferences){
      if($reference-isnot[Collections.IDictionary]-or-not$reference.Contains('manifest_record')){
        throw 'Source protection requires an explicit manifest_record.'
      }
      $record=$reference.manifest_record
      $Guards.Add((Enter-RunTerminalConsumptionGuard -RunDirectory (Split-Path -Parent $record.path)))
      $text=@(Invoke-RunCapacityCommand -Python $Python -RepoRoot $RepoRoot `
        -Arguments @('-B','-c',$resolver,($record|ConvertTo-Json -Depth 16 -Compress),$Session.artifact_root,$(if($reference.Contains('stopped_receipt_record')){$reference.stopped_receipt_record|ConvertTo-Json -Depth 16 -Compress}else{'null'})) -FailureLabel 'Source capacity owner verification failed')
      $source=($text-join"`n")|ConvertFrom-Json
      $root=[string]$source.artifact_root
      if(-not$groups.ContainsKey($root)){$groups[$root]=@{paths=@();keys=@()}}
      $groups[$root].paths+=@([string]$source.run_directory)
      if($reference.Contains('protected_paths')){$groups[$root].paths+=@($reference.protected_paths)}
      if($reference.Contains('protected_cache_keys')){$groups[$root].keys+=@($reference.protected_cache_keys)}
    }
    foreach($root in @($groups.Keys|Sort-Object)){
      $paths=@($groups[$root].paths|Select-Object -Unique);$keys=@($groups[$root].keys|Select-Object -Unique)
      if($root-ieq$Session.artifact_root){
        $Session.protected_paths=@(@($Session.protected_paths)+$paths|Select-Object -Unique)
        $Session.protected_cache_keys=@(@($Session.protected_cache_keys)+$keys|Select-Object -Unique)
        continue
      }
      $existing=@($Session.source_protection_leases|Where-Object{$_.artifact_root-ieq$root-and$_.status-eq'active'})
      if($existing.Count){
        $lease=$existing[0];$operation='--renew-protection-lease'
      }else{
        $lease=[pscustomobject]@{artifact_root=$root;lease_id=($Session.lease_id+'-source-'+$Session.source_protection_leases.Count);
          status='active';protected_paths=@();protected_cache_keys=@()}
        $Session.source_protection_leases=@($Session.source_protection_leases)+@($lease)
        $operation='--create-protection-lease'
      }
      $arguments=@('-m','common.contracts.reconcile_artifact_capacity','--artifact-root',$root,
        $operation,$lease.lease_id,'--lease-owner',$Session.owner,'--lease-ttl-seconds',([string]$Session.lease_ttl_seconds),
        '--committed-new-bytes','0')
      foreach($path in $paths){$arguments+=@('--protect-path',$path)}
      foreach($key in $keys){$arguments+=@('--protect-cache-key',$key)}
      $output=@(Invoke-RunCapacityCommand -Python $Python -RepoRoot $RepoRoot -Arguments $arguments -FailureLabel 'Source capacity protection failed')
      $document=($output-join"`n")|ConvertFrom-Json
      $lease.protected_paths=@($document.protected_paths|ForEach-Object{Join-Path $root $_})
      $lease.protected_cache_keys=@($document.protected_cache_keys)
      $null=$touched.Add([string]$lease.lease_id)
    }
  return [pscustomobject]@{renewed_source_lease_ids=@($touched)}
}

function Enter-ArtifactWorkflowCapacitySession {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$Python,[Parameter(Mandatory)][string]$RepoRoot,
    [Parameter(Mandatory)][string]$ArtifactRoot,[Parameter(Mandatory)][string]$RunDirectory,
    [Parameter(Mandatory)][long]$CommittedNewBytes,[string]$Owner='',
    [int]$LeaseTtlSeconds=21600,[string[]]$ProtectedPaths=@(),
    [string[]]$ProtectedCacheKeys=@(),[object[]]$SourceReferences=@()
  )
  if($CommittedNewBytes-lt0-or$LeaseTtlSeconds-le0){throw 'Workflow capacity session requires nonnegative bytes and a positive TTL.'}
  $leaseId='workflow-'+[guid]::NewGuid().ToString('N')
  if([string]::IsNullOrWhiteSpace($Owner)){$Owner="run-artifact-support:$([IO.Path]::GetFileName($RunDirectory))"}
  if(-not(Get-Command Resolve-WorkspacePaths -ErrorAction SilentlyContinue)){
    . (Join-Path $PSScriptRoot '../paths/workspace_paths.ps1')
  }
  $ArtifactRoot=(Resolve-WorkspacePaths -SourceRoot $RepoRoot -ArtifactRoot $ArtifactRoot -Python $Python).artifact_root
  $paths=@([IO.Path]::GetFullPath($RunDirectory))+$ProtectedPaths|Select-Object -Unique
  $session=[pscustomobject]@{schema_version=1;role='artifact_workflow_capacity_session';status='active';
    artifact_root=$ArtifactRoot;lease_id=$leaseId;owner=$Owner;lease_ttl_seconds=$LeaseTtlSeconds;
    committed_new_bytes=$CommittedNewBytes;protected_paths=@($paths);protected_cache_keys=@($ProtectedCacheKeys|Select-Object -Unique);
    source_protection_leases=@();lease=$null;startup_gate=$null}
  $sourceGuards=[Collections.Generic.List[object]]::new()
  try{
  $null=Add-ArtifactWorkflowSourceProtection -Python $Python -RepoRoot $RepoRoot -Session $session -SourceReferences $SourceReferences -Guards $sourceGuards
  $arguments=@('-m','common.contracts.reconcile_artifact_capacity','--artifact-root',$ArtifactRoot,
    '--create-protection-lease',$leaseId,'--lease-owner',$Owner,
    '--lease-ttl-seconds',([string]$LeaseTtlSeconds),'--committed-new-bytes',([string]$CommittedNewBytes))
  foreach($path in $session.protected_paths){$arguments+=@('--protect-path',$path)}
  foreach($key in $session.protected_cache_keys){$arguments+=@('--protect-cache-key',$key)}
    $leaseOutput=@(Invoke-RunCapacityCommand -Python $Python -RepoRoot $RepoRoot -Arguments $arguments `
      -FailureLabel 'Workflow capacity lease creation failed')
    # The active lease is the single reservation source, including pressure relief.
    $session.lease=(@($leaseOutput)-join"`n")|ConvertFrom-Json
    $session.protected_paths=@($session.lease.protected_paths|ForEach-Object{Join-Path $ArtifactRoot $_})
    $session.protected_cache_keys=@($session.lease.protected_cache_keys)
    $session.startup_gate=Invoke-ArtifactWorkflowCapacityAdmission -Python $Python -RepoRoot $RepoRoot -Session $session
    return $session
  }catch{
    $sessionFailure=$_
    try{
      Exit-ArtifactWorkflowCapacitySession -Python $Python -RepoRoot $RepoRoot -Session $session|Out-Null
      $sessionFailure.Exception.Data['capacity_lease_cleanup']=@{lease_id=$leaseId;status='released'}
    }catch{
      $sessionFailure.Exception.Data['capacity_lease_cleanup']=@{lease_id=$leaseId;status='failed';error=$_.Exception.Message}
      $sessionFailure.Exception.Data['capacity_session']=$session
      Write-Warning "CAPACITY_WORKFLOW_LEASE_CLEANUP_FAILED lease_id=$leaseId error=$($_.Exception.Message)"
    }
    throw $sessionFailure
  }finally{foreach($guard in $sourceGuards){$guard.Dispose()}}
}

function Update-ArtifactWorkflowCapacitySession {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$Python,[Parameter(Mandatory)][string]$RepoRoot,
    [Parameter(Mandatory)][pscustomobject]$Session,[string[]]$ProtectedPaths=@(),
    [string[]]$ProtectedCacheKeys=@(),[Nullable[long]]$RemainingCommittedNewBytes=$null,[object[]]$SourceReferences=@()
  )
  if([string]$Session.status-ne'active'){throw 'Workflow capacity session is not active.'}
  if($null-ne$RemainingCommittedNewBytes-and$RemainingCommittedNewBytes-lt0){throw 'Remaining committed bytes must be nonnegative.'}
  [int64]$priorCommitment=$Session.committed_new_bytes
  if($null-eq$Session.PSObject.Properties['source_protection_leases']){$Session|Add-Member -NotePropertyName source_protection_leases -NotePropertyValue @()}
  $sourceGuards=[Collections.Generic.List[object]]::new()
  try{
  $sourceUpdate=Add-ArtifactWorkflowSourceProtection -Python $Python -RepoRoot $RepoRoot -Session $Session -SourceReferences $SourceReferences -Guards $sourceGuards
  foreach($source in $Session.source_protection_leases){
    if($source.status-ne'active'-or$sourceUpdate.renewed_source_lease_ids-contains$source.lease_id){continue}
    $null=Invoke-RunCapacityCommand -Python $Python -RepoRoot $RepoRoot -Arguments @(
      '-m','common.contracts.reconcile_artifact_capacity','--artifact-root',$source.artifact_root,
      '--renew-protection-lease',$source.lease_id,'--lease-owner',$Session.owner,
      '--lease-ttl-seconds',([string]$Session.lease_ttl_seconds),'--committed-new-bytes','0') -FailureLabel 'Source protection renewal failed'
  }
  $arguments=@('-m','common.contracts.reconcile_artifact_capacity','--artifact-root',[string]$Session.artifact_root,
    '--renew-protection-lease',[string]$Session.lease_id,'--lease-owner',[string]$Session.owner,
    '--lease-ttl-seconds',([string]$Session.lease_ttl_seconds))
  if($null-ne$RemainingCommittedNewBytes){$arguments+=@('--committed-new-bytes',([string]$RemainingCommittedNewBytes))}
  foreach($path in @($Session.protected_paths)+@($ProtectedPaths)){$arguments+=@('--protect-path',$path)}
  foreach($key in @($Session.protected_cache_keys)+@($ProtectedCacheKeys)){$arguments+=@('--protect-cache-key',$key)}
  $output=@(Invoke-RunCapacityCommand -Python $Python -RepoRoot $RepoRoot -Arguments $arguments `
    -FailureLabel 'Workflow capacity lease renewal failed')
  if($null-ne$RemainingCommittedNewBytes){$Session.committed_new_bytes=[int64]$RemainingCommittedNewBytes}
  $renewal=($output-join"`n")|ConvertFrom-Json
  $Session.lease=$renewal
  $Session.protected_paths=@($renewal.protected_paths|ForEach-Object{Join-Path $Session.artifact_root $_})
  $Session.protected_cache_keys=@($renewal.protected_cache_keys)
  $gate=$null
  if($null-ne$RemainingCommittedNewBytes-and[int64]$RemainingCommittedNewBytes-gt$priorCommitment){
    # The larger commitment is already durable.  Re-admission may fail, but
    # failure leaves the conservative larger reservation visible to peers.
    $gate=Invoke-ArtifactWorkflowCapacityAdmission -Python $Python -RepoRoot $RepoRoot -Session $Session
  }
  return [pscustomobject]@{session=$Session;renewal=$renewal;admission_gate=$gate}
  }finally{foreach($guard in $sourceGuards){$guard.Dispose()}}
}

function Exit-ArtifactWorkflowCapacitySession {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$Python,[Parameter(Mandatory)][string]$RepoRoot,
    [Parameter(Mandatory)][pscustomobject]$Session
  )
  if([string]$Session.status-ne'active'){return [pscustomobject]@{deleted=$false;status=[string]$Session.status}}
  $errors=[Collections.Generic.List[object]]::new();$output=@()
  if($null-ne$Session.PSObject.Properties['source_protection_leases']){
    foreach($source in $Session.source_protection_leases){
      if($source.status-ne'active'){continue}
      try{
        $null=Invoke-RunCapacityCommand -Python $Python -RepoRoot $RepoRoot -Arguments @(
          '-m','common.contracts.reconcile_artifact_capacity','--artifact-root',$source.artifact_root,
          '--delete-protection-lease',$source.lease_id) -FailureLabel 'Source protection release failed'
        $source.status='released'
      }catch{$errors.Add($_)}
    }
  }
  try{
    $output=@(Invoke-RunCapacityCommand -Python $Python -RepoRoot $RepoRoot -Arguments @(
      '-m','common.contracts.reconcile_artifact_capacity','--artifact-root',[string]$Session.artifact_root,
      '--delete-protection-lease',[string]$Session.lease_id) -FailureLabel 'Workflow capacity lease deletion failed')
  }catch{$errors.Add($_)}
  if($errors.Count){
    $failure=$errors[0];$failure.Exception.Data['capacity_session']=$Session
    $failure.Exception.Data['capacity_release_errors']=@($errors|ForEach-Object{$_.Exception.Message})
    throw $failure
  }
  $Session.status='released'
  return ((@($output)-join"`n")|ConvertFrom-Json)
}

function Write-RunJson {
  [CmdletBinding()]
  param([Parameter(Mandatory)][AllowEmptyCollection()][object]$Value,[Parameter(Mandatory)][string]$Path,[int]$Depth=8,
    [switch]$Atomic)
  if(-not$Atomic){
    ConvertTo-Json -InputObject $Value -Depth $Depth | Set-Content -LiteralPath $Path -Encoding UTF8
    return
  }
  $destination=[IO.Path]::GetFullPath($Path)
  $temporary=Join-Path ([IO.Path]::GetDirectoryName($destination)) ('.run-json-'+[guid]::NewGuid().ToString('N')+'.tmp')
  $failure=$null
  try{
    ConvertTo-Json -InputObject $Value -Depth $Depth | Set-Content -LiteralPath $temporary -Encoding UTF8
    $stream=[IO.File]::Open($temporary,[IO.FileMode]::Open,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
    try{$stream.Flush($true)}finally{$stream.Dispose()}
    [IO.File]::Move($temporary,$destination,$true)
  }catch{$failure=$_;throw}
  finally{
    if([IO.File]::Exists($temporary)){
      try{[IO.File]::Delete($temporary)}catch{
        if($null-eq$failure){throw}
        $failure.Exception.Data['run_json_temporary_cleanup_error']=$_.Exception.Message
      }
    }
  }
}

function Write-RunManifest {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$Python,
    [Parameter(Mandatory)][string]$RepoRoot,
    [Parameter(Mandatory)][string]$RunConfig,
    [Parameter(Mandatory)][ValidateSet('success','failed','interrupted','checkpoint','superseded')][string]$Status,
    [string[]]$Software=@(),
    [string]$Manifest='',
    [string[]]$Outputs=@(),
    [switch]$PassThru
  )
  Invoke-RunToolRootContext -RepoRoot $RepoRoot -Operation {
    $arguments=@((Join-Path $RepoRoot 'common\contracts\write_run_manifest.py'),'--run-config',$RunConfig,'--status',$Status)
    if(-not[string]::IsNullOrWhiteSpace($Manifest)){$arguments+=@('--manifest',$Manifest)}
    foreach($item in $Software){$arguments+=@('--software',$item)}
    # CreateProcessW limits the command line to 32,767 UTF-16 characters.
    # https://learn.microsoft.com/windows/win32/api/processthreadsapi/nf-processthreadsapi-createprocessw
    # Stream UTF-8 directly; no output-list file needs publishing or cleanup.
    $OutputEncoding=[Text.UTF8Encoding]::new($false)
    $arguments+=@('--output-list-json','-')
    $PSNativeCommandUseErrorActionPreference=$false
    $captured=@((ConvertTo-Json -InputObject @($Outputs) -Compress) | & $Python @arguments 2>&1)
    $exitCode=$LASTEXITCODE
    $writerOutput=@($captured|Where-Object{$_-isnot[Management.Automation.ErrorRecord]})
    $stderr=@($captured|Where-Object{$_-is[Management.Automation.ErrorRecord]})
    if($exitCode-ne0){
      # Same bounded native-stream diagnostic contract as capacity admission.
      $details=@{stdout=($writerOutput-join"`n");stderr=($stderr-join"`n")}
      foreach($stream in @('stdout','stderr')){
        if($details[$stream].Length-gt4096){$details[$stream]='[truncated tail] '+$details[$stream].Substring($details[$stream].Length-4096)}
      }
      throw "Run manifest failed for status $Status; exit_code=$exitCode; stdout=$($details.stdout); stderr=$($details.stderr)"
    }
    foreach($errorLine in $stderr){Write-Error -Message ([string]$errorLine) -ErrorAction Continue}
    if($PassThru){$writerOutput}
  }
}

function Write-VerifiedRunManifest {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$Python,
    [Parameter(Mandatory)][string]$RepoRoot,
    [Parameter(Mandatory)][string]$RunConfig,
    [Parameter(Mandatory)][ValidateSet('success','failed','interrupted','checkpoint','superseded')][string]$Status,
    [string[]]$Software=@(),
    [string]$Manifest='',
    [string[]]$Outputs=@(),
    [switch]$DeferCapacityFinalization
  )
  if([string]::IsNullOrWhiteSpace($Manifest)){
    $Manifest=Join-Path (Split-Path -Parent $RunConfig) 'run_manifest.json'
  }
  $capacityLifecycle=$null
  $terminalCapacityLifecycle=$Status-in@('success','failed','interrupted')
  if($terminalCapacityLifecycle){
    $runConfiguration=Get-Content -LiteralPath $RunConfig -Raw -Encoding UTF8|ConvertFrom-Json
    if($null-ne$runConfiguration.PSObject.Properties['capacity_ledger_lifecycle']-and
       [bool]$runConfiguration.capacity_ledger_lifecycle.enabled){
      $capacityLifecycle=$runConfiguration.capacity_ledger_lifecycle
      $null=Invoke-RunCapacityLifecycleAdapter -Python $Python -RepoRoot $RepoRoot `
        -Action assert-retention -ArtifactRoot ([string]$capacityLifecycle.artifact_root) `
        -RunConfig $RunConfig
    }
  }
  $manifestPublished=$false
  try{
    Write-RunManifest -Python $Python -RepoRoot $RepoRoot -RunConfig $RunConfig `
      -Status $Status -Software $Software -Manifest $Manifest -Outputs $Outputs -PassThru
    $manifestPublished=$true
    if($null-ne$capacityLifecycle-and-not$DeferCapacityFinalization){
      $capacityFinal=Invoke-RunCapacityLifecycleAdapter -Python $Python -RepoRoot $RepoRoot `
        -Action finalize-ready -ArtifactRoot ([string]$capacityLifecycle.artifact_root) `
        -RunConfig $RunConfig
      if([bool]$capacityFinal.light_evidence_budget_exceeded){
        $largest=@($capacityFinal.largest_files|ForEach-Object{"$($_.path)=$($_.bytes)B"})-join', '
        Write-Warning ("RUN_LIGHT_EVIDENCE_BUDGET_EXCEEDED RUN={0} BYTES={1} BUDGET={2} LARGEST=[{3}]"-f `
          $capacityFinal.run_directory,$capacityFinal.bytes,$capacityFinal.light_evidence_budget_bytes,$largest) `
          -WarningAction Continue
      }
    }
  }catch{
    if($manifestPublished-and$null-ne$capacityLifecycle){
      throw "Verified $Status run manifest was published, but capacity ledger finalization failed; the run remains writing for recovery: $($_.Exception.Message)"
    }
    throw "Could not publish verified $Status run manifest: $($_.Exception.Message)"
  }
}

function Write-TerminalRunRecord {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$RunDir,
    [Parameter(Mandatory)][ValidateSet('failed','interrupted')][string]$Status,
    [Parameter(Mandatory)][string]$Reason,
    [Parameter(Mandatory)][string]$RepoRoot,
    [Parameter(Mandatory)][string]$Python,
    [Parameter(Mandatory)][string]$SummaryRole,
    [string[]]$Software=@()
  )
  $config=Join-Path $RunDir 'run_config.json'
  $summary=Join-Path $RunDir 'summary.json'
  Write-RunJson -Path $summary -Depth 4 -Value ([ordered]@{
    schema_version=1;role=$SummaryRole;status=$Status;reason=$Reason
  })
  Write-VerifiedRunManifest -Python $Python -RepoRoot $RepoRoot -RunConfig $config `
    -Manifest (Join-Path $RunDir 'run_manifest.json') -Status $Status `
    -Software $Software -Outputs @($summary)
}

function Get-RunPackagePathCapacity {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$RunDirectory,
    [string[]]$AdditionalDirectories=@(),
    [string[]]$ExpectedExecutionRelativePaths=@()
  )
  # 259 is the largest path accepted by legacy Win32 callers (MAX_PATH minus
  # the terminating NUL).  This is deliberately a compatibility diagnostic,
  # not a claim about a particular solver's own path limit.
  $legacyWindowsPathLimit=259
  $relativePaths=@(
    'inputs','results','logs','run_config.json','summary.json','run_manifest.json'
  )
  $relativePaths+=$AdditionalDirectories
  $relativePaths+=$ExpectedExecutionRelativePaths
  $entries=foreach($relative in $relativePaths|Sort-Object -Unique){
    if([string]::IsNullOrWhiteSpace($relative)){
      throw 'Execution path capacity entries must not be empty.'
    }
    if([IO.Path]::IsPathRooted($relative)-or
       $relative.Split([IO.Path]::DirectorySeparatorChar,[IO.Path]::AltDirectorySeparatorChar)-contains'..'){
      throw "Execution path capacity entry must be a contained relative path: $relative"
    }
    $path=[IO.Path]::GetFullPath((Join-Path $RunDirectory $relative))
    [pscustomobject]@{
      relative_path=$relative.Replace('\','/');path=$path;length=$path.Length
      legacy_windows_path_limit=$legacyWindowsPathLimit
      remaining_legacy_windows_characters=$legacyWindowsPathLimit-$path.Length
      legacy_windows_compatible=($path.Length-le$legacyWindowsPathLimit)
    }
  }
  $longest=@($entries|Sort-Object length -Descending|Select-Object -First 1)
  return [pscustomobject]@{
    schema_version=1;role='run_package_execution_path_capacity'
    run_directory=[IO.Path]::GetFullPath($RunDirectory)
    legacy_windows_path_limit=$legacyWindowsPathLimit
    entries=@($entries);longest_path=$longest[0]
    legacy_windows_compatible=(@($entries|Where-Object{-not$_.legacy_windows_compatible}).Count-eq 0)
  }
}

function Get-RunPackageCopiedSourcePaths {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$RepoRoot,
    [Parameter(Mandatory)][string[]]$SourceRelativeDirectories,
    [Parameter(Mandatory)][string[]]$Extensions,
    [string]$DestinationRoot = 'inputs/code'
  )
  $repo = [IO.Path]::GetFullPath($RepoRoot)
  $paths = foreach ($relativeDirectory in $SourceRelativeDirectories) {
    $source = [IO.Path]::GetFullPath((Join-Path $repo $relativeDirectory))
    if (-not $source.StartsWith($repo + [IO.Path]::DirectorySeparatorChar,
        [StringComparison]::OrdinalIgnoreCase) -or
        -not (Test-Path -LiteralPath $source -PathType Container)) {
      throw "Copied source directory is not one repository-local directory: $relativeDirectory"
    }
    Get-ChildItem -LiteralPath $source -Recurse -File |
      Where-Object { $_.Extension -in $Extensions } |
      ForEach-Object {
        $nested = $_.FullName.Substring($source.Length).TrimStart([char[]]@(92,47))
        ($DestinationRoot.TrimEnd([char[]]@(92,47)) + '/' +
          $relativeDirectory.Trim([char[]]@(92,47)) + '/' + $nested).Replace([string][char]92,'/')
      }
  }
  return @($paths | Sort-Object -Unique)
}

function Assert-RunPackagePathCapacity {
  [CmdletBinding()]
  param([Parameter(Mandatory)][pscustomobject]$Report)
  if($Report.legacy_windows_compatible){return $Report}
  $overLimit=@($Report.entries|Where-Object{-not$_.legacy_windows_compatible}|Select-Object -First 1)[0]
  $message=('EXECUTION_PATH_CAPACITY=FAIL PATH={0} LENGTH={1} LEGACY_WINDOWS_LIMIT={2} '+
    'REMEDIATION=choose a shorter MASS_SPECTROMETRY_EXECUTION_ROOT or shorten the declared relative path.') -f
    $overLimit.path,$overLimit.length,$overLimit.legacy_windows_path_limit
  throw $message
}

function New-RunExecutionAlias {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$TargetDirectory,
    [string[]]$AdditionalDirectories=@(),
    [string[]]$ExpectedExecutionRelativePaths=@(),
    [string]$ExecutionRoot='',
    [string]$AliasName=''
  )
  $target=[IO.Path]::GetFullPath($TargetDirectory)
  if(-not(Test-Path -LiteralPath $target -PathType Container)){
    throw "Execution alias target directory is missing: $target"
  }
  if([string]::IsNullOrWhiteSpace($ExecutionRoot)){
    $ExecutionRoot=if($env:MASS_SPECTROMETRY_EXECUTION_ROOT){
      $env:MASS_SPECTROMETRY_EXECUTION_ROOT
    }else{
      # Desktop children can be denied C:\tmp.  The shared artifact root is
      # writable to every project workflow and keeps aliases in one audited
      # disposable location rather than falling back to a long path.
      Join-Path (Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))) 'artifacts\common\execution_aliases'
    }
  }
  $executionRootPath=[IO.Path]::GetFullPath($ExecutionRoot)
  if($AliasName-and$AliasName-notmatch'^source_[a-f0-9]{64}_[1-9][0-9]*$'){throw 'Explicit source alias name must bind its request identity and ordinal.'}
  $alias=Join-Path $executionRootPath $(if($AliasName){$AliasName}else{'run_'+[guid]::NewGuid().ToString('N')})
  if(Test-Path -LiteralPath $alias){
    $existing=Get-Item -LiteralPath $alias -Force
    if($existing.LinkType-ne'Junction'-or
       [IO.Path]::GetFullPath([string]@($existing.Target)[0])-ine$target){throw 'Existing execution alias target or owner differs.'}
    throw 'Same-owner execution alias already exists; retain it and return to its original owner context.'
  }
  $pathCapacity=Get-RunPackagePathCapacity -RunDirectory $alias `
    -AdditionalDirectories $AdditionalDirectories `
    -ExpectedExecutionRelativePaths $ExpectedExecutionRelativePaths
  $null=Assert-RunPackagePathCapacity -Report $pathCapacity
  New-Item -ItemType Directory -Force -Path $executionRootPath|Out-Null
  try{
    New-Item -ItemType Junction -Path $alias -Target $target|Out-Null
  }catch{
    throw "Could not create short execution alias $alias for target ${target}: $($_.Exception.Message)"
  }
  return [pscustomobject]@{
    target_directory=$target;execution_alias=$alias;execution_path_capacity=$pathCapacity
  }
}

function Remove-RunExecutionAlias {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$ExecutionAlias,
    [Parameter(Mandatory)][string]$TargetDirectory
  )
  $alias=[IO.Path]::GetFullPath($ExecutionAlias)
  $targetDirectory=[IO.Path]::GetFullPath($TargetDirectory)
  if(-not(Test-Path -LiteralPath $alias -PathType Container)){return}
  $item=Get-Item -LiteralPath $alias -Force
  if($item.LinkType-ne'Junction'){
    throw "Execution alias is not a junction: $alias"
  }
  $target=[IO.Path]::GetFullPath([string]@($item.Target)[0])
  if(-not $target.Equals($targetDirectory,[StringComparison]::OrdinalIgnoreCase)){
    throw "Execution alias target differs from expected target: $alias"
  }
  [IO.Directory]::Delete($alias)
}

function Resolve-RunSourceExecutionInputs {
  param([string]$Python,[string]$RepoRoot,$Session,[object[]]$SourceReferences,
    [string[]]$NativeInputPaths,[switch]$RequireProtection)
  $resolver=@'
import json,sys
from pathlib import Path
from common.contracts.run_capacity_lifecycle import resolve_consumed_run_capacity_owner
from common.contracts.verify_run_manifest import record_path
from common.contracts.capacity_protection import load_capacity_protection_leases,path_is_protected
session,refs,paths,require=json.loads(sys.argv[1]),json.loads(sys.argv[2]),json.loads(sys.argv[3]),sys.argv[4]=='True'
sources={}
for ref in refs:
    source=resolve_consumed_run_capacity_owner(ref['manifest_record'],consumer_artifact_root=Path(session['artifact_root']),stopped_receipt_record=ref.get('stopped_receipt_record'))
    run=Path(source['run_directory']);root=Path(source['artifact_root'])
    manifest=json.loads(record_path(ref['manifest_record']).read_text(encoding='utf-8-sig'))
    records=[*manifest.get('inputs',{}).values(),*manifest.get('outputs',[])]
    bound={record_path(row,base_dir=run) for row in records}
    if require:
        candidates=([session] if root==Path(session['artifact_root']).resolve() else
                    [row for row in session.get('source_protection_leases',[]) if Path(row['artifact_root']).resolve()==root and row['status']=='active'])
        if len(candidates)!=1 or session['status']!='active': raise ValueError('native source requires its admitted protection owner')
        lease_id=candidates[0]['lease_id']
        active=[row for row in load_capacity_protection_leases(root)['audit'] if row['lease_id']==lease_id and row['status']=='active' and row['owner']==session['owner']]
        if len(active)!=1: raise ValueError('native source protection is not active')
        lease=json.loads(Path(active[0]['path']).read_text(encoding='utf-8-sig'))
        if not path_is_protected(run,[root/item for item in lease['protected_paths']]): raise ValueError('native source run is not protected by this owner')
    key=str(run)
    if key in sources: sources[key]['bound'].update(bound)
    else: sources[key]={'target_directory':key,'bound':bound,'input_paths':[]}
for raw in paths:
    path=Path(raw)
    if not path.is_absolute() or (require and not path.is_file()): raise ValueError('native source input must be an existing absolute file')
    path=path.resolve()
    matches=[row for row in sources.values() if path.is_relative_to(Path(row['target_directory'])) and path in row['bound']]
    if len(matches)!=1: raise ValueError('native source input is not uniquely bound by an admitted producer manifest')
    matches[0]['input_paths'].append(str(path))
rows=[{'target_directory':row['target_directory'],'input_paths':row['input_paths']} for row in sources.values() if row['input_paths']]
print(json.dumps(sorted(rows,key=lambda row:row['target_directory'])))
'@
  $output=@(Invoke-RunCapacityCommand -Python $Python -RepoRoot $RepoRoot -Arguments @('-B','-c',$resolver,
    ($Session|ConvertTo-Json -Depth 64 -Compress),(ConvertTo-Json -InputObject @($SourceReferences) -Depth 64 -Compress),
    (ConvertTo-Json -InputObject @($NativeInputPaths) -Compress),([string][bool]$RequireProtection)) -FailureLabel 'Native source authority verification failed')
  return @(ConvertFrom-Json -InputObject ($output-join"`n"))
}

function New-RunSourceExecutionContext {
  <# Explicit frozen Python-prepared inputs only; source authority stays canonical. #>
  param([string]$Python,[string]$RepoRoot,[pscustomobject]$Package,$Session,
    [object[]]$SourceReferences,[string[]]$NativeInputPaths,[string]$RequestSha256)
  $watch=[Diagnostics.Stopwatch]::StartNew()
  try{
  if($RequestSha256-notmatch'^[a-fA-F0-9]{64}$'){throw 'Native source context requires its original request identity.'}
  $sources=@(Resolve-RunSourceExecutionInputs -Python $Python -RepoRoot $RepoRoot -Session $Session `
    -SourceReferences $SourceReferences -NativeInputPaths $NativeInputPaths -RequireProtection)
  $executionRoot=[IO.Path]::GetFullPath([string]$Package.path_context.execution_root)
  $context=[ordered]@{schema_version=1;role='run_source_execution_context';
    child_run_directory=[string]$Package.artifact_run_dir;execution_root=$executionRoot;request_sha256=$RequestSha256.ToUpperInvariant();sources=@()}
  try{
    foreach($source in $sources){
      $target=[string]$source.target_directory
      $relative=@($source.input_paths|ForEach-Object{[IO.Path]::GetRelativePath($target,[string]$_)})
      $capacity=Get-RunPackagePathCapacity -RunDirectory $target -ExpectedExecutionRelativePaths $relative
      $row=[ordered]@{target_directory=$target;execution_directory=$target;input_paths=@($source.input_paths);execution_alias=$null}
      if(-not$capacity.legacy_windows_compatible){
        $alias=New-RunExecutionAlias -TargetDirectory $target -ExecutionRoot $executionRoot -ExpectedExecutionRelativePaths $relative `
          -AliasName ('source_'+$RequestSha256.ToLowerInvariant()+'_'+($context.sources.Count+1))
        $row.execution_directory=[string]$alias.execution_alias;$row.execution_alias=[string]$alias.execution_alias
      }
      $context.sources+=@($row)
    }
    return $context
  }catch{
    $failure=$_
    $failure.Exception.Data['source_execution_context']=$context
    # No process has started: roll back only these exact newly-created links.
    $removed=$true
    foreach($row in $context.sources){if($null-ne$row.execution_alias){
      try{Remove-RunExecutionAlias -ExecutionAlias $row.execution_alias -TargetDirectory $row.target_directory}
      catch{$removed=$false;$failure.Exception.Data['source_alias_cleanup_error']=$_.Exception.Message}
    }}
    $failure.Exception.Data['source_execution_aliases_rolled_back']=$removed
    throw $failure
  }
  }finally{
    $watch.Stop()
    if($null-eq$Package.PSObject.Properties['native_path_preparation']){
      $Package|Add-Member -NotePropertyName native_path_preparation -NotePropertyValue @{calls=0;elapsed_seconds=0.0;transport_bytes=0L}
    }
    $Package.native_path_preparation.calls++
    $Package.native_path_preparation.elapsed_seconds+=$watch.Elapsed.TotalSeconds
  }
}

function Remove-RunSourceExecutionContext {
  <# Called only after writer completion, or before any prepared process starts. #>
  param([string]$Python,[string]$RepoRoot,$Session,[object[]]$SourceReferences,[string[]]$NativeInputPaths,
    [string]$RunDirectory,[string]$ExecutionRoot,[string]$RequestSha256,$Context)
  if($RequestSha256-notmatch'^[a-fA-F0-9]{64}$'-or$Context.request_sha256-ine$RequestSha256-or
     $Context.schema_version-ne1-or$Context.role-cne'run_source_execution_context'-or
     [IO.Path]::GetFullPath([string]$Context.child_run_directory)-ine[IO.Path]::GetFullPath($RunDirectory)-or
     [IO.Path]::GetFullPath([string]$Context.execution_root)-ine[IO.Path]::GetFullPath($ExecutionRoot)){
    throw 'Native source context owner or frozen execution root differs.'
  }
  $expected=@(Resolve-RunSourceExecutionInputs -Python $Python -RepoRoot $RepoRoot -Session $Session `
    -SourceReferences $SourceReferences -NativeInputPaths $NativeInputPaths)
  if(@($Context.sources).Count-ne$expected.Count){throw 'Native source context declarations differ.'}
  $ordinal=0
  foreach($row in $Context.sources){
    $ordinal++
    $matched=@($expected|Where-Object target_directory -IEQ ([string]$row.target_directory))
    if($matched.Count-ne1-or$expected[$ordinal-1].target_directory-ine$row.target_directory-or(@($matched[0].input_paths)-join"`n")-cne(@($row.input_paths)-join"`n")){
      throw 'Native source context input or target differs.'
    }
    if($null-eq$row.execution_alias){
      if($row.execution_directory-ine$row.target_directory){throw 'Native source context unowned execution path differs.'}
    }else{
      $alias=[IO.Path]::GetFullPath([string]$row.execution_alias)
      if($alias-ine$row.execution_directory-or
         [IO.Path]::GetFullPath((Split-Path -Parent $alias))-ine[IO.Path]::GetFullPath($ExecutionRoot)-or
         [IO.Path]::GetFileName($alias)-cne('source_'+$RequestSha256.ToLowerInvariant()+'_'+$ordinal)){
        throw 'Native source alias is outside its frozen owner scope.'
      }
    }
  }
  # Validate every record before touching any alias.
  foreach($row in $Context.sources){if($null-ne$row.execution_alias){
    Remove-RunExecutionAlias -ExecutionAlias $row.execution_alias -TargetDirectory $row.target_directory
  }}
}


function Get-RunNativeExecutionContext {
  <# Inspect only the actual native plan; keep persistent identity canonical. #>
  [CmdletBinding()]
  param([Parameter(Mandatory)][pscustomobject]$Package,
    [Parameter(Mandatory)][AllowEmptyCollection()][string[]]$Paths,
    [string]$ExecutionRoot='',[string]$Tool='native tool')
  $watch=[Diagnostics.Stopwatch]::StartNew()
  . (Join-Path (Split-Path -Parent $PSScriptRoot) 'paths/workspace_paths.ps1')
  $persistent=[IO.Path]::GetFullPath([string]$Package.artifact_run_dir).TrimEnd('\','/')
  if($null-ne$Package.execution_alias-and-not(Test-Path -LiteralPath ([string]$Package.execution_alias) -PathType Container)){
    # A persisted package may outlive its disposable execution representation.
    # Re-evaluate this native plan from its unchanged persistent identity.
    $Package.run_dir=$persistent;$Package.execution_alias=$null;$Package.execution_path_capacity=$null
  }
  $execution=[string]$Package.run_dir
  $relativePaths=@();$external=@()
  foreach($path in $Paths){
    if(-not[IO.Path]::IsPathFullyQualified($path)){throw "Native plan path must be absolute: $path"}
    $full=[IO.Path]::GetFullPath($path)
    if($full.Equals($persistent,[StringComparison]::OrdinalIgnoreCase)){$relativePaths+='.'}
    elseif($full.StartsWith($persistent+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)){
      $relativePaths+=[IO.Path]::GetRelativePath($persistent,$full)
    }elseif($full.StartsWith($execution.TrimEnd('\','/')+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)){
      $relativePaths+=[IO.Path]::GetRelativePath($execution,$full)
    }else{
      $external+=$full
    }
  }
  $capacity=Get-RunPackagePathCapacity -RunDirectory $execution -ExpectedExecutionRelativePaths $relativePaths
  foreach($path in $external){
    if($path.Length-gt$capacity.legacy_windows_path_limit){
      throw ("NATIVE_PATH_PREPARATION=FAIL TOOL={0} PATH={1} LENGTH={2} REASON=external_input_requires_its_existing_owner_transport REMEDIATION=prepare_the_explicit_input_with_its_supported_private_copy_or_companion_boundary ELAPSED_SECONDS={3}" -f $Tool,$path,$path.Length,$watch.Elapsed.TotalSeconds)
    }
  }
  if($Paths.Count-and-not$capacity.legacy_windows_compatible){
    if($null-ne$Package.execution_alias){$null=Assert-RunPackagePathCapacity -Report $capacity}
    if(-not$ExecutionRoot-and$null-ne$Package.PSObject.Properties['path_context']){$ExecutionRoot=[string]$Package.path_context.execution_root}
    $alias=New-RunExecutionAlias -TargetDirectory $persistent -ExecutionRoot $ExecutionRoot -ExpectedExecutionRelativePaths $relativePaths
    $execution=[string]$alias.execution_alias
    $Package.run_dir=$execution;$Package.execution_alias=$execution
    $capacity=$alias.execution_path_capacity
  }
  $Package.execution_path_capacity=$capacity
  $projected=if($Paths.Count){Project-RunPath -Paths $Paths -ArtifactRunDir $persistent -RunDir $execution -Python $Package.python}else{@()}
  $environment=@{MASS_SPECTROMETRY_RUN_DIRECTORY=$persistent;MASS_SPECTROMETRY_RUN_EXECUTION_DIRECTORY=$execution}
  if($null-ne$Package.PSObject.Properties['path_context']){
    $environment.MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH=[string]$Package.path_context.host_resource_state_path
    $environment.MASS_SPECTROMETRY_ARTIFACT_ROOT=[string]$Package.path_context.artifact_root
    $environment.MASS_SPECTROMETRY_EXECUTION_ROOT=[string]$Package.path_context.execution_root
  }
  $elapsed=$watch.Elapsed.TotalSeconds
  if($null-eq$Package.PSObject.Properties['native_path_preparation']){
    $Package|Add-Member -NotePropertyName native_path_preparation -NotePropertyValue @{calls=0;elapsed_seconds=0.0;transport_bytes=0L}
  }
  $Package.native_path_preparation.calls++
  $Package.native_path_preparation.elapsed_seconds+=$elapsed
  return [pscustomobject]@{artifact_run_dir=$persistent;run_dir=$execution;execution_alias=$Package.execution_alias;
    projected_paths=@($projected);environment=$environment;execution_path_capacity=$capacity;
    preparation_elapsed_seconds=$elapsed;transport_bytes=0;tool=$Tool}
}

function New-RunPackage {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$Python,
    [Parameter(Mandatory)][string]$RepoRoot,
    [Parameter(Mandatory)][string]$ArtifactRoot,
    [Parameter(Mandatory)][string]$RunId,
    [Parameter(Mandatory)][string]$Project,
    [Parameter(Mandatory)][string]$Mode,
    [Parameter(Mandatory)][string[]]$Software,
    [switch]$RetentionContractEnabled,
    [ValidateSet('compact','qualification','solver_review')][string]$RetentionClass='compact',
    [string]$RetentionReason='',
    [string[]]$AdditionalDirectories=@(),
    [switch]$CapacityLedgerLifecycleEnabled,
    [string]$CapacityLedgerArtifactRoot='',
    [switch]$UseShortExecutionPath,
    [string]$ExecutionRoot='',
    [string[]]$ExpectedExecutionRelativePaths=@(),
    $PathContext=$null
  )
  if($RetentionContractEnabled-and$RetentionClass-ne'compact'-and[string]::IsNullOrWhiteSpace($RetentionReason)){
    throw "RetentionReason is required for artifact retention class $RetentionClass."
  }
  if($RetentionContractEnabled-and$RetentionClass-eq'compact'-and-not[string]::IsNullOrWhiteSpace($RetentionReason)){
    throw 'RetentionReason must be empty for compact artifact retention.'
  }
  if(-not$RetentionContractEnabled-and(
      $RetentionClass-ne'compact'-or-not[string]::IsNullOrWhiteSpace($RetentionReason))){
    throw 'RetentionContractEnabled is required when selecting run artifact retention.'
  }
  if($CapacityLedgerLifecycleEnabled-and-not$RetentionContractEnabled){
    throw 'CapacityLedgerLifecycleEnabled requires RetentionContractEnabled.'
  }
  if(-not$CapacityLedgerLifecycleEnabled-and-not[string]::IsNullOrWhiteSpace($CapacityLedgerArtifactRoot)){
    throw 'CapacityLedgerArtifactRoot requires CapacityLedgerLifecycleEnabled.'
  }
  . (Join-Path (Split-Path -Parent $PSScriptRoot) 'paths/workspace_paths.ps1')
  $projectDirectory=[IO.DirectoryInfo][IO.Path]::GetFullPath($ArtifactRoot)
  $structuredProject=$null-ne$projectDirectory.Parent-and$projectDirectory.Parent.Name-eq'projects'
  if($CapacityLedgerLifecycleEnabled-and-not$structuredProject){
    throw 'ArtifactRoot must be the canonical artifacts/projects/<Project> directory, not its runs directory.'
  }
  $rootArguments=@{SourceRoot=$RepoRoot;Python=$Python}
  if($null-ne$PathContext){$rootArguments.FrozenContext=$PathContext}
  else{
    if($CapacityLedgerArtifactRoot){$rootArguments.ArtifactRoot=$CapacityLedgerArtifactRoot}
    elseif($structuredProject){$rootArguments.ArtifactRoot=$projectDirectory.Parent.Parent.FullName}
    if($ExecutionRoot){$rootArguments.ExecutionRoot=$ExecutionRoot}
  }
  $resolvedPaths=Resolve-WorkspacePaths @rootArguments
  $hostEnvironment=Save-RunEnvironment -Names @('MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH')
  try{
  $env:MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH=[string]$resolvedPaths.host_resource_state_path
  if($ExecutionRoot-and$null-ne$PathContext-and$ExecutionRoot-cne$resolvedPaths.execution_root){throw 'ExecutionRoot differs from the frozen path context.'}
  $ExecutionRoot=[string]$resolvedPaths.execution_root
  # A configured root is governed regardless of its directory name. Also
  # recognize the existing projects/<owner> shape before creating any files.
  $governedArtifactsRoot=$null
  $configuredRoot=[IO.Path]::GetFullPath([string]$resolvedPaths.artifact_root).TrimEnd('\','/')
  if($structuredProject-or$projectDirectory.FullName.StartsWith($configuredRoot+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)){
    $governedArtifactsRoot=[IO.DirectoryInfo]$configuredRoot
  }
  if($null-ne$governedArtifactsRoot-and(-not$RetentionContractEnabled-or-not$CapacityLedgerLifecycleEnabled)){
    throw 'Runs beneath artifacts require retention and capacity-ledger lifecycle before package creation.'
  }
  if($null-ne$governedArtifactsRoot){
    $expectedProjectRoot=Join-Path $governedArtifactsRoot.FullName ('projects/'+$Project)
    $actualProjectRoot=[IO.Path]::GetFullPath($ArtifactRoot)
    if($structuredProject){
      $actualRoots=Resolve-WorkspacePaths -SourceRoot $RepoRoot -ArtifactRoot $projectDirectory.Parent.Parent.FullName `
        -ExecutionRoot $resolvedPaths.execution_root -HostResourceStatePath $resolvedPaths.host_resource_state_path -Python $Python
      $actualProjectRoot=Join-Path $actualRoots.artifact_root ('projects/'+$projectDirectory.Name)
    }
    if(-not($actualProjectRoot.TrimEnd('\','/').Equals(
        [IO.Path]::GetFullPath($expectedProjectRoot).TrimEnd('\','/'),[StringComparison]::OrdinalIgnoreCase))){
      throw 'ArtifactRoot must be the canonical artifacts/projects/<Project> directory, not its runs directory.'
    }
    $ArtifactRoot=$expectedProjectRoot
  }
  if($CapacityLedgerLifecycleEnabled){
    if([string]::IsNullOrWhiteSpace($CapacityLedgerArtifactRoot)){
      if($null-eq$governedArtifactsRoot){
        throw 'Could not derive the workspace artifacts root for capacity-ledger lifecycle.'
      }
      $CapacityLedgerArtifactRoot=$governedArtifactsRoot.FullName
    }
    $CapacityLedgerArtifactRoot=[IO.Path]::GetFullPath($CapacityLedgerArtifactRoot)
  }
  $python=[IO.Path]::GetFullPath($Python)
  if(-not(Test-Path -LiteralPath $python -PathType Leaf)){throw "Run Python environment is missing: $python"}
  $pythonVersion=(& $python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
  if($LASTEXITCODE-ne 0 -or $pythonVersion-ne '3.11'){
    throw "Run package requires Python 3.11, found $pythonVersion at $python"
  }
  $identityCheck=& $python (Join-Path $RepoRoot 'common\contracts\artifact_identity_archive.py') `
    --repository-root $RepoRoot --check-new-run-project $Project 2>&1
  if($LASTEXITCODE-ne 0 -or -not($identityCheck-match '^NEW_RUN_PROJECT=PASS ')){
    throw "Run project identity rejected before package creation: $($identityCheck -join [Environment]::NewLine)"
  }
  $validation=& $python (Join-Path $RepoRoot 'common\contracts\artifact_naming.py') run $RunId
  if($LASTEXITCODE-ne 0 -or -not($validation-match '^ARTIFACT_ID=PASS ')){throw "Invalid run_id: $RunId"}
  $artifactRunDir=Join-Path $ArtifactRoot "runs\$RunId"
  if(Test-Path -LiteralPath $artifactRunDir){throw "Run already exists: $artifactRunDir"}
  if($CapacityLedgerLifecycleEnabled){
    New-Item -ItemType Directory -Path $artifactRunDir -ErrorAction Stop|Out-Null
    try{
      $null=Invoke-RunCapacityLifecycleAdapter -Python $python -RepoRoot $RepoRoot `
        -Action register-writing-range -ArtifactRoot $CapacityLedgerArtifactRoot -RunDirectory $artifactRunDir
    }catch{
      [IO.Directory]::Delete($artifactRunDir,$false)
      throw
    }
  }
  $runDir=$artifactRunDir
  $executionAlias=$null
  $pathCapacity=Get-RunPackagePathCapacity -RunDirectory $runDir -AdditionalDirectories $AdditionalDirectories `
    -ExpectedExecutionRelativePaths $ExpectedExecutionRelativePaths
  if($UseShortExecutionPath-or($ExpectedExecutionRelativePaths.Count-and-not$pathCapacity.legacy_windows_compatible)){
    if(-not$CapacityLedgerLifecycleEnabled){New-Item -ItemType Directory -Force -Path $artifactRunDir|Out-Null}
    try{
      $aliasRecord=New-RunExecutionAlias -TargetDirectory $artifactRunDir `
        -AdditionalDirectories $AdditionalDirectories -ExecutionRoot $ExecutionRoot `
        -ExpectedExecutionRelativePaths $ExpectedExecutionRelativePaths
    }catch{
      if(-not$CapacityLedgerLifecycleEnabled){[IO.Directory]::Delete($artifactRunDir,$true)}
      throw
    }
    $executionAlias=$aliasRecord.execution_alias
    $pathCapacity=$aliasRecord.execution_path_capacity
    $runDir=$executionAlias
  }else{
    $pathCapacity=Get-RunPackagePathCapacity -RunDirectory $runDir `
      -AdditionalDirectories $AdditionalDirectories `
      -ExpectedExecutionRelativePaths $ExpectedExecutionRelativePaths
  }
  $package=[ordered]@{
    python=$python;run_dir=$runDir;input_dir=(Join-Path $runDir 'inputs');result_dir=(Join-Path $runDir 'results');
    log_dir=(Join-Path $runDir 'logs');run_config=(Join-Path $runDir 'run_config.json');summary=(Join-Path $runDir 'summary.json');
    artifact_run_dir=$artifactRunDir;execution_alias=$executionAlias;execution_path_capacity=$pathCapacity;path_context=$resolvedPaths
    native_path_preparation=@{calls=0;elapsed_seconds=0.0;transport_bytes=0L}
  }
  $directories=@($package.input_dir,$package.result_dir,$package.log_dir)
  foreach($relative in $AdditionalDirectories){$directories+=Join-Path $runDir $relative}
  New-Item -ItemType Directory -Force -Path $directories|Out-Null
  $initialConfig=[ordered]@{
    schema_version=$(if($RetentionContractEnabled){2}else{1});
    run_id=$RunId;project=$Project;mode=$Mode;project_root=$RepoRoot;inputs=[ordered]@{};
    parameters=[ordered]@{lifecycle_stage='run_package_initialized'};formal_gate_passed=$false
    paths=$resolvedPaths
  }
  if($RetentionContractEnabled){
    $initialConfig.artifact_retention=[ordered]@{policy_version=1;class=$RetentionClass;
      reason=$(if($RetentionClass-eq'compact'){$null}else{$RetentionReason})}
  }
  if($CapacityLedgerLifecycleEnabled){
    $capacityPolicy=Get-Content -LiteralPath (Join-Path $RepoRoot 'common\contracts\artifact_capacity_policy.json') `
      -Raw -Encoding UTF8|ConvertFrom-Json
    [int64]$lightBudget=$capacityPolicy.light_evidence_budget_bytes
    if($lightBudget-le0){throw 'Artifact capacity policy light-evidence budget must be positive.'}
    $initialConfig.capacity_ledger_lifecycle=[ordered]@{
      schema_version=1;enabled=$true;artifact_root=$CapacityLedgerArtifactRoot
      light_evidence_budget_bytes=$lightBudget
    }
  }
  Write-RunJson -Path $package.run_config -Value $initialConfig
  Write-RunJson -Path $package.summary -Value ([ordered]@{
    schema_version=1;role='run_package_initialization_summary';status='checkpoint';
    reason='Run package initialized; task-specific inputs are not frozen yet.'
  })
  $null=Write-VerifiedRunManifest -Python $python -RepoRoot $RepoRoot -RunConfig $package.run_config `
    -Status checkpoint -Software $Software -Outputs @($package.summary)
  if($CapacityLedgerLifecycleEnabled){
    $null=Invoke-RunCapacityLifecycleAdapter -Python $python -RepoRoot $RepoRoot `
      -Action register-writing -ArtifactRoot $CapacityLedgerArtifactRoot -RunConfig $package.run_config
  }
  return [pscustomobject]$package
  }finally{Restore-RunEnvironment -Names @('MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH') -Snapshot $hostEnvironment}
}

function Remove-RunPackageExecutionAlias {
  [CmdletBinding()]
  param([Parameter(Mandatory)][pscustomobject]$Package)
  if($null-eq$Package.execution_alias){return}
  Remove-RunExecutionAlias -ExecutionAlias ([string]$Package.execution_alias) `
    -TargetDirectory ([string]$Package.artifact_run_dir)
  $Package.run_dir=[string]$Package.artifact_run_dir
  $Package.execution_alias=$null
  $Package.execution_path_capacity=$null
}

function Apply-RunArtifactRetention {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$Python,
    [Parameter(Mandatory)][string]$RepoRoot,
    [Parameter(Mandatory)][string]$RunConfig,
    [string[]]$PreservePaths=@(),
    [string[]]$RemovePaths=@(),
    [switch]$FailedRun,
    [string[]]$RecoveryInputs=@(),
    [switch]$Resume,
    [Nullable[long]]$MaximumRunBytes=$null
  )
  $arguments=@('apply','--run-config',$RunConfig)
  foreach($path in $PreservePaths){
    if(-not[string]::IsNullOrWhiteSpace($path)){
      $arguments+=@('--preserve-path',$path)
    }
  }
  foreach($path in $RemovePaths){
    if(-not[string]::IsNullOrWhiteSpace($path)){
      $arguments+=@('--remove-path',$path)
    }
  }
  if($FailedRun){$arguments+='--failed-run'}
  foreach($path in $RecoveryInputs){$arguments+=@('--recovery-input',$path)}
  if($Resume){$arguments+='--resume'}
  if($null-ne$MaximumRunBytes){$arguments+=@('--maximum-run-bytes',[string]$MaximumRunBytes)}
  $output=Invoke-RunToolRootContext -RepoRoot $RepoRoot -Operation {
    & $Python (Join-Path $RepoRoot 'common\contracts\artifact_retention.py') @arguments
    if($LASTEXITCODE-ne 0){throw 'Run artifact retention failed.'}
  }
  Write-Verbose ($output -join [Environment]::NewLine)
  return Join-Path (Split-Path -Parent $RunConfig) 'retention_actions.json'
}

function Save-RunEnvironment {
  [CmdletBinding()]
  param([Parameter(Mandatory)][string[]]$Names)
  $snapshot=@{};foreach($name in $Names){$snapshot[$name]=[Environment]::GetEnvironmentVariable($name)};return $snapshot
}

function Restore-RunEnvironment {
  [CmdletBinding()]
  param([Parameter(Mandatory)][string[]]$Names,[Parameter(Mandatory)][hashtable]$Snapshot)
  foreach($name in $Names){
    if($null-eq$Snapshot[$name]){Remove-Item -LiteralPath ('Env:\'+$name) -ErrorAction SilentlyContinue}
    else{[Environment]::SetEnvironmentVariable($name,$Snapshot[$name])}
  }
}

function Copy-VerifiedRunInput {
  # Consumers that publish a receipt can reuse this verified copy's identity.
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$Source,
    [Parameter(Mandatory)][string]$Destination,
    [ValidateRange(1,5)][int]$VerificationAttempts=1,
    [ref]$VerifiedIdentity
  )
  $sourcePath=[IO.Path]::GetFullPath($Source);$destinationPath=[IO.Path]::GetFullPath($Destination)
  if(-not(Test-Path -LiteralPath $sourcePath -PathType Leaf)){throw "Run input is missing: $sourcePath"}
  $parent=Split-Path -Parent $destinationPath
  if(-not(Test-Path -LiteralPath $parent -PathType Container)){New-Item -ItemType Directory -Path $parent -Force|Out-Null}
  foreach($attempt in 1..$VerificationAttempts){
    $sourceHashBefore=(Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash
    if(Test-Path -LiteralPath $destinationPath -PathType Leaf){(Get-Item -LiteralPath $destinationPath).IsReadOnly=$false}
    if($attempt-eq1){
      Copy-Item -LiteralPath $sourcePath -Destination $destinationPath -Force
    }else{
      $readStream=$null;$writeStream=$null
      try{
        $readStream=[IO.File]::Open($sourcePath,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
        $writeStream=[IO.FileStream]::new($destinationPath,[IO.FileMode]::Create,[IO.FileAccess]::Write,[IO.FileShare]::None,8MB,[IO.FileOptions]::WriteThrough)
        $readStream.CopyTo($writeStream,8MB)
        $writeStream.Flush($true)
      }finally{
        if($null-ne$writeStream){$writeStream.Dispose()}
        if($null-ne$readStream){$readStream.Dispose()}
      }
      [IO.File]::SetLastWriteTimeUtc($destinationPath,[IO.File]::GetLastWriteTimeUtc($sourcePath))
    }
    $sourceHashAfter=(Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash
    $destinationHash=(Get-FileHash -LiteralPath $destinationPath -Algorithm SHA256).Hash
    if($sourceHashBefore-ceq$sourceHashAfter -and $sourceHashAfter-ceq$destinationHash){
      if($null-ne$VerifiedIdentity){
        $VerifiedIdentity.Value=[pscustomobject]@{path=$destinationPath;bytes=(Get-Item -LiteralPath $destinationPath).Length;sha256=$destinationHash}
      }
      return $destinationPath
    }
  }
  $failure=[InvalidOperationException]::new("Run input changed or copied inconsistently while frozen after $VerificationAttempts attempt(s): $sourcePath")
  $failure.Data['source_path']=$sourcePath
  $failure.Data['destination_path']=$destinationPath
  $failure.Data['source_sha256']=$sourceHashAfter
  $failure.Data['frozen_sha256']=$destinationHash
  throw $failure
}

function Write-RunDirectoryChecksumInventory {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$Directory,
    [Parameter(Mandatory)][string]$OutputPath,
    [string[]]$ExcludedPatterns=@()
  )
  $outputName=[IO.Path]::GetFileName($OutputPath)
  $records=Get-ChildItem -LiteralPath $Directory -File|Where-Object{
    $name=$_.Name
    if($name-eq$outputName){return $false}
    foreach($pattern in $ExcludedPatterns){if($name-like$pattern){return $false}}
    return $true
  }|Sort-Object Name|ForEach-Object{
    [pscustomobject]@{file=$_.Name;bytes=$_.Length;sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash}
  }
  $records|Export-Csv -LiteralPath $OutputPath -NoTypeInformation -Encoding UTF8
}

function Get-RunFileSha256 {
  [CmdletBinding()]
  param([Parameter(Mandatory)][string]$Path)
  $fullPath=[IO.Path]::GetFullPath($Path)
  if(-not(Test-Path -LiteralPath $fullPath -PathType Leaf)){throw "Run file is missing: $fullPath"}
  return (Get-FileHash -LiteralPath $fullPath -Algorithm SHA256).Hash
}

function Test-RunFilesIdentical {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$Left,
    [Parameter(Mandatory)][string]$Right
  )
  $leftPath=[IO.Path]::GetFullPath($Left);$rightPath=[IO.Path]::GetFullPath($Right)
  if(-not(Test-Path -LiteralPath $leftPath -PathType Leaf) -or
     -not(Test-Path -LiteralPath $rightPath -PathType Leaf)){return $false}
  return (Get-Item -LiteralPath $leftPath).Length -eq (Get-Item -LiteralPath $rightPath).Length -and
    (Get-RunFileSha256 -Path $leftPath) -ceq (Get-RunFileSha256 -Path $rightPath)
}

function Complete-FailedRun {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$Python,[Parameter(Mandatory)][string]$RepoRoot,
    [Parameter(Mandatory)][string]$RunConfig,[Parameter(Mandatory)][string]$Summary,
    [Parameter(Mandatory)][string]$SummaryRole,[Parameter(Mandatory)][string]$Reason,
    [Parameter(Mandatory)][string[]]$Software,
    [ValidateSet('failed','interrupted')][string]$Status='failed',
    [string]$FailureClass='',
    [int]$SummarySchemaVersion=1,
    [string]$FailureStage='',
    [Nullable[bool]]$ThresholdResultEligible=$null,
    [hashtable]$AdditionalSummaryProperties=@{},
    [string[]]$AdditionalOutputs=@(),
    [string]$ResourceUsagePath='',
    [switch]$PreserveRawOutputs,
    [string[]]$PreserveRawOutputPaths=@(),
    [switch]$DeferCapacityFinalization
  )
  Invoke-RunToolRootContext -RepoRoot $RepoRoot -Operation {
  $document=Get-Content -LiteralPath $RunConfig -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  $runDir=Split-Path -Parent $RunConfig
  $existingManifest=Join-Path $runDir 'run_manifest.json'
  if(Test-Path -LiteralPath $existingManifest -PathType Leaf){
    $published=Get-Content -LiteralPath $existingManifest -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
    if($published.role-cne'simulation_run_manifest'-or$published.run_id-cne$document.run_id-or
       $published.project-cne$document.project-or$published.mode-cne$document.mode){
      throw 'Existing run manifest identity differs; failure cleanup cannot replace it.'
    }
    if($published.status-in@('success','failed','interrupted','superseded')){
      # Preserve the existing terminal before changing its config, summary or
      # retained outputs. This small read is not another payload verification.
      Write-Warning "Existing $($published.status) terminal retained; failure cleanup skipped for $($document.run_id)."
      return
    }
    if($published.status-cne'checkpoint'){throw 'Existing run manifest status is invalid; failure cleanup cannot replace it.'}
  }
  if(-not $document.Contains('inputs')){$document.inputs=[ordered]@{}}
  $known=@($document.inputs.Values|ForEach-Object{if($_ -is [string]){[IO.Path]::GetFullPath($_)}})
  $inputDir=Join-Path $runDir 'inputs';$index=0
  if(Test-Path -LiteralPath $inputDir -PathType Container){foreach($file in Get-ChildItem -LiteralPath $inputDir -Recurse -File|Sort-Object FullName){
    if($known-notcontains$file.FullName){$index+=1;$document.inputs[("recovered_input_{0:D3}"-f$index)]=$file.FullName}
  }}
  Write-RunJson -Path $RunConfig -Value $document
  $summaryDocument=[ordered]@{
    schema_version=$SummarySchemaVersion;role=$SummaryRole;status=$Status;reason=$Reason
  }
  if(-not[string]::IsNullOrWhiteSpace($FailureClass)){
    $summaryDocument.failure_class=$FailureClass
  }
  if(-not[string]::IsNullOrWhiteSpace($FailureStage)){
    $summaryDocument.failure_stage=$FailureStage
  }
  if($null-ne$ThresholdResultEligible){
    $summaryDocument.threshold_result_eligible=[bool]$ThresholdResultEligible
  }
  foreach($key in $AdditionalSummaryProperties.Keys){
    if($key-in@('schema_version','role','status','reason','failure_class','failure_stage','threshold_result_eligible')){
      throw "Additional failed-run summary property is reserved: $key"
    }
    $summaryDocument[$key]=$AdditionalSummaryProperties[$key]
  }
  Write-RunJson -Path $Summary -Value $summaryDocument
  $retentionActions=$null
  if(-not $PreserveRawOutputs -and $PreserveRawOutputPaths.Count-ne 0){
    throw 'Recoverable raw output paths require PreserveRawOutputs.'
  }
  if($PreserveRawOutputs){
    if($PreserveRawOutputPaths.Count-eq 0){
      throw 'PreserveRawOutputs requires at least one declared recoverable output.'
    }
    if([int]$document.schema_version-ne 2){
      throw 'Recoverable output retention requires run_config schema_version 2.'
    }
  }
  # The retention boundary validates explicit recovery declarations and owns
  # failed-run disposal. Generic terminal publication does not parse solver logs.
  if([int]$document.schema_version-eq 2){
    $existingRetentionActions=Join-Path $runDir 'retention_actions.json'
    if(Test-Path -LiteralPath $existingRetentionActions -PathType Leaf){
      # A success-path publication may already have reconciled retention before
      # a later manifest verification error.  Reuse that immutable receipt when
      # terminalizing the failure; applying retention twice is both unnecessary
      # and rejected by the retention contract.
      $retentionActions=$existingRetentionActions
    }else{
      $retentionActions=Apply-RunArtifactRetention -Python $Python -RepoRoot $RepoRoot `
        -RunConfig $RunConfig -PreservePaths $PreserveRawOutputPaths -FailedRun
    }
  }
  if(-not[string]::IsNullOrWhiteSpace($ResourceUsagePath)-and
    (Test-Path -LiteralPath $ResourceUsagePath -PathType Leaf)){
    $usage=Get-Content -LiteralPath $ResourceUsagePath -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
    if([string]$usage.status-eq'running'){
      $usage.status=$Status
    }
    if(-not[string]::IsNullOrWhiteSpace($FailureClass)){
      $usage.failure_class=$FailureClass
    }
    $finalBytes=[int64](Get-ChildItem -LiteralPath $runDir -Recurse -File|
      Measure-Object -Property Length -Sum).Sum
    $usage.final_retained_bytes=$finalBytes
    if([int64]$usage.peak_run_directory_bytes-lt$finalBytes){
      $usage.peak_run_directory_bytes=$finalBytes
    }
    # Scheduler-only usage receipts govern CPU/memory admission and do not
    # necessarily carry the campaign retention-byte limit.  Failed-run
    # publication must still finalize such a receipt instead of treating an
    # intentionally absent optional limit as a malformed object.
    $hasCompactFinalLimit = $usage.Contains('limits') -and
      $usage.limits -is [System.Collections.IDictionary] -and
      $usage.limits.Contains('compact_final_retained_bytes')
    if($hasCompactFinalLimit -and
        $finalBytes-gt[int64]$usage.limits.compact_final_retained_bytes){
      $usage.status='resource_budget_exceeded'
      $usage.failure_class='resource_budget_exceeded'
      $usage.limit_name='compact_final_retained_bytes'
      $Status='interrupted'
      Write-RunJson -Path $Summary -Value ([ordered]@{
        schema_version=1;role=$SummaryRole;status='interrupted';reason='Compact final retained-byte budget exceeded.'
        failure_class='resource_budget_exceeded'
      })
    }
    Write-RunJson -Path $ResourceUsagePath -Value $usage
    $AdditionalOutputs+=@($ResourceUsagePath)
  }
  $outputs=@($Summary)+@($AdditionalOutputs|Where-Object{
    -not[string]::IsNullOrWhiteSpace($_)-and(Test-Path -LiteralPath $_ -PathType Leaf)
  })
  if($retentionActions){$outputs+=$retentionActions}
  foreach($relative in @('results','logs','simion')){
    $directory=Join-Path $runDir $relative
    if(Test-Path -LiteralPath $directory -PathType Container){
      $outputs+=@(Get-ChildItem -LiteralPath $directory -Recurse -File|Sort-Object FullName|Select-Object -ExpandProperty FullName)
    }
  }
  Write-VerifiedRunManifest -Python $Python -RepoRoot $RepoRoot -RunConfig $RunConfig `
    -Status $Status -Software $Software -Outputs @($outputs|Select-Object -Unique) `
    -DeferCapacityFinalization:$DeferCapacityFinalization
  }
}

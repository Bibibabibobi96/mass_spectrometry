Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'

function Invoke-SingleReflectionFrontendFieldStage {
  <# Internal field stage. Caller owns the run and leases. SIMION consumes
     immutable standalone members; raw families stay in owner scratch. #>
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$Python,
    [Parameter(Mandatory)][string]$RepoRoot,
    [Parameter(Mandatory)][string]$RunDirectory,
    [Parameter(Mandatory)][string]$PreparedDirectory,
    [Parameter(Mandatory)][string]$SimionExe,
    [Parameter(Mandatory)][ref]$HostLease,
    [Parameter(Mandatory)][ref]$CapacitySession,
    [Parameter(Mandatory)]$Limits,
    [Parameter(Mandatory)][long]$ReservedRunPayloadBytes,
    [string]$CacheRoot='',
    [Diagnostics.Stopwatch]$StageElapsed=$null,
    $NativeOperations=$null,[string]$NativeResourceReleaseId='simion'
  )
  foreach($required in @('Invoke-RunToolRootContext','Write-RunJson','Update-ArtifactWorkflowCapacitySession',
    'Invoke-ResourceBudgetedProcess','Update-HostResourceStage','Get-HostResourceBudget',
    'Protect-ImmutablePaSource','Unprotect-ImmutablePaSource')){
    if(-not(Get-Command $required -ErrorAction SilentlyContinue)){throw "Frontend field stage requires caller public helper: $required"}
  }
  $run=[IO.Path]::GetFullPath($RunDirectory)
  $prepared=Join-Path ([IO.Path]::GetFullPath($PreparedDirectory)) 'inputs'
  if(-not(Test-Path -LiteralPath (Join-Path $run 'run_config.json'))){throw 'Managed run config required before field construction.'}
  if($null-eq$HostLease.Value-or$null-eq$CapacitySession.Value){throw 'Active host and workflow capacity sessions required.'}
  if(-not$CacheRoot){$CacheRoot=Join-Path (Split-Path -Parent $RepoRoot) 'artifacts/common/simion/pa_family_cache'}
  $workflow=Join-Path $RepoRoot 'integrations/workflows/single_reflection_flight'
  $builder=Join-Path $RepoRoot 'common/simion/build_dirichlet_patch_operating_pa.lua'
  $exporter=Join-Path $RepoRoot 'common/simion/export_detached_standalone_pa.lua'
  $verifier=Join-Path $workflow 'audit_frontend_working_fields.lua'
  $inputs=Join-Path $run 'inputs';$logs=Join-Path $run 'logs'
  $output=Join-Path $run 'simion/frontend_working_fields'
  $wallClockWarningNames=[Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
  New-Item -ItemType Directory -Path $output -Force|Out-Null
  function Invoke-FrontendFieldPython {
    param([string[]]$Arguments,[string]$Name)
    $stdout=Join-Path $logs ($Name+'.stdout.json');$stderr=Join-Path $logs ($Name+'.stderr.log')
    Invoke-RunToolRootContext -RepoRoot $RepoRoot -Operation {
      &$Python -B @Arguments 1>$stdout 2>$stderr
      if($LASTEXITCODE-ne0){throw "Frontend field Python stage failed: $Name (see $stderr)"}
    }
    if((Get-Item -LiteralPath $stdout).Length){return Get-Content -LiteralPath $stdout -Raw|ConvertFrom-Json -Depth 100}
  }
  function Invoke-FrontendFieldNative {
    param([string[]]$Arguments,[string]$Directory,[string]$Name)
    if($null -ne $StageElapsed -and $StageElapsed.Elapsed.TotalSeconds -gt [double]$Limits.wall_clock_seconds -and $wallClockWarningNames.Add('wall_clock_seconds')){
      Write-Warning ('RESOURCE_BUDGET_WARNING=wall_clock_seconds STAGE=instrument_field_design ' +
        'MEASURED_SECONDS={0:N3} LIMIT_SECONDS={1}' -f $StageElapsed.Elapsed.TotalSeconds,$Limits.wall_clock_seconds)
    }
    try{
    $result=Invoke-ResourceBudgetedProcess -Limits $Limits -RunDir $run `
      -UsagePath (Join-Path $logs ($Name+'.resource_usage.json')) -FilePath $SimionExe `
      -WorkingDirectory $Directory -ArgumentList $Arguments `
      -RedirectStandardOutput (Join-Path $logs ($Name+'.stdout.log')) `
      -RedirectStandardError (Join-Path $logs ($Name+'.stderr.log'))
      if($null-ne$NativeOperations){Add-FrontendNativeOperation -NativeOperations $NativeOperations -NativeResourceReleaseId $NativeResourceReleaseId -OperationId $Name -ProcessRecord $result}
    }catch{
      if($null-ne$NativeOperations){Add-FrontendNativeOperation -NativeOperations $NativeOperations -NativeResourceReleaseId $NativeResourceReleaseId -OperationId $Name -ExceptionData $_.Exception.Data}
      throw
    }
    if($result.resource_budget_exceeded-or$result.exit_code-ne0){throw "Frontend field native stage failed: $Name"}
  }
  $planCode=@'
import json,sys
from pathlib import Path
from integrations.workflows.single_reflection_flight.field_plan import build_field_plan
print(json.dumps(build_field_plan(*map(Path,sys.argv[1:4]))))
'@
  $bundle=Invoke-FrontendFieldPython -Arguments @('-c',$planCode,$prepared,$SimionExe,$RepoRoot) -Name 'frontend_working_plan'
  $fieldHandoffs=@{}
  $requestPath=Join-Path $prepared 'request.json'
  if(Test-Path -LiteralPath $requestPath){
    $request=Get-Content -LiteralPath $requestPath -Raw|ConvertFrom-Json -AsHashtable -Depth 100
  }else{$request=@{}}
  if($request.ContainsKey('continuation')-and$request.continuation.ContainsKey('frontend_field_transactions')){
    $provenance=Get-Content -LiteralPath (Join-Path $prepared 'source_provenance.json') -Raw|ConvertFrom-Json -AsHashtable -Depth 100
    $index=0
    foreach($entry in $request.continuation.frontend_field_transactions){
      $index++
      $fieldHandoffs[([string]$entry.domain_id+'/'+[string]$entry.member_id)]=@{
        schema_version=1
        transaction_record=$provenance.input_records[('continuation_field_transaction_{0:D3}' -f $index)]
        predecessor_manifest=$provenance.input_records.continuation_parent_manifest
        stopped_receipt=$provenance.input_records.continuation_stopped_receipt
      }
    }
  }
  $domainReceipts=@();$allPaths=@();$parentFields=@{};$cacheKeys=@()
  foreach($unbound in $bundle.domains){
    $domainPlan=$unbound
    $domainName=[string]$domainPlan.domain_id
    if($domainName-eq'entrance_refinement'){
      $bindCode=@'
import json,sys
from pathlib import Path
from integrations.workflows.single_reflection_flight.field_plan import bind_parent_fields
bundle=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8-sig'))
print(json.dumps(bind_parent_fields(bundle['domains'][1],json.loads(sys.argv[2]))))
'@
      $domainPlan=Invoke-FrontendFieldPython -Arguments @('-c',$bindCode,(Join-Path $logs 'frontend_working_plan.stdout.json'),($parentFields|ConvertTo-Json -Depth 100 -Compress)) -Name 'frontend_entrance_refinement_plan'
    }
    $domainScratch=Join-Path $output ($domainName+'_audit_geometry')
    $raw=Join-Path $domainScratch 'frontend.pa#'
    $records=@()
    $transaction=$null
    try {
      foreach($member in $domainPlan.members){
        $merged=[ordered]@{}
        foreach($property in $domainPlan.PSObject.Properties){$merged[$property.Name]=$property.Value}
        foreach($property in $member.PSObject.Properties){$merged[$property.Name]=$property.Value}
        $plan=[pscustomobject]$merged
        $prefix=$domainName+'_'+[string]$member.member_id
        $planPath=Join-Path $inputs ($prefix+'_field_plan.json')
        Write-RunJson -Path $planPath -Value $plan -Depth 100
        $point=$plan.working_points[0];$source=$null
        if($plan.PSObject.Properties.Name-contains'frozen_field_source'){$source=$plan.frozen_field_source}
        $identityPath=if($null-ne$source){[string]$source.identity_path}else{Join-Path $inputs ($prefix+'_cache_identity.json')}
        $key=if($null-ne$source){[string]$source.cache_key}else{[string]$plan.cache_key}
        if($null-eq$source){Write-RunJson -Path $identityPath -Value $plan.identity -Depth 100}
        # Explicit source generations remain pinned at their original capacity owner.
        if($null-eq$source){
          $scope=Update-ArtifactWorkflowCapacitySession -Python $Python -RepoRoot $RepoRoot -Session $CapacitySession.Value -ProtectedCacheKeys @($key)
          $CapacitySession.Value=$scope.session
        }
        $cacheKeys+=@($key)
        $keyRoot=Join-Path $CacheRoot $key
        $cacheArgs=@('-m','common.simion.pa_family_cache','--cache-root',$CacheRoot,'--identity',$identityPath,'--filenames',($plan.filenames-join','))
        $transactionArgs=$cacheArgs+@('--action','advance-transaction','--owner',([IO.Path]::GetFileName($run)),'--producer-run-config',(Join-Path $run 'run_config.json'),'--recovery-policy','none','--published-pin-reason','Retain standalone frontend fields required by saved instrument workbenches.')
        $generation=$null;$transaction=$null;$refinePerformed=$false;$published=$false
        [long]$keyBytesBefore=0
        if($null-ne$source){$generation=[string]$source.generation_directory}
        else {
          if(Test-Path -LiteralPath $keyRoot){$keyBytesBefore=[long]((Get-ChildItem -LiteralPath $keyRoot -Recurse -File|Measure-Object Length -Sum).Sum)}
          $probe=Invoke-FrontendFieldPython -Arguments ($cacheArgs+@('--action','probe')) -Name ($prefix+'_probe')
          if($probe.disposition-eq'hit'){$generation=[string]$probe.generation_directory}
          elseif($probe.disposition-ne'miss'){throw "Frontend member cache is not reusable: $($probe.disposition)"}
          else {
            [long]$cacheFloor=[long]$plan.grid[0]*[long]$plan.grid[1]*[long]$plan.grid[2]*24
            [long]$memberCommitment=$ReservedRunPayloadBytes+$cacheFloor
            if([long]$CapacitySession.Value.committed_new_bytes-lt$memberCommitment){
              $scope=Update-ArtifactWorkflowCapacitySession -Python $Python -RepoRoot $RepoRoot -Session $CapacitySession.Value -RemainingCommittedNewBytes $memberCommitment
              $CapacitySession.Value=$scope.session
            }
            $beginArguments=$transactionArgs
            $route=$domainName+'/'+[string]$member.member_id
            if($fieldHandoffs.ContainsKey($route)){
              $handoff=$fieldHandoffs[$route]
              $handoff.capacity_lease_id=[string]$CapacitySession.Value.lease_id
              $handoff.capacity_lease_owner=[string]$CapacitySession.Value.owner
              $handoffPath=Join-Path $inputs ($prefix+'_producer_handoff.json')
              Write-RunJson -Path $handoffPath -Value $handoff -Depth 100
              $beginArguments+=@('--producer-handoff',$handoffPath)
            }
            $transaction=Invoke-FrontendFieldPython -Arguments $beginArguments -Name ($prefix+'_begin')
            if($transaction.action_required-eq'complete'){$generation=[string]$transaction.generation_directory;$published=$true}
          }
        }
        $audit=$null
        if($null-ne$generation){
          $reuseCode=@'
import json,sys
from pathlib import Path
from integrations.workflows.single_reflection_flight.field_plan import reusable_audit
print(json.dumps(reusable_audit(json.loads(Path(sys.argv[1]).read_text(encoding='utf-8-sig')),Path(sys.argv[2]),Path(sys.argv[3]))))
'@
          $reuse=Invoke-FrontendFieldPython -Arguments @('-c',$reuseCode,$planPath,$generation,$verifier) -Name ($prefix+'_audit_reuse')
          if($null-ne$reuse){$audit=[string]$reuse.path}
        }
        if($null-eq$audit){
          New-Item -ItemType Directory -Path $domainScratch -Force|Out-Null
          if(-not(Test-Path -LiteralPath $raw)){
            [long]$rawCommitment=$ReservedRunPayloadBytes+[long]$plan.grid[0]*[long]$plan.grid[1]*[long]$plan.grid[2]*8
            if([long]$CapacitySession.Value.committed_new_bytes-lt$rawCommitment){
              $scope=Update-ArtifactWorkflowCapacitySession -Python $Python -RepoRoot $RepoRoot -Session $CapacitySession.Value -RemainingCommittedNewBytes $rawCommitment
              $CapacitySession.Value=$scope.session
            }
            $gem=Join-Path $domainScratch 'frontend.gem'
            Copy-Item -LiteralPath (Join-Path $prepared ([string]$plan.gem_filename)) -Destination $gem -Force
            Invoke-FrontendFieldNative -Arguments @('--nogui','--noprompt','gem2pa',$gem,$raw) -Directory $domainScratch -Name ($domainName+'_gem2pa')
          }
          if($null-ne$transaction-and$transaction.action_required-eq'build'){
            $scratch=[string]$transaction.scratch_directory;$payload=[string]$transaction.build_directory
            $working=Join-Path $scratch 'working.pa0';$destination=Join-Path $payload ([string]$point.filename)
            if(-not(Test-Path -LiteralPath $destination)){
              $parentSource='zero_neumann';$sourceOrigin='0,0,0';$patchOrigin='0,0,0';$parentGuard=$null
              if($domainName-eq'entrance_refinement'){
                $parent=$parentFields[[string]$member.member_id];$parentSource=[string]$parent.record.path
                $sourceOrigin=(@('x','y','z')|ForEach-Object{([double]$plan.parent_origin_mm.$_).ToString('G17',[Globalization.CultureInfo]::InvariantCulture)})-join','
                $patchOrigin=(@('x','y','z')|ForEach-Object{([double]$plan.instance_origin_mm.$_).ToString('G17',[Globalization.CultureInfo]::InvariantCulture)})-join','
              }
              try {
                if($domainName-eq'entrance_refinement'){
                  $null=Protect-ImmutablePaSource -Source $parentSource -ExpectedBytes ([long]$parent.record.bytes) -ExpectedSha256 ([string]$parent.record.sha256)
                  $parentGuard=$parentSource
                }
                $HostLease.Value=Update-HostResourceStage -Lease $HostLease.Value -Stage pa_refine -Budget (Get-HostResourceBudget -Role SIMION -Stage pa_refine) -RetainedMemoryBytes 0
                Invoke-FrontendFieldNative -Arguments @('--nogui','--noprompt','lua',$builder,$raw,$working,$parentSource,$sourceOrigin,$patchOrigin,[string]$point.voltage_argument,[string]$point.convergence_argument) -Directory $scratch -Name ($prefix+'_refine_'+$point.filename)
              } finally {
                if($null-ne$parentGuard){$null=Unprotect-ImmutablePaSource -Source $parentGuard}
                $HostLease.Value=Update-HostResourceStage -Lease $HostLease.Value -Stage prepare -Budget (Get-HostResourceBudget -Role SIMION -Stage prepare) -RetainedMemoryBytes 0
              }
              $refinePerformed=$true;$exported=Join-Path $scratch ([string]$point.filename)
              if(Test-Path -LiteralPath $exported){Remove-Item -LiteralPath $exported}
              Invoke-FrontendFieldNative -Arguments @('--nogui','--noprompt','lua',$exporter,$working,$exported) -Directory $scratch -Name ($prefix+'_export_'+$point.filename)
              Move-Item -LiteralPath $exported -Destination $destination
            }
            $paPath=$destination
          } elseif($null-ne$transaction-and$transaction.action_required-eq'verify') {
            $paPath=Join-Path ([string]$transaction.build_directory) ([string]$point.filename)
          } else {$paPath=Join-Path $generation ([string]$point.filename)}
          $audit=Join-Path $logs ($prefix+'_fields_audit.json')
          $spec=Join-Path $inputs ($prefix+'_audit.tsv')
          $specCode=@'
import json,sys
from pathlib import Path
from integrations.workflows.single_reflection_flight.field_plan import write_audit_spec
plan=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8-sig'))
plan['working_points'][0]['path']=sys.argv[3]
write_audit_spec(plan,Path(sys.argv[2]),Path('.'),Path(sys.argv[4]))
'@
          $null=Invoke-FrontendFieldPython -Arguments @('-c',$specCode,$planPath,$raw,$paPath,$spec) -Name ($prefix+'_audit_spec')
          $auditGuard=$null
          try {
            if($null-ne$generation){
              $cacheManifest=Get-Content -LiteralPath (Join-Path $generation 'cache_manifest.json') -Raw|ConvertFrom-Json -Depth 100
              $paRecord=@($cacheManifest.files|Where-Object{$_.name-eq$point.filename})[0]
              $null=Protect-ImmutablePaSource -Source $paPath -ExpectedBytes ([long]$paRecord.bytes) -ExpectedSha256 ([string]$paRecord.sha256)
              $auditGuard=$paPath
            }
            Invoke-FrontendFieldNative -Arguments @('--nogui','--noprompt','lua',$verifier,$spec,$audit) -Directory $domainScratch -Name ($prefix+'_audit')
          } finally {if($null-ne$auditGuard){$null=Unprotect-ImmutablePaSource -Source $auditGuard}}
          $stampCode=@'
import json,sys
from pathlib import Path
from integrations.workflows.single_reflection_flight.field_plan import audit_input_identity
from common.contracts.file_identity import file_sha256
p=Path(sys.argv[1]);report=json.loads(p.read_text())
report['audit_input_sha256']=audit_input_identity(json.loads(Path(sys.argv[2]).read_text(encoding='utf-8-sig')))
report['audit_verifier_sha256']=file_sha256(Path(sys.argv[3]))
p.write_text(json.dumps(report),encoding='utf-8')
'@
          $null=Invoke-FrontendFieldPython -Arguments @('-c',$stampCode,$audit,$planPath,$verifier) -Name ($prefix+'_audit_identity')
        }
        if($null-ne$transaction-and$transaction.action_required-eq'build'){
          $transaction=Invoke-FrontendFieldPython -Arguments $transactionArgs -Name ($prefix+'_seal')
        }
        if($null-ne$transaction-and$transaction.action_required-eq'verify'){
          $evidence=Join-Path $inputs ($prefix+'_cache_verification.json')
          Write-RunJson -Path $evidence -Depth 8 -Value @{schema_version=1;role='simion_pa_family_verification';status='pass';cache_key=$key;inventory_sha256=$transaction.inventory_sha256;solver_release='SIMION 2020';verifier_path=$verifier;verifier_sha256=(Get-FileHash -LiteralPath $verifier -Algorithm SHA256).Hash;verification_output_path=$audit;verification_output_sha256=(Get-FileHash -LiteralPath $audit -Algorithm SHA256).Hash}
          $transaction=Invoke-FrontendFieldPython -Arguments ($transactionArgs+@('--verification-evidence',$evidence)) -Name ($prefix+'_publish')
          $published=$true;$generation=[string]$transaction.generation_directory
        }
        if($null-ne$transaction-and$transaction.action_required-ne'complete'){throw 'Frontend member transaction did not complete.'}
        $manifest=Get-Content -LiteralPath (Join-Path $generation 'cache_manifest.json') -Raw|ConvertFrom-Json -Depth 100
        $memberRecord=@($manifest.files|Where-Object{$_.name-eq$point.filename})
        if($memberRecord.Count-ne1){throw 'Published member absent or duplicated.'}
        $record=@{kind=[string]$point.kind;path=(Join-Path $generation ([string]$point.filename));bytes=[long]$memberRecord[0].bytes;sha256=[string]$memberRecord[0].sha256;read_only=$true;cache_key=$key;generation_directory=$generation;cache_filenames=@($manifest.files|ForEach-Object{$_.name});source_schema_version=if($null-ne$source){[int]$source.source_schema_version}else{3};cache_identity_record=@{path=$identityPath;bytes=(Get-Item -LiteralPath $identityPath).Length;sha256=(Get-FileHash -LiteralPath $identityPath -Algorithm SHA256).Hash};audit_record=@{path=$audit;bytes=(Get-Item -LiteralPath $audit).Length;sha256=(Get-FileHash -LiteralPath $audit -Algorithm SHA256).Hash};refine_performed=$refinePerformed}
        if($point.PSObject.Properties.Name-contains'working_point_id'){$record.working_point_id=[string]$point.working_point_id}
        if($null-ne$source){$record.source=@{schema_version=[int]$source.source_schema_version;cache_key=$key;generation_directory=$generation}}
        $records+=@($record);$allPaths+=@([string]$record.path)
        if($domainName-eq'parent'){$parentFields[[string]$member.member_id]=@{cache_key=$key;record=$record}}
        if($published){
          [long]$keyBytesAfter=[long]((Get-ChildItem -LiteralPath $keyRoot -Recurse -File|Measure-Object Length -Sum).Sum)
          [long]$remaining=[long]$CapacitySession.Value.committed_new_bytes-[math]::Max([long]0,$keyBytesAfter-$keyBytesBefore)
          if($remaining-lt$ReservedRunPayloadBytes){throw 'Workflow commitment cannot cover actual published cache plus reserved run payload.'}
          $scope=Update-ArtifactWorkflowCapacitySession -Python $Python -RepoRoot $RepoRoot -Session $CapacitySession.Value -ProtectedCacheKeys @($key) -RemainingCommittedNewBytes $remaining
          $CapacitySession.Value=$scope.session
        }
      }
      $domainReceipts+=@{domain_id=$domainName;working_points=$records}
    } catch {
      $scientificFailure=$_
      # Native calls have returned before this catch. Keep retained payload and
      # working files accounted while the owner still holds its capacity lease.
      if($null-ne$transaction-and$transaction.status-eq'building'){
        try {
          $null=Invoke-FrontendFieldPython -Arguments ($transactionArgs+@('--record-stage-only')) -Name ($prefix+'_stopped_stage_accounting')
        } catch {
          $reason='Stopped frontend transaction accounting failed: '+$_.Exception.Message
          $CapacitySession.Value|Add-Member -NotePropertyName defer_capacity_finalization -NotePropertyValue $reason -Force
          Write-Warning $reason
        }
      }
      throw $scientificFailure
    } finally {
      $HostLease.Value=Update-HostResourceStage -Lease $HostLease.Value -Stage prepare -Budget (Get-HostResourceBudget -Role SIMION -Stage prepare) -RetainedMemoryBytes 0
      foreach($name in @('frontend.pa#','frontend.gem')){
        $temporary=Join-Path $domainScratch $name
        if(Test-Path -LiteralPath $temporary){Remove-Item -LiteralPath $temporary -Force}
      }
    }
  }
  $bankCode=@'
import json,sys
from integrations.workflows.single_reflection_flight.field_plan import field_bank
design=json.loads(sys.argv[1])
print(json.dumps(field_bank(design,sys.argv[2].split(','))))
'@
  $designArgument=Get-Content -LiteralPath (Join-Path $prepared 'frontend_field_design.json') -Raw
  $bankDocument=Invoke-FrontendFieldPython -Arguments @('-c',$bankCode,$designArgument,((@($bundle.domains|ForEach-Object{$_.domain_id}))-join',')) -Name 'frontend_working_bank'
  $bank=Join-Path $output 'standalone_field_bank.json'
  Write-RunJson -Path $bank -Value $bankDocument -Depth 10
  $receipt=Join-Path $inputs 'frontend_working_field_stage_receipt.json'
  $receiptDocument=@{schema_version=3;role='single_reflection_frontend_working_fields';status='success';domains=$domainReceipts;field_bank_record=@{path=$bank;bytes=(Get-Item -LiteralPath $bank).Length;sha256=(Get-FileHash -LiteralPath $bank -Algorithm SHA256).Hash};fly_performed=$false;validation_scope='native_grid_and_physical_metal_voltage_samples_only__not_field_convergence'}
  if($bundle.PSObject.Properties.Name-contains'rf_reference_voltage_v'){$receiptDocument.rf_reference_voltage_v=$bundle.rf_reference_voltage_v}
  Write-RunJson -Path $receipt -Depth 100 -Value $receiptDocument
  $scope=Update-ArtifactWorkflowCapacitySession -Python $Python -RepoRoot $RepoRoot -Session $CapacitySession.Value -RemainingCommittedNewBytes $ReservedRunPayloadBytes
  $CapacitySession.Value=$scope.session
  return [pscustomobject]@{field_paths=$allPaths;field_bank=$bank;cache_receipt=$receipt;cache_keys=@($cacheKeys|Select-Object -Unique)}
}

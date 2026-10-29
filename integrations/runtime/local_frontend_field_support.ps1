Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'

function Invoke-LocalFrontendFieldCompositions {
  <# Project the published standalone inputs once for all three working points.
     Public helpers retain source write/delete guards until the last native
     process has exited. Private inputs retain their first verified read guard
     across every working point; outputs are separate new files. #>
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$SelectionPath,
    [Parameter(Mandatory)][object[]]$Compositions,
    [Parameter(Mandatory)][string]$ComposerPath,
    [Parameter(Mandatory)][string]$OutputDirectory,
    [Parameter(Mandatory)][scriptblock]$InvokeNative
  )
  $records=@((Get-Content -LiteralPath $SelectionPath -Raw|ConvertFrom-Json).records)
  $directory=Join-Path ([IO.Path]::GetTempPath()) ('simion_pa_links_local_fields_'+[guid]::NewGuid().ToString('N').Substring(0,12))
  $projected=@{};$copied=@();$sourceChecks=@();$preserveActiveInputs=$false;$compositionFailure=$null
  try {
    foreach($record in $records){
      $source=[string]$record.path
      if($projected.ContainsKey($source)){throw 'Duplicate standalone response source.'}
      $projected[$source]=New-ShortPaCopy -Source $source `
        -Destination (Join-Path $directory ('r{0}.pa'-f[int]$record.response_id)) `
        -ExpectedBytes ([int64]$record.bytes) -ExpectedSha256 ([string]$record.sha256) -GuardDestinationReadOnly
      $copied+=$record
    }
    foreach($job in $Compositions){
      if(Test-Path -LiteralPath ([string]$job.output)){throw 'Local working-point destination already exists; use a fresh managed run.'}
      $used=@([string]$job.base)+@($job.terms|ForEach-Object{[string]$_.path})
      foreach($source in $used){if(-not$projected.ContainsKey($source)){throw "Composition source is absent from the verified selection: $source"}}
      $arguments=@('--nogui','--noprompt','lua',$ComposerPath,[string]$projected[[string]$job.base],[string]$job.output)
      foreach($term in $job.terms){$arguments+=([string]$projected[[string]$term.path]+','+([double]$term.coefficient).ToString('G17',[Globalization.CultureInfo]::InvariantCulture))}
      & $InvokeNative $arguments $OutputDirectory ('local_field_compose_'+$job.kind)
      # The first verification's actual read guard must remain live; acquiring
      # a guard after a writable interval is not proof of the original bytes.
      foreach($source in @($used|Select-Object -Unique)){
        $identity=Get-ShortPaCopyIdentity -Path ([string]$projected[$source])
        if(-not$identity.identity_guarded){throw 'Local field input lost its verified read guard.'}
      }
    }
  } catch {
    $compositionFailure=$_
    if($_.Exception.Data.Contains('observed_process_exit_confirmed')-and
       $_.Exception.Data['observed_process_exit_confirmed']-is[bool]-and
       -not$_.Exception.Data['observed_process_exit_confirmed']){
      $preserveActiveInputs=$true
      $_.Exception.Data['local_field_preserved_input_directory']=$directory
    }
    throw
  } finally {
    if(-not$preserveActiveInputs){
      try {
        try {
          foreach($record in $copied){
            $check=Protect-ImmutablePaSource -Source ([string]$record.path) `
              -ExpectedBytes ([int64]$record.bytes) -ExpectedSha256 ([string]$record.sha256)
            try{$sourceChecks+=$check}finally{
              if(-not$check.already_protected){$null=Unprotect-ImmutablePaSource -Source ([string]$record.path)}
            }
          }
        } finally {
          Remove-ShortPaCopyDirectory -Path $directory
        }
      }catch{
        if($null-eq$compositionFailure){throw}
        $compositionFailure.Exception.Data['local_field_cleanup_error']=$_
        Write-Warning "Local field input cleanup failed; original composition error is retained: $_" -WarningAction Continue
      }
    }
  }
  return [pscustomobject]@{response_copies=$copied.Count;response_copy_bytes=[int64](($copied|Measure-Object -Property bytes -Sum).Sum);
    input_representation='manifest_bound_public_short_standalone_copies';source_verification_after_native=$sourceChecks;
    temporary_directory=$directory;temporary_copies_removed=(-not(Test-Path -LiteralPath $directory))}
}

function Invoke-LocalFrontendFieldStage {
  <# Internal stage of family_source_closure. The caller owns the run, capacity
     session, solver discovery and terminal publication. No Fly or IOB here. #>
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
    [string]$CacheRoot='',
    [Diagnostics.Stopwatch]$StageElapsed=$null
  )
  # The orchestration owner imports the live public helpers before loading
  # this frozen stage. Reloading host helpers from a run snapshot would derive
  # a second host ledger beside that snapshot instead of retaining its lease.
  foreach($required in @('Invoke-RunToolRootContext','Write-RunJson','Update-ArtifactWorkflowCapacitySession','Invoke-ResourceBudgetedProcess','Update-HostResourceStage','Get-HostResourceBudget','New-ShortPaCopy','Get-ShortPaCopyIdentity','Protect-ImmutablePaSource','Unprotect-ImmutablePaSource','Remove-ShortPaCopyDirectory')){
    if(-not(Get-Command $required -ErrorAction SilentlyContinue)){throw "Local field stage requires the caller's live public helper: $required"}
  }
  $run=[IO.Path]::GetFullPath($RunDirectory)
  $prepared=Join-Path ([IO.Path]::GetFullPath($PreparedDirectory)) 'inputs'
  $runtime=Join-Path $RepoRoot 'integrations/runtime'
  $log=Join-Path $run 'logs';$inputsDir=Join-Path $run 'inputs'
  $output=Join-Path $run 'simion/local_frontend_fields'
  $wallClockWarningNames=[Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
  if(-not(Test-Path -LiteralPath (Join-Path $run 'run_config.json'))){throw 'Managed run config required before field construction.'}
  if($null-eq$HostLease.Value-or$null-eq$CapacitySession.Value){throw 'Active host and workflow capacity sessions required.'}
  if(-not$CacheRoot){$CacheRoot=Join-Path (Split-Path -Parent $RepoRoot) 'artifacts/common/simion/pa_family_cache'}
  New-Item -ItemType Directory -Path $output -Force|Out-Null
  # The caller already froze these implementations in the executable snapshot.
  # Use that single registered source rather than copy/hash a second tool set.
  $frozenTools=@{}
  foreach($tool in @('initialize_fast_adjust_pa_basis.lua','verify_local_frontend_fields.lua','export_standalone_pa.lua','compose_standalone_pa.lua')){
    $source=if($tool-in@('export_standalone_pa.lua','compose_standalone_pa.lua')){Join-Path $RepoRoot ('common/simion/'+$tool)}else{Join-Path $runtime $tool}
    $frozenTools[$tool]=$source
  }
  function Invoke-LocalFieldPython {
    param([string[]]$Arguments,[string]$Name)
    $stdout=Join-Path $log ($Name+'.stdout.json');$stderr=Join-Path $log ($Name+'.stderr.log')
    Invoke-RunToolRootContext -RepoRoot $RepoRoot -Operation {
      &$Python -B @Arguments 1>$stdout 2>$stderr
      if($LASTEXITCODE-ne0){throw "Local field Python stage failed: $Name (see $stderr)"}
    }
    if((Get-Item -LiteralPath $stdout).Length){return Get-Content -LiteralPath $stdout -Raw|ConvertFrom-Json -Depth 80}
  }
  function Invoke-LocalFieldNative {
    param([string[]]$Arguments,[string]$Directory,[string]$Name)
    if($null -ne $StageElapsed -and $StageElapsed.Elapsed.TotalSeconds -gt [double]$Limits.wall_clock_seconds -and $wallClockWarningNames.Add('wall_clock_seconds')){
      Write-Warning ('RESOURCE_BUDGET_WARNING=wall_clock_seconds STAGE=instrument_field_design ' +
        'MEASURED_SECONDS={0:N3} LIMIT_SECONDS={1}' -f $StageElapsed.Elapsed.TotalSeconds,$Limits.wall_clock_seconds)
    }
    $result=Invoke-ResourceBudgetedProcess -Limits $Limits -RunDir $run `
      -UsagePath (Join-Path $log ($Name+'.resource_usage.json')) -FilePath $SimionExe `
      -WorkingDirectory $Directory -ArgumentList $Arguments `
      -RedirectStandardOutput (Join-Path $log ($Name+'.stdout.log')) `
      -RedirectStandardError (Join-Path $log ($Name+'.stderr.log'))
    if($result.resource_budget_exceeded-or$result.exit_code-ne0){throw "Local field native stage failed: $Name"}
  }
  $planCode=@'
import json,sys
from pathlib import Path
from integrations.runtime.frontend_field_plan import build_field_plan
print(json.dumps(build_field_plan(*map(Path,sys.argv[1:4]))))
'@
  $plan=Invoke-LocalFieldPython -Arguments @('-c',$planCode,$prepared,$SimionExe,$runtime) -Name 'local_field_plan'
  $plan.recipe.exporter_path=$frozenTools['export_standalone_pa.lua']
  $identityPath=Join-Path $inputsDir 'local_frontend_pa_cache_identity.json'
  $recipePath=Join-Path $inputsDir 'local_frontend_response_recipe.json'
  Write-RunJson -Path $identityPath -Value $plan.identity -Depth 80
  Write-RunJson -Path $recipePath -Value $plan.recipe -Depth 20
  $scope=Update-ArtifactWorkflowCapacitySession -Python $Python -RepoRoot $RepoRoot -Session $CapacitySession.Value -ProtectedCacheKeys @([string]$plan.cache_key)
  $CapacitySession.Value=$scope.session
  $cacheArgs=@('-m','common.simion.pa_family_cache','--cache-root',$CacheRoot,'--identity',$identityPath,'--filenames',($plan.filenames-join','))
  $probe=Invoke-LocalFieldPython -Arguments ($cacheArgs+@('--action','probe')) -Name 'local_field_cache_probe'
  $published=$false;$refinePerformed=$false
  $HostLease.Value=Update-HostResourceStage -Lease $HostLease.Value -Stage pa_refine -Budget (Get-HostResourceBudget -Role SIMION -Stage pa_refine) -RetainedMemoryBytes 0
  $stageFailure=$null
  try {
    if($probe.disposition-eq'hit'){$generation=[string]$probe.generation_directory}
    elseif($probe.disposition-ne'miss'){throw "Local field cache is not reusable: $($probe.disposition)"}
    else {
      $transactionArgs=$cacheArgs+@('--action','advance-transaction','--owner',([IO.Path]::GetFileName($run)), '--producer-run-config',(Join-Path $run 'run_config.json'),'--recovery-policy','none','--response-receipt',$recipePath)
      $transaction=Invoke-LocalFieldPython -Arguments $transactionArgs -Name 'local_field_transaction_begin'
      if($transaction.action_required-eq'build'){
        $scratch=[string]$transaction.scratch_directory;$payload=[string]$transaction.build_directory
        # Only private owner scratch is writable by SIMION; published native
        # members are never reopened, even after a cache hit.
        Copy-Item -LiteralPath (Join-Path $prepared 'frontend.gem') -Destination (Join-Path $scratch 'frontend.gem') -Force
        Copy-Item -LiteralPath (Join-Path $prepared 'frontend.pa+') -Destination (Join-Path $scratch 'frontend.pa+') -Force
        $spec=Join-Path $inputsDir 'local_frontend_response_verification.tsv'
        $lines=[Collections.Generic.List[string]]::new();$lines.Add('local_frontend_response_verification_v4')
        $lines.Add(('model'+"`t"+$plan.model_id+"`t"+$plan.mode_count+"`t"+($plan.mode_ids-join"`t")))
        $lines.Add(('grid'+"`t"+($plan.grid-join"`t")))
        foreach($id in $plan.mode_ids){$lines.Add(('response'+"`t"+$id+"`t"+(Join-Path ([string]$transaction.build_directory) "frontend.response_$id.pa")))}
        $lines.Add(('physical_count'+"`t"+@($plan.physical_samples).Count+"`t"+@($plan.physical_samples|Where-Object{$_.kind-eq'rod'}).Count))
        foreach($body in $plan.physical_samples){$lines.Add(('physical'+"`t"+$body.label+"`t"+$body.electrode_id+"`t"+$body.kind+"`t"+($body.gu-join"`t")))}
        foreach($sample in $plan.samples){$lines.Add(('sample'+"`t"+($sample-join"`t")))}
        [IO.File]::WriteAllText($spec,($lines-join"`n")+"`n",[Text.UTF8Encoding]::new($false))
        Invoke-LocalFieldNative -Arguments @('--nogui','--noprompt','gem2pa',(Join-Path $scratch 'frontend.gem'),(Join-Path $scratch 'frontend.pa#')) -Directory $scratch -Name 'local_field_gem2pa'
        Invoke-LocalFieldNative -Arguments @('--nogui','--noprompt','lua',$frozenTools['verify_local_frontend_fields.lua'],$spec,(Join-Path $log 'local_frontend_raw_ids.tsv'),'raw',(Join-Path $scratch 'frontend.pa#')) -Directory $scratch -Name 'local_field_raw_physical_ids'
        Invoke-LocalFieldNative -Arguments @('--nogui','--noprompt','lua',$frozenTools['initialize_fast_adjust_pa_basis.lua'],(Join-Path $scratch 'frontend.pa#')) -Directory $scratch -Name 'local_field_refine_declared_modes'
        $refinePerformed=$true
        $allowed=@(0)+@($plan.mode_ids|ForEach-Object{[int]$_})
        foreach($member in Get-ChildItem -LiteralPath $scratch -File){if($member.Name-match'^frontend\.pa(\d+)$'-and[int]$Matches[1]-notin$allowed){throw 'Refine unexpectedly produced physical-basis members instead of the declared model modes.'}}
        foreach($id in $plan.mode_ids){
          Invoke-LocalFieldNative -Arguments @('--nogui','--noprompt','lua',$frozenTools['export_standalone_pa.lua'],(Join-Path $scratch "frontend.pa$id"),(Join-Path $scratch "frontend.response_$id.pa")) -Directory $scratch -Name "local_field_export_$id"
        }
        foreach($name in $plan.filenames){if($name-in@('standalone_response_set.json','standalone_mode_normalization.tsv')){continue};$source=Join-Path $scratch $name;if(-not(Test-Path -LiteralPath $source)){throw "Missing solved family member: $name"};Move-Item -LiteralPath $source -Destination (Join-Path $payload $name)}
        $verificationOutput=Join-Path $log 'local_frontend_response_samples.tsv'
        $verifier=$frozenTools['verify_local_frontend_fields.lua']
        Invoke-LocalFieldNative -Arguments @('--nogui','--noprompt','lua',$verifier,$spec,$verificationOutput) -Directory $run -Name 'local_field_verify'
        Copy-Item -LiteralPath $verificationOutput -Destination (Join-Path $payload 'standalone_mode_normalization.tsv')
        $transaction=Invoke-LocalFieldPython -Arguments $transactionArgs -Name 'local_field_transaction_seal'
      }
      if($transaction.action_required-eq'verify'){
        $verificationOutput=Join-Path $log 'local_frontend_response_samples.tsv'
        $verifier=$frozenTools['verify_local_frontend_fields.lua']
        if(-not(Test-Path -LiteralPath $verificationOutput)){throw 'Measured normalization evidence missing; cannot publish unmeasured responses.'}
        $evidence=Join-Path $inputsDir 'local_frontend_cache_verification.json'
        Write-RunJson -Path $evidence -Depth 8 -Value @{schema_version=1;role='simion_pa_family_verification';status='pass';cache_key=$plan.cache_key;inventory_sha256=$transaction.inventory_sha256;solver_release='SIMION 2020';verifier_path=$verifier;verifier_sha256=(Get-FileHash -LiteralPath $verifier -Algorithm SHA256).Hash;verification_output_path=$verificationOutput;verification_output_sha256=(Get-FileHash -LiteralPath $verificationOutput -Algorithm SHA256).Hash}
        $transaction=Invoke-LocalFieldPython -Arguments ($transactionArgs+@('--verification-evidence',$evidence)) -Name 'local_field_transaction_publish'
        $published=$true
      }
      if($transaction.action_required-ne'complete'){throw 'Local field transaction did not reach published completion.'}
      $generation=[string]$transaction.generation_directory
      if($published){
        $publishedBytes=[int64]((Get-ChildItem -LiteralPath (Join-Path $CacheRoot ([string]$plan.cache_key)) -Recurse -File|Measure-Object Length -Sum).Sum)
        $remaining=[int64]$CapacitySession.Value.committed_new_bytes-$publishedBytes
        if($remaining-lt0){throw 'Actual PA cache publication exceeds the declared workflow commitment.'}
        $scope=Update-ArtifactWorkflowCapacitySession -Python $Python -RepoRoot $RepoRoot -Session $CapacitySession.Value -ProtectedCacheKeys @([string]$plan.cache_key) -RemainingCommittedNewBytes $remaining
        $CapacitySession.Value=$scope.session
      }
    }
    $selection=Join-Path $inputsDir 'local_frontend_standalone_selection.json'
    $null=Invoke-LocalFieldPython -Arguments @('-m','integrations.runtime.standalone_pa_family','--directory',$generation,'--prefix','frontend','--response-ids',($plan.mode_ids-join','),'--manifest',(Join-Path $generation 'cache_manifest.json'),'--output',$selection,'--metadata-only') -Name 'local_field_select'
    $composeCode=@'
import json,sys
from pathlib import Path
from integrations.runtime.standalone_field_bank import resolve_mode_states,composition_terms,read_response_normalization
from integrations.runtime.build_single_flight_program import STANDALONE_DYNAMIC_FIELD_BANK_SCHEMA_VERSION,STANDALONE_DYNAMIC_FIELD_BANK_ROLE,STANDALONE_DYNAMIC_FIELD_RUNTIME_REPRESENTATION
p,selection,output,normalization_path=map(Path,sys.argv[1:5])
f=json.loads((p/'frontend_contract.json').read_text());u=json.loads((p/'guide_contract.json').read_text())
states=resolve_mode_states(u,f,f['pa_plus_solution_model'])
records=json.loads(selection.read_text())['records'];jobs=[]
normalization=read_response_normalization(normalization_path,records)
names={'carrier_off':'coarse_frontend.carrier_off.pa','rf_differential_unit':'coarse_frontend.rf_differential.pa','pulse_delta':'coarse_frontend.pulse_delta.pa'}
for kind,coefficients in states.items():
 base,terms=composition_terms(records,coefficients,response_normalization_v=normalization["mode_reference_v"]);jobs.append({'kind':kind,'base':base,'terms':terms,'output':str(output/names[kind])})
bank={'schema_version':STANDALONE_DYNAMIC_FIELD_BANK_SCHEMA_VERSION,'role':STANDALONE_DYNAMIC_FIELD_BANK_ROLE,'runtime_representation':STANDALONE_DYNAMIC_FIELD_RUNTIME_REPRESENTATION,'dynamic_roles':[{'role':'coarse_frontend','instance_index':1,'carrier_pa_basename':names['carrier_off'],'rf_differential_pa_basenames':[names['rf_differential_unit']],'rf_reference_voltage_v':1.0,'pulse_delta_pa_basename':names['pulse_delta']}]}
print(json.dumps({'compositions':jobs,'mode_states_v':states,'field_bank':bank,'response_normalization':normalization}))
'@
    $composition=Invoke-LocalFieldPython -Arguments @('-c',$composeCode,$prepared,$selection,$output,(Join-Path $generation 'standalone_mode_normalization.tsv')) -Name 'local_field_composition_plan'
    $isolation=Invoke-LocalFrontendFieldCompositions -SelectionPath $selection -Compositions $composition.compositions `
      -ComposerPath $frozenTools['compose_standalone_pa.lua'] -OutputDirectory $output -InvokeNative {
        param($Arguments,$Directory,$Name)
        Invoke-LocalFieldNative -Arguments $Arguments -Directory $Directory -Name $Name
      }
    $bank=Join-Path $output 'standalone_field_bank.json'
    Write-RunJson -Path $bank -Value $composition.field_bank -Depth 16
    $receipt=Join-Path $inputsDir 'local_frontend_field_stage_receipt.json'
    $paths=@($composition.compositions|ForEach-Object{[string]$_.output})
    $records=@($composition.compositions|ForEach-Object{
      $file=Get-Item -LiteralPath ([string]$_.output);$file.IsReadOnly=$true
      @{kind=[string]$_.kind;path=$file.FullName;bytes=$file.Length;sha256=(Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash;read_only=$true;validation='native_composition_exit_zero_from_verified_standalone_basis'}
    })
    if($null -ne $StageElapsed -and $StageElapsed.Elapsed.TotalSeconds -gt [double]$Limits.wall_clock_seconds -and $wallClockWarningNames.Add('wall_clock_seconds')){
      Write-Warning ('RESOURCE_BUDGET_WARNING=wall_clock_seconds STAGE=instrument_field_design ' +
        'MEASURED_SECONDS={0:N3} LIMIT_SECONDS={1}' -f $StageElapsed.Elapsed.TotalSeconds,$Limits.wall_clock_seconds)
    }
    Write-RunJson -Path $receipt -Depth 20 -Value @{schema_version=1;role='rf_oatof_local_frontend_field_stage';status='success';cache_key=$plan.cache_key;generation_directory=$generation;selection_path=$selection;field_bank_path=$bank;field_bank_record=@{path=$bank;bytes=(Get-Item -LiteralPath $bank).Length;sha256=(Get-FileHash -LiteralPath $bank -Algorithm SHA256).Hash};working_points=$records;cache_identity_record=@{path=$identityPath;bytes=(Get-Item -LiteralPath $identityPath).Length;sha256=(Get-FileHash -LiteralPath $identityPath -Algorithm SHA256).Hash};refine_performed=$refinePerformed;refine_policy='official_defaults';mode_count=$plan.mode_count;model_id=$plan.model_id;response_normalization=$composition.response_normalization;published_native_members_opened=$false;response_copies=$isolation.response_copies;input_isolation=$isolation;fly_performed=$false;validation_scope='native_reopen_grid_and_declared_basis_samples_only__not_field_convergence';aperture_topology_gate='required_before_fly_by_caller'}
    return [pscustomobject]@{field_paths=$paths;field_bank=$bank;cache_receipt=$receipt;cache_key=$plan.cache_key;generation_directory=$generation;selection=$selection}
  } catch {
    $stageFailure=$_
    throw
  } finally {
    $writerUnknown=($null-ne$stageFailure-and
      $stageFailure.Exception.Data.Contains('observed_process_exit_confirmed')-and
      $stageFailure.Exception.Data['observed_process_exit_confirmed']-is[bool]-and
      -not$stageFailure.Exception.Data['observed_process_exit_confirmed'])
    if(-not$writerUnknown){
      try{
        $HostLease.Value=Update-HostResourceStage -Lease $HostLease.Value -Stage prepare -Budget (Get-HostResourceBudget -Role SIMION -Stage prepare) -RetainedMemoryBytes 0
      }catch{
        if($null-eq$stageFailure){throw}
        $stageFailure.Exception.Data['local_field_stage_transition_error']=$_
        Write-Warning "Local field stage transition failed; original operation error is retained: $_" -WarningAction Continue
      }
    }
  }
}

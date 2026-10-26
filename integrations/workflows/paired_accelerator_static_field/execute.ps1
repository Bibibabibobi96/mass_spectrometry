[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$Request,
  [string]$ExecutionBudgetPath='',
  [string]$RunId='',
  [switch]$DryRun,
  [switch]$SolverAuthorized,
  [string]$ComsolSourceManifest='',
  [string]$PaProducerStoppedReceipt='',
  [string]$SimionExe='',
  [string]$Python='',
  [string]$ArtifactRoot='',
  [string]$RepoRoot=(Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)))
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$RepoRoot=(Resolve-Path -LiteralPath $RepoRoot).Path
$Request=(Resolve-Path -LiteralPath $Request).Path
if(-not$DryRun-and(-not$SolverAuthorized-or-not$ExecutionBudgetPath)){
  throw 'Native paired field execution requires SolverAuthorized and an explicit ExecutionBudgetPath.'
}
. (Join-Path $RepoRoot 'common/require_powershell7.ps1')
. (Join-Path $RepoRoot 'common/contracts/run_artifact_support.ps1')
. (Join-Path $RepoRoot 'common/host_execution_lease.ps1')
. (Join-Path $RepoRoot 'integrations/runtime/dependencies.ps1')
. (Join-Path $RepoRoot 'common/multipole/resource_budget_support.ps1')
. (Join-Path $RepoRoot 'common/simion/short_pa_path_support.ps1')
if(-not$Python){$Python=Join-Path $RepoRoot '.venv/Scripts/python.exe'}
if(-not$ArtifactRoot){$ArtifactRoot=Join-Path (Split-Path -Parent $RepoRoot) 'artifacts'}
if(-not$RunId){$RunId=(Get-Date -Format yyyyMMdd_HHmmss)+$(if($DryRun){'__test__python__paired-accelerator-static-field'}else{'__sim__cross__paired-accelerator-static-field'})}
$project='instrument_assembly';$consumer='paired_accelerator_static_field'
$reason='Paired OA-only common static BVP; retain solved fields and evidence after postprocessing failure; no numerical-equivalence qualification.'
$software=@('Python 3.11','PowerShell 7')
if(-not$DryRun){$software+=@('SIMION 2020','COMSOL 6.4','MATLAB R2025b')}
$package=$null;$capacity=$null;$lease=$null;$buildAlias=$null;$guard=$null;$terminalized=$false
$frozen=$null;$stage='initialization';$cache=$null;$reusedComsol=$false;$savedModel=$null;$comsolSourceStage=''
$protected=@();if($ComsolSourceManifest){$protected+=Split-Path -Parent (Resolve-Path -LiteralPath $ComsolSourceManifest).Path}
$header="import json,sys; from pathlib import Path; from integrations.workflows.paired_accelerator_static_field.runtime import *; "
function Invoke-PairedPython {
  param([string]$Code,[string[]]$Arguments=@())
  $executionRoot=if($null-ne$frozen){$frozen.execution_root}else{$RepoRoot}
  Invoke-RunToolRootContext -RepoRoot $executionRoot -Operation {
    $stdout=Join-Path $package.log_dir ($stage+'.python.stdout.json')
    $stderr=Join-Path $package.log_dir ($stage+'.python.stderr.log')
    &$Python -B -c ($header+$Code) @Arguments 1> $stdout 2> $stderr
    if($LASTEXITCODE-ne0){throw ("Paired field Python stage failed: "+(Get-Content -LiteralPath $stderr -Raw))}
    return Get-Content -LiteralPath $stdout -Raw|ConvertFrom-Json -AsHashtable -Depth 100
  }
}
function Invoke-PairedNative {
  param([string]$Name,[string[]]$Arguments,[string]$Directory)
  $record=Invoke-ResourceBudgetedProcess -Limits ([pscustomobject]$budget.limits) -RunDir $package.run_dir `
    -UsagePath (Join-Path $package.log_dir ($Name+'.resource_usage.json')) -FilePath $SimionExe `
    -ArgumentList $Arguments -WorkingDirectory $Directory `
    -RedirectStandardOutput (Join-Path $package.log_dir ($Name+'.stdout.log')) `
    -RedirectStandardError (Join-Path $package.log_dir ($Name+'.stderr.log'))
  if($record.resource_budget_exceeded-or$record.exit_code-ne0){throw "Native paired field stage failed: $Name"}
}
try{
  $lease=Enter-HostResourceStage -Role GATE -Stage prepare -Budget (Get-HostResourceBudget -Role GATE -Stage prepare) -RunId $RunId
  $package=New-RunPackage -Python $Python -RepoRoot $RepoRoot -ArtifactRoot (Join-Path $ArtifactRoot 'projects/instrument_assembly') `
    -RunId $RunId -Project $project -Mode $consumer -Software $software -RetentionContractEnabled -RetentionClass solver_review `
    -RetentionReason $reason -CapacityLedgerLifecycleEnabled -CapacityLedgerArtifactRoot $ArtifactRoot `
    -UseShortExecutionPath -AdditionalDirectories @('simion','comsol')
  $capacity=Enter-ArtifactWorkflowCapacitySession -Python $Python -RepoRoot $RepoRoot -ArtifactRoot $ArtifactRoot `
    -RunDirectory $package.artifact_run_dir -CommittedNewBytes 0 -Owner ('paired-static:'+$RunId) -ProtectedPaths $protected
  $stage='freeze_inputs'
  $requestPath=Copy-VerifiedRunInput -Source $Request -Destination (Join-Path $package.input_dir 'request.json')
  $author=Get-Content -LiteralPath $requestPath -Raw|ConvertFrom-Json -AsHashtable -Depth 100
  foreach($name in @('parent_manifest','frontend_geometry','oatof_resolved')){
    $source=[string]$author.source_records[$name].path
    if(-not[IO.Path]::IsPathRooted($source)){$source=Join-Path (Split-Path -Parent $Request) $source}
    $null=Copy-VerifiedRunInput -Source $source -Destination (Join-Path $package.input_dir "sources/$name.json")
  }
  $frozen=Freeze-ConsumerDependencies -RepoRoot $RepoRoot -ContractPath (Join-Path $RepoRoot 'integrations/config/runtime_dependencies.json') `
    -InputDir $package.input_dir -OwnerId $project -ConsumerId $consumer
  $config=Get-Content -LiteralPath $package.run_config -Raw|ConvertFrom-Json -AsHashtable -Depth 100
  $config.inputs.code_inventory=$frozen.code_inventory_path;$config.inputs.dependency_contract=$frozen.dependency_contract_path
  $config.parameters=@{workflow=$consumer;request_source_path=$Request;dry_run=[bool]$DryRun;solver_authorized=[bool]$SolverAuthorized}
  Write-RunJson -Path $package.run_config -Depth 100 -Value $config
  $plan=Invoke-PairedPython 'print(json.dumps(prepare_run(Path(sys.argv[1]))))' @($package.run_dir)
  Write-RunJson -Path (Join-Path $package.result_dir 'preparation_receipt.json') -Depth 100 -Value @{
    schema_version=1;role='paired_accelerator_static_field_preparation';status='success';solver_executed=$false
    plan=(Join-Path $package.input_dir 'bvp/paired_accelerator_static_field_plan.json');sample_points=$plan.sample_points.count}
  if(-not$DryRun-and$ComsolSourceManifest){
    $stage='verify_saved_comsol_source'
    $ComsolSourceManifest=(Resolve-Path -LiteralPath $ComsolSourceManifest).Path
    $null=Copy-VerifiedRunInput -Source $ComsolSourceManifest -Destination (Join-Path $package.input_dir 'comsol_source_manifest.json')
    $source=Invoke-PairedPython 'print(json.dumps(comsol_reuse(Path(sys.argv[1]),Path(sys.argv[2]))))' @($package.run_dir,$ComsolSourceManifest)
    $savedModel=[string]$source.model.path;$comsolSourceStage=[string]$source.source_stage
    $protected+=@($savedModel)
    $reusedComsol=($comsolSourceStage-eq'solved_saved')
  }
  if(-not$DryRun){
    $budgetPath=Copy-VerifiedRunInput -Source $ExecutionBudgetPath -Destination (Join-Path $package.input_dir 'execution_budget.json')
    $budget=Get-Content -LiteralPath $budgetPath -Raw|ConvertFrom-Json -AsHashtable -Depth 100
    if([long]$budget.committed_new_bytes-le0){throw 'Positive explicit committed_new_bytes required.'}
    foreach($name in @('wall_clock_seconds','transient_run_directory_bytes','process_tree_working_set_bytes','minimum_system_available_memory_bytes','compact_final_retained_bytes')){
      if([long]$budget.limits[$name]-le0){throw "Positive public process limit required: $name"}
    }
    if(-not$SimionExe){$SimionExe=Join-Path $env:ProgramFiles 'SIMION-2020/simion.exe'}
    $SimionExe=(Resolve-Path -LiteralPath $SimionExe).Path
    $cache=Invoke-PairedPython 'print(json.dumps(cache_plan(*map(Path,sys.argv[1:]))))' @($package.run_dir,$frozen.execution_root,$SimionExe,(Join-Path $ArtifactRoot 'common/simion/pa_family_cache'))
    $cachePath=Join-Path $package.input_dir 'pa_cache_plan.json';Write-RunJson -Path $cachePath -Depth 100 -Value $cache
    $update=Update-ArtifactWorkflowCapacitySession -Python $Python -RepoRoot $RepoRoot -Session $capacity `
      -RemainingCommittedNewBytes ([long]$budget.committed_new_bytes) -ProtectedCacheKeys @($cache.cache_key) -ProtectedPaths $protected
    $capacity=$update.session
    Exit-HostResourceStage -Lease $lease;$lease=$null
    $stage='simion_working_field'
    $cacheLease=@{lease_id=$capacity.lease_id;owner=$capacity.owner}
    $cacheArguments=@($package.run_dir,$cachePath,($cacheLease|ConvertTo-Json -Compress))
    if($PaProducerStoppedReceipt){$cacheArguments+=@((Resolve-Path -LiteralPath $PaProducerStoppedReceipt).Path)}
    $progress=Invoke-PairedPython 'print(json.dumps(advance_cache(Path(sys.argv[1]),read(Path(sys.argv[2])),capacity_session=json.loads(sys.argv[3]),producer_stopped_receipt=Path(sys.argv[4]) if len(sys.argv)>4 else None)))' `
      $cacheArguments
    if($progress.action_required-eq'build'){
      $scratch=[string]$progress.scratch_directory
      $buildAlias=New-RunExecutionAlias -TargetDirectory $scratch
      $short=[string]$buildAlias.execution_alias
      $build=Invoke-PairedPython 'print(json.dumps(field_build_arguments(read(Path(sys.argv[1])))))' @((Join-Path $package.input_dir 'bvp/paired_accelerator_static_field_plan.json'))
      $lease=Enter-HostResourceStage -Role SIMION -Stage prepare -Budget $budget.host_budgets.simion_prepare -RunId $RunId
      Invoke-PairedNative -Name gem2pa -Directory $short -Arguments @('--nogui','--noprompt','gem2pa',(Join-Path $package.input_dir 'bvp/paired_accelerator.gem'),(Join-Path $short 'working.pa#'))
      $lease=Update-HostResourceStage -Lease $lease -Stage pa_refine -Budget $budget.host_budgets.simion_refine -RetainedMemoryBytes 0
      Assert-HostResourceHeavyStage
      Invoke-PairedNative -Name refine_static_on -Directory $short -Arguments @('--nogui','--noprompt','lua',
        (Join-Path $frozen.execution_root 'common/simion/build_dirichlet_patch_operating_pa.lua'),
        (Join-Path $short 'working.pa#'),(Join-Path $short 'working.pa0'),'zero_neumann',$build.origin,$build.origin,$build.voltages)
      $lease=Update-HostResourceStage -Lease $lease -Stage prepare -Budget $budget.host_budgets.simion_prepare -RetainedMemoryBytes 0
      Invoke-PairedNative -Name detach_static_on -Directory $short -Arguments @('--nogui','--noprompt','lua',
        (Join-Path $frozen.execution_root 'common/simion/export_detached_standalone_pa.lua'),(Join-Path $short 'working.pa0'),(Join-Path $short 'working.pa'))
      Exit-HostResourceStage -Lease $lease;$lease=$null
      Move-Item -LiteralPath (Join-Path $short 'working.pa') -Destination (Join-Path $progress.build_directory 'paired_static_on.pa')
      Remove-RunExecutionAlias -ExecutionAlias $buildAlias.execution_alias -TargetDirectory $scratch;$buildAlias=$null
      $progress=Invoke-PairedPython 'print(json.dumps(advance_cache(Path(sys.argv[1]),read(Path(sys.argv[2])))))' @($package.run_dir,$cachePath)
    }
    if($progress.action_required-notin@('verify','complete')){throw 'Unexpected public PA transaction action.'}
    $pa=if($progress.action_required-eq'verify'){Join-Path $progress.build_directory 'paired_static_on.pa'}else{Join-Path $progress.generation_directory 'paired_static_on.pa'}
    if($progress.action_required-eq'complete'){
      $manifest=Get-Content -LiteralPath (Join-Path $progress.generation_directory 'cache_manifest.json') -Raw|ConvertFrom-Json
      $member=@($manifest.files|Where-Object name -eq 'paired_static_on.pa')[0]
      $guard=Protect-ImmutablePaSource -Source $pa -ExpectedBytes $member.bytes -ExpectedSha256 $member.sha256
    }
    $taskArguments=@($package.run_dir,$frozen.execution_root,$pa);if($savedModel){$taskArguments+=@($savedModel,$comsolSourceStage)}
    $taskCode='print(json.dumps(materialize_tasks(Path(sys.argv[1]),Path(sys.argv[2]),Path(sys.argv[3]),saved_model=Path(sys.argv[4]) if len(sys.argv)>4 else None,saved_model_stage=sys.argv[5] if len(sys.argv)>5 else "solved_saved")))'
    $tasks=Invoke-PairedPython $taskCode $taskArguments
    $lease=Enter-HostResourceStage -Role SIMION -Stage prepare -Budget $budget.host_budgets.simion_prepare -RunId $RunId
    Invoke-PairedNative -Name sample_static_on -Directory $package.run_dir -Arguments @('--nogui','--noprompt','lua',$tasks.lua)
    Exit-HostResourceStage -Lease $lease;$lease=$null
    $null=Invoke-PairedPython 'validate_samples(read(Path(sys.argv[1])),Path(sys.argv[2]));print("{}")' @((Join-Path $package.input_dir 'bvp/paired_accelerator_static_field_plan.json'),(Join-Path $package.result_dir 'simion_field_samples.csv'))
    if($progress.action_required-eq'verify'){
      $progress=Invoke-PairedPython 'print(json.dumps(advance_cache(Path(sys.argv[1]),read(Path(sys.argv[2])),Path(sys.argv[3]))))' @($package.run_dir,$cachePath,(Join-Path $package.log_dir 'simion_field_native_facts.txt'))
      if($progress.action_required-ne'complete'){throw 'Public working PA publication did not complete.'}
    }
    Write-RunJson -Path (Join-Path $package.result_dir 'simion_field_publication.json') -Depth 100 -Value $progress
    $stage='comsol_field'
    & (Join-Path $RepoRoot 'common/comsol/run_comsol_r2025b.ps1') -TaskScript $tasks.matlab `
      -ReportPath (Join-Path $package.log_dir 'comsol_bootstrap.txt') -ResourceBudgets $budget.host_budgets.comsol -RunId $RunId
    if($LASTEXITCODE-ne0){throw 'COMSOL field build/export failed; any solved/saved MPH is retained.'}
    $null=Invoke-PairedPython 'validate_samples(read(Path(sys.argv[1])),Path(sys.argv[2]));print("{}")' @((Join-Path $package.input_dir 'bvp/paired_accelerator_static_field_plan.json'),(Join-Path $package.run_dir 'comsol/comsol_field_samples.csv'))
    $stage='diagnostic_comparison'
    Invoke-RunToolRootContext -RepoRoot $frozen.execution_root -Operation {
      &$Python -B -m projects.single_reflection_oa_tof_mass_analyzer.analysis.compare_vector_field_samples `
        (Join-Path $package.run_dir 'comsol/comsol_field_samples.csv') (Join-Path $package.result_dir 'simion_field_samples.csv') --output (Join-Path $package.result_dir 'comparison')
      if($LASTEXITCODE-ne0){throw 'Static field diagnostic comparison failed.'}
    }
  }
  $stage='terminal_publication'
  if($lease){Exit-HostResourceStage -Lease $lease;$lease=$null}
  $config=Get-Content -LiteralPath $package.run_config -Raw|ConvertFrom-Json -AsHashtable -Depth 100
  foreach($file in Get-ChildItem -LiteralPath $package.input_dir -Recurse -File){$config.inputs[[IO.Path]::GetRelativePath($package.input_dir,$file.FullName)]=$file.FullName}
  Write-RunJson -Path $package.run_config -Depth 100 -Value $config
  Write-RunJson -Path $package.summary -Value @{
    schema_version=1;role='paired_accelerator_static_field_summary';status='success';dry_run=[bool]$DryRun
    native_executed=(-not$DryRun);comsol_reused_solution=$reusedComsol;comsol_source_stage=$comsolSourceStage;sample_points=$plan.sample_points.count
    qualification='preparation_only_or_static_diagnostic__no_numerical_equivalence_or_particle_qualification'}
  $null=Apply-RunArtifactRetention -Python $Python -RepoRoot $RepoRoot -RunConfig $package.run_config
  $outputs=@(Get-ChildItem $package.result_dir,$package.log_dir,(Join-Path $package.run_dir 'comsol') -Recurse -File|ForEach-Object FullName)+@($package.summary)
  Write-VerifiedRunManifest -Python $Python -RepoRoot $RepoRoot -RunConfig $package.run_config -Status success -Outputs $outputs -Software $software -DeferCapacityFinalization
  $terminalized=$true
}catch{
  $failure=$_
  if($lease){Exit-HostResourceStage -Lease $lease;$lease=$null}
  if($package-and-not$terminalized){
    $comsolOutputs=@()
    $comsolDirectory=Join-Path $package.run_dir 'comsol'
    if(Test-Path -LiteralPath $comsolDirectory -PathType Container){
      $comsolOutputs=@(Get-ChildItem -LiteralPath $comsolDirectory -Recurse -File|ForEach-Object FullName)
    }
    Complete-FailedRun -Python $Python -RepoRoot $RepoRoot -RunConfig $package.run_config -Summary $package.summary `
      -SummaryRole paired_accelerator_static_field_summary -Reason $failure.Exception.Message -FailureStage $stage `
      -Software $software -AdditionalOutputs $comsolOutputs -DeferCapacityFinalization
    $terminalized=$true
  }
  throw $failure
}finally{
  if($guard){Unprotect-ImmutablePaSource -Source $guard.path}
  if($buildAlias){Remove-RunExecutionAlias -ExecutionAlias $buildAlias.execution_alias -TargetDirectory $buildAlias.target_directory}
  if($capacity){$null=Exit-ArtifactWorkflowCapacitySession -Python $Python -RepoRoot $RepoRoot -Session $capacity}
  if($package-and$terminalized){
    &$Python -B -m common.contracts.run_capacity_lifecycle --action seal-stopped-payload --artifact-root $ArtifactRoot `
      --run-config $package.run_config --owner $project --confirm-writing-stopped --retention-reason $reason
    if($LASTEXITCODE-ne0){throw 'Paired static-field stopped-payload sealing failed; published scientific terminal retained.'}
  }
  if($package){Remove-RunPackageExecutionAlias -Package $package}
}

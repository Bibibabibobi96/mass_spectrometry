param(
  [string]$SimionExe = 'C:\Program Files\SIMION-2020\simion.exe',
  [string]$OutputDir = '',
  [string]$ArtifactProjectRoot = '',
  [string]$TemplateIob = '',
  [string]$RunId = '',
  [string]$ContractPath = '',
  [string]$CandidateBaselinePath = '',
  [string]$CandidateTextDir = '',
  [string]$ParticleSeed = '',
  [Parameter(Mandatory)][string]$CapacitySessionPath,
  [Parameter(Mandatory)][string]$ComponentPlanPath,
  [string]$ProducerHandoffPath = '',
  [Parameter(Mandatory)][string]$CompletionPath,
  [Parameter(Mandatory)][ValidatePattern('^[a-fA-F0-9]{64}$')][string]$ContextSha256,
  [Parameter(Mandatory)][ValidateSet(100,1000)][int]$ParticleCount,
  [switch]$DeferRunFinalization
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$repoRoot = (Resolve-Path (Join-Path $projectRoot '..\..')).Path
$workspaceRoot = Split-Path -Parent $repoRoot
# Candidate execution freezes this script below runs/<run_id>/inputs/code.  In
# that layout PSScriptRoot no longer identifies the workspace, so the caller
# supplies the already-frozen artifact project root.  Formal/default callers
# retain the repository-relative resolution below.
if ([string]::IsNullOrWhiteSpace($ArtifactProjectRoot)) {
  $artifactRoot = Join-Path $workspaceRoot 'artifacts\projects\single_reflection_oa_tof_mass_analyzer'
}
else {
  $artifactRoot = [IO.Path]::GetFullPath($ArtifactProjectRoot)
}
$formalBaselinePath = Join-Path $projectRoot 'config\baseline.json'
$modePath = Join-Path $projectRoot 'config\modes\formal.json'
$formalContractPath = Join-Path $projectRoot 'config\resolved_geometry.json'
. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
$nativeOperations=[Collections.Generic.List[object]]::new()
$producerComponents=[Collections.Generic.List[object]]::new()
$hostExecutionLease=$null;$hostRelease=$null;$buildFailure=$null
$expectedRunRoot=[IO.Path]::GetFullPath((Join-Path $artifactRoot ('runs/'+$RunId)))
$CompletionPath=[IO.Path]::GetFullPath($CompletionPath)
if(-not$CompletionPath.StartsWith(($expectedRunRoot+[IO.Path]::DirectorySeparatorChar),[StringComparison]::OrdinalIgnoreCase)){
  throw 'Build completion must be a record inside the managed run.'
}
if(Test-Path -LiteralPath $CompletionPath){throw 'Build completion already exists; use a fresh run.'}
try {
$candidateMode = -not [string]::IsNullOrWhiteSpace($ContractPath)
. (Join-Path $projectRoot 'oatof_lifecycle_preflight.ps1')
if (-not $candidateMode) { Assert-OaTofFormalAssetsReadable -ProjectRoot $projectRoot }
if ($candidateMode -and [string]::IsNullOrWhiteSpace($TemplateIob)) { throw 'Candidate build requires an explicit frozen non-Formal TemplateIob.' }
if ($candidateMode -and $TemplateIob -match '(?i)formal') { throw 'Candidate TemplateIob must not reference a Formal path.' }
if (-not $candidateMode -or -not $DeferRunFinalization) {
  throw 'PA construction requires the managed Candidate workflow and its existing capacity session.'
}
if ($ParticleSeed -notmatch '^-?\d+$') { throw 'ParticleSeed is required and must be an explicit integer run-instance input.' }
$particleSeedValue = [int]$ParticleSeed
if ($candidateMode) {
  $contractPath = [IO.Path]::GetFullPath($ContractPath)
  if (-not (Test-Path -LiteralPath $contractPath -PathType Leaf)) { throw "Candidate ContractPath is missing: $contractPath" }
  if ([string]::IsNullOrWhiteSpace($CandidateBaselinePath) -or [string]::IsNullOrWhiteSpace($CandidateTextDir)) {
    throw 'Candidate build requires CandidateBaselinePath and CandidateTextDir with ContractPath.'
  }
  $baselinePath = [IO.Path]::GetFullPath($CandidateBaselinePath)
  $textDir = [IO.Path]::GetFullPath($CandidateTextDir)
  if (-not (Test-Path -LiteralPath $baselinePath -PathType Leaf)) { throw "Candidate baseline is missing: $baselinePath" }
  foreach ($name in @('oatof_resolved.lua','oatof_ideal_grounded.lua','oatof_ideal_grounded.fly2')) {
    if (-not (Test-Path -LiteralPath (Join-Path $textDir $name) -PathType Leaf)) {
      throw "Candidate text input is missing: $name"
    }
  }
}
else {
  $contractPath = $formalContractPath
  $baselinePath = $formalBaselinePath
  $textDir = Join-Path $projectRoot 'simion\workbench\formal'
}

. (Join-Path $repoRoot 'common\host_execution_lease.ps1')
. (Join-Path $repoRoot 'common\simion\native_fast_adjust_runtime_support.ps1')
. (Join-Path $repoRoot 'common\resource_budget_support.ps1')
$capacitySession=Get-Content -LiteralPath $CapacitySessionPath -Raw|ConvertFrom-Json -Depth 80
$runRoot=Join-Path $artifactRoot ('runs/'+$RunId)
if($capacitySession.role-ne'artifact_workflow_capacity_session'-or$capacitySession.status-ne'active'-or
  [IO.Path]::GetFullPath($runRoot)-notin@($capacitySession.protected_paths)){
  throw 'PA construction requires the active workflow session protecting this exact run.'
}
$scope=Update-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $capacitySession
$capacitySession=$scope.session
$cacheRoot=Join-Path ([string]$capacitySession.artifact_root) 'common/simion/pa_family_cache'
$planCode=@'
import json,sys
from pathlib import Path
from projects.single_reflection_oa_tof_mass_analyzer.analysis.simion_component_pa_plan import compile_component_pa_plan
contract,plan,repo,exe=map(Path,sys.argv[1:])
actual=compile_component_pa_plan(json.loads(contract.read_text(encoding='utf-8-sig')),repository_root=repo,simion_exe=exe)
assert actual==json.loads(plan.read_text(encoding='utf-8-sig')), 'frozen component plan differs from the actual builder sources or geometry'
'@
Invoke-RunToolRootContext -RepoRoot $repoRoot -Operation {
  & $python -B -c $planCode $contractPath $ComponentPlanPath $repoRoot $SimionExe
  if($LASTEXITCODE-ne0){throw 'Frozen component PA plan validation failed.'}
}
$componentPlan=Get-Content -LiteralPath $ComponentPlanPath -Raw|ConvertFrom-Json -Depth 80
$scope=Update-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $capacitySession `
  -ProtectedCacheKeys @($componentPlan.components|Where-Object cacheable|ForEach-Object{[string]$_.cache_key})
$capacitySession=$scope.session
$producerHandoffs=@{}
if($ProducerHandoffPath){
  $handoffCode=@'
import json,sys
from pathlib import Path
from common.contracts.verify_run_manifest import verify_record
from projects.single_reflection_oa_tof_mass_analyzer.analysis.prepare_candidate_run import load_pa_producer_handoffs
path,run,plan,session=map(Path,sys.argv[1:])
record=json.loads((run/'run_config.json').read_text(encoding='utf-8-sig'))['pa_producer_handoffs']
assert Path(record['path']).resolve()==path.resolve(), 'PA handoff index differs from the run input'
verify_record('PA producer handoff index',record)
keys={row['cache_key'] for row in json.loads(plan.read_text(encoding='utf-8-sig'))['components'] if row['cacheable']}
print(json.dumps(load_pa_producer_handoffs(path,run,expected_cache_keys=keys,capacity_session=json.loads(session.read_text(encoding='utf-8-sig')))))
'@
  $handoffText=@(Invoke-RunToolRootContext -RepoRoot $repoRoot -Operation {
    & $python -B -c $handoffCode $ProducerHandoffPath $runRoot $ComponentPlanPath $CapacitySessionPath
    if($LASTEXITCODE-ne0){throw 'Frozen producer handoff inputs failed validation.'}
  })
  $producerHandoffs=($handoffText-join"`n")|ConvertFrom-Json -AsHashtable -Depth 80
}
$hostExecutionLease = Enter-HostExecutionLease -Role SIMION -Stage prepare -RunId $RunId
$outputAlias=$null
$script:codeExecutionAlias=$null
try {
if ([string]::IsNullOrWhiteSpace($OutputDir)) {
  if ([string]::IsNullOrWhiteSpace($RunId)) {
    $RunId = (Get-Date -Format 'yyyyMMdd_HHmmss') + '__build__simion__formal-delivery__n1000'
  }
  $OutputDir = Join-Path $artifactRoot "runs\$RunId\simion"
}
$outputFull = [IO.Path]::GetFullPath($OutputDir)
$runsRoot = [IO.Path]::GetFullPath((Join-Path $artifactRoot 'runs'))
if (-not $outputFull.StartsWith(([IO.Path]::GetFullPath($runRoot)+[IO.Path]::DirectorySeparatorChar), [StringComparison]::OrdinalIgnoreCase)) {
  throw 'OutputDir must remain under runs; promotion to formal is a separate gate.'
}
if (Test-Path -LiteralPath $outputFull) {
  $existing = @(Get-ChildItem -LiteralPath $outputFull -Force)
  if ($existing.Count -ne 0) {
    throw "Output directory already exists or is not empty; no automatic overwrite is allowed: $outputFull"
  }
}
else {
  New-Item -ItemType Directory -Path $outputFull | Out-Null
}

$outputAlias=New-RunExecutionAlias -TargetDirectory $outputFull `
  -ExecutionRoot (Join-Path ([string]$capacitySession.artifact_root) 'common/execution_aliases')
$runtimeOutput=[string]$outputAlias.execution_alias
$buildLogs=Join-Path $outputFull 'build_logs'
New-Item -ItemType Directory -Path $buildLogs|Out-Null
$nativeSequence=0
$script:allOperationsStopped=$true
$contract = Get-Content -LiteralPath $contractPath -Raw -Encoding UTF8 | ConvertFrom-Json
$geometry = $contract.geometry_mm
$accelerator = $contract.geometry_derivation.accelerator
$build = $contract.simion_geometry_build
$detector = $contract.simion_detector_marker
$source = $contract.particle_source
$voltage = $contract.electrodes_V

function Invoke-OwnedSimionArguments {
  param([string[]]$ArgumentList,[string]$OperationId)
  $observationPath=Join-Path $buildLogs ($OperationId+'.native.json')
  $request=@{command=@($SimionExe)+@($ArgumentList);cwd=$outputFull;
    stdout=(Join-Path $buildLogs ($OperationId+'.stdout.log'));stderr=(Join-Path $buildLogs ($OperationId+'.stderr.log'));
    observation=$observationPath}
  $code=@'
from common.host_resource_python import await_managed_process_start
await_managed_process_start()
import json,sys,time
from pathlib import Path
from common.simion.process_observation import run_observed_process
from common.contracts.recorded_file_removal import write_json_atomic
r=json.loads(sys.argv[1]);d={'exit_confirmed':False,'returncode':None};started=time.perf_counter();exit_code=1
try:
    p,peak=run_observed_process(r['command'],cwd=Path(r['cwd']),stdout=Path(r['stdout']),stderr=Path(r['stderr']),warning_seconds=1800)
    d.update(exit_confirmed=True,returncode=p.returncode,native_peak_working_set_bytes=peak);exit_code=0 if p.returncode==0 else 1
except BaseException as error:
    d.update(exit_confirmed=getattr(error,'observed_process_exit_confirmed',False),returncode=getattr(error,'observed_process_returncode',None),error=f'{type(error).__name__}: {error}')
finally:
    d['native_elapsed_seconds']=time.perf_counter()-started;write_json_atomic(Path(r['observation']),d)
raise SystemExit(exit_code)
'@
  $observed=@{observation=@{exit_confirmed=$false;returncode=$null};managed_process_completion=$null}
  $script:allOperationsStopped=$false
  try{
    $observed.managed_process_completion=Invoke-RepositoryManagedPythonProcess -Python $python `
      -ArgumentList @('-B','-c',$code,($request|ConvertTo-Json -Depth 8 -Compress)) -WorkingDirectory $repoRoot `
      -StandardOutputPath (Join-Path $buildLogs ($OperationId+'.helper.stdout.log')) `
      -StandardErrorPath (Join-Path $buildLogs ($OperationId+'.helper.stderr.log'))
    $receipt=$observed.managed_process_completion
    $script:allOperationsStopped=$receipt.ownership_confirmed-and$receipt.worker_exit_confirmed-and
      $receipt.launcher_exit_confirmed-and$receipt.stdout_drained-and$receipt.stderr_drained
    if(Test-Path -LiteralPath $observationPath){$observed.observation=Get-Content -LiteralPath $observationPath -Raw|ConvertFrom-Json -AsHashtable}
    $script:allOperationsStopped=$script:allOperationsStopped-and$observed.observation.exit_confirmed
    if(-not$script:allOperationsStopped-or$receipt.exit_code-ne0-or$observed.observation.returncode-ne0){
      $detail=$(if($observed.observation.Contains('error')){$observed.observation.error}else{''})
      throw "Native component operation failed: $OperationId (worker=$($receipt.exit_code), native=$($observed.observation.returncode)): $detail"
    }
    return $observed
  }catch{
    $originalError=$_
    if($_.Exception.Data.Contains('managed_python_completion')){
      $observed.managed_process_completion=$_.Exception.Data['managed_python_completion']
      $receipt=$observed.managed_process_completion
      $script:allOperationsStopped=$receipt.ownership_confirmed-and$receipt.worker_exit_confirmed-and
        $receipt.launcher_exit_confirmed-and$receipt.stdout_drained-and$receipt.stderr_drained
    }
    if(Test-Path -LiteralPath $observationPath){
      try{$observed.observation=Get-Content -LiteralPath $observationPath -Raw|ConvertFrom-Json -AsHashtable}catch{}
    }
    $script:allOperationsStopped=$script:allOperationsStopped-and$observed.observation.exit_confirmed
    $originalError.Exception.Data['native_operation_observation']=$observed
    throw $originalError
  }
}

function Invoke-SimionLua([string]$Script, [object[]]$Arguments, [switch]$Refines) {
  if ($Refines) {
    $hostExecutionLease = Update-HostResourceStage -Lease $hostExecutionLease -Stage pa_refine `
      -Budget (Get-HostResourceBudget -Role SIMION -Stage pa_refine) -RetainedMemoryBytes 0
  }
  # A parameterized rebuild may intentionally change PA dimensions relative
  # to the seed IOB.  In --nogui mode SIMION otherwise waits indefinitely at
  # the interactive "Continue loading anyway?" prompt.  --noprompt accepts
  # the default continuation; the runtime contract still verifies every PA
  # filename, dimension, grid, transform, and priority after the save.
  $script:nativeSequence++
  $name=('{0:D3}_{1}'-f$script:nativeSequence,[IO.Path]::GetFileNameWithoutExtension($Script))
  $operation=@{operation_id=$name;observation=@{exit_confirmed=$false;returncode=$null}}
  $nativeOperations.Add($operation)
  try{
    $argumentsText=@($Arguments|ForEach-Object{if($_-is[IFormattable]){$_.ToString($null,[Globalization.CultureInfo]::InvariantCulture)}else{[string]$_}})
    $nativeScript=$Script
    # The Lua opener retains MAX_PATH; only the explicit frozen code root is
    # transported. Persistent field/IOB identities are not changed or copied.
    if([IO.Path]::GetFullPath($Script).Length-ge260){
      $relative=[IO.Path]::GetRelativePath($repoRoot,[IO.Path]::GetFullPath($Script))
      if([IO.Path]::IsPathFullyQualified($relative)-or$relative-eq'..'-or
         $relative.StartsWith('..'+[IO.Path]::DirectorySeparatorChar)){
        throw 'Native Lua script is outside its frozen repository root.'
      }
      if($null-eq$script:codeExecutionAlias){
        $runConfig=Get-Content -LiteralPath (Join-Path $expectedRunRoot 'run_config.json') -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
        if(-not$runConfig.Contains('paths')-or$runConfig.paths-isnot[Collections.IDictionary]-or
           -not$runConfig.paths.Contains('execution_root')-or$runConfig.paths.execution_root-isnot[string]-or
           -not[IO.Path]::IsPathFullyQualified($runConfig.paths.execution_root)){
          throw 'Frozen run paths.execution_root is required for Lua transport.'
        }
        $script:codeExecutionAlias=New-RunExecutionAlias -TargetDirectory $repoRoot `
          -ExecutionRoot $runConfig.paths.execution_root -ExpectedExecutionRelativePaths @($relative)
      }
      $nativeScript=Join-Path $script:codeExecutionAlias.execution_alias $relative
      $null=Assert-RunPackagePathCapacity -Report (Get-RunPackagePathCapacity `
        -RunDirectory $script:codeExecutionAlias.execution_alias -ExpectedExecutionRelativePaths @($relative))
    }
    $observed=Invoke-OwnedSimionArguments -ArgumentList (@('--nogui','--noprompt','lua',$nativeScript)+$argumentsText) -OperationId $name
    $operation.observation=$observed.observation;$operation.managed_process_completion=$observed.managed_process_completion
  }catch{
    if($_.Exception.Data.Contains('native_operation_observation')){
      $observed=$_.Exception.Data['native_operation_observation'];$operation.observation=$observed.observation
      $operation.managed_process_completion=$observed.managed_process_completion
    }
    throw
  }
  if ($Refines) {
    $hostExecutionLease = Update-HostResourceStage -Lease $hostExecutionLease -Stage prepare `
      -Budget (Get-HostResourceBudget -Role SIMION -Stage prepare) -RetainedMemoryBytes 0
  }
}

function Assert-GeneratedReflectronSet([string]$Directory,[int]$MaxElectrode) {
  $base = Join-Path $Directory 'reflectron.pa#'
  if (-not (Test-Path -LiteralPath $base -PathType Leaf)) {
    throw 'Generated reflectron.pa# is missing.'
  }
  $basisBytes = (Get-Item -LiteralPath $base).Length
  foreach ($electrode in 1..$MaxElectrode) {
    $path = Join-Path $Directory "reflectron.pa$electrode"
    if (-not (Test-Path -LiteralPath $path -PathType Leaf) -or
        (Get-Item -LiteralPath $path).Length -ne $basisBytes) {
      throw "Generated reflectron pa$electrode is missing or incomplete."
    }
  }
  if (-not (Test-Path -LiteralPath (Join-Path $Directory 'reflectron.pa0') -PathType Leaf)) {
    throw 'Generated reflectron.pa0 is missing.'
  }
}

function Invoke-SegmentedReflectronRefine([string]$Directory,[int]$MaxElectrode) {
  $hostExecutionLease = Update-HostResourceStage -Lease $hostExecutionLease -Stage pa_refine `
    -Budget (Get-HostResourceBudget -Role SIMION -Stage pa_refine) -RetainedMemoryBytes 0
  $singleRefiner = Join-Path $projectRoot 'simion\reflectron\refine_single_pa.lua'
  foreach ($electrode in 0..$MaxElectrode) {
    Invoke-SimionLua $singleRefiner @(
      (Join-Path $Directory "reflectron.pa$electrode")
    )
  }
  $hostExecutionLease = Update-HostResourceStage -Lease $hostExecutionLease -Stage prepare `
    -Budget (Get-HostResourceBudget -Role SIMION -Stage prepare) -RetainedMemoryBytes 0
}

function Build-OwnedComponent([string]$Role,[string]$Directory) {
if($Role-eq'accelerator'){
  $acceleratorStem=Join-Path $Directory 'accelerator.pa#'
  Invoke-SimionLua -Refines (Join-Path $repoRoot 'projects\orthogonal_accelerator\simion\build_two_zone_pa.lua') @(
  (Join-Path $repoRoot 'projects\orthogonal_accelerator\simion\two_zone_accelerator.gem'), $acceleratorStem,
  $build.accelerator.cell_xy_mm, $build.accelerator.cell_z_mm,
  $geometry.accelerator_bore_half, $geometry.accelerator_ring_width,
  $geometry.accelerator_insulation_gap, $geometry.accelerator_rear_clearance,
  $geometry.accelerator_shield_wall, $build.accelerator.vacuum_margin_mm,
  $build.accelerator.max_gib, $build.accelerator.back_domain_margin_mm,
  $build.accelerator.front_domain_margin_mm, $build.accelerator.grid_phase_z_mm,
  $accelerator.d1_mm, $accelerator.d2_mm, $contract.rings.accelerator_count,
  $geometry.accelerator_repeller_thickness, $geometry.accelerator_ring_thickness,
  $geometry.accelerator_front_vacuum_margin, $voltage.repeller, $voltage.grid1,
  0, 0, 0, 0 # This instrument workflow builds the declared closed shield; no side-port dimensions.
  )
}
elseif($Role-eq'reflectron'){
$reflectronStem = Join-Path $Directory 'reflectron.pa#'
$maxReflectronElectrode = 4 + [int]$contract.rings.stage1_count + [int]$contract.rings.stage2_count
  Invoke-SimionLua -Refines (Join-Path $projectRoot 'simion\reflectron\build_reflectron_variant.lua') @(
  (Join-Path $projectRoot 'simion\reflectron\oatof_reflectron_ideal_10_5.gem'), $reflectronStem,
  (Join-Path $textDir 'oatof_resolved.lua'),
  'initialize-only'
  )
  Assert-GeneratedReflectronSet $Directory $maxReflectronElectrode
  Invoke-SegmentedReflectronRefine $Directory $maxReflectronElectrode
}
elseif($Role-eq'flight_tube'){
  $flightTubeStem = Join-Path $Directory 'flight_tube_ground.pa#'
  Invoke-SimionLua -Refines (Join-Path $projectRoot 'simion\workbench\build_flight_tube_variant.lua') @(
  (Join-Path $projectRoot 'simion\workbench\oatof_flight_tube_ground.gem'), $flightTubeStem,
  (Join-Path $textDir 'oatof_resolved.lua')
  )
}
elseif($Role-eq'detector'){
  $detectorStem = Join-Path $Directory 'detector_ground.pa#'
  Invoke-SimionLua -Refines (Join-Path $projectRoot 'simion\workbench\build_detector_variant.lua') @(
  (Join-Path $projectRoot 'simion\workbench\oatof_detector_ground.gem'), $detectorStem,
  (Join-Path $textDir 'oatof_resolved.lua')
  )
}
else{throw "Unknown component role: $Role"}
}

function Invoke-ComponentCache([string[]]$Arguments,[string]$Name) {
  $stdout=Join-Path $buildLogs ($Name+'.json')
  $stderr=Join-Path $buildLogs ($Name+'.stderr.log')
  $operation=@{operation_id=('cache_'+$Name);operation_kind='python_metadata';
    observation=@{exit_confirmed=$false;returncode=$null};managed_process_completion=$null}
  $nativeOperations.Add($operation)
  $code='from common.host_resource_python import await_managed_process_start; await_managed_process_start(); import runpy; runpy.run_module("common.simion.pa_family_cache",run_name="__main__")'
  $script:allOperationsStopped=$false
  try{
    $operation.managed_process_completion=Invoke-RepositoryManagedPythonProcess -Python $python `
      -ArgumentList (@('-B','-c',$code)+$Arguments) -WorkingDirectory $repoRoot `
      -StandardOutputPath $stdout -StandardErrorPath $stderr
  }catch{
    if($_.Exception.Data.Contains('managed_python_completion')){
      $operation.managed_process_completion=$_.Exception.Data['managed_python_completion']
    }
    throw
  }finally{
    $receipt=$operation.managed_process_completion
    if($null-ne$receipt){
      $script:allOperationsStopped=$receipt.ownership_confirmed-and$receipt.worker_exit_confirmed-and
        $receipt.launcher_exit_confirmed-and$receipt.stdout_drained-and$receipt.stderr_drained
      $operation.observation=@{exit_confirmed=[bool]$script:allOperationsStopped;returncode=$receipt.exit_code}
    }
  }
  if(-not$script:allOperationsStopped-or$receipt.exit_code-ne0){throw "Component cache operation failed: $Name (worker=$($receipt.exit_code); see $stderr)"}
  return Get-Content -LiteralPath $stdout -Raw|ConvertFrom-Json -Depth 80
}

$componentReceipts=@()
foreach($component in $componentPlan.components){
  $watch=[Diagnostics.Stopwatch]::StartNew()
  $role=[string]$component.role;$stem=[string]$component.stem
  if(-not$component.cacheable){
    Build-OwnedComponent $role $runtimeOutput
    $componentReceipts+=@{role=$role;source='fresh_frozen_fractional_gem';cache_hit=$false;
      controller_path=(Join-Path $outputFull ($stem+'.pa0'));wall_seconds=$watch.Elapsed.TotalSeconds}
    continue
  }
  $identityPath=Join-Path $buildLogs ($role+'_identity.json')
  Write-RunJson -Path $identityPath -Value $component.identity -Depth 80
  $cacheArgs=@('--cache-root',$cacheRoot,'--identity',$identityPath,'--filenames',($component.expected_files-join','))
  $producerComponent=@{cache_key=[string]$component.cache_key;role=$role;response_ids=@($component.response_ids);
    response_build_operation_ids=@()}
  $producerComponents.Add($producerComponent)
  $handoff=$producerHandoffs[[string]$component.cache_key]
  if($null-ne$handoff-and$handoff.response_build_complete){
    $producerComponent.response_build_completion=$handoff.response_build_completion
  }
  $private=$null
  $privateArguments=@{
    ExpectedCacheKey=[string]$component.cache_key;ReceiptName=($stem+'.standalone_responses.json');RawName=($stem+'.pa#');
    FamilyPrefix=$stem;ExpectedResponseIds=@($component.response_ids|ForEach-Object{[int]$_});
    DestinationDirectory=$runtimeOutput;RequireEmptyFamilyNamespace=$true;Python=$python;RepoRoot=$repoRoot;
    SimionExe=$SimionExe;ResourceLease=$hostExecutionLease;RunId=$RunId;NativeOperationObservations=$nativeOperations;
    InvokeNativeOperation={param($ArgumentList,$OperationId) Invoke-OwnedSimionArguments -ArgumentList $ArgumentList -OperationId $OperationId}
  }
  $probe=Invoke-ComponentCache ($cacheArgs+@('--action','probe')) ($role+'_probe')
  $cacheHit=$probe.disposition-eq'hit'
  if($null-ne$handoff-and$cacheHit){throw 'Producer handoff cannot replace a published component; select ordinary published reuse.'}
  if(-not$cacheHit){
    if($probe.disposition-ne'miss'){throw "Component cache cannot be reused: $role $($probe.disposition)"}
    $recipePath=Join-Path $buildLogs ($role+'_response_recipe.json')
    $receiptName=$stem+'.standalone_responses.json'
    Write-RunJson -Path $recipePath -Depth 12 -Value @{
      schema_version=2;receipt_name=$receiptName;
      exporter_path=(Join-Path $repoRoot 'common/simion/export_standalone_pa.lua');source_location='build_scratch';
      exports=@($component.response_ids|ForEach-Object{@{response_id=[int]$_;source_name=($stem+'.pa'+$_);standalone_name=($stem+'.response'+$_+'.pa')}})
    }
    $transactionArgs=$cacheArgs+@('--action','advance-transaction','--owner',$RunId,
      '--producer-run-config',(Join-Path $runRoot 'run_config.json'))
    if($null-ne$handoff){
      if($handoff.has_sealed_inventory-and-not$handoff.response_build_complete){
        throw "Sealed component $role lacks manifest-bound completed response-build evidence. Preserve $cacheRoot/.transactions/$($component.cache_key)/transaction.json; disposition requires the existing advance-transaction --cancel-unpublished-transaction contract with explicit cancellation and no active consumers."
      }
      $transaction=Invoke-ComponentCache ($transactionArgs+@('--producer-handoff',[string]$handoff.request_path)) ($role+'_handoff')
    }else{
      $transaction=Invoke-ComponentCache ($transactionArgs+@('--response-receipt',$recipePath)) ($role+'_begin')
    }
    if($null-eq$handoff-and$transaction.action_required-ne'build'){
      throw 'An unfinished PA transaction requires its explicit public producer handoff; file presence cannot authorize resumption.'
    }
    $scratch=[string]$transaction.scratch_directory;$payload=[string]$transaction.build_directory
    $scratchAlias=$null
    try{
      $verifier=Join-Path $PSScriptRoot 'verify_component_pa.lua'
      $verificationOutput=$null
      $reuseScratch=$false
      if($null-ne$handoff-and$handoff.response_build_complete-and-not$transaction.inventory_sha256){
        $nativeNames=@(0..$component.response_ids.Count|ForEach-Object{$stem+'.pa'+$_})
        $payloadNames=@($component.expected_files|Where-Object{$_-ne$receiptName})
        $reuseScratch=@($nativeNames|Where-Object{-not(Test-Path -LiteralPath (Join-Path $scratch $_) -PathType Leaf)}).Count-eq0-and
          @($payloadNames|Where-Object{-not(Test-Path -LiteralPath (Join-Path $scratch $_) -PathType Leaf)-and
            -not(Test-Path -LiteralPath (Join-Path $payload $_) -PathType Leaf)}).Count-eq0
        if($reuseScratch){
          # A stopped move may have landed some unsealed members already.
          # Restore the same owned unit for its original full-field verifier.
          foreach($name in $payloadNames){
            if(-not(Test-Path -LiteralPath (Join-Path $scratch $name))){
              Move-Item -LiteralPath (Join-Path $payload $name) -Destination (Join-Path $scratch $name)
            }
          }
        }
      }
      $rebuild=-not$reuseScratch-and($transaction.action_required-eq'build'-or($null-ne$handoff-and-not$handoff.response_build_complete))
      if($rebuild-or$reuseScratch){
        # Only an unsealed, exclusively handed-off producer scratch is reset.
        # The public inventory is never cleared or made writable here.
        if($transaction.inventory_sha256){throw 'A sealed transaction cannot be rebuilt by the component builder.'}
        if($rebuild){
          $producerComponent.Remove('response_build_completion')
          $scratchNames=@($stem+'.pa#',$stem+'.pa+',$stem+'.pa_')+@(0..$component.response_ids.Count|ForEach-Object{$stem+'.pa'+$_})+
            @($component.response_ids|ForEach-Object{$stem+'.response'+$_+'.pa'})
          foreach($name in $scratchNames){
            $path=Join-Path $scratch $name
            if(Test-Path -LiteralPath $path){Remove-Item -LiteralPath $path -Force}
          }
        }
        $scratchAlias=New-RunExecutionAlias -TargetDirectory $scratch `
          -ExecutionRoot (Join-Path ([string]$capacitySession.artifact_root) 'common/execution_aliases')
        $nativeScratch=[string]$scratchAlias.execution_alias
        if($rebuild){
          $responseOperationStart=$nativeOperations.Count
          Build-OwnedComponent $role $nativeScratch
          foreach($id in $component.response_ids){
            Invoke-SimionLua (Join-Path $repoRoot 'common/simion/export_standalone_pa.lua') @(
              (Join-Path $nativeScratch ($stem+'.pa'+$id)),(Join-Path $nativeScratch ($stem+'.response'+$id+'.pa')))
          }
          $producerComponent.response_build_operation_ids=@($nativeOperations.ToArray()|Select-Object -Skip $responseOperationStart|ForEach-Object{$_.operation_id})
        }
        Invoke-SimionLua $verifier (@((Join-Path $nativeScratch $stem),$nativeScratch,$component.response_ids.Count)+
          @($component.grid.dimensions)+@($component.grid.cell_mm)+@([string]$component.grid.symmetry_type))
        $verificationOutput=Join-Path $buildLogs ('{0:D3}_verify_component_pa.stdout.log'-f$script:nativeSequence)
        foreach($name in $component.expected_files){
          if($name-eq$receiptName){continue}
          Move-Item -LiteralPath (Join-Path $scratch $name) -Destination (Join-Path $payload $name) -Force
        }
        Remove-RunExecutionAlias -ExecutionAlias $scratchAlias.execution_alias -TargetDirectory $scratch
        $scratchAlias=$null
      }
      $transaction=Invoke-ComponentCache $transactionArgs ($role+'_seal')
      if($transaction.action_required-ne'complete'){
        if($transaction.action_required-ne'verify'){throw 'Component transaction did not reach verification.'}
        if($null-eq$verificationOutput){
          $private=New-NativeFastAdjustRuntimeFamily @privateArguments `
            -TransactionPath (Join-Path $transaction.transaction_directory 'transaction.json') `
            -ExpectedInventorySha256 ([string]$transaction.inventory_sha256) -ExpectedOwner $RunId `
            -ProducerRunConfig (Join-Path $runRoot 'run_config.json') -CapacitySessionPath $CapacitySessionPath `
            -GetResponseVerificationArguments {
              param($FamilyStem,$StandalonePath,$ResponseId)
              return @('--nogui','--noprompt','lua',$verifier,$FamilyStem,$runtimeOutput,[string]$component.response_ids.Count)+
                @($component.grid.dimensions|ForEach-Object{[string]$_})+@($component.grid.cell_mm|ForEach-Object{[string]$_})+
                @([string]$component.grid.symmetry_type,[string]$ResponseId,$StandalonePath)
            }
          $hostExecutionLease=$private.resource_lease
          $verificationOutput=Join-Path $buildLogs ($role+'_handoff_verification.log')
          $verifiedText=@($component.response_ids|ForEach-Object{
            [IO.File]::ReadAllText((Join-Path $buildLogs ($stem+'.verify.response.'+$_+'.stdout.log')))
          })-join"`n"
          [IO.File]::WriteAllText($verificationOutput,$verifiedText,[Text.UTF8Encoding]::new($false))
        }
        $evidence=Join-Path $buildLogs ($role+'_verification.json')
        Write-RunJson -Path $evidence -Depth 8 -Value @{
          schema_version=1;role='simion_pa_family_verification';status='pass';cache_key=$component.cache_key;
          inventory_sha256=$transaction.inventory_sha256;solver_release='SIMION 2020';verifier_path=$verifier;
          verifier_sha256=(Get-FileHash -LiteralPath $verifier -Algorithm SHA256).Hash;
          verification_output_path=$verificationOutput;verification_output_sha256=(Get-FileHash -LiteralPath $verificationOutput -Algorithm SHA256).Hash
        }
        $transaction=Invoke-ComponentCache ($transactionArgs+@('--verification-evidence',$evidence)) ($role+'_publish')
      }
      if($transaction.action_required-ne'complete'){throw 'Component transaction did not publish.'}
      $probe=$transaction
    }catch{
      $componentFailure=$_
      if($script:allOperationsStopped){
        try{$null=Invoke-ComponentCache ($transactionArgs+@('--record-stage-only')) ($role+'_failed_inventory')}
        catch{Write-Warning "Component accounting failed after the original error: $_"}
      }
      throw $componentFailure
    }finally{
      if($null-ne$scratchAlias-and$script:allOperationsStopped){Remove-RunExecutionAlias -ExecutionAlias $scratchAlias.execution_alias -TargetDirectory $scratch}
    }
  }
  if($null-eq$private){
    $privateArguments.ResourceLease=$hostExecutionLease
    $private=New-NativeFastAdjustRuntimeFamily @privateArguments -GenerationDirectory ([string]$probe.generation_directory) `
      -ExpectedGenerationSha256 ([string]$probe.generation_sha256)
  }else{
    $private.receipt.generation_directory=[string]$probe.generation_directory
    $private.receipt.generation_sha256=[string]$probe.generation_sha256
  }
  $hostExecutionLease=$private.resource_lease
  # Apply the existing provider's ordered voltage projection to the fresh
  # private controller. The immutable cache contains unit responses only.
  $adjusted=Join-Path (Split-Path -Parent $private.controller_path) 'operating.pa0'
  $assignments=@($component.response_ids|ForEach-Object{
    $value=[double]$component.operating_voltages_v.([string]$_)
    ([string]$_+'='+$value.ToString('G17',[Globalization.CultureInfo]::InvariantCulture))
  })
  Invoke-SimionLua (Join-Path $repoRoot 'common/simion/voltageize_pa0.lua') (@($private.controller_path,$adjusted)+$assignments)
  Move-Item -LiteralPath $adjusted -Destination $private.controller_path -Force
  $private.receipt.controller_path=Join-Path $outputFull ($stem+'.pa0')
  $componentReceipts+=@{role=$role;source='published_standalone_responses';cache_hit=$cacheHit;
    controller_path=$private.receipt.controller_path;asset=$private.receipt;wall_seconds=$watch.Elapsed.TotalSeconds}
  $scope=Update-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $capacitySession
  $capacitySession=$scope.session
}

$ionGenerator = Join-Path $PSScriptRoot 'generate_comsol_consistent_ions.ps1'
  foreach ($particleCount in @($ParticleCount)) {
    $ionPath = Join-Path $outputFull "oatof_comsol_524amu_gaussian_N$particleCount.ion"
    & $ionGenerator -N $particleCount -MassAmu $contract.validation_target.mass_amu -Charge 1 `
      -EnergyMeanEv $contract.validation_target.initial_energy_mean_ev `
      -EnergyStdEv $contract.validation_target.initial_energy_sigma_ev `
      -HalfWidthXmm ($source.size_x_mm/2) -HalfWidthYmm ($source.size_y_mm/2) `
      -HalfWidthZmm ($source.size_z_mm/2) -CenterXmm $source.center_x_mm `
      -CenterYmm $source.center_y_mm -CenterZmm $source.center_z_mm `
      -Seed $particleSeedValue -Output $ionPath | Out-Null
  }

Copy-Item -LiteralPath (Join-Path $projectRoot 'docs\SIMION_DELIVERY_CHECKLIST.md') `
  -Destination (Join-Path $outputFull 'SIMION_DELIVERY_CHECKLIST.md')
Copy-Item -LiteralPath $baselinePath -Destination (Join-Path $outputFull 'baseline.json')
if (-not $candidateMode) {
  Copy-Item -LiteralPath $modePath -Destination (Join-Path $outputFull 'formal_mode.json')
}
Copy-Item -LiteralPath $contractPath -Destination (Join-Path $outputFull 'resolved_geometry.json')
$resolvedLua = Join-Path $textDir 'oatof_resolved.lua'
Copy-Item -LiteralPath $resolvedLua -Destination (Join-Path $outputFull 'oatof_resolved.lua')

& $python (Join-Path $repoRoot 'common\contracts\artifact_naming.py') run $RunId
if ($LASTEXITCODE -ne 0) { throw "Invalid run_id: $RunId" }

$template = $TemplateIob
if ([string]::IsNullOrWhiteSpace($template)) {
  $template = Join-Path $artifactRoot 'formal\simion\oatof_ideal_grounded.iob'
}
if (-not (Test-Path -LiteralPath $template -PathType Leaf)) {
  throw "Four-instance template IOB is unavailable: $template"
}
$template = (Resolve-Path -LiteralPath $template).Path
$templateCon = [IO.Path]::ChangeExtension($template, '.con')
if (-not (Test-Path -LiteralPath $templateCon -PathType Leaf)) {
  throw "Four-instance template GUI configuration is unavailable: $templateCon"
}
$iobOutput = Join-Path $outputFull 'oatof_ideal_grounded.iob'
# Seed the final IOB/CON themselves from the GUI layout template.  Opening the
# copy beside the new PA files makes relative references resolve locally; the
# Lua builder then rewrites all four instances and saves back to the same IOB.
# This avoids disposable _layout_template sidecars and makes the build
# deletion-free.
Copy-Item -LiteralPath $template -Destination $iobOutput
Copy-Item -LiteralPath $templateCon -Destination ([IO.Path]::ChangeExtension($iobOutput, '.con'))
Invoke-SimionLua (Join-Path $PSScriptRoot 'build_formal_iob.lua') @(
  (Join-Path $runtimeOutput 'oatof_resolved.lua'), (Join-Path $runtimeOutput 'oatof_ideal_grounded.iob'), (Join-Path $runtimeOutput 'oatof_ideal_grounded.iob'),
  (Join-Path $textDir 'oatof_ideal_grounded.lua'),
  (Join-Path $textDir 'oatof_ideal_grounded.fly2'),
  (Join-Path $runtimeOutput 'reflectron.pa0'),
  (Join-Path $runtimeOutput 'accelerator.pa0')
)
Remove-RunExecutionAlias -ExecutionAlias $outputAlias.execution_alias -TargetDirectory $outputFull
$outputAlias=$null
# Independent canonical reload proves the persisted workbench has no alias
# dependency before its immutable inventory is accepted for a later Fly.
$savedEnvironment=Save-RunEnvironment -Names @('OATOF_SIMION_IOB_PATH','OATOF_SIMION_IOB_REPORT',
  'OATOF_SIMION_EXPECTED_QUALITY','OATOF_SIMION_EXPECTED_INSTANCES','OATOF_SIMION_PROGRAM_LOAD_REPORT','OATOF_SIMION_TEMPLATE_STRUCTURE_ONLY')
try{
  $env:OATOF_SIMION_IOB_PATH=$iobOutput
  $env:OATOF_SIMION_IOB_REPORT=Join-Path $buildLogs 'canonical_iob_verification.txt'
  $env:OATOF_SIMION_EXPECTED_QUALITY=[string]$contract.simion_runtime.trajectory_quality
  $env:OATOF_SIMION_EXPECTED_INSTANCES='4'
  $env:OATOF_SIMION_PROGRAM_LOAD_REPORT=Join-Path $buildLogs 'canonical_program_load.txt'
  $env:OATOF_SIMION_TEMPLATE_STRUCTURE_ONLY='0'
  Invoke-SimionLua (Join-Path $PSScriptRoot 'verify_iob_runtime_contract.lua') @()
  if(-not(Select-String -LiteralPath $env:OATOF_SIMION_IOB_REPORT -Pattern '^STATUS=PASS$' -Quiet)){
    throw 'Canonical workbench reload did not verify.'
  }
}finally{Restore-RunEnvironment -Names @($savedEnvironment.Keys) -Snapshot $savedEnvironment}

foreach ($required in @('oatof_ideal_grounded.iob','oatof_ideal_grounded.con','oatof_ideal_grounded.lua','oatof_ideal_grounded.fly2')) {
  if (-not (Test-Path -LiteralPath (Join-Path $outputFull $required) -PathType Leaf)) {
    throw "Delivery is missing $required"
  }
}
$hostExecutionLease = Update-HostResourceStage -Lease $hostExecutionLease -Stage postprocess `
  -Budget (Get-HostResourceBudget -Role SIMION -Stage postprocess) -RetainedMemoryBytes 0
$runtimeFiles=@(Get-ChildItem -LiteralPath $outputFull -Recurse -File|Where-Object{
  $_.Name-match'\.pa(?:\d+|#|-surf)?$'
}|Sort-Object FullName|ForEach-Object{@{path=$_.FullName;bytes=$_.Length;sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash}})
$runtimeReceipt=Join-Path $outputFull 'simion_runtime_receipt.json'
Write-RunJson -Path $runtimeReceipt -Depth 80 -Value @{
  schema_version=1;role='oatof_simion_private_runtime';status='verified';run_id=$RunId;context_sha256=$ContextSha256;
  output_directory=$outputFull;component_plan_sha256=(Get-FileHash -LiteralPath $ComponentPlanPath -Algorithm SHA256).Hash;
  simion_executable_sha256=(Get-FileHash -LiteralPath $SimionExe -Algorithm SHA256).Hash;
  components=$componentReceipts;files=$runtimeFiles;published_native_members_opened=$false;
  canonical_iob_verified=$true;execution_alias_removed=$true;
  iob=@{path=$iobOutput;bytes=(Get-Item -LiteralPath $iobOutput).Length;sha256=(Get-FileHash -LiteralPath $iobOutput -Algorithm SHA256).Hash}
}
$shaPath = Join-Path $outputFull 'SHA256SUMS.csv'
# The build manifest records the checksum file, so the checksum file cannot in
# turn include the manifest without a circular hash dependency.  Write the
# delivery checksum first, then the provenance manifest.
$hashes = Get-ChildItem -LiteralPath $outputFull -File | Where-Object {
  $_.Name -notin @('SHA256SUMS.csv','run_manifest.json') -and $_.Name -notlike 'trj*.tmp'
} | Sort-Object Name | ForEach-Object {
  [pscustomobject]@{file=$_.Name; bytes=$_.Length; sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash}
}
$hashes | Export-Csv -LiteralPath $shaPath -NoTypeInformation -Encoding UTF8
$summaryPath=Join-Path $outputFull 'stage_summary.json'
Write-RunJson -Path $summaryPath -Depth 12 -Value @{schema_version=1;role='oa_tof_simion_delivery_summary';
  status='success';delivery_dir='simion';run_finalization_deferred=$true;
  runtime_receipt=$runtimeReceipt;components=$componentReceipts;particle_count=$ParticleCount}
"STATUS=PASS OUTPUT_DIR=$outputFull FILES=$($hashes.Count)"

} catch {
  $buildFailure=$_;throw
} finally {
  $hostRelease=@{inherited=[bool]$hostExecutionLease.inherited;token=[string]$hostExecutionLease.token;result=$null;error=$null}
  try{$hostRelease.result=Exit-HostResourceStage -Lease $hostExecutionLease -PassThru}
  catch{
    $hostRelease.error=$_.Exception.Message
    if($null-ne$buildFailure){Write-Warning "Host release failed after the original build error: $_"}else{throw}
  }
  finally{
    if($null-ne$script:codeExecutionAlias-and$script:allOperationsStopped){
      try{Remove-RunExecutionAlias -ExecutionAlias $script:codeExecutionAlias.execution_alias -TargetDirectory $repoRoot}
      catch{if($null-ne$buildFailure){Write-Warning "Code alias cleanup failed after the original build error: $_"}else{throw}}
    }
    if($null-ne$outputAlias-and$script:allOperationsStopped){
      try{Remove-RunExecutionAlias -ExecutionAlias $outputAlias.execution_alias -TargetDirectory $outputFull}
      catch{if($null-ne$buildFailure){Write-Warning "Execution alias cleanup failed after the original build error: $_"}else{throw}}
    }
  }
}
}catch{$buildFailure=$_;throw}
finally{
  $completion=@{schema_version=1;role='oatof_component_build_completion';run_id=$RunId;context_sha256=$ContextSha256;
    operations=@($nativeOperations.ToArray());components=@($producerComponents.ToArray());host_release=$hostRelease;
    exception=$(if($null-ne$buildFailure){$buildFailure.Exception.Message}else{$null})}
  try{
    Write-RunJson -Path $CompletionPath -Value $completion -Depth 64 -Atomic
  }
  catch{if($null-ne$buildFailure){Write-Warning "Build completion write failed after original failure: $_"}else{throw}}
}

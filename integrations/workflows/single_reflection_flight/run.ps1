[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$Request,
  [Parameter(Mandatory)][string]$ExecutionBudgetPath,
  [string]$RunId='',
  [switch]$FieldDesignOnly,
  [switch]$WorkbenchOnly,
  [switch]$Fly,
  [string]$Python='',
  [string]$RepoRoot=(Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)))
)

# This is the public run owner.  execute.ps1 owns scientific preparation,
# frozen executable dependencies, and updates the owner's capacity reservation;
# this wrapper owns the one run package, capacity session and terminal seal.
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
if(([int][bool]$FieldDesignOnly+[int][bool]$WorkbenchOnly+[int][bool]$Fly)-gt1){
  throw 'Select at most one of FieldDesignOnly, WorkbenchOnly or Fly.'
}
$stage=if($FieldDesignOnly){'field_design'}elseif($WorkbenchOnly){'workbench'}else{'fly'}
$RepoRoot=(Resolve-Path -LiteralPath $RepoRoot).Path
$Request=(Resolve-Path -LiteralPath $Request).Path
$ExecutionBudgetPath=(Resolve-Path -LiteralPath $ExecutionBudgetPath).Path
. (Join-Path $RepoRoot 'common/require_powershell7.ps1')
. (Join-Path $RepoRoot 'common/contracts/run_artifact_support.ps1')
if(-not$Python){$Python=Join-Path $RepoRoot '.venv/Scripts/python.exe'}
$Python=(Resolve-Path -LiteralPath $Python).Path
if(-not$RunId){$RunId=(Get-Date -Format 'yyyyMMdd_HHmmss')+'__sim__simion__single-reflection-flight'}

$project='instrument_assembly'
$workspace=Split-Path -Parent $RepoRoot
$artifacts=Join-Path $workspace 'artifacts'
$package=$null
$capacity=$null
$terminalized=$false;$writerUnknown=$false
$stageName='create_run_package'
$retentionReason='Retain native single-reflection fields, saved workbench, frozen source-cohort flight evidence, and default-replay parity for solver review.'
try {
  $package=New-RunPackage -Python $Python -RepoRoot $RepoRoot `
    -ArtifactRoot (Join-Path $artifacts "projects/$project") -RunId $RunId -Project $project `
    -Mode ("single_reflection_{0}" -f $stage) -Software @('SIMION 2020','Python 3.11','PowerShell 7') `
    -RetentionContractEnabled -RetentionClass solver_review -RetentionReason $retentionReason -CapacityLedgerLifecycleEnabled `
    -UseShortExecutionPath -AdditionalDirectories @('simion') `
    -ExpectedExecutionRelativePaths @(
      'inputs/runtime_snapshot/projects/single_reflection_oa_tof_mass_analyzer/simion/reflectron/oatof_reflectron_ideal_10_5.gem'
    )
  # Preparation initially needs no payload commitment. The delegated native
  # stage renews this same session from its frozen engineering budget.
  $ownerProtectedPaths=@($package.artifact_run_dir)
  $author=Get-Content -LiteralPath $Request -Raw|ConvertFrom-Json -AsHashtable -Depth 100
  if($author.ContainsKey('continuation')){
    $parentManifest=[string]$author.continuation.predecessor_run_manifest.path
    if(-not[IO.Path]::IsPathRooted($parentManifest)){$parentManifest=Join-Path (Split-Path -Parent $Request) $parentManifest}
    $parentManifest=(Resolve-Path -LiteralPath $parentManifest).Path
    $ownerProtectedPaths+=Split-Path -Parent $parentManifest
    $parent=Get-Content -LiteralPath $parentManifest -Raw|ConvertFrom-Json -AsHashtable -Depth 100
    if($parent.ContainsKey('inputs')){
      foreach($name in $parent.inputs.Keys){
        if($name.StartsWith('continuation_artifact_')){$ownerProtectedPaths+=[string]$parent.inputs[$name].path}
      }
    }
    if($parent.ContainsKey('outputs')){
      foreach($record in $parent.outputs){
        if((Split-Path -Leaf ([string]$record.path))-notin@('workbench_preparation.json','discovery_workbench_preparation.json')){continue}
        $parentWorkbench=Get-Content -LiteralPath ([string]$record.path) -Raw|ConvertFrom-Json -AsHashtable -Depth 100
        foreach($case in @($parentWorkbench.batches)){
          if($case.ContainsKey('continuation_pa_guard_records')){$ownerProtectedPaths+=@($case.continuation_pa_guard_records|ForEach-Object{[string]$_.path})}
        }
      }
    }
  }
  $capacity=Enter-ArtifactWorkflowCapacitySession -Python $Python -RepoRoot $RepoRoot -ArtifactRoot $artifacts `
    -RunDirectory $package.artifact_run_dir -CommittedNewBytes 0 -ProtectedPaths $ownerProtectedPaths `
    -Owner "instrument-assembly-single-reflection:$RunId"
  Write-RunJson -Path (Join-Path $package.result_dir 'artifact_capacity_gate_startup.json') -Depth 20 -Value $capacity
  # The public owner is part of the executable decision path.  Freeze this
  # small script once; execute.ps1 then freezes its own runtime closure.
  $runnerInput=Join-Path $package.input_dir 'run_single_reflection_flight.ps1'
  Copy-VerifiedRunInput -Source $PSCommandPath -Destination $runnerInput|Out-Null
  $initialConfig=Get-Content -LiteralPath $package.run_config -Raw|ConvertFrom-Json -AsHashtable -Depth 100
  $initialConfig.inputs.public_runner=$runnerInput
  Write-RunJson -Path $package.run_config -Depth 100 -Value $initialConfig

  $stageName='execute_frozen_workflow'
  $executeArguments=@{
    Request=$Request;ExecutionBudgetPath=$ExecutionBudgetPath;OutputDirectory=[string]$package.run_dir
    RepoRoot=$RepoRoot;Python=$Python;WorkflowCapacitySession=$capacity
  }
  if($stage-eq'field_design'){$executeArguments.FieldDesignOnly=$true}
  elseif($stage-eq'workbench'){$executeArguments.WorkbenchOnly=$true}
  else{$executeArguments.Fly=$true}
  & (Join-Path $RepoRoot 'integrations/workflows/single_reflection_flight/execute.ps1') @executeArguments

  $stageName='terminal_publication'
  $config=Get-Content -LiteralPath $package.run_config -Raw|ConvertFrom-Json -AsHashtable -Depth 100
  $config.parameters=[ordered]@{
    workflow='single_reflection_flight';requested_stage=$stage;scientific_request=(Join-Path $package.input_dir 'request.json')
    execution_budget=(Join-Path $package.input_dir 'resolved_integration_engineering_budget.json');gui_executed=$false
  }
  Write-RunJson -Path $package.run_config -Depth 100 -Value $config
  $nativeFlightCount=0;$reusedFlightCount=0;$nativeWorkbenchCount=0
  $flightRecords=Join-Path $package.result_dir 'single_reflection/flight_execution_records.json'
  if(Test-Path -LiteralPath $flightRecords){$nativeFlightCount=@(Get-Content -LiteralPath $flightRecords -Raw|ConvertFrom-Json).Count}
  foreach($receiptName in @('discovery_workbench_preparation.json','workbench_preparation.json')){
    $receiptPath=Join-Path $package.result_dir "single_reflection/$receiptName"
    if(Test-Path -LiteralPath $receiptPath){
      $wb=Get-Content -LiteralPath $receiptPath -Raw|ConvertFrom-Json -AsHashtable -Depth 100
      $cases=if($wb.ContainsKey('batches')){@($wb.batches)}else{@($wb)}
      foreach($case in $cases){
        if($case.ContainsKey('continuation_source')){$reusedFlightCount++}
        elseif($case.ContainsKey('native_workbench_execution')){$nativeWorkbenchCount+=@($case.native_workbench_execution).Count}
        if($case.ContainsKey('replay_continuation_source')){$reusedFlightCount++}
      }
    }
  }
  Write-RunJson -Path $package.summary -Depth 30 -Value ([ordered]@{
    schema_version=1;role='single_reflection_flight_run_summary';status='success';requested_stage=$stage
    field_design_executed=$true;workbench_executed=($stage-eq'workbench'-or$nativeWorkbenchCount-gt0);fly_executed=($nativeFlightCount-gt0)
    native_flight_batch_count=$nativeFlightCount;reused_flight_batch_count=$reusedFlightCount
    gui_executed=$false;qualification='workflow_execution_only__physical_qualification_is_defined_by_frozen_stage_receipts'
  })
  $retention=Apply-RunArtifactRetention -Python $Python -RepoRoot $RepoRoot -RunConfig $package.run_config
  $terminal=Update-ArtifactWorkflowCapacitySession -Python $Python -RepoRoot $RepoRoot -Session $capacity -RemainingCommittedNewBytes 0
  $capacity=$terminal.session
  Write-RunJson -Path (Join-Path $package.result_dir 'artifact_capacity_gate_terminal.json') -Depth 20 -Value $terminal
  $artifactInputPrefix=(Join-Path $package.artifact_run_dir 'inputs')+[IO.Path]::DirectorySeparatorChar
  $outputs=@(Get-ChildItem -LiteralPath $package.artifact_run_dir -Recurse -File|Where-Object{
    $_.Name-notin@('run_config.json','run_manifest.json') -and -not $_.FullName.StartsWith($artifactInputPrefix,[StringComparison]::OrdinalIgnoreCase)
  }|ForEach-Object{$_.FullName})
  Write-VerifiedRunManifest -Python $Python -RepoRoot $RepoRoot -RunConfig $package.run_config -Status success `
    -Software @('SIMION 2020','Python 3.11','PowerShell 7') -Outputs $outputs -DeferCapacityFinalization
  $terminalized=$true
  $stageName='stopped_payload_seal'
  $null=Exit-ArtifactWorkflowCapacitySession -Python $Python -RepoRoot $RepoRoot -Session $capacity
  $capacity=$null
  & $Python -B -m common.contracts.run_capacity_lifecycle --action seal-stopped-payload --artifact-root $artifacts `
    --run-config $package.run_config --owner $project --confirm-writing-stopped --retention-reason $retentionReason
  if($LASTEXITCODE-ne0){throw 'Single-reflection stopped-payload sealing failed.'}
  Write-Output "SINGLE_REFLECTION_RUN=PASS RUN_ID=$RunId STAGE=$stage GUI=False"
}catch {
  $failure=$_
  $data=$failure.Exception.Data
  $writerUnknown=([bool]$data['simion_first_batch_writer_unknown']-or[bool]$data['simion_first_batch_drain_error']-or
    ($data.Contains('simion_wave_writer_completion_confirmed')-and-not[bool]$data['simion_wave_writer_completion_confirmed']))
  if($writerUnknown){
    try{Write-RunJson -Path (Join-Path $package.result_dir 'writer_completion_unknown.json') -Value @{
      schema_version=1;role='writer_completion_unknown';status='unknown';reason=$failure.Exception.Message;failure_stage=$stageName
      drain_error=[string]$data['simion_first_batch_drain_error'];wave_drain_error=[string]$data['simion_wave_drain_error']
    }}catch{$failure.Exception.Data['writer_unknown_result_error']=[string]$_}
    throw $failure
  }
  $deferred=($null-ne$capacity-and$capacity.PSObject.Properties['defer_capacity_finalization']-and$capacity.defer_capacity_finalization)
  if($null-ne$package-and-not$terminalized){
    $failureProperties=@{requested_stage=$stage;gui_executed=$false}
    if($deferred){
      $failureProperties.capacity_finalization_deferred=$true
      $failureProperties.capacity_accounting_failure=[string]$capacity.defer_capacity_finalization
    }
    Complete-FailedRun -Python $Python -RepoRoot $RepoRoot -RunConfig $package.run_config -Summary $package.summary `
      -SummaryRole single_reflection_flight_run_summary -Reason $failure.Exception.Message `
      -Software @('SIMION 2020','Python 3.11','PowerShell 7') -Status failed -FailureStage $stageName `
      -AdditionalSummaryProperties $failureProperties -DeferCapacityFinalization
    $terminalized=$true
    if($deferred){
      Write-Warning 'Capacity commitment and protection lease retained; stopped payload sealing awaits transaction accounting.'
    }else{
      if($null-ne$capacity){
        $null=Exit-ArtifactWorkflowCapacitySession -Python $Python -RepoRoot $RepoRoot -Session $capacity
        $capacity=$null
      }
      & $Python -B -m common.contracts.run_capacity_lifecycle --action seal-stopped-payload --artifact-root $artifacts `
        --run-config $package.run_config --owner $project --confirm-writing-stopped --retention-reason $retentionReason
      if($LASTEXITCODE-ne0){throw 'Single-reflection failed-run stopped-payload sealing failed.'}
    }
  }
  throw $failure
}finally {
  if(-not$writerUnknown-and$null-ne$capacity-and-not($capacity.PSObject.Properties['defer_capacity_finalization']-and$capacity.defer_capacity_finalization)){
    $null=Exit-ArtifactWorkflowCapacitySession -Python $Python -RepoRoot $RepoRoot -Session $capacity
  }
  if(-not$writerUnknown-and$null-ne$package){Remove-RunPackageExecutionAlias -Package $package}
}

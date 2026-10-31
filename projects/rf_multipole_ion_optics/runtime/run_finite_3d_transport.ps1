[CmdletBinding(DefaultParameterSetName="Run")]
param(
  [Parameter(Mandatory=$true,ParameterSetName="Run")][string]$ProjectId,
  [Parameter(Mandatory=$true,ParameterSetName="Run")][string]$RuntimeProfileId,
  [Parameter(Mandatory=$true,ParameterSetName="Run")][string]$DesignProfileId,
  [Parameter(Mandatory=$true,ParameterSetName="Run")][string]$ParticleSourcePath,
  [Parameter(Mandatory=$true,ParameterSetName="Run")][Parameter(ParameterSetName="Analyze")][string]$EngineeringBudgetPath,
  [string]$EvidenceContractPath='',
  [string]$RunId='',
  [string]$PythonExe='',
  [ValidateRange(1,9)][int]$MeshAutoLevel=6,
  [double]$WorkingRegionMaximumElementSizeMm=[double]::NaN,
  [double]$MinimumElementSizeMm=[double]::NaN,
  [ValidateRange(4,10000)][int]$RfStepsPerPeriod=80,
  [ValidateRange(0.001,1000000)][double]$MaximumTimeUs=80.0,
  [ValidateSet('compact','qualification','solver_review')][string]$RetentionClass='compact',
  [string]$RetentionReason='',
  [string]$SourceFamilyPath='',
  [string]$OperatingPointId='',
  [ValidateSet('transport','mesh_build','field_solve')][string]$StopStage='transport',
  [string]$ResolvedRuntimeProfilePath='',
  [Parameter(Mandatory,ParameterSetName='Resume')][switch]$ResumeFinalization,
  [Parameter(Mandatory,ParameterSetName='Analyze')][switch]$AnalyzeOnly,
  [Parameter(ParameterSetName='Analyze')][switch]$ReextractFromModel,
  [Parameter(Mandatory,ParameterSetName='Analyze')][string]$ParentManifestPath,
  [string]$ResultPath='',
  [Parameter(ParameterSetName='Resume')][string]$ArtifactRootPath=''
)

Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
if($AnalyzeOnly-and[string]::IsNullOrWhiteSpace($EngineeringBudgetPath)){throw 'AnalyzeOnly requires an explicit EngineeringBudgetPath for its new analysis payload; parent native commitment is not a fallback.'}
$repoRoot=(Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$python=if($PythonExe){[IO.Path]::GetFullPath($PythonExe)}else{Join-Path $repoRoot '.venv\Scripts\python.exe'}
. (Join-Path $repoRoot 'common/contracts/run_artifact_workflow.ps1') -ResultPath $ResultPath -ResumeFinalization:$ResumeFinalization
if($ResumeFinalization){
  . (Join-Path $repoRoot 'common/paths/workspace_paths.ps1')
  $pathArguments=@{SourceRoot=$repoRoot;Python=$python}
  if($ArtifactRootPath){$pathArguments.ArtifactRoot=$ArtifactRootPath}
  if($RunId){
    Invoke-RunToolRootContext -RepoRoot $repoRoot -Operation {
      & $python -B -m common.contracts.artifact_naming run $RunId|Out-Null
      if($LASTEXITCODE-ne0){throw 'Recovery requires a valid existing RunId.'}
    }
  }
  if(-not$ResultPath){
    $recoveryPaths=Resolve-WorkspacePaths @pathArguments
    $projectArtifacts=Join-Path $recoveryPaths.artifact_root 'projects/rf_multipole_ion_optics'
    if(-not$RunId){throw 'Resume requires the original RunId or ResultPath.'}
    $ResultPath=Join-Path $projectArtifacts ('scratch/workflow_results/'+$RunId+'/result.json')
  }
  $prior=Get-Content -LiteralPath $ResultPath -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  if($prior.role-cne'run_artifact_workflow_result'){throw 'Resume requires the original workflow Result.'}
  $recoveryConfig=Get-Content -LiteralPath (Join-Path $prior.run_directory 'run_config.json') -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  if(-not$recoveryConfig.Contains('paths')){throw 'Recovery configuration omits its frozen workspace roots.'}
  $recoveryPaths=Resolve-WorkspacePaths -SourceRoot $repoRoot -FrozenContext $recoveryConfig.paths -Python $python
  if($ArtifactRootPath-and[IO.Path]::GetFullPath($ArtifactRootPath)-ine[IO.Path]::GetFullPath($recoveryPaths.artifact_root)){throw 'Recovery ArtifactRootPath differs from the frozen workspace roots.'}
  $projectArtifacts=Join-Path $recoveryPaths.artifact_root 'projects/rf_multipole_ion_optics'
  $originalRunId=Split-Path -Leaf $prior.run_directory
  if($RunId-and$RunId-cne$originalRunId){throw 'Recovery RunId differs from the original Result.'}
  if(-not$RunId){
  Invoke-RunToolRootContext -RepoRoot $repoRoot -Operation {
    & $python -B -m common.contracts.artifact_naming run $originalRunId|Out-Null
    if($LASTEXITCODE-ne0){throw 'Recovery requires a valid existing RunId.'}
  }
  }
  $runRoot=Join-Path $projectArtifacts ('runs/'+$originalRunId)
  if([IO.Path]::GetFullPath($prior.run_directory)-ine[IO.Path]::GetFullPath($runRoot)){throw 'Recovery Result is outside its configured project artifact root.'}
  $outcome=Invoke-RunArtifactWorkflow -RequestPath (Join-Path $runRoot 'inputs/execution_request.json') -ResultPath $ResultPath -ResumeFinalization
  Write-Output "MULTIPOLE_COMSOL_WORKFLOW_RESULT=$ResultPath STATUS=$($outcome.status) STAGE=$($outcome.stage)"
  if($outcome.stage-ne'complete'){throw "COMSOL finalization remains incomplete: $($outcome.stage)"}
  if($outcome.status-ne'success'){throw "COMSOL finalization completed; original execution status=$($outcome.status)."}
  return
}
if(-not$AnalyzeOnly){. (Join-Path $PSScriptRoot 'finite_3d_transport_preflight.ps1')}
if(-not [double]::IsNaN($WorkingRegionMaximumElementSizeMm) -and $WorkingRegionMaximumElementSizeMm-le 0){
  throw 'WorkingRegionMaximumElementSizeMm must be positive when supplied.'
}
. (Join-Path $repoRoot 'common/paths/workspace_paths.ps1')
$workspacePaths=Resolve-WorkspacePaths -SourceRoot $repoRoot -Python $python
$projectArtifactRoot=if($ProjectId){Join-Path ([string]$workspacePaths.artifact_root) ('projects/'+$ProjectId)}else{$null}
. (Join-Path $repoRoot 'common/resource_budget_support.ps1')
. (Join-Path $repoRoot 'common/host_execution_lease.ps1')

function Close-FiniteComsolStage {
  param([Collections.IDictionary]$State)
  if($null-eq$State.host_lease){return}
  $lease=$State.host_lease
  try{$actual=Exit-HostResourceStage -Lease $lease -PassThru}catch{$State.writer_unknown=$true;throw}
  if(-not$lease.inherited-and($null-eq$actual-or$actual.status-cne'released'-or$actual.token-cne$lease.token)){
    $State.writer_unknown=$true;throw 'COMSOL host release is unconfirmed.'
  }
  if($lease.inherited-and$null-ne$actual){$State.writer_unknown=$true;throw 'Inherited COMSOL stage returned an invented release.'}
  if($State.Contains('analysis_operations')-and$State.analysis_operations.Count){
    $State.analysis_host_release=@{host_release=@{inherited=[bool]$lease.inherited;token=[string]$lease.token;result=$actual;error=$null}}
  }
  $State.host_lease=$null
}

function Get-FiniteComsolWriterCompletion {
  param([Collections.IDictionary]$State,[string]$RunId)
  if(-not$State.native_attempted){return @{operations=@();resource_releases=@()}}
  if($null-eq$State.wrapper_observation){throw 'COMSOL wrapper process completion is unknown.'}
  $receipt=Get-Content -LiteralPath $State.launcher_receipt -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  if($receipt.schema_version-ne1-or$receipt.role-cne'comsol_launcher_completion'-or$receipt.run_id-cne$RunId){throw 'COMSOL launcher receipt identity differs.'}
  if($null-ne$receipt.host_release.error){throw "COMSOL host release failed: $($receipt.host_release.error)"}
  if($receipt.operations-isnot[array]){throw 'COMSOL launcher operations are not an array.'}
  $operations=@(@{operation_id='comsol-wrapper';observation=$State.wrapper_observation;resource_release_id='comsol'})
  $operations+=@($receipt.operations|ForEach-Object{
    @{operation_id=('comsol-'+$_.operation_id);observation=$_.observation;resource_release_id='comsol'}
  })
  $releases=[Collections.Generic.List[object]]::new()
  Add-RunArtifactResourceRelease -ResourceReleases $releases -ReleaseId 'comsol' -Receipt @{host_release=$receipt.host_release}
  $completion=@{operations=$operations;resource_releases=@($releases.ToArray())}
  Assert-WorkflowWriterCompletion $completion -PowerShellOwner
  return $completion
}

function Complete-FiniteComsolOwner {
  param([Collections.IDictionary]$Context,[Collections.IDictionary]$State,[string]$RunId,
    [string]$Status,[Collections.IDictionary]$Summary,[string[]]$Outputs=@(),[string[]]$Required=@(),$OriginalFailure=$null)
  if(-not$Summary.Contains('execution_status')){$Summary.execution_status=$Status}
  if(-not$Summary.Contains('data_validity')){$Summary.data_validity=if($Status-eq'success'){'valid'}else{'unknown'}}
  if(-not$Summary.Contains('scientific_result')){$Summary.scientific_result=if($Summary.Contains('qualification_status')){$Summary.qualification_status}else{'NOT_EVALUATED'}}
  $Summary.phase_timings_seconds=$State.phase_timings
  $Summary.total_elapsed_seconds=$State.timer.Elapsed.TotalSeconds
  if($State.Contains('saved_extraction')){$Summary.saved_solution_extraction=$State.saved_extraction}
  try{
    if($State.writer_unknown){throw 'COMSOL host release is unconfirmed; preserve its original resources.'}
    $completion=Get-FiniteComsolWriterCompletion -State $State -RunId $RunId
    Close-FiniteComsolStage -State $State
    if($State.Contains('analysis_operations')-and$State.analysis_operations.Count){
      $completion.operations=@($completion.operations)+@($State.analysis_operations.ToArray())
      $releases=[Collections.Generic.List[object]]::new()
      foreach($item in $completion.resource_releases){$releases.Add($item)}
      Add-RunArtifactResourceRelease -ResourceReleases $releases -ReleaseId 'analysis-python' -Receipt $State.analysis_host_release
      $completion.resource_releases=@($releases.ToArray())
      Assert-WorkflowWriterCompletion $completion -PowerShellOwner
    }
  }
  catch{
    $State.writer_unknown=$true
    $Summary.secondary_errors=@($_.Exception.Message)
    $Summary.execution_status='writer_completion_unknown';$Summary.recovery_action='inspect_writer_completion'
    $Summary.failure_reason=if($null-ne$OriginalFailure){$OriginalFailure.Exception.Message}else{$_.Exception.Message}
    $State.finalization_started=$true
    $null=Complete-RunArtifactPowerShellOwner -Context $Context -Status failed -Summary $Summary -WriterCompletion @{operations=@();resource_releases=@()} -WritersStopped $false -OriginalFailure $OriginalFailure
    throw
  }
  $usage=@()
  if($State.usage_path-and(Test-Path -LiteralPath $State.usage_path -PathType Leaf)){$usage=@(@{case_name='comsol';path=$State.usage_path})}
  if($State.Contains('analysis_usage_paths')){$usage+=@($State.analysis_usage_paths.ToArray())}
  $State.finalization_started=$true
  $outcome=Complete-RunArtifactPowerShellOwner -Context $Context -Status $Status -Summary $Summary -OutputPaths $Outputs -RequiredOutputPaths $Required -WriterCompletion $completion -WritersStopped $true -OriginalFailure $OriginalFailure -ResourceUsagePaths $usage
  if($outcome.stage-ne'complete'){throw "COMSOL public finalization failed at $($outcome.stage); resume the original Result."}
  $State.finalization_started=$false
  Write-Output "MULTIPOLE_COMSOL_WORKFLOW_RESULT=$($Context.result_path)"
  return $outcome
}



function Copy-FiniteComsolRuntime {
  param([string]$RepoRoot,[string]$InputDir,[string[]]$SourceAreas,[string[]]$AdditionalPaths=@())
  $codeRoot=Join-Path $inputDir 'code'
  foreach($area in $SourceAreas){
    $sourceRoot=Join-Path $repoRoot $area;$destinationRoot=Join-Path $codeRoot $area
    Get-ChildItem -LiteralPath $sourceRoot -Recurse -File|Where-Object{
      $_.Extension -in @('.py','.json','.ps1','.m','.lua')
    }|ForEach-Object{
      $relative=$_.FullName.Substring($sourceRoot.Length).TrimStart('\')
      $destination=Join-Path $destinationRoot $relative
      New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination)|Out-Null
      Copy-Item -LiteralPath $_.FullName -Destination $destination
    }
  }
  foreach($relative in $AdditionalPaths){
    Copy-VerifiedRunInput -Source (Join-Path $repoRoot $relative) `
      -Destination (Join-Path $codeRoot $relative)|Out-Null
  }
  $codeInventory=Join-Path $inputDir 'code_inventory.json'
  $resolvedCodeRoot=(Resolve-Path -LiteralPath $codeRoot).Path
  $inventory=@(Get-ChildItem -LiteralPath $codeRoot -Recurse -File|Sort-Object FullName|ForEach-Object{
    [ordered]@{path=[IO.Path]::GetRelativePath($resolvedCodeRoot,$_.FullName).Replace('\','/');sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash}
  })
  [ordered]@{schema_version=1;role='frozen_code_inventory';files=$inventory}|
    ConvertTo-Json -Depth 5|Set-Content -LiteralPath $codeInventory -Encoding UTF8

  return @{code_root=$codeRoot;inventory_path=$codeInventory;files=$inventory}
}
function Invoke-FiniteComsolAnalysis {
  param([Collections.IDictionary]$OwnerContext,[Collections.IDictionary]$OwnerState,
    [string]$RunId,[string]$ProjectId,[string]$DesignProfileId,[string]$Python,
    [string]$RepoRoot,[string]$CodeRoot,[string]$Resolved,[string]$Numerics,
    [string]$ParticleSource,[string]$SourceMetadata,[string]$Events,[string]$PrimaryState,[string]$ControlState,[string]$Evidence,
    [string]$AxialTopology,[string]$ResolvedHash,[string]$ResultDir,[string]$Summary,
    [string[]]$NativeOutputs=@(),[string[]]$Required=@(),[pscustomobject]$AnalysisLimits=$null)
  $ownerState.phase='analysis';$analysisStart=$ownerState.timer.Elapsed.TotalSeconds;$ownerState.analysis_started_at=$analysisStart
  Write-Output "MULTIPOLE_COMSOL_WORKFLOW_RESULT=$($ownerContext.result_path)"
  if($null-ne$AnalysisLimits){
    $ownerState.analysis_operations=[Collections.Generic.List[object]]::new()
    $ownerState.analysis_usage_paths=[Collections.Generic.List[object]]::new()
  }
  # This local binding invokes the existing public observer; it owns no loop,
  # scheduler or process registry. Normal transport preserves its original call.
  $invokePython={
    param([string]$Name,[string[]]$Arguments)
    if($null-eq$AnalysisLimits){& $python @Arguments;return [int]$LASTEXITCODE}
    $usage=Join-Path $ownerContext.run_directory ('results/analysis_'+$Name+'_resource_usage.json')
    $stdout=Join-Path $ownerContext.run_directory ('logs/analysis_'+$Name+'.stdout.log')
    $stderr=Join-Path $ownerContext.run_directory ('logs/analysis_'+$Name+'.stderr.log')
    $ownerState.analysis_usage_paths.Add(@{case_name=('analysis_'+$Name);path=$usage})
    # These closed analysis argv values contain files, normalized repo directory
    # and diagnostic text; preserve spaces/quotes through Start-Process transport.
    $nativeArguments=@($Arguments|ForEach-Object{'"'+([string]$_).Replace('"','\"')+'"'})
    try{
      $process=Invoke-ResourceBudgetedProcess -Limits $AnalysisLimits -RunDir $ownerContext.run_directory -UsagePath $usage `
        -FilePath $python -ArgumentList $nativeArguments -WorkingDirectory $codeRoot `
        -Environment @{PYTHONPATH=$codeRoot;PYTHONNOUSERSITE='1';PYTHONDONTWRITEBYTECODE='1';SIMULATION_PYTHON_EXE=$python} `
        -RedirectStandardOutput $stdout -RedirectStandardError $stderr
      $observation=@{exit_confirmed=$true;returncode=[int]$process.exit_code;process_id=[int]$process.root_process_id;process_started_at_utc_ticks=[long]$process.root_process_started_at_utc_ticks}
    }catch{
      $data=$_.Exception.Data
      if($data.Contains('observed_process_exit_confirmed')){
        if(-not[bool]$data['observed_process_exit_confirmed']-or-not$data.Contains('observed_process_id')-or
           -not$data.Contains('observed_process_started_at_utc_ticks')-or-not$data.Contains('observed_process_returncode')-or
           [long]$data['observed_process_id']-le0-or[long]$data['observed_process_started_at_utc_ticks']-le0-or$null-eq$data['observed_process_returncode']){$ownerState.writer_unknown=$true}
        else{
          $observation=@{exit_confirmed=[bool]$data['observed_process_exit_confirmed'];returncode=[int]$data['observed_process_returncode'];
            process_id=[int]$data['observed_process_id'];process_started_at_utc_ticks=[long]$data['observed_process_started_at_utc_ticks']}
          $ownerState.analysis_operations.Add(@{operation_id=('python-analysis-'+$Name);observation=$observation;resource_release_id='analysis-python'})
        }
      }
      throw
    }
    $ownerState.analysis_operations.Add(@{operation_id=('python-analysis-'+$Name);observation=$observation;resource_release_id='analysis-python'})
    if(Test-Path -LiteralPath $stdout){Get-Content -LiteralPath $stdout|Write-Host}
    if(Test-Path -LiteralPath $stderr){Get-Content -LiteralPath $stderr|Write-Host}
    if($process.resource_budget_exceeded){throw 'Analysis process stopped by existing physical-danger policy; inspect its resource usage.'}
    return [int]$process.exit_code
  }
  $metrics=Join-Path $ResultDir 'finite_3d_transport_metrics.json'
  $pairedMetrics=Join-Path $ResultDir 'paired_axial_drive_metrics.json'
  $evaluation=Join-Path $ResultDir 'evidence_evaluation.json'
  $exitStatePlot=Join-Path $ResultDir 'exit_state_diagnostics.png'
  $exitStatePlotManifest=Join-Path $ResultDir 'exit_state_diagnostics.json'
  Push-Location $codeRoot
  try{
    $env:PYTHONPATH=$codeRoot
    $exit=& $invokePython 'metrics' @('-B','-m','projects.rf_multipole_ion_optics.analysis.analyze_comsol_transport_metrics',
      '--events',$events,'--primary-state',$primaryState,'--control-state',$controlState,'--particle-source',$ParticleSource,
      '--particle-source-metadata',$SourceMetadata,'--resolved-design',$resolved,'--numerics',$numerics,'--output',$metrics)
    if($exit-ne 0){throw 'Python COMSOL transport metrics analysis failed.'}
  }finally{Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue;Pop-Location}
  if(-not(Test-Path -LiteralPath $metrics -PathType Leaf)){
    throw 'Python COMSOL transport metrics did not create finite_3d_transport_metrics.json.'}
  Push-Location $codeRoot
  try{
    $env:PYTHONPATH=$codeRoot
    $exitStatePlotLabel=$ProjectId.Replace('_',' ')
    $exit=& $invokePython 'exit_plot' @('-B','-m','projects.rf_multipole_ion_optics.analysis.exit_state_plot',
      '--series',"$exitStatePlotLabel=$primaryState=$RunId",'--output',$exitStatePlot,'--manifest',$exitStatePlotManifest,
      '--title',"$exitStatePlotLabel exit-state diagnostic",'--purpose','Regular single-run multipole exit-state diagnostic',
      '--allow-no-exit','--repo-root',$repoRoot)
    if($exit-ne 0){throw 'COMSOL exit-state diagnostic plot failed.'}
  }finally{Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue;Pop-Location}
  $exitStatePlotDocument=Get-Content -LiteralPath $exitStatePlotManifest -Raw -Encoding UTF8|ConvertFrom-Json
  $exitStatePlotStatus=[string]$exitStatePlotDocument.status
  $exitStatePlotReason=$exitStatePlotDocument.reason
  if($exitStatePlotStatus-eq'created'){
    if(-not(Test-Path -LiteralPath $exitStatePlot -PathType Leaf)){throw 'Created exit-state diagnostic PNG is missing.'}
  }elseif($exitStatePlotStatus-eq'not_applicable'){
    if([string]::IsNullOrWhiteSpace([string]$exitStatePlotReason)-or$null-ne$exitStatePlotDocument.figure-or
      (Test-Path -LiteralPath $exitStatePlot -PathType Leaf)){throw 'Invalid not-applicable exit-state diagnostic.'}
  }else{throw 'Exit-state diagnostic manifest has an unsupported status.'}
  if($axialTopology-ne'none'){
  Push-Location $codeRoot
    try{
      $env:PYTHONPATH=$codeRoot
      $exit=& $invokePython 'paired' @('-B','-m','projects.rf_multipole_ion_optics.analysis.analyze_simion_axial_acceleration',
        '--accelerated-state',$primaryState,'--control-state',$controlState,'--resolved-contract',$resolved,'--output',$pairedMetrics)
      if($exit-ne 0){throw 'COMSOL paired axial-drive metrics analysis failed.'}
    }finally{Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue;Pop-Location}
  }
  $qualification='UNQUALIFIED';$scientificFailedChecks=@()
  if($evidence){
    $evidenceDocument=Get-Content -LiteralPath $evidence -Raw -Encoding UTF8|ConvertFrom-Json
    $evidenceMetrics=if([string]$evidenceDocument.evaluation-eq'axial_drop_vs_zero_drop'){
      if($axialTopology-eq'none'){throw 'Axial-drop evidence requires an axial-drive design profile.'}
      $pairedMetrics
    }else{$metrics}
    Push-Location $codeRoot
    try{
      $env:PYTHONPATH=$codeRoot
      $evidenceExit=& $invokePython 'evidence' @('-B','-m','projects.rf_multipole_ion_optics.analysis.evaluate_transport_evidence',
        '--metrics',$evidenceMetrics,'--evidence',$evidence,'--project-id',$ProjectId,'--design-profile-id',$DesignProfileId,'--output',$evaluation)
    }finally{Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue;Pop-Location}
    if(-not(Test-Path -LiteralPath $evaluation -PathType Leaf)){throw 'COMSOL evidence evaluation did not create its decision.'}
    $decision=Get-Content -LiteralPath $evaluation -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
    if($decision.role-cne'multipole_transport_evidence_evaluation'-or$decision.project_id-cne$ProjectId-or
       $decision.design_profile_id-cne$DesignProfileId-or$decision.checks-isnot[Collections.IDictionary]-or
       @($decision.checks.Values|Where-Object{$_-isnot[bool]}).Count){throw 'COMSOL evidence decision identity or checks are invalid.'}
    if($evidenceExit-eq1-and$decision.status-ceq'FAIL'){
      $scientificFailedChecks=@($decision.checks.Keys|Where-Object{-not$decision.checks[$_]}|Sort-Object)
      if(-not$scientificFailedChecks.Count){throw 'COMSOL FAIL decision has no failed check.'}
      $qualification='FAIL'
    }elseif($evidenceExit-eq0-and$decision.status-ceq'PASS'){$qualification='PASS'}
    else{throw 'COMSOL evidence evaluation process/status mismatch.'}
  }
  $result=Get-Content -LiteralPath $metrics -Raw -Encoding UTF8|ConvertFrom-Json
  $primary=$result.cases.PSObject.Properties[[string]$result.primary_case_id].Value
  $control=$result.cases.PSObject.Properties[[string]$result.control_case_id].Value
  [ordered]@{schema_version=1;role='multipole_finite_3d_transport_summary';status='success';
    qualification_status=$qualification;project_id=$ProjectId;design_profile_id=$DesignProfileId;
    parent_resolved_design_sha256=$resolvedHash;primary_transmission=$primary.transmission_fraction;
    control_transmission=$control.transmission_fraction;model_level='L3';formal_gate_passed=$false;
    exit_state_plot_status=$exitStatePlotStatus;exit_state_plot_reason=$exitStatePlotReason}|
    ConvertTo-Json -Depth 5|Set-Content -LiteralPath $summary -Encoding UTF8
  $outputs=@($metrics,$exitStatePlot,$exitStatePlotManifest,$summary)+@($NativeOutputs)
  if(Test-Path -LiteralPath $pairedMetrics){$outputs+=$pairedMetrics}
  if(Test-Path -LiteralPath $evaluation){$outputs+=$evaluation}
  $outputs=@($outputs|Where-Object{Test-Path -LiteralPath $_ -PathType Leaf})
  $ownerState.phase_timings.analysis=$ownerState.timer.Elapsed.TotalSeconds-$analysisStart
  $summaryDocument=Get-Content -LiteralPath $summary -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  $status='success';$scientificError=$null
  if($scientificFailedChecks.Count){
    $status='failed'
    $reason='Scientific evidence FAIL: '+($scientificFailedChecks-join', ')
    $summaryDocument.execution_status='completed';$summaryDocument.data_validity='valid';$summaryDocument.scientific_result='FAIL'
    $summaryDocument.failure_stage='scientific_evaluation';$summaryDocument.failure_reason=$reason
    $summaryDocument.scientific_failed_checks=$scientificFailedChecks
    $summaryDocument.recovery_action='inspect_negative_result_or_start_explicit_new_study'
    $scientificError=[Management.Automation.ErrorRecord]::new([InvalidOperationException]::new($reason),
      'ScientificEvidenceThresholdsNotMet',[Management.Automation.ErrorCategory]::InvalidResult,$evaluation)
  }
  $null=Complete-FiniteComsolOwner -Context $ownerContext -State $ownerState -RunId $RunId -Status $status -Summary $summaryDocument -Outputs $outputs -Required $Required -OriginalFailure $scientificError
  if($null-ne$scientificError){throw $scientificError}
  Write-Output "MULTIPOLE_COMSOL_RESOLVED=PASS PROJECT=$ProjectId PROFILE=$DesignProfileId RUN_ID=$RunId PARENT_SHA256=$resolvedHash QUALIFICATION=$qualification"
}

function Get-FiniteComsolAnalysisSource {
  param([string]$ManifestPath,[string]$Python,[string]$RepoRoot,[switch]$ReextractFromModel)
  $code=@'
import json,re,sys
from pathlib import Path
from common.contracts.write_run_manifest import file_record,require_completed_terminal_publication
from common.contracts.file_identity import file_sha256
def admit(path,reextract,allow_cold=True,require_native_payload=True):
    path=path.resolve(strict=True);root=path.parent
    require_completed_terminal_publication(path)
    owner=json.loads(path.read_text(encoding='utf-8-sig'))
    if path.name!='run_manifest.json' or owner.get('schema_version') not in (1,2) or owner.get('role')!='simulation_run_manifest':
        raise ValueError('analysis parent requires its actual run_manifest.json')
    if owner.get('status') not in ('success','failed') or owner.get('project')!='rf_multipole_ion_optics':
        raise ValueError('analysis parent must be a sealed RF success/failed owner')
    def verify_small(record,expected=None):
        p=Path(record['path']).resolve(strict=True)
        if expected is not None and p!=expected:raise ValueError('parent bound path differs')
        if p.stat().st_size!=record['bytes'] or file_sha256(p).upper()!=record['sha256'].upper():raise ValueError('parent small identity differs')
        return p
    config_path=verify_small(owner['run_config'],root/'run_config.json')
    config=json.loads(config_path.read_text(encoding='utf-8-sig'))
    cold_child=config.get('mode')=='finite_comsol_analysis' and config.get('parameters',{}).get('reextract_from_model') is True
    if config.get('project')!=owner['project'] or config.get('run_id')!=root.name:
        raise ValueError('analysis parent identity differs')
    if not cold_child and (config.get('mode')!='resolved_design_transport' or config.get('role')!='multipole_resolved_comsol_run_config'):
        raise ValueError('analysis parent is not the frozen finite COMSOL transport owner')
    if not cold_child and config.get('parameters',{}).get('stop_stage')!='transport':raise ValueError('analysis requires transport exports, not a field/mesh-only run')
    def bound_output(name):
        target=(root/name).resolve();matches=[r for r in owner['outputs'] if Path(r.get('path','')).resolve()==target]
        if len(matches)!=1:raise ValueError('parent output is absent or ambiguous: '+name)
        r=matches[0]
        if not target.is_file() or target.stat().st_size!=r['bytes']:raise ValueError('parent export stat differs: '+name)
        return r
    def bound_input(key):
        p=Path(config['inputs'][key]).resolve(strict=True)
        values=[r for r in owner['inputs'].values() if isinstance(r,dict) and Path(r.get('path','')).resolve()==p]
        if not values or any((r.get('bytes'),r.get('sha256'))!=(values[0].get('bytes'),values[0].get('sha256')) for r in values):
            raise ValueError('parent scientific input is unbound: '+key)
        if not p.is_file() or p.stat().st_size!=values[0]['bytes']:raise ValueError('parent input stat differs: '+key)
        return values[0]
    completion_record=bound_output('results/execution_completion.json')
    completion=json.loads(verify_small(completion_record).read_text(encoding='utf-8-sig'))
    if completion.get('run_id')!=root.name or completion.get('project')!=owner['project']:raise ValueError('parent completion identity differs')
    if cold_child:
        if not allow_cold or reextract:raise ValueError('Cold CSV child can only be reanalyzed, not used as another native model owner')
        original_record=config['provenance']['parent_manifest_record']
        original=verify_small(original_record)
        native=admit(original,True,False,False)
        inventory_record=bound_input('code_inventory')
        inventory=json.loads(verify_small(inventory_record).read_text(encoding='utf-8-sig'))
        for relative in ('runtime/run_finite_3d_transport.ps1','comsol/reextract_finite_3d_transport.m','comsol/export_finite_3d_particle_outputs.m','comsol/validate_finite_extraction_context.m'):
            relative='projects/rf_multipole_ion_optics/'+relative
            matches=[entry for entry in inventory['files'] if entry['path']==relative]
            frozen_path=root/'inputs/code'/relative
            if len(matches)!=1 or file_sha256(frozen_path).upper()!=matches[0]['sha256'].upper():raise ValueError('Cold child frozen consumer/helper identity differs: '+relative)
        entry_request=json.loads(verify_small(bound_input('execution_request')).read_text(encoding='utf-8-sig'))
        prepared=entry_request.get('prepared',{})
        if prepared.get('owner_kind')!='powershell':raise ValueError('Cold child lacks public PowerShell owner')
        verify_small(prepared['entrypoint'],root/'inputs/code/projects/rf_multipole_ion_optics/runtime/run_finite_3d_transport.ps1')
        # Reuse only this exact newly published cold-child format, never generic lineage.
        request_record=bound_input('saved_extraction_request')
        request=json.loads(verify_small(request_record).read_text(encoding='utf-8-sig'))
        task_record=bound_input('saved_extraction_task')
        task_text=verify_small(task_record).read_text(encoding='utf-8-sig')
        if 'receipt=reextract_finite_3d_transport(request,fid);' not in task_text or 'receipt.native_solves==0 && ~receipt.parent_model_saved' not in task_text:
            raise ValueError('Cold child frozen task is not the supported saved-solution reader')
        for key, record in (('model_path',native['exports']['model']),('mapping_path',native['exports']['mapping']),('source_path',native['inputs']['particle_source'])):
            if Path(request[key]).resolve()!=Path(record['path']).resolve():raise ValueError('Cold child original native dependency differs: '+key)
        for key in ('multipole_resolved_design','solver_numerics','particle_source_metadata','engineering_budget'):
            record=bound_input(key)
            if (record['bytes'],record['sha256'].upper())!=(native['inputs'][key]['bytes'],native['inputs'][key]['sha256'].upper()):raise ValueError('Cold child frozen science differs: '+key)
        inputs={key:bound_input(key) for key in ('multipole_resolved_design','solver_numerics','particle_source_metadata','engineering_budget')}
        inputs['particle_source']=native['inputs']['particle_source']
        if bool(config['inputs'].get('evidence_contract'))!=('evidence_contract' in native['inputs']):raise ValueError('Cold child evidence authority differs from native parent')
        if config['inputs'].get('evidence_contract'):
            record=bound_input('evidence_contract');expected=native['inputs']['evidence_contract']
            if (record['bytes'],record['sha256'].upper())!=(expected['bytes'],expected['sha256'].upper()):raise ValueError('Cold child frozen evidence differs from native parent')
            inputs['evidence_contract']=record
        report_record=bound_output('logs/comsol_saved_extraction.txt')
        report=verify_small(report_record).read_text(encoding='utf-8-sig')
        if not all(re.search('^'+re.escape(token)+r'\s*$',report,re.M) for token in ('TASK=MULTIPOLE_FINITE_SAVED_EXTRACTION','CHECKPOINT=PARTICLE_EXPORT_COMPLETE','NATIVE_SOLVES=0','PARENT_MODEL_SAVED=false','STATUS=PASS')):
            raise ValueError('SAVED_EXTRACTION_STAGE_EVIDENCE_MISSING: actual completed extraction report required')
        operations=completion.get('writer_completion',{}).get('operations',[])
        if not any(item.get('operation_id')=='comsol-wrapper' and item.get('observation',{}).get('exit_confirmed') is True and item['observation'].get('returncode')==0 for item in operations):
            raise ValueError('SAVED_EXTRACTION_STAGE_EVIDENCE_MISSING: real successful commercial wrapper completion required')
        exports={name:bound_output('results/'+filename) for name,filename in (('events','particle_events.csv'),('primary_state','particle_state__primary.csv'),('control_state','particle_state__control.csv'))}
        for name, output in (('events','events'),('primary_state','primary_canonical'),('control_state','control_canonical')):
            if Path(request['context']['outputs'][output]).resolve()!=Path(exports[name]['path']).resolve():raise ValueError('Cold child exported path differs from frozen request')
        return dict(manifest_record=file_record(path),config_record=owner['run_config'],config=config,inputs=inputs,exports=exports,completion=completion,
            stage_evidence=dict(basis='completed_saved_extraction_child_bound_task_report_and_original_native_owner',native_report_record=report_record,task_record=task_record,original_native_stage=native['stage_evidence']),
            ancestor_references=[dict(manifest_record=native['manifest_record'],protected_paths=[record['path'] for record in native['inputs'].values()])],ancestor_completion=native['completion'])
    inputs={name:bound_input(name) for name in ('multipole_resolved_design','solver_numerics','particle_source','particle_source_metadata','engineering_budget')}
    if config['inputs'].get('evidence_contract'):inputs['evidence_contract']=bound_input('evidence_contract')
    report_record=bound_output('logs/comsol_finite_3d_transport.txt')
    report=verify_small(report_record).read_text(encoding='utf-8-sig')
    task_record=bound_input('comsol_task')
    task=verify_small(task_record,root/'inputs/code/projects/rf_multipole_ion_optics/comsol/solve_finite_3d_transport.m')
    inventory_record=bound_input('code_inventory')
    inventory=json.loads(verify_small(inventory_record).read_text(encoding='utf-8-sig'))
    entries=[entry for entry in inventory['files'] if entry['path']=='projects/rf_multipole_ion_optics/comsol/solve_finite_3d_transport.m']
    if len(entries)!=1 or entries[0]['sha256'].upper()!=task_record['sha256'].upper():raise ValueError('parent frozen producer task differs from its code inventory')
    # Derive only these frozen normal finite producer families; no current defaults.
    compact=re.sub(r'\s+','',task.read_text(encoding='utf-8-sig'))
    case_positions=[compact.find(token) for token in ("solve_particle_case(model,cpt,'on',","solve_particle_case(model,cpt,'zero',")]
    raw_save=compact.find('model.save(modelPath);',max(case_positions))
    if any(pos<0 for pos in case_positions) or case_positions!=sorted(case_positions) or raw_save<case_positions[-1]:
        raise ValueError('TRANSPORT_STAGE_EVIDENCE_MISSING: frozen physical cases/raw-save control sequence unsupported')
    if not re.search(r'^TASK=MULTIPOLE_FINITE_3D_TRANSPORT\s*$',report,re.M):raise ValueError('TRANSPORT_STAGE_EVIDENCE_MISSING: original native task differs')
    statuses=re.findall(r'^STATUS=(PASS|FAIL)\s*$',report,re.M)
    whole_pass=bool(statuses) and statuses[-1]=='PASS' and bool(re.search(r'^MODEL_SAVED=true\s*$',report,re.M))
    raw_complete=all(re.search(pattern,report,re.M) for pattern in (
        r'^CHECKPOINT=PRIMARY_PARTICLE_CASE_COMPLETE\s*$',r'^CHECKPOINT=CONTROL_PARTICLE_CASE_COMPLETE\s*$',
        r'^TIMING_PERSIST_SECONDS=[0-9.eE+\-]+ RAW_SOLUTION_PERSISTED=true\s*$'))
    helper_token='export_finite_3d_particle_outputs(model,source,sourceMetadata,extractionContext,fid);'
    helper_call=compact.find(helper_token)
    helper_record=None
    if helper_call>=0:
        helper_path=root/'inputs/code/projects/rf_multipole_ion_optics/comsol/export_finite_3d_particle_outputs.m'
        helper_entries=[entry for entry in inventory['files'] if entry['path']=='projects/rf_multipole_ion_optics/comsol/export_finite_3d_particle_outputs.m']
        if len(helper_entries)!=1:raise ValueError('TRANSPORT_STAGE_EVIDENCE_MISSING: frozen export helper absent from inventory')
        helper_record=file_record(helper_path)
        if helper_record['sha256'].upper()!=helper_entries[0]['sha256'].upper():raise ValueError('parent frozen export helper differs from inventory')
        helper=re.sub(r'\s+','',helper_path.read_text(encoding='utf-8-sig'))
        ordered=('writetable(events,eventsPath);','write_canonical_particle_state(pdOn,source,primaryCanonicalStatePath,','write_canonical_particle_state(pdZero,source,controlCanonicalStatePath,')
        points=[helper.find(token) for token in ordered]
        marker=compact.find("fprintf(fid,'CHECKPOINT=PARTICLE_EXPORT_COMPLETE\\n');")
        final_save=compact.rfind('model.save(modelPath);')
        passed_site=compact.rfind("fprintf(fid,'ELECTRODE_COUNT=%d\\nMODEL_SAVED=true\\nSTATUS=PASS\\n'")
        known_export=raw_save<helper_call<final_save<passed_site and all(point>=0 for point in points) and points==sorted(points)
        export_complete=known_export and marker>helper_call and bool(re.search(r'^CHECKPOINT=PARTICLE_EXPORT_COMPLETE\s*$',report,re.M))
    else:
        sequence=('writetable(events,eventsPath);','write_canonical_particle_state(pdOn,source,primaryCanonicalStatePath,','write_canonical_particle_state(pdZero,source,controlCanonicalStatePath,')
        points=[compact.find(token) for token in sequence]
        save=compact.rfind('model.save(modelPath);')
        passed=compact.rfind("fprintf(fid,'ELECTRODE_COUNT=%d\\nMODEL_SAVED=true\\nSTATUS=PASS\\n'")
        known_export=all(point>=0 for point in points) and points==sorted(points) and points[-1]<save<passed
        export_site=compact.find("fprintf(fid,'TIMING_NATIVE_EXPORT_SECONDS=")
        export_complete=(known_export and points[-1]<export_site<passed and raw_complete and all(re.search(pattern,report,re.M) for pattern in (
          r'^TIMING_EXTRACT_SECONDS=[0-9.eE+\-]+ RETAINED_SAMPLES=[0-9]+\s*$',r'^TIMING_NATIVE_EXPORT_SECONDS=[0-9.eE+\-]+\s*$')))
    if reextract:
        if "solutionTag=['sol_'label];" not in compact or "datasetTag=['pd_'label'_temp'];" not in compact or "dataset.set('solution',solutionTag);" not in compact:
            raise ValueError('SAVED_SOLUTION_TAG_BINDING_MISSING: original finite solution/dataset names cannot be proven')
        if not (raw_complete or (whole_pass and known_export)):
            raise ValueError('RAW_SOLUTION_STAGE_EVIDENCE_MISSING: both physical cases and original raw save must be proven; do not solve implicitly')
        try:
            if require_native_payload:
                exports={'model':bound_output('results/finite_3d_transport.mph'),'mapping':bound_output('results/release_source_mapping.json')}
            else:
                exports={}
                for key,name in (('model','results/finite_3d_transport.mph'),('mapping','results/release_source_mapping.json')):
                    matches=[record for record in owner['outputs'] if Path(record.get('path','')).resolve()==(root/name).resolve()]
                    if len(matches)!=1:raise ValueError('Original extraction dependency record absent: '+key)
                    exports[key]=matches[0]
        except ValueError as error:
            raise ValueError('SAVED_SOLUTION_REEXTRACTION_DEPENDENCY_MISSING: original MPH and complete native release mapping required; '+str(error)) from error
        if require_native_payload:verify_small(exports['mapping']) # No native payload dependency for already exported CSV child.
        stage_basis='frozen_producer_two_cases_and_raw_save' if raw_complete else 'frozen_producer_whole_native_PASS_MODEL_SAVED'
    else:
        if not known_export or not (whole_pass or export_complete):
            raise ValueError('TRANSPORT_STAGE_EVIDENCE_MISSING: neither native task PASS/MODEL_SAVED nor proven completed exports; validated saved-solution re-extraction is required, not implicit solve')
        stage_basis='frozen_producer_post_export_record_and_case_completions' if export_complete else 'frozen_producer_whole_native_PASS_MODEL_SAVED_and_bound_exports'
        try:
            exports={name:bound_output('results/'+filename) for name,filename in (
                ('events','particle_events.csv'),('primary_state','particle_state__primary.csv'),('control_state','particle_state__control.csv'))}
        except ValueError as error:
            raise ValueError('CSV_EXPORTS_INCOMPLETE_REEXTRACTION_REQUIRED: AnalyzeOnly will not solve or load MPH; '+str(error)) from error
    stage_evidence=dict(native_report_record=report_record,comsol_task_record=task_record,code_inventory_record=inventory_record,basis=stage_basis)
    if helper_record is not None:stage_evidence['export_helper_record']=helper_record
    request=bound_input('execution_request')
    request_document=json.loads(verify_small(request).read_text(encoding='utf-8-sig'))
    prepared=request_document.get('prepared',{})
    entry_record=prepared.get('entrypoint')
    if prepared.get('owner_kind')!='powershell' or not isinstance(entry_record,dict):raise ValueError('parent lacks its original public workflow entrypoint')
    verify_small(entry_record,root/'inputs/code/projects/rf_multipole_ion_optics/runtime/run_finite_3d_transport.ps1')
    entry_inventory=[entry for entry in inventory['files'] if entry['path']=='projects/rf_multipole_ion_optics/runtime/run_finite_3d_transport.ps1']
    if len(entry_inventory)!=1 or entry_inventory[0]['sha256'].upper()!=entry_record['sha256'].upper():raise ValueError('parent original workflow differs from its frozen code inventory')
    stage_evidence['workflow_entrypoint_record']=entry_record
    return dict(manifest_record=file_record(path),config_record=owner['run_config'],config=config,
        inputs=inputs,exports=exports,completion=completion,stage_evidence=stage_evidence)
print(json.dumps(admit(Path(sys.argv[1]),sys.argv[2]=='1')))
'@
  $text=Invoke-RunToolRootContext -RepoRoot $RepoRoot -Operation {
    & $Python -B -c $code $ManifestPath ([int][bool]$ReextractFromModel)
    if($LASTEXITCODE-ne0){throw 'Finite COMSOL analysis parent admission failed; inspect the exact preceding reason.'}
  }
  return ($text-join"`n")|ConvertFrom-Json -AsHashtable -Depth 100
}

function Invoke-FiniteComsolSavedExtraction {
  param([Collections.IDictionary]$Context,[Collections.IDictionary]$State,[Collections.IDictionary]$Source,
    [Collections.IDictionary]$Frozen,[string]$CodeRoot,[string]$Python,[string]$RunId,[pscustomobject]$Limits)
  $inputDir=Join-Path $Context.run_directory 'inputs';$resultDir=Join-Path $Context.run_directory 'results'
  $request=Join-Path $inputDir 'saved_extraction_request.json'
  $report=Join-Path $Context.run_directory 'logs/comsol_saved_extraction.txt'
  $usage=Join-Path $resultDir 'saved_extraction_resource_usage.json'
  $destinations=@{events='particle_events.csv';trajectories='trajectory_samples.csv';canonical='particle_state.csv';
    primary_canonical='particle_state__primary.csv';control_canonical='particle_state__control.csv';
    primary_trajectories='trajectory_samples__primary.csv';control_trajectories='trajectory_samples__control.csv'}
  $outputs=@{};foreach($key in $destinations.Keys){$outputs[$key]=Join-Path $resultDir $destinations[$key]}
  $binding=Join-Path $inputDir 'saved_extraction_binding.json'
  Write-RunJson -Path $binding -Value @{outputs=$outputs;model_path=$Source.exports.model.path;
    mapping_path=$Source.exports.mapping.path;source_path=$Source.inputs.particle_source.path;
    source_metadata_path=$Frozen.particle_source_metadata;resolved_path=$Frozen.multipole_resolved_design;numerics_path=$Frozen.solver_numerics} -Depth 20
  $task=Join-Path $inputDir 'reextract_saved_finite_solution.m'
  $State.launcher_receipt=Join-Path $Context.run_directory 'logs/comsol_launcher_completion.json'
  $launcher=Join-Path $CodeRoot 'common/comsol/run_comsol_r2025b.ps1'
  $budgetsPath=Join-Path $inputDir 'saved_extraction_host_budgets.json'
  $nativeRequest=Join-Path $inputDir 'saved_extraction_native_request.json'
  $bootstrap=Join-Path $CodeRoot 'common/comsol/livelink_r2025b/comsolstartup.m'
  $stdout=Join-Path $Context.run_directory 'logs/saved_extraction.stdout.log'
  $stderr=Join-Path $Context.run_directory 'logs/saved_extraction.stderr.log'
  $nativePaths=@($launcher,$bootstrap,$task,$request,$nativeRequest,$binding,$report,$State.launcher_receipt,$budgetsPath,$CodeRoot,$stdout,$stderr,$usage,
    $Source.exports.model.path,$Source.exports.mapping.path,$Source.inputs.particle_source.path,$Frozen.particle_source_metadata)+@($outputs.Values)
  $native=Get-RunNativeExecutionContext -Package $Context.package -Paths $nativePaths -Tool COMSOL
  $Context.execution_run_directory=[string]$Context.package.run_dir
  $nativeMap=@{};for($index=0;$index-lt$nativePaths.Count;$index++){$nativeMap[$nativePaths[$index]]=$native.projected_paths[$index]}
  $projection=@"
import json,sys
from pathlib import Path
from projects.rf_multipole_ion_optics.runtime.finite_extraction_context import project_finite_extraction_science
read=lambda p:json.loads(Path(p).read_text(encoding='utf-8-sig'))
binding=read(sys.argv[1]);mapping=read(binding['mapping_path'])
if mapping.get('native_scope')!='complete_cohort':raise ValueError('Original complete native release mapping required')
metadata=read(binding['source_metadata_path'])
context=project_finite_extraction_science(read(binding['resolved_path']),read(binding['numerics_path']),metadata)
for name in ('native_order','source_ids','source_birth_s'):
    if not isinstance(mapping.get(name),list) or not mapping[name]:raise ValueError('Original release mapping missing '+name)
    context[name]=mapping[name]
count=len(context['source_ids'])
if any(isinstance(value,bool) or not isinstance(value,int) or value<=0 for name in ('source_ids','native_order') for value in context[name]):
    raise ValueError('Original mapping must preserve exact positive integer identities/permutation')
if count!=metadata['particle_count'] or len(set(context['source_ids']))!=count or sorted(context['native_order'])!=list(range(1,count+1)) or len(context['source_birth_s'])!=count:
    raise ValueError('Original native release mapping does not close the mother cohort')
context.update(solution_on='sol_on',solution_zero='sol_zero',dataset_on='pd_on_temp',dataset_zero='pd_zero_temp',outputs=binding['outputs'])
request={key:binding[key] for key in ('model_path','source_path','source_metadata_path','mapping_path')}
request['context']=context
Path(sys.argv[2]).write_text(json.dumps(request,allow_nan=False),encoding='utf-8')
"@
  Invoke-RunToolRootContext -RepoRoot $nativeMap[$CodeRoot] -Operation {
    & $Python -B -c $projection $nativeMap[$binding] $nativeMap[$request]
    if($LASTEXITCODE-ne0){throw 'Saved extraction context cannot be projected from original frozen authority.'}
  }
  $task=Join-Path $inputDir 'reextract_saved_finite_solution.m'
  $matlab=@"
% Frozen per-run task: the project reader never solves or saves the original.
addpath(fullfile(fileparts(mfilename('fullpath')),'code','projects','rf_multipole_ion_optics','comsol'));
addpath(fullfile(fileparts(mfilename('fullpath')),'code','common','comsol'));
fid=fopen(getenv('COMSOL_BOOTSTRAP_REPORT'),'w');assert(fid>=0,'Cold report unavailable.');
cleanup=onCleanup(@()fclose(fid));
fprintf(fid,'TASK=MULTIPOLE_FINITE_SAVED_EXTRACTION\n');
try
 request=jsondecode(fileread(getenv('RF_FINITE_REEXTRACTION_REQUEST')));
 receipt=reextract_finite_3d_transport(request,fid);
 assert(receipt.native_solves==0 && ~receipt.parent_model_saved,'Cold reader changed original model.');
 fprintf(fid,'CHECKPOINT=PARTICLE_EXPORT_COMPLETE\nNATIVE_SOLVES=0\nPARENT_MODEL_SAVED=false\nSTATUS=PASS\n');
catch exception
 fprintf(fid,'STATUS=FAIL\nERROR=%s\n',getReport(exception,'extended','hyperlinks','off'));rethrow(exception);
end
"@
  Set-Content -LiteralPath $task -Value $matlab -Encoding UTF8
  $configPath=Join-Path $Context.run_directory 'run_config.json'
  $config=Get-Content -LiteralPath $configPath -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  $config.inputs.saved_extraction_request=$request;$config.inputs.saved_extraction_task=$task
  $config.provenance.referenced_model=$Source.exports.model;$config.provenance.release_mapping=$Source.exports.mapping
  $State.phase='saved_extraction';$start=$State.timer.Elapsed.TotalSeconds
  $State.usage_path=$usage;$State.launcher_receipt=Join-Path $Context.run_directory 'logs/comsol_launcher_completion.json'
  $launcher=Join-Path $CodeRoot 'common/comsol/run_comsol_r2025b.ps1'
  $budgets=@{};foreach($stage in @('prepare','solver','postprocess')){
    $budget=Get-HostResourceBudget -Role COMSOL -Stage $stage
    $budget.memory_bytes=[long]$Limits.process_tree_working_set_bytes;$budgets[$stage]=$budget
  }
  $budgetsPath=Join-Path $inputDir 'saved_extraction_host_budgets.json'
  Write-RunJson -Path $budgetsPath -Value $budgets -Depth 20
  $config.inputs.saved_extraction_host_budgets=$budgetsPath
  Write-RunJson -Atomic -Path $configPath -Value $config -Depth 100
  # Persistent request/config keep owner identities. This disposable native-only
  # envelope is projected once and removed only after actual writers are stopped.
  $executionRequest=Get-Content -LiteralPath $request -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  foreach($key in @('model_path','source_path','source_metadata_path','mapping_path')){$executionRequest[$key]=$nativeMap[$executionRequest[$key]]}
  foreach($key in @($executionRequest.context.outputs.Keys)){$executionRequest.context.outputs[$key]=$nativeMap[$executionRequest.context.outputs[$key]]}
  Write-RunJson -Path $nativeRequest -Value $executionRequest -Depth 100
  $nativeEnvironment=@{};foreach($key in $native.environment.Keys){$nativeEnvironment[$key]=$native.environment[$key]}
  $nativeEnvironment.RF_FINITE_REEXTRACTION_REQUEST=$nativeMap[$nativeRequest]
  $nativeEnvironment.SIMULATION_PYTHON_EXE=$Python
  $nativeStopped=$false
  $quote={param($value) "'"+([string]$value).Replace("'","''")+"'"}
  $command="& $(& $quote $nativeMap[$launcher]) -TaskScript $(& $quote $nativeMap[$task]) -ReportPath $(& $quote $nativeMap[$report]) -StartupAttempts 1 -RunId $(& $quote $RunId) -CompletionPath $(& $quote $nativeMap[$State.launcher_receipt]) -ResourceBudgets (Get-Content -LiteralPath $(& $quote $nativeMap[$budgetsPath]) -Raw -Encoding UTF8 | ConvertFrom-Json -AsHashtable)"
  $encoded=[Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($command))
  try{
    try{
      $State.native_attempted=$true
      $process=Invoke-ResourceBudgetedProcess -Limits $Limits -RunDir $Context.run_directory -UsagePath $usage `
        -FilePath (Get-Process -Id $PID).Path -ArgumentList @('-NoProfile','-NonInteractive','-EncodedCommand',$encoded) -WorkingDirectory $nativeMap[$CodeRoot] -Environment $nativeEnvironment `
        -RedirectStandardOutput $nativeMap[$stdout] -RedirectStandardError $nativeMap[$stderr]
      $State.wrapper_observation=@{exit_confirmed=$true;returncode=[int]$process.exit_code;process_id=[int]$process.root_process_id;process_started_at_utc_ticks=[long]$process.root_process_started_at_utc_ticks}
    }catch{
      $data=$_.Exception.Data
      if($data.Contains('observed_process_exit_confirmed')-and$data.Contains('observed_process_returncode')-and
         $data.Contains('observed_process_id')-and$data.Contains('observed_process_started_at_utc_ticks')){
        $State.wrapper_observation=@{exit_confirmed=$data['observed_process_exit_confirmed'];returncode=$data['observed_process_returncode'];
          process_id=$data['observed_process_id'];process_started_at_utc_ticks=$data['observed_process_started_at_utc_ticks']}
      }
      throw
    }
    try{$null=Get-FiniteComsolWriterCompletion -State $State -RunId $RunId;$nativeStopped=$true}catch{
      if($process.exit_code-ne0){
        $detail=@(Get-Content -LiteralPath (Join-Path $Context.run_directory 'logs/saved_extraction.stderr.log') -Tail 60 -ErrorAction SilentlyContinue)-join"`n"
        $primary=[InvalidOperationException]::new("Saved-solution extraction failed; no solve was requested. Report=$report`n$detail")
        $primary.Data['writer_completion_error']=$_.Exception.Message;throw $primary
      }
      throw
    }
    if($process.resource_budget_exceeded-or$process.exit_code-ne0){throw "Saved-solution extraction failed; no solve was requested. Report=$report"}
    $text=Get-Content -LiteralPath $report -Raw -Encoding UTF8
    foreach($token in @('TASK=MULTIPOLE_FINITE_SAVED_EXTRACTION','CHECKPOINT=PARTICLE_EXPORT_COMPLETE','NATIVE_SOLVES=0','PARENT_MODEL_SAVED=false','STATUS=PASS')){
      if($text-notmatch('(?m)^'+[regex]::Escape($token)+'\r?$')){throw "Saved-solution extraction report missing actual fact: $token"}
    }
    foreach($path in $outputs.Values){if(-not(Test-Path -LiteralPath $path -PathType Leaf)){throw "Saved-solution extraction output missing: $path"}}
    $State.saved_extraction=@{completed=$true;commercial_model_load=$true;native_solves=0;parent_model_saved=$false;report_path=$report;source_model_record=$Source.exports.model}
    return @{code_root=$nativeMap[$CodeRoot];exports=@{events=@{path=$outputs.events};primary_state=@{path=$outputs.primary_canonical};control_state=@{path=$outputs.control_canonical}};
      outputs=@($outputs.Values)+@($report,$usage);required=@($report,$outputs.events,$outputs.primary_canonical,$outputs.control_canonical)}
  }finally{
    $State.phase_timings.saved_extraction=$State.timer.Elapsed.TotalSeconds-$start
    if($nativeStopped){Remove-Item -LiteralPath $nativeRequest -Force -ErrorAction SilentlyContinue}
  }
}

function Invoke-FiniteComsolAnalysisChild {
  param([string]$ParentManifestPath,[string]$EngineeringBudgetPath,[string]$Python,[string]$RepoRoot,[string]$RunId,[string]$ResultPath,
    [string]$RetentionClass,[string]$RetentionReason,[switch]$ReextractFromModel)
  $parent=(Resolve-Path -LiteralPath $ParentManifestPath).Path
  $reader=Enter-RunTerminalConsumptionGuard -RunDirectory (Split-Path -Parent $parent)
  $capacity=$null;$package=$null;$context=$null;$failure=$null
  $state=@{native_attempted=$false;wrapper_observation=$null;launcher_receipt=$null;host_lease=$null;
    writer_unknown=$false;finalization_started=$false;usage_path=$null;phase='prepare';phase_timings=@{};timer=[Diagnostics.Stopwatch]::StartNew()}
  $names=@('PYTHONPATH','SIMULATION_PYTHON_EXE','MASS_SPECTROMETRY_ARTIFACT_ROOT','MASS_SPECTROMETRY_EXECUTION_ROOT','MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH','MASS_SPECTROMETRY_RUN_DIRECTORY','MASS_SPECTROMETRY_RUN_EXECUTION_DIRECTORY','RF_FINITE_REEXTRACTION_REQUEST')
  $saved=Save-RunEnvironment -Names $names
  try{
    $env:SIMULATION_PYTHON_EXE=$Python
    $source=Get-FiniteComsolAnalysisSource -ManifestPath $parent -Python $Python -RepoRoot $RepoRoot -ReextractFromModel:$ReextractFromModel
    Assert-WorkflowWriterCompletion $source.completion.writer_completion -PowerShellOwner
    if($source.Contains('ancestor_completion')){Assert-WorkflowWriterCompletion $source.ancestor_completion.writer_completion -PowerShellOwner}
    $config=$source.config;$projectId=[string]$config.project
    $paths=Resolve-WorkspacePaths -SourceRoot $RepoRoot -FrozenContext $config.paths -Python $Python
    $env:MASS_SPECTROMETRY_ARTIFACT_ROOT=[string]$paths.artifact_root
    $env:MASS_SPECTROMETRY_EXECUTION_ROOT=[string]$paths.execution_root
    $env:MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH=[string]$paths.host_resource_state_path
    if(-not$RunId){$RunId=(Get-Date -Format yyyyMMdd_HHmmss)+$(if($ReextractFromModel){'__analysis__comsol__rf-finite-reextract'}else{'__analysis__python__rf-finite-comsol'})}
    $projectRoot=Join-Path $paths.artifact_root ('projects/'+$projectId)
    $analysisBudgetPath=(Resolve-Path -LiteralPath $EngineeringBudgetPath).Path
    Assert-WorkflowFileRecord $source.inputs.engineering_budget
    Assert-WorkflowFileRecord $source.inputs.particle_source_metadata
    $budgetCode='import json,sys;from pathlib import Path;from projects.rf_multipole_ion_optics.runtime.resource_budget import validate_analysis_budget;read=lambda p:json.loads(Path(p).read_text(encoding="utf-8-sig"));print(json.dumps(validate_analysis_budget(read(sys.argv[1]),parent_config=read(sys.argv[2]),parent_budget=read(sys.argv[3]),source_metadata=read(sys.argv[4]),retention_class=sys.argv[5],run_id=sys.argv[6])))'
    $budgetText=Invoke-RunToolRootContext -RepoRoot $RepoRoot -Operation {
      & $Python -B -c $budgetCode $analysisBudgetPath $source.config_record.path $source.inputs.engineering_budget.path `
        $source.inputs.particle_source_metadata.path $RetentionClass $RunId
      if($LASTEXITCODE-ne0){throw 'Analysis engineering budget differs from frozen parent authority.'}
    }
    $analysisBudget=($budgetText-join"`n")|ConvertFrom-Json -AsHashtable -Depth 100
    $analysisAreas=@('common/contracts','common/paths','common/analysis','projects/rf_multipole_ion_optics/core','projects/rf_multipole_ion_optics/runtime','projects/rf_multipole_ion_optics/analysis')
    $analysisAdditional=@()
    if($ReextractFromModel){
      $analysisAreas+=@('common/comsol','projects/rf_multipole_ion_optics/comsol')
      $analysisAdditional=@('common/host_execution_lease.ps1','common/host_resource_scheduler.py','common/host_resource_policy.json','common/require_powershell7.ps1','common/resource_budget_support.ps1')
    }
    $copiedPaths=@(Get-RunPackageCopiedSourcePaths -RepoRoot $RepoRoot -SourceRelativeDirectories $analysisAreas -Extensions @('.py','.json','.ps1','.m','.lua'))
    $copiedPaths+=@($analysisAdditional|ForEach-Object{"inputs/code/$_"})
    [long]$codeBytes=0
    $inventoryTemplate=@(foreach($relative in $copiedPaths){
      $inside=$relative.Substring('inputs/code/'.Length)
      $codeBytes+=[long](Get-Item -LiteralPath (Join-Path $RepoRoot $inside)).Length
      [ordered]@{path=$inside;sha256=('0'*64)}
    })
    $inventoryDocument=[ordered]@{schema_version=1;role='frozen_code_inventory';files=$inventoryTemplate}
    [long]$inventoryBytes=[Text.Encoding]::UTF8.GetByteCount(($inventoryDocument|ConvertTo-Json -Depth 5)+[Environment]::NewLine)
    [long]$inputBytes=[long]$source.manifest_record.bytes+[long](Get-Item -LiteralPath $analysisBudgetPath).Length
    foreach($key in $source.inputs.Keys){if($key-ne'particle_source'){$inputBytes+=[long]$source.inputs[$key].bytes}}
    # Explicit analysis authorization bounds new results/closeout conservatively;
    # old native models and CSV references contribute no new payload bytes.
    [long]$resultAndCloseout=[long]$analysisBudget.limits.compact_final_retained_bytes
    [long]$requiredNew=$codeBytes+$inputBytes+$inventoryBytes+$resultAndCloseout
    [long]$commitment=[long]$analysisBudget.limits.transient_run_directory_bytes
    if($commitment-lt$requiredNew){throw "Analysis new-payload budget is insufficient: required=$requiredNew (code=$codeBytes inputs=$inputBytes inventory=$inventoryBytes results_and_closeout=$resultAndCloseout), authorized=$commitment; referenced native/CSV new bytes=0."}
    $forecast=@{copied_source_bytes=$codeBytes;frozen_small_input_bytes=$inputBytes;code_inventory_bytes=$inventoryBytes;
      result_and_closeout_allowance_bytes=$resultAndCloseout;required_new_bytes=$requiredNew;committed_new_bytes=$commitment;
      referenced_native_and_csv_new_bytes=0;authority='explicit analysis engineering budget; no parent native commitment'}
    $references=@(@{manifest_record=$source.manifest_record;protected_paths=@($source.exports.Values|ForEach-Object path)+@($source.inputs.Values|ForEach-Object path)})
    if($source.Contains('ancestor_references')){$references+=@($source.ancestor_references)}
    $capacity=Enter-ArtifactWorkflowCapacitySession -Python $Python -RepoRoot $RepoRoot -ArtifactRoot $paths.artifact_root `
      -RunDirectory (Join-Path $projectRoot ('runs/'+$RunId)) -CommittedNewBytes $commitment `
      -SourceReferences $references -Owner ("run-artifact-workflow:{0}:{1}"-f$projectId,$RunId)
    $package=New-RunPackage -Python $Python -RepoRoot $RepoRoot -ArtifactRoot $projectRoot -PathContext $paths `
      -RunId $RunId -Project $projectId -Mode finite_comsol_analysis -RetentionContractEnabled -CapacityLedgerLifecycleEnabled `
      -RetentionClass $RetentionClass -RetentionReason $RetentionReason -Software $(if($ReextractFromModel){@('COMSOL 6.4','MATLAB R2025b','Python 3.11')}else{@('Python 3.11')})
    $copied=Copy-FiniteComsolRuntime -RepoRoot $RepoRoot -InputDir $package.input_dir -SourceAreas $analysisAreas -AdditionalPaths $analysisAdditional
    $frozen=@{}
    foreach($key in $source.inputs.Keys){
      if($key-eq'particle_source'){continue} # Protected source CSV is consumed once, never copied/rehashed.
      $destination=Join-Path $package.input_dir ($key+'.json')
      Assert-WorkflowFileRecord $source.inputs[$key]
      $null=Copy-VerifiedRunInput -Source $source.inputs[$key].path -Destination $destination
      $frozen[$key]=$destination
    }
    $analysisBudgetFrozen=Join-Path $package.input_dir 'analysis_engineering_budget.json'
    $null=Copy-VerifiedRunInput -Source $analysisBudgetPath -Destination $analysisBudgetFrozen
    Write-RunJson -Path (Join-Path $package.result_dir 'analysis_payload_forecast.json') -Value $forecast -Depth 20
    $parentManifestCopy=Join-Path $package.input_dir 'parent_run_manifest.json'
    $null=Copy-VerifiedRunInput -Source $parent -Destination $parentManifestCopy
    $context=Initialize-RunArtifactPowerShellOwner -Python $Python -RepoRoot $RepoRoot -Package $package -CapacitySession $capacity `
      -ResultPath $ResultPath -EntrypointPath (Join-Path $copied.code_root 'projects/rf_multipole_ion_optics/runtime/run_finite_3d_transport.ps1') `
      -CommitmentInputPaths @($analysisBudgetFrozen,$parentManifestCopy) -Software @('Python 3.11')
    $child=Get-Content -LiteralPath $package.run_config -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
    foreach($key in $frozen.Keys){$child.inputs[$key]=Convert-WorkflowOwnerPath $context $frozen[$key]}
    $child.inputs.code_inventory=Convert-WorkflowOwnerPath $context $copied.inventory_path
    $child.inputs.parent_manifest=Convert-WorkflowOwnerPath $context $parentManifestCopy
    $child.inputs.analysis_engineering_budget=Convert-WorkflowOwnerPath $context $analysisBudgetFrozen
    $child.parameters=@{analysis_only=$true;reextract_from_model=[bool]$ReextractFromModel;runtime_profile_id=$config.parameters.runtime_profile_id;design_profile_id=$config.parameters.design_profile_id}
    $child.provenance=@{parent_resolved_design_sha256=(Get-Content -LiteralPath $frozen.multipole_resolved_design -Raw -Encoding UTF8|ConvertFrom-Json).resolved_sha256;parent_manifest_record=$source.manifest_record;referenced_exports=$source.exports;particle_source_record=$source.inputs.particle_source;native_transport_stage=$source.stage_evidence}
    Write-RunJson -Atomic -Path (Join-Path $context.run_directory 'run_config.json') -Value $child -Depth 100
    $state.phase_timings.prepare=$state.timer.Elapsed.TotalSeconds
    $analysisExports=$source.exports;$analysisCodeRoot=$copied.code_root
    $nativeOutputs=@();$nativeRequired=@()
    if($ReextractFromModel){
      $cold=Invoke-FiniteComsolSavedExtraction -Context $context -State $state -Source $source -Frozen $frozen -CodeRoot $copied.code_root `
        -Python $Python -RunId $RunId -Limits ([pscustomobject]$analysisBudget.limits)
      $analysisExports=$cold.exports;$analysisCodeRoot=$cold.code_root;$nativeOutputs=$cold.outputs;$nativeRequired=$cold.required
    }
    $hostBudget=Get-HostResourceBudget -Role COMSOL -Stage postprocess
    $hostBudget.memory_bytes=[long]$analysisBudget.limits.process_tree_working_set_bytes
    $state.host_lease=Enter-HostResourceStage -StatePath $paths.host_resource_state_path -Role COMSOL -Stage postprocess -RunId $RunId -Budget $hostBudget
    $design=Get-Content -LiteralPath $frozen.multipole_resolved_design -Raw -Encoding UTF8|ConvertFrom-Json
    $axial=[string]$design.axial_drive.topology
    $evidence=if($frozen.Contains('evidence_contract')){$frozen.evidence_contract}else{''}
    Invoke-FiniteComsolAnalysis -OwnerContext $context -OwnerState $state -RunId $RunId -ProjectId $projectId `
      -DesignProfileId $config.parameters.design_profile_id -Python $Python -RepoRoot $RepoRoot -CodeRoot $analysisCodeRoot `
      -Resolved $frozen.multipole_resolved_design -Numerics $frozen.solver_numerics -ParticleSource $source.inputs.particle_source.path -SourceMetadata $frozen.particle_source_metadata -Events $analysisExports.events.path `
      -PrimaryState $analysisExports.primary_state.path -ControlState $analysisExports.control_state.path -Evidence $evidence `
      -AxialTopology $axial -ResolvedHash $design.resolved_sha256 -ResultDir $package.result_dir -Summary $package.summary -NativeOutputs $nativeOutputs -Required $nativeRequired -AnalysisLimits ([pscustomobject]$analysisBudget.limits)
  }catch{
    $failure=$_
    if($state.phase-eq'analysis'){$state.phase_timings.analysis=$state.timer.Elapsed.TotalSeconds-$state.analysis_started_at}
    if($context-and-not$context.completion_written-and-not$state.finalization_started){
      $failed=@{schema_version=1;role='multipole_finite_3d_transport_summary';failure_stage=$state.phase;
        failure_reason=$failure.Exception.Message;recovery_action='repair_analysis_and_create_new_analysis_child';formal_gate_passed=$false}
      try{$null=Complete-FiniteComsolOwner -Context $context -State $state -RunId $RunId -Status failed -Summary $failed -OriginalFailure $failure `
        -Outputs @((Get-ChildItem -LiteralPath $package.result_dir -File|ForEach-Object FullName))}catch{$failure.Exception.Data['failure_closure_error']=$_.Exception.Message}
    }
    throw $failure
  }finally{
    try{
      try{
        if(-not$context){
          try{Close-FiniteComsolStage -State $state}finally{
            if($capacity){$null=Exit-ArtifactWorkflowCapacitySession -Python $Python -RepoRoot $RepoRoot -Session $capacity}
            if($package){Remove-RunPackageExecutionAlias -Package $package}
          }
        }
      }catch{if($failure){$failure.Exception.Data['analysis_bootstrap_cleanup_error']=$_.Exception.Message}else{throw}}
      finally{if(-not$state.writer_unknown){$reader.Dispose()}}
    }finally{Restore-RunEnvironment -Names $names -Snapshot $saved}
  }
}

if($AnalyzeOnly){
  $overrides=@('EvidenceContractPath','MeshAutoLevel','WorkingRegionMaximumElementSizeMm','MinimumElementSizeMm','RfStepsPerPeriod','MaximumTimeUs','SourceFamilyPath','OperatingPointId','StopStage','ResolvedRuntimeProfilePath')
  if(@($overrides|Where-Object{$PSBoundParameters.ContainsKey($_)}).Count){throw 'AnalyzeOnly uses parent frozen scientific authority; scientific overrides are not accepted.'}
  Invoke-FiniteComsolAnalysisChild -ParentManifestPath $ParentManifestPath -EngineeringBudgetPath $EngineeringBudgetPath -Python $python -RepoRoot $repoRoot -RunId $RunId `
    -ResultPath $ResultPath -RetentionClass $RetentionClass -RetentionReason $RetentionReason -ReextractFromModel:$ReextractFromModel
  return
}

$particleSourceInput=(Resolve-Path -LiteralPath $ParticleSourcePath).Path
$engineeringBudgetInput=(Resolve-Path -LiteralPath $EngineeringBudgetPath).Path
$hasSourceFamily=-not[string]::IsNullOrWhiteSpace($SourceFamilyPath)
$hasOperatingPoint=-not[string]::IsNullOrWhiteSpace($OperatingPointId)
if($hasSourceFamily-ne$hasOperatingPoint){
  throw 'SourceFamilyPath and OperatingPointId must be supplied together.'
}
$sourceFamilyInput=if($hasSourceFamily){(Resolve-Path -LiteralPath $SourceFamilyPath).Path}else{$null}
$registryPreflight=Get-Content -LiteralPath (Join-Path $repoRoot 'config\project_registry.json') -Raw -Encoding UTF8|ConvertFrom-Json
$projectMatches=@($registryPreflight.projects|Where-Object{[string]$_.project_id-eq$ProjectId})
if($projectMatches.Count-ne 1){throw "ProjectId is not unique in the canonical project registry: $ProjectId"}
if([string]::IsNullOrWhiteSpace($RunId)){
  $RunId=(Get-Date -Format 'yyyyMMdd_HHmmss')+"__sim__comsol__$($ProjectId.Replace('_','-'))-$($DesignProfileId.Replace('_','-'))__resolved-l3"
}
$budgetPreflight=Join-Path ([IO.Path]::GetTempPath()) ("multipole_budget_{0}.json"-f[guid]::NewGuid())
try{
  Push-Location $repoRoot
  try{
    & $python -m projects.rf_multipole_ion_optics.runtime.resource_budget --repo-root $repoRoot `
      --budget $engineeringBudgetInput --project-id $ProjectId --solver comsol `
      --runtime-profile-id $RuntimeProfileId --design-profile-id $DesignProfileId `
      --particle-source $particleSourceInput --retention-class $RetentionClass `
      --output $budgetPreflight `
      @($(if($ResolvedRuntimeProfilePath){'--resolved-runtime-profile';$ResolvedRuntimeProfilePath}))
  }finally{Pop-Location}
  if($LASTEXITCODE-ne 0){throw 'COMSOL resource-budget preflight failed.'}
  $resolvedBudget=Get-Content -LiteralPath $budgetPreflight -Raw -Encoding UTF8|ConvertFrom-Json
  if($resolvedBudget.PSObject.Properties.Name-notcontains'stop_stage'){
    throw 'COMSOL resolved resource budget omits the runtime-profile stop stage.'
  }
  $authorizedStopStage=[string]$resolvedBudget.stop_stage
  if($authorizedStopStage-notin@('transport','mesh_build','field_solve')){
    throw 'COMSOL resolved resource budget has an unsupported runtime-profile stop stage.'
  }
  if($StopStage-ne$authorizedStopStage){
    throw 'COMSOL StopStage differs from the authorized runtime profile.'
  }
  $authorizedNumerics=$resolvedBudget.solver_numerics
  $authorizedBackend=[string]$authorizedNumerics.stationary_linear_solver_backend
  if($authorizedBackend-notin@('mumps','pardiso','cg_amg')){
    throw 'COMSOL runtime profile has an unsupported stationary linear-solver backend.'
  }
  $hasIterativeSolver=$authorizedNumerics.PSObject.Properties.Name-contains'stationary_iterative_solver'
  if($authorizedBackend-eq'cg_amg'){
    if(-not$hasIterativeSolver){
      throw 'CG-AMG runtime profile omits stationary_iterative_solver.'
    }
    $authorizedIterativeSolver=$authorizedNumerics.stationary_iterative_solver
    $iterativeKeys=@($authorizedIterativeSolver.PSObject.Properties.Name|Sort-Object)
    if(($iterativeKeys-join',')-ne'error_check_mode,maximum_iterations,relative_tolerance'){
      throw 'CG-AMG stationary_iterative_solver fields differ.'
    }
    $authorizedRelativeTolerance=[double]$authorizedIterativeSolver.relative_tolerance
    $authorizedMaximumIterations=[double]$authorizedIterativeSolver.maximum_iterations
    $authorizedErrorCheck=[string]$authorizedIterativeSolver.error_check_mode
    if([double]::IsNaN($authorizedRelativeTolerance)-or
      [double]::IsInfinity($authorizedRelativeTolerance)-or
      $authorizedRelativeTolerance-le 0-or$authorizedRelativeTolerance-ge 1-or
      [double]::IsNaN($authorizedMaximumIterations)-or
      [double]::IsInfinity($authorizedMaximumIterations)-or
      $authorizedMaximumIterations-lt 1-or
      $authorizedMaximumIterations-ne[math]::Truncate($authorizedMaximumIterations)-or
      $authorizedErrorCheck-ne'on'){
      throw 'CG-AMG stationary_iterative_solver values are invalid.'
    }
  }else{
    if($hasIterativeSolver){
      throw 'Direct stationary solver profiles forbid stationary_iterative_solver.'
    }
    $authorizedIterativeSolver=$null
  }
  if($authorizedNumerics.PSObject.Properties.Name-notcontains'electric_potential_element_order'){
    throw 'COMSOL runtime profile omits the required electric-potential element order.'
  }
  $authorizedElementOrder=[string]$authorizedNumerics.electric_potential_element_order
  if($authorizedElementOrder-notin@('linear','quadratic')){
    throw 'COMSOL runtime profile has an unsupported electric-potential element order.'
  }
  $maximumMeshCells=$null
  if($resolvedBudget.limits.PSObject.Properties.Name-contains'maximum_mesh_cells'){
    $maximumMeshCells=[int64]$resolvedBudget.limits.maximum_mesh_cells
  }
  $fieldPreregistration=$null
  $fieldSamplingPlanInput=$null
  if($StopStage-eq'field_solve'){
    $fieldPreregistration=Assert-MultipoleFieldPreregistration `
      -Path $EvidenceContractPath -RepoRoot $repoRoot -ProjectId $ProjectId `
      -RunId $RunId -RuntimeProfileId $RuntimeProfileId `
      -DesignProfileId $DesignProfileId `
      -ParticleSourceProfileId ([string]$resolvedBudget.particle_source_profile_id) `
      -SolverNumericsProfileId ([string]$resolvedBudget.solver_numerics_profile_id) `
      -RetentionClass $RetentionClass `
      -ExpectedResolvedSha256 ([string]$resolvedBudget.expected_run_parent_resolved_design_sha256) `
      -EngineeringBudgetPath $engineeringBudgetInput
    $fieldSamplingPlanInput=[IO.Path]::GetFullPath(
      (Join-Path $repoRoot ([string]$fieldPreregistration.field_sampling.plan_path))
    )
  }
  $authorizedHmin=if($authorizedNumerics.mesh.PSObject.Properties.Name -contains 'minimum_element_size_mm'){$authorizedNumerics.mesh.minimum_element_size_mm}else{$null}
  if($null-ne$authorizedHmin-and([double]::IsNaN([double]$authorizedHmin)-or[double]::IsInfinity([double]$authorizedHmin)-or[double]$authorizedHmin-le0)){
    throw 'COMSOL authorized minimum element size must be positive finite.'
  }
  $authorizedHmax=$authorizedNumerics.mesh.working_region_maximum_element_size_mm
  if(($null-eq$authorizedHmin)-ne[double]::IsNaN($MinimumElementSizeMm)-or
    ($null-ne$authorizedHmin-and[double]$authorizedHmin-ne$MinimumElementSizeMm)-or
    ($null-ne$authorizedHmin-and$null-ne$authorizedHmax-and[double]$authorizedHmin-gt[double]$authorizedHmax)){
    throw 'COMSOL minimum element size differs from the authorized runtime profile.'
  }
  if([int]$authorizedNumerics.mesh.global_auto_level-ne$MeshAutoLevel-or
    [int]$authorizedNumerics.trajectory.rf_steps_per_period-ne$RfStepsPerPeriod-or
    [double]$authorizedNumerics.trajectory.maximum_global_time_us-ne$MaximumTimeUs-or
    ($null-eq$authorizedHmax)-ne[double]::IsNaN($WorkingRegionMaximumElementSizeMm)-or
    ($null-ne$authorizedHmax-and[double]$authorizedHmax-ne$WorkingRegionMaximumElementSizeMm)){
    throw 'COMSOL numerical arguments differ from the authorized runtime profile.'
  }
}finally{
  Remove-Item -LiteralPath $budgetPreflight -Force -ErrorAction SilentlyContinue
}
$hostRuntimeSourcePaths=@(
  'common/host_execution_lease.ps1','common/host_resource_scheduler.py',
  'common/host_resource_policy.json','common/require_powershell7.ps1','common/resource_budget_support.ps1','common/resource_budget_support.ps1')
$analysisSourcePaths=@('common/analysis/particle_census.py','common/simion/native_completion.py')
$executionCapacityPaths=Get-RunPackageCopiedSourcePaths -RepoRoot $repoRoot `
  -SourceRelativeDirectories @('common/contracts','common/paths','common/comsol','projects/rf_multipole_ion_optics/core','projects/rf_multipole_ion_optics/runtime','projects/rf_multipole_ion_optics/analysis','projects/rf_multipole_ion_optics/config','projects/rf_multipole_ion_optics/comsol','projects/rf_multipole_ion_optics/simion') `
  -Extensions @('.py','.json','.ps1','.m','.lua')
$executionCapacityPaths+=@(($hostRuntimeSourcePaths+$analysisSourcePaths)|ForEach-Object{"inputs/code/$_"})
$entryScriptHash=(Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash
$ownerContext=$null;$capacity=$null;$package=$null;$comsolRunFailure=$null
$resourceBudgetExceeded=$false
$ownerState=@{native_attempted=$false;wrapper_observation=$null;launcher_receipt=$null;host_lease=$null;
  writer_unknown=$false;finalization_started=$false;usage_path=$null;phase='prepare';phase_timings=@{};timer=[Diagnostics.Stopwatch]::StartNew()}
$environmentNames=@('PYTHONPATH','SIMULATION_PYTHON_EXE','MULTIPOLE_RESOLVED_DESIGN','MULTIPOLE_SOLVER_NUMERICS','MULTIPOLE_L3_PARTICLE_SOURCE',
 'MULTIPOLE_L3_PARTICLE_SOURCE_METADATA','MULTIPOLE_L3_RUNTIME_DIR','MULTIPOLE_L3_EVENTS','MULTIPOLE_L3_TRAJECTORIES','MULTIPOLE_L3_METRICS','MULTIPOLE_L3_PLOT','MULTIPOLE_L3_MODEL',
 'MULTIPOLE_L3_CANONICAL_STATE','MULTIPOLE_L3_PRIMARY_CANONICAL_STATE','MULTIPOLE_L3_CONTROL_CANONICAL_STATE','MULTIPOLE_L3_PRIMARY_TRAJECTORIES','MULTIPOLE_L3_CONTROL_TRAJECTORIES',
 'MULTIPOLE_L3_SOLVER_PROGRESS_DIR','MULTIPOLE_L3_STOP_STAGE','MULTIPOLE_L3_FIELD_SAMPLE_POINTS','MULTIPOLE_L3_FIELD_SAMPLES','MULTIPOLE_L3_MAXIMUM_MESH_CELLS','MULTIPOLE_FINITE_EXTRACTION_SCIENCE')
$oldEnvironment=Save-RunEnvironment -Names $environmentNames
$env:SIMULATION_PYTHON_EXE=$python
try{
$capacity=Enter-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -ArtifactRoot $workspacePaths.artifact_root `
  -RunDirectory (Join-Path $projectArtifactRoot ('runs/'+$RunId)) -CommittedNewBytes ([long]$resolvedBudget.limits.transient_run_directory_bytes) `
  -ProtectedPaths @(@($particleSourceInput,$engineeringBudgetInput,$sourceFamilyInput)|Where-Object{$_-and(Test-WorkflowPathWithin $_ ([string]$workspacePaths.artifact_root))}) -Owner ("run-artifact-workflow:{0}:{1}"-f$ProjectId,$RunId)
$package=New-RunPackage -Python $python -RepoRoot $repoRoot `
  -ArtifactRoot $projectArtifactRoot -PathContext $workspacePaths -RunId $RunId `
  -Project $ProjectId -Mode 'resolved_design_transport' `
  -RetentionContractEnabled -CapacityLedgerLifecycleEnabled `
  -RetentionClass $RetentionClass -RetentionReason $RetentionReason `
  -Software @('COMSOL 6.4','MATLAB R2025b','Python 3.11') -UseShortExecutionPath `
  -ExpectedExecutionRelativePaths $executionCapacityPaths
$runDir=$package.run_dir;$inputDir=$package.input_dir;$resultDir=$package.result_dir
$logDir=$package.log_dir;$runConfig=$package.run_config;$summary=$package.summary
$runtimeDir=Join-Path $logDir 'runtime'
$solverProgressDir=Join-Path $logDir 'solver_progress'
New-Item -ItemType Directory -Force -Path $runtimeDir|Out-Null
New-Item -ItemType Directory -Force -Path $solverProgressDir|Out-Null
. (Join-Path $repoRoot 'common\host_execution_lease.ps1')
$hostExecutionOutcome='failed'
$ownerState.host_lease=Enter-HostExecutionLease -StatePath $workspacePaths.host_resource_state_path -Role COMSOL -Stage prepare -RunId $RunId
$comsolRunFailure=$null

  $copied=Copy-FiniteComsolRuntime -RepoRoot $repoRoot -InputDir $inputDir -SourceAreas @(
    'common/contracts','common/paths','common/comsol','projects/rf_multipole_ion_optics/core','projects/rf_multipole_ion_optics/runtime','projects/rf_multipole_ion_optics/analysis','projects/rf_multipole_ion_optics/config','projects/rf_multipole_ion_optics/comsol','projects/rf_multipole_ion_optics/simion') -AdditionalPaths @($hostRuntimeSourcePaths+$analysisSourcePaths)
  $codeRoot=$copied.code_root;$codeInventory=$copied.inventory_path;$inventory=$copied.files

  $profileResolution=Join-Path $inputDir 'design_profile_resolution.json'
  $engineeringBudget=Join-Path $inputDir 'engineering_budget.json'
  Copy-Item -LiteralPath $engineeringBudgetInput -Destination $engineeringBudget
  $ownerSource=Join-Path $codeRoot 'projects/rf_multipole_ion_optics/runtime/run_finite_3d_transport.ps1'
  $ownerEntry=@($inventory|Where-Object{$_.path-ceq'projects/rf_multipole_ion_optics/runtime/run_finite_3d_transport.ps1'})
  if($ownerEntry.Count-ne1-or$ownerEntry[0].sha256-ine$entryScriptHash){throw 'Frozen COMSOL owner differs from the launched source.'}
  $ownerContext=Initialize-RunArtifactPowerShellOwner -Python $python -RepoRoot $repoRoot -Package $package -CapacitySession $capacity `
    -ResultPath $ResultPath -EntrypointPath $ownerSource -CommitmentInputPaths @($engineeringBudget) -Software @('COMSOL 6.4','MATLAB R2025b','Python 3.11')
  $ResultPath=$ownerContext.result_path

  $compiledRuntime=$null
  if($ResolvedRuntimeProfilePath){
    $compiledRuntime=Get-Content -LiteralPath $ResolvedRuntimeProfilePath -Raw -Encoding UTF8|ConvertFrom-Json -Depth 100
    if($compiledRuntime.project_id-ne$ProjectId-or$compiledRuntime.design_profile_id-ne$DesignProfileId-or$compiledRuntime.runtime_profile_id-ne$RuntimeProfileId){throw 'Compiled COMSOL runtime identity differs.'}
    Write-RunJson -Path $profileResolution -Value $compiledRuntime.design_profile_resolution -Depth 100
  }else{
  Push-Location $codeRoot
  try{
    $env:PYTHONPATH=$codeRoot
    & $python -m projects.rf_multipole_ion_optics.runtime.design_profile --repo-root $repoRoot --project-id $ProjectId `
      --design-profile-id $DesignProfileId --output $profileResolution
    if($LASTEXITCODE-ne 0){throw 'Governed design profile resolution failed.'}
  }finally{Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue;Pop-Location}
  }
  $profile=Get-Content -LiteralPath $profileResolution -Raw -Encoding UTF8|ConvertFrom-Json
  $identity=$profile.profile.identity
  $registry=Join-Path $inputDir 'project_registry.json'
  $descriptor=Join-Path $inputDir 'project.json';$profiles=Join-Path $inputDir 'design_profiles.json'
  $request=Join-Path $inputDir 'multipole_design_request.json'
  $variables=Join-Path $inputDir 'design_variables.json';$envelope=Join-Path $inputDir 'optimization_envelope.json'
  $modeRegistry=$null;$modeId=$null
  Copy-Item -LiteralPath $profile.registry_path -Destination $registry
  Copy-Item -LiteralPath $profile.descriptor_path -Destination $descriptor
  Copy-Item -LiteralPath $profile.profiles_path -Destination $profiles
  if($null-ne$compiledRuntime){
    if($null-eq$profile.PSObject.Properties['input_definitions']){throw 'Compiled COMSOL runtime omits its resolved design input definitions.'}
    Write-RunJson -Path $request -Value $profile.input_definitions.design_request -Depth 100
    Write-RunJson -Path $variables -Value $profile.input_definitions.design_variables -Depth 100
    Write-RunJson -Path $envelope -Value $profile.input_definitions.optimization_envelope -Depth 100
  }else{
  Copy-Item -LiteralPath $profile.paths.design_request -Destination $request
  Copy-Item -LiteralPath $profile.paths.design_variables -Destination $variables
  Copy-Item -LiteralPath $profile.paths.optimization_envelope -Destination $envelope
  }
  if($profile.profile.PSObject.Properties.Name-contains'mode_id'){
    $modeId=[string]$profile.profile.mode_id
    if(-not($profile.paths.PSObject.Properties.Name-contains'operating_mode_registry')){
      throw 'Typed design profile is missing its resolved operating-mode registry path.'
    }
    $modeRegistry=Join-Path $inputDir 'operating_modes.json'
    if($null-ne$compiledRuntime){Write-RunJson -Path $modeRegistry -Value $profile.input_definitions.operating_mode_registry -Depth 100}
    else{Copy-Item -LiteralPath $profile.paths.operating_mode_registry -Destination $modeRegistry}
  }

  $resolved=Join-Path $inputDir 'multipole_resolved_design.json'
  if($null-ne$compiledRuntime){
    Write-RunJson -Path $resolved -Value $compiledRuntime.design_profile_resolution.resolved_design -Depth 100
  }else{
  Push-Location $codeRoot
  try{
    $env:PYTHONPATH=$codeRoot
    $compileArguments=@('-m','projects.rf_multipole_ion_optics.core.compile_design_request',
      '--request',$request,'--design-variables',$variables,
      '--optimization-envelope',$envelope,'--output',$resolved,
      '--provenance-root',$inputDir,'--project-id',$ProjectId,
      '--radial-order-n',([string][int]$identity.radial_order_n),
      '--electrode-count',([string][int]$identity.electrode_count))
    if($modeRegistry){
      $compileArguments+=@('--operating-mode-registry',$modeRegistry,'--mode-id',$modeId)
    }
    & $python @compileArguments
    if($LASTEXITCODE-ne 0){throw 'Governed multipole design compilation failed.'}
  }finally{Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue;Pop-Location}
  }
  $design=Get-Content -LiteralPath $resolved -Raw -Encoding UTF8|ConvertFrom-Json
  $resolvedHash=[string]$design.resolved_sha256
  $expectedResolvedHash=[string]$resolvedBudget.expected_run_parent_resolved_design_sha256
  if($expectedResolvedHash-and$resolvedHash-ne$expectedResolvedHash){
    throw "Compiled resolved design differs from the authorized run identity: expected=$expectedResolvedHash actual=$resolvedHash"
  }
  $fieldSamplingPlan=$null
  $fieldSamplePoints=$null
  if($StopStage-eq'field_solve'){
    $fieldSamplingPlan=Join-Path $inputDir 'stationary_field_sampling_plan.json'
    $fieldSamplePoints=Join-Path $inputDir 'stationary_field_sample_points.csv'
    Copy-Item -LiteralPath $fieldSamplingPlanInput -Destination $fieldSamplingPlan
    Push-Location $codeRoot
    try{
      $env:PYTHONPATH=$codeRoot
      & $python -m projects.rf_multipole_ion_optics.analysis.stationary_field_sampling generate `
        --resolved-design $resolved --sampling-plan $fieldSamplingPlan `
        --output $fieldSamplePoints
    }finally{Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue;Pop-Location}
    if($LASTEXITCODE-ne 0){throw 'Governed stationary-field sample generation failed.'}
    $fieldSamplePointCount=@(Import-Csv -LiteralPath $fieldSamplePoints).Count
    if($fieldSamplePointCount-ne[int64]$fieldPreregistration.field_sampling.expected_point_count){
      throw 'Generated stationary-field sample count differs from preregistration.'
    }
  }
  $axialTopology=[string]$design.axial_drive.topology
  $particleSource=Join-Path $inputDir 'particle_source.csv'
  Copy-Item -LiteralPath $particleSourceInput -Destination $particleSource
  $volumeSnapshotReceipt=$null;$volumeReceiptIdentity=$null
  if($null-ne$compiledRuntime-and$compiledRuntime.particle_source.PSObject.Properties.Name-contains'volume_snapshot_receipt'){
    $volumeBinding=$compiledRuntime.particle_source.volume_snapshot_receipt
    if($null-eq$volumeBinding-or-not($volumeBinding.PSObject.Properties.Name-contains'path')-or-not($volumeBinding.PSObject.Properties.Name-contains'sha256')){throw 'Resolved COMSOL volume receipt binding is invalid.'}
    $volumeSnapshotReceipt=Join-Path $inputDir 'particle_source_volume_snapshot_receipt.json'
    Copy-VerifiedRunInput -Source ([string]$volumeBinding.path) -Destination $volumeSnapshotReceipt -VerifiedIdentity ([ref]$volumeReceiptIdentity)|Out-Null
    if([string]$volumeReceiptIdentity.sha256-ne[string]$volumeBinding.sha256){throw 'Resolved COMSOL volume receipt differs from its frozen identity.'}
  }
  $sourceFamily=$null;$sourceFamilySha=$null
  if($sourceFamilyInput){
    $sourceFamily=Join-Path $inputDir 'particle_source_family.json'
    Copy-Item -LiteralPath $sourceFamilyInput -Destination $sourceFamily
    $sourceFamilySha=(Get-FileHash -LiteralPath $sourceFamily -Algorithm SHA256).Hash
  }
  $sourceMetadata=Join-Path $inputDir 'particle_source_metadata.json'
  Push-Location $codeRoot
  try{
    $env:PYTHONPATH=$codeRoot
    $preflightArguments=@('-m','projects.rf_multipole_ion_optics.runtime.particle_source_preflight',
      '--source',$particleSource,'--resolved-design',$resolved,'--output',$sourceMetadata,'--solver','comsol')
    if($sourceFamily){
      $preflightArguments+=@('--source-family',$sourceFamily,
        '--operating-point',$OperatingPointId,
        '--expected-source-family-sha256',$sourceFamilySha)
    }
    if($volumeSnapshotReceipt){$preflightArguments+=@('--volume-snapshot-receipt',$volumeSnapshotReceipt)}
    & $python @preflightArguments
    if($LASTEXITCODE-ne 0){throw 'Canonical particle source preflight failed.'}
  }finally{Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue;Pop-Location}
  $sourceMeta=Get-Content -LiteralPath $sourceMetadata -Raw -Encoding UTF8|ConvertFrom-Json
  if($sourceFamily){
    $binding=$sourceMeta.operating_point_binding
    if($null-eq$binding -or
      [string]$binding.operating_point_id-ne$OperatingPointId -or
      [string]$binding.source_family_sha256-ne$sourceFamilySha
    ){throw 'Canonical particle source operating-point binding differs from the frozen runner input.'}
  }elseif($null-ne$sourceMeta.operating_point_binding){
    throw 'Canonical particle source reported an unexpected operating-point binding.'
  }

  $numerics=Join-Path $inputDir 'solver_numerics.json'
  $solverNumericsDocument=[ordered]@{schema_version=1;role='multipole_comsol_solver_numerics';
    stationary_linear_solver_backend=$authorizedBackend;
    electric_potential_element_order=$authorizedElementOrder;
    mesh=$authorizedNumerics.mesh;
    trajectory=$authorizedNumerics.trajectory}
  if($authorizedBackend-eq'cg_amg'){
    $solverNumericsDocument.stationary_iterative_solver=$authorizedIterativeSolver
  }
  $solverNumericsDocument|
    ConvertTo-Json -Depth 5|Set-Content -LiteralPath $numerics -Encoding UTF8
  $evidence=$null
  if(-not[string]::IsNullOrWhiteSpace($EvidenceContractPath)){
    $evidence=Join-Path $inputDir 'evidence_contract.json'
    Copy-Item -LiteralPath ([IO.Path]::GetFullPath($EvidenceContractPath)) -Destination $evidence
  }

  $extractionScience=Join-Path $inputDir 'finite_extraction_science.json'
  $projectScience='import json,sys;from pathlib import Path;from projects.rf_multipole_ion_optics.runtime.finite_extraction_context import project_finite_extraction_science;read=lambda p:json.loads(Path(p).read_text(encoding="utf-8-sig"));Path(sys.argv[4]).write_text(json.dumps(project_finite_extraction_science(read(sys.argv[1]),read(sys.argv[2]),read(sys.argv[3])),allow_nan=False),encoding="utf-8")'
  Invoke-RunToolRootContext -RepoRoot $codeRoot -Operation {
    & $python -B -c $projectScience $resolved $numerics $sourceMetadata $extractionScience
    if($LASTEXITCODE-ne0){throw 'Frozen finite extraction science projection failed.'}
  }
  $events=Join-Path $resultDir 'particle_events.csv';$trajectories=Join-Path $resultDir 'trajectory_samples.csv'
  $metrics=Join-Path $resultDir 'finite_3d_transport_metrics.json'
  $pairedMetrics=Join-Path $resultDir 'paired_axial_drive_metrics.json'
  $plot=Join-Path $resultDir 'finite_3d_transport.png'
  $exitStatePlot=Join-Path $resultDir 'exit_state_diagnostics.png'
  $exitStatePlotManifest=Join-Path $resultDir 'exit_state_diagnostics.json'
  $model=Join-Path $resultDir 'finite_3d_transport.mph';$canonicalState=Join-Path $resultDir 'particle_state.csv'
  $primaryState=Join-Path $resultDir 'particle_state__primary.csv';$controlState=Join-Path $resultDir 'particle_state__control.csv'
  $primaryTrajectories=Join-Path $resultDir 'trajectory_samples__primary.csv'
  $controlTrajectories=Join-Path $resultDir 'trajectory_samples__control.csv'
  $report=Join-Path $logDir 'comsol_finite_3d_transport.txt';$evaluation=Join-Path $resultDir 'evidence_evaluation.json'
  $fieldSamples=Join-Path $resultDir 'stationary_field_samples.csv'
  $fieldSampleValidation=Join-Path $resultDir 'stationary_field_sample_validation.json'
  $task=Join-Path $codeRoot 'projects\rf_multipole_ion_optics\comsol\solve_finite_3d_transport.m'
  $configDocument=[ordered]@{schema_version=2;role='multipole_resolved_comsol_run_config';run_id=$RunId;project=$ProjectId;
    mode='resolved_design_transport';project_root=$profile.project_root;
    artifact_retention=[ordered]@{policy_version=1;class=$RetentionClass;
      reason=$(if($RetentionClass-eq'compact'){$null}else{$RetentionReason})};
    provenance=[ordered]@{parent_resolved_design_sha256=$resolvedHash;particle_source_sha256=$sourceMeta.source_sha256;
      source_family_sha256=$sourceFamilySha;volume_snapshot_receipt_origin=$(if($volumeSnapshotReceipt){$volumeBinding}else{$null});volume_snapshot_receipt_sha256=$(if($volumeReceiptIdentity){[string]$volumeReceiptIdentity.sha256}else{$null});operating_point_id=$(if($sourceFamily){$OperatingPointId}else{$null});
      particle_source_operating_point_binding=$sourceMeta.operating_point_binding};
    inputs=[ordered]@{project_registry=$registry;project_descriptor=$descriptor;design_profiles=$profiles;
      engineering_budget=$engineeringBudget;
      design_profile_resolution=$profileResolution;design_request=$request;design_variables=$variables;
      optimization_envelope=$envelope;operating_mode_registry=$modeRegistry;
      multipole_resolved_design=$resolved;particle_source=$particleSource;
      particle_source_metadata=$sourceMetadata;particle_source_family=$sourceFamily;particle_source_volume_snapshot_receipt=$volumeSnapshotReceipt;
      solver_numerics=$numerics;finite_extraction_science=$extractionScience;code_inventory=$codeInventory;
      evidence_contract=$evidence;stationary_field_sampling_plan=$fieldSamplingPlan;
      stationary_field_sample_points=$fieldSamplePoints;comsol_task=$task};
    parameters=[ordered]@{model_level='L3';runtime_profile_id=$RuntimeProfileId;design_profile_id=$DesignProfileId;
      operating_mode_id=$modeId;
      operating_point_id=$(if($sourceFamily){$OperatingPointId}else{$null});mesh_convergence=$false;
      stop_stage=$StopStage};
    formal_gate_passed=$false}
  foreach($key in @($configDocument.inputs.Keys)){
    if($configDocument.inputs[$key]-is[string]){$configDocument.inputs[$key]=Convert-WorkflowOwnerPath $ownerContext $configDocument.inputs[$key]}
  }
  # Scientific metadata must retain the lifecycle authority created by the package.
  $packageConfig=Get-Content -LiteralPath $package.run_config -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  $configDocument.capacity_ledger_lifecycle=$packageConfig.capacity_ledger_lifecycle
  $configDocument.paths=$package.path_context
  $configDocument.inputs.execution_request=$ownerContext.request_path
  Write-RunJson -Atomic -Path (Join-Path $ownerContext.run_directory 'run_config.json') -Value $configDocument -Depth 100

  $resourceUsage=Join-Path $resultDir 'resource_usage.json'
  $ownerState.usage_path=$resourceUsage
  $ownerState.launcher_receipt=Join-Path $logDir 'comsol_launcher_completion.json'
  $ownerState.phase_timings.prepare=$ownerState.timer.Elapsed.TotalSeconds
  $ownerState.phase='native';$nativeStart=$ownerState.timer.Elapsed.TotalSeconds
  try{
    $env:SIMULATION_PYTHON_EXE=$python
    $env:MULTIPOLE_FINITE_EXTRACTION_SCIENCE=$extractionScience
    $env:MULTIPOLE_RESOLVED_DESIGN=$resolved;$env:MULTIPOLE_SOLVER_NUMERICS=$numerics
    $env:MULTIPOLE_L3_PARTICLE_SOURCE=$particleSource;$env:MULTIPOLE_L3_PARTICLE_SOURCE_METADATA=$sourceMetadata
    $env:MULTIPOLE_L3_RUNTIME_DIR=$runtimeDir;$env:MULTIPOLE_L3_EVENTS=$events
    $env:MULTIPOLE_L3_TRAJECTORIES=$trajectories;$env:MULTIPOLE_L3_METRICS=$metrics
    $env:MULTIPOLE_L3_PLOT=$plot;$env:MULTIPOLE_L3_MODEL=$model;$env:MULTIPOLE_L3_CANONICAL_STATE=$canonicalState
    $env:MULTIPOLE_L3_PRIMARY_CANONICAL_STATE=$primaryState
    $env:MULTIPOLE_L3_CONTROL_CANONICAL_STATE=$controlState
    $env:MULTIPOLE_L3_PRIMARY_TRAJECTORIES=$primaryTrajectories
    $env:MULTIPOLE_L3_CONTROL_TRAJECTORIES=$controlTrajectories
    $env:MULTIPOLE_L3_SOLVER_PROGRESS_DIR=$solverProgressDir
    $env:MULTIPOLE_L3_STOP_STAGE=$StopStage
    $env:MULTIPOLE_L3_FIELD_SAMPLE_POINTS=if($fieldSamplePoints){$fieldSamplePoints}else{''}
    $env:MULTIPOLE_L3_FIELD_SAMPLES=if($StopStage-eq'field_solve'){$fieldSamples}else{''}
    $env:MULTIPOLE_L3_MAXIMUM_MESH_CELLS=if($null-ne$maximumMeshCells){[string]$maximumMeshCells}else{''}
    $pwsh=(Get-Process -Id $PID).Path
    if($ownerState.host_lease.inherited){
      # A child may inherit a heavy owner, but cannot release or upgrade someone else's light grant.
      Assert-HostResourceHeavyStage -Lease $ownerState.host_lease
    }else{
      Close-FiniteComsolStage -State $ownerState
    }
    try{
      $ownerState.native_attempted=$true
      $solverProcess=Invoke-ResourceBudgetedProcess -Limits $resolvedBudget.limits `
        -RunDir $runDir -UsagePath $resourceUsage -FilePath $pwsh -ArgumentList @(
          '-NoProfile','-NonInteractive','-File',(Join-Path $codeRoot 'common\comsol\run_comsol_r2025b.ps1'),
          '-TaskScript',$task,'-ReportPath',$report,'-StartupAttempts','1','-RunId',$RunId,'-CompletionPath',$ownerState.launcher_receipt)
      $ownerState.wrapper_observation=@{exit_confirmed=$true;returncode=[int]$solverProcess.exit_code;
        process_id=[int]$solverProcess.root_process_id;process_started_at_utc_ticks=[long]$solverProcess.root_process_started_at_utc_ticks}
    }catch{
      $data=$_.Exception.Data
      if($data.Contains('observed_process_exit_confirmed')-and$data.Contains('observed_process_returncode')-and
         $data.Contains('observed_process_id')-and$data.Contains('observed_process_started_at_utc_ticks')){
        $ownerState.wrapper_observation=@{exit_confirmed=$data['observed_process_exit_confirmed'];returncode=$data['observed_process_returncode'];
          process_id=$data['observed_process_id'];process_started_at_utc_ticks=$data['observed_process_started_at_utc_ticks']}
      }
      throw
    }
    try{$null=Get-FiniteComsolWriterCompletion -State $ownerState -RunId $RunId}
    catch{
      $proofFailure=$_
      if($solverProcess.resource_budget_exceeded-or$solverProcess.exit_code-ne0){
        $resourceBudgetExceeded=[bool]$solverProcess.resource_budget_exceeded
        $nativeReason=@(Get-Content -LiteralPath $report -Tail 60 -ErrorAction SilentlyContinue)-join "`n"
        $primaryMessage=if($resourceBudgetExceeded){'COMSOL resource budget exceeded.'}else{"COMSOL finite 3D multipole transport failed. Report=$report`n$nativeReason"}
        $primary=[InvalidOperationException]::new($primaryMessage)
        $primary.Data['writer_completion_error']=$proofFailure.Exception.Message
        throw $primary
      }
      throw
    }
    if($null-eq$ownerState.host_lease){$ownerState.host_lease=Enter-HostExecutionLease -StatePath $workspacePaths.host_resource_state_path -Role COMSOL -Stage postprocess -RunId $RunId}
    if($solverProcess.resource_budget_exceeded){
      $resourceBudgetExceeded=$true
      throw 'COMSOL resource budget exceeded.'
    }
    if($null-ne$maximumMeshCells){
      try{
        $meshCells=Assert-MultipoleMeshCellBudgetReport -Path $report `
          -MaximumMeshCells $maximumMeshCells
      }catch{
        if([string]$_.Exception.Data['limit_name']-eq'maximum_mesh_cells'){
          $resourceBudgetExceeded=$true
          $usage=Get-Content -LiteralPath $resourceUsage -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
          $usage.status='resource_budget_exceeded'
          $usage.failure_class='resource_budget_exceeded'
          $usage.limit_name='maximum_mesh_cells'
          $usage.mesh_cells=[int64]$_.Exception.Data['measured_value']
          Write-ResourceUsage -Usage $usage -Path $resourceUsage
        }
        throw
      }
    }
    if($solverProcess.exit_code-ne 0){
      $nativeReason=@(Get-Content -LiteralPath $report -Tail 60 -ErrorAction SilentlyContinue)-join "`n"
      throw "COMSOL finite 3D multipole transport failed. Report=$report`n$nativeReason"
    }
  }finally{$ownerState.phase_timings.native=$ownerState.timer.Elapsed.TotalSeconds-$nativeStart}
  $ownerState.phase='analysis';$analysisStart=$ownerState.timer.Elapsed.TotalSeconds
  if($StopStage-eq'mesh_build'){
    try{
      $expectedMeshStrategy='selected_region_free_tetrahedral'
      if($solverNumericsDocument.mesh.PSObject.Properties.Name-contains'strategy'){
        $expectedMeshStrategy=[string]$solverNumericsDocument.mesh.strategy
      }
      $meshCells=Assert-MultipoleMeshBuildReport -Path $report -ExpectedMeshStrategy $expectedMeshStrategy
    }catch{
      if([string]$_.Exception.Data['limit_name']-eq'maximum_mesh_cells'){
        $resourceBudgetExceeded=$true
        $usage=Get-Content -LiteralPath $resourceUsage -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
        $usage.status='resource_budget_exceeded'
        $usage.failure_class='resource_budget_exceeded'
        $usage.limit_name='maximum_mesh_cells'
        $usage.mesh_cells=[int64]$_.Exception.Data['measured_value']
        Write-ResourceUsage -Usage $usage -Path $resourceUsage
      }
      throw
    }
    $summaryDocument=[ordered]@{schema_version=1;role='multipole_finite_3d_transport_summary';status='success';
      qualification_status='UNQUALIFIED_MESH_BUILD_DIAGNOSTIC_ONLY';project_id=$ProjectId;
      design_profile_id=$DesignProfileId;parent_resolved_design_sha256=$resolvedHash;
      model_level='L3';stop_stage='mesh_build';field_physics_created=0;field_studies_created=0;
      field_solutions_created=0;particle_physics_created=0;particle_studies_created=0;
      formal_gate_passed=$false}
    if($null-ne$maximumMeshCells){
      $summaryDocument.mesh_cells=$meshCells
      $summaryDocument.maximum_mesh_cells=$maximumMeshCells
    }
    $summaryDocument|ConvertTo-Json -Depth 5|Set-Content -LiteralPath $summary -Encoding UTF8
    $outputs=@($report,$summary,$resourceUsage)|Where-Object{Test-Path -LiteralPath $_ -PathType Leaf}
    $outputs+=@(Get-ChildItem -LiteralPath $solverProgressDir -File|ForEach-Object{$_.FullName})
    $ownerState.phase_timings.analysis=$ownerState.timer.Elapsed.TotalSeconds-$analysisStart
    $summaryDocument=Get-Content -LiteralPath $summary -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
    $null=Complete-FiniteComsolOwner -Context $ownerContext -State $ownerState -RunId $RunId -Status success -Summary $summaryDocument -Outputs $outputs -Required @($report)
    $hostExecutionOutcome='success'
    Write-Output "MULTIPOLE_COMSOL_RESOLVED=PASS PROJECT=$ProjectId PROFILE=$DesignProfileId RUN_ID=$RunId STOP_STAGE=mesh_build QUALIFICATION=UNQUALIFIED"
    return
  }
  if($StopStage-eq'field_solve'){
    Push-Location $codeRoot
    try{
      $env:PYTHONPATH=$codeRoot
      & $python -m projects.rf_multipole_ion_optics.analysis.stationary_field_sampling validate `
        --input $fieldSamples --output $fieldSampleValidation
    }finally{Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue;Pop-Location}
    if($LASTEXITCODE-ne 0){throw 'COMSOL stationary-field sample validation failed.'}
    $fieldSampleValidationDocument=Get-Content -LiteralPath $fieldSampleValidation `
      -Raw -Encoding UTF8|ConvertFrom-Json
    if([string]$fieldSampleValidationDocument.status-ne'PASS'-or
      [int64]$fieldSampleValidationDocument.point_count-ne
        [int64]$fieldPreregistration.field_sampling.expected_point_count-or
      [int64]$fieldSampleValidationDocument.row_count-ne
        [int64]$fieldPreregistration.field_sampling.expected_row_count){
      throw 'COMSOL stationary-field sample validation differs from preregistration.'
    }
    $fieldSolve=Assert-MultipoleFieldSolveReport -Path $report
    $fieldReportContent=Get-Content -LiteralPath $report -Raw -Encoding UTF8
    foreach($token in $fieldPreregistration.required_report.tokens){
      if($fieldReportContent-notmatch("(?m)^$([regex]::Escape([string]$token))\r?$")){
        throw "COMSOL field-solve report is missing preregistered token: $token"
      }
    }
    foreach($checkpoint in $fieldPreregistration.required_report.forbidden_checkpoints){
      if($fieldReportContent-match("(?m)^$([regex]::Escape([string]$checkpoint))\r?$")){
        throw "COMSOL field-solve report contains forbidden checkpoint: $checkpoint"
      }
    }
    if($fieldSolve.stationary_linear_solver_backend-ne$authorizedBackend-or
      $fieldSolve.electric_potential_element_order-ne$authorizedElementOrder){
      throw 'COMSOL field-solve report differs from the authorized solver numerics.'
    }
    if($authorizedBackend-eq'cg_amg'){
      $actualConfiguration=$fieldSolve.stationary_solver_configuration
      if([double]$actualConfiguration.relative_tolerance-ne
          [double]$authorizedIterativeSolver.relative_tolerance-or
        [int64]$actualConfiguration.maximum_linear_iterations-ne
          [int64]$authorizedIterativeSolver.maximum_iterations-or
        [string]$actualConfiguration.linear_error_check-ne
          [string]$authorizedIterativeSolver.error_check_mode){
        throw 'COMSOL field-solve convergence settings differ from the authorized solver numerics.'
      }
    }
    $summaryDocument=[ordered]@{schema_version=1;role='multipole_finite_3d_transport_summary';status='success';
      qualification_status='UNQUALIFIED_FIELD_SOLVE_DIAGNOSTIC_ONLY';project_id=$ProjectId;
      design_profile_id=$DesignProfileId;parent_resolved_design_sha256=$resolvedHash;
      model_level='L3';stop_stage='field_solve';
      stationary_linear_solver_backend=$fieldSolve.stationary_linear_solver_backend;
      electric_potential_element_order=$fieldSolve.electric_potential_element_order;
      field_physics_created=$fieldSolve.field_physics_created;
      field_studies_created=$fieldSolve.field_studies_created;
      field_solutions_created=$fieldSolve.field_solutions_created;
      field_dof=$fieldSolve.field_dof;
      field_solver_evidence=$fieldSolve.field_solver_evidence;
      stationary_solver_configuration=$fieldSolve.stationary_solver_configuration;
      field_sample_point_count=[int64]$fieldSampleValidationDocument.point_count;
      field_sample_row_count=[int64]$fieldSampleValidationDocument.row_count;
      particle_physics_created=0;particle_studies_created=0;
      formal_gate_passed=$false}
    if($null-ne$maximumMeshCells){
      $summaryDocument.mesh_cells=$meshCells
      $summaryDocument.maximum_mesh_cells=$maximumMeshCells
    }
    $summaryDocument|ConvertTo-Json -Depth 5|Set-Content -LiteralPath $summary -Encoding UTF8
    $outputs=@($report,$summary,$resourceUsage,$fieldSamples,$fieldSampleValidation)|
      Where-Object{Test-Path -LiteralPath $_ -PathType Leaf}
    $outputs+=@(Get-ChildItem -LiteralPath $solverProgressDir -File|ForEach-Object{$_.FullName})
    $ownerState.phase_timings.analysis=$ownerState.timer.Elapsed.TotalSeconds-$analysisStart
    $summaryDocument=Get-Content -LiteralPath $summary -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
    $null=Complete-FiniteComsolOwner -Context $ownerContext -State $ownerState -RunId $RunId -Status success -Summary $summaryDocument -Outputs $outputs -Required @($report)
    $hostExecutionOutcome='success'
    Write-Output "MULTIPOLE_COMSOL_RESOLVED=PASS PROJECT=$ProjectId PROFILE=$DesignProfileId RUN_ID=$RunId STOP_STAGE=field_solve QUALIFICATION=UNQUALIFIED"
    return
  }
  $analysisNativeOutputs=@($events,$trajectories,$plot,$model,(Join-Path $resultDir 'release_source_mapping.json'),(Join-Path $resultDir 'finite_extraction_context.json'),
    $canonicalState,$resourceUsage,$primaryState,$controlState,$primaryTrajectories,$controlTrajectories,$report)
  $analysisNativeOutputs+=@(Get-ChildItem -LiteralPath $solverProgressDir -File|ForEach-Object FullName)
  Invoke-FiniteComsolAnalysis -OwnerContext $ownerContext -OwnerState $ownerState -RunId $RunId -ProjectId $ProjectId `
    -DesignProfileId $DesignProfileId -Python $python -RepoRoot $repoRoot -CodeRoot $codeRoot -Resolved $resolved `
    -Numerics $numerics -ParticleSource $particleSource -SourceMetadata $sourceMetadata -Events $events -PrimaryState $primaryState -ControlState $controlState -Evidence $evidence `
    -AxialTopology $axialTopology -ResolvedHash $resolvedHash -ResultDir $resultDir -Summary $summary -NativeOutputs $analysisNativeOutputs -Required @($report)
  $hostExecutionOutcome='success'

}catch{
  $comsolRunFailure=$_
  if($ownerState.phase-eq'analysis'){$ownerState.phase_timings.analysis=$ownerState.timer.Elapsed.TotalSeconds-$analysisStart}
  elseif($ownerState.phase-eq'prepare'){$ownerState.phase_timings.prepare=$ownerState.timer.Elapsed.TotalSeconds}
  if($null-ne$ownerContext-and($ownerContext.completion_written-or$ownerState.finalization_started)){throw $comsolRunFailure}
  $hostExecutionOutcome=if($resourceBudgetExceeded){'interrupted'}else{'failed'}
  if($null-ne$ownerContext){
    $failedSummary=[ordered]@{schema_version=1;role='multipole_finite_3d_transport_summary';failure_stage=$ownerState.phase;
      failure_reason=$comsolRunFailure.Exception.Message;recovery_action='inspect_failure';formal_gate_passed=$false}
    $failureOutputs=@(foreach($directory in @($resultDir,$logDir)){
      if(Test-Path -LiteralPath $directory){Get-ChildItem -LiteralPath $directory -Recurse -File|Select-Object -ExpandProperty FullName}
    })
    try{$null=Complete-FiniteComsolOwner -Context $ownerContext -State $ownerState -RunId $RunId -Status $hostExecutionOutcome -Summary $failedSummary -Outputs $failureOutputs -OriginalFailure $comsolRunFailure}
    catch{$comsolRunFailure.Exception.Data['failure_closure_error']=$_.Exception.Message;Write-Warning "COMSOL failure closure also failed: $($_.Exception.Message)"}
  }
  throw $comsolRunFailure
}finally{
  try{
    # Only uninitialized, never-started preparation needs local admission rollback.
    # Once initialized, the public owner exclusively handles terminal cleanup.
    if($null-eq$ownerContext-and-not$ownerState.native_attempted){
      try{Close-FiniteComsolStage -State $ownerState}finally{
        if($null-ne$capacity){Exit-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $capacity|Out-Null}
        if($null-ne$package){Remove-RunPackageExecutionAlias -Package $package}
      }
    }
  }catch{
    if($null-eq$comsolRunFailure){throw}
    $comsolRunFailure.Exception.Data['preparation_cleanup_error']=$_.Exception.Message
  }finally{Restore-RunEnvironment -Names $environmentNames -Snapshot $oldEnvironment}
}

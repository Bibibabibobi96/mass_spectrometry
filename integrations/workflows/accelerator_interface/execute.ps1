[CmdletBinding()]
param(
  [string]$ReferenceMrRunPath='',
  [ValidateSet('orthogonal_accelerator','dual_pressure_rectilinear_ion_processor')]
  [string]$AcceleratorProvider='orthogonal_accelerator',
  [string]$IonProcessorRunPath='',
  [string]$MultipoleIpRequestPath='',
  [string]$MultipoleIpRunId='',
  [string]$IonProcessorRunId='',
  [string]$IonProcessorConfigurationDirectory='',
  [string]$IonProcessorFieldRunPath='',
  [switch]$ContinueOnIpScientificFailure,
  [switch]$FinalizeJointWorkbench,
  [string]$PreparedInterfaceRunPath='',
  [string]$JointFieldRunPath='',
  [string]$ContractPath='',
  [string]$MatchingRequestPath='',
  [switch]$FullJoint,
  [switch]$ResumeFinalization,
  [string]$ResultPath='',
  [string]$FieldRequestPath='',
  [string]$ContinuationPredecessorManifestPath='',
  [string]$PreparedJointWorkbenchRunPath='',
  [string]$SimionExe='',
  [string]$RunId='',
  [string]$LuaExe='',
  [string]$PythonExe='',
  [string]$RepoRoot=(Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)))
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
function New-AcceleratorInterfaceRunId {
  param([Parameter(Mandatory)][string]$Provider)
  $slug=if($Provider-eq'orthogonal_accelerator'){'oa'}else{'ip'}
  return (Get-Date -Format 'yyyyMMdd_HHmmss')+'__analysis__python__accelerator-interface-'+$slug+'-'+[guid]::NewGuid().ToString('N').Substring(0,8)
}
$projectId='instrument_assembly'
$software=@('Python 3.11')
$repoRoot=(Resolve-Path -LiteralPath $RepoRoot).Path
$script:pythonRoot=$repoRoot
. (Join-Path $repoRoot 'common/require_powershell7.ps1')
. (Join-Path $repoRoot 'integrations/runtime/dependencies.ps1')
$workspaceRoot=Split-Path -Parent $repoRoot
. (Join-Path $repoRoot 'common/contracts/run_artifact_support.ps1')
$python=if($PythonExe){(Resolve-Path -LiteralPath $PythonExe).Path}else{Join-Path $repoRoot '.venv/Scripts/python.exe'}
function Invoke-JointOwnerStage {
  param([string]$Script,[hashtable]$Arguments)
  $watch=[Diagnostics.Stopwatch]::StartNew()
  try{& $Script @Arguments}
  finally{Write-Output ("JOINT_STAGE OWNER={0} ELAPSED_SECONDS={1:F3}" -f $Script,$watch.Elapsed.TotalSeconds)}
}
function Get-JointDesignReceipt {
  param([string]$Run)
  $path=Invoke-RunToolRootContext -RepoRoot $repoRoot -Operation {
    & $python -B -c 'import sys;from pathlib import Path;from integrations.workflows.accelerator_interface.prepare import verified_preparation_reference;print(verified_preparation_reference(Path(sys.argv[1]),"results/accelerator_interface_preparation.json"))' $Run
    if($LASTEXITCODE-ne0){throw 'Design preparation receipt failed its owner and manifest validation.'}
  }
  return Get-Content -LiteralPath ($path|Select-Object -Last 1) -Raw|ConvertFrom-Json -AsHashtable
}
function Get-MultipoleIpPreparation {
  param([string]$Run,[string]$ConfigurationDirectory)
  # Check the published handoff and the actual receiver geometry before any IP
  # native work. The project owns its geometry projection and coordinate map.
  $code=@'
import json, sys
from pathlib import Path
from common.contracts.verify_run_manifest import verified_successful_run_reference, verify_record, record_path
from projects.dual_pressure_rectilinear_ion_processor.analysis.native_geometry import native_projection
from projects.dual_pressure_rectilinear_ion_processor.analysis.coordinates import transform_from_config
run, config = map(Path, sys.argv[1:])
path = verified_successful_run_reference(run, 'results/multipole_ip/preparation_receipt.json', project='instrument_assembly', mode='multipole_ip_preparation')
receipt = json.loads(path.read_text(encoding='utf-8-sig'))
if receipt.get('role') != 'multipole_ip_preparation' or receipt.get('status') != 'success':
    raise ValueError('MP-to-IP preparation receipt is not complete')
verify_record('receiver model', receipt['receiver_model'], base_dir=run)
model = json.loads(record_path(receipt['receiver_model'], base_dir=run).read_text(encoding='utf-8-sig'))
candidate = {name: json.loads((config / (name + '.json')).read_text(encoding='utf-8-sig')) for name in ('baseline', 'numerics', 'coordinate_transform')}
if native_projection(model['baseline'], model['numerics']) != native_projection(candidate['baseline'], candidate['numerics']) or transform_from_config(model) != transform_from_config(candidate):
    raise ValueError('IP configuration geometry/frame differs from the frozen MP-to-IP receiver')
source = verified_successful_run_reference(run, 'results/multipole_ip/ip_injected_source.json', project='instrument_assembly', mode='multipole_ip_preparation')
if record_path(receipt['injected_source'], base_dir=run) != source:
    raise ValueError('MP-to-IP source differs from its preparation receipt')
verify_record('injected source', receipt['injected_source'], base_dir=run)
print(json.dumps(receipt))
'@
  $output=Invoke-RunToolRootContext -RepoRoot $repoRoot -Operation {
    & $python -B -c $code $Run $ConfigurationDirectory
    if($LASTEXITCODE-ne0){throw 'MP-to-IP preparation or receiver configuration failed validation.'}
  }
  return (($output -join "`n")|ConvertFrom-Json -AsHashtable)
}
function Assert-CompletedIpScientificFailure {
  param([string]$Run)
  $code=@'
import json, sys
from pathlib import Path
from projects.dual_pressure_rectilinear_ion_processor.analysis.component_exit import load_component_source
summary, _, _ = load_component_source(Path(sys.argv[1]).resolve())
if not (summary.get('status') == 'failed' and summary.get('execution_status') == 'completed' and summary.get('data_validity') == 'valid' and summary.get('science_status') == 'not_passed' and summary.get('analysis_exit_code') == 2 and summary.get('native_completed') is True and summary.get('diagnostics_complete') is True):
    raise ValueError('IP failure lacks completed native and analysis evidence')
print(json.dumps(summary))
'@
  $output=Invoke-RunToolRootContext -RepoRoot $repoRoot -Operation {
    & $python -B -c $code $Run
    if($LASTEXITCODE-ne0){throw 'IP failure is not a verified completed scientific negative result.'}
  }
  return (($output -join "`n")|ConvertFrom-Json -AsHashtable)
}
function Assert-JointFieldRunId {
  param([string]$Id)
  Invoke-RunToolRootContext -RepoRoot $repoRoot -Operation {
    & $python -B -m common.contracts.artifact_naming run $Id|Out-Null
    if($LASTEXITCODE-ne0){throw "Run ID '$Id' does not satisfy the repository run naming contract."}
  }
}
function Get-JointSourceStart {
  param([hashtable]$ExitReceipt)
  if(-not$ExitReceipt.ContainsKey('inputs')-or$null-eq$ExitReceipt.inputs){return 'unknown'}
  if($ExitReceipt.inputs.ContainsKey('inputs/injected_source.json')){return 'upstream_injected_population'}
  if($ExitReceipt.inputs.ContainsKey('inputs/release.csv')){return 'ip_local_release'}
  return 'unknown'
}
function Write-FullJointFailure {
  param([string]$Stage,[string]$Flight,[string]$Reason,[double]$Elapsed)
  $recovery='inspect_stage_owner_result';$summaryPath=Join-Path $Flight 'summary.json'
  if(Test-Path -LiteralPath $summaryPath -PathType Leaf){
    try{
      $summary=Get-Content -LiteralPath $summaryPath -Raw|ConvertFrom-Json -AsHashtable
      if($summary.ContainsKey('failure_stage')){$Stage=[string]$summary.failure_stage}
      if($summary.ContainsKey('reason')){$Reason=[string]$summary.reason}
      if($Stage-eq'automatic_joint_diagnostics'){$recovery='use_prepared_joint_analysis_without_fly'}
      elseif($summary.status-eq'success'){$recovery='inspect_published_result_and_capacity_sealing'}
      else{$recovery='inspect_flight_summary_and_use_prepared_joint_owner'}
    }catch{Write-Warning 'Flight summary could not be read; original failure retained.'}
  }
  Write-Error ("FULL_JOINT=FAILED STAGE={0} DATA_VALIDITY=unknown SCIENCE=unknown FLIGHT={1} RECOVERY={2} TOTAL_SECONDS={3:F3} REASON={4}" -f $Stage,$Flight,$recovery,$Elapsed,$Reason) -ErrorAction Continue
}
function Write-FullJointFlightResult {
  param([string]$Workbench,[string]$Flight,[double]$Elapsed)
  $summary=Get-Content -LiteralPath (Join-Path $Flight 'summary.json') -Raw|ConvertFrom-Json -AsHashtable
  if($summary.status-ne'success'){throw 'Prepared joint owner did not publish a successful flight summary.'}
  $validity='unknown';$counts='unknown';$peak='unknown';$source='unknown';$scope='unknown'
  $diagnosticPath=Join-Path $summary.diagnostics 'diagnostics_receipt.json'
  if(Test-Path -LiteralPath $diagnosticPath -PathType Leaf){
    $diagnostic=Get-Content -LiteralPath $diagnosticPath -Raw|ConvertFrom-Json -AsHashtable
    if($diagnostic.status-eq'complete_recorded_diagnostics'){
      $validity='recorded_diagnostics_complete';$counts=($diagnostic.counts|ConvertTo-Json -Compress -Depth 10)
      if($diagnostic.ContainsKey('detector_peak')){$peak=($diagnostic.detector_peak|ConvertTo-Json -Compress -Depth 20)}
    }
  }
  $exitPath=Join-Path $Workbench 'results/ion_processor_exit/component_exit_receipt.json'
  if(Test-Path -LiteralPath $exitPath -PathType Leaf){$source=Get-JointSourceStart -ExitReceipt (Get-Content -LiteralPath $exitPath -Raw|ConvertFrom-Json -AsHashtable)}
  $bindingPath=Join-Path $Workbench 'results/joint_workbench/static_field_binding.json'
  if(Test-Path -LiteralPath $bindingPath -PathType Leaf){
    $binding=Get-Content -LiteralPath $bindingPath -Raw|ConvertFrom-Json -AsHashtable
    if($binding.ContainsKey('parent')-and$binding.parent.ContainsKey('grid')-and$binding.ContainsKey('refinement_windows')){
      $windows=@($binding.refinement_windows|ForEach-Object{@{name=$_.name;grid=$_.grid;active_box_mm=$_.active_box_mm}})
      $scope=(@{parent_grid=$binding.parent.grid;windows=$windows}|ConvertTo-Json -Compress -Depth 20)
    }
  }
  Write-Output ("FULL_JOINT EXECUTION=success DATA_VALIDITY={0} SCIENCE=not_qualified SOURCE={1} HANDOFF=state FIELD_SCOPE={2} COUNTS={3} DETECTOR_PEAK={4} NATIVE_BATCHES={5} REUSED_BATCHES={6} WORKBENCH={7} RESULT={8} DIAGNOSTICS={9} RECOVERY=none TOTAL_SECONDS={10:F3}" -f $validity,$source,$scope,$counts,$peak,$summary.actual_native_batch_count,$summary.reused_batch_count,$Workbench,$Flight,$summary.diagnostics,$Elapsed)
}
function Invoke-JointAnalysisPreflight {
  param([string]$Design,[string]$Source,[string]$Contract)
  Invoke-RunToolRootContext -RepoRoot $repoRoot -Operation {
    & $python -B -c 'import sys;from pathlib import Path;from integrations.workflows.accelerator_interface.prepare import preflight_joint_analysis;preflight_joint_analysis(*map(Path,sys.argv[1:]))' $Design $Source $Contract
    if($LASTEXITCODE-ne 0){throw "Joint analysis preflight failed (exit $LASTEXITCODE)."}
  }
}
function Invoke-FullJoint {
  $totalWatch=[Diagnostics.Stopwatch]::StartNew()
  if($PreparedJointWorkbenchRunPath){
    if(-not$ContractPath-or$FinalizeJointWorkbench-or$PreparedInterfaceRunPath-or$JointFieldRunPath-or$MatchingRequestPath-or$FieldRequestPath-or$MultipoleIpRequestPath-or$MultipoleIpRunId-or$IonProcessorRunId-or$IonProcessorConfigurationDirectory-or$IonProcessorFieldRunPath-or$ContinueOnIpScientificFailure){
      throw 'A prepared workbench requires ContractPath and cannot be combined with design or field inputs.'
    }
    $workbench=(Resolve-Path -LiteralPath $PreparedJointWorkbenchRunPath).Path
    $flightId=if($RunId){$RunId}else{(Get-Date -Format 'yyyyMMdd_HHmmss')+'__sim__simion__ip-mr-joint-'+[guid]::NewGuid().ToString('N').Substring(0,8)}
    $flightRun=Join-Path $workspaceRoot "artifacts/projects/instrument_assembly/runs/$flightId"
    $flight=@{PreparedJointWorkbenchRunPath=$workbench;ContractPath=$ContractPath;RunId=$flightId;RepoRoot=$repoRoot}
    if($ResultPath){$flight.ResultPath=$ResultPath}
    if($PythonExe){$flight.PythonExe=$PythonExe};if($SimionExe){$flight.SimionExe=$SimionExe}
    if($ContinuationPredecessorManifestPath){$flight.ContinuationPredecessorManifestPath=$ContinuationPredecessorManifestPath}
    try{
      Invoke-JointOwnerStage -Script (Join-Path $repoRoot 'integrations/workflows/prepared_joint/execute.ps1') -Arguments $flight
      Write-FullJointFlightResult -Workbench $workbench -Flight $flightRun -Elapsed $totalWatch.Elapsed.TotalSeconds
    }catch{
      Write-FullJointFailure -Stage 'flight_and_analysis' -Flight $flightRun -Reason $_.Exception.Message -Elapsed $totalWatch.Elapsed.TotalSeconds
      throw
    }
    return
  }
  if($AcceleratorProvider-ne'dual_pressure_rectilinear_ion_processor'-or-not$ReferenceMrRunPath-or-not$ContractPath){
    throw 'FullJoint requires IP provider, MR reference and observation contract.'
  }
  if($MultipoleIpRequestPath){
    if($IonProcessorRunPath-or-not$MultipoleIpRunId-or-not$IonProcessorRunId-or-not$IonProcessorConfigurationDirectory){
      throw 'MP-to-IP source requires explicit preparation and IP run IDs and IP configuration, without an existing IP run.'
    }
    Assert-JointFieldRunId -Id $MultipoleIpRunId
    Assert-JointFieldRunId -Id $IonProcessorRunId
  }elseif(-not$IonProcessorRunPath-or$MultipoleIpRunId-or$IonProcessorRunId-or$IonProcessorConfigurationDirectory-or$IonProcessorFieldRunPath-or$ContinueOnIpScientificFailure){
    throw 'FullJoint requires an existing IP source or an explicit MP-to-IP request and its source options.'
  }
  if($FinalizeJointWorkbench-or($JointFieldRunPath-and-not$PreparedInterfaceRunPath)-or
     ($PreparedInterfaceRunPath-and$MatchingRequestPath)-or($JointFieldRunPath-and$FieldRequestPath)){
    throw 'FullJoint accepts either an existing design or matching request, and either an existing field or field request.'
  }
  if(-not$PreparedInterfaceRunPath-and-not$MatchingRequestPath){throw 'FullJoint requires an existing design or matching request.'}
  if(-not$JointFieldRunPath-and-not$FieldRequestPath){throw 'FullJoint requires an existing field or field request.'}
  $fieldRequest=$null;$fieldId=''
  if($FieldRequestPath){
    $fieldTemplate=(Resolve-Path -LiteralPath $FieldRequestPath).Path
    $fieldRequest=Get-Content -LiteralPath $fieldTemplate -Raw|ConvertFrom-Json -AsHashtable
    $fieldId=[string]$fieldRequest.run_id
    if(-not$fieldId-or$fieldId-in@('.','..')-or$fieldId-match'[/\\]'){throw 'Field request requires a safe new run_id.'}
    Assert-JointFieldRunId -Id $fieldId
  }
  $designId=if($RunId){$RunId}else{New-AcceleratorInterfaceRunId -Provider $AcceleratorProvider}
  $designRun=if($PreparedInterfaceRunPath){(Resolve-Path -LiteralPath $PreparedInterfaceRunPath).Path}else{Join-Path $workspaceRoot "artifacts/projects/instrument_assembly/runs/$designId"}
  $fieldRun=if($JointFieldRunPath){(Resolve-Path -LiteralPath $JointFieldRunPath).Path}else{Join-Path $workspaceRoot "artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/$fieldId"}
  $finalId=New-AcceleratorInterfaceRunId -Provider $AcceleratorProvider
  $finalRun=Join-Path $workspaceRoot "artifacts/projects/instrument_assembly/runs/$finalId"
  $flightId=(Get-Date -Format 'yyyyMMdd_HHmmss')+'__sim__simion__ip-mr-joint-'+[guid]::NewGuid().ToString('N').Substring(0,8)
  $flightRun=Join-Path $workspaceRoot "artifacts/projects/instrument_assembly/runs/$flightId"
  $common=@{ReferenceMrRunPath=$ReferenceMrRunPath;AcceleratorProvider=$AcceleratorProvider;IonProcessorRunPath=$IonProcessorRunPath;RepoRoot=$repoRoot}
  if($LuaExe){$common.LuaExe=$LuaExe};if($PythonExe){$common.PythonExe=$PythonExe};if($SimionExe){$common.SimionExe=$SimionExe}
  $stage='design';$temporary=$null
  try {
    if($MultipoleIpRequestPath){
      $stage='multipole_ip_preparation'
      $sourceRequest=(Resolve-Path -LiteralPath $MultipoleIpRequestPath).Path
      $ipConfiguration=(Resolve-Path -LiteralPath $IonProcessorConfigurationDirectory).Path
      $sourceRun=Join-Path $workspaceRoot "artifacts/projects/instrument_assembly/runs/$MultipoleIpRunId"
      $sourceArguments=@{Request=$sourceRequest;RunId=$MultipoleIpRunId;RepoRoot=$repoRoot}
      if($PythonExe){$sourceArguments.PythonExe=$PythonExe}
      Invoke-JointOwnerStage -Script (Join-Path $repoRoot 'integrations/workflows/multipole_ip/execute.ps1') -Arguments $sourceArguments
      $sourceReceipt=Get-MultipoleIpPreparation -Run $sourceRun -ConfigurationDirectory $ipConfiguration
      if([int]$sourceReceipt.exit_count-eq0){
        Write-Output ("FULL_JOINT=ZERO_EXIT EXECUTION=success DATA_VALIDITY=valid SCIENCE=not_qualified SOURCE_RUN={0} SOURCE_CASE={1} SOURCE_PREPARATION={2} MOTHER={3} TRANSFERRED=0 IP_FLY=False MR_FIELD=False MR_FLY=False RECOVERY=none TOTAL_SECONDS={4:F3}" -f $sourceReceipt.source.run_id,$sourceReceipt.source.case_id,$sourceRun,$sourceReceipt.mother_count,$totalWatch.Elapsed.TotalSeconds)
        return
      }
      $stage='ion_processor_flight'
      $IonProcessorRunPath=Join-Path $workspaceRoot "artifacts/projects/dual_pressure_rectilinear_ion_processor/runs/$IonProcessorRunId"
      $ipArguments=@{RunId=$IonProcessorRunId;InjectedSource=(Join-Path $sourceRun 'results/multipole_ip/ip_injected_source.json');ConfigurationDirectory=$ipConfiguration}
      if($SimionExe){$ipArguments.SimionExe=$SimionExe}
      if($IonProcessorFieldRunPath){$ipArguments.NativeFieldRun=(Resolve-Path -LiteralPath $IonProcessorFieldRunPath).Path}
      try {Invoke-JointOwnerStage -Script (Join-Path $repoRoot 'projects/dual_pressure_rectilinear_ion_processor/simion/run_functional.ps1') -Arguments $ipArguments}
      catch {
        $ipFailure=$_
        if(-not$ContinueOnIpScientificFailure-or$ipFailure.Exception.Message-cne'Analysis or required diagnostics incomplete; see frozen summary and logs'){throw $ipFailure}
        try {$ipSummary=Assert-CompletedIpScientificFailure -Run $IonProcessorRunPath}
        catch {$ipFailure.Exception.Data['ip_source_verification_error']=$_.Exception.Message;throw $ipFailure}
        Write-Output "FULL_JOINT_IP_SCIENCE=not_passed IP_RUN=$IonProcessorRunPath ORIGINAL_ERROR=$($ipFailure.Exception.Message)"
      }
      $common.IonProcessorRunPath=$IonProcessorRunPath
      Write-Output "FULL_JOINT_SOURCE RUN=$($sourceReceipt.source.run_id) CASE=$($sourceReceipt.source.case_id) PREPARATION=$sourceRun IP_RUN=$IonProcessorRunPath HANDOFF=state"
    }
    $stage='design'
    if(-not$PreparedInterfaceRunPath){Invoke-JointOwnerStage -Script $PSCommandPath -Arguments ($common+@{MatchingRequestPath=$MatchingRequestPath;RunId=$designId})}
    $manifest=Join-Path $designRun 'run_manifest.json'
    $assembly=Join-Path $designRun 'results/joint_flight/assembly/assembly_preparation.json'
    $designReceipt=Join-Path $designRun 'results/accelerator_interface_preparation.json'
    if(-not(Test-Path -LiteralPath $manifest -PathType Leaf)-or-not(Test-Path -LiteralPath $designReceipt -PathType Leaf)){throw 'Design owner did not publish its manifest and preparation receipt.'}
    $designResult=Get-JointDesignReceipt -Run $designRun
    if($designResult.status-eq'zero_exit'){
      $counts=$designResult.source_exit.counts
      $source=Get-JointSourceStart -ExitReceipt $designResult.source_exit
      $producer='unknown'
      if($designResult.source_exit.ContainsKey('producer_result')){$producer=($designResult.source_exit.producer_result|ConvertTo-Json -Compress -Depth 10)}
      Write-Output ("FULL_JOINT=ZERO_EXIT EXECUTION=success DATA_VALIDITY=valid SCIENCE=not_qualified SOURCE={0} HANDOFF=none PRODUCER_RESULT={1} DESIGN={2} MOTHER={3} TRANSFERRED=0 NOT_TRANSFERRED={4} MR_FIELD=False FLY=False RECOVERY=none TOTAL_SECONDS={5:F3}" -f $source,$producer,$designRun,$counts.source,$counts.not_transferred,$totalWatch.Elapsed.TotalSeconds)
      return
    }
    if($designResult.status-ne'prepared'){throw 'Design receipt is not an interface design preparation.'}
    if(-not(Test-Path -LiteralPath $assembly -PathType Leaf)){throw 'Design owner did not publish its assembly receipt.'}
    $stage='analysis_preflight'
    Invoke-JointAnalysisPreflight -Design $designRun -Source $IonProcessorRunPath -Contract $ContractPath
    $stage='field'
    if(-not$JointFieldRunPath){
      $fieldRequest.replacement_assembly_path=$assembly
      $fieldRequest.replacement_assembly_manifest=$manifest
      $temporary=Join-Path ([IO.Path]::GetTempPath()) ('ip-mr-field-'+[guid]::NewGuid().ToString('N')+'.json')
      $fieldRequest|ConvertTo-Json -Depth 100|Set-Content -LiteralPath $temporary -Encoding utf8
      Invoke-JointOwnerStage -Script (Join-Path $repoRoot 'projects/parallel_mirror_dual_stripe_mr_tof/simion/run_native_static_field_provider.ps1') -Arguments @{RequestPath=$temporary;RunDirectory=$fieldRun;Approved=$true;PythonExe=$python}
    }
    if(-not(Test-Path -LiteralPath (Join-Path $fieldRun 'run_manifest.json') -PathType Leaf)){throw 'Field owner did not publish its manifest.'}
    $stage='binding'
    Invoke-JointOwnerStage -Script $PSCommandPath -Arguments ($common+@{FinalizeJointWorkbench=$true;PreparedInterfaceRunPath=$designRun;JointFieldRunPath=$fieldRun;ContractPath=$ContractPath;RunId=$finalId})
    if(-not(Test-Path -LiteralPath (Join-Path $finalRun 'run_manifest.json') -PathType Leaf)){throw 'Workbench owner did not publish its manifest.'}
    $stage='flight_and_analysis'
    $flight=@{PreparedJointWorkbenchRunPath=$finalRun;ContractPath=$ContractPath;RunId=$flightId;RepoRoot=$repoRoot}
    if($ResultPath){$flight.ResultPath=$ResultPath}
    if($PythonExe){$flight.PythonExe=$PythonExe};if($SimionExe){$flight.SimionExe=$SimionExe}
    if($ContinuationPredecessorManifestPath){$flight.ContinuationPredecessorManifestPath=$ContinuationPredecessorManifestPath}
    Invoke-JointOwnerStage -Script (Join-Path $repoRoot 'integrations/workflows/prepared_joint/execute.ps1') -Arguments $flight
    Write-Output "FULL_JOINT_INPUTS DESIGN=$designRun FIELD=$fieldRun"
    Write-FullJointFlightResult -Workbench $finalRun -Flight $flightRun -Elapsed $totalWatch.Elapsed.TotalSeconds
  }catch{
    Write-Output "FULL_JOINT_INPUTS DESIGN=$designRun FIELD=$fieldRun WORKBENCH=$finalRun"
    Write-FullJointFailure -Stage $stage -Flight $flightRun -Reason $_.Exception.Message -Elapsed $totalWatch.Elapsed.TotalSeconds
    throw
  }finally{if($temporary-and(Test-Path -LiteralPath $temporary)){Remove-Item -LiteralPath $temporary}}
}
if($ResumeFinalization){
  if(-not$FullJoint-or-not$RunId){throw 'ResumeFinalization requires FullJoint and the existing flight RunId.'}
  $allowed=@('ResumeFinalization','FullJoint','RunId','ResultPath','PythonExe','RepoRoot')
  if(@($PSBoundParameters.Keys|Where-Object{$_-notin$allowed}).Count){throw 'Finalization recovery consumes the frozen run; omit scientific and native execution options.'}
  $recovery=@{ResumeFinalization=$true;RunId=$RunId;RepoRoot=$repoRoot}
  if($ResultPath){$recovery.ResultPath=$ResultPath}
  if($PythonExe){$recovery.PythonExe=$PythonExe}
  Invoke-JointOwnerStage -Script (Join-Path $repoRoot 'integrations/workflows/prepared_joint/execute.ps1') -Arguments $recovery
  return
}
if($ResultPath-and-not$FullJoint){throw 'ResultPath requires FullJoint.'}
if($FullJoint){Invoke-FullJoint;return}
if($FieldRequestPath){throw 'FieldRequestPath requires FullJoint.'}
if($ContinuationPredecessorManifestPath){throw 'ContinuationPredecessorManifestPath requires FullJoint.'}
if($PreparedJointWorkbenchRunPath){throw 'PreparedJointWorkbenchRunPath requires FullJoint.'}
if($MultipoleIpRequestPath-or$MultipoleIpRunId-or$IonProcessorRunId-or$IonProcessorConfigurationDirectory-or$IonProcessorFieldRunPath-or$ContinueOnIpScientificFailure){throw 'MP-to-IP source options require FullJoint.'}
if(-not$ReferenceMrRunPath){throw 'ReferenceMrRunPath is required for interface preparation.'}
$reference=(Resolve-Path -LiteralPath $ReferenceMrRunPath).Path
if($AcceleratorProvider-eq'dual_pressure_rectilinear_ion_processor'-and-not$IonProcessorRunPath){
  throw 'Ion processor selection requires an explicit source run.'
}
if($AcceleratorProvider-eq'dual_pressure_rectilinear_ion_processor'-and-not$FinalizeJointWorkbench-and-not$MatchingRequestPath){
  throw 'IP preparation requires an explicit MatchingRequestPath.'
}
if($FinalizeJointWorkbench-and($AcceleratorProvider-ne'dual_pressure_rectilinear_ion_processor'-or-not$PreparedInterfaceRunPath-or-not$JointFieldRunPath)){
  throw 'Joint workbench finalization requires explicit IP provider, design and new field runs.'
}
if(-not$FinalizeJointWorkbench-and($PreparedInterfaceRunPath-or$JointFieldRunPath)){throw 'Design/field run arguments require FinalizeJointWorkbench.'}
if($ContractPath-and-not$FinalizeJointWorkbench){throw 'ContractPath requires FinalizeJointWorkbench.'}
if($MatchingRequestPath-and($FinalizeJointWorkbench-or$AcceleratorProvider-ne'dual_pressure_rectilinear_ion_processor')){
  throw 'MatchingRequestPath selects an IP design request; finalization consumes the design-frozen request.'
}
$executionContract=if($ContractPath){(Resolve-Path -LiteralPath $ContractPath).Path}else{''}
$designRun=if($PreparedInterfaceRunPath){(Resolve-Path -LiteralPath $PreparedInterfaceRunPath).Path}else{''}
$fieldRun=if($JointFieldRunPath){(Resolve-Path -LiteralPath $JointFieldRunPath).Path}else{''}
$sourceRun=if($IonProcessorRunPath){(Resolve-Path -LiteralPath $IonProcessorRunPath).Path}else{''}
if($AcceleratorProvider-eq'dual_pressure_rectilinear_ion_processor'){
  if(-not$LuaExe){$LuaExe=Join-Path $env:ProgramFiles 'SIMION-2020/lua.exe'}
  $LuaExe=(Resolve-Path -LiteralPath $LuaExe).Path
  $software+=@('Plain Lua (SIMION 2020 bundled interpreter; no solver)')
}
if($FinalizeJointWorkbench){
  if(-not$SimionExe){$SimionExe=Join-Path $env:ProgramFiles 'SIMION-2020/simion.exe'}
  $SimionExe=(Resolve-Path -LiteralPath $SimionExe).Path
  $software+=@('SIMION 2020 IOB assembly only; no Refine or Fly')
}
if(-not$RunId){$RunId=New-AcceleratorInterfaceRunId -Provider $AcceleratorProvider}
$package=New-RunPackage -Python $python -RepoRoot $repoRoot `
  -ArtifactRoot (Join-Path $workspaceRoot "artifacts/projects/$projectId") `
  -RunId $RunId -Project $projectId -Mode accelerator_interface_preparation `
  -Software $software -RetentionContractEnabled -RetentionClass compact -CapacityLedgerLifecycleEnabled
$terminalized=$false
$capacitySession=$null
$lease=$null
$paGuards=[Collections.Generic.List[IO.FileStream]]::new()
$extraOutputs=@()
$stage='capacity_startup'
try{
  # One frozen PA template plus up to five temporary hard-linked companions
  # count toward the logical-file peak; no field PA or samples are copied.
  $protected=@($package.artifact_run_dir,$reference)
  if($sourceRun){$protected+=@($sourceRun)}
  if($designRun){$protected+=@($designRun)}
  if($fieldRun){$protected+=@($fieldRun)}
  $capacitySession=Enter-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot `
    -ArtifactRoot (Join-Path $workspaceRoot 'artifacts') -RunDirectory $package.artifact_run_dir `
    -CommittedNewBytes 134217728 -ProtectedPaths $protected -Owner "instrument-assembly-accelerator-interface:$RunId"
  $startup=Join-Path $package.result_dir 'artifact_capacity_gate_startup.json'
  Write-RunJson -Path $startup -Depth 14 -Value $capacitySession
  $stage='freeze_executable_dependencies'
  $dependencyPath=Join-Path $repoRoot 'integrations/config/runtime_dependencies.json'
  $frozen=Freeze-ConsumerDependencies -RepoRoot $repoRoot -ContractPath $dependencyPath -InputDir $package.input_dir -OwnerId $projectId -ConsumerId accelerator_interface
  $script:pythonRoot=[string]$frozen.execution_root
  $configuration=Get-Content -LiteralPath $package.run_config -Raw|ConvertFrom-Json -AsHashtable
  $configuration.inputs=[ordered]@{code_inventory=$frozen.code_inventory_path;dependency_contract=$frozen.dependency_contract_path}
  foreach($identity in $frozen.identities){$configuration.inputs[$identity.frozen_input_name]=$identity.snapshot_path}
  Write-RunJson -Path $package.run_config -Depth 50 -Value $configuration
  $stage='prepare_only'
  $lease=Enter-HostExecutionLease -Role GATE
  $arguments=@('-m','integrations.workflows.accelerator_interface.prepare',
    '--provider',$AcceleratorProvider,'--reference-mr-run',$reference,'--run-directory',$package.artifact_run_dir)
  if($sourceRun){$arguments+=@('--source-run',$sourceRun)}
  if($LuaExe){$arguments+=@('--lua-executable',$LuaExe)}
  if($MatchingRequestPath){$arguments+=@('--matching-request',(Resolve-Path -LiteralPath $MatchingRequestPath).Path)}
  if($FinalizeJointWorkbench){$arguments+=@('--finalize-joint-workbench','--prepared-interface-run',$designRun,'--joint-field-run',$fieldRun)}
  if($executionContract){$arguments+=@('--contract',$executionContract)}
  $log=Join-Path $package.log_dir 'prepare_accelerator_interface.log'
  Invoke-RunToolRootContext -RepoRoot $script:pythonRoot -Operation {
    & $python -B @arguments 2>&1|Tee-Object -FilePath $log
    if($LASTEXITCODE-ne0){throw "Accelerator interface preparation failed; Python source error is retained in $log"}
  }
  Exit-HostExecutionLease -Lease $lease
  $lease=$null
  $receipt=Get-Content -LiteralPath (Join-Path $package.result_dir 'accelerator_interface_preparation.json') -Raw|ConvertFrom-Json -AsHashtable
  if($FinalizeJointWorkbench){
    $stage='iob_assembly_no_fly'
    $joint=$receipt.joint_workbench_binding
    $build=$joint.workbench_build_contract
    $audit=$joint.interface_field_audit
    # Reuse the static-trial read/no-write/no-delete payload guard policy. The
    # builder saves only IOB and small companions, never dirty PA arrays.
    $guardPaths=@($build.paths)+@($joint.guard_paths)+@($audit.guard_paths)
    foreach($path in @($guardPaths|Select-Object -Unique)){
      $paGuards.Add([IO.File]::Open([string]$path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read))
      $surface=[string]$path+'-surf'
      if(Test-Path -LiteralPath $surface -PathType Leaf){$paGuards.Add([IO.File]::Open($surface,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read))}
    }
    $lease=Enter-HostExecutionLease -Role SIMION -Stage preparation
    $stage='joint_asset_identity_before_iob'
    Invoke-RunToolRootContext -RepoRoot $script:pythonRoot -Operation {
      & $python -B -c 'import sys;from pathlib import Path;from projects.parallel_mirror_dual_stripe_mr_tof.analysis.static_field_binding import load_binding,verify_joint_asset_records;verify_joint_asset_records(load_binding(Path(sys.argv[1])));print("JOINT_NATIVE_ASSETS=PASS")' (Join-Path $package.result_dir 'joint_workbench/static_field_binding.json')
      if($LASTEXITCODE-ne0){throw 'Joint workbench live asset identity verification failed; no vendor consumer was started.'}
    }
    $stage='iob_assembly_no_fly'
    $buildLog=Join-Path $package.log_dir 'joint_workbench_assembly.log'
    $extraOutputs+=@($buildLog)
    $builder=Join-Path $package.result_dir 'joint_workbench/runtime/build_workbench.lua'
    $request=Join-Path $package.result_dir 'joint_workbench/runtime/workbench_build.lua'
    Invoke-RunToolRootContext -RepoRoot $script:pythonRoot -Operation {
      & $SimionExe --nogui --noprompt lua $builder -- --measured-source $request 2>&1|Tee-Object -FilePath $buildLog
      if($LASTEXITCODE-ne0){throw 'Joint workbench IOB assembly failed; no joint flight was attempted.'}
    }
    $buildText=Get-Content -LiteralPath $buildLog -Raw
    $declaredInstances=@($build.paths).Count
    if($declaredInstances-notin@(4,5)){throw 'Verified IP workbench requires four or five collision instances.'}
    if($buildText-notmatch("MRTOF_NATIVE_CORRIDOR_IOB_BUILD=PASS instances="+$declaredInstances+' static_measured_source=true')-or
       $buildText-match'(?im)(error:|error,|failed to save|cannot save|unable to save)'){
      throw 'Joint workbench builder did not prove the declared role count, clean save/reload and priority probes.'
    }
    if(-not(Test-Path -LiteralPath $build.output -PathType Leaf)){throw 'Joint IOB missing after successful assembly.'}
    $stage='interface_energy_field_audit_no_fly'
    $auditLog=Join-Path $package.log_dir 'interface_energy_field_audit.log'
    $extraOutputs+=@($auditLog)
    # A new vendor process loads only source basis + proven highest-priority IP
    # fine level. It does not inherit the builder's large PA collection.
    Invoke-RunToolRootContext -RepoRoot $script:pythonRoot -Operation {
      & $SimionExe --nogui --noprompt lua $audit.program -- $audit.lua_request 2>&1|Tee-Object -FilePath $auditLog
      if($LASTEXITCODE-ne0){throw 'Read-only interface field audit failed.'}
    }
    if((Get-Content -LiteralPath $auditLog -Raw)-notmatch'MRTOF_INTERFACE_FIELD_AUDIT=PASS'){
      throw 'Interface field audit did not close all measured crossings and centroid.'
    }
    Invoke-RunToolRootContext -RepoRoot $script:pythonRoot -Operation {
      & $python -B -c 'import sys;from pathlib import Path;from projects.parallel_mirror_dual_stripe_mr_tof.analysis.joint_flight_preparation import summarize_interface_field_audit;summarize_interface_field_audit(Path(sys.argv[1]))' (Split-Path -Parent $audit.raw_output)
      if($LASTEXITCODE-ne0){throw 'Interface energy/field ledger reduction failed.'}
    }
    $joint.interface_field_audit.status='reported_no_energy_acceptance'
    Exit-HostExecutionLease -Lease $lease
    $lease=$null
    foreach($guard in $paGuards){$guard.Dispose()};$paGuards.Clear()
    $joint.status='iob_built_no_joint_flight'
    $joint.vendor_program_executed=$true
    $joint.iob_path=$build.output
    $joint.joint_simulation_executed=$false
    $receipt.status='workbench_ready_no_joint_flight'
    Write-Output 'JOINT_WORKBENCH_READINESS=CONFIGURATION_AND_FIELD_IDENTITY ENERGY_TARGET_ACCEPTANCE=not_declared SIX_DIMENSIONAL_MATCH_QUALIFIED=False TIME_FOCUS_QUALIFIED=False JOINT_FLY=False GUI=False'
    Write-RunJson -Path (Join-Path $package.result_dir 'joint_workbench/joint_binding_receipt.json') -Depth 40 -Value $joint
    Write-RunJson -Path (Join-Path $package.result_dir 'accelerator_interface_preparation.json') -Depth 40 -Value $receipt
  }
  $configuration=Get-Content -LiteralPath $package.run_config -Raw|ConvertFrom-Json -AsHashtable
  foreach($key in $receipt.inputs.Keys){$configuration.inputs[$key]=$receipt.inputs[$key].path}
  $configuration.parameters=[ordered]@{
    accelerator_provider=$AcceleratorProvider
    source_run=$sourceRun
    reference_mr_run=$reference
    finalize_joint_workbench=[bool]$FinalizeJointWorkbench
    prepared_design_run=$designRun
    new_joint_field_run=$fieldRun
    solver_execution='none'
    qualification='interface_preparation_only_not_joint_simulation'
  }
  Write-RunJson -Path $package.run_config -Depth 50 -Value $configuration
  Write-RunJson -Path $package.summary -Depth 30 -Value ([ordered]@{
    schema_version=1;role='mrtof_accelerator_interface_run_summary';status='success'
    qualification='interface_preparation_only_not_joint_simulation';preparation=$receipt
  })
  $stage='terminal_publication'
  $retention=Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config
  $terminal=Update-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot `
    -Session $capacitySession -RemainingCommittedNewBytes 0
  $capacitySession=$terminal.session
  Write-RunJson -Path (Join-Path $package.result_dir 'artifact_capacity_gate_terminal.json') -Depth 14 -Value $terminal
  $outputs=@(Get-ChildItem -LiteralPath $package.result_dir -Recurse -File|ForEach-Object{$_.FullName})
  $outputs+=@($package.summary,$log,$retention)+$extraOutputs
  Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config `
    -Status success -Software $software -Outputs $outputs -DeferCapacityFinalization
  $terminalized=$true
  $stage='capacity_finalization'
  Invoke-RunCapacityLifecycleAdapter -Python $python -RepoRoot $repoRoot `
    -Action finalize-ready -ArtifactRoot (Join-Path $workspaceRoot 'artifacts') -RunConfig $package.run_config|Out-Null
  if($receipt.status-eq'zero_exit'){
    Write-Output "ACCELERATOR_PREPARATION=ZERO_EXIT PROVIDER=$AcceleratorProvider RUN_ID=$RunId MOTHER=$($receipt.source_exit.counts.source) TRANSFERRED=0 SCIENTIFIC_QUALIFICATION=not_passed SOLVER_EXECUTED=False"
  }else{Write-Output "ACCELERATOR_PREPARATION=PASS PROVIDER=$AcceleratorProvider RUN_ID=$RunId SOLVER_EXECUTED=False"}
}catch{
  if($terminalized){
    Write-Warning 'Scientific summary and verified manifest retained; capacity handoff failed and requires public owner recovery.'
  }else{
    Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config -Summary $package.summary `
      -SummaryRole mrtof_accelerator_interface_run_summary -Reason $_.Exception.Message `
      -Software $software -Status failed -FailureStage $stage
    $terminalized=$true
  }
  throw
}finally{
  if($null-ne$lease){Exit-HostExecutionLease -Lease $lease}
  foreach($guard in $paGuards){$guard.Dispose()}
  if($null-ne$capacitySession){$null=Exit-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $capacitySession}
}

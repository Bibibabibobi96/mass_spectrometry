[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$WorkpointRunPath,
  [string]$NativeCorridorBankRunPath='',
  [string]$FieldBindingPath='',
  [string]$GeometryReviewRunPath='',
  [Parameter(Mandatory)][string]$BunchSourceReceiptPath,
  [Parameter(Mandatory)][string]$CompositionPlanPath,
  [string]$LocalScopePath='',
  [string]$MirrorVoltageVariationPath='',
  [string]$InitialCohortRunPath='',
  [string]$CohortBatchContinuationRunPath='',
  [ValidateSet(3,13,100,1000)][int]$CohortParticleCount=1000,
  [switch]$FocusDiagnosticOnly,
  [ValidateSet('','focus_z','slow_energy','controlled_aberration')][string]$DiagnosticPurpose='',
  [Nullable[double]]$TrajectoryStepScaleOverride=$null,
  [string]$RunId='',
  [string]$SimionExe='',
  [string]$PythonExe=''
)

# Candidate continuation only.  It runs one static cohort from the checkpointed
# native Fast Adjust family; no PA is rebuilt, copied, Refined, or materialized.
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$projectId='parallel_mirror_dual_stripe_mr_tof'
$repoRoot=(Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$workspaceRoot=Split-Path -Parent $repoRoot
$python=if($PythonExe){[IO.Path]::GetFullPath($PythonExe)}else{Join-Path $repoRoot '.venv\Scripts\python.exe'}
$workpointRun=(Resolve-Path -LiteralPath $WorkpointRunPath).Path
$workpointConfig=Get-Content -LiteralPath (Join-Path $workpointRun 'run_config.json') -Raw|ConvertFrom-Json -AsHashtable
$staticFieldMode=$workpointConfig.parameters.ContainsKey('corridor_field')-and$workpointConfig.parameters.corridor_field-in@('comsol_static_scalar_v','native_static_pa')
if($staticFieldMode-and$NativeCorridorBankRunPath){throw 'Static screening cannot consume a native field bank.'}
if(-not$staticFieldMode-and$FieldBindingPath){throw 'Native workpoint cannot be rebound to a static field.'}
$bankRun=if($staticFieldMode){''}else{(Resolve-Path -LiteralPath $NativeCorridorBankRunPath).Path}
$sourceReceipt=(Resolve-Path -LiteralPath $BunchSourceReceiptPath).Path
$mirrorVoltageVariation=if([string]::IsNullOrWhiteSpace($MirrorVoltageVariationPath)){$null}else{(Resolve-Path -LiteralPath $MirrorVoltageVariationPath).Path}
$initialCohortRun=if([string]::IsNullOrWhiteSpace($InitialCohortRunPath)){$null}else{(Resolve-Path -LiteralPath $InitialCohortRunPath).Path}
if(-not$staticFieldMode-and$null-ne$initialCohortRun-and$null-ne$mirrorVoltageVariation){throw 'An existing static cohort cannot be rebound to a new mirror-voltage variation.'}
if($FocusDiagnosticOnly){
  if($DiagnosticPurpose-and$DiagnosticPurpose-ne'focus_z'){
    throw 'FocusDiagnosticOnly cannot be combined with a different DiagnosticPurpose.'
  }
  $DiagnosticPurpose='focus_z'
}
$diagnosticOnly=-not[string]::IsNullOrWhiteSpace($DiagnosticPurpose)
$trajectoryStepScale=if($null-eq$TrajectoryStepScaleOverride){$null}else{[double]$TrajectoryStepScaleOverride}
if($null-ne$trajectoryStepScale-and(-not[double]::IsFinite($trajectoryStepScale)-or$trajectoryStepScale-le0)){
  throw 'TrajectoryStepScaleOverride must be finite and positive.'
}
$requiredDiagnosticCount = if($DiagnosticPurpose -eq 'controlled_aberration'){13}elseif($diagnosticOnly){3}else{0}
if(($requiredDiagnosticCount -eq 0 -and $CohortParticleCount -notin @(100,1000))-or
   ($requiredDiagnosticCount -ne 0 -and $CohortParticleCount -ne $requiredDiagnosticCount)){
  throw 'DiagnosticPurpose requires its controlled cohort size: focus_z/slow_energy use N=3 and controlled_aberration uses N=13.'
}
if([string]::IsNullOrWhiteSpace($RunId)){$RunId=(Get-Date -Format 'yyyyMMdd_HHmmss')+'__sim__simion__mrtof-native-corridor-bunch-screening'}

. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')
. (Join-Path $repoRoot 'projects\parallel_mirror_dual_stripe_mr_tof\simion\native_corridor_runtime_support.ps1')

function Get-VerifiedManifestOutput {
  param([Parameter(Mandatory)][string]$ManifestPath,[Parameter(Mandatory)][string]$Name)
  $manifest=Get-Content -LiteralPath $ManifestPath -Raw|ConvertFrom-Json -Depth 40
  $records=@($manifest.outputs|Where-Object{[IO.Path]::GetFileName([string]$_.path)-eq$Name})
  if($records.Count-ne1){throw "Manifest must bind exactly one ${Name}: $ManifestPath"}
  $path=[IO.Path]::GetFullPath([string]$records[0].path)
  if(-not(Test-Path -LiteralPath $path -PathType Leaf)){throw "Manifest output is missing: $path"}
  if((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash-ne([string]$records[0].sha256).ToUpperInvariant()){
    throw "Manifest output identity differs: $path"
  }
  return $path
}

function Get-DeclaredManifestOutputPath {
  param([Parameter(Mandatory)][string]$ManifestPath,[Parameter(Mandatory)][string]$Name)
  $manifest=Get-Content -LiteralPath $ManifestPath -Raw|ConvertFrom-Json -Depth 40
  $records=@($manifest.outputs|Where-Object{[IO.Path]::GetFileName([string]$_.path)-eq$Name})
  if($records.Count-ne1){throw "Manifest must declare exactly one ${Name}: $ManifestPath"}
  return [IO.Path]::GetFullPath([string]$records[0].path)
}

function Assert-VerifiedManifest {
  param([Parameter(Mandatory)][string]$ManifestPath,[Parameter(Mandatory)][string]$Status,[Parameter(Mandatory)][string]$Mode,[string]$Owner=$projectId,[string]$ConsumedOutput='',[switch]$ReadOnlyFlightEvidence)
  if($ReadOnlyFlightEvidence){
    $identity=Get-Content -LiteralPath $ManifestPath -Raw|ConvertFrom-Json -AsHashtable
    if(-not(($identity.project-eq'instrument_assembly'-and$identity.mode-eq'oa_mr')-or
      ($identity.project-eq'parallel_mirror_dual_stripe_mr_tof'-and$identity.mode-eq'finite_3d_two_prism_voltage_trial'))){
      throw 'Read-only flight evidence has an unsupported owner/mode pair.'
    }
    $Owner=[string]$identity.project;$Mode=[string]$identity.mode
  }
  $arguments=@($ManifestPath,'--require-status',$Status,'--require-project',$Owner,'--require-mode',$Mode)
  if($ConsumedOutput){$arguments+=@('--consumer-projection-id','mrtof_static_screening_center_v1','--consumed-output',$ConsumedOutput)}
  & $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') @arguments|Out-Host
  if($LASTEXITCODE-ne0){throw "Manifest verification failed: $ManifestPath"}
}


function Read-SelectedStaticCenter {
  param([Parameter(Mandatory)][string]$WorkpointRun,[Parameter(Mandatory)]$Handoff)
  if(-not$Handoff.selected_workpoint.ContainsKey('field_binding')){throw 'Static handoff omits the actually flown field.'}
  $selectedBinding=[string]$Handoff.selected_workpoint.field_binding.path
  $lineagePath=Get-VerifiedManifestOutput -ManifestPath (Join-Path $WorkpointRun 'run_manifest.json') -Name 'iteration_lineage.json'
  $lineage=Get-Content -LiteralPath $lineagePath -Raw|ConvertFrom-Json -AsHashtable
  $matches=@($lineage.children|Where-Object{
    $path=Get-VerifiedManifestOutput -ManifestPath $_.child_manifest -Name 'two_prism_trial_materialization.json'
    $value=Get-Content -LiteralPath $path -Raw|ConvertFrom-Json -AsHashtable
    $value.ContainsKey('field_binding')-and$null-ne$value.field_binding-and
      [IO.Path]::GetFullPath([string]$value.field_binding.path)-eq[IO.Path]::GetFullPath($selectedBinding)
  })
  if($matches.Count-ne1){throw 'Static handoff does not identify one actual centre child.'}
  $manifest=[string]$matches[0].child_manifest
  $materializationPath=Get-VerifiedManifestOutput -ManifestPath $manifest -Name 'two_prism_trial_materialization.json'
  Assert-VerifiedManifest -ManifestPath $manifest -Status success -Mode oa_mr -Owner instrument_assembly -ConsumedOutput $materializationPath -ReadOnlyFlightEvidence
  $materialization=Get-Content -LiteralPath $materializationPath -Raw|ConvertFrom-Json -AsHashtable
  $actual=@($materialization.stripe_biases_v)+@($materialization.prism_voltages_v)
  $expected=@($Handoff.selected_workpoint.voltages_v)
  if($actual.Count-ne4-or$expected.Count-ne4-or@(0..3|Where-Object{[double]$actual[$_]-ne[double]$expected[$_]}).Count){throw 'Selected centre field belongs to different P/S voltages.'}
  if([string]$materialization.field_binding.mode-ne[string]$Handoff.selected_workpoint.field_binding.mode){throw 'Selected centre field mode differs from its handoff.'}
  return @{manifest=$manifest;materialization_path=$materializationPath;materialization=$materialization;config=(Get-Content -LiteralPath (Join-Path (Split-Path -Parent $manifest) 'run_config.json') -Raw|ConvertFrom-Json -AsHashtable)}
}

function Read-StaticCenterProblem {
  param([Parameter(Mandatory)]$Selected,[Parameter(Mandatory)][string]$ContractPath,[Parameter(Mandatory)][string]$SourceReceipt,[string]$GeometryReviewRun='')
  $center=$Selected.materialization;$centerConfig=$Selected.config
  $contractData=Get-Content -LiteralPath $ContractPath -Raw|ConvertFrom-Json -AsHashtable
  $profileId=if($center.trajectory_profile.ContainsKey('base_profile_id')){[string]$center.trajectory_profile.base_profile_id}else{[string]$center.trajectory_profile.profile_id}
  $baseStep=[double]$contractData.simion.trajectory_profiles[$profileId].maximum_step_us
  if(-not[double]::IsFinite($baseStep)-or$baseStep-le0){throw 'Static centre has no valid trajectory step authority.'}
  $centerBinding=Get-Content -LiteralPath $center.field_binding.path -Raw|ConvertFrom-Json -AsHashtable
  if($center.field_binding.mode-eq'native_static_pa'){
    if(-not$GeometryReviewRun){throw 'Native static screening requires its original GeometryReviewRunPath; sealed field geometry remains authoritative.'}
    $geometry=(Resolve-Path -LiteralPath $GeometryReviewRun).Path
    $review=Get-Content -LiteralPath (Join-Path $geometry 'run_manifest.json') -Raw|ConvertFrom-Json -AsHashtable
    if($review.status-ne'success'-or$review.project-ne$projectId){throw 'Native static geometry review must be a successful project owner.'}
    $geometryInputName=switch($review['mode']){
      'native_static_field_provider' {'resolved_geometry'}
      'resolved_engineering_cad_export' {'resolved_geometry.json'}
      'validated_engineering_cad_publication' {'resolved_geometry.json'}
      default {throw 'Native static geometry owner has an unsupported mode.'}
    }
    $record=Get-VerifiedRunManifestInputRecord -Records $review.inputs -Name $geometryInputName -Label 'geometry review'
    Assert-VerifiedRunRecordHash -Path $record.path -Record $record -Label 'geometry review'
    if((Get-FileHash -LiteralPath $centerBinding.parent.geometry_authority_path -Algorithm SHA256).Hash-ne([string]$record.sha256).ToUpperInvariant()){throw 'Geometry review differs from the sealed native field geometry.'}
  }else{$geometry=Split-Path -Parent $centerBinding.collision_manifest}
  $provider=Get-VerifiedManifestOutput -ManifestPath $centerConfig.inputs.accelerator_run_manifest -Name 'mrtof_runtime_receipt.json'
  if((Get-FileHash -LiteralPath $provider -Algorithm SHA256).Hash-ne(Get-FileHash -LiteralPath $centerConfig.inputs.accelerator_provider_receipt -Algorithm SHA256).Hash){throw 'Original OA provider differs from the actually flown receipt.'}
  # Formal volume and controlled cohorts have different particles/receipts, but
  # must retain the selected centre's physical source and current OA projection.
  $sourceCode=@'
import json, sys
from pathlib import Path
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.bunch_source_and_schedule import load_verified_bunch_source_receipt
source, mother = [load_verified_bunch_source_receipt(Path(p)) for p in sys.argv[1:3]]
for key in ('nominal_center_state', 'species', 'frame_id', 'clock_basis', 'common_time_of_birth_us', 'source_y_offset_mm', 'center_rule'):
    if source[key] != mother[key]:
        raise ValueError(f'Screening source physical state differs: {key}')
definitions = [json.loads(Path(r['definition']['path']).read_text(encoding='utf-8-sig')) for r in (source, mother)]
for key in ('coordinate_semantics', 'center_rule', 'field_cache_dependency', 'aperture_plane_axes', 'acceleration_axis', 'position_radius_mm', 'acceleration_axis_full_width_mm', 'kinetic_energy_center_ev', 'kinetic_energy_full_width_ev', 'nominal_direction_workbench', 'angular_full_width_deg', 'mass_th', 'charge_e', 'common_time_of_birth_us'):
    if definitions[0][key] != definitions[1][key]:
        raise ValueError(f'Screening source physical definition differs: {key}')
for key, default in (('kinetic_energy_distribution', 'uniform'), ('kinetic_energy_sigma_ev', None)):
    if definitions[0].get(key, default) != definitions[1].get(key, default):
        raise ValueError(f'Screening source physical definition differs: {key}')
if source['geometry_contract']['derived_center_workbench_mm'] != mother['geometry_contract']['derived_center_workbench_mm']:
    raise ValueError('Screening source geometry-derived centre differs')
providers = [json.loads(Path(r['accelerator_provider_receipt']['path']).read_text(encoding='utf-8-sig')) for r in (source, mother)]
current = json.loads(Path(sys.argv[3]).read_text(encoding='utf-8-sig'))
for candidate in providers:
    if candidate['role'] != current['role'] or candidate['resolved_campaign']['sha256'] != current['resolved_campaign']['sha256']:
        raise ValueError('Screening source OA campaign authority differs')
    for key in ('accepted_release', 'geometry', 'endpoint_voltages_v', 'ring_voltages_v', 'target_axial_energy_per_charge_v', 'required_source_y_offset_from_accelerator_axis_mm'):
        if candidate['mrtof_projection'][key] != current['mrtof_projection'][key]:
            raise ValueError(f'Screening source OA physical projection differs: {key}')
'@
  Invoke-ProjectPython -Arguments @('-c',$sourceCode,$SourceReceipt,$centerConfig.inputs.bunch_source_receipt,$provider)
  return @{
    geometry=$geometry;mirror=(Split-Path -Parent $centerConfig.inputs.mirror_run_manifest);stripe=(Split-Path -Parent $centerConfig.inputs.stripe_run_manifest)
    accelerator_provider_receipt=$provider;contract_sha256=(Get-FileHash -LiteralPath $ContractPath -Algorithm SHA256).Hash
    trajectory_profile=$profileId;trajectory_step_scale=([double]$center.trajectory_profile.maximum_step_us/$baseStep)
    source_y_offset_mm=(Get-Content -LiteralPath $SourceReceipt -Raw|ConvertFrom-Json -AsHashtable).source_y_offset_mm
  }
}

function Assert-StaticScreeningField {
  param([Parameter(Mandatory)]$Selected,[Parameter(Mandatory)][string]$BindingPath,[string]$Variation='',[Parameter(Mandatory)][string]$ContractPath,[Parameter(Mandatory)]$Voltages)
  $center=$Selected.materialization
  if($center.field_binding.mode-eq'native_static_pa'){
    # A TE1 probe retains the qualified centre's P/S anchor, not its old mirror
    # field bytes. Reuse the sealed provider authority and fixed-grid projection.
    $code=@'
import copy, json, sys
from pathlib import Path
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.static_field_binding import load_binding, _record
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.corridor_field_provider import derive_candidate_authority, candidate_authority
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.downstream_fixed_grid_workpoint import _native_static_binding_problem
def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))
center, actual = [load_binding(Path(p)) for p in sys.argv[1:3]]
if center['mode'] != 'native_static_pa' or actual['mode'] != center['mode']:
    raise ValueError('Screening static field representation differs')
values = json.loads(sys.argv[5])
candidate = dict(zip(('s1', 's2', 'p1', 'p2'), values, strict=True))
if candidate_authority(center['authority'], candidate) != center['authority']:
    raise ValueError('Selected centre field P/S authority differs')
manifest = Path(actual['manifest'])
request_path = Path(read(manifest.parent / 'run_config.json')['inputs']['request'])
_record(manifest, request_path)
request = read(request_path)
if request['role'] != 'mrtof_native_static_field_provider_request' or request['candidate_voltages_v'] != candidate:
    raise ValueError('Screening provider P/S request differs')
source = load_binding(Path(request['source_binding_path']))
if Path(request['source_field_manifest']).resolve() != Path(source['manifest']).resolve():
    raise ValueError('Screening provider source parent manifest differs')
if sys.argv[3]:
    if not request.get('mirror_voltage_variation_path'):
        raise ValueError('Screening provider mirror variation differs')
    variations = [read(request['mirror_voltage_variation_path']), read(sys.argv[3])]
    for variation in variations:
        # Diagnostic locators may change when the same measured fit is republished.
        for sample in variation.get('detector_plane_root_fit', {}).get('samples', []):
            sample.pop('diagnostic_path', None)
    if variations[0] != variations[1]:
        raise ValueError('Screening provider mirror variation differs')
    request.update(mirror_voltage_variation_path=sys.argv[3], mirror_contract_path=sys.argv[4])
    expected, _ = derive_candidate_authority(request, source['authority'])
    center_target = candidate_authority(center['authority'], candidate,
                                        mirror_voltages_v=expected['analyzer_electrode_voltages_v'][:5])
else:
    expected = center_target = center['authority']
if actual['authority'] != expected or expected != center_target or actual['geometry'] != center['geometry']:
    raise ValueError('Screening full voltage or geometry authority differs')
# Retain the verified centre's actual source when projecting a storage-only view.
materialization = read(sys.argv[6])
materialization.update(analyzer_electrode_voltages_v=expected['analyzer_electrode_voltages_v'],
                       stripe_biases_v=values[:2], prism_voltages_v=values[2:])
expected_center = copy.deepcopy(center)
expected_center['authority'] = expected
if _native_static_binding_problem(actual, materialization, canonical_consumer_layout=True) != _native_static_binding_problem(expected_center, materialization, canonical_consumer_layout=True):
    raise ValueError('Screening numerical or collision identity differs')
'@
    Invoke-ProjectPython -Arguments @('-B','-c',$code,$center.field_binding.path,$BindingPath,$Variation,$ContractPath,($Voltages|ConvertTo-Json -Compress),$Selected.materialization_path)
  }else{
    if((Get-FileHash -LiteralPath $BindingPath -Algorithm SHA256).Hash-ne(Get-FileHash -LiteralPath $center.field_binding.path -Algorithm SHA256).Hash){throw 'Screening cannot rebind the selected centre to another static field.'}
    if($Variation-and(Get-FileHash -LiteralPath $Variation -Algorithm SHA256).Hash-ne(Get-FileHash -LiteralPath $Selected.config.inputs.terminal_time_mirror_voltage_variation -Algorithm SHA256).Hash){throw 'Screening mirror variation differs from the selected static centre.'}
  }
}

function Invoke-ProjectPython {
  param([Parameter(Mandatory)][string[]]$Arguments)
  Push-Location -LiteralPath $repoRoot
  $savedPythonPath=$env:PYTHONPATH
  try{
    $env:PYTHONPATH=$repoRoot
    & $python @Arguments
    if($LASTEXITCODE-ne0){throw "Python stage failed: $($Arguments -join ' ')"}
  }finally{
    $env:PYTHONPATH=$savedPythonPath
    Pop-Location
  }
}

function New-CohortRunId {
  if($RunId-notmatch'^(?<stamp>\d{8}_\d{6})__(?:sim|analysis)__(?:simion|python)__(?<subject>[a-z0-9]+(?:-[a-z0-9]+)*)(?:__[a-z0-9]+(?:-[a-z0-9]+)*)?(?:__r\d{2})?$'){
    throw 'Screening run_id cannot derive a cohort identity.'
  }
  $stamp=[string]$Matches.stamp;$subject=[string]$Matches.subject
  $revision=if($RunId-match'__r(?<retry>\d{2})$'){"__r$($Matches.retry)"}else{''}
  return "$stamp`__sim`__simion`__$subject-n$CohortParticleCount-static$revision"
}

$workpointManifest=Join-Path $workpointRun 'run_manifest.json'
$bankManifest=if($staticFieldMode){$null}else{Join-Path $bankRun 'run_manifest.json'}
$sourceRun=Split-Path -Parent (Split-Path -Parent $sourceReceipt)
$sourceManifest=Join-Path $sourceRun 'run_manifest.json'
$trialRunner=Join-Path $repoRoot 'integrations/workflows/oa_mr/execute.ps1'
$artifactProjectRoot=Join-Path $workspaceRoot "artifacts\projects\$projectId"
$package=New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactProjectRoot `
  -RunId $RunId -Project $projectId -Mode 'native_corridor_candidate_bunch_screening' `
  -Software @('SIMION 2020','Python 3.11') -RetentionContractEnabled -RetentionClass compact `
  -CapacityLedgerLifecycleEnabled
$terminalized=$false;$failureStage='preflight';$capacitySession=$null;$nativeRuntimeSession=$null
try{
  $failureStage='verify_inputs'
  $handoff=Get-DeclaredManifestOutputPath -ManifestPath $workpointManifest -Name 'best_physical_workpoint_handoff.json'
  # A resumed workpoint can legitimately retain its family in its original
  # owner run.  Consume the manifest-declared checkpoint instead of assuming
  # a same-directory copy exists.
  $checkpoint=$null
  if($staticFieldMode){
    Assert-VerifiedManifest -ManifestPath $workpointManifest -Status success -Mode downstream_fixed_grid_workpoint_iteration
  }else{
  $checkpoint=Get-DeclaredManifestOutputPath -ManifestPath $workpointManifest -Name 'native_corridor_runtime_checkpoint.json'
  & $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') $workpointManifest --require-status checkpoint --require-project $projectId --require-mode downstream_fixed_grid_workpoint_iteration `
    --consumer-projection-id mrtof_native_bunch_workpoint_consumer_v1 --consumed-output $handoff --consumed-output $checkpoint|Out-Host
  if($LASTEXITCODE-ne0){throw 'Workpoint handoff/checkpoint projection failed verification.'}
  $bankPublication=Join-Path $bankRun 'results\pa_family_cache_publication.json'
  & $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') $bankManifest --require-status success --require-project $projectId --require-mode native_corridor_detached_response_bank `
    --consumer-projection-id mrtof_native_bunch_bank_consumer_v1 --consumed-output $bankPublication|Out-Host
  if($LASTEXITCODE-ne0){throw 'Native bank publication projection failed verification.'}
  }
  Assert-VerifiedManifest -ManifestPath $sourceManifest -Status 'success' -Mode 'deterministic_bunch_source_materialization'
  $handoff=Get-VerifiedManifestOutput -ManifestPath $workpointManifest -Name 'best_physical_workpoint_handoff.json'
  if(-not$staticFieldMode){$checkpoint=Get-VerifiedManifestOutput -ManifestPath $workpointManifest -Name 'native_corridor_runtime_checkpoint.json'}
  $handoffData=Get-Content -LiteralPath $handoff -Raw|ConvertFrom-Json -AsHashtable
  if($handoffData.status-ne'within_tolerance'){
    $history=Get-VerifiedManifestOutput -ManifestPath $workpointManifest -Name 'iteration_history.json'
    $handoff=Join-Path $package.input_dir 'qualified_workpoint_handoff.json'
    Invoke-ProjectPython -Arguments @(
      '-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.downstream_workpoint_iteration',
      '--select-best-physical-workpoint','--history',$history,'--output',$handoff
    )
    $handoffData=Get-Content -LiteralPath $handoff -Raw|ConvertFrom-Json -AsHashtable
  }
  if($handoffData.role-ne'mrtof_best_physical_workpoint_handoff'-or$handoffData.status-ne'within_tolerance' -or
     $handoffData.qualification-ne'candidate_bunch_screening_authorized'){
    throw 'Workpoint handoff does not authorize Candidate bunch screening.'
  }
  $voltages=@($handoffData.selected_workpoint.voltages_v|ForEach-Object{[double]$_})
  if($voltages.Count-ne4-or@($voltages|Where-Object{-not[double]::IsFinite($_)}).Count){throw 'Handoff voltage vector is invalid.'}
  if($staticFieldMode){
    $selected=Read-SelectedStaticCenter -WorkpointRun $workpointRun -Handoff $handoffData
    $centerConfig=$selected.config;$center=$selected.materialization
    $problem=Read-StaticCenterProblem -Selected $selected -ContractPath $workpointConfig.inputs.contract -SourceReceipt $sourceReceipt -GeometryReviewRun $GeometryReviewRunPath
    if(-not$FieldBindingPath){$FieldBindingPath=[string]$center.field_binding.path}
  }else{$problem=$workpointConfig.parameters.native_recovery_problem}
  if($null-eq$problem){throw 'Workpoint has no native physical-problem identity.'}
  $mirrorInputs=if($staticFieldMode){$centerConfig.inputs}else{$workpointConfig.inputs}
  if($null-eq$mirrorVoltageVariation-and$mirrorInputs.ContainsKey('terminal_time_mirror_voltage_variation')){
    $inheritedMirrorVariation=[string]$mirrorInputs.terminal_time_mirror_voltage_variation
    if(-not[string]::IsNullOrWhiteSpace($inheritedMirrorVariation)){
      $mirrorVoltageVariation=(Resolve-Path -LiteralPath $inheritedMirrorVariation).Path
    }
  }
  if($staticFieldMode){Assert-StaticScreeningField -Selected $selected -BindingPath $FieldBindingPath -Variation $mirrorVoltageVariation -ContractPath $workpointConfig.inputs.contract -Voltages $voltages}
  if([string]::IsNullOrWhiteSpace([string]$problem.accelerator_provider_receipt)){
    throw 'Workpoint must bind an OA accelerator provider receipt.'
  }
  $providerReceipt=(Resolve-Path -LiteralPath ([string]$problem.accelerator_provider_receipt)).Path
  $nativeSystemRuntimeBundlePath=''
  if(-not$staticFieldMode){
    if([string]::IsNullOrWhiteSpace([string]$problem.native_system_runtime_bundle)){throw 'Workpoint has no native system runtime bundle identity.'}
    $nativeSystemRuntimeBundlePath=(Resolve-Path -LiteralPath ([string]$problem.native_system_runtime_bundle)).Path
  }
  $workpointContract=(Resolve-Path -LiteralPath (Join-Path $workpointRun 'inputs\contract.json')).Path
  if((Get-FileHash -LiteralPath $workpointContract -Algorithm SHA256).Hash-ne[string]$problem.contract_sha256){
    throw 'Workpoint frozen contract identity differs from its physical-problem identity.'
  }
  $sourceData=Get-Content -LiteralPath $sourceReceipt -Raw|ConvertFrom-Json -AsHashtable
  if([int]$sourceData.particle_count-lt$CohortParticleCount){throw 'Candidate screening source is smaller than the requested cohort.'}
  $expectedCohortRole=if($diagnosticOnly){'controlled_diagnostic'}else{'formal_volume'}
  if([string]$sourceData.cohort_role-ne$expectedCohortRole){
    throw "Candidate screening requires a $expectedCohortRole source."
  }
  $contractData=Get-Content -LiteralPath $workpointContract -Raw|ConvertFrom-Json -AsHashtable
  $expectedSourceY=[double]$contractData.accelerator.focus_y_anchor.project_y_mm+[double]$sourceData.source_y_offset_mm
  $sourceCenterY=[double]$sourceData.nominal_center_state.position_workbench_mm[1]
  if([math]::Abs($sourceCenterY-$expectedSourceY)-gt1e-9){
    throw 'Candidate screening source centre does not match the workpoint accelerator y pose.'
  }
  $sourceReceiptBound=Get-VerifiedManifestOutput -ManifestPath $sourceManifest -Name 'bunch_source_receipt.json'
  if([IO.Path]::GetFullPath($sourceReceiptBound)-ne$sourceReceipt){throw 'Requested source receipt is not the source manifest receipt.'}
  $configuration=Get-Content -LiteralPath $package.run_config -Raw|ConvertFrom-Json -AsHashtable
  $configuration.inputs=[ordered]@{}
  $smallInputs=[ordered]@{workpoint_manifest=$workpointManifest;workpoint_handoff=$handoff;contract=$workpointContract;source_receipt=$sourceReceipt;accelerator_provider_receipt=$providerReceipt;workflow_source=$PSCommandPath}
  if($mirrorVoltageVariation){$smallInputs.mirror_voltage_variation=$mirrorVoltageVariation}
  if($staticFieldMode){
    $smallInputs.selected_center_manifest=$selected.manifest
    $smallInputs.selected_center_materialization=$selected.materialization_path
    $smallInputs.selected_center_config=Join-Path (Split-Path -Parent $selected.manifest) 'run_config.json'
    $smallInputs.static_field_binding=$FieldBindingPath
    if($center.field_binding.mode-eq'native_static_pa'){$smallInputs.geometry_review_manifest=Join-Path $problem.geometry 'run_manifest.json'}
    $configuration.parameters.selected_center_consumer_projection=@{projection_id='mrtof_static_screening_center_v1';manifest=$selected.manifest;consumed_output=$selected.materialization_path;assertion_scope='selected_center_config_and_materialization_only'}
  }
  foreach($entry in $smallInputs.GetEnumerator()){
    $configuration.inputs[$entry.Key]=Copy-VerifiedRunInput -Source $entry.Value -Destination (Join-Path $package.input_dir ($entry.Key+[IO.Path]::GetExtension($entry.Value)))
  }
  $configuration.parameters.diagnostic_purpose=$DiagnosticPurpose
  $configuration.parameters.cohort_particle_count=$CohortParticleCount
  Write-RunJson -Path $package.run_config -Depth 30 -Value $configuration

  $failureStage='capacity_startup'
  $capacitySession=Enter-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot `
    -ArtifactRoot (Join-Path $workspaceRoot 'artifacts') -RunDirectory $package.artifact_run_dir `
    -CommittedNewBytes 52428800 -ProtectedPaths @(@($package.artifact_run_dir,$workpointRun,$bankRun,$sourceRun,$nativeSystemRuntimeBundlePath,$FieldBindingPath)|Where-Object{$_}) `
    -Owner "mrtof-native-corridor-bunch-screening:$RunId"
  $startup=Join-Path $package.result_dir 'artifact_capacity_gate_startup.json';Write-RunJson -Path $startup -Depth 20 -Value $capacitySession

  $failureStage="cohort_n$CohortParticleCount"
  $cohortRunId=New-CohortRunId
  $cohortArguments=@{
    GeometryReviewRunPath=[string]$problem.geometry;MirrorRunPath=[string]$problem.mirror;StripeRunPath=[string]$problem.stripe
    NativeSystemRuntimeBundlePath=$nativeSystemRuntimeBundlePath
    NativeCorridorBankRunPath=$bankRun;CapacityWorkflowSession=$capacitySession
    BunchSourceReceiptPath=$sourceReceipt;BunchParticleIdMin=1;BunchParticleIdMax=$CohortParticleCount;ContractPath=$workpointContract
    RetainGuiWorkbench=$true
    Stripe1VoltageV=$voltages[0];Stripe2VoltageV=$voltages[1];Prism1VoltageV=$voltages[2];Prism2VoltageV=$voltages[3]
    TrajectoryProfileId=[string]$problem.trajectory_profile;TrajectoryStepScale=$(if($null-eq$trajectoryStepScale){[double]$problem.trajectory_step_scale}else{$trajectoryStepScale})
    AcceleratorSourceYOffsetMm=[double]$problem.source_y_offset_mm;RunId=$cohortRunId;PythonExe=$python
  }
  if($staticFieldMode){
    $cohortArguments.Remove('NativeCorridorBankRunPath')
    $cohortArguments.Remove('NativeSystemRuntimeBundlePath')
    $cohortArguments.FieldBindingPath=$FieldBindingPath
  }
  $cohortArguments.AcceleratorProviderReceiptPath=$providerReceipt
  $cohortArguments.CompositionPlanPath=$CompositionPlanPath
  if($LocalScopePath){$cohortArguments.LocalScopePath=$LocalScopePath}
  if($null-ne$mirrorVoltageVariation){$cohortArguments.MirrorVoltageVariationPath=$mirrorVoltageVariation}
  if(-not[string]::IsNullOrWhiteSpace($CohortBatchContinuationRunPath)){$cohortArguments.BatchContinuationRunPath=$CohortBatchContinuationRunPath}
  if($SimionExe){$cohortArguments.SimionExe=$SimionExe}
  if($null-ne$initialCohortRun){
    $cohortRun=$initialCohortRun;$cohortManifest=Join-Path $cohortRun 'run_manifest.json'
  }else{
    if(-not$staticFieldMode){
    $failureStage='open_native_runtime'
    $bank=Get-Content -LiteralPath (Join-Path $bankRun 'results\pa_family_cache_publication.json') -Raw|ConvertFrom-Json -AsHashtable
    $checkpointData=Get-Content -LiteralPath $checkpoint -Raw|ConvertFrom-Json -AsHashtable
    $runtimeDirectory=[IO.Path]::GetFullPath([string]$checkpointData.directory)
    $runtimeOwner=Split-Path (Split-Path $runtimeDirectory -Parent) -Parent
    $nativeRuntimeSession=[pscustomobject]@{
      lease_id=$capacitySession.lease_id;directory=$runtimeDirectory;runtime=$null;resident_bytes=[int64]0
      owner_run_directory=$runtimeOwner;owner_run_config=(Join-Path $runtimeOwner 'run_config.json');checkpoint_path=$checkpoint
    }
    $runtimeSimion=if($SimionExe){$SimionExe}else{Join-Path $env:ProgramFiles 'SIMION-2020\simion.exe'}
    Open-NativeCorridorRuntimeCheckpoint -Session $nativeRuntimeSession -CapacityWorkflowSession $capacitySession `
      -BankGenerationDirectory $bank.generation_directory -CacheKey $bank.cache_key -GenerationSha256 $bank.generation_sha256 `
      -Python $python -RepoRoot $repoRoot -SimionExe $runtimeSimion
    $cohortArguments.NativeCorridorRuntimeSession=$nativeRuntimeSession
    }
    $failureStage="cohort_n$CohortParticleCount"
    & $trialRunner @cohortArguments
    $cohortRun=Join-Path $workspaceRoot "artifacts/projects/instrument_assembly/runs/$cohortRunId";$cohortManifest=Join-Path $cohortRun 'run_manifest.json'
  }
  Assert-VerifiedManifest -ManifestPath $cohortManifest -Status 'success' -Mode 'oa_mr' -Owner instrument_assembly -ReadOnlyFlightEvidence:($null-ne$initialCohortRun)
  $cohortGate=Get-VerifiedManifestOutput -ManifestPath $cohortManifest -Name 'bunch_collection_gate.json'
  $cohortGateData=Get-Content -LiteralPath $cohortGate -Raw|ConvertFrom-Json -AsHashtable
  $cohortSummary=Get-Content -LiteralPath (Join-Path $cohortRun 'summary.json') -Raw|ConvertFrom-Json -AsHashtable
  $cohortVoltages=@($cohortSummary.stripe_biases_v)+@($cohortSummary.prism_voltages_v)
  if([int]$cohortSummary.source_particle_count-ne$CohortParticleCount-or
     [int]$cohortSummary.source_cohort.mother_particle_count-ne[int]$sourceData.mother_particle_count-or
     [string]$cohortSummary.source_cohort.selection.parent_particle_states_sha256-ne[string]$sourceData.particle_states_sha256-or
     $cohortVoltages.Count-ne4-or(@(0..3|Where-Object{[double]$cohortVoltages[$_]-ne[double]$voltages[$_]}).Count-ne0)-or
     [string]$cohortSummary.accelerator_pulse.mode-ne'static'){
    throw 'Cohort run does not bind the requested source, workpoint voltages, and static accelerator mode.'
  }

  if($staticFieldMode){
    $cohortConfig=Get-Content -LiteralPath (Join-Path $cohortRun 'run_config.json') -Raw|ConvertFrom-Json -AsHashtable
    if(-not$cohortConfig.inputs.ContainsKey('static_field_binding')-or
      (Get-FileHash -LiteralPath $cohortConfig.inputs.static_field_binding -Algorithm SHA256).Hash-ne(Get-FileHash -LiteralPath $FieldBindingPath -Algorithm SHA256).Hash){throw 'Cohort uses a different actual static field binding.'}
  }
  $failureStage='publish'
  $paReuse=if(-not$staticFieldMode){'one_checkpointed_native_fast_adjust_family__no_pa_copy_or_refine'}elseif($center.field_binding.mode-eq'native_static_pa'){'published_native_static_pa__four_read_only_collision_instances'}else{'published_comsol_scalar_v__four_read_only_collision_instances'}
  $result=Join-Path $package.result_dir 'bunch_screening_result.json'
  Write-RunJson -Path $result -Depth 20 -Value ([ordered]@{
    schema_version=1;role='mrtof_native_corridor_bunch_screening';status=$(if([bool]$cohortGateData.hard_stop){'hard_stop'}else{'complete'})
    purpose=$(if($diagnosticOnly){$DiagnosticPurpose}else{'candidate_bunch_metrics'})
    pa_reuse=$paReuse;accelerator_field_mode='static'
    cohort_run_manifest=$cohortManifest;cohort_collection_gate=$cohortGate
    next_action=$(if($diagnosticOnly){"analyze_controlled_${DiagnosticPurpose}_response_only"}elseif([bool]$cohortGateData.hard_stop){'stop_below_collection_hard_minimum'}else{"analyze_complete_n${CohortParticleCount}_candidate_resolution"})
  })
  Write-RunJson -Path $package.summary -Depth 20 -Value ([ordered]@{schema_version=1;role='mrtof_native_corridor_bunch_screening_summary';status='success';purpose=$(if($diagnosticOnly){$DiagnosticPurpose}else{'candidate_bunch_metrics'});cohort_collection_gate=$cohortGateData;accelerator_field_mode='static';pa_reuse=$paReuse})
  $retention=Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config
  $terminal=Update-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $capacitySession -RemainingCommittedNewBytes 0
  $capacitySession=$terminal.session;$terminalPath=Join-Path $package.result_dir 'artifact_capacity_gate_terminal.json';Write-RunJson -Path $terminalPath -Depth 14 -Value $terminal
  $completeOutputs=@($package.summary,$result,$startup,$terminalPath,$retention)
  Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config -Status success -Software @('SIMION 2020','Python 3.11') -Outputs $completeOutputs
  $terminalized=$true;Write-Host "MRTOF_NATIVE_BUNCH_SCREENING=PASS RUN_ID=$RunId"
}catch{
  if(-not$terminalized){Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config -Summary $package.summary -SummaryRole 'mrtof_native_corridor_bunch_screening_summary' -Reason $_.Exception.Message -Software @('SIMION 2020','Python 3.11') -Status failed -FailureStage $failureStage;$terminalized=$true}
  throw
}finally{
  if($null-ne$nativeRuntimeSession){Suspend-NativeCorridorRuntimeSession -Session $nativeRuntimeSession}
  if(-not$terminalized-and(Test-Path -LiteralPath $package.run_config)){Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config -Summary $package.summary -SummaryRole 'mrtof_native_corridor_bunch_screening_summary' -Reason 'Native corridor bunch screening stopped before terminal publication.' -Software @('SIMION 2020','Python 3.11') -Status interrupted -FailureStage $failureStage}
  if($null-ne$capacitySession){$null=Exit-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $capacitySession}
}

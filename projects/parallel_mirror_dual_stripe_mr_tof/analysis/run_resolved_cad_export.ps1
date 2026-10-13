[CmdletBinding()]
param(
 [Parameter(Mandatory)][string]$FieldRunPath,
 [Parameter(Mandatory)][string]$AssemblyRunPath,
 [Parameter(Mandatory)][string]$RunId,
 [switch]$CheckOnly,[switch]$Smoke,[string]$SmokePart,[string]$ReuseCadRunPath,[switch]$Approved,
 [string]$OriginalStripeRunPath,[string]$StripePoseRunPath,
 [ValidateSet('step','parasolid')][string]$ExchangeFormat='step',
 [string]$PublishCadRunPath,[string]$EnglishOverviewPath,[string]$OverviewManifestPath,
 [switch]$InspectMachiningHoles,[switch]$OmitMountingHoles,[string]$MachiningHoleAuditRunPath,
 [string]$ElectricalStepCadRunPath,[string]$IndividualStepDeliveryRunPath
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$repoRoot=(Resolve-Path (Join-Path $PSScriptRoot '../../..')).Path
$python=Join-Path $repoRoot '.venv/Scripts/python.exe'
. (Join-Path $repoRoot 'common/contracts/run_artifact_support.ps1')
. (Join-Path $repoRoot 'common/host_execution_lease.ps1')
$project='parallel_mirror_dual_stripe_mr_tof'
$allArtifacts=Join-Path (Split-Path -Parent $repoRoot) 'artifacts'
$projectArtifacts=Join-Path $allArtifacts "projects/$project"
$field=(Resolve-Path -LiteralPath $FieldRunPath).Path
$assembly=(Resolve-Path -LiteralPath $AssemblyRunPath).Path
foreach($run in @($field,$assembly)){
 $manifest=Get-Content -LiteralPath (Join-Path $run 'run_manifest.json') -Raw|ConvertFrom-Json
 if($manifest.status-ne'success'-or$manifest.project-ne$project){throw 'CAD requires sealed successful project sources.'}
}
$geometry=Join-Path $field 'inputs/resolved_geometry.json'
$authority=Join-Path $field 'inputs/frozen_input.json'
$materialization=Join-Path $assembly 'results/two_prism_trial_materialization.json'
$publish=$null;$overview=$null;$overviewManifest=$null
if(($EnglishOverviewPath-or$OverviewManifestPath)-and-not($PublishCadRunPath-or$ElectricalStepCadRunPath)){throw 'Word document inputs require publication or electrical STEP scope.'}
if($ElectricalStepCadRunPath-and($EnglishOverviewPath-or$OverviewManifestPath)){
 if(-not$EnglishOverviewPath-or-not$OverviewManifestPath){throw 'English overview and its manifest must be paired.'}
 $overview=(Resolve-Path -LiteralPath $EnglishOverviewPath).Path
 $overviewManifest=(Resolve-Path -LiteralPath $OverviewManifestPath).Path
}
if($PublishCadRunPath){
 if($Smoke-or$SmokePart-or$ReuseCadRunPath-or$OriginalStripeRunPath-or$StripePoseRunPath-or$InspectMachiningHoles-or$OmitMountingHoles-or$MachiningHoleAuditRunPath){throw 'Publication cannot create or revalidate CAD.'}
 $publish=(Resolve-Path -LiteralPath $PublishCadRunPath).Path
 if(-not$EnglishOverviewPath-or-not$OverviewManifestPath){throw 'Publication requires an accepted Word overview and its source manifest.'}
 $overview=(Resolve-Path -LiteralPath $EnglishOverviewPath).Path
 $overviewManifest=(Resolve-Path -LiteralPath $OverviewManifestPath).Path
 $publishedValidation=Get-Content -LiteralPath (Join-Path $publish 'cad_validation.json') -Raw|ConvertFrom-Json
 $ExchangeFormat=[string]$publishedValidation.exchange_format
}
$software=if($publish){@('Python 3.11')}else{@('SolidWorks 2022')}
$committedBytes=if($publish){2*[long](Get-Item -LiteralPath (Join-Path $publish 'mrtof_cad_delivery.zip')).Length+16777216}else{536870912}
$original=$null;$pose=$null;$curveNames=@('s1_electrode_11','s1_electrode_12','s2_electrode_13','s2_electrode_14','central_ion_foil_ground')
$holeAudit=$null
if($MachiningHoleAuditRunPath){
 if(-not$OmitMountingHoles){throw 'Machining audit reference requires no-hole variant.'}
 $holeAudit=(Resolve-Path -LiteralPath $MachiningHoleAuditRunPath).Path
 $holeManifest=Get-Content -LiteralPath (Join-Path $holeAudit 'run_manifest.json') -Raw|ConvertFrom-Json
 if($holeManifest.status-ne'success'-or$holeManifest.project-ne$project){throw 'Original-hole reference requires sealed successful audit.'}
 $inventoryPath=Join-Path $holeAudit 'machining_hole_inventory.json'
 $inventoryRecord=@($holeManifest.outputs|Where-Object{$_.path-eq$inventoryPath})
 if($inventoryRecord.Count-ne1-or$inventoryRecord[0].sha256-ne(Get-FileHash -LiteralPath $inventoryPath).Hash-or$inventoryRecord[0].bytes-ne(Get-Item -LiteralPath $inventoryPath).Length){throw 'Original-hole inventory identity differs.'}
 if((Get-FileHash -LiteralPath (Join-Path $holeAudit 'inputs/resolved_geometry.json')).Hash-ne(Get-FileHash -LiteralPath $geometry).Hash){throw 'Original-hole audit frozen geometry differs.'}
}
if([bool]$OriginalStripeRunPath-ne[bool]$StripePoseRunPath){throw 'Original native and pose runs must be paired.'}
if($OriginalStripeRunPath){
 $original=(Resolve-Path -LiteralPath $OriginalStripeRunPath).Path;$pose=(Resolve-Path -LiteralPath $StripePoseRunPath).Path
 foreach($run in @($original,$pose)){
  $manifest=Get-Content -LiteralPath (Join-Path $run 'run_manifest.json') -Raw|ConvertFrom-Json
  if($manifest.status-ne'success'-or$manifest.project-ne$project){throw 'Original CAD requires successful native/pose audit runs.'}
 }
 if((Get-FileHash -LiteralPath (Join-Path $original 'inputs/resolved_geometry.json')).Hash-ne(Get-FileHash -LiteralPath $geometry).Hash){throw 'Original native audit physical geometry differs.'}
 if(-not$ReuseCadRunPath){throw 'Original Stripe route must reuse the other saved current components.'}
}
$reuse=$null
$electrical=$null
$individual=$null
if($IndividualStepDeliveryRunPath){
 if(-not$ElectricalStepCadRunPath-or$Smoke){throw 'Individual STEP requires a sealed electrical source and complete scope.'}
 $individual=(Resolve-Path -LiteralPath $IndividualStepDeliveryRunPath).Path
 foreach($pair in @(@($geometry,'resolved_geometry.json'),@($authority,'frozen_input.json'),@($materialization,'assembly_materialization.json'))){
  if((Get-FileHash -LiteralPath (Join-Path $individual ('inputs/'+$pair[1]))).Hash-ne(Get-FileHash -LiteralPath $pair[0]).Hash){throw 'Individual STEP prior physical inputs differ.'}
 }
}
if($ElectricalStepCadRunPath){
 if($publish-or$ReuseCadRunPath-or$original-or$InspectMachiningHoles-or$OmitMountingHoles){throw 'Electrical STEP only consumes sealed CAD.'}
 $electrical=(Resolve-Path -LiteralPath $ElectricalStepCadRunPath).Path
 $ExchangeFormat='step'
}
if($ReuseCadRunPath){
 if($Smoke-and(-not$original-or$SmokePart-notin$curveNames)){throw 'Saved-parts smoke is limited to one declared original Stripe part.'}
 $reuse=(Resolve-Path -LiteralPath $ReuseCadRunPath).Path
 $reuseManifest=Get-Content -LiteralPath (Join-Path $reuse 'run_manifest.json') -Raw|ConvertFrom-Json
 $reuseConfig=Get-Content -LiteralPath (Join-Path $reuse 'run_config.json') -Raw|ConvertFrom-Json -AsHashtable
 if($reuseManifest.project-ne$project-or$reuseManifest.status-notin@('success','failed')){throw 'Reuse requires a terminal governed CAD source.'}
 foreach($pair in @(@($geometry,'resolved_geometry.json'),@($authority,'frozen_input.json'),@($materialization,'assembly_materialization.json'))){
  $prior=Join-Path $reuse ('inputs/'+$pair[1])
  if((Get-FileHash -LiteralPath $prior -Algorithm SHA256).Hash-ne(Get-FileHash -LiteralPath $pair[0] -Algorithm SHA256).Hash){throw 'Saved CAD frozen physical inputs differ.'}
 }
 $nativeParts=@(Get-ChildItem -LiteralPath (Join-Path $reuse 'cad') -Filter *.SLDPRT -File)
 if(-not$nativeParts.Count){throw 'No saved native parts to revalidate.'}
 if($ExchangeFormat-eq'step'){foreach($part in $nativeParts){if(-not(Test-Path -LiteralPath (Join-Path $part.DirectoryName ($part.BaseName+'.step')))){throw 'Saved part STEP is missing.'}}}
}
$module='projects.parallel_mirror_dual_stripe_mr_tof.analysis.export_resolved_cad'
$preflight=@('-B','-m',$module,'--geometry',$geometry,'--authority',$authority,'--materialization',$materialization,
 '--output',(Join-Path $projectArtifacts "runs/$RunId/cad"),'--exchange-format',$ExchangeFormat,'--check-only')
if($Smoke){$preflight+='--smoke'}
if($SmokePart){$preflight+=@('--smoke-part',$SmokePart)}
if($original){$preflight+=@('--original-stripe-run',$original,'--stripe-pose-run',$pose)}
if($publish){$preflight+=@('--publish-cad-run',$publish,'--english-overview',$overview,'--overview-manifest',$overviewManifest)}
if($InspectMachiningHoles){$preflight+='--inspect-machining-holes'}
if($OmitMountingHoles){$preflight+='--omit-mounting-holes'}
if($holeAudit){$preflight+=@('--machining-hole-audit-run',$holeAudit)}
if($electrical){$preflight+=@('--electrical-step-cad-run',$electrical)}
if($individual){$preflight+=@('--individual-step-delivery-run',$individual)}
if($electrical-and$overview){$preflight+=@('--english-overview',$overview,'--overview-manifest',$overviewManifest)}
Invoke-RunToolRootContext -RepoRoot $repoRoot -Operation {& $python @preflight;if($LASTEXITCODE-ne0){throw 'CAD physical input preflight failed.'}}
if($CheckOnly){Write-Host 'MRTOF_CAD_CHECK_ONLY=PASS';return}
if(-not$Approved){throw 'Actual CAD export or publication requires -Approved.'}
$package=$null;$capacity=$null;$hostLease=$null
try{
 $package=New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot $projectArtifacts -RunId $RunId -Project $project `
  -Mode $(if($publish){'validated_engineering_cad_publication'}elseif($InspectMachiningHoles){'original_stripe_machining_feature_inventory'}else{'resolved_engineering_cad_export'}) -Software $software -RetentionContractEnabled -RetentionClass solver_review `
  -RetentionReason 'Engineering neutral and native CAD delivery; frozen physical simulation geometry, not manufacturing qualification.' `
  -AdditionalDirectories @('cad') -CapacityLedgerLifecycleEnabled -CapacityLedgerArtifactRoot $allArtifacts
 $capacity=Enter-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -ArtifactRoot $allArtifacts `
  -RunDirectory $package.artifact_run_dir -CommittedNewBytes $committedBytes -Owner "mrtof-cad:$RunId" -ProtectedPaths @($field,$assembly,$reuse,$original,$pose,$publish,$overview,$overviewManifest,$holeAudit,$electrical,$individual|Where-Object {$_})
 $source=Copy-VerifiedRunInput -Source (Join-Path $PSScriptRoot 'export_resolved_cad.py') -Destination (Join-Path $package.input_dir 'cad_exporter.py')
 $null=Copy-VerifiedRunInput -Source $PSCommandPath -Destination (Join-Path $package.input_dir 'launcher.ps1')
 $geometry=Copy-VerifiedRunInput -Source $geometry -Destination (Join-Path $package.input_dir 'resolved_geometry.json')
 $authority=Copy-VerifiedRunInput -Source $authority -Destination (Join-Path $package.input_dir 'frozen_input.json')
 $materialization=Copy-VerifiedRunInput -Source $materialization -Destination (Join-Path $package.input_dir 'assembly_materialization.json')
 $fieldManifest=Copy-VerifiedRunInput -Source (Join-Path $field 'run_manifest.json') -Destination (Join-Path $package.input_dir 'field_manifest.json')
 $assemblyManifest=Copy-VerifiedRunInput -Source (Join-Path $assembly 'run_manifest.json') -Destination (Join-Path $package.input_dir 'assembly_manifest.json')
 $reusedPartFiles=@();$reusedManifest=$null
 if($reuse){
  $reusedManifest=Copy-VerifiedRunInput -Source (Join-Path $reuse 'run_manifest.json') -Destination (Join-Path $package.input_dir 'reused_cad_manifest.json')
  foreach($part in $nativeParts){
   if($Smoke-or$InspectMachiningHoles){continue}
   if($original-and$part.BaseName-in$curveNames){continue}
   $extensions=@('.SLDPRT');if($ExchangeFormat-eq'step'){$extensions+='.step'}
   foreach($extension in $extensions){
    $partFile=Join-Path $part.DirectoryName ($part.BaseName+$extension)
    $reusedPartFiles+=Copy-VerifiedRunInput -Source $partFile -Destination (Join-Path $package.artifact_run_dir ('cad/'+$part.BaseName+$extension))
   }
  }
 }
 $originalInputs=@{}
 if($holeAudit){
  $originalInputs.original_machining_hole_inventory=Copy-VerifiedRunInput -Source (Join-Path $holeAudit 'machining_hole_inventory.json') -Destination (Join-Path $package.input_dir 'original_machining_hole_inventory.json')
  $originalInputs.machining_hole_audit_manifest=Copy-VerifiedRunInput -Source (Join-Path $holeAudit 'run_manifest.json') -Destination (Join-Path $package.input_dir 'machining_hole_audit_manifest.json')
 }
 if($original){
  foreach($entry in @(@($original,'run_manifest.json','original_stripe_manifest.json'),@($pose,'run_manifest.json','stripe_pose_manifest.json'),
    @($original,'inputs/curve_contract.json','stripe_curve_contract.json'),@($original,'results/native_geometry.json','stripe_native_audit.json'),
    @($pose,'results/native_geometry.json','stripe_parent_pose.json'),@($pose,'inputs/child_pose.json','stripe_child_pose.json'),
    @($pose,'inputs/current_frame.json','stripe_frame.json'))){
   $originalInputs[$entry[2]]=Copy-VerifiedRunInput -Source (Join-Path $entry[0] $entry[1]) -Destination (Join-Path $package.input_dir $entry[2])
  }
  $audit=Get-Content -LiteralPath (Join-Path $original 'results/native_geometry.json') -Raw|ConvertFrom-Json
  foreach($pair in @(@(1,'s1_electrode_11'),@(1,'s1_electrode_12'),@(3,'s2_electrode_13'),@(3,'s2_electrode_14'),@(2,'central_ion_foil_ground'))){
   if($Smoke-and$pair[1]-ne$SmokePart){continue}
   $doc=@($audit.documents|Where-Object{$_.name-like "*ion foil $($pair[0]).SLDPRT"})
   if($doc.Count-ne1){throw 'Original native source mapping is not unique.'}
   $nativeSource=[string]$doc[0].path
   if($holeAudit-and$reuse-and$reuseConfig.parameters.ContainsKey('omit_circular_mounting_holes')-and$reuseConfig.parameters.omit_circular_mounting_holes){
    $nativeSource=Join-Path $reuse ('cad/'+$pair[1]+'.SLDPRT')
    $nativeRecord=@($reuseManifest.outputs|Where-Object{$_.path-eq$nativeSource})
    if($nativeRecord.Count-ne1-or$nativeRecord[0].sha256-ne(Get-FileHash -LiteralPath $nativeSource).Hash){throw 'Saved no-hole native source identity differs.'}
   }
   $originalInputs['native_'+$pair[1]]=$nativeSource
   $reusedPartFiles+=Copy-VerifiedRunInput -Source $nativeSource -Destination (Join-Path $package.artifact_run_dir ('cad/'+$pair[1]+'.SLDPRT'))
  }
 }
 $config=Get-Content -LiteralPath $package.run_config -Raw|ConvertFrom-Json -AsHashtable
 $config.inputs=@{geometry=$geometry;authority=$authority;materialization=$materialization;exporter=$source;
  field_manifest=$fieldManifest;assembly_manifest=$assemblyManifest;launcher=(Join-Path $package.input_dir 'launcher.ps1');
  reused_cad_manifest=$reusedManifest}
 if($publish){
  $config.inputs.english_overview=$overview
  $overviewManifest=Copy-VerifiedRunInput -Source $overviewManifest -Destination (Join-Path $package.input_dir 'overview_source_manifest.json')
  $config.inputs.overview_source_manifest=$overviewManifest
  $config.inputs.published_cad_manifest=Copy-VerifiedRunInput -Source (Join-Path $publish 'run_manifest.json') -Destination (Join-Path $package.input_dir 'published_cad_manifest.json')
  $config.inputs.published_cad_zip=Join-Path $publish 'mrtof_cad_delivery.zip'
 }
 if($electrical){
  if($individual){$config.inputs.individual_step_source_manifest=Copy-VerifiedRunInput -Source (Join-Path $individual 'run_manifest.json') -Destination (Join-Path $package.input_dir 'individual_step_source_manifest.json')}
  $config.inputs.electrical_cad_manifest=Copy-VerifiedRunInput -Source (Join-Path $electrical 'run_manifest.json') -Destination (Join-Path $package.input_dir 'electrical_cad_manifest.json')
  $config.inputs.electrical_parts_plan=Copy-VerifiedRunInput -Source (Join-Path $electrical 'cad_parts_plan.json') -Destination (Join-Path $package.input_dir 'electrical_parts_plan.json')
  if($overview){
   $config.inputs.english_overview=$overview
   $overviewManifest=Copy-VerifiedRunInput -Source $overviewManifest -Destination (Join-Path $package.input_dir 'overview_source_manifest.json')
   $config.inputs.overview_source_manifest=$overviewManifest
  }
 }
 foreach($key in $originalInputs.Keys){$config.inputs[$key]=$originalInputs[$key]}
 $config.parameters=@{cad_scope=$(if($electrical){'global_coordinate_electrical_step'}elseif($publish){'documented_validated_delivery_publication'}elseif($InspectMachiningHoles){'read_only_original_machining_feature_inventory'}elseif($Smoke){'single_named_part_smoke'}else{'complete_physical_assembly'});smoke_part=$SmokePart;
  project_units='mm';manufacturing_qualified=$false;committed_new_bytes=$committedBytes;publication_only=[bool]$publish;published_cad_run=$publish;
  omit_circular_mounting_holes=[bool]$OmitMountingHoles;
  machining_hole_audit_run=$holeAudit;
  revalidate_saved_parts=[bool]$reuse;reused_part_copy_paths=$reusedPartFiles;original_stripe_native_reuse=[bool]$original;
  electrical_step_cad_run=$electrical;
  individual_step_delivery_run=$individual;
  step_exchange_tolerance_mm=$(if($electrical){0.005}else{$null});step_exchange_user_approved_date=$(if($electrical){'2026-10-13'}else{$null});step_volume_deviations_reported_separately=[bool]$electrical;
  original_stripe_run=$original;stripe_pose_run=$pose;exchange_format=$ExchangeFormat;curve_representation=$(if($publish-or$electrical){'published_original_native_bspline_and_features'}elseif($original){'original_native_bspline_and_features'}else{'frozen_resolved_polyline'})}
 Write-RunJson -Path $package.run_config -Depth 100 -Value $config
 $cadStage=if($publish){'cad_delivery_publication'}else{'cad_export'}
 $cadBudget=Get-HostResourceBudget -Role GATE -Stage $cadStage
 $cadBudget.memory_bytes=if($publish){536870912}else{8589934592}
 if($publish){$cadBudget.exclusive_resources=@()}else{$cadBudget.exclusive_resources=@('solidworks-2022-cad')}
 $hostLease=Enter-HostResourceStage -Role GATE -Stage $cadStage -RunId $RunId -Budget $cadBudget
 $arguments=@('-B','-m',$module,'--geometry',$geometry,'--authority',$authority,'--materialization',$materialization,
  '--output',(Join-Path $package.artifact_run_dir 'cad'),'--exchange-format',$ExchangeFormat)
 if($Smoke){$arguments+='--smoke'}
 if($SmokePart){$arguments+=@('--smoke-part',$SmokePart)}
 if($reuse){$arguments+='--reuse-saved-parts'}
 if($original){$arguments+=@('--original-stripe-run',$original,'--stripe-pose-run',$pose)}
if($publish){$arguments+=@('--publish-cad-run',$publish,'--english-overview',$overview,'--overview-manifest',$overviewManifest)}
 if($InspectMachiningHoles){$arguments+='--inspect-machining-holes'}
 if($OmitMountingHoles){$arguments+='--omit-mounting-holes'}
 if($holeAudit){$arguments+=@('--machining-hole-audit-run',$holeAudit)}
if($electrical){$arguments+=@('--electrical-step-cad-run',$electrical)}
if($individual){$arguments+=@('--individual-step-delivery-run',$individual)}
if($electrical-and$overview){$arguments+=@('--english-overview',$overview,'--overview-manifest',$overviewManifest)}
 Invoke-RunToolRootContext -RepoRoot $repoRoot -Operation {
  & $python @arguments 1> (Join-Path $package.log_dir 'cad_stdout.log') 2> (Join-Path $package.log_dir 'cad_stderr.log')
  if($LASTEXITCODE-ne0){throw "CAD export/publication failed; see $($package.log_dir)."}
 }
 if($publish){
  $validation=Get-Content -LiteralPath (Join-Path $package.artifact_run_dir 'delivery_publication.json') -Raw|ConvertFrom-Json
  Write-RunJson -Path $package.summary -Value @{status='success';part_count=$validation.part_count;assembly_count=$validation.assembly_count;
   qualification=$validation.qualification;commercial_cad_performed=$false;source_run_id=$validation.source_run_id;
   zip_member_count=$validation.zip_member_count;delivery_publication='delivery_publication.json'}
 }elseif($InspectMachiningHoles){
  $validation=Get-Content -LiteralPath (Join-Path $package.artifact_run_dir 'machining_hole_inventory.json') -Raw|ConvertFrom-Json
  Write-RunJson -Path $package.summary -Value @{status='success';part_count=$validation.component_count;
   qualification=$validation.qualification;geometry_modified=$false;machining_hole_inventory='machining_hole_inventory.json'}
 }else{
  $validation=Get-Content -LiteralPath (Join-Path $package.artifact_run_dir 'cad_validation.json') -Raw|ConvertFrom-Json
  Write-RunJson -Path $package.summary -Value @{status='success';part_count=$validation.component_count;
   solidworks_revision=$validation.solidworks_revision;qualification=$validation.qualification;cad_validation='cad_validation.json'}
 }
 $null=Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config
 $outputs=@(Get-ChildItem -LiteralPath $package.artifact_run_dir -Recurse -File|Where-Object{$_.FullName-notlike "$($package.input_dir)*"-and$_.FullName-ne$package.run_config-and$_.Name-ne'run_manifest.json'}|Select-Object -ExpandProperty FullName)
 Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config -Status success `
  -Software $software -Outputs $outputs|Out-Host
 Write-Host "MRTOF_CAD_RUN=SUCCESS $($package.artifact_run_dir)"
}catch{
 if($null-ne$package){
  $failedOutputs=@(Get-ChildItem -LiteralPath $package.artifact_run_dir -Recurse -File|Where-Object{$_.FullName-notlike "$($package.input_dir)*"-and$_.FullName-ne$package.run_config-and$_.Name-ne'run_manifest.json'}|Select-Object -ExpandProperty FullName)
  Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config -Summary $package.summary `
   -SummaryRole mrtof_cad_export_summary -Reason $_.Exception.Message -Software $software -AdditionalOutputs $failedOutputs|Out-Host
 }
 throw
}finally{
 if($null-ne$hostLease){Exit-HostExecutionLease -Lease $hostLease}
 if($null-ne$capacity){Exit-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $capacity}
}

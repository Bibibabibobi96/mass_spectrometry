[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$PackagePath,
    [Parameter(Mandatory)][string]$RunId,
    [Parameter(Mandatory)][string]$RootRunId,
    [Parameter(Mandatory)][string]$PABuildRunPath,
    [Parameter(Mandatory)][string]$RuntimeControllerPath,
    [Parameter(Mandatory)][string]$CampaignPath,
    [Parameter(Mandatory)][string]$ReleaseSpecPath,
    [Parameter(Mandatory)][string]$WorkspaceRoot,
    [Parameter(Mandatory)][string]$ArtifactRoot,
    [string]$PythonExe='',
    [string]$InitialAnalysisPath='',
    [ValidateRange(4,20)][int]$MaximumTrials=7,
    [string]$SimionExe=''
)
# Store-stage scientific action, not a public run/lifecycle entrypoint.
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$workspaceRoot=(Resolve-Path -LiteralPath $WorkspaceRoot).Path;$artifactRoot=$ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($ArtifactRoot)
$python=if($PythonExe){[IO.Path]::GetFullPath($PythonExe)}elseif($env:SIMULATION_PYTHON_EXE){[IO.Path]::GetFullPath($env:SIMULATION_PYTHON_EXE)}else{throw 'Explicit PythonExe or SIMULATION_PYTHON_EXE is required'}
$packageRootText=& $python -I -B -c 'from pathlib import Path;import msplatform;print(Path(msplatform.__file__).resolve().parent)'
if($LASTEXITCODE-ne0){throw 'Installed msplatform package is unavailable.'};$packageRoot=(Resolve-Path -LiteralPath $packageRootText).Path
$entryPackageRoot=Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
if(-not[string]::Equals($packageRoot,[IO.Path]::GetFullPath($entryPackageRoot),[StringComparison]::OrdinalIgnoreCase)){throw 'Selected Python msplatform package differs from the entry package.'}
$repoRoot=Split-Path -Parent $packageRoot
$executionResources=Join-Path $packageRoot 'execution/resources';$simionResources=Join-Path $packageRoot 'backends/simion/resources'
. (Join-Path $executionResources 'workspace_paths.ps1');$componentArtifactRoot=Resolve-RunArtifactRoot -ArtifactRoot $artifactRoot -OwnerKind component -OwnerId orthogonal_accelerator -Python $python
. (Join-Path $executionResources 'require_powershell7.ps1')
. (Join-Path $executionResources 'run_artifact_support.ps1')
. (Join-Path $simionResources 'focus_python.ps1')
if(-not$SimionExe){$SimionExe=Join-Path $env:ProgramFiles 'SIMION-2020\simion.exe'}
foreach($item in @($python,$SimionExe,$CampaignPath,$ReleaseSpecPath)){if(-not(Test-Path -LiteralPath $item -PathType Leaf)){throw "Required Fast-Adjust input is missing: $item"}}
$family=(Resolve-Path -LiteralPath $PABuildRunPath).Path
& $python -I -B -c 'from msplatform.execution.manifest_verification import main; from msplatform.backends.simion.native_completion import retention_api; main(retention_api=retention_api)' (Join-Path $family 'run_manifest.json') --require-status success --require-project orthogonal_accelerator --require-mode component_focus_pa_build
if($LASTEXITCODE-ne0){throw 'Fast-Adjust controller requires a verified published provider PA build run'}
$package=Get-Content -LiteralPath $PackagePath -Raw -Encoding UTF8|ConvertFrom-Json
$stage='freeze_inputs'
try {
    $campaign=Copy-VerifiedRunInput (Resolve-Path -LiteralPath $CampaignPath).Path (Join-Path $package.input_dir 'campaign.json')
    $release=Copy-VerifiedRunInput (Resolve-Path -LiteralPath $ReleaseSpecPath).Path (Join-Path $package.input_dir 'release_spec.json')
    $state=Join-Path $package.result_dir 'fast_adjust_controller_state.json'
    $focusPython=Initialize-FocusFrozenPython -PackageRoot $packageRoot -RunConfig $package.run_config -Python $python -CampaignPath $campaign -InputNames @('campaign.json','release_spec.json')
    $componentContract=Join-Path $focusPython.code_root 'src/msplatform/components/orthogonal_accelerator/component_contract.json'
    $stateArguments=@('--component-contract',$componentContract,'--campaign',$campaign,'--state',$state,'--maximum-trials',$MaximumTrials)
    Invoke-FocusFrozenPython -Python $python -CodeRoot $focusPython.code_root -OriginsPath $focusPython.origins_path -Module msplatform.workflows.oa_focus_fast_adjust -Arguments $stateArguments;if($LASTEXITCODE-ne0){throw 'Fast-Adjust controller initialization failed'}
    if($InitialAnalysisPath){
        $initialAnalysis=(Resolve-Path -LiteralPath $InitialAnalysisPath).Path
        $stage='record_initial_theory_flight';Invoke-FocusFrozenPython -Python $python -CodeRoot $focusPython.code_root -OriginsPath $focusPython.origins_path -Module msplatform.workflows.oa_focus_fast_adjust -Arguments @('--component-contract',$componentContract,'--campaign',$campaign,'--state',$state,'--analysis',$initialAnalysis);if($LASTEXITCODE-ne0){throw 'Fast-Adjust initial-theory analysis recording failed'}
    }
    $trials=@()
    for($index=0;$index-lt$MaximumTrials;$index++){
        $current=Get-Content -Raw -LiteralPath $state|ConvertFrom-Json -Depth 16
        if([string]$current.status -ne 'running' -or $null -eq $current.next_parameters){break}
        $candidate=Join-Path $package.result_dir ("candidate_campaign_{0}.json" -f $index)
        $stage="derive_candidate_$index";Invoke-FocusFrozenPython -Python $python -CodeRoot $focusPython.code_root -OriginsPath $focusPython.origins_path -Module msplatform.workflows.oa_focus_fast_adjust -Arguments @('--component-contract',$componentContract,'--campaign',$campaign,'--state',$state,'--candidate-campaign',$candidate);if($LASTEXITCODE-ne0){throw 'Fast-Adjust candidate derivation failed'}
        $childRunId="$RootRunId`__fast-adjust-trial$index`__r$('{0:d2}' -f ($index + 2))"
        $stage="flight_$index";$childReceipt=Join-Path $package.input_dir "fast-adjust-result-$index.json";&$python -I -B -m msplatform.workflows.oa_focus_component --action flight --run-id $childRunId --pa-build-run-path $family --runtime-controller-path $RuntimeControllerPath --campaign-path $candidate --release-spec-path $release --workspace-root $workspaceRoot --store-root $artifactRoot --receipt-path $childReceipt --powershell-exe (Get-Process -Id $PID).Path --simion-exe $SimionExe
        if($LASTEXITCODE-ne0){throw 'Fast-Adjust trial flight failed'}
        $childResult=Get-Content -LiteralPath $childReceipt -Raw -Encoding UTF8|ConvertFrom-Json
        $childRun=Split-Path -Parent ([string]$childResult.manifest.path)
        $childManifest=[string]$childResult.manifest.path;$analysis=Join-Path $childRun 'results\focus_analysis.json'
        foreach($required in @($childManifest,$analysis)){if(-not(Test-Path -LiteralPath $required -PathType Leaf)){throw "Fast-Adjust trial output is missing: $required"}}
        $stage="record_trial_$index";Invoke-FocusFrozenPython -Python $python -CodeRoot $focusPython.code_root -OriginsPath $focusPython.origins_path -Module msplatform.workflows.oa_focus_fast_adjust -Arguments @('--component-contract',$componentContract,'--campaign',$campaign,'--state',$state,'--analysis',$analysis);if($LASTEXITCODE-ne0){throw 'Fast-Adjust trial analysis recording failed'}
        $analysisValue=Get-Content -Raw -LiteralPath $analysis|ConvertFrom-Json -Depth 16
        $record=@((Get-Content -Raw -LiteralPath $state|ConvertFrom-Json -Depth 16).records)[-1]
        $trials+=@([ordered]@{index=$index;run_id=$childRunId;run_directory=$childRun;kind=[string]$record.kind;parameters=$record.parameters;maximum_normalized_residual=[double]$record.maximum_normalized_residual;score=[double]$record.score;candidate_campaign_sha256=(Get-FileHash $candidate -Algorithm SHA256).Hash;manifest_sha256=(Get-FileHash $childManifest -Algorithm SHA256).Hash;analysis_sha256=(Get-FileHash $analysis -Algorithm SHA256).Hash;peak_to_peak_t_ns=[double]$analysisValue.focus_metrics.peak_to_peak_t_ns;status=[string]$analysisValue.status})
    }
    $final=Get-Content -Raw -LiteralPath $state|ConvertFrom-Json -Depth 16
    if([string]$final.status-notin@('accepted','exhausted')){throw 'Fast-Adjust controller did not reach a terminal bounded state'}
    $selectedCampaign=''
    $bestCampaign=Join-Path $package.result_dir 'best_campaign.json'
    $stage='write_best_campaign';Invoke-FocusFrozenPython -Python $python -CodeRoot $focusPython.code_root -OriginsPath $focusPython.origins_path -Module msplatform.workflows.oa_focus_fast_adjust -Arguments @('--component-contract',$componentContract,'--campaign',$campaign,'--state',$state,'--best-campaign',$bestCampaign);if($LASTEXITCODE-ne0){throw 'Fast-Adjust best campaign derivation failed'}
    $acceptedTrial=$null
    if([string]$final.status -eq 'accepted'){
        $acceptedRecords=@($final.records|Where-Object{[bool]$_.accepted})
        if($acceptedRecords.Count-ne1){throw 'Fast-Adjust accepted state must identify exactly one trial'}
        $acceptedMatches=@($trials|Where-Object{[string]$_.analysis_sha256-eq[string]$acceptedRecords[0].analysis_sha256})
        if($acceptedMatches.Count-ne1){throw 'Fast-Adjust accepted trial identity is unavailable'}
        $acceptedTrial=$acceptedMatches[0]
        $selectedCampaign=Join-Path $package.result_dir 'accepted_campaign.json'
        $stage='write_accepted_campaign';Invoke-FocusFrozenPython -Python $python -CodeRoot $focusPython.code_root -OriginsPath $focusPython.origins_path -Module msplatform.workflows.oa_focus_fast_adjust -Arguments @('--component-contract',$componentContract,'--campaign',$campaign,'--state',$state,'--selected-campaign',$selectedCampaign);if($LASTEXITCODE-ne0){throw 'Fast-Adjust accepted campaign derivation failed'}
    }
    $receipt=Join-Path $package.result_dir 'component_focus_fast_adjust_receipt.json'
    [ordered]@{schema_version=1;role='orthogonal_accelerator_component_focus_fast_adjust_receipt';status=[string]$final.status;qualification='candidate_prototype_numeric_component_focus_only';controller_state_sha256=(Get-FileHash $state -Algorithm SHA256).Hash;pa_build_run_manifest_sha256=(Get-FileHash (Join-Path $family 'run_manifest.json') -Algorithm SHA256).Hash;pa_policy='published_read_only_native_fast_adjust_family__no_build_copy_or_refine';best_campaign_sha256=(Get-FileHash $bestCampaign -Algorithm SHA256).Hash;best_record=$final.records[([int]$final.best_record_index)];accepted_campaign_sha256=$(if($selectedCampaign){(Get-FileHash $selectedCampaign -Algorithm SHA256).Hash}else{$null});accepted_trial=$acceptedTrial;trial_count=$trials.Count;trials=$trials}|ConvertTo-Json -Depth 16|Set-Content $receipt -Encoding utf8
    $summary=[ordered]@{schema_version=1;role='orthogonal_accelerator_component_focus_fast_adjust';status=[string]$final.status;qualification='candidate_prototype_numeric_component_focus_only';trial_count=$trials.Count;receipt_sha256=(Get-FileHash $receipt -Algorithm SHA256).Hash};Write-RunJson -Path $package.summary -Depth 16 -Value $summary
    $outputs=@($package.summary,$state,$receipt,$bestCampaign,$focusPython.origins_path)+@(Get-ChildItem -LiteralPath $package.result_dir -Filter 'candidate_campaign_*.json' -File|ForEach-Object{$_.FullName})
    if($selectedCampaign){$outputs+=@($selectedCampaign)}
    Write-RunJson -Path (Join-Path $package.result_dir 'action_publication.json') -Depth 8 -Value ([ordered]@{schema_version=1;role='oa_focus_action_publication';outputs=$outputs})
}catch{throw
}

[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$RunId,
    [Parameter(Mandatory)][string]$RootRunId,
    [Parameter(Mandatory)][string]$PABuildRunPath,
    [Parameter(Mandatory)][string]$CampaignPath,
    [Parameter(Mandatory)][string]$ReleaseSpecPath,
    [Parameter(Mandatory)][double[]]$Gap1VoltageDropBoundsV,
    [string]$InitialAnalysisPath='',
    [ValidateRange(3,5)][int]$MaximumTrials=5,
    [string]$SimionExe=''
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$projectRoot=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$repoRoot=(Resolve-Path (Join-Path $projectRoot '..\..')).Path
$workspaceRoot=(Resolve-Path (Join-Path $repoRoot '..')).Path
. (Join-Path $repoRoot 'common\require_powershell7.ps1')
. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')
$python=Join-Path $repoRoot '.venv\Scripts\python.exe'
if(-not$SimionExe){$SimionExe=Join-Path $env:ProgramFiles 'SIMION-2020\simion.exe'}
foreach($item in @($python,$SimionExe,$CampaignPath,$ReleaseSpecPath)){if(-not(Test-Path -LiteralPath $item -PathType Leaf)){throw "Required Fast-Adjust input is missing: $item"}}
if($Gap1VoltageDropBoundsV.Count-ne2){throw 'Gap1VoltageDropBoundsV requires exactly two values'}
$family=(Resolve-Path -LiteralPath $PABuildRunPath).Path
& $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') (Join-Path $family 'run_manifest.json') --require-status success --require-project orthogonal_accelerator --require-mode component_focus_pa_build
if($LASTEXITCODE-ne0){throw 'Fast-Adjust controller requires a verified published provider PA build run'}
$artifactRoot=Join-Path $workspaceRoot 'artifacts'
$package=New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot (Join-Path $artifactRoot 'projects\orthogonal_accelerator') -RunId $RunId -Project orthogonal_accelerator -Mode component_focus_fast_adjust -Software @('SIMION 2020','Python 3.11') -RetentionContractEnabled -RetentionClass solver_review -RetentionReason 'Bounded provider-owned component voltage search using one existing published native Fast-Adjust PA family.' -AdditionalDirectories @('simion') -UseShortExecutionPath -CapacityLedgerLifecycleEnabled
$done=$false;$failureDetail='';$stage='freeze_inputs'
try {
    $campaign=Copy-VerifiedRunInput (Resolve-Path -LiteralPath $CampaignPath).Path (Join-Path $package.input_dir 'campaign.json')
    $release=Copy-VerifiedRunInput (Resolve-Path -LiteralPath $ReleaseSpecPath).Path (Join-Path $package.input_dir 'release_spec.json')
    $flightRunner=Join-Path $PSScriptRoot 'run_component_focus_flight.ps1'
    $state=Join-Path $package.result_dir 'fast_adjust_controller_state.json'
    $stateArguments=@('-m','projects.orthogonal_accelerator.analysis.component_focus_fast_adjust','--campaign',$campaign,'--state',$state,'--bounds-v',$Gap1VoltageDropBoundsV[0],$Gap1VoltageDropBoundsV[1],'--maximum-trials',$MaximumTrials)
    Push-Location $repoRoot;try{&$python @stateArguments;if($LASTEXITCODE-ne0){throw 'Fast-Adjust controller initialization failed'}}finally{Pop-Location}
    if($InitialAnalysisPath){
        $initialAnalysis=(Resolve-Path -LiteralPath $InitialAnalysisPath).Path
        $stage='record_initial_theory_flight';Push-Location $repoRoot;try{&$python -m projects.orthogonal_accelerator.analysis.component_focus_fast_adjust --campaign $campaign --state $state --analysis $initialAnalysis;if($LASTEXITCODE-ne0){throw 'Fast-Adjust initial-theory analysis recording failed'}}finally{Pop-Location}
    }
    $trials=@()
    for($index=0;$index-lt$MaximumTrials;$index++){
        $current=Get-Content -Raw -LiteralPath $state|ConvertFrom-Json -Depth 16
        if([string]$current.status -ne 'running' -or $null -eq $current.next_gap1_voltage_drop_v){break}
        $candidate=Join-Path $package.result_dir ("candidate_campaign_{0}.json" -f $index)
        $stage="derive_candidate_$index";Push-Location $repoRoot;try{&$python -m projects.orthogonal_accelerator.analysis.component_focus_fast_adjust --campaign $campaign --state $state --candidate-campaign $candidate;if($LASTEXITCODE-ne0){throw 'Fast-Adjust candidate derivation failed'}}finally{Pop-Location}
        $childRunId="$RootRunId`__fast-adjust-trial$index`__r$('{0:d2}' -f ($index + 2))"
        $stage="flight_$index";&$flightRunner -RunId $childRunId -PABuildRunPath $family -CampaignPath $candidate -ReleaseSpecPath $release -SimionExe $SimionExe
        if($LASTEXITCODE-ne0){throw 'Fast-Adjust trial flight failed'}
        $childRun=Join-Path $artifactRoot (Join-Path 'projects\orthogonal_accelerator\runs' $childRunId)
        $childManifest=Join-Path $childRun 'run_manifest.json';$analysis=Join-Path $childRun 'results\focus_analysis.json'
        foreach($required in @($childManifest,$analysis)){if(-not(Test-Path -LiteralPath $required -PathType Leaf)){throw "Fast-Adjust trial output is missing: $required"}}
        $stage="record_trial_$index";Push-Location $repoRoot;try{&$python -m projects.orthogonal_accelerator.analysis.component_focus_fast_adjust --campaign $campaign --state $state --analysis $analysis;if($LASTEXITCODE-ne0){throw 'Fast-Adjust trial analysis recording failed'}}finally{Pop-Location}
        $analysisValue=Get-Content -Raw -LiteralPath $analysis|ConvertFrom-Json -Depth 16
        $trials+=@([ordered]@{index=$index;run_id=$childRunId;candidate_campaign_sha256=(Get-FileHash $candidate -Algorithm SHA256).Hash;manifest_sha256=(Get-FileHash $childManifest -Algorithm SHA256).Hash;analysis_sha256=(Get-FileHash $analysis -Algorithm SHA256).Hash;peak_to_peak_t_ns=[double]$analysisValue.focus_metrics.peak_to_peak_t_ns;status=[string]$analysisValue.status})
    }
    $final=Get-Content -Raw -LiteralPath $state|ConvertFrom-Json -Depth 16
    if([string]$final.status-notin@('accepted','exhausted')){throw 'Fast-Adjust controller did not reach a terminal bounded state'}
    $selectedCampaign=''
    if([string]$final.status -eq 'accepted'){
        $selectedCampaign=Join-Path $package.result_dir 'accepted_campaign.json'
        $stage='write_accepted_campaign';Push-Location $repoRoot;try{&$python -m projects.orthogonal_accelerator.analysis.component_focus_fast_adjust --campaign $campaign --state $state --selected-campaign $selectedCampaign;if($LASTEXITCODE-ne0){throw 'Fast-Adjust accepted campaign derivation failed'}}finally{Pop-Location}
    }
    $receipt=Join-Path $package.result_dir 'component_focus_fast_adjust_receipt.json'
    [ordered]@{schema_version=1;role='orthogonal_accelerator_component_focus_fast_adjust_receipt';status=[string]$final.status;qualification='candidate_prototype_numeric_component_focus_only';controller_state_sha256=(Get-FileHash $state -Algorithm SHA256).Hash;pa_build_run_manifest_sha256=(Get-FileHash (Join-Path $family 'run_manifest.json') -Algorithm SHA256).Hash;pa_policy='published_read_only_native_fast_adjust_family__no_build_copy_or_refine';accepted_campaign_sha256=$(if($selectedCampaign){(Get-FileHash $selectedCampaign -Algorithm SHA256).Hash}else{$null});trial_count=$trials.Count;trials=$trials}|ConvertTo-Json -Depth 16|Set-Content $receipt -Encoding utf8
    $summary=[ordered]@{schema_version=1;role='orthogonal_accelerator_component_focus_fast_adjust';status=[string]$final.status;qualification='candidate_prototype_numeric_component_focus_only';trial_count=$trials.Count;receipt_sha256=(Get-FileHash $receipt -Algorithm SHA256).Hash};Write-RunJson -Path $package.summary -Depth 16 -Value $summary
    $outputs=@($package.summary,$state,$receipt)+@(Get-ChildItem -LiteralPath $package.result_dir -Filter 'candidate_campaign_*.json' -File|ForEach-Object{$_.FullName})
    if($selectedCampaign){$outputs+=@($selectedCampaign)}
    Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config -Status success -Software @('SIMION 2020','Python 3.11') -Outputs $outputs
    $done=$true
}catch{$failureDetail=$_.Exception.Message;throw
}finally{if(-not$done){$reason="Fast-Adjust controller failed at $stage.";if(-not[string]::IsNullOrWhiteSpace($failureDetail)){$reason+=" $failureDetail"};Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config -Summary $package.summary -SummaryRole orthogonal_accelerator_component_focus_fast_adjust -Reason $reason -Software @('SIMION 2020','Python 3.11') -Status failed};Remove-RunPackageExecutionAlias -Package $package}

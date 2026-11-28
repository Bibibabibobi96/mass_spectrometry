[CmdletBinding()]
param([Parameter(Mandatory)][string]$PackagePath,[Parameter(Mandatory)][string]$RunId,[Parameter(Mandatory)][string]$RootRunId,[Parameter(Mandatory)][string]$PABuildRunPath,[Parameter(Mandatory)][string]$RuntimeControllerPath,[Parameter(Mandatory)][string]$CampaignPath,[Parameter(Mandatory)][string]$ReleaseSpecPath,[Parameter(Mandatory)][string]$InitialAnalysisPath,[Parameter(Mandatory)][string]$WorkspaceRoot,[Parameter(Mandatory)][string]$ArtifactRoot,[string]$PythonExe='',[string]$SimionExe='')
# Store-stage scientific action, not a public run/lifecycle entrypoint.
Set-StrictMode -Version Latest;$ErrorActionPreference='Stop'
$workspaceRoot=(Resolve-Path -LiteralPath $WorkspaceRoot).Path;$artifactRoot=$ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($ArtifactRoot)
$python=if($PythonExe){[IO.Path]::GetFullPath($PythonExe)}elseif($env:SIMULATION_PYTHON_EXE){[IO.Path]::GetFullPath($env:SIMULATION_PYTHON_EXE)}else{throw 'Explicit PythonExe or SIMULATION_PYTHON_EXE is required'}
$packageRootText=& $python -I -B -c 'from pathlib import Path;import msplatform;print(Path(msplatform.__file__).resolve().parent)'
if($LASTEXITCODE-ne0){throw 'Installed msplatform package is unavailable.'};$packageRoot=(Resolve-Path -LiteralPath $packageRootText).Path
$entryPackageRoot=Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
if(-not[string]::Equals($packageRoot,[IO.Path]::GetFullPath($entryPackageRoot),[StringComparison]::OrdinalIgnoreCase)){throw 'Selected Python msplatform package differs from the entry package.'}
$repoRoot=Split-Path -Parent $packageRoot
$executionResources=Join-Path $packageRoot 'execution/resources';$simionResources=Join-Path $packageRoot 'backends/simion/resources'
. (Join-Path $executionResources 'workspace_paths.ps1');$componentArtifactRoot=Resolve-RunArtifactRoot -ArtifactRoot $artifactRoot -OwnerKind component -OwnerId orthogonal_accelerator -Python $python
. (Join-Path $executionResources 'require_powershell7.ps1');. (Join-Path $executionResources 'run_artifact_support.ps1')
$package=Get-Content -LiteralPath $PackagePath -Raw -Encoding UTF8|ConvertFrom-Json
$stage='freeze_inputs';try {
 $campaign=Copy-VerifiedRunInput (Resolve-Path $CampaignPath).Path (Join-Path $package.input_dir 'campaign.json');$release=Copy-VerifiedRunInput (Resolve-Path $ReleaseSpecPath).Path (Join-Path $package.input_dir 'release_spec.json');$native=Copy-VerifiedRunInput (Resolve-Path $InitialAnalysisPath).Path (Join-Path $package.input_dir 'native_focus_analysis.json')
 $analyses=@{native=$native};$manifests=@{}
 $rootStamp=($RootRunId -split '__',2)[0]
 if($rootStamp -notmatch '^\d{8}_\d{6}$'){throw 'RootRunId does not begin with a valid artifact timestamp.'}
 $hash=[Security.Cryptography.SHA256]::Create();try{$rootToken=([BitConverter]::ToString($hash.ComputeHash([Text.Encoding]::UTF8.GetBytes($RootRunId))).Replace('-','').Substring(0,8)).ToLowerInvariant()}finally{$hash.Dispose()}
 foreach($mode in @('zone1_ideal','zone2_ideal','full_ideal')){
  $stage=$mode;$safeMode=$mode.Replace('_','-');$childRunId="$rootStamp`__sim__simion__oa-field-$safeMode-$rootToken`__r01";$childReceipt=Join-Path $package.input_dir "field-$mode-result.json";&$python -I -B -m msplatform.workflows.oa_focus_component --action flight --run-id $childRunId --pa-build-run-path $PABuildRunPath --runtime-controller-path $RuntimeControllerPath --campaign-path $campaign --release-spec-path $release --field-mode $mode --workspace-root $workspaceRoot --store-root $artifactRoot --receipt-path $childReceipt --powershell-exe (Get-Process -Id $PID).Path --simion-exe $SimionExe;if($LASTEXITCODE-ne0){throw "Ideal-field child failed: $mode"}
  $childResult=Get-Content -LiteralPath $childReceipt -Raw -Encoding UTF8|ConvertFrom-Json;$child=Split-Path -Parent ([string]$childResult.manifest.path);$analyses[$mode]=Join-Path $child 'results\focus_analysis.json';$manifests[$mode]=(Get-FileHash ([string]$childResult.manifest.path) -Algorithm SHA256).Hash
 }
 $out=Join-Path $package.result_dir 'two_zone_ideal_field_contrast.json';&$python -I -B -m msplatform.workflows.oa_focus_field_contrast --native $analyses.native --zone1-ideal $analyses.zone1_ideal --zone2-ideal $analyses.zone2_ideal --full-ideal $analyses.full_ideal --output $out;if($LASTEXITCODE-ne0){throw 'Ideal field contrast analysis failed'}
 $summary=[ordered]@{schema_version=1;role='orthogonal_accelerator_component_focus_field_contrast';status='diagnostic';native_analysis_sha256=(Get-FileHash $native -Algorithm SHA256).Hash;child_manifest_sha256=$manifests;contrast_sha256=(Get-FileHash $out -Algorithm SHA256).Hash};Write-RunJson -Path $package.summary -Depth 16 -Value $summary
 Write-RunJson -Path (Join-Path $package.result_dir 'action_publication.json') -Depth 8 -Value ([ordered]@{schema_version=1;role='oa_focus_action_publication';outputs=@($package.summary,$out)})
}catch{throw
}

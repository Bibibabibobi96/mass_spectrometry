param(
    [string]$RequestPath,
    [Parameter(Mandatory=$true)][string]$RunDirectory,
    [Parameter(Mandatory=$true)][string]$WorkspaceRoot,
    [Parameter(Mandatory=$true)][string]$ArtifactRoot,
    [Parameter(Mandatory=$true)][string]$PythonExe,
    [switch]$Approved,
    [switch]$Child
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$RunDirectory=$ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($RunDirectory)
$repo=(Resolve-Path -LiteralPath $WorkspaceRoot).Path
$artifactWorkspaceRoot=$ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($ArtifactRoot)
$python=[IO.Path]::GetFullPath($PythonExe)
$packageRootText=& $python -I -B -c 'from pathlib import Path;import msplatform;print(Path(msplatform.__file__).resolve().parent)'
if($LASTEXITCODE-ne0-or[string]::IsNullOrWhiteSpace([string]$packageRootText)){throw 'Installed msplatform package is unavailable.'}
$packageRoot=(Resolve-Path -LiteralPath ([string]$packageRootText).Trim()).Path
$executionResources=Join-Path $packageRoot 'execution/resources'
. (Join-Path $executionResources 'require_powershell7.ps1')
. (Join-Path $executionResources 'run_artifact_support.ps1')
$hostState=Join-Path $artifactWorkspaceRoot 'common/host_resources.sqlite3'
$hostContext=@{workspace=$repo;python_executable=$python;host_state_path=$hostState;policy_path=(Join-Path $executionResources 'host_resource_policy.json')}
. (Join-Path $executionResources 'host_execution_lease.ps1') -HostContext $hostContext
if($RequestPath){$RequestPath=(Resolve-Path -LiteralPath $RequestPath).Path}
$preparedConfig=Join-Path $RunDirectory 'run_config.json'
if($Child){
    $plan=Get-Content (Join-Path $PSScriptRoot 'plan.json') -Raw | ConvertFrom-Json
    $env:MRTOF_COMSOL_RESOURCE_DIRECTORY=[string]$plan.matlab_resource_directory
    if(-not(Test-Path -LiteralPath (Join-Path $env:MRTOF_COMSOL_RESOURCE_DIRECTORY 'update_corridor_workpoint_voltages.m'))){throw 'Installed COMSOL MATLAB resource closure is missing.'}
    . (Join-Path $executionResources 'resource_process_support.ps1')
    $budget=Get-HostResourceBudget -Role COMSOL -Stage solver
    $launcherOptions=@{}
    if($plan.PSObject.Properties.Name -contains 'comsol_allocator'){
        $launcherOptions.Allocator=[string]$plan.comsol_allocator
    }
    # Observation warnings do not override the repository solver admission budget.
    $comsolLauncher=Join-Path $packageRoot 'backends/comsol/launcher/run_comsol_r2025b.ps1'
    . (Join-Path (Split-Path -Parent $comsolLauncher) 'resolve_comsol_64.ps1')
    $comsolLauncherParameters=Get-ComsolLauncherParameters -HostContext $script:HostResourceExecutionContext -WorkingDirectory $script:HostResourceExecutionContext.workspace
    & $comsolLauncher @comsolLauncherParameters `
        -TaskScript (Join-Path $PSScriptRoot 'candidate_field.m') `
        -ReportPath (Join-Path $PSScriptRoot 'bootstrap_report.txt') `
        -StartupAttempts 1 -StartupReportTimeoutAction warn `
        -ResourceBudgets @{solver=$budget} -RunId ([string]$plan.run_id) @launcherOptions
    return # Public PS entry returns on success and throws on failure, not LASTEXITCODE.
}
if($env:MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN){throw 'Field provider must run outside a held SIMION/host lease; release the caller stage first.'}
if(-not(Test-Path -LiteralPath $preparedConfig)){
    if(-not $RequestPath){throw 'New preparation requires RequestPath.'}
    & $python -I -B -m msplatform.backends.comsol.corridor_field --request $RequestPath --run-directory $RunDirectory --repository-root $repo --runner-path (Join-Path $packageRoot 'backends/comsol/launcher/run_corridor_field_provider.ps1')
    if($LASTEXITCODE -ne 0){throw 'Candidate field preparation failed.'}
}elseif($RequestPath){throw 'Prepared input is frozen; omit RequestPath when approving that run.'}
if(-not $Approved){return}
$inputs=Join-Path $RunDirectory 'inputs'
if((Test-Path (Join-Path $RunDirectory 'run_manifest.json')) -or (Test-Path (Join-Path $inputs 'provider.stdout.log'))){throw 'Existing attempt/terminal identity; no automatic retry.'}
$plan=Get-Content (Join-Path $inputs 'plan.json') -Raw | ConvertFrom-Json
. (Join-Path $executionResources 'resource_process_support.ps1')
$capacity=$null
$process=$null
$outcome='failed'
$failure=$null
$watch=[Diagnostics.Stopwatch]::StartNew()
$peak=[int64]0
$tracked=@()
$ticks=@{}
$rootTicks=@{}
$warnings=@{wall=$false;memory=$false;artifact=$false}
try{
    $capacity=Enter-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repo `
        -ArtifactRoot $artifactWorkspaceRoot -RunDirectory $RunDirectory `
        -CommittedNewBytes ([int64]$plan.artifact_budget_bytes) `
        -ProtectedPaths @([string]$plan.source_mph) -Owner 'mrtof-same-mesh-field-provider'
    $arguments='-NoProfile -File "'+(Join-Path $inputs 'run_corridor_field_provider.ps1')+'" -Child -RunDirectory "'+$RunDirectory+'" -WorkspaceRoot "'+$repo+'" -ArtifactRoot "'+$artifactWorkspaceRoot+'" -PythonExe "'+$python+'"'
    $process=Start-Process -FilePath (Get-Process -Id $PID).Path -ArgumentList $arguments `
        -WorkingDirectory $inputs -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $inputs 'provider.stdout.log') `
        -RedirectStandardError (Join-Path $inputs 'provider.stderr.log')
    $rootTicks[[string]$process.Id]=$process.StartTime.ToUniversalTime().Ticks
    while(-not $process.HasExited){
        $sample=Get-ManagedSolverProcessSample -RootProcessIds @($process.Id) -TrackedProcessIds $tracked `
            -RootProcessStartedAtUtcTicks $rootTicks -TrackedProcessStartedAtUtcTicks $ticks
        $tracked=$sample.tracked_process_ids
        $ticks=$sample.tracked_process_started_at_utc_ticks
        $peak=[Math]::Max($peak,[int64]$sample.managed_memory_bytes)
        $bytes=[int64](Get-ChildItem -LiteralPath $RunDirectory -File -Recurse | Measure-Object Length -Sum).Sum
        $exceeded=@{wall=($watch.Elapsed.TotalSeconds -gt $plan.solve_seconds);memory=($peak -gt $plan.solve_memory_bytes);artifact=($bytes -gt $plan.artifact_budget_bytes)}
        foreach($name in $exceeded.Keys){
            if($exceeded[$name] -and -not $warnings[$name]){Write-Warning "Field provider $name threshold exceeded; same process continues.";$warnings[$name]=$true}
        }
        $null=$process.WaitForExit(500)
    }
    $process.WaitForExit()
    if($process.ExitCode -ne 0){throw "COMSOL candidate provider exited $($process.ExitCode)"}
    $outcome='success'
}catch [Management.Automation.PipelineStoppedException]{
    $outcome='interrupted';$failure=$_.Exception.Message;throw
}catch{
    $failure=$_.Exception.Message;throw
}finally{
    if($process -and -not $process.HasExited){
        Write-Warning 'Field provider has not reported a native failure after parent exit; awaiting natural completion before finalization.'
        $process.WaitForExit()
    }
    $watch.Stop()
    @{outcome=$outcome;failure_message=$failure;wall_seconds=$watch.Elapsed.TotalSeconds;peak_managed_memory_bytes=$peak;resource_threshold_action='warn';resource_warnings=$warnings} |
        ConvertTo-Json | Set-Content -LiteralPath (Join-Path $inputs 'provider_usage.json') -Encoding utf8
    if($capacity){Exit-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repo -Session $capacity}
    & $python -I -B -m msplatform.backends.comsol.corridor_field --run-directory $RunDirectory --finalize
    if($LASTEXITCODE -ne 0){throw 'Candidate provider terminal publication failed; retain original run for recovery.'}
}

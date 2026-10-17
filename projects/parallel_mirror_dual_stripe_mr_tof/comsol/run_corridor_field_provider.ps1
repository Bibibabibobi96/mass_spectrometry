param(
    [string]$RequestPath,
    [Parameter(Mandatory=$true)][string]$RunDirectory,
    [switch]$Approved,
    [switch]$Child
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$RunDirectory=$ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($RunDirectory)
if($RequestPath){$RequestPath=(Resolve-Path -LiteralPath $RequestPath).Path}
$preparedConfig=Join-Path $RunDirectory 'run_config.json'
$repo = if($Child){[string](Get-Content (Join-Path $PSScriptRoot 'plan.json') -Raw | ConvertFrom-Json).repo_root}elseif(Test-Path -LiteralPath $preparedConfig){[string](Get-Content (Join-Path $RunDirectory 'inputs/plan.json') -Raw | ConvertFrom-Json).repo_root}else{Split-Path (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent) -Parent}
. (Join-Path $repo 'common/require_powershell7.ps1')
. (Join-Path $repo 'common/contracts/run_artifact_support.ps1')
$python=Join-Path $repo '.venv/Scripts/python.exe'
if($Child){
    $plan=Get-Content (Join-Path $PSScriptRoot 'plan.json') -Raw | ConvertFrom-Json
    . (Join-Path $repo 'common/multipole/resource_budget_support.ps1')
    $budget=Get-HostResourceBudget -Role COMSOL -Stage solver
    $launcherOptions=@{}
    if($plan.PSObject.Properties.Name -contains 'comsol_allocator'){
        $launcherOptions.Allocator=[string]$plan.comsol_allocator
    }
    # Observation warnings do not override the repository solver admission budget.
    & (Join-Path $repo 'common/comsol/run_comsol_r2025b.ps1') `
        -TaskScript (Join-Path $PSScriptRoot 'candidate_field.m') `
        -ReportPath (Join-Path $PSScriptRoot 'bootstrap_report.txt') `
        -StartupAttempts 1 -StartupReportTimeoutAction warn `
        -ResourceBudgets @{solver=$budget} -RunId ([string]$plan.run_id) @launcherOptions
    return # Public PS entry returns on success and throws on failure, not LASTEXITCODE.
}
if($env:MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN){throw 'Field provider must run outside a held SIMION/host lease; release the caller stage first.'}
if(-not(Test-Path -LiteralPath $preparedConfig)){
    if(-not $RequestPath){throw 'New preparation requires RequestPath.'}
    Invoke-RunToolRootContext -RepoRoot $repo -Operation {
        & $python -m projects.parallel_mirror_dual_stripe_mr_tof.analysis.corridor_field_provider --request $RequestPath --run-directory $RunDirectory
        if($LASTEXITCODE -ne 0){throw 'Candidate field preparation failed.'}
    }
}elseif($RequestPath){throw 'Prepared input is frozen; omit RequestPath when approving that run.'}
if(-not $Approved){return}
$inputs=Join-Path $RunDirectory 'inputs'
if((Test-Path (Join-Path $RunDirectory 'run_manifest.json')) -or (Test-Path (Join-Path $inputs 'provider.stdout.log'))){throw 'Existing attempt/terminal identity; no automatic retry.'}
$plan=Get-Content (Join-Path $inputs 'plan.json') -Raw | ConvertFrom-Json
. (Join-Path $repo 'common/multipole/resource_budget_support.ps1')
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
        -ArtifactRoot (Join-Path (Split-Path $repo -Parent) 'artifacts') -RunDirectory $RunDirectory `
        -CommittedNewBytes ([int64]$plan.artifact_budget_bytes) `
        -ProtectedPaths @([string]$plan.source_mph) -Owner 'mrtof-same-mesh-field-provider'
    $arguments='-NoProfile -File "'+(Join-Path $inputs 'run_corridor_field_provider.ps1')+'" -Child -RunDirectory "'+$RunDirectory+'"'
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
    if($process -and -not $process.HasExited){$process.Kill($true);$process.WaitForExit()}
    $watch.Stop()
    @{outcome=$outcome;failure_message=$failure;wall_seconds=$watch.Elapsed.TotalSeconds;peak_managed_memory_bytes=$peak;resource_threshold_action='warn';resource_warnings=$warnings} |
        ConvertTo-Json | Set-Content -LiteralPath (Join-Path $inputs 'provider_usage.json') -Encoding utf8
    if($capacity){Exit-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repo -Session $capacity}
    Invoke-RunToolRootContext -RepoRoot $repo -Operation {
        & $python (Join-Path $inputs 'corridor_field_provider.py') --run-directory $RunDirectory --finalize
        if($LASTEXITCODE -ne 0){throw 'Candidate provider terminal publication failed; retain original run for recovery.'}
    }
}

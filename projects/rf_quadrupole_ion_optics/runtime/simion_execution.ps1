Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '..\..\..\common\multipole\resource_budget_support.ps1')

function Initialize-RfSimionPaBasis {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$SimionExe,
        [Parameter(Mandatory = $true)][string]$CandidateDir
    )

    Push-Location $CandidateDir
    try {
        & $SimionExe --nogui --noprompt gem2pa quad_monolithic.gem quad_monolithic.pa#
        if ($LASTEXITCODE -ne 0) { throw 'SIMION gem2pa failed.' }
        & $SimionExe --nogui --noprompt refine quad_monolithic.pa#
        if ($LASTEXITCODE -ne 0) { throw 'SIMION refine failed.' }
    } finally {
        Pop-Location
    }
}

function Initialize-RfSimionPreparedBatch {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$SimionExe,
        [Parameter(Mandatory = $true)][string]$CandidateDir,
        [Parameter(Mandatory = $true)][string]$IobPath,
        [Parameter(Mandatory = $true)][string]$Fly2Path,
        [Parameter(Mandatory = $true)][string]$IobBuilderScript,
        [Parameter(Mandatory = $true)][string]$ProgramSourcePath,
        [Parameter(Mandatory = $true)][string]$RunConfigLua,
        [Parameter(Mandatory = $true)][string]$InspectScript,
        [Parameter(Mandatory = $true)][string]$IobReport,
        [Parameter(Mandatory = $true)][string]$LogDir
    )

    $iobStdoutPath = Join-Path $LogDir 'simion_iob_stdout.txt'
    $iobStderrPath = Join-Path $LogDir 'simion_iob_stderr.txt'
    $iobExitCodePath = Join-Path $LogDir 'simion_iob_exit_code.txt'
    $stdoutPath = Join-Path $LogDir 'simion_stdout.txt'
    $stderrPath = Join-Path $LogDir 'simion_stderr.txt'
    Push-Location $CandidateDir
    try {
        & $SimionExe --nogui --noprompt lua $IobBuilderScript $IobPath `
            $ProgramSourcePath $Fly2Path
        if ($LASTEXITCODE -ne 0) { throw 'SIMION runtime IOB build failed.' }
        Start-Sleep -Milliseconds 500

        $env:MULTIPOLE_SIMION_RUN_CONFIG_LUA = $RunConfigLua
        $env:RFQUAD_SIMION_REFERENCE_REPORT = $IobReport
        $env:RFQUAD_SIMION_REFERENCE_IOB = $IobPath
        'NOT_STARTED' | Set-Content -LiteralPath $iobExitCodePath -Encoding ASCII
        $inspectArguments = @('--nogui','--noprompt','lua',$InspectScript)
        $inspectProcess = Start-Process -FilePath $SimionExe -ArgumentList $inspectArguments `
            -WorkingDirectory $CandidateDir -WindowStyle Hidden -Wait -PassThru `
            -RedirectStandardOutput $iobStdoutPath -RedirectStandardError $iobStderrPath
        [string]$inspectProcess.ExitCode |
            Set-Content -LiteralPath $iobExitCodePath -Encoding ASCII
        Get-Content -LiteralPath $iobStdoutPath -Encoding UTF8 | Write-Host
        if ((Get-Item -LiteralPath $iobStderrPath).Length -gt 0) {
            Get-Content -LiteralPath $iobStderrPath -Encoding UTF8 | Write-Host
        }
        if ($inspectProcess.ExitCode -ne 0) {
            throw "SIMION IOB runtime contract failed with exit code $($inspectProcess.ExitCode)."
        }
        Start-Sleep -Milliseconds 500

    } finally {
        Remove-Item Env:MULTIPOLE_SIMION_RUN_CONFIG_LUA -ErrorAction SilentlyContinue
        Remove-Item Env:RFQUAD_SIMION_REFERENCE_REPORT -ErrorAction SilentlyContinue
        Remove-Item Env:RFQUAD_SIMION_REFERENCE_IOB -ErrorAction SilentlyContinue
        Pop-Location
    }
}

function New-RfSimionFlyProcessSpecification {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$SimionExe,
        [Parameter(Mandatory = $true)][string]$CandidateDir,
        [Parameter(Mandatory = $true)][string]$IobPath,
        [Parameter(Mandatory = $true)][string]$Fly2Path,
        [Parameter(Mandatory = $true)][string]$RunConfigLua,
        [Parameter(Mandatory = $true)][string]$IobReport,
        [Parameter(Mandatory = $true)][string]$LogDir,
        [Parameter(Mandatory = $true)][int]$TrajectoryQuality,
        [Parameter(Mandatory = $true)][int]$RfStepsPerPeriod
    )

    if ($TrajectoryQuality -le 0 -or $RfStepsPerPeriod -le 0) {
        throw 'SIMION launch numerics must be positive.'
    }
    [pscustomobject]@{
        name = $Name
        file_path = $SimionExe
        working_directory = $CandidateDir
        argument_list = @(
            '--nogui','--noprompt','fly',
            '--trajectory-quality',[string]$TrajectoryQuality,
            '--particles',$Fly2Path,
            '--programs','1',
            '--retain-trajectories','0',
            '--adjustable',"transport_rf_steps_per_period=$RfStepsPerPeriod",
            $IobPath
        )
        stdout = Join-Path $LogDir 'simion_stdout.txt'
        stderr = Join-Path $LogDir 'simion_stderr.txt'
        environment = @{
            MULTIPOLE_SIMION_RUN_CONFIG_LUA = $RunConfigLua
            RFQUAD_SIMION_REFERENCE_REPORT = $IobReport
            RFQUAD_SIMION_REFERENCE_IOB = $IobPath
        }
    }
}

function Invoke-RfSimionFlyWave {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][object[]]$ProcessSpecifications
    )

    if ($ProcessSpecifications.Count -eq 0) {
        throw 'SIMION fly wave requires at least one process specification.'
    }
    $running = @()
    foreach ($specification in $ProcessSpecifications) {
        $process = Start-Process -FilePath $specification.file_path `
            -ArgumentList $specification.argument_list `
            -WorkingDirectory $specification.working_directory `
            -Environment $specification.environment `
            -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput $specification.stdout `
            -RedirectStandardError $specification.stderr
        $running += [pscustomobject]@{
            specification = $specification
            process = $process
            peak_working_set_bytes = [int64]0
        }
    }
    do {
        $activeCount = 0
        foreach ($entry in $running) {
            if (-not $entry.process.HasExited) {
                $entry.process.Refresh()
                $entry.peak_working_set_bytes = [Math]::Max(
                    $entry.peak_working_set_bytes, [int64]$entry.process.WorkingSet64)
                $activeCount++
            }
        }
        if ($activeCount -gt 0) { Start-Sleep -Milliseconds 100 }
    } while ($activeCount -gt 0)

    foreach ($entry in $running) {
        $entry.process.WaitForExit()
        $entry.process.Refresh()
        $entry.peak_working_set_bytes = [Math]::Max(
            $entry.peak_working_set_bytes, [int64]$entry.process.PeakWorkingSet64)
        Get-Content -LiteralPath $entry.specification.stdout -Encoding UTF8 | Write-Host
        if ((Get-Item -LiteralPath $entry.specification.stderr).Length -gt 0) {
            Get-Content -LiteralPath $entry.specification.stderr -Encoding UTF8 | Write-Host
        }
        if ($entry.process.ExitCode -ne 0) {
            throw "SIMION fly '$($entry.specification.name)' failed with exit code $($entry.process.ExitCode)."
        }
    }
    return $running
}

function Invoke-RfSimionPreparedBatch {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$SimionExe,
        [Parameter(Mandatory = $true)][string]$CandidateDir,
        [Parameter(Mandatory = $true)][string]$IobPath,
        [Parameter(Mandatory = $true)][string]$Fly2Path,
        [Parameter(Mandatory = $true)][string]$IobBuilderScript,
        [Parameter(Mandatory = $true)][string]$ProgramSourcePath,
        [Parameter(Mandatory = $true)][string]$RunConfigLua,
        [Parameter(Mandatory = $true)][string]$InspectScript,
        [Parameter(Mandatory = $true)][string]$IobReport,
        [Parameter(Mandatory = $true)][string]$LogDir,
        [Parameter(Mandatory = $true)][int]$TrajectoryQuality,
        [Parameter(Mandatory = $true)][int]$RfStepsPerPeriod
    )

    Initialize-RfSimionPreparedBatch `
        -SimionExe $SimionExe -CandidateDir $CandidateDir -IobPath $IobPath -Fly2Path $Fly2Path `
        -IobBuilderScript $IobBuilderScript -ProgramSourcePath $ProgramSourcePath `
        -RunConfigLua $RunConfigLua -InspectScript $InspectScript -IobReport $IobReport -LogDir $LogDir
    $flySpecification = New-RfSimionFlyProcessSpecification `
        -Name 'batch_001' -SimionExe $SimionExe -CandidateDir $CandidateDir -IobPath $IobPath `
        -Fly2Path $Fly2Path -RunConfigLua $RunConfigLua -IobReport $IobReport -LogDir $LogDir `
        -TrajectoryQuality $TrajectoryQuality -RfStepsPerPeriod $RfStepsPerPeriod
    return Invoke-RfSimionFlyWave -ProcessSpecifications @($flySpecification)
}

function Invoke-RfSimionParticleBatchWave {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$SimionExe,
        [Parameter(Mandatory = $true)][string]$CandidateDir,
        [Parameter(Mandatory = $true)][string]$IobPath,
        [Parameter(Mandatory = $true)][string]$RootFly2Path,
        [Parameter(Mandatory = $true)][string]$IobBuilderScript,
        [Parameter(Mandatory = $true)][string]$ProgramSourcePath,
        [Parameter(Mandatory = $true)][string]$RootRunConfigLua,
        [Parameter(Mandatory = $true)][string]$InspectScript,
        [Parameter(Mandatory = $true)][string]$IobReport,
        [Parameter(Mandatory = $true)][string]$LogDir,
        [Parameter(Mandatory = $true)][int]$TrajectoryQuality,
        [Parameter(Mandatory = $true)][int]$RfStepsPerPeriod,
        [Parameter(Mandatory = $true)][object[]]$BatchRuns,
        [Parameter(Mandatory = $true)][string]$BatchPlanPath,
        [Parameter(Mandatory = $true)][string]$DispatchPlanPath,
        [Parameter(Mandatory = $true)][string]$RunDir,
        [Parameter(Mandatory = $true)][string]$UsagePath,
        [Parameter(Mandatory = $true)][string]$PythonExe,
        [Parameter(Mandatory = $true)][string]$RepositoryRoot,
        [object[]]$ExistingProcessRecords = @(),
        [switch]$Prepared
    )

    if ($BatchRuns.Count -eq 0) { throw 'SIMION particle batch wave requires at least one batch.' }
    if (-not $Prepared) {
        Initialize-RfSimionPaBasis -SimionExe $SimionExe -CandidateDir $CandidateDir
        Initialize-RfSimionPreparedBatch -SimionExe $SimionExe -CandidateDir $CandidateDir `
            -IobPath $IobPath -Fly2Path $RootFly2Path -IobBuilderScript $IobBuilderScript `
            -ProgramSourcePath $ProgramSourcePath -RunConfigLua $RootRunConfigLua `
            -InspectScript $InspectScript -IobReport $IobReport -LogDir $LogDir
    }
    $specifications = @($BatchRuns | ForEach-Object {
        New-RfSimionFlyProcessSpecification -Name ([string]$_.name) `
            -SimionExe $SimionExe -CandidateDir $CandidateDir -IobPath ([string]$_.config.iob) `
            -Fly2Path ([string]$_.config.fly2) -RunConfigLua ([string]$_.lua) -IobReport $IobReport `
            -LogDir ([string]$_.log_dir) -TrajectoryQuality ([int]$_.config.trajectory_quality) `
            -RfStepsPerPeriod ([int]$_.config.rf_steps_per_period)
    })
    if ($ExistingProcessRecords.Count -gt 0) {
        $specifications = @($specifications | Select-Object -Skip 1)
    }
    $receipt = Invoke-ResourceBudgetedProcesses -DispatchPlanPath $DispatchPlanPath `
        -RunDir $RunDir -UsagePath $UsagePath -ProcessSpecifications $specifications `
        -ExistingProcessRecords $ExistingProcessRecords
    if ($receipt.resource_budget_exceeded) {
        throw 'SIMION particle batch wave reached sustained critical memory pressure.'
    }
    $failed = @($receipt.processes | Where-Object { $null -ne $_.exit_code -and [int]$_.exit_code -ne 0 })
    if ($failed.Count -gt 0) { throw "SIMION particle batch wave failed: $($failed.name -join ', ')" }
    Push-Location $RepositoryRoot
    try {
        foreach ($merge in @(@{output = $BatchRuns[0].merged_state; property = 'state'}, @{output = $BatchRuns[0].merged_trajectory; property = 'trajectory'})) {
            $arguments = @('-m','common.simion.particle_batching','--merge-rebase-csv','--output',$merge.output)
            foreach ($batchRun in $BatchRuns) {
                $arguments += @('--batch-csv',$batchRun.($merge.property),[string]$batchRun.batch.simion_particle_id_offset)
            }
            & $PythonExe @arguments | Out-Null
            if ($LASTEXITCODE -ne 0) { throw 'SIMION shared particle CSV merge failed.' }
        }
        $summaryArguments = @('-m','common.simion.particle_batching','--merge-summaries',
            '--batch-plan',$BatchPlanPath,'--output',$BatchRuns[0].merged_summary)
        foreach ($batchRun in $BatchRuns) { $summaryArguments += @('--batch-summary',$batchRun.summary) }
        & $PythonExe @summaryArguments | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'SIMION shared summary merge failed.' }
    } finally {
        Pop-Location
    }
    return $receipt
}

function Start-RfSimionFormalFirstBatch {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$SimionExe,
        [Parameter(Mandatory = $true)][string]$CandidateDir,
        [Parameter(Mandatory = $true)][string]$IobPath,
        [Parameter(Mandatory = $true)][string]$RootFly2Path,
        [Parameter(Mandatory = $true)][string]$IobBuilderScript,
        [Parameter(Mandatory = $true)][string]$ProgramSourcePath,
        [Parameter(Mandatory = $true)][string]$RootRunConfigLua,
        [Parameter(Mandatory = $true)][string]$InspectScript,
        [Parameter(Mandatory = $true)][string]$IobReport,
        [Parameter(Mandatory = $true)][string]$LogDir,
        [Parameter(Mandatory = $true)][int]$TrajectoryQuality,
        [Parameter(Mandatory = $true)][int]$RfStepsPerPeriod,
        [Parameter(Mandatory = $true)]$FirstBatchRun,
        [Parameter(Mandatory = $true)][string]$DispatchPlanPath
    )
    Initialize-RfSimionPaBasis -SimionExe $SimionExe -CandidateDir $CandidateDir
    Initialize-RfSimionPreparedBatch -SimionExe $SimionExe -CandidateDir $CandidateDir `
        -IobPath $IobPath -Fly2Path $RootFly2Path -IobBuilderScript $IobBuilderScript `
        -ProgramSourcePath $ProgramSourcePath -RunConfigLua $RootRunConfigLua `
        -InspectScript $InspectScript -IobReport $IobReport -LogDir $LogDir
    $specification = New-RfSimionFlyProcessSpecification -Name ([string]$FirstBatchRun.name) `
        -SimionExe $SimionExe -CandidateDir $CandidateDir -IobPath ([string]$FirstBatchRun.config.iob) `
        -Fly2Path ([string]$FirstBatchRun.config.fly2) -RunConfigLua ([string]$FirstBatchRun.lua) `
        -IobReport $IobReport -LogDir ([string]$FirstBatchRun.log_dir) `
        -TrajectoryQuality ([int]$FirstBatchRun.config.trajectory_quality) `
        -RfStepsPerPeriod ([int]$FirstBatchRun.config.rf_steps_per_period)
    return Start-ObservedFormalProcess -DispatchPlanPath $DispatchPlanPath `
        -ProcessSpecification $specification
}

function Update-RfSimionDispatchAfterFormalObservation {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$PythonExe,
        [Parameter(Mandatory = $true)][string]$RepositoryRoot,
        [Parameter(Mandatory = $true)][string]$DispatchRequestPath,
        [Parameter(Mandatory = $true)][string]$ResourceProfilesPath,
        [Parameter(Mandatory = $true)][string]$DispatchPlanPath,
        [Parameter(Mandatory = $true)][string]$BatchPlanPath,
        [Parameter(Mandatory = $true)]$Observation
    )
    if ([int64]$Observation.observed_peak_process_tree_working_set_bytes -lt 1) {
        throw 'The first formal SIMION batch did not produce a usable resource observation.'
    }
    $arguments = @(
        '-m','common.simion.resource_scheduler','--request',$DispatchRequestPath,
        '--profiles',$ResourceProfilesPath,'--output',$DispatchPlanPath,
        '--available-memory-bytes',([string]$Observation.available_memory_bytes),
        '--total-physical-memory-bytes',([string]$Observation.total_physical_memory_bytes),
        '--observed-formal-peak-bytes',([string]$Observation.observed_peak_process_tree_working_set_bytes),
        '--observed-formal-cpu-percent',([string]$Observation.observed_process_cpu_percent),
        '--observed-background-cpu-percent',([string]$Observation.observed_background_cpu_percent)
    )
    if ($Observation.completed_naturally) { $arguments += '--first-batch-completed' }
    Push-Location $RepositoryRoot
    try {
        & $PythonExe @arguments | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'SIMION formal-first dispatch replanning failed.' }
        & $PythonExe -m common.simion.particle_batching --from-dispatch-plan $DispatchPlanPath `
            --output $BatchPlanPath | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'SIMION formal-first particle batch planning failed.' }
    } finally {
        Pop-Location
    }
    return [pscustomobject]@{
        dispatch = Get-Content -LiteralPath $DispatchPlanPath -Raw -Encoding UTF8 | ConvertFrom-Json
        batches = Get-Content -LiteralPath $BatchPlanPath -Raw -Encoding UTF8 | ConvertFrom-Json
    }
}

function Invoke-RfSimionCoreRun {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$SimionExe,
        [Parameter(Mandatory = $true)][string]$CandidateDir,
        [Parameter(Mandatory = $true)][string]$IobPath,
        [Parameter(Mandatory = $true)][string]$Fly2Path,
        [Parameter(Mandatory = $true)][string]$IobBuilderScript,
        [Parameter(Mandatory = $true)][string]$ProgramSourcePath,
        [Parameter(Mandatory = $true)][string]$RunConfigLua,
        [Parameter(Mandatory = $true)][string]$InspectScript,
        [Parameter(Mandatory = $true)][string]$IobReport,
        [Parameter(Mandatory = $true)][string]$LogDir,
        [Parameter(Mandatory = $true)][int]$TrajectoryQuality,
        [Parameter(Mandatory = $true)][int]$RfStepsPerPeriod
    )

    Initialize-RfSimionPaBasis -SimionExe $SimionExe -CandidateDir $CandidateDir
    return Invoke-RfSimionPreparedBatch @PSBoundParameters
}

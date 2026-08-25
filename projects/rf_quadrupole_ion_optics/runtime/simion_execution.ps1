Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

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
        stdout_path = Join-Path $LogDir 'simion_stdout.txt'
        stderr_path = Join-Path $LogDir 'simion_stderr.txt'
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
            -RedirectStandardOutput $specification.stdout_path `
            -RedirectStandardError $specification.stderr_path
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
        Get-Content -LiteralPath $entry.specification.stdout_path -Encoding UTF8 | Write-Host
        if ((Get-Item -LiteralPath $entry.specification.stderr_path).Length -gt 0) {
            Get-Content -LiteralPath $entry.specification.stderr_path -Encoding UTF8 | Write-Host
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
        [Parameter(Mandatory = $true)][string]$PythonExe,
        [Parameter(Mandatory = $true)][string]$RepositoryRoot
    )

    if ($BatchRuns.Count -eq 0) { throw 'SIMION particle batch wave requires at least one batch.' }
    if ($BatchRuns.Count -eq 1) {
        return Invoke-RfSimionCoreRun -SimionExe $SimionExe -CandidateDir $CandidateDir `
            -IobPath $IobPath -Fly2Path $RootFly2Path -IobBuilderScript $IobBuilderScript `
            -ProgramSourcePath $ProgramSourcePath -RunConfigLua $RootRunConfigLua `
            -InspectScript $InspectScript -IobReport $IobReport -LogDir $LogDir `
            -TrajectoryQuality $TrajectoryQuality -RfStepsPerPeriod $RfStepsPerPeriod
    }
    Initialize-RfSimionPaBasis -SimionExe $SimionExe -CandidateDir $CandidateDir
    Initialize-RfSimionPreparedBatch -SimionExe $SimionExe -CandidateDir $CandidateDir `
        -IobPath $IobPath -Fly2Path $RootFly2Path -IobBuilderScript $IobBuilderScript `
        -ProgramSourcePath $ProgramSourcePath -RunConfigLua $RootRunConfigLua `
        -InspectScript $InspectScript -IobReport $IobReport -LogDir $LogDir
    $specifications = @($BatchRuns | ForEach-Object {
        New-RfSimionFlyProcessSpecification -Name ([string]$_.name) `
            -SimionExe $SimionExe -CandidateDir $CandidateDir -IobPath ([string]$_.config.iob) `
            -Fly2Path ([string]$_.config.fly2) -RunConfigLua ([string]$_.lua) -IobReport $IobReport `
            -LogDir ([string]$_.log_dir) -TrajectoryQuality ([int]$_.config.trajectory_quality) `
            -RfStepsPerPeriod ([int]$_.config.rf_steps_per_period)
    })
    $receipt = @(Invoke-RfSimionFlyWave -ProcessSpecifications $specifications)
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

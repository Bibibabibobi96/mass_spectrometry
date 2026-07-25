Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Invoke-RfSimionCoreRun {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$SimionExe,
        [Parameter(Mandatory = $true)][string]$CandidateDir,
        [Parameter(Mandatory = $true)][string]$IobPath,
        [Parameter(Mandatory = $true)][string]$Fly2Path,
        [Parameter(Mandatory = $true)][string]$RunConfigLua,
        [Parameter(Mandatory = $true)][string]$InspectScript,
        [Parameter(Mandatory = $true)][string]$IobReport,
        [Parameter(Mandatory = $true)][string]$LogDir,
        [Parameter(Mandatory = $true)][int]$TrajectoryQuality,
        [Parameter(Mandatory = $true)][int]$RfStepsPerPeriod
    )

    if ($TrajectoryQuality -le 0 -or $RfStepsPerPeriod -le 0) {
        throw 'SIMION launch numerics must be positive.'
    }
    $stdoutPath = Join-Path $LogDir 'simion_stdout.txt'
    $stderrPath = Join-Path $LogDir 'simion_stderr.txt'
    Push-Location $CandidateDir
    try {
        & $SimionExe --nogui --noprompt gem2pa quad_monolithic.gem quad_monolithic.pa#
        if ($LASTEXITCODE -ne 0) { throw 'SIMION gem2pa failed.' }
        & $SimionExe --nogui --noprompt refine quad_monolithic.pa#
        if ($LASTEXITCODE -ne 0) { throw 'SIMION refine failed.' }
        Start-Sleep -Milliseconds 500

        $env:MULTIPOLE_SIMION_RUN_CONFIG_LUA = $RunConfigLua
        $env:RFQUAD_SIMION_REFERENCE_REPORT = $IobReport
        $env:RFQUAD_SIMION_REFERENCE_IOB = $IobPath
        & $SimionExe --nogui --noprompt lua $InspectScript
        if ($LASTEXITCODE -ne 0) { throw 'SIMION IOB runtime contract failed.' }
        Start-Sleep -Milliseconds 500

        $flyArguments = @(
            '--nogui','--noprompt','fly',
            '--trajectory-quality',[string]$TrajectoryQuality,
            '--particles',$Fly2Path,
            '--programs','1',
            '--retain-trajectories','0',
            '--adjustable',"transport_rf_steps_per_period=$RfStepsPerPeriod",
            $IobPath
        )
        $flyProcess = Start-Process -FilePath $SimionExe -ArgumentList $flyArguments `
            -WindowStyle Hidden -Wait -PassThru `
            -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath
        Get-Content -LiteralPath $stdoutPath -Encoding UTF8
        if ((Get-Item -LiteralPath $stderrPath).Length -gt 0) {
            Get-Content -LiteralPath $stderrPath -Encoding UTF8
        }
        if ($flyProcess.ExitCode -ne 0) {
            throw "SIMION fly failed with exit code $($flyProcess.ExitCode)."
        }
    } finally {
        Remove-Item Env:MULTIPOLE_SIMION_RUN_CONFIG_LUA -ErrorAction SilentlyContinue
        Remove-Item Env:RFQUAD_SIMION_REFERENCE_REPORT -ErrorAction SilentlyContinue
        Remove-Item Env:RFQUAD_SIMION_REFERENCE_IOB -ErrorAction SilentlyContinue
        Pop-Location
    }
}

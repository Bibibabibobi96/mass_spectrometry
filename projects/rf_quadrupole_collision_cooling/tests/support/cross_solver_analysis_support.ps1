Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function New-CrossSolverAnalysisPackage {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Python,[Parameter(Mandatory)][string]$RepoRoot,
        [Parameter(Mandatory)][string]$ArtifactRoot,[Parameter(Mandatory)][string]$RunId,
        [Parameter(Mandatory)][string]$PackageMode,[Parameter(Mandatory)][string[]]$Software
    )
    New-RunPackage -Python $Python -RepoRoot $RepoRoot -ArtifactRoot $ArtifactRoot `
        -RunId $RunId -Project 'rf_quadrupole_collision_cooling' -Mode $PackageMode -Software $Software
}

function Assert-CrossSolverSourceManifest {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Python,[Parameter(Mandatory)][string]$RepoRoot,
        [Parameter(Mandatory)][string]$Manifest)
    & $Python (Join-Path $RepoRoot 'common\contracts\verify_run_manifest.py') $Manifest `
        --require-status success --require-project rf_quadrupole_collision_cooling
    if ($LASTEXITCODE -ne 0) { throw "Source run-manifest verification failed: $Manifest" }
    Get-Content -LiteralPath $Manifest -Raw -Encoding UTF8 | ConvertFrom-Json
}

function Get-CrossSolverSourcePair {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Python,[Parameter(Mandatory)][string]$RepoRoot,
        [Parameter(Mandatory)][string]$ArtifactRoot,[Parameter(Mandatory)][string]$ComsolRunId,
        [Parameter(Mandatory)][string]$SimionRunId
    )
    $result=[ordered]@{}
    foreach($entry in @([pscustomobject]@{Name='comsol';RunId=$ComsolRunId},
        [pscustomobject]@{Name='simion';RunId=$SimionRunId})){
        $run=Join-Path $ArtifactRoot "runs\$($entry.RunId)";$manifest=Join-Path $run 'run_manifest.json'
        $manifestData=Assert-CrossSolverSourceManifest -Python $Python -RepoRoot $RepoRoot -Manifest $manifest
        $configPath=[IO.Path]::GetFullPath([string]$manifestData.run_config.path)
        $result[$entry.Name]=[pscustomobject]@{run=$run;manifest=$manifest;manifest_data=$manifestData;
            config_path=$configPath;config=(Get-Content -LiteralPath $configPath -Raw -Encoding UTF8|ConvertFrom-Json)}
    }
    [pscustomobject]$result
}

function Copy-CrossSolverAnalysisInputs {
    [CmdletBinding()] param([Parameter(Mandatory)][object[]]$Pairs)
    foreach($pair in $Pairs){Copy-VerifiedRunInput -Source $pair[0] -Destination $pair[1]|Out-Null}
}

function New-CrossSolverFrozenPathSet {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$InputDir,[Parameter(Mandatory)][string]$AnalyzerFilename,
        [Parameter(Mandatory)][string]$ModeFilename)
    [pscustomobject]@{
        analyzer=Join-Path $InputDir $AnalyzerFilename;core=Join-Path $InputDir 'particle_state_comparison_core.py'
        mode=Join-Path $InputDir $ModeFilename;comsol_manifest=Join-Path $InputDir 'comsol_run_manifest.json'
        simion_manifest=Join-Path $InputDir 'simion_run_manifest.json';comsol_config=Join-Path $InputDir 'comsol_run_config.json'
        simion_config=Join-Path $InputDir 'simion_run_config.json';comsol_state=Join-Path $InputDir 'comsol_particle_state.csv'
        simion_state=Join-Path $InputDir 'simion_particle_state.csv';support=Join-Path $InputDir 'cross_solver_analysis_support.ps1'
    }
}

function Invoke-CrossSolverAnalyzer {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Python,[Parameter(Mandatory)][string]$Analyzer,
        [Parameter(Mandatory)][string[]]$Arguments,[Parameter(Mandatory)][string]$Stdout,
        [Parameter(Mandatory)][string]$Stderr,[Parameter(Mandatory)][string[]]$RequiredOutputs
    )
    & $Python $Analyzer @Arguments 1> $Stdout 2> $Stderr
    if($LASTEXITCODE-ne 0){throw "Cross-solver analyzer failed with exit code $LASTEXITCODE."}
    foreach($path in $RequiredOutputs){
        if(-not(Test-Path -LiteralPath $path -PathType Leaf)){throw "Cross-solver analyzer output is missing: $path"}
    }
}

function Complete-CrossSolverAnalysis {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Python,[Parameter(Mandatory)][string]$RepoRoot,
        [Parameter(Mandatory)][string]$RunConfig,[Parameter(Mandatory)][string]$Summary,
        [Parameter(Mandatory)][object]$SummaryValue,[Parameter(Mandatory)][string[]]$Outputs,
        [Parameter(Mandatory)][string[]]$Software,[Parameter(Mandatory)][string[]]$Logs
    )
    Write-RunJson -Path $Summary -Depth 10 -Value $SummaryValue
    Write-VerifiedRunManifest -Python $Python -RepoRoot $RepoRoot -RunConfig $RunConfig `
        -Status success -Software $Software -Outputs ($Outputs+@($Summary)+$Logs)
}

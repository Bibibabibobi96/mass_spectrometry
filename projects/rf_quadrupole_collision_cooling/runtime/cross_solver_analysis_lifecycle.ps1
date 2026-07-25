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
    $null = & $Python (Join-Path $RepoRoot 'common\contracts\verify_run_manifest.py') $Manifest `
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

function Get-CrossSolverResolvedDrive {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$ComsolResolvedDesign,
        [Parameter(Mandatory)][string]$SimionResolvedDesign
    )
    $numericTypes = @(
        [byte],[sbyte],[int16],[uint16],[int32],[uint32],
        [int64],[uint64],[single],[double],[decimal]
    )
    $records = [ordered]@{}
    foreach($entry in @(
        [pscustomobject]@{Solver='COMSOL';Path=$ComsolResolvedDesign},
        [pscustomobject]@{Solver='SIMION';Path=$SimionResolvedDesign}
    )){
        $path = [IO.Path]::GetFullPath($entry.Path)
        if(-not(Test-Path -LiteralPath $path -PathType Leaf)){
            throw "$($entry.Solver) frozen resolved design is missing: $path"
        }
        try {
            $document = Get-Content -LiteralPath $path -Raw -Encoding UTF8 |
                ConvertFrom-Json
        } catch {
            throw "$($entry.Solver) frozen resolved design is invalid JSON: $path"
        }
        if($document.role -ne 'multipole_resolved_design_do_not_edit' -or
            -not $document.PSObject.Properties['drive']){
            throw "$($entry.Solver) frozen resolved design identity or drive is invalid."
        }
        $drive = $document.drive
        $values = [ordered]@{}
        foreach($propertyName in @(
            'rf_amplitude_V_zero_to_peak_per_group','frequency_Hz'
        )){
            $property = $drive.PSObject.Properties[$propertyName]
            if($null -eq $property -or $null -eq $property.Value -or
                -not $numericTypes.Contains($property.Value.GetType())){
                throw "$($entry.Solver) resolved drive lacks numeric $propertyName."
            }
            try {
                $number = [double]$property.Value
            } catch {
                throw "$($entry.Solver) resolved drive $propertyName is not numeric."
            }
            if([double]::IsNaN($number) -or [double]::IsInfinity($number)){
                throw "$($entry.Solver) resolved drive $propertyName is not finite."
            }
            $values[$propertyName] = $number
        }
        if($values.frequency_Hz -le 0){
            throw "$($entry.Solver) resolved drive frequency_Hz must be positive."
        }
        $records[$entry.Solver] = [pscustomobject]@{
            path=$path
            sha256=(Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash
            rf_peak_v=$values.rf_amplitude_V_zero_to_peak_per_group
            frequency_hz=$values.frequency_Hz
        }
    }
    if($records.COMSOL.sha256 -cne $records.SIMION.sha256 -or
        $records.COMSOL.rf_peak_v -ne $records.SIMION.rf_peak_v -or
        $records.COMSOL.frequency_hz -ne $records.SIMION.frequency_hz){
        throw 'COMSOL and SIMION frozen resolved designs or drive values differ.'
    }
    [pscustomobject]@{
        comsol_path=$records.COMSOL.path
        simion_path=$records.SIMION.path
        resolved_design_sha256=$records.COMSOL.sha256
        rf_peak_v=$records.COMSOL.rf_peak_v
        frequency_hz=$records.COMSOL.frequency_hz
    }
}

function Copy-CrossSolverAnalysisInputs {
    [CmdletBinding()] param([Parameter(Mandatory)][object[]]$Pairs)
    foreach($pair in $Pairs){Copy-VerifiedRunInput -Source $pair[0] -Destination $pair[1]|Out-Null}
}

function New-CrossSolverFrozenPathSet {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$InputDir,[Parameter(Mandatory)][string]$AnalyzerRelativePath,
        [Parameter(Mandatory)][string]$ModeFilename)
    $moduleRoot=Join-Path $InputDir 'code'
    [pscustomobject]@{
        module_root=$moduleRoot;analyzer=Join-Path $moduleRoot $AnalyzerRelativePath
        core=Join-Path $moduleRoot 'projects\rf_quadrupole_collision_cooling\analysis\particle_state_comparison_core.py'
        mode=Join-Path $InputDir $ModeFilename;comsol_manifest=Join-Path $InputDir 'comsol_run_manifest.json'
        simion_manifest=Join-Path $InputDir 'simion_run_manifest.json';comsol_config=Join-Path $InputDir 'comsol_run_config.json'
        simion_config=Join-Path $InputDir 'simion_run_config.json';comsol_state=Join-Path $InputDir 'comsol_particle_state.csv'
        simion_state=Join-Path $InputDir 'simion_particle_state.csv';support=Join-Path $InputDir 'cross_solver_analysis_lifecycle.ps1'
    }
}

function Invoke-CrossSolverAnalyzer {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Python,[Parameter(Mandatory)][string]$AnalyzerModule,
        [Parameter(Mandatory)][string]$ModuleRoot,
        [Parameter(Mandatory)][string[]]$Arguments,[Parameter(Mandatory)][string]$Stdout,
        [Parameter(Mandatory)][string]$Stderr,[Parameter(Mandatory)][string[]]$RequiredOutputs
    )
    $savedPythonPath=$env:PYTHONPATH
    $savedNoUserSite=$env:PYTHONNOUSERSITE
    try{
        $env:PYTHONPATH=$ModuleRoot
        $env:PYTHONNOUSERSITE='1'
        Push-Location -LiteralPath $ModuleRoot
        try{
            & $Python -m $AnalyzerModule @Arguments 1> $Stdout 2> $Stderr
            if($LASTEXITCODE-ne 0){throw "Cross-solver analyzer failed with exit code $LASTEXITCODE."}
        }finally{Pop-Location}
    }finally{
        $env:PYTHONPATH=$savedPythonPath
        $env:PYTHONNOUSERSITE=$savedNoUserSite
    }
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

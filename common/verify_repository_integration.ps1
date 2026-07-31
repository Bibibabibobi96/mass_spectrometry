[CmdletBinding()]
param(
    [string]$PythonExe = '',
    [ValidateRange(1, 32)][int]$MaxConcurrency = 4,
    [string]$InternalStage = '',
    [string]$InternalLogPath = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'require_powershell7.ps1')
. (Join-Path $PSScriptRoot 'parallel_gate_support.ps1')
$repoRoot = Split-Path -Parent $PSScriptRoot
if (-not $PythonExe) {
    $venvPython = Join-Path $repoRoot '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $venvPython -PathType Leaf) { $PythonExe = $venvPython }
    else { $PythonExe = (Get-Command python -ErrorAction Stop).Source }
}
$PythonExe = [IO.Path]::GetFullPath($PythonExe)
if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) { throw "Python runtime missing: $PythonExe" }
$pythonVersion = (& $PythonExe -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
if ($LASTEXITCODE -ne 0 -or $pythonVersion -ne '3.11') { throw "Repository integration gate requires Python 3.11, found $pythonVersion at $PythonExe" }

function Invoke-IntegrationStage {
    param([Parameter(Mandatory)][string]$Name, [Parameter(Mandatory)][scriptblock]$Action)
    $timer = [Diagnostics.Stopwatch]::StartNew()
    Write-Output "GATE_STAGE=RUN NAME=$Name"
    & $Action
    if ($LASTEXITCODE -ne 0) { throw "Repository integration stage failed: $Name" }
    Write-Output "GATE_STAGE=PASS NAME=$Name ELAPSED_SECONDS=$([math]::Round($timer.Elapsed.TotalSeconds, 3))"
}

$stageActions = [ordered]@{
    documentation = { & (Join-Path $PSScriptRoot 'verify_documentation.ps1') }
    livelink_failure_classification = { & (Join-Path $PSScriptRoot 'comsol\test_livelink_failure_classification.ps1') }
    livelink_environment = { & (Join-Path $PSScriptRoot 'comsol\test_livelink_environment.ps1') }
    development_standards = { & $PythonExe (Join-Path $PSScriptRoot 'verify_development_standards.py') }
    ruff_all = { & $PythonExe -m ruff check (Join-Path $repoRoot 'common') (Join-Path $repoRoot 'projects') }
    project_registry = { & $PythonExe (Join-Path $PSScriptRoot 'contracts\build_project_registry.py') --check }
    rf_quadrupole_generated_publications = {
        & (Join-Path $repoRoot 'projects\rf_quadrupole_ion_optics\verify_project.ps1') -Level Freshness -PythonExe $PythonExe
    }
    common_contracts = { & $PythonExe -m unittest discover -s (Join-Path $PSScriptRoot 'contracts') -p 'test_*.py' }
    multipole_common = { & $PythonExe -m unittest discover -s (Join-Path $PSScriptRoot 'multipole') -p 'test_*.py' }
    integration_common = { & $PythonExe -m unittest discover -s (Join-Path $PSScriptRoot 'integration') -p 'test_*.py' }
    rf_multipole_to_single_reflection_oatof_integration = {
        & (Join-Path $repoRoot 'integrations\rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer\verify_integration.ps1') -PythonExe $PythonExe
    }
    multipole_foundation = {
        Push-Location $repoRoot
        try { & $PythonExe -m common.multipole.verify_family_foundation }
        finally { Pop-Location }
    }
    solidworks_common = { & $PythonExe -m unittest discover -s (Join-Path $PSScriptRoot 'solidworks') -p 'test_*.py' }
    single_reflection_oa_tof_mass_analyzer_static = {
        & (Join-Path $repoRoot 'projects\single_reflection_oa_tof_mass_analyzer\verify_project.ps1') -Level Static -PythonExe $PythonExe
    }
    rf_quadrupole_static = {
        & (Join-Path $repoRoot 'projects\rf_quadrupole_ion_optics\verify_project.ps1') -Level Static -PythonExe $PythonExe
    }
    rf_hexapole_static = { & (Join-Path $repoRoot 'projects\rf_hexapole_ion_optics\verify_project.ps1') -PythonExe $PythonExe }
    rf_octupole_static = { & (Join-Path $repoRoot 'projects\rf_octupole_ion_optics\verify_project.ps1') -PythonExe $PythonExe }
    wehnelt_static = {
        & (Join-Path $repoRoot 'projects\transverse_helical_filament_wehnelt_electron_gun\verify_project.ps1') -PythonExe $PythonExe
    }
    electron_impact_static = {
        & (Join-Path $repoRoot 'projects\apertured_tube_electron_impact_ion_source\verify_project.ps1') -PythonExe $PythonExe
    }
}

function Invoke-InternalIntegrationStage {
    if (-not $stageActions.Contains($InternalStage)) {
        throw "Unknown repository integration stage: $InternalStage"
    }
    if (-not $InternalLogPath) {
        throw 'InternalLogPath is required for an internal integration stage.'
    }
    $passed = Invoke-LoggedGateStage -Name $InternalStage `
        -LogPath $InternalLogPath -Action {
            Invoke-IntegrationStage $InternalStage $stageActions[$InternalStage]
        }
    if ($passed) { exit 0 }
    exit 1
}

function Invoke-ParallelIntegrationGroup {
    param([Parameter(Mandatory)][string[]]$Names)
    $items = @(
        $Names | ForEach-Object {
            [pscustomobject]@{
                Name = $_
                Run = $true
                Reason = 'repository_integration'
                Action = $stageActions[$_]
            }
        }
    )
    Invoke-IndependentGateStageGroup -Items $items `
        -MaxConcurrency $MaxConcurrency -GateScriptPath $PSCommandPath `
        -ChildBaseArguments @(
            '-PythonExe', $PythonExe,
            '-MaxConcurrency', [string]$MaxConcurrency
        ) `
        -TempNamePrefix 'repository_integration_gate_' `
        -FailureMessage 'Repository integration stages failed' `
        -InvokeInlineStage {
            param($item)
            Invoke-IntegrationStage $item.Name $item.Action
        } `
        -InvokeSkipStage {
            param($item)
            throw "Unexpected skipped repository integration stage: $($item.Name)"
        }
}

if ($InternalStage) {
    Invoke-InternalIntegrationStage
}

$fastFailStages = @(
    'livelink_failure_classification',
    'livelink_environment',
    'development_standards',
    'ruff_all',
    'project_registry',
    'rf_quadrupole_generated_publications'
)
$fullRegressionStages = @(
    'common_contracts',
    'multipole_common',
    'integration_common',
    'rf_multipole_to_single_reflection_oatof_integration',
    'multipole_foundation',
    'solidworks_common',
    'single_reflection_oa_tof_mass_analyzer_static',
    'rf_quadrupole_static',
    'rf_hexapole_static',
    'rf_octupole_static',
    'wehnelt_static',
    'electron_impact_static'
)

$env:PYTHONDONTWRITEBYTECODE = '1'
$env:RUFF_NO_CACHE = 'true'
# Documentation recursively enumerates the repository.  Keep it exclusive
# because later test stages may create randomized fixtures below repo/.tmp.
Invoke-IntegrationStage 'documentation' $stageActions['documentation']
Invoke-ParallelIntegrationGroup $fastFailStages
# Freshness is in the completed group above.  No second quadrupole gate starts
# until that hard barrier has passed.
Invoke-ParallelIntegrationGroup $fullRegressionStages

Write-Output "REPOSITORY_INTEGRATION_GATE=PASS PYTHON=$pythonVersion"

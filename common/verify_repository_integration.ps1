[CmdletBinding()]
param(
    [string]$PythonExe = '',
    [ValidateRange(0, 32)][int]$MaxConcurrency = 0,
    [string]$InternalStage = '',
    [string]$InternalLogPath = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'require_powershell7.ps1')
. (Join-Path $PSScriptRoot 'parallel_gate_support.ps1')
. (Join-Path $PSScriptRoot 'gate_catalog_support.ps1')
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
$concurrencyMode = if ($MaxConcurrency -eq 0) { 'auto' } else { 'explicit' }
$MaxConcurrency = Resolve-GateConcurrency -Requested $MaxConcurrency
$routes = @(Read-GateCatalog -RepoRoot $repoRoot)

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
    repository_text_bytes = { & $PythonExe (Join-Path $PSScriptRoot 'verify_repository_text_bytes.py') }
    livelink_failure_classification = { & (Join-Path $PSScriptRoot 'comsol\test_livelink_failure_classification.ps1') }
    livelink_environment = { & (Join-Path $PSScriptRoot 'comsol\test_livelink_environment.ps1') }
    development_standards = { & $PythonExe (Join-Path $PSScriptRoot 'verify_development_standards.py') }
    ruff_all = {
        & $PythonExe -m ruff check (Join-Path $repoRoot 'common') `
            (Join-Path $repoRoot 'projects') (Join-Path $repoRoot 'integrations')
    }
}

foreach ($route in $routes) {
    if ($route.repository_integration_group -eq 'covered') { continue }
    $stage = [string]$route.stage
    if ($stageActions.Contains($stage)) {
        throw "Duplicate repository integration stage: $stage"
    }
    $command = if (
        $route.repository_integration_group -eq 'regression' -and
        $null -ne $route.PSObject.Properties['repository_integration_command']
    ) {
        $route.repository_integration_command
    } else {
        $route.command
    }
    $stageActions[$stage] = {
        Invoke-GateCatalogCommand -Command $command -RepoRoot $repoRoot `
            -PythonExe $PythonExe
    }.GetNewClosure()
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

Write-Output (
    "GATE_CONCURRENCY=$MaxConcurrency MODE=$concurrencyMode " +
    "LOGICAL_PROCESSORS=$([Environment]::ProcessorCount)"
)

$globalFastStages = @(
    'repository_text_bytes',
    'livelink_failure_classification',
    'livelink_environment',
    'development_standards',
    'ruff_all'
)
$catalogFastStages = @(
    $routes | Where-Object {
        $_.repository_integration_group -eq 'fast'
    } | ForEach-Object { [string]$_.stage }
)
$fastFailStages = @($globalFastStages + $catalogFastStages)
$fullRegressionStages = @(
    $routes | Where-Object {
        $_.repository_integration_group -eq 'regression'
    } | ForEach-Object { [string]$_.stage }
)

$env:PYTHONDONTWRITEBYTECODE = '1'
$env:RUFF_NO_CACHE = 'true'
# Documentation recursively enumerates the repository, so keep it exclusive.
Invoke-IntegrationStage 'documentation' $stageActions['documentation']
Invoke-ParallelIntegrationGroup $fastFailStages
# Freshness is in the completed group above.  No second quadrupole gate starts
# until that hard barrier has passed.
Invoke-ParallelIntegrationGroup $fullRegressionStages

Write-Output "REPOSITORY_INTEGRATION_GATE=PASS PYTHON=$pythonVersion"

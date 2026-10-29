[CmdletBinding()]
param(
    [string]$PythonExe = '',
    [string]$SummaryPath = '',
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
. (Join-Path $PSScriptRoot 'host_execution_lease.ps1')
if (-not $PythonExe) {
    $venvPython = Join-Path $repoRoot '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $venvPython -PathType Leaf) { $PythonExe = $venvPython }
    else { $PythonExe = (Get-Command python -ErrorAction Stop).Source }
}
$PythonExe = [IO.Path]::GetFullPath($PythonExe)
if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) { throw "Python runtime missing: $PythonExe" }
$pythonVersion = (& $PythonExe -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
if ($LASTEXITCODE -ne 0 -or $pythonVersion -ne '3.11') { throw "Repository integration gate requires Python 3.11, found $pythonVersion at $PythonExe" }
$originalSimulationPython = [Environment]::GetEnvironmentVariable('SIMULATION_PYTHON_EXE', 'Process')
$gateSummary = $null
$gateFailure = $null
try {
$env:SIMULATION_PYTHON_EXE = $PythonExe
$concurrencyMode = if ($MaxConcurrency -eq 0) { 'auto' } else { 'explicit' }
$MaxConcurrency = Resolve-GateConcurrency -Requested $MaxConcurrency
$routes = @(Read-GateCatalog -RepoRoot $repoRoot)
$catalogCommandInvoker = ${function:Invoke-GateCatalogCommand}

function Invoke-IntegrationStage {
    param([Parameter(Mandatory)][string]$Name, [Parameter(Mandatory)][scriptblock]$Action)
    Invoke-RecordedGateStage -Name $Name -Reason 'repository_integration' -Summary $gateSummary -Action {
        & $Action
        if ($LASTEXITCODE -ne 0) { throw "Repository integration stage failed: $Name" }
    }
}

$stageCommands = [ordered]@{
    documentation = [pscustomobject]@{ runner='powershell'; script='common/verify_documentation.ps1'; parameters=[pscustomobject]@{ PythonExe=$PythonExe } }
    repository_text_bytes = [pscustomobject]@{ runner='python'; arguments=@('common/verify_repository_text_bytes.py') }
    development_standards = [pscustomobject]@{ runner='python'; arguments=@('common/verify_development_standards.py') }
    ruff_all = [pscustomobject]@{ runner='python'; arguments=@('-m', 'ruff', 'check', 'common', 'projects', 'integrations') }
}

foreach ($route in $routes) {
    if ($route.repository_integration_group -eq 'covered') { continue }
    $stage = [string]$route.stage
    if ($stageCommands.Contains($stage)) {
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
    $stageCommands[$stage] = $command
}
$stageActions = [ordered]@{}
foreach ($stage in $stageCommands.Keys) {
    $command = $stageCommands[$stage]
    $stageActions[$stage] = {
        & $catalogCommandInvoker -Command $command -RepoRoot $repoRoot `
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
    $items = @($Names | ForEach-Object { $allStageItems[$_] })
    Invoke-IndependentGateStageGroup -Items $items `
        -Summary $gateSummary `
        -MaxConcurrency $MaxConcurrency -GateScriptPath $PSCommandPath `
        -PythonExe $PythonExe `
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

$allStageItems = [ordered]@{}
foreach ($name in $stageActions.Keys) {
    $route = @($routes | Where-Object { $_.stage -eq $name })
    $allStageItems[$name] = [pscustomobject]@{
        Name = $name; Run = $true; Reason = 'repository_integration'
        Action = $stageActions[$name]; Command = $stageCommands[$name]
        DependencyProfile = $(if ($route.Count -gt 0) { $route[0].dependency_profile } else { 'locked' })
        RequiresStages = $(if ($route.Count -gt 0 -and $null -ne $route[0].PSObject.Properties['requires_stages']) {
            @($route[0].requires_stages)
        } else { @() })
    }
}
$gateSummary = New-GateRunSummary -Items @($allStageItems.Values) `
    -GateName 'repository_integration' -SummaryPath $SummaryPath `
    -PythonExe $PythonExe -RepoRoot $repoRoot

Write-Output (
    "GATE_CONCURRENCY=$MaxConcurrency MODE=$concurrencyMode " +
    "LOGICAL_PROCESSORS=$([Environment]::ProcessorCount)"
)

$globalFastStages = @(
    'repository_text_bytes',
    'development_standards',
    'ruff_all'
)
$catalogFastStages = @(
    $routes | Where-Object {
        $_.repository_integration_group -eq 'fast'
    } | ForEach-Object { [string]$_.stage }
)
$priorityStages = @($globalFastStages + $catalogFastStages)
$fullRegressionStages = @(
    $routes | Where-Object {
        $_.repository_integration_group -eq 'regression'
    } | ForEach-Object { [string]$_.stage }
)

$env:PYTHONDONTWRITEBYTECODE = '1'
$env:RUFF_NO_CACHE = 'true'
# Documentation recursively enumerates the repository, so keep it exclusive.
try { Invoke-IntegrationStage 'documentation' $stageActions['documentation'] }
catch {
    if ($_.Exception -is [Management.Automation.PipelineStoppedException]) { throw }
    $gateFailure = $_
}
# The environment and catalog are valid here. A failed check does not suppress
# independent diagnostics; only explicit prerequisites block their successors.
try { Invoke-ParallelIntegrationGroup @($priorityStages + $fullRegressionStages) }
catch {
    if ($_.Exception -is [Management.Automation.PipelineStoppedException]) { throw }
    if ($null -eq $gateFailure) { $gateFailure = $_ }
    else { $gateFailure.Exception.Data['independent_stage_failure'] = $_.Exception.Message }
}
if ($null -ne $gateFailure) { throw $gateFailure }

Write-Output "REPOSITORY_INTEGRATION_GATE=PASS PYTHON=$pythonVersion"
} catch {
    $gateFailure = $_
    throw
} finally {
    try { Complete-GateRunSummary -Summary $gateSummary -Failure $gateFailure }
    finally {
        [Environment]::SetEnvironmentVariable('SIMULATION_PYTHON_EXE', $originalSimulationPython, 'Process')
    }
}

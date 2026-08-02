[CmdletBinding()]
param(
    [string]$PythonExe = '',
    [string[]]$ChangedPath = @(),
    [switch]$FullScope,
    [switch]$PlanOnly,
    [ValidateRange(0, 32)][int]$MaxConcurrency = 0,
    [string]$InternalStage = '',
    [string]$InternalRequestPath = '',
    [string]$InternalLogPath = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'require_powershell7.ps1')
. (Join-Path $PSScriptRoot 'parallel_gate_support.ps1')
. (Join-Path $PSScriptRoot 'gate_catalog_support.ps1')

$repoRoot = Split-Path -Parent $PSScriptRoot
if ($InternalStage) {
    if (-not $InternalRequestPath -or
        -not (Test-Path -LiteralPath $InternalRequestPath -PathType Leaf)) {
        throw 'InternalRequestPath is required for an internal changed-gate stage.'
    }
    $internalRequest = Get-Content -Raw -LiteralPath $InternalRequestPath |
        ConvertFrom-Json -Depth 8
    $PythonExe = [string]$internalRequest.python_exe
    $ChangedPath = @($internalRequest.changed_paths)
    $FullScope = [Management.Automation.SwitchParameter]::new(
        [bool]$internalRequest.full_scope
    )
}
if (-not $PythonExe) {
    $venvPython = Join-Path $repoRoot '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $venvPython -PathType Leaf) { $PythonExe = $venvPython }
    else { $PythonExe = (Get-Command python -ErrorAction Stop).Source }
}
$PythonExe = [IO.Path]::GetFullPath($PythonExe)
if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) { throw "Python runtime missing: $PythonExe" }
$pythonVersion = (& $PythonExe -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
if ($LASTEXITCODE -ne 0 -or $pythonVersion -ne '3.11') {
    throw "Changed-files gate requires Python 3.11, found $pythonVersion at $PythonExe"
}
$concurrencyMode = if ($MaxConcurrency -eq 0) { 'auto' } else { 'explicit' }
$MaxConcurrency = Resolve-GateConcurrency -Requested $MaxConcurrency

function ConvertTo-RepositoryPath {
    param([Parameter(Mandatory)][string]$Path)
    $candidate = if ([IO.Path]::IsPathRooted($Path)) { [IO.Path]::GetFullPath($Path) } else { [IO.Path]::GetFullPath((Join-Path $repoRoot $Path)) }
    $rootPrefix = $repoRoot.TrimEnd('\') + '\'
    if (-not $candidate.StartsWith($rootPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "ChangedPath must be inside repository: $Path"
    }
    return $candidate.Substring($rootPrefix.Length).Replace('\', '/')
}

function Get-ChangedRepositoryPaths {
    if ($ChangedPath.Count -gt 0) {
        $script:changedPathSource = 'EXPLICIT_CHANGED_PATH'
        return @($ChangedPath | ForEach-Object { ConvertTo-RepositoryPath $_ } | Sort-Object -Unique)
    }
    $head = (& git -C $repoRoot rev-parse --verify HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $head) {
        throw 'Changed-files gate cannot determine Git HEAD; pass -ChangedPath explicitly.'
    }
    $script:changedPathSource = "GIT_DIFF_BASE=HEAD:$head;UNTRACKED=git_ls_files"
    $tracked = @(& git -C $repoRoot diff --name-only --diff-filter=ACMRD HEAD)
    if ($LASTEXITCODE -ne 0) { throw 'git diff for changed-files gate failed.' }
    $untracked = @(& git -C $repoRoot ls-files --others --exclude-standard)
    if ($LASTEXITCODE -ne 0) { throw 'git ls-files for changed-files gate failed.' }
    return @($tracked + $untracked | Where-Object { $_ } | ForEach-Object { $_.Replace('\', '/') } | Sort-Object -Unique)
}

function Test-PathPrefix {
    param([Parameter(Mandatory)][string]$Prefix)
    return @($script:changedPaths | Where-Object { $_.StartsWith($Prefix, [StringComparison]::OrdinalIgnoreCase) }).Count -gt 0
}

function Test-AnyPath {
    param([Parameter(Mandatory)][scriptblock]$Predicate)
    return @($script:changedPaths | Where-Object $Predicate).Count -gt 0
}

function Get-ChangedRouteReason {
    param([Parameter(Mandatory)]$Route)
    foreach ($match in @($Route.matches)) {
        foreach ($path in $script:changedPaths) {
            if ($null -ne $match.PSObject.Properties['exact'] -and
                $path.Equals([string]$match.exact, [StringComparison]::OrdinalIgnoreCase)) {
                return [string]$match.reason
            }
            if ($null -ne $match.PSObject.Properties['prefix'] -and
                $path.StartsWith([string]$match.prefix, [StringComparison]::OrdinalIgnoreCase)) {
                return [string]$match.reason
            }
            if ($null -ne $match.PSObject.Properties['regex'] -and
                [regex]::IsMatch($path, [string]$match.regex, [Text.RegularExpressions.RegexOptions]::IgnoreCase)) {
                return [string]$match.reason
            }
        }
    }
    return ''
}

function Invoke-ChangedGateStage {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$Reason,
        [Parameter(Mandatory)][scriptblock]$Action
    )
    $timer = [Diagnostics.Stopwatch]::StartNew()
    Write-Output "GATE_STAGE=RUN NAME=$Name REASON=$Reason"
    & $Action
    if ($LASTEXITCODE -ne 0) { throw "Changed-files gate stage failed: $Name" }
    $timer.Stop()
    Write-Output "GATE_STAGE=PASS NAME=$Name ELAPSED_SECONDS=$([Math]::Round($timer.Elapsed.TotalSeconds, 3))"
}

function Skip-ChangedGateStage {
    param([Parameter(Mandatory)][string]$Name, [Parameter(Mandatory)][string]$Reason)
    Write-Output "GATE_STAGE=SKIP NAME=$Name REASON=$Reason"
}

if ($FullScope -and $ChangedPath.Count -gt 0) {
    throw 'FullScope and ChangedPath are mutually exclusive.'
}
$changedPaths = @()
if ($FullScope) {
    $changedPathSource = 'FULL_SCOPE'
} else {
    $changedPaths = @(Get-ChangedRepositoryPaths)
}
$routes = @(Read-GateCatalog -RepoRoot $repoRoot)
$codeExtensions = @('.py', '.ps1', '.m', '.lua', '.gem')
$hasCodeChange = $FullScope -or (Test-AnyPath {
    $codeExtensions -contains [IO.Path]::GetExtension($_).ToLowerInvariant()
})
$changedPython = @($changedPaths | Where-Object { [IO.Path]::GetExtension($_).ToLowerInvariant() -eq '.py' })
$existingPythonFiles = @(
    $changedPython |
        ForEach-Object { Join-Path $repoRoot $_ } |
        Where-Object { Test-Path -LiteralPath $_ -PathType Leaf }
)
$hasDocumentationChange = $FullScope -or (Test-AnyPath {
    [IO.Path]::GetExtension($_).ToLowerInvariant() -eq '.md'
})
$isDocumentationOnly = -not $FullScope -and $changedPaths.Count -gt 0 -and -not (Test-AnyPath {
    [IO.Path]::GetExtension($_).ToLowerInvariant() -ne '.md'
})

$stageItems = [ordered]@{}
function Add-ChangedStageItem {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][bool]$Run,
        [Parameter(Mandatory)][string]$Reason,
        [Parameter(Mandatory)][ValidateSet('stdlib', 'locked')]
        [string]$DependencyProfile,
        [scriptblock]$Action
    )
    $stageItems[$Name] = [pscustomobject]@{
        Name = $Name
        Run = $Run
        Reason = $Reason
        DependencyProfile = $DependencyProfile
        Action = $Action
    }
}

Add-ChangedStageItem 'repository_hygiene' $true 'always' 'stdlib' {
    & (Join-Path $PSScriptRoot 'verify_repository_hygiene.ps1')
}
Add-ChangedStageItem 'repository_text_bytes' $true 'always' 'stdlib' {
    & $PythonExe (Join-Path $PSScriptRoot 'verify_repository_text_bytes.py')
}
$documentationReason = if ($hasDocumentationChange) {
    'documentation_or_project_docs_changed'
} else {
    'no_documentation_path_changed'
}
Add-ChangedStageItem 'documentation' $hasDocumentationChange `
    $documentationReason 'stdlib' {
    & (Join-Path $PSScriptRoot 'verify_documentation.ps1')
}
$developmentReason = if ($hasCodeChange) {
    'source_code_changed'
} else {
    'no_source_code_path_changed'
}
Add-ChangedStageItem 'development_standards' $hasCodeChange `
    $developmentReason 'stdlib' {
    & $PythonExe (Join-Path $PSScriptRoot 'verify_development_standards.py')
}
if ($FullScope) {
    Add-ChangedStageItem 'ruff_changed_python' $true 'full_scope' 'locked' {
        & $PythonExe -m ruff check (Join-Path $repoRoot 'common') `
            (Join-Path $repoRoot 'projects') (Join-Path $repoRoot 'integrations')
    }
} elseif ($existingPythonFiles.Count -gt 0) {
    Add-ChangedStageItem 'ruff_changed_python' $true `
        'existing_python_source_changed' 'locked' {
        & $PythonExe -m ruff check -- @existingPythonFiles
    }
} elseif ($changedPython.Count -gt 0) {
    Add-ChangedStageItem 'ruff_changed_python' $false `
        'only_deleted_python_paths_changed' 'locked'
} else {
    Add-ChangedStageItem 'ruff_changed_python' $false `
        'no_python_path_changed' 'locked'
}

$catalogCommandInvoker = ${function:Invoke-GateCatalogCommand}.GetNewClosure()
$routeCommandInvoker = {
    param($Command)
    & $catalogCommandInvoker -Command $Command -RepoRoot $repoRoot `
        -PythonExe $PythonExe
}.GetNewClosure()
foreach ($route in $routes) {
    $name = [string]$route.stage
    $coveredByFullScopeStage = $FullScope -and
        $null -ne $route.PSObject.Properties['run_on_full_scope'] -and
        -not [bool]$route.run_on_full_scope
    if ($coveredByFullScopeStage) {
        Add-ChangedStageItem $name $false (
            "covered_by_$([string]$route.full_scope_coverage_stage)"
        ) ([string]$route.dependency_profile)
        continue
    }
    $reason = if ($FullScope) {
        'full_scope'
    } else {
        Get-ChangedRouteReason -Route $route
    }
    if ($reason) {
        $command = $route.command
        Add-ChangedStageItem $name $true $reason `
            ([string]$route.dependency_profile) {
            & $routeCommandInvoker -Command $command
        }.GetNewClosure()
    } else {
        Add-ChangedStageItem $name $false 'no_route_match' `
            ([string]$route.dependency_profile)
    }
}

foreach ($route in $routes) {
    $item = $stageItems[[string]$route.stage]
    if (-not $item.Run) { continue }
    $requiredStages = if (
        $null -ne $route.PSObject.Properties['requires_stages']
    ) {
        @($route.requires_stages)
    } else {
        @()
    }
    foreach ($requiredStage in $requiredStages) {
        if (-not $stageItems[[string]$requiredStage].Run) {
            throw "Selected gate stage is missing prerequisite: $($route.stage) -> $requiredStage"
        }
    }
}

function Invoke-InternalChangedStage {
    if (-not $stageItems.Contains($InternalStage)) {
        throw "Unknown changed-gate stage: $InternalStage"
    }
    $item = $stageItems[$InternalStage]
    if (-not $item.Run) {
        throw "Internal changed-gate stage was not selected: $InternalStage"
    }
    if (-not $InternalLogPath) {
        throw 'InternalLogPath is required for an internal changed-gate stage.'
    }
    $passed = Invoke-LoggedGateStage -Name $InternalStage `
        -LogPath $InternalLogPath -Action {
            Invoke-ChangedGateStage $item.Name $item.Reason $item.Action
        }
    if ($passed) { exit 0 }
    exit 1
}

function Invoke-ChangedStageGroup {
    param([Parameter(Mandatory)][string[]]$Names)
    $items = @($Names | ForEach-Object { $stageItems[$_] })
    $request = @{
        python_exe = $PythonExe
        full_scope = [bool]$FullScope
        changed_paths = @($changedPaths)
    }
    Invoke-IndependentGateStageGroup -Items $items `
        -MaxConcurrency $MaxConcurrency -GateScriptPath $PSCommandPath `
        -ChildBaseArguments @(
            '-MaxConcurrency', [string]$MaxConcurrency
        ) `
        -TempNamePrefix 'changed_gate_' `
        -FailureMessage 'Changed-files gate stages failed' `
        -RequestPayload $request `
        -InternalRequestParameter '-InternalRequestPath' `
        -InvokeInlineStage {
            param($item)
            Invoke-ChangedGateStage $item.Name $item.Reason $item.Action
        } `
        -InvokeSkipStage {
            param($item)
            Skip-ChangedGateStage $item.Name $item.Reason
        }
}

if ($InternalStage) {
    Invoke-InternalChangedStage
}

Write-Output "CHANGED_GATE_INPUT_SOURCE=$changedPathSource"
Write-Output "CHANGED_GATE_INPUTS=COUNT=$($changedPaths.Count) PATHS=$($changedPaths -join ',')"
Write-Output (
    "GATE_CONCURRENCY=$MaxConcurrency MODE=$concurrencyMode " +
    "LOGICAL_PROCESSORS=$([Environment]::ProcessorCount)"
)

if ($PlanOnly) {
    $selectedStages = @(
        $stageItems.Values | Where-Object { $_.Run } |
            ForEach-Object { $_.Name }
    )
    $dependencyProfile = if (@(
            $stageItems.Values | Where-Object {
                $_.Run -and $_.DependencyProfile -eq 'locked'
            }
        ).Count -gt 0) {
        'locked'
    } else {
        'stdlib'
    }
    Write-Output (
        "CHANGED_GATE_PLAN=PASS DEPENDENCY_PROFILE=$dependencyProfile " +
        "SELECTED_STAGES=$($selectedStages -join ',')"
    )
    return
}

$env:PYTHONDONTWRITEBYTECODE = '1'
$env:RUFF_NO_CACHE = 'true'
Invoke-ChangedGateStage 'repository_hygiene' 'always' (
    $stageItems['repository_hygiene'].Action
)
Invoke-ChangedGateStage 'repository_text_bytes' 'always' (
    $stageItems['repository_text_bytes'].Action
)

# Documentation recursively enumerates the repository and therefore runs
# exclusively before any test stage can create randomized repo/.tmp fixtures.
$documentation = $stageItems['documentation']
if ($documentation.Run) {
    Invoke-ChangedGateStage $documentation.Name $documentation.Reason (
        $documentation.Action
    )
} else {
    Skip-ChangedGateStage $documentation.Name $documentation.Reason
}

if ($isDocumentationOnly) {
    Write-Output 'CHANGED_GATE_FAST_PATH=DOCUMENTATION_ONLY'
    Write-Output "CHANGED_GATE=PASS PYTHON=$pythonVersion CHANGED_PATHS=$($changedPaths.Count)"
    return
}

$preFreshnessBarrier = @(
    'development_standards',
    'ruff_changed_python',
    'project_registry',
    'rf_quadrupole_generated_publications'
)
Invoke-ChangedStageGroup $preFreshnessBarrier

$postFreshnessStages = @(
    $routes |
        ForEach-Object { [string]$_.stage } |
        Where-Object {
            $_ -notin @(
                'project_registry',
                'rf_quadrupole_generated_publications'
            )
        }
)
# Any selected quadrupole Core gate is now separated from its Freshness gate by
# the completed group above; no two quadrupole gate instances run concurrently.
Invoke-ChangedStageGroup $postFreshnessStages

Write-Output "CHANGED_GATE=PASS PYTHON=$pythonVersion CHANGED_PATHS=$($changedPaths.Count) FULL_SCOPE=$([bool]$FullScope)"

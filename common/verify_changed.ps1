[CmdletBinding()]
param(
    [string]$PythonExe = '',
    [string[]]$ChangedPath = @(),
    [switch]$FullScope
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'require_powershell7.ps1')

$repoRoot = Split-Path -Parent $PSScriptRoot
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

function Read-ChangedScopeRoutes {
    $routePath = Join-Path $PSScriptRoot 'changed_scope_routes.json'
    if (-not (Test-Path -LiteralPath $routePath -PathType Leaf)) {
        throw "Changed-scope route table missing: $routePath"
    }
    $contract = Get-Content -Raw -LiteralPath $routePath | ConvertFrom-Json -Depth 32
    if ($contract.schema_version -ne 1 -or $contract.role -ne 'changed_scope_gate_routes') {
        throw 'Changed-scope route table has an unsupported identity.'
    }
    $routes = @($contract.routes)
    if ($routes.Count -eq 0) { throw 'Changed-scope route table must contain routes.' }

    $stageNames = @($routes | ForEach-Object { [string]$_.stage })
    if (@($stageNames | Where-Object { -not $_ }).Count -gt 0) {
        throw 'Every changed-scope route must define a stage.'
    }
    if (@($stageNames | Sort-Object -Unique).Count -ne $stageNames.Count) {
        throw 'Changed-scope route stage names must be unique.'
    }

    foreach ($route in $routes) {
        if (@($route.matches).Count -eq 0) {
            throw "Changed-scope route has no path matches: $($route.stage)"
        }
        foreach ($match in @($route.matches)) {
            $matchKinds = @(
                @('exact', 'prefix', 'regex') | Where-Object {
                    $null -ne $match.PSObject.Properties[$_]
                }
            )
            if ($matchKinds.Count -ne 1 -or -not [string]$match.reason) {
                throw "Changed-scope route match must define one matcher and a reason: $($route.stage)"
            }
        }
        if ([string]$route.command.runner -notin @('python', 'powershell')) {
            throw "Unsupported changed-scope route runner: $($route.stage)"
        }
        if ($route.command.runner -eq 'powershell') {
            $scriptPath = [string]$route.command.script
            if (-not $scriptPath) {
                throw "PowerShell changed-scope route is missing its script: $($route.stage)"
            }
            $resolvedScript = Join-Path $repoRoot $scriptPath
            if (-not (Test-Path -LiteralPath $resolvedScript -PathType Leaf)) {
                throw "Changed-scope route script missing: $scriptPath"
            }
        }
        if ($null -ne $route.PSObject.Properties['run_on_full_scope'] -and
            -not [bool]$route.run_on_full_scope) {
            $coverageStage = [string]$route.full_scope_coverage_stage
            if (-not $coverageStage -or $coverageStage -notin $stageNames) {
                throw "Full-scope route coverage stage is invalid: $($route.stage)"
            }
            if ([array]::IndexOf($stageNames, $coverageStage) -ge
                [array]::IndexOf($stageNames, [string]$route.stage)) {
                throw "Full-scope route coverage must run before the covered route: $($route.stage)"
            }
        }
    }

    $projectRoutes = @($routes | Where-Object {
        $null -ne $_.PSObject.Properties['project_id'] -and [string]$_.project_id
    })
    $discoveredProjectGates = @(
        Get-ChildItem -LiteralPath (Join-Path $repoRoot 'projects') -Directory |
            ForEach-Object {
                $gatePath = Join-Path $_.FullName 'verify_project.ps1'
                if (Test-Path -LiteralPath $gatePath -PathType Leaf) {
                    "projects/$($_.Name)/verify_project.ps1"
                }
            } |
            Sort-Object
    )
    $routedProjectGates = @(
        $projectRoutes |
            ForEach-Object { ([string]$_.command.script).Replace('\', '/') } |
            Sort-Object
    )
    if ($projectRoutes.Count -ne @($projectRoutes.project_id | Sort-Object -Unique).Count -or
        $routedProjectGates.Count -ne @($routedProjectGates | Sort-Object -Unique).Count) {
        throw 'Each project gate must have exactly one changed-scope project route.'
    }
    if (($discoveredProjectGates -join "`n") -cne ($routedProjectGates -join "`n")) {
        throw "Changed-scope project routes do not match discovered project gates.`nDISCOVERED=$($discoveredProjectGates -join ',')`nROUTED=$($routedProjectGates -join ',')"
    }
    return $routes
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

function Invoke-ChangedRouteCommand {
    param([Parameter(Mandatory)]$Command)
    Push-Location $repoRoot
    try {
        if ($Command.runner -eq 'python') {
            $arguments = @(
                @($Command.arguments) | ForEach-Object {
                    ([string]$_).Replace('{python}', $PythonExe)
                }
            )
            & $PythonExe @arguments
        } else {
            $scriptPath = Join-Path $repoRoot ([string]$Command.script)
            $parameters = @{}
            foreach ($property in $Command.parameters.PSObject.Properties) {
                $parameters[$property.Name] = ([string]$property.Value).Replace('{python}', $PythonExe)
            }
            & $scriptPath @parameters
        }
        if ($LASTEXITCODE -ne 0) {
            throw "Changed-scope route command failed with exit code $LASTEXITCODE."
        }
    } finally {
        Pop-Location
    }
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
$routes = @(Read-ChangedScopeRoutes)
Write-Output "CHANGED_GATE_INPUT_SOURCE=$changedPathSource"
Write-Output "CHANGED_GATE_INPUTS=COUNT=$($changedPaths.Count) PATHS=$($changedPaths -join ',')"

Invoke-ChangedGateStage 'repository_hygiene' 'always' { & (Join-Path $PSScriptRoot 'verify_repository_hygiene.ps1') }

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

if ($hasDocumentationChange) {
    Invoke-ChangedGateStage 'documentation' 'documentation_or_project_docs_changed' { & (Join-Path $PSScriptRoot 'verify_documentation.ps1') }
} else { Skip-ChangedGateStage 'documentation' 'no_documentation_path_changed' }

if ($isDocumentationOnly) {
    Write-Output 'CHANGED_GATE_FAST_PATH=DOCUMENTATION_ONLY'
    Write-Output "CHANGED_GATE=PASS PYTHON=$pythonVersion CHANGED_PATHS=$($changedPaths.Count)"
    return
}

if ($hasCodeChange) {
    Invoke-ChangedGateStage 'development_standards' 'source_code_changed' { & $PythonExe (Join-Path $PSScriptRoot 'verify_development_standards.py') }
} else { Skip-ChangedGateStage 'development_standards' 'no_source_code_path_changed' }

if ($FullScope) {
    Invoke-ChangedGateStage 'ruff_changed_python' 'full_scope' {
        & $PythonExe -m ruff check (Join-Path $repoRoot 'common') (Join-Path $repoRoot 'projects') (Join-Path $repoRoot 'integrations')
    }
} elseif ($existingPythonFiles.Count -gt 0) {
    Invoke-ChangedGateStage 'ruff_changed_python' 'existing_python_source_changed' {
        & $PythonExe -m ruff check -- @existingPythonFiles
    }
} elseif ($changedPython.Count -gt 0) {
    Skip-ChangedGateStage 'ruff_changed_python' 'only_deleted_python_paths_changed'
} else { Skip-ChangedGateStage 'ruff_changed_python' 'no_python_path_changed' }

foreach ($route in $routes) {
    $coveredByFullScopeStage = $FullScope -and
        $null -ne $route.PSObject.Properties['run_on_full_scope'] -and
        -not [bool]$route.run_on_full_scope
    if ($coveredByFullScopeStage) {
        Skip-ChangedGateStage ([string]$route.stage) "covered_by_$([string]$route.full_scope_coverage_stage)"
        continue
    }
    $reason = if ($FullScope) { 'full_scope' } else { Get-ChangedRouteReason -Route $route }
    if ($reason) {
        $command = $route.command
        Invoke-ChangedGateStage ([string]$route.stage) $reason {
            Invoke-ChangedRouteCommand -Command $command
        }
    } else {
        Skip-ChangedGateStage ([string]$route.stage) 'no_route_match'
    }
}

Write-Output "CHANGED_GATE=PASS PYTHON=$pythonVersion CHANGED_PATHS=$($changedPaths.Count) FULL_SCOPE=$([bool]$FullScope)"

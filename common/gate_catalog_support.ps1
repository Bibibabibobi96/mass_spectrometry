Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Test-GateCatalogCommand {
    param(
        [Parameter(Mandatory)]$Command,
        [Parameter(Mandatory)][string]$Stage,
        [Parameter(Mandatory)][string]$RepoRoot
    )
    if ([string]$Command.runner -notin @('python', 'powershell')) {
        throw "Unsupported gate catalog runner: $Stage"
    }
    if ($Command.runner -eq 'powershell') {
        $scriptPath = [string]$Command.script
        if (-not $scriptPath) {
            throw "PowerShell gate catalog command is missing its script: $Stage"
        }
        if (-not (Test-Path -LiteralPath (Join-Path $RepoRoot $scriptPath) -PathType Leaf)) {
            throw "Gate catalog script missing: $scriptPath"
        }
    }
}

function Read-GateCatalog {
    param([Parameter(Mandatory)][string]$RepoRoot)
    $catalogPath = Join-Path $PSScriptRoot 'gate_catalog.json'
    if (-not (Test-Path -LiteralPath $catalogPath -PathType Leaf)) {
        throw "Repository gate catalog missing: $catalogPath"
    }
    $contract = Get-Content -Raw -LiteralPath $catalogPath |
        ConvertFrom-Json -Depth 32
    if ($contract.schema_version -ne 2 -or
        $contract.role -ne 'repository_gate_catalog') {
        throw 'Repository gate catalog has an unsupported identity.'
    }
    $routes = @($contract.routes)
    if ($routes.Count -eq 0) {
        throw 'Repository gate catalog must contain routes.'
    }
    $stageNames = @($routes | ForEach-Object { [string]$_.stage })
    if (@($stageNames | Where-Object { -not $_ }).Count -gt 0 -or
        @($stageNames | Sort-Object -Unique).Count -ne $stageNames.Count) {
        throw 'Repository gate catalog stage names must be present and unique.'
    }

    foreach ($route in $routes) {
        $stage = [string]$route.stage
        if ([string]$route.dependency_profile -notin @('stdlib', 'locked')) {
            throw "Gate catalog dependency profile is invalid: $stage"
        }
        if ([string]$route.repository_integration_group -notin @(
                'fast', 'regression', 'covered'
            )) {
            throw "Gate catalog repository integration group is invalid: $stage"
        }
        if ($null -ne $route.PSObject.Properties['runtime_dependencies_path']) {
            $inventoryPath = Join-Path $RepoRoot ([string]$route.runtime_dependencies_path)
            if (-not (Test-Path -LiteralPath $inventoryPath -PathType Leaf)) {
                throw "Gate runtime dependency inventory missing: $inventoryPath"
            }
            $inventory = Get-Content -Raw -LiteralPath $inventoryPath |
                ConvertFrom-Json -Depth 32
            if ($inventory.schema_version -ne 2 -or
                $inventory.role -ne 'integration_runtime_dependencies' -or
                @($inventory.providers).Count -eq 0) {
                throw "Unsupported gate runtime dependency inventory: $inventoryPath"
            }
            $dependencyPaths = @(
                [string]$route.runtime_dependencies_path
                foreach ($provider in $inventory.providers) {
                    if (@($provider.files).Count -eq 0) {
                        throw "Gate runtime dependency provider has no files: $inventoryPath"
                    }
                    foreach ($file in $provider.files) {
                        $sourcePath = [string]$file.source_repo_path
                        if (-not $sourcePath -or -not (Test-Path -LiteralPath (
                                    Join-Path $RepoRoot $sourcePath
                                ) -PathType Leaf)) {
                            throw "Gate runtime dependency source missing: $sourcePath"
                        }
                        $sourcePath
                    }
                }
            ) | Sort-Object -Unique
            $route.matches = @($route.matches) + @(
                foreach ($sourcePath in $dependencyPaths) {
                    [pscustomobject]@{
                        exact = $sourcePath
                        reason = 'declared_runtime_dependency_changed'
                    }
                }
            )
        }
        if (@($route.matches).Count -eq 0) {
            throw "Gate catalog route has no path matches: $stage"
        }
        foreach ($match in @($route.matches)) {
            $matchKinds = @(
                @('exact', 'prefix', 'regex') | Where-Object {
                    $null -ne $match.PSObject.Properties[$_]
                }
            )
            if ($matchKinds.Count -ne 1 -or -not [string]$match.reason) {
                throw "Gate catalog match must define one matcher and a reason: $stage"
            }
        }
        Test-GateCatalogCommand -Command $route.command -Stage $stage `
            -RepoRoot $RepoRoot
        if ($null -ne $route.PSObject.Properties['test_selection']) {
            $selection = $route.test_selection
            if (@($selection.roots).Count -eq 0) {
                throw "Gate test owner requires discovery roots: $stage"
            }
            foreach ($root in @($selection.roots)) {
                if ([IO.Path]::IsPathRooted([string]$root) -or
                    [string]$root -match '(^|/)\.\.(/|$)' -or
                    -not ([string]$root).EndsWith('/') -or
                    -not (Test-Path -LiteralPath (Join-Path $RepoRoot $root) -PathType Container)) {
                    throw "Invalid gate test discovery root: $stage -> $root"
                }
            }
        }
        if ($null -ne $route.PSObject.Properties['repository_integration_command']) {
            Test-GateCatalogCommand `
                -Command $route.repository_integration_command `
                -Stage $stage -RepoRoot $RepoRoot
        }
        $requiredStages = if (
            $null -ne $route.PSObject.Properties['requires_stages']
        ) {
            @($route.requires_stages)
        } else {
            @()
        }
        foreach ($requiredStage in $requiredStages) {
            if ([string]$requiredStage -notin $stageNames -or
                [array]::IndexOf($stageNames, [string]$requiredStage) -ge
                [array]::IndexOf($stageNames, $stage)) {
                throw "Gate catalog prerequisite must name an earlier stage: $stage"
            }
        }
        if ($null -ne $route.PSObject.Properties['run_on_full_scope'] -and
            -not [bool]$route.run_on_full_scope) {
            $coverageStage = [string]$route.full_scope_coverage_stage
            if (-not $coverageStage -or $coverageStage -notin $stageNames -or
                [array]::IndexOf($stageNames, $coverageStage) -ge
                [array]::IndexOf($stageNames, $stage)) {
                throw "Full-scope route coverage stage is invalid: $stage"
            }
            if ($route.repository_integration_group -ne 'covered') {
                throw "A full-scope-covered route must be covered in L2: $stage"
            }
        }
    }

    $projectRoutes = @($routes | Where-Object {
        $null -ne $_.PSObject.Properties['project_id'] -and
        [string]$_.project_id
    })
    $discoveredProjectGates = @(
        Get-ChildItem -LiteralPath (Join-Path $RepoRoot 'projects') -Directory |
            ForEach-Object {
                $gatePath = Join-Path $_.FullName 'verify_project.ps1'
                if (Test-Path -LiteralPath $gatePath -PathType Leaf) {
                    "projects/$($_.Name)/verify_project.ps1"
                }
            } | Sort-Object
    )
    $routedProjectGates = @(
        $projectRoutes | ForEach-Object {
            ([string]$_.command.script).Replace('\', '/')
        } | Sort-Object
    )
    if (($discoveredProjectGates -join "`n") -cne
        ($routedProjectGates -join "`n")) {
        throw 'Gate catalog project routes do not match discovered project gates.'
    }

    $discoveredIntegrationGates = @(
        Get-ChildItem -LiteralPath (Join-Path $RepoRoot 'integrations') `
            -Filter 'verify_integration.ps1' -File -Recurse |
            ForEach-Object {
                $_.FullName.Substring($RepoRoot.Length + 1).Replace('\', '/')
            } | Sort-Object
    )
    $routedIntegrationGates = @(
        $routes | Where-Object {
            $scriptPath = if (
                $null -ne $_.command.PSObject.Properties['script']
            ) {
                [string]$_.command.script
            } else {
                ''
            }
            $scriptPath.Replace('\', '/').StartsWith(
                'integrations/', [StringComparison]::OrdinalIgnoreCase
            )
        } | ForEach-Object {
            ([string]$_.command.script).Replace('\', '/')
        } | Sort-Object
    )
    if (($discoveredIntegrationGates -join "`n") -cne
        ($routedIntegrationGates -join "`n")) {
        throw 'Gate catalog integration routes do not match discovered integration gates.'
    }
    return $routes
}

function Get-GateChangedTests {
    param(
        [Parameter(Mandatory)]$Route,
        [Parameter(Mandatory)][AllowEmptyCollection()][string[]]$ChangedPaths,
        [Parameter(Mandatory)][AllowEmptyCollection()][string[]]$KnownTestRoots,
        [Parameter(Mandatory)][string]$RepoRoot,
        [switch]$FullScope
    )
    if ($null -eq $Route.PSObject.Properties['test_selection']) { return $null }
    $selection = $Route.test_selection
    $roots = @($selection.roots)
    $related = @($ChangedPaths | Where-Object {
        $path = $_
        @($roots | Where-Object { $path.StartsWith($_, [StringComparison]::OrdinalIgnoreCase) }).Count -gt 0 -or
        ($null -ne $selection.PSObject.Properties['support_paths'] -and @(
            $selection.support_paths | Where-Object {
                $path.StartsWith($_, [StringComparison]::OrdinalIgnoreCase)
            }
        ).Count -gt 0) -or
        ($null -ne $selection.PSObject.Properties['scope'] -and
            $path.StartsWith([string]$selection.scope, [StringComparison]::OrdinalIgnoreCase) -and
            @($KnownTestRoots | Where-Object {
                $path.StartsWith($_, [StringComparison]::OrdinalIgnoreCase)
            }).Count -eq 0)
    })
    if ($FullScope) { $related = @($roots | ForEach-Object { $_ + '__init__.py' }) }
    if ($related.Count -eq 0) { return $null }
    $modules = @($related | Where-Object {
        $_ -match '/test_[^/]+\.py$' -and
        (($roots | ForEach-Object { $_.TrimEnd('/') }) -contains (Split-Path -Parent $_).Replace('\', '/')) -and
        (Test-Path -LiteralPath (Join-Path $RepoRoot $_) -PathType Leaf)
    })
    $expanded = $FullScope -or $modules.Count -ne $related.Count
    if ($expanded) {
        $discoveryRoots = @($roots)
        if ($null -ne $selection.PSObject.Properties['scope'] -and ($FullScope -or @($related | Where-Object {
            $path = $_
            @($KnownTestRoots | Where-Object {
                $path.StartsWith($_, [StringComparison]::OrdinalIgnoreCase)
            }).Count -eq 0
        }).Count -gt 0)) {
            $discoveryRoots += [string]$selection.scope
        }
        $modules = @(
            foreach ($root in ($discoveryRoots | Sort-Object -Unique)) {
                Get-ChildItem -LiteralPath (Join-Path $RepoRoot $root) -Filter 'test_*.py' -File -Recurse |
                    ForEach-Object { $_.FullName.Substring($RepoRoot.Length + 1).Replace('\', '/') } |
                    Where-Object {
                        $path = $_
                        # Shared fixtures expand each registered owner once;
                        # the scope fallback additionally owns only new roots.
                        @($roots | Where-Object { $path.StartsWith($_, [StringComparison]::OrdinalIgnoreCase) }).Count -gt 0 -or
                        @($KnownTestRoots | Where-Object { $path.StartsWith($_, [StringComparison]::OrdinalIgnoreCase) }).Count -eq 0
                    }
            }
        )
    }
    return [pscustomobject]@{
        Modules = @($modules | Sort-Object -Unique)
        Expanded = $expanded
        OnlyTestModules = -not $expanded -and $related.Count -eq $ChangedPaths.Count
        Reason = if ($FullScope) { 'full_scope_test_owner_discovery' }
            elseif ($expanded) { 'test_owner_discovery_for_deleted_support_or_unknown_path' }
            else { 'changed_test_modules' }
    }
}

function Invoke-GateCatalogCommand {
    param(
        [Parameter(Mandatory)]$Command,
        [Parameter(Mandatory)][string]$RepoRoot,
        [Parameter(Mandatory)][string]$PythonExe
    )
    Push-Location $RepoRoot
    try {
        if ($Command.runner -eq 'python') {
            $arguments = @(
                @($Command.arguments) | ForEach-Object {
                    ([string]$_).Replace('{python}', $PythonExe)
                }
            )
            $hasPythonPathRoots = $null -ne $Command.PSObject.Properties['python_path_roots']
            $originalPythonPath = [Environment]::GetEnvironmentVariable('PYTHONPATH', 'Process')
            try {
                if ($hasPythonPathRoots) {
                    # Explicit unittest modules retain the import roots that
                    # unittest discover previously supplied through start_dir.
                    $pythonSearchPath = @($Command.python_path_roots | ForEach-Object {
                        [IO.Path]::GetFullPath((Join-Path $RepoRoot ([string]$_)))
                    })
                    if ($null -ne $originalPythonPath) { $pythonSearchPath += $originalPythonPath }
                    [Environment]::SetEnvironmentVariable(
                        'PYTHONPATH', ($pythonSearchPath -join [IO.Path]::PathSeparator), 'Process'
                    )
                }
                & $PythonExe @arguments
            } finally {
                if ($hasPythonPathRoots) {
                    if ($null -eq $originalPythonPath) {
                        [Environment]::SetEnvironmentVariable('PYTHONPATH', [NullString]::Value, 'Process')
                    } else {
                        [Environment]::SetEnvironmentVariable('PYTHONPATH', $originalPythonPath, 'Process')
                    }
                }
            }
        } else {
            $scriptPath = Join-Path $RepoRoot ([string]$Command.script)
            $parameters = @{}
            if ($null -ne $Command.PSObject.Properties['parameters']) {
                foreach ($property in $Command.parameters.PSObject.Properties) {
                    $value = $property.Value
                    if ($value -is [string]) {
                        $value = $value.Replace('{python}', $PythonExe)
                    }
                    $parameters[$property.Name] = $value
                }
            }
            & $scriptPath @parameters
        }
        if ($LASTEXITCODE -ne 0) {
            throw "Gate catalog command failed with exit code $LASTEXITCODE."
        }
    } finally {
        Pop-Location
    }
}

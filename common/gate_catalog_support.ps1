Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function New-ResolvedGateStageRequest {
    <# Same-invocation executable selection, not completed-test evidence. #>
    param([Parameter(Mandatory)][object[]]$Items, [Parameter(Mandatory)][string]$PythonExe,
        [Collections.IDictionary]$Selection=$null)
    $index=0
    $records=@($Items | ForEach-Object {
        $item=$_
        $record=@{name=$item.Name;reason=$item.Reason;command=$item.Command;order=$index;
            dependency_profile=$item.DependencyProfile;requires_stages=@($item.RequiresStages|Where-Object{$_});selected=[bool]$item.Run}
        $index++
        $record
    })
    $request=@{python_exe=$PythonExe;stages=@($records|Where-Object{$_.selected-and$null-ne$_.command})}
    if($null-ne$Selection){
        $request.schema_version=1;$request.role='software_verification_plan';$request.selection=$Selection
        $request.skipped_stages=@($records|Where-Object{-not$_.selected})
    }
    return $request
}

function Get-GatePlanCheckoutState {
    <# Git owns clean source identity. Dirty/no-Git inputs use metadata only;
       ignored environments and solver payloads are never read or hashed. #>
    param([Parameter(Mandatory)][string]$RepoRoot,[string[]]$Paths=@(),[string[]]$IgnorePaths=@())
    $root=[IO.Path]::GetFullPath($RepoRoot)
    $head=$null;$dirty=@();$tracked=@()
    if(Test-Path -LiteralPath (Join-Path $root '.git')){
        $head=(& git -C $root rev-parse --verify HEAD).Trim()
        if($LASTEXITCODE-ne0){throw 'Cannot resolve verification checkout HEAD.'}
        $changed=(& git -C $root diff --name-only --no-renames -z HEAD)-join "`n"
        if($LASTEXITCODE-ne0){throw 'Cannot read verification checkout changes.'}
        $untracked=(& git -C $root ls-files --others --exclude-standard -z)-join "`n"
        if($LASTEXITCODE-ne0){throw 'Cannot read verification checkout additions.'}
        $dirty=@(($changed+$untracked)-split [char]0|Where-Object{$_}|Sort-Object -Unique)
        $listing=(& git -C $root ls-files -z)-join "`n"
        if($LASTEXITCODE-ne0){throw 'Cannot read verification checkout tracked paths.'}
        $tracked=@($listing-split [char]0|Where-Object{$_})
    }
    $ignored=@($IgnorePaths|Where-Object{$_}|ForEach-Object{[IO.Path]::GetFullPath($_)})
    $dirty=@($dirty|Where-Object{[IO.Path]::GetFullPath((Join-Path $root $_))-notin$ignored})
    $files=[ordered]@{}
    $candidates=@($Paths+$dirty|Where-Object{$_}|Sort-Object -Unique)
    foreach($relative in $candidates){
        $path=if([IO.Path]::IsPathRooted($relative)){[IO.Path]::GetFullPath($relative)}else{[IO.Path]::GetFullPath((Join-Path $root $relative))}
        if($path-in$ignored-or-not$path.StartsWith($root.TrimEnd('\')+'\',[StringComparison]::OrdinalIgnoreCase)){continue}
        if(Test-Path -LiteralPath $path -PathType Container){
            if($null-ne$head){continue}
            $members=@(Get-ChildItem -LiteralPath $path -Recurse -File|Where-Object{
                $_.Extension-in@('.py','.ps1','.m','.lua','.gem','.json','.yml')-and
                $_.FullName-notmatch '[\\/](?:\.venv|__pycache__|artifacts)[\\/]'
            }|ForEach-Object{$_.FullName})
        }else{$members=@($path)}
        foreach($member in $members|Sort-Object -Unique){
            if($member-in$ignored){continue}
            $key=[IO.Path]::GetRelativePath($root,$member).Replace('\','/')
            if($null-ne$head-and$key-in$tracked-and$key-notin$dirty){continue}
            $info=Get-Item -LiteralPath $member -ErrorAction SilentlyContinue
            $files[$key]=if($null-ne$info){@{exists=$true;bytes=$info.Length;modified_utc_ticks=$info.LastWriteTimeUtc.Ticks}}else{@{exists=$false}}
        }
    }
    return @{repository=$root;head=$head;dirty_paths=$dirty;files=$files}
}

function Get-GatePlanSourcePaths {
    param([Parameter(Mandatory)][object[]]$Items,[string[]]$ChangedPaths=@())
    $paths=@('common/verify.ps1','common/gate_catalog.json','common/gate_catalog_support.ps1','common/parallel_gate_support.ps1')+$ChangedPaths
    foreach($item in $Items|Where-Object{$_.Run-and$null-ne$_.Command}){
        if($item.Command.runner-eq'powershell'){
            $paths+=@([string]$item.Command.script)
            $arguments=@(if($null-ne$item.Command.PSObject.Properties['parameters']){
                $item.Command.parameters.PSObject.Properties|ForEach-Object{$_.Value}
            })
        }else{$arguments=@($item.Command.arguments)}
        foreach($argument in $arguments){
            if($argument-isnot[string]){continue}
            $value=[string]$argument
            if($value.StartsWith('-')){continue}
            if($value.Contains('/')-or$value.EndsWith('.py')){$paths+=@($value)}
            elseif($value-match '^(?:common|projects|integrations)\.[A-Za-z0-9_.]+$'){$paths+=@($value.Replace('.','/')+'.py')}
        }
    }
    return @($paths|Sort-Object -Unique)
}

function Assert-GatePlanCheckoutState {
    param([Parameter(Mandatory)]$Request,[Parameter(Mandatory)][string]$RepoRoot,[string[]]$IgnorePaths=@())
    if($Request.schema_version-ne1-or$Request.role-cne'software_verification_plan') {throw 'Unsupported software verification plan.'}
    $saved=$Request.checkout
    if([IO.Path]::GetFullPath([string]$saved.repository)-ine[IO.Path]::GetFullPath($RepoRoot)){throw 'Verification plan belongs to another checkout.'}
    $current=Get-GatePlanCheckoutState -RepoRoot $RepoRoot -Paths @($Request.source_paths) -IgnorePaths $IgnorePaths
    if($saved.head-cne$current.head-or(@($saved.dirty_paths)-join"`n")-cne(@($current.dirty_paths)-join"`n")){
        throw 'Verification checkout changed; create a new plan.'
    }
    foreach($key in @($saved.files.Keys)+@($current.files.Keys)|Sort-Object -Unique){
        if(-not$saved.files.Contains($key)-or-not$current.files.Contains($key)){throw 'Verification selection inputs changed; create a new plan.'}
        foreach($field in @('exists','bytes','modified_utc_ticks')){
            if($saved.files[$key][$field]-ne$current.files[$key][$field]){throw "Verification input changed: $key; create a new plan."}
        }
    }
}

function Invoke-ResolvedGateStage {
    <# Children run one resolved stage; catalog, modules and prerequisites were
       planned once by their parent. This is not a stored PASS or reuse cache. #>
    param([Parameter(Mandatory)][string]$RepoRoot, [Parameter(Mandatory)][string]$Stage,
        [AllowEmptyString()][string]$RequestPath, [AllowEmptyString()][string]$LogPath)
    if (-not $RequestPath -or -not (Test-Path -LiteralPath $RequestPath -PathType Leaf)) {
        throw 'InternalRequestPath is required for an internal gate stage.'
    }
    $request = Get-Content -Raw -LiteralPath $RequestPath | ConvertFrom-Json -Depth 32
    $selected = @($request.stages | Where-Object { $_.name -ceq $Stage })
    if ($selected.Count -ne 1 -or -not $LogPath) {
        throw 'Internal request must contain exactly one matching planned stage and a log path.'
    }
    $planned = $selected[0]
    if($null-ne$planned.PSObject.Properties['selected']-and-not$planned.selected){throw 'Internal stage was not selected.'}
    $python = [string]$request.python_exe
    Test-GateCatalogCommand -Command $planned.command -Stage $Stage -RepoRoot $RepoRoot
    $priorRuntime = [Environment]::GetEnvironmentVariable('SIMULATION_PYTHON_EXE', 'Process')
    try {
        $env:SIMULATION_PYTHON_EXE = $python
        return Invoke-LoggedGateStage -Name $Stage -LogPath $LogPath -Action {
            Invoke-RecordedGateStage -Name $Stage -Reason $planned.reason -Action {
                Invoke-GateCatalogCommand -Command $planned.command -RepoRoot $RepoRoot -PythonExe $python
            }
        }
    } finally {
        [Environment]::SetEnvironmentVariable('SIMULATION_PYTHON_EXE', $priorRuntime, 'Process')
    }
}

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

    # Exact domain ownership stays in this catalog. Exclude those known
    # specialized contracts from the conservative directory fallback; unknown
    # contracts and shared lifecycle/validator semantics still expand normally.
    $ownedContracts = @($routes | ForEach-Object { @($_.matches) } | Where-Object {
        $_.reason -eq 'owned_domain_schema_changed'
    } | ForEach-Object { [string]$_.exact } | Sort-Object -Unique)
    foreach ($route in $routes) {
        foreach ($match in @($route.matches)) {
            if ($null -ne $match.PSObject.Properties['regex'] -and
                ([string]$match.regex).StartsWith('^common/contracts/') -and $ownedContracts.Count) {
                $excluded = ($ownedContracts | ForEach-Object { [regex]::Escape($_) }) -join '|'
                $match.regex = '^(?!(?:' + $excluded + ')$)' + ([string]$match.regex).Substring(1)
            }
        }
        $stage = [string]$route.stage
        if ([string]$route.dependency_profile -notin @('stdlib', 'locked')) {
            throw "Gate catalog dependency profile is invalid: $stage"
        }
        if ([string]$route.repository_integration_group -notin @(
                'fast', 'regression'
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
        if ($null -ne $route.PSObject.Properties['repository_integration_partition']) {
            $partition = $route.repository_integration_partition
            $completeCommand = if ($null -ne $route.PSObject.Properties['repository_integration_command']) {
                $route.repository_integration_command
            } else { $route.command }
            $validRunner = if ($completeCommand.runner -eq 'powershell') {
                $null -ne $route.PSObject.Properties['repository_integration_command'] -and
                $null -ne $partition.PSObject.Properties['parameter'] -and
                [string]$partition.parameter -match '^[A-Za-z][A-Za-z0-9]*$'
            } else {
                $arguments = @($completeCommand.arguments)
                $null -ne $route.PSObject.Properties['test_selection'] -and
                $null -ne $route.test_selection.PSObject.Properties['scope'] -and
                $arguments.Count -eq 7 -and $arguments[0] -eq '-m' -and
                $arguments[1] -in @('unittest','common.gate_unittest') -and $arguments[2] -eq 'discover' -and
                $arguments[3] -eq '-s' -and ([string]$arguments[4]).TrimEnd('/') -ceq ([string]$route.test_selection.scope).TrimEnd('/') -and
                $arguments[5] -eq '-p' -and $arguments[6] -eq 'test_*.py' -and
                $null -ne $route.PSObject.Properties['partition_preflight'] -and -not [bool]$route.partition_preflight
            }
            if ($route.repository_integration_group -ne 'regression' -or -not $validRunner -or
                $null -eq $route.PSObject.Properties['test_selection'] -or
                $null -eq $route.test_selection.PSObject.Properties['scope'] -or
                [int]$partition.count -lt 2 -or [int]$partition.count -gt 8 -or
                [double]$partition.default_seconds -le 0) {
                throw "Invalid repository integration test partition: $stage"
            }
            $scope = [string]$route.test_selection.scope
            if ([IO.Path]::IsPathRooted($scope) -or $scope -match '(^|/)\.\.(/|$)' -or
                -not $scope.EndsWith('/') -or -not (Test-Path -LiteralPath (Join-Path $RepoRoot $scope) -PathType Container)) {
                throw "Invalid repository integration partition scope: $stage -> $scope"
            }
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
    $mappedPaths = @()
    $mappedModules = @()
    $mappedProfiles = @()
    if (-not $FullScope -and $null -ne $selection.PSObject.Properties['dependencies']) {
        foreach ($path in $ChangedPaths) {
            # Deleted authorities need the existing full-owner fallback, not a
            # stale leaf dependency mapping.
            if (-not (Test-Path -LiteralPath (Join-Path $RepoRoot $path) -PathType Leaf)) { continue }
            foreach ($dependency in $selection.dependencies) {
                if (Get-ChangedRouteReason -Route $dependency -Paths @($path)) {
                    $mappedPaths += $path
                    $mappedModules += @($dependency.modules)
                    $mappedProfiles += [string]$dependency.dependency_profile
                }
            }
        }
    }
    $related = @($ChangedPaths | Where-Object {
        $path = $_
        if ($path -in $mappedPaths) { return $false }
        @($roots | Where-Object { $path.StartsWith($_, [StringComparison]::OrdinalIgnoreCase) }).Count -gt 0 -or
        ($null -ne $selection.PSObject.Properties['support_paths'] -and @(
            $selection.support_paths | Where-Object {
                $supportPath = [string]$_
                if ($supportPath.EndsWith('/')) {
                    $path.StartsWith($supportPath, [StringComparison]::OrdinalIgnoreCase)
                } else {
                    $path.Equals($supportPath, [StringComparison]::OrdinalIgnoreCase)
                }
            }
        ).Count -gt 0) -or
        ($null -ne $selection.PSObject.Properties['scope'] -and
            $path.StartsWith([string]$selection.scope, [StringComparison]::OrdinalIgnoreCase) -and
            @($KnownTestRoots | Where-Object {
                $path.StartsWith($_, [StringComparison]::OrdinalIgnoreCase)
            }).Count -eq 0)
    })
    if (-not $FullScope -and @($ChangedPaths | Where-Object {
        $_ -notin $mappedPaths -and $_ -notin $related -and -not (Test-DocumentationPath $_)
    }).Count -gt 0) { return $null }
    if ($FullScope) { $related = @($roots | ForEach-Object { $_ + '__init__.py' }) }
    if ($related.Count -eq 0 -and $mappedModules.Count -eq 0) { return $null }
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
        Modules = @($modules + $mappedModules | Sort-Object -Unique)
        Expanded = $expanded -or $mappedModules.Count -gt 0
        # Expanded can cover only a project's selected roots. Equality with
        # the sole declared scope proves that every scope member was included.
        CompleteOwner = $expanded -and $roots.Count -eq 1 -and
            $null -ne $selection.PSObject.Properties['scope'] -and
            ([string]$roots[0]).TrimEnd('/') -ceq ([string]$selection.scope).TrimEnd('/')
        OnlyTestModules = -not $expanded -and $related.Count -eq $ChangedPaths.Count
        DependencyProfile = if ($related.Count -eq 0 -and $mappedProfiles.Count -gt 0 -and
            'locked' -notin $mappedProfiles) { 'stdlib' } else { [string]$Route.dependency_profile }
        Reason = if ($FullScope) { 'full_scope_test_owner_discovery' }
            elseif ($mappedModules.Count -gt 0 -and $related.Count -eq 0) { 'declared_owner_module_dependencies' }
            elseif ($expanded) { 'test_owner_discovery_for_deleted_support_or_unknown_path' }
            else { 'changed_test_modules' }
    }
}

function Get-GateRepositoryTestPartitions {
    <# Enumerate the owner's complete test scope once; weights affect order only. #>
    param([Parameter(Mandatory)]$Route, [Parameter(Mandatory)][string]$RepoRoot,
        [AllowEmptyCollection()][string[]]$Modules)
    $config = $Route.repository_integration_partition
    $root = Join-Path $RepoRoot ([string]$Route.test_selection.scope)
    $weights = @{}
    foreach ($property in $config.measured_seconds.PSObject.Properties) {
        if ([double]$property.Value -le 0) { throw "Invalid measured test duration: $($property.Name)" }
        $weights[$property.Name] = [double]$property.Value
    }
    $selected = if ($PSBoundParameters.ContainsKey('Modules')) { @($Modules) } else {
        @(Get-ChildItem -LiteralPath $root -Filter 'test_*.py' -File -Recurse | ForEach-Object {
            $_.FullName.Substring($RepoRoot.Length + 1).Replace('\', '/')
        })
    }
    $weightedModules = @($selected | Sort-Object -Unique | ForEach-Object {
        $name = ([string]$_).Replace('\','/').Replace('/','.') -replace '\.py$',''
        $baseName = ($name -split '\.')[-1]
        [pscustomobject]@{
            name = $name
            seconds = if ($weights.ContainsKey($baseName)) { $weights[$baseName] } else { [double]$config.default_seconds }
        }
    } | Sort-Object -Property @{Expression='seconds';Descending=$true}, @{Expression='name';Descending=$false})
    if (-not $weightedModules.Count) { throw "Repository integration test partition is empty: $($Route.stage)" }
    $groups = @(@(for ($i = 0; $i -lt [int]$config.count; $i++) {
        [pscustomobject]@{ index = $i; seconds = [double]0; modules = [Collections.Generic.List[string]]::new() }
    }))
    foreach ($module in $weightedModules) {
        $group = $groups | Sort-Object -Property seconds, index | Select-Object -First 1
        $group.modules.Add($module.name)
        $group.seconds += $module.seconds
    }
    return @($groups | Where-Object { $_.modules.Count -gt 0 })
}

function Invoke-GateCatalogCommand {
    param(
        [Parameter(Mandatory)]$Command,
        [Parameter(Mandatory)][string]$RepoRoot,
        [Parameter(Mandatory)][string]$PythonExe
    )
    $global:LASTEXITCODE = 0
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
                $argumentFile = $null
                try {
                    if ($arguments.Count -gt 3 -and ($arguments[0..2] -join '|') -eq '-m|ruff|check') {
                        # Ruff's official argfile protects the resolved child
                        # command from CreateProcessW's command-line limit too.
                        $argumentFile = [IO.Path]::GetTempFileName()
                        [IO.File]::WriteAllLines($argumentFile, [string[]]@($arguments | Select-Object -Skip 3),
                            [Text.UTF8Encoding]::new($false))
                        $arguments = @('-m', 'ruff', 'check', '--', ('@' + $argumentFile))
                    } elseif ($arguments.Count -gt 1 -and
                        $arguments[0] -eq 'common/verify_development_standards.py' -and $arguments[1] -eq '--path') {
                        $paths = @(for ($index = 1; $index -lt $arguments.Count; $index += 2) {
                            if ($arguments[$index] -ne '--path' -or $index + 1 -ge $arguments.Count) {
                                throw 'Development-standards changed-path projection is malformed.'
                            }
                            $arguments[$index + 1]
                        })
                        $argumentFile = [IO.Path]::GetTempFileName()
                        [IO.File]::WriteAllText($argumentFile, (ConvertTo-Json -InputObject $paths -Compress),
                            [Text.UTF8Encoding]::new($false))
                        $arguments = @($arguments[0], '--changed-paths-file', $argumentFile)
                    }
                    & $PythonExe @arguments
                } finally {
                    if ($argumentFile) { Remove-Item -LiteralPath $argumentFile }
                }
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

function Get-ChangedRouteReason {
    param([Parameter(Mandatory)]$Route, [string[]]$Paths)
    foreach ($match in @($Route.matches)) {
        foreach ($path in $Paths) {
            # Match Changed test owners with the same documentation boundary
            # already used by Get-GateOwnerChangedPaths. Explicit full/owner
            # plans do not call this Changed-path match to select their scope.
            if ($null -ne $Route.PSObject.Properties['test_selection'] -and
                (Test-DocumentationPath $path)) { continue }
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

function Test-DocumentationPath {
    param([Parameter(Mandatory)][string]$Path)
    return [IO.Path]::GetExtension($Path).Equals('.md', [StringComparison]::OrdinalIgnoreCase) -or
        $Path -match '^(?:(?:projects|integrations)/[^/]+/)?docs/history/[^/]+/[^/]+\.txt$'
}


function Get-GateOwnerChangedPaths {
    param([Parameter(Mandatory)]$Route, [AllowEmptyCollection()][string[]]$ChangedPaths)
    return @($ChangedPaths | Where-Object {
        -not (Test-DocumentationPath $_) -and (Get-ChangedRouteReason -Route $Route -Paths @($_))
    })
}

function ConvertTo-GateExecutionCommand {
    param([Parameter(Mandatory)]$Command)
    if ($Command.runner -eq 'python' -and @($Command.arguments).Count -ge 2 -and
        $Command.arguments[0] -eq '-m' -and $Command.arguments[1] -eq 'unittest') {
        $copy = $Command | ConvertTo-Json -Depth 32 | ConvertFrom-Json -Depth 32
        $copy.arguments[1] = 'common.gate_unittest'
        return $copy
    }
    return $Command
}

<#
.SYNOPSIS
Verify changed files, an owner, or the complete software repository.
.DESCRIPTION
Normal invocation plans and executes automatically. PlanOnly is optional.
-PlanOnly -PlanPath writes a same-checkout executable selection; -PlanPath
consumes it without catalog/module replanning (for CI dependency installation).
This plan records no PASS and confers no scientific or asset qualification.
#>
[CmdletBinding()]
param(
    [ValidateSet('Changed', 'Owner', 'Repository')][string]$Scope = 'Changed',
    [string[]]$Owner = @(),
    [string]$PythonExe = '',
    [string[]]$ChangedPath = @(),
    [switch]$FullScope,
    [switch]$PlanOnly,
    [string]$SummaryPath = '',
    [ValidateRange(0, 32)][int]$MaxConcurrency = 0,
    [string]$InternalStage = '',
    [Alias('PlanPath')][string]$InternalRequestPath = '',
    [string]$InternalLogPath = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$consumePlan = $InternalRequestPath -and -not $PlanOnly -and -not $InternalStage
if($consumePlan-and@(@('Scope','Owner','ChangedPath','FullScope')|Where-Object{$PSBoundParameters.ContainsKey($_)}).Count){
    throw 'PlanPath execution cannot override the frozen selection.'
}
$repositoryScope = $Scope -eq 'Repository'
$ownerScope = $Scope -eq 'Owner'
if ($ownerScope -and -not $Owner.Count) { throw 'Owner scope requires at least one explicit Owner.' }
if (-not $ownerScope -and $Owner.Count) { throw 'Owner is only valid with Owner scope.' }
if ($repositoryScope -or $ownerScope) {
    if ($ChangedPath.Count -or $FullScope) { throw 'Owner/Repository scope cannot be combined with ChangedPath or FullScope.' }
    # Repository chooses complete Static contracts below. Changed -FullScope
    # retains its existing Core/Static selection; these scopes are distinct.
    if ($repositoryScope) { $FullScope = $true }
}
. (Join-Path $PSScriptRoot 'require_powershell7.ps1')
. (Join-Path $PSScriptRoot 'parallel_gate_support.ps1')
. (Join-Path $PSScriptRoot 'gate_catalog_support.ps1')

$repoRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'host_execution_lease.ps1')
if ($InternalStage) {
    $passed = Invoke-ResolvedGateStage -RepoRoot $repoRoot -Stage $InternalStage `
        -RequestPath $InternalRequestPath -LogPath $InternalLogPath
    if ($passed) { exit 0 }
    exit 1
}

if($consumePlan){
    $resolvedPlan=Get-Content -LiteralPath $InternalRequestPath -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable -Depth 32
    Assert-GatePlanCheckoutState -Request $resolvedPlan -RepoRoot $repoRoot -IgnorePaths @($InternalRequestPath,$SummaryPath)
    if($PythonExe-and[IO.Path]::GetFullPath($PythonExe)-ine[IO.Path]::GetFullPath($resolvedPlan.python_exe)){
        throw 'PlanPath execution cannot change the selected Python runtime.'
    }
    $PythonExe=[string]$resolvedPlan.python_exe
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
$originalSimulationPython = [Environment]::GetEnvironmentVariable('SIMULATION_PYTHON_EXE', 'Process')
$gateSummary = $null
$gateFailure = $null
try {
$env:SIMULATION_PYTHON_EXE = $PythonExe
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
    $tracked = @(& git -C $repoRoot diff --name-only --no-renames --diff-filter=ACMRD HEAD)
    if ($LASTEXITCODE -ne 0) { throw 'git diff for changed-files gate failed.' }
    $untracked = @(& git -C $repoRoot ls-files --others --exclude-standard)
    if ($LASTEXITCODE -ne 0) { throw 'git ls-files for changed-files gate failed.' }
    return @($tracked + $untracked | Where-Object { $_ } | ForEach-Object { $_.Replace('\', '/') } | Sort-Object -Unique)
}

function Test-AnyPath {
    param([Parameter(Mandatory)][scriptblock]$Predicate)
    return @($script:changedPaths | Where-Object $Predicate).Count -gt 0
}


function Invoke-ChangedGateStage {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$Reason,
        [Parameter(Mandatory)][scriptblock]$Action
    )
    $changedStageAction = $Action
    Invoke-RecordedGateStage -Name $Name -Reason $Reason -Summary $gateSummary -Action {
        & $changedStageAction
        if ($LASTEXITCODE -ne 0) { throw "Changed-files gate stage failed: $Name" }
    }
}

function Skip-ChangedGateStage {
    param([Parameter(Mandatory)][string]$Name, [Parameter(Mandatory)][string]$Reason)
    Write-Output "GATE_STAGE=SKIP NAME=$Name REASON=$Reason"
}

function Add-ChangedStageItem {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][bool]$Run,
        [Parameter(Mandatory)][string]$Reason,
        [Parameter(Mandatory)][ValidateSet('stdlib', 'locked')]
        [string]$DependencyProfile
    )
    $stageItems[$Name] = [pscustomobject]@{
        Name = $Name
        Run = $Run
        Reason = $Reason
        DependencyProfile = $DependencyProfile
        Action = $null
        Command = $null
        RequiresStages = @()
    }
}

function Invoke-ChangedStageGroup {
    param([Parameter(Mandatory)][string[]]$Names)
    $items = @($Names | Where-Object { $stageItems.Contains($_) } | ForEach-Object { $stageItems[$_] })
    $request = New-ResolvedGateStageRequest -Items $items -PythonExe $PythonExe
    Invoke-IndependentGateStageGroup -Items $items `
        -StopOnFailure:(-not $repositoryScope) `
        -Summary $gateSummary `
        -MaxConcurrency $MaxConcurrency -GateScriptPath $PSCommandPath `
        -PythonExe $PythonExe `
        -ChildBaseArguments @(
            '-MaxConcurrency', [string]$MaxConcurrency
        ) `
        -TempNamePrefix $(if ($repositoryScope) { 'repository_integration_gate_' } else { 'changed_gate_' }) `
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

$stageItems=[ordered]@{}
if($consumePlan){
    $selection=$resolvedPlan.selection
    $Scope=[string]$selection.scope;$Owner=@($selection.owner)
    if($Scope-notin@('Changed','Owner','Repository')){throw 'Verification plan scope is invalid.'}
    $repositoryScope=$Scope-eq'Repository';$ownerScope=$Scope-eq'Owner'
    $FullScope=[bool]$selection.full_scope;$changedPaths=@($selection.changed_paths)
    $changedPathSource=[string]$selection.input_source;$isDocumentationOnly=[bool]$selection.documentation_only
    $executionOrder=@($selection.execution_order)
    foreach($record in @($resolvedPlan.stages)+@($resolvedPlan.skipped_stages)|Sort-Object order){
        if($stageItems.Contains([string]$record.name)){throw 'Duplicate stage in verification plan.'}
        if($record.dependency_profile-notin@('stdlib','locked')){throw 'Unknown planned dependency profile.'}
        if($record.selected){Test-GateCatalogCommand -Command ([pscustomobject]$record.command) -Stage $record.name -RepoRoot $repoRoot}
        Add-ChangedStageItem -Name $record.name -Run ([bool]$record.selected) -Reason $record.reason -DependencyProfile $record.dependency_profile
        $stageItems[$record.name].Command=$record.command
        $stageItems[$record.name].RequiresStages=@($record.requires_stages)
    }
    foreach($item in $stageItems.Values|Where-Object Run){
        foreach($required in $item.RequiresStages){
            if(-not$stageItems.Contains($required)-or-not$stageItems[$required].Run){throw 'Planned prerequisite was not selected.'}
        }
    }
}else{
if ($FullScope -and $ChangedPath.Count -gt 0) {
    throw 'FullScope and ChangedPath are mutually exclusive.'
}
$routes = @(Read-GateCatalog -RepoRoot $repoRoot)
if ($ownerScope) {
    $knownOwners = @($routes | ForEach-Object { if ($null -ne $_.PSObject.Properties['owner']) { [string]$_.owner }; [string]$_.stage })
    $unknownOwners = @($Owner | Where-Object { $_ -notin $knownOwners })
    if ($unknownOwners.Count) { throw "Unsupported verification owner: $($unknownOwners -join ',')." }
}
$changedPaths = @()
if ($FullScope) {
    $changedPathSource = 'FULL_SCOPE'
} elseif ($ownerScope) {
    $changedPathSource = 'EXPLICIT_OWNER'
    $ownerSources = foreach ($ownerName in $Owner) {
        $ownerRoutes = @($routes | Where-Object { [string]$_.stage -eq $ownerName -or
            ($null -ne $_.PSObject.Properties['owner'] -and [string]$_.owner -eq $ownerName) })
        $declaredOwners=@($ownerRoutes|ForEach-Object{if($null-ne$_.PSObject.Properties['owner']){[string]$_.owner}}|Sort-Object -Unique)
        $sourceOwner=if($declaredOwners.Count-eq1){$declaredOwners[0]}else{$ownerName}
        $root = if (Test-Path -LiteralPath (Join-Path $repoRoot $sourceOwner) -PathType Container) { $sourceOwner }
            elseif (Test-Path -LiteralPath (Join-Path $repoRoot ('projects/' + $sourceOwner)) -PathType Container) { 'projects/' + $sourceOwner }
            elseif (@($ownerRoutes | Where-Object { $_.command.runner -eq 'powershell' -and $_.command.script.StartsWith('integrations/') }).Count) { 'integrations' }
            else { $null }
        if ($root) {
            Get-ChildItem -LiteralPath (Join-Path $repoRoot $root) -File -Recurse | Where-Object {
                $_.Extension -in @('.py','.ps1','.m','.lua','.gem') -and $_.FullName -notmatch '[\\/]docs[\\/]history[\\/]'
            } | ForEach-Object { ConvertTo-RepositoryPath $_.FullName }
        } else {
            foreach ($route in $ownerRoutes) {
                foreach ($match in $route.matches) {
                    if ($null -ne $match.PSObject.Properties['exact'] -and (Test-Path -LiteralPath (Join-Path $repoRoot $match.exact) -PathType Leaf)) {
                        [string]$match.exact
                    }
                }
            }
        }
    }
    $changedPaths = @($ownerSources | Sort-Object -Unique)
} else {
    $changedPaths = @(Get-ChangedRepositoryPaths)
}
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
    Test-DocumentationPath $_
})
$isDocumentationOnly = -not $ownerScope -and -not $FullScope -and $changedPaths.Count -gt 0 -and -not (Test-AnyPath {
    # The standards' rule document is also a policy change, not the prose-only fast path.
    -not (Test-DocumentationPath $_) -or $_ -eq 'docs/DEVELOPMENT_STANDARDS.md'
})
$hasStandardsChange = $FullScope -or ($changedPaths.Count -gt 0 -and -not $isDocumentationOnly)
$knownTestRoots = @(
    $routes | Where-Object { $null -ne $_.PSObject.Properties['test_selection'] } |
        ForEach-Object { @($_.test_selection.roots) }
)

$stageItems = [ordered]@{}

Add-ChangedStageItem 'repository_hygiene' (-not $repositoryScope) 'changed_scope' 'stdlib'
Add-ChangedStageItem 'repository_text_bytes' $true 'always' 'stdlib'
$documentationReason = if ($hasDocumentationChange) {
    'documentation_or_project_docs_changed'
} else {
    'no_documentation_path_changed'
}
Add-ChangedStageItem 'documentation' $hasDocumentationChange `
    $documentationReason 'stdlib'
$developmentReason = if ($hasCodeChange) {
    'source_code_changed'
} elseif ($hasStandardsChange) {
    'configuration_or_unknown_path_changed'
} else {
    'no_source_code_path_changed'
}
Add-ChangedStageItem 'development_standards' $hasStandardsChange `
    $developmentReason 'stdlib'
if ($FullScope) {
    Add-ChangedStageItem 'ruff_changed_python' $true 'full_scope' 'locked'
} elseif ($existingPythonFiles.Count -gt 0) {
    Add-ChangedStageItem 'ruff_changed_python' $true `
        'existing_python_source_changed' 'locked'
} elseif ($changedPython.Count -gt 0) {
    Add-ChangedStageItem 'ruff_changed_python' $false `
        'only_deleted_python_paths_changed' 'locked'
} else {
    Add-ChangedStageItem 'ruff_changed_python' $false `
        'no_python_path_changed' 'locked'
}

$partitionParents = @{}
function Test-CompletePartitionOwnerCommand {
    param($Route, $Command, $TestSelection)
    if ($null -eq $Route.PSObject.Properties['repository_integration_partition'] -or
        $Command.runner -notin @('powershell','python')) { return $false }
    $complete = if ($null -ne $Route.PSObject.Properties['repository_integration_command']) {
        $Route.repository_integration_command
    } else { $Route.command }
    if ($Command.runner -eq 'python') {
        if ($complete.runner -ne 'python') { return $false }
        if ($null -ne $TestSelection -and $TestSelection.CompleteOwner) { return $true }
        return (ConvertTo-Json -InputObject @($Command.arguments) -Compress) -ceq
            (ConvertTo-Json -InputObject @($complete.arguments) -Compress)
    }
    if ($Command.runner -ne $complete.runner -or $Command.script -ne $complete.script) { return $false }
    # ChangedTestModules augments the complete owner discovery. Other command
    # differences matter: Changed Core checks must not become Repository Static checks.
    $moduleParameter = [string]$Route.test_selection.module_parameter
    $actualNames = @($Command.parameters.PSObject.Properties.Name | Where-Object { $_ -ne $moduleParameter } | Sort-Object)
    $completeNames = @($complete.parameters.PSObject.Properties.Name | Where-Object { $_ -ne 'PreflightOnly' } | Sort-Object)
    if (($actualNames -join '|') -cne ($completeNames -join '|')) { return $false }
    foreach ($parameter in $completeNames) {
        if ((ConvertTo-Json -InputObject $Command.parameters.$parameter -Depth 8 -Compress) -cne
            (ConvertTo-Json -InputObject $complete.parameters.$parameter -Depth 8 -Compress)) { return $false }
    }
    return $true
}
foreach ($route in $routes) {
    $name = [string]$route.stage
    $reason = if ($ownerScope) {
        if ([string]$route.stage -in $Owner -or
            ($null -ne $route.PSObject.Properties['owner'] -and [string]$route.owner -in $Owner)) { 'explicit_owner' } else { '' }
    } elseif ($FullScope) {
        'full_scope'
    } else {
        Get-ChangedRouteReason -Route $route -Paths $changedPaths
    }
    if ($reason) {
        $command = if (($repositoryScope -or $ownerScope) -and
            $null -ne $route.PSObject.Properties['repository_integration_command']) {
            $route.repository_integration_command
        } else { $route.command }
        # FullScope selects the complete owner contract. Its preflight is
        # separated below only when the existing catalog partitions apply.
        if (($FullScope -or $ownerScope) -and $command.runner -eq 'powershell' -and $null -ne $route.PSObject.Properties['repository_integration_partition']) {
            $command = $command | ConvertTo-Json -Depth 32 | ConvertFrom-Json -Depth 32
            $command.parameters.PSObject.Properties.Remove('PreflightOnly')
        }
        $ownerChangedPaths = @(Get-GateOwnerChangedPaths -Route $route -ChangedPaths $changedPaths)
        $testSelection = Get-GateChangedTests -Route $route -ChangedPaths $ownerChangedPaths `
            -KnownTestRoots $knownTestRoots -RepoRoot $repoRoot -FullScope:($FullScope -or $ownerScope)
        $preserveCommand = $null -ne $route.PSObject.Properties['test_selection'] -and
            $null -ne $route.test_selection.PSObject.Properties['preserve_command'] -and
            [bool]$route.test_selection.preserve_command
        if ($null -ne $testSelection -and
            ($preserveCommand -or -not $testSelection.OnlyTestModules) -and
            $null -ne $route.test_selection.PSObject.Properties['module_parameter']) {
            # The project gate merges this list with its own Core modules.  A
            # source change still executes the original project contract gate.
            $command = $command | ConvertTo-Json -Depth 32 | ConvertFrom-Json -Depth 32
            $moduleName = [string]$route.test_selection.module_parameter
            $testModules = @($testSelection.Modules | ForEach-Object {
                $_.Substring(0, $_.Length - 3).Replace('/', '.')
            })
            $command.parameters | Add-Member -NotePropertyName $moduleName -NotePropertyValue $testModules
            $reason = $testSelection.Reason
        }
        elseif ($null -ne $testSelection -and ($testSelection.OnlyTestModules -or
            ($testSelection.Expanded -and $command.runner -eq 'python'))) {
            $testModules = @($testSelection.Modules)
            $command = [pscustomobject]@{
                runner = 'python'; arguments = @('-m', 'unittest') + $testModules
                python_path_roots = @($route.test_selection.roots)
            }
            $reason = $testSelection.Reason
        } elseif ($null -ne $testSelection -and $testSelection.Expanded) {
            $reason = $testSelection.Reason
        }
        $partitions = @()
        if (($null -eq $testSelection -or -not $testSelection.OnlyTestModules) -and
            (Test-CompletePartitionOwnerCommand -Route $route -Command $command -TestSelection $testSelection)) {
            $partitionArguments = @{Route=$route;RepoRoot=$repoRoot}
            if ($command.runner -eq 'python' -and $null -ne $testSelection -and $testSelection.CompleteOwner) {
                $partitionArguments.Modules = @($testSelection.Modules)
            }
            $partitions = @(Get-GateRepositoryTestPartitions @partitionArguments)
            $command = $(if ($null -ne $route.PSObject.Properties['repository_integration_command']) {
                $route.repository_integration_command
            } else { $route.command }) | ConvertTo-Json -Depth 32 | ConvertFrom-Json -Depth 32
        }
        $command = ConvertTo-GateExecutionCommand -Command $command
        Add-ChangedStageItem $name $true $reason `
            $(if ($null -ne $testSelection) { $testSelection.DependencyProfile } else { [string]$route.dependency_profile })
        $stageItems[$name].Command = $command
        if ($partitions.Count -and $null -ne $route.PSObject.Properties['partition_preflight'] -and
            -not [bool]$route.partition_preflight) {
            # This owner's former preflight was only Ruff. The central source
            # check owns that responsibility; its test shards need no process.
            $stageItems[$name].Run = $false
            $stageItems[$name].Reason = if ($command.runner -eq 'python') {'owner_tests_partitioned_without_parent_process'} else {'tests_partitioned_without_duplicate_ruff_preflight'}
        }
        foreach ($partition in $partitions) {
            $partName = '{0}__tests_{1:D2}' -f $name, ([int]$partition.index + 1)
            if ($command.runner -eq 'python') {
                $partCommand = [pscustomobject]@{runner='python';
                    arguments=@('-m','unittest')+@($partition.modules);
                    python_path_roots=@($route.test_selection.roots)}
            } else {
                $partCommand = $route.repository_integration_command | ConvertTo-Json -Depth 32 | ConvertFrom-Json -Depth 32
                $partCommand.parameters.PSObject.Properties.Remove('PreflightOnly')
                $partCommand.parameters | Add-Member -NotePropertyName 'PreflightValidated' -NotePropertyValue $true
                $partCommand.parameters | Add-Member -NotePropertyName ([string]$route.repository_integration_partition.parameter) `
                    -NotePropertyValue @($partition.modules)
            }
            $partCommand = ConvertTo-GateExecutionCommand -Command $partCommand
            Add-ChangedStageItem $partName $true 'complete_owner_test_partition' `
                ([string]$route.dependency_profile)
            $stageItems[$partName].Command = $partCommand
            $partitionParents[$partName] = $name
        }
    } else {
        Add-ChangedStageItem $name $false 'no_route_match' `
            ([string]$route.dependency_profile)
    }
}

$prerequisitesAdded = $true
while ($prerequisitesAdded) {
    $prerequisitesAdded = $false
    foreach ($route in $routes) {
        if (-not $stageItems[[string]$route.stage].Run -or
            $null -eq $route.PSObject.Properties['requires_stages']) { continue }
        foreach ($requiredName in @($route.requires_stages)) {
            if ($stageItems[[string]$requiredName].Run) { continue }
            $required = $routes | Where-Object stage -eq $requiredName | Select-Object -First 1
            $command = if (($repositoryScope -or $ownerScope) -and
                $null -ne $required.PSObject.Properties['repository_integration_command']) {
                $required.repository_integration_command
            } else { $required.command }
            $command = ConvertTo-GateExecutionCommand -Command $command
            Add-ChangedStageItem ([string]$requiredName) $true ('required_by_' + $route.stage) `
                ([string]$required.dependency_profile)
            $stageItems[[string]$requiredName].Command = $command
            $prerequisitesAdded = $true
        }
    }
}

$registryConsumers = @($routes | Where-Object {
    $null -ne $_.PSObject.Properties['uses_project_registry'] -and $_.uses_project_registry -and
    $stageItems[[string]$_.stage].Run -and $stageItems[[string]$_.stage].Command.runner -eq 'powershell'
} | ForEach-Object { [string]$_.stage })
if ($registryConsumers.Count) {
    $registryRoute = $routes | Where-Object stage -eq 'project_registry' | Select-Object -First 1
    if (-not $stageItems['project_registry'].Run) {
        $command = ConvertTo-GateExecutionCommand -Command $registryRoute.command
        Add-ChangedStageItem 'project_registry' $true 'selected_owner_registry_prerequisite' 'locked'
        $stageItems['project_registry'].Command = $command
    }
    foreach ($name in $registryConsumers) {
        $stageItems[$name].Command.parameters | Add-Member -NotePropertyName RegistryPrevalidated -NotePropertyValue $true -Force
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
    $item.RequiresStages = $requiredStages
    if ([string]$route.stage -in $registryConsumers) {
        $item.RequiresStages = @($requiredStages + 'project_registry' | Sort-Object -Unique)
    }
    foreach ($requiredStage in $requiredStages) {
        if (-not $stageItems[[string]$requiredStage].Run) {
            throw "Selected gate stage is missing prerequisite: $($route.stage) -> $requiredStage"
        }
    }
}
foreach ($partName in $partitionParents.Keys) {
    $parent = $partitionParents[$partName]
    $stageItems[$partName].RequiresStages = $(if ($stageItems[$parent].Run) { @($parent) } else { @() })
}

# Logical analysis routes remain independently selected. Execute their short
# unittest modules together, keeping stdlib-only work out of locked batches.
foreach ($profile in @('stdlib', 'locked')) {
    $members = @($routes | Where-Object {
        $null -ne $_.PSObject.Properties['execution_batch'] -and $_.execution_batch -eq 'analysis' -and
        $stageItems[[string]$_.stage].Run -and $stageItems[[string]$_.stage].DependencyProfile -eq $profile
    } | ForEach-Object { $stageItems[[string]$_.stage] })
    if ($members.Count -lt 2) { continue }
    $modules = @($members | ForEach-Object { @($_.Command.arguments | Select-Object -Skip 2) } | Sort-Object -Unique)
    $command = [pscustomobject]@{ runner='python'; arguments=@('-m', 'common.gate_unittest') + $modules }
    $name = 'analysis_' + $profile + '_tests'
    Add-ChangedStageItem $name $true ('analysis_routes:' + (($members | ForEach-Object Name) -join ',')) $profile
    $stageItems[$name].Command = $command
    $stageItems[$name].RequiresStages = @($members | ForEach-Object { @($_.RequiresStages) } | Sort-Object -Unique)
    foreach ($member in $members) { $member.Run = $false; $member.Reason = 'executed_in_' + $name }
}


$stageItems['repository_hygiene'].Command = @{
    runner = 'powershell'; script = 'common/verify_repository_hygiene.ps1'
}
$stageItems['repository_text_bytes'].Command = @{
    runner = 'python'; arguments = @('common/verify_repository_text_bytes.py')
}
$stageItems['documentation'].Command = @{
    runner = 'powershell'; script = 'common/verify_documentation.ps1'
    parameters = @{ StructureOnly = (-not $repositoryScope); PythonExe = $PythonExe }
}
if (-not $FullScope) { $stageItems['documentation'].Command.parameters['ChangedPath'] = @($changedPaths) }
$stageItems['development_standards'].Command = @{
    runner = 'python'; arguments = @('common/verify_development_standards.py') + $(if (-not $FullScope) {
        @($changedPaths | ForEach-Object { '--path'; $_ })
    } else { @() })
}
$ownerRuffPaths = @($routes | Where-Object {
    $null -ne $_.PSObject.Properties['parent_ruff_paths'] -and $stageItems[[string]$_.stage].Run -and
    $stageItems[[string]$_.stage].Command.runner -eq 'powershell'
} | ForEach-Object { @($_.parent_ruff_paths) })
if ($ownerRuffPaths.Count) {
    $stageItems['ruff_changed_python'].Run = $true
    $stageItems['ruff_changed_python'].Reason = 'selected_owner_lint_responsibilities'
}
$stageItems['ruff_changed_python'].Command = @{
    runner = 'python'
    arguments = @('-m', 'ruff', 'check') + $(if ($FullScope) {
        @('common', 'projects', 'integrations')
    } else { @($existingPythonFiles + $ownerRuffPaths | Sort-Object -Unique) })
}
foreach ($item in $stageItems.Values) {
    if ($null -eq $item.Command) { continue }
    if ($item.Command.runner -eq 'powershell' -and
        $null -ne $item.Command.PSObject.Properties['parameters']) {
        foreach ($property in $item.Command.parameters.PSObject.Properties) {
            if ($property.Value -is [string]) {
                $property.Value = $property.Value.Replace('{python}', $PythonExe)
            }
        }
    } elseif ($item.Command.runner -eq 'python') {
        $item.Command.arguments = @($item.Command.arguments | ForEach-Object {
            ([string]$_).Replace('{python}', $PythonExe)
        })
    }
}


$priorityStages = @(
    'development_standards',
    'ruff_changed_python',
    'project_registry',
    'rf_multipole_generated_publications'
)
$partitionPriority = @($routes | ForEach-Object {
    $parent = [string]$_.stage
    $children = @($partitionParents.Keys | Where-Object { $partitionParents[$_] -eq $parent } | Sort-Object)
    if ($children.Count) { $parent; $children }
})
$priorityStages += $partitionPriority
$remainingStages = @(
    $stageItems.Keys |
        Where-Object {
            $_ -notin $priorityStages -and $_ -notin @('repository_hygiene', 'repository_text_bytes', 'documentation')
        }
)
# Short checks are offered first; catalog prerequisites govern readiness.
$executionOrder=@($priorityStages+$remainingStages|Where-Object{$stageItems.Contains($_)})
}
# Both normal and consumed plans execute exactly their compiled command data.
$catalogCommandInvoker=(Get-Command Invoke-GateCatalogCommand -CommandType Function).ScriptBlock
foreach($item in $stageItems.Values){
    if($null-eq$item.Command){continue}
    $plannedCommand=$item.Command|ConvertTo-Json -Depth 32|ConvertFrom-Json -Depth 32
    $item.Command=$plannedCommand
    $item.Action={& $catalogCommandInvoker -Command $plannedCommand -RepoRoot $repoRoot -PythonExe $PythonExe}.GetNewClosure()
}

Write-Output "CHANGED_GATE_INPUT_SOURCE=$changedPathSource"
Write-Output "SOFTWARE_GATE_SCOPE=$Scope FULL_CHANGED_SCOPE=$([bool]($FullScope -and -not $repositoryScope))"
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
    $effectiveStageNames = if ($isDocumentationOnly) {
        @('repository_hygiene', 'repository_text_bytes', 'documentation')
    } else { $selectedStages }
    $dependencyProfile = if (@(
            $effectiveStageNames | ForEach-Object { $stageItems[$_] } | Where-Object {
                $_.DependencyProfile -eq 'locked'
            }
        ).Count -gt 0) {
        'locked'
    } else {
        'stdlib'
    }
    if ($InternalRequestPath) {
        $selection=@{scope=$Scope;owner=@($Owner);full_scope=[bool]$FullScope;changed_paths=@($changedPaths);
            input_source=$changedPathSource;documentation_only=[bool]$isDocumentationOnly;execution_order=@($executionOrder);dependency_profile=$dependencyProfile}
        $request=New-ResolvedGateStageRequest -Items @($stageItems.Values) -PythonExe $PythonExe -Selection $selection
        $request.source_paths=@(Get-GatePlanSourcePaths -Items @($stageItems.Values) -ChangedPaths $changedPaths)
        $request.checkout=Get-GatePlanCheckoutState -RepoRoot $repoRoot -Paths $request.source_paths -IgnorePaths @($InternalRequestPath,$SummaryPath)
        $planPath=[IO.Path]::GetFullPath($InternalRequestPath)
        [IO.Directory]::CreateDirectory((Split-Path -Parent $planPath))|Out-Null
        Write-GateRunSummary -Summary @{Path=$planPath;Document=$request}
    }
    $executionMode = if ($repositoryScope) { 'REPOSITORY' } elseif ($ownerScope) { 'OWNER' } elseif ($isDocumentationOnly) {
        'DOCUMENTATION_ONLY'
    } else {
        'FULL_CHANGED_SCOPE'
    }
    $effectiveStages = $effectiveStageNames -join ','
    Write-Output (
        "CHANGED_GATE_PLAN=PASS DEPENDENCY_PROFILE=$dependencyProfile " +
        "EXECUTION_MODE=$executionMode " +
        "EFFECTIVE_STAGES=$effectiveStages " +
        "SELECTED_STAGES=$($selectedStages -join ',')"
    )
    return
}

$env:PYTHONDONTWRITEBYTECODE = '1'
$env:RUFF_NO_CACHE = 'true'
$summaryItems = if ($isDocumentationOnly) {
    @('repository_hygiene', 'repository_text_bytes', 'documentation') |
        ForEach-Object { $stageItems[$_] }
} else { @($stageItems.Values) }
$gateSummary = New-GateRunSummary -Items @($summaryItems) -GateName 'software_verification' `
    -PythonExe $PythonExe -RepoRoot $repoRoot -SummaryPath $SummaryPath
$gateSummary.Document.scope=$Scope;$gateSummary.Document.owner=@($Owner)
$gateSummary.Document.full_changed_scope=[bool]($FullScope-and-not$repositoryScope)
$gateSummary.Document.planned_request=$(if($consumePlan){[IO.Path]::GetFullPath($InternalRequestPath)}else{$null})
Write-GateRunSummary -Summary $gateSummary
foreach ($name in @('repository_hygiene', 'repository_text_bytes')) {
    if (-not $stageItems[$name].Run) { continue }
    try { Invoke-ChangedGateStage $name $stageItems[$name].Reason $stageItems[$name].Action }
    catch {
        if (-not $repositoryScope -or $_.Exception -is [Management.Automation.PipelineStoppedException]) { throw }
        if ($null -eq $gateFailure) { $gateFailure = $_ }
    }
}

# Documentation recursively enumerates the repository and therefore runs
# exclusively before any test stage can create randomized repo/.tmp fixtures.
$documentation = $stageItems['documentation']
if ($documentation.Run) {
    try { Invoke-ChangedGateStage $documentation.Name $documentation.Reason $documentation.Action }
    catch {
        if (-not $repositoryScope -or $_.Exception -is [Management.Automation.PipelineStoppedException]) { throw }
        if ($null -eq $gateFailure) { $gateFailure = $_ }
    }
} else {
    Skip-ChangedGateStage $documentation.Name $documentation.Reason
}

if ($isDocumentationOnly) {
    Write-Output 'CHANGED_GATE_FAST_PATH=DOCUMENTATION_ONLY'
    Write-Output "SOFTWARE_VERIFICATION=PASS SCOPE=$Scope PYTHON=$pythonVersion CHANGED_PATHS=$($changedPaths.Count)"
    return
}

Invoke-ChangedStageGroup $executionOrder
if ($null -ne $gateFailure) { throw $gateFailure }

Write-Output "SOFTWARE_VERIFICATION=PASS SCOPE=$Scope OWNERS=$($Owner -join ',') PYTHON=$pythonVersion FULL_CHANGED_SCOPE=$([bool]($FullScope-and-not$repositoryScope))"
} catch {
    $gateFailure = $_
    throw
} finally {
    try {
        Complete-GateRunSummary -Summary $gateSummary -Failure $gateFailure
    } finally {
        [Environment]::SetEnvironmentVariable('SIMULATION_PYTHON_EXE', $originalSimulationPython, 'Process')
    }
}

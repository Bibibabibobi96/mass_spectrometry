[CmdletBinding()]
param(
    [string]$PythonExe = '',
    [string[]]$ChangedPath = @(),
    [switch]$FullScope,
    [switch]$PlanOnly,
    [string]$SummaryPath = '',
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
. (Join-Path $PSScriptRoot 'host_execution_lease.ps1')
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
    Test-DocumentationPath $_
})
$isDocumentationOnly = -not $FullScope -and $changedPaths.Count -gt 0 -and -not (Test-AnyPath {
    # The standards' rule document is also a policy change, not the prose-only fast path.
    -not (Test-DocumentationPath $_) -or $_ -eq 'docs/DEVELOPMENT_STANDARDS.md'
})
$hasStandardsChange = $FullScope -or ($changedPaths.Count -gt 0 -and -not $isDocumentationOnly)
$knownTestRoots = @(
    $routes | Where-Object { $null -ne $_.PSObject.Properties['test_selection'] } |
        ForEach-Object { @($_.test_selection.roots) }
)

$stageItems = [ordered]@{}
$script:ChangedGateHygienePassed = $false
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
        Command = $null
        RequiresStages = @()
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
    & (Join-Path $PSScriptRoot 'verify_documentation.ps1') `
        -StructureOnly:$script:ChangedGateHygienePassed -PythonExe $PythonExe
}
$developmentReason = if ($hasCodeChange) {
    'source_code_changed'
} elseif ($hasStandardsChange) {
    'configuration_or_unknown_path_changed'
} else {
    'no_source_code_path_changed'
}
Add-ChangedStageItem 'development_standards' $hasStandardsChange `
    $developmentReason 'stdlib' {
    if ($FullScope) {
        & $PythonExe (Join-Path $PSScriptRoot 'verify_development_standards.py')
    } else {
        # Keep arbitrary path counts out of CreateProcessW's command line. The
        # persisted command below retains the actual paths for reproduction.
        $standardsPathsFile = [IO.Path]::GetTempFileName()
        try {
            [IO.File]::WriteAllText($standardsPathsFile,
                (ConvertTo-Json -InputObject @($changedPaths) -Compress), [Text.UTF8Encoding]::new($false))
            & $PythonExe (Join-Path $PSScriptRoot 'verify_development_standards.py') `
                --changed-paths-file $standardsPathsFile
        } finally {
            Remove-Item -LiteralPath $standardsPathsFile
        }
    }
}
if ($FullScope) {
    Add-ChangedStageItem 'ruff_changed_python' $true 'full_scope' 'locked' {
        & $PythonExe -m ruff check (Join-Path $repoRoot 'common') `
            (Join-Path $repoRoot 'projects') (Join-Path $repoRoot 'integrations')
    }
} elseif ($existingPythonFiles.Count -gt 0) {
    Add-ChangedStageItem 'ruff_changed_python' $true `
        'existing_python_source_changed' 'locked' {
        # Ruff's official argfile avoids CreateProcessW's command-line limit.
        # https://docs.astral.sh/ruff/configuration/#argfile-support
        $ruffArgumentFile = [IO.Path]::GetTempFileName()
        try {
            [IO.File]::WriteAllLines(
                $ruffArgumentFile, [string[]]$existingPythonFiles,
                [Text.UTF8Encoding]::new($false)
            )
            & $PythonExe -m ruff check -- ('@' + $ruffArgumentFile)
        } finally {
            Remove-Item -LiteralPath $ruffArgumentFile
        }
    }
} elseif ($changedPython.Count -gt 0) {
    Add-ChangedStageItem 'ruff_changed_python' $false `
        'only_deleted_python_paths_changed' 'locked'
} else {
    Add-ChangedStageItem 'ruff_changed_python' $false `
        'no_python_path_changed' 'locked'
}

$catalogCommandInvoker = ${function:Invoke-GateCatalogCommand}
$routeCommandInvoker = {
    param($Command)
    & $catalogCommandInvoker -Command $Command -RepoRoot $repoRoot `
        -PythonExe $PythonExe
}.GetNewClosure()
$partitionParents = @{}
function Test-CompletePartitionOwnerCommand {
    param($Route, $Command)
    if ($null -eq $Route.PSObject.Properties['repository_integration_partition'] -or
        $null -eq $Route.PSObject.Properties['repository_integration_command'] -or
        $Command.runner -ne 'powershell') { return $false }
    $complete = $Route.repository_integration_command
    if ($Command.runner -ne $complete.runner -or $Command.script -ne $complete.script) { return $false }
    # ChangedTestModules augments the complete owner discovery. Other command
    # differences matter: an L1 Core gate must not become an L2 Static gate.
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
        Get-ChangedRouteReason -Route $route -Paths $changedPaths
    }
    if ($reason) {
        $command = if ($FullScope -and
            $null -ne $route.PSObject.Properties['test_selection'] -and
            $null -ne $route.test_selection.PSObject.Properties['module_parameter'] -and
            $null -ne $route.PSObject.Properties['repository_integration_command']) {
            $route.repository_integration_command
        } else { $route.command }
        # FullScope selects the complete owner contract. Its preflight is
        # separated below only when the existing catalog partitions apply.
        if ($FullScope -and $null -ne $route.PSObject.Properties['repository_integration_partition']) {
            $command = $command | ConvertTo-Json -Depth 32 | ConvertFrom-Json -Depth 32
            $command.parameters.PSObject.Properties.Remove('PreflightOnly')
        }
        $ownerChangedPaths = @(Get-GateOwnerChangedPaths -Route $route -ChangedPaths $changedPaths)
        $testSelection = Get-GateChangedTests -Route $route -ChangedPaths $ownerChangedPaths `
            -KnownTestRoots $knownTestRoots -RepoRoot $repoRoot -FullScope:$FullScope
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
            (Test-CompletePartitionOwnerCommand -Route $route -Command $command)) {
            $partitions = @(Get-GateRepositoryTestPartitions -Route $route -RepoRoot $repoRoot)
            $command = $route.repository_integration_command | ConvertTo-Json -Depth 32 | ConvertFrom-Json -Depth 32
        }
        $command = ConvertTo-GateExecutionCommand -Command $command
        Add-ChangedStageItem $name $true $reason `
            ([string]$route.dependency_profile) {
            & $routeCommandInvoker -Command $command
        }.GetNewClosure()
        $stageItems[$name].Command = $command
        foreach ($partition in $partitions) {
            $partName = '{0}__tests_{1:D2}' -f $name, ([int]$partition.index + 1)
            $partCommand = $route.repository_integration_command | ConvertTo-Json -Depth 32 | ConvertFrom-Json -Depth 32
            $partCommand.parameters.PSObject.Properties.Remove('PreflightOnly')
            $partCommand.parameters | Add-Member -NotePropertyName 'PreflightValidated' -NotePropertyValue $true
            $partCommand.parameters | Add-Member -NotePropertyName ([string]$route.repository_integration_partition.parameter) `
                -NotePropertyValue @($partition.modules)
            Add-ChangedStageItem $partName $true 'complete_owner_test_partition' `
                ([string]$route.dependency_profile) {
                & $routeCommandInvoker -Command $partCommand
            }.GetNewClosure()
            $stageItems[$partName].Command = $partCommand
            $partitionParents[$partName] = $name
        }
    } else {
        Add-ChangedStageItem $name $false 'no_route_match' `
            ([string]$route.dependency_profile)
    }
}

foreach ($route in $routes) {
    if ($null -eq $route.PSObject.Properties['full_scope_coverage_stage']) { continue }
    $coverageStage = [string]$route.full_scope_coverage_stage
    if ($stageItems[$coverageStage].Run) {
        $item = $stageItems[[string]$route.stage]
        if (-not $item.Run) { continue }
        $coverCommand = $stageItems[$coverageStage].Command
        $itemCommand = $item.Command
        if ($null -eq $coverCommand -or $null -eq $itemCommand -or
            $itemCommand.runner -ne 'python') { continue }
        $itemArgs = @($itemCommand.arguments)
        if ($itemArgs.Count -lt 3 -or $itemArgs[0] -ne '-m' -or $itemArgs[1] -notin @('unittest', 'common.gate_unittest')) { continue }
        $coveredModules = @()
        $coverParts = @($partitionParents.Keys | Where-Object { $partitionParents[$_] -eq $coverageStage -and $stageItems[$_].Run })
        if ($coverParts.Count) {
            $coverageRoute = $routes | Where-Object { $_.stage -eq $coverageStage } | Select-Object -First 1
            $moduleParameter = [string]$coverageRoute.repository_integration_partition.parameter
            $coveredModules = @($coverParts | ForEach-Object { @($stageItems[$_].Command.parameters.$moduleParameter) })
        } elseif ($coverCommand.runner -eq 'python') {
            $coverArgs = @($coverCommand.arguments)
            if ($coverArgs.Count -lt 3 -or $coverArgs[0] -ne '-m' -or
                $coverArgs[1] -notin @('unittest', 'common.gate_unittest')) { continue }
            if ($coverArgs[2] -eq 'discover') {
                # Only the declared complete common-contract discovery covers its sibling routes.
                if (($coverArgs -join '|') -eq '-m|common.gate_unittest|discover|-s|common/contracts|-p|test_*.py') {
                    $coveredModules = @($itemArgs | Select-Object -Skip 2 | ForEach-Object {
                        ([string]$_).Replace('/', '.').Replace('\', '.') -replace '\.py$', ''
                    } | Where-Object {
                        $_ -match '^common\.contracts\.test_[^.]+$'
                    })
                }
            } else {
                $coveredModules = @($coverArgs | Select-Object -Skip 2 | ForEach-Object {
                    ([string]$_).Replace('/', '.').Replace('\', '.') -replace '\.py$', ''
                })
            }
        } else { continue }
        $remaining = @($itemArgs | Select-Object -Skip 2 | Where-Object {
            (([string]$_).Replace('/', '.').Replace('\', '.') -replace '\.py$', '') -notin $coveredModules
        })
        if ($remaining.Count -eq 0) {
            $item.Run = $false
            $item.Reason = "covered_by_$coverageStage"
        } elseif ($remaining.Count -lt ($itemArgs.Count - 2)) {
            $command = [pscustomobject]@{ runner = 'python'; arguments = @('-m', 'common.gate_unittest') + $remaining }
            if ($null -ne $itemCommand.PSObject.Properties['python_path_roots']) {
                $command | Add-Member -NotePropertyName 'python_path_roots' -NotePropertyValue @($itemCommand.python_path_roots)
            }
            $item.Command = $command
            $item.Action = { & $routeCommandInvoker -Command $command }.GetNewClosure()
            $item.Reason = "partially_covered_by_$coverageStage"
        }
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
    foreach ($requiredStage in $requiredStages) {
        if (-not $stageItems[[string]$requiredStage].Run) {
            throw "Selected gate stage is missing prerequisite: $($route.stage) -> $requiredStage"
        }
    }
}
foreach ($partName in $partitionParents.Keys) {
    $stageItems[$partName].RequiresStages = @($partitionParents[$partName])
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
        -StopOnFailure `
        -Summary $gateSummary `
        -MaxConcurrency $MaxConcurrency -GateScriptPath $PSCommandPath `
        -PythonExe $PythonExe `
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

$stageItems['repository_hygiene'].Command = @{
    runner = 'powershell'; script = 'common/verify_repository_hygiene.ps1'
}
$stageItems['repository_text_bytes'].Command = @{
    runner = 'python'; arguments = @('common/verify_repository_text_bytes.py')
}
$stageItems['documentation'].Command = @{
    runner = 'powershell'; script = 'common/verify_documentation.ps1'
    parameters = @{ StructureOnly = $true; PythonExe = $PythonExe }
}
$stageItems['development_standards'].Command = @{
    runner = 'python'; arguments = @('common/verify_development_standards.py') + $(if (-not $FullScope) {
        @($changedPaths | ForEach-Object { '--path'; $_ })
    } else { @() })
}
$stageItems['ruff_changed_python'].Command = @{
    runner = 'python'
    arguments = @('-m', 'ruff', 'check') + $(if ($FullScope) {
        @('common', 'projects', 'integrations')
    } else { $existingPythonFiles })
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
    $executionMode = if ($isDocumentationOnly) {
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
$gateSummary = New-GateRunSummary -Items @($summaryItems) -GateName 'changed_scope' `
    -PythonExe $PythonExe -RepoRoot $repoRoot -SummaryPath $SummaryPath
Invoke-ChangedGateStage 'repository_hygiene' 'always' (
    $stageItems['repository_hygiene'].Action
)
$script:ChangedGateHygienePassed = $true
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
    $routes |
        ForEach-Object { [string]$_.stage } |
        Where-Object {
            $_ -notin $priorityStages
        }
)
# Short checks are offered first; catalog prerequisites govern readiness.
Invoke-ChangedStageGroup @($priorityStages + $remainingStages)

Write-Output "CHANGED_GATE=PASS PYTHON=$pythonVersion CHANGED_PATHS=$($changedPaths.Count) FULL_SCOPE=$([bool]$FullScope)"
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

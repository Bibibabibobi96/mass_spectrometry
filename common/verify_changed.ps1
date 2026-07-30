[CmdletBinding()]
param(
    [string]$PythonExe = '',
    [string[]]$ChangedPath = @()
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

$changedPaths = @(Get-ChangedRepositoryPaths)
Write-Output "CHANGED_GATE_INPUT_SOURCE=$changedPathSource"
Write-Output "CHANGED_GATE_INPUTS=COUNT=$($changedPaths.Count) PATHS=$($changedPaths -join ',')"

Invoke-ChangedGateStage 'repository_hygiene' 'always' { & (Join-Path $PSScriptRoot 'verify_repository_hygiene.ps1') }

$codeExtensions = @('.py', '.ps1', '.m', '.lua', '.gem')
$hasCodeChange = Test-AnyPath { $codeExtensions -contains [IO.Path]::GetExtension($_).ToLowerInvariant() }
$changedPython = @($changedPaths | Where-Object { [IO.Path]::GetExtension($_).ToLowerInvariant() -eq '.py' })
$existingPythonFiles = @(
    $changedPython |
        ForEach-Object { Join-Path $repoRoot $_ } |
        Where-Object { Test-Path -LiteralPath $_ -PathType Leaf }
)
$hasDocumentationChange = Test-AnyPath {
    [IO.Path]::GetExtension($_).ToLowerInvariant() -eq '.md'
}
$isDocumentationOnly = $changedPaths.Count -gt 0 -and -not (Test-AnyPath {
    [IO.Path]::GetExtension($_).ToLowerInvariant() -ne '.md'
})
$hasRegistryChange = Test-PathPrefix 'config/project_registry.json'
$hasMultipoleChange = Test-PathPrefix 'common/multipole/'
$hasIntegrationHandoffPublisherChange = Test-AnyPath {
    $_ -eq 'common/multipole/publish_three_mode_binding.py'
}
$hasCommonIntegrationChange = Test-PathPrefix 'common/integration/'
$hasIntegrationInstanceChange = Test-PathPrefix 'integrations/'
$hasComponentPortChange = Test-AnyPath {
    $_ -match '^projects/[^/]+/config/interfaces/'
}
$hasIntegrationSchemaChange = Test-AnyPath {
    $_ -in @(
        'common/contracts/schemas/component_port.schema.json',
        'common/contracts/schemas/composition_plan.schema.json',
        'common/contracts/schemas/connection_profile.schema.json',
        'common/contracts/schemas/connection_profile_registry.schema.json',
        'common/contracts/schemas/execution_adapter_registry.schema.json',
        'common/contracts/schemas/integration_artifact_identity.schema.json',
        'common/contracts/schemas/integration_registry.schema.json',
        'common/contracts/schemas/migration_equivalence_preregistration.schema.json',
        'common/contracts/schemas/resolved_connection.schema.json'
    )
}
$hasIntegrationChange = $hasCommonIntegrationChange -or $hasIntegrationInstanceChange -or
    $hasComponentPortChange -or $hasIntegrationSchemaChange -or
    $hasIntegrationHandoffPublisherChange
$hasSolidWorksChange = Test-PathPrefix 'common/solidworks/'
$hasContractsChange = Test-PathPrefix 'common/contracts/'
$hasComsolCommonChange = Test-PathPrefix 'common/comsol/'
$hasGateContractChange = Test-AnyPath {
    $_ -in @(
        'common/verify_changed.ps1',
        'common/verify_repository_integration.ps1',
        'common/verify_lightweight.ps1',
        'common/require_powershell7.ps1',
        '.github/workflows/lightweight-gate.yml'
    )
}

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

if ($existingPythonFiles.Count -gt 0) {
    Invoke-ChangedGateStage 'ruff_changed_python' 'existing_python_source_changed' {
        & $PythonExe -m ruff check -- @existingPythonFiles
    }
} elseif ($changedPython.Count -gt 0) {
    Skip-ChangedGateStage 'ruff_changed_python' 'only_deleted_python_paths_changed'
} else { Skip-ChangedGateStage 'ruff_changed_python' 'no_python_path_changed' }

if ($hasRegistryChange -or (Test-AnyPath { $_ -match '^projects/[^/]+/config/project\.json$' })) {
    Invoke-ChangedGateStage 'project_registry' 'project_descriptor_or_registry_changed' { & $PythonExe (Join-Path $PSScriptRoot 'contracts\build_project_registry.py') --check }
} else { Skip-ChangedGateStage 'project_registry' 'no_project_descriptor_or_registry_changed' }

$needsQuadrupoleFreshness = (Test-PathPrefix 'projects/rf_quadrupole_ion_optics/') -or
    $hasContractsChange -or $hasMultipoleChange -or $hasComsolCommonChange
if ($needsQuadrupoleFreshness) {
    $quadrupoleGate = Join-Path $repoRoot 'projects\rf_quadrupole_ion_optics\verify_project.ps1'
    Invoke-ChangedGateStage 'rf_quadrupole_generated_publications' 'quadrupole_or_direct_dependency_changed' {
        & $quadrupoleGate -Level Freshness -PythonExe $PythonExe
    }
} else {
    Skip-ChangedGateStage 'rf_quadrupole_generated_publications' 'quadrupole_and_direct_dependencies_unchanged'
}

if ($hasContractsChange) {
    Invoke-ChangedGateStage 'common_contracts' 'common_contracts_changed' { & $PythonExe -m unittest discover -s (Join-Path $PSScriptRoot 'contracts') -p 'test_*.py' }
} else { Skip-ChangedGateStage 'common_contracts' 'common_contracts_not_changed' }

if ($hasGateContractChange) {
    Push-Location $repoRoot
    try {
        Invoke-ChangedGateStage 'gate_contract_tests' 'gate_entrypoint_or_workflow_changed' {
            & $PythonExe -m unittest common.contracts.test_verify_changed common.contracts.test_development_standards
        }
    } finally { Pop-Location }
} else { Skip-ChangedGateStage 'gate_contract_tests' 'no_gate_entrypoint_or_workflow_changed' }

if ($hasMultipoleChange) {
    Invoke-ChangedGateStage 'multipole_common' 'common_multipole_changed' { & $PythonExe -m unittest discover -s (Join-Path $PSScriptRoot 'multipole') -p 'test_*.py' }
    Push-Location $repoRoot
    try { Invoke-ChangedGateStage 'multipole_foundation' 'common_multipole_changed' { & $PythonExe -m common.multipole.verify_family_foundation } }
    finally { Pop-Location }
} else {
    Skip-ChangedGateStage 'multipole_common' 'common_multipole_not_changed'
    Skip-ChangedGateStage 'multipole_foundation' 'common_multipole_not_changed'
}

if ($hasCommonIntegrationChange -or $hasIntegrationSchemaChange) {
    Invoke-ChangedGateStage 'integration_common' 'common_integration_or_schema_changed' {
        & $PythonExe -m unittest discover -s (Join-Path $PSScriptRoot 'integration') -p 'test_*.py'
    }
} else {
    Skip-ChangedGateStage 'integration_common' 'common_integration_and_schemas_unchanged'
}

if ($hasIntegrationChange) {
    Invoke-ChangedGateStage 'rf_multipole_to_single_reflection_oatof_integration' 'integration_contract_port_or_handoff_publisher_changed' {
        & (Join-Path $repoRoot 'integrations\rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer\verify_integration.ps1') -PythonExe $PythonExe
    }
} else {
    Skip-ChangedGateStage 'rf_multipole_to_single_reflection_oatof_integration' 'integration_contracts_and_ports_unchanged'
}

if ($hasSolidWorksChange) {
    Invoke-ChangedGateStage 'solidworks_common' 'common_solidworks_changed' { & $PythonExe -m unittest discover -s (Join-Path $PSScriptRoot 'solidworks') -p 'test_*.py' }
} else { Skip-ChangedGateStage 'solidworks_common' 'common_solidworks_not_changed' }

$projectTriggers = [ordered]@{
    single_reflection_oa_tof_mass_analyzer = (Test-PathPrefix 'projects/single_reflection_oa_tof_mass_analyzer/') -or $hasContractsChange -or $hasComsolCommonChange
    rf_quadrupole_ion_optics = (Test-PathPrefix 'projects/rf_quadrupole_ion_optics/') -or $hasContractsChange -or $hasMultipoleChange -or $hasComsolCommonChange
    rf_hexapole_ion_optics = (Test-PathPrefix 'projects/rf_hexapole_ion_optics/') -or $hasMultipoleChange
    rf_octupole_ion_optics = (Test-PathPrefix 'projects/rf_octupole_ion_optics/') -or $hasMultipoleChange
    transverse_helical_filament_wehnelt_electron_gun = (Test-PathPrefix 'projects/transverse_helical_filament_wehnelt_electron_gun/') -or $hasContractsChange -or $hasComsolCommonChange
    apertured_tube_electron_impact_ion_source = (Test-PathPrefix 'projects/apertured_tube_electron_impact_ion_source/') -or $hasContractsChange
}
$projectReasons = @{
    single_reflection_oa_tof_mass_analyzer = if (Test-PathPrefix 'projects/single_reflection_oa_tof_mass_analyzer/') { 'single_reflection_oa_tof_mass_analyzer_path_changed' } elseif ($hasContractsChange) { 'common_contracts_direct_dependency_changed' } elseif ($hasComsolCommonChange) { 'common_comsol_direct_dependency_changed' } else { 'no_direct_dependency_changed' }
    rf_quadrupole_ion_optics = if (Test-PathPrefix 'projects/rf_quadrupole_ion_optics/') { 'rf_quadrupole_path_changed' } elseif ($hasContractsChange) { 'common_contracts_direct_dependency_changed' } elseif ($hasMultipoleChange) { 'common_multipole_direct_dependency_changed' } elseif ($hasComsolCommonChange) { 'common_comsol_direct_dependency_changed' } else { 'no_direct_dependency_changed' }
    rf_hexapole_ion_optics = if (Test-PathPrefix 'projects/rf_hexapole_ion_optics/') { 'rf_hexapole_path_changed' } elseif ($hasMultipoleChange) { 'common_multipole_direct_dependency_changed' } else { 'no_direct_dependency_changed' }
    rf_octupole_ion_optics = if (Test-PathPrefix 'projects/rf_octupole_ion_optics/') { 'rf_octupole_path_changed' } elseif ($hasMultipoleChange) { 'common_multipole_direct_dependency_changed' } else { 'no_direct_dependency_changed' }
    transverse_helical_filament_wehnelt_electron_gun = if (Test-PathPrefix 'projects/transverse_helical_filament_wehnelt_electron_gun/') { 'wehnelt_path_changed' } elseif ($hasContractsChange) { 'common_contracts_direct_dependency_changed' } elseif ($hasComsolCommonChange) { 'common_comsol_direct_dependency_changed' } else { 'no_direct_dependency_changed' }
    apertured_tube_electron_impact_ion_source = if (Test-PathPrefix 'projects/apertured_tube_electron_impact_ion_source/') { 'electron_impact_path_changed' } elseif ($hasContractsChange) { 'common_contracts_direct_dependency_changed' } else { 'no_direct_dependency_changed' }
}
$projectScripts = @{
    single_reflection_oa_tof_mass_analyzer = 'projects\single_reflection_oa_tof_mass_analyzer\verify_project.ps1'
    rf_quadrupole_ion_optics = 'projects\rf_quadrupole_ion_optics\verify_project.ps1'
    rf_hexapole_ion_optics = 'projects\rf_hexapole_ion_optics\verify_project.ps1'
    rf_octupole_ion_optics = 'projects\rf_octupole_ion_optics\verify_project.ps1'
    transverse_helical_filament_wehnelt_electron_gun = 'projects\transverse_helical_filament_wehnelt_electron_gun\verify_project.ps1'
    apertured_tube_electron_impact_ion_source = 'projects\apertured_tube_electron_impact_ion_source\verify_project.ps1'
}
foreach ($project in $projectTriggers.Keys) {
    $stage = "${project}_static"
    if ($projectTriggers[$project]) {
        $projectScript = Join-Path $repoRoot $projectScripts[$project]
        if ($project -eq 'rf_quadrupole_ion_optics') {
            Invoke-ChangedGateStage $stage $projectReasons[$project] { & $projectScript -Level Core -PythonExe $PythonExe }
        } else {
            Invoke-ChangedGateStage $stage $projectReasons[$project] { & $projectScript -PythonExe $PythonExe }
        }
    } else { Skip-ChangedGateStage $stage $projectReasons[$project] }
}

Write-Output "CHANGED_GATE=PASS PYTHON=$pythonVersion CHANGED_PATHS=$($changedPaths.Count)"

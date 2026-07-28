[CmdletBinding()]
param(
    [string]$PythonExe = ''
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
if ($LASTEXITCODE -ne 0 -or $pythonVersion -ne '3.11') { throw "Repository integration gate requires Python 3.11, found $pythonVersion at $PythonExe" }

function Invoke-IntegrationStage {
    param([Parameter(Mandatory)][string]$Name, [Parameter(Mandatory)][scriptblock]$Action)
    $timer = [Diagnostics.Stopwatch]::StartNew()
    Write-Output "GATE_STAGE=RUN NAME=$Name"
    & $Action
    if ($LASTEXITCODE -ne 0) { throw "Repository integration stage failed: $Name" }
    Write-Output "GATE_STAGE=PASS NAME=$Name ELAPSED_SECONDS=$([math]::Round($timer.Elapsed.TotalSeconds, 3))"
}

Invoke-IntegrationStage 'documentation' { & (Join-Path $PSScriptRoot 'verify_documentation.ps1') }
Invoke-IntegrationStage 'livelink_failure_classification' { & (Join-Path $PSScriptRoot 'comsol\test_livelink_failure_classification.ps1') }
Invoke-IntegrationStage 'livelink_environment' { & (Join-Path $PSScriptRoot 'comsol\test_livelink_environment.ps1') }
Invoke-IntegrationStage 'development_standards' { & $PythonExe (Join-Path $PSScriptRoot 'verify_development_standards.py') }
Invoke-IntegrationStage 'ruff_all' { & $PythonExe -m ruff check (Join-Path $repoRoot 'common') (Join-Path $repoRoot 'projects') }
Invoke-IntegrationStage 'project_registry' { & $PythonExe (Join-Path $PSScriptRoot 'contracts\build_project_registry.py') --check }
Invoke-IntegrationStage 'rf_quadrupole_generated_publications' {
    & (Join-Path $repoRoot 'projects\rf_quadrupole_ion_optics\verify_project.ps1') -Level Freshness -PythonExe $PythonExe
}
Invoke-IntegrationStage 'common_contracts' { & $PythonExe -m unittest discover -s (Join-Path $PSScriptRoot 'contracts') -p 'test_*.py' }
Invoke-IntegrationStage 'multipole_common' { & $PythonExe -m unittest discover -s (Join-Path $PSScriptRoot 'multipole') -p 'test_*.py' }
Invoke-IntegrationStage 'integration_common' { & $PythonExe -m unittest discover -s (Join-Path $PSScriptRoot 'integration') -p 'test_*.py' }
Invoke-IntegrationStage 'rf_multipole_to_single_reflection_oatof_integration' {
    & (Join-Path $repoRoot 'integrations\rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer\verify_integration.ps1') -PythonExe $PythonExe
}
Push-Location $repoRoot
try { Invoke-IntegrationStage 'multipole_foundation' { & $PythonExe -m common.multipole.verify_family_foundation } }
finally { Pop-Location }
Invoke-IntegrationStage 'solidworks_common' { & $PythonExe -m unittest discover -s (Join-Path $PSScriptRoot 'solidworks') -p 'test_*.py' }
Invoke-IntegrationStage 'single_reflection_oa_tof_mass_analyzer_static' { & (Join-Path $repoRoot 'projects\single_reflection_oa_tof_mass_analyzer\verify_project.ps1') -Level Static -PythonExe $PythonExe }
Invoke-IntegrationStage 'rf_quadrupole_static' { & (Join-Path $repoRoot 'projects\rf_quadrupole_ion_optics\verify_project.ps1') -Level Static -PythonExe $PythonExe }
Invoke-IntegrationStage 'rf_hexapole_static' { & (Join-Path $repoRoot 'projects\rf_hexapole_ion_optics\verify_project.ps1') -PythonExe $PythonExe }
Invoke-IntegrationStage 'rf_octupole_static' { & (Join-Path $repoRoot 'projects\rf_octupole_ion_optics\verify_project.ps1') -PythonExe $PythonExe }
Invoke-IntegrationStage 'wehnelt_static' { & (Join-Path $repoRoot 'projects\transverse_helical_filament_wehnelt_electron_gun\verify_project.ps1') -PythonExe $PythonExe }
Invoke-IntegrationStage 'electron_impact_static' { & (Join-Path $repoRoot 'projects\apertured_tube_electron_impact_ion_source\verify_project.ps1') -PythonExe $PythonExe }

Write-Output "REPOSITORY_INTEGRATION_GATE=PASS PYTHON=$pythonVersion"

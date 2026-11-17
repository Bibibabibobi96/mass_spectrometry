Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function New-RfPublishedDesignFreshnessPackage {
    <# Check only the requested fixed publication using frozen governance and its original checker. #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Python,
        [Parameter(Mandatory)][string]$SourceRoot,
        [Parameter(Mandatory)][string]$SnapshotRoot,
        [Parameter(Mandatory)][ValidateSet('interface','mass_filter')][string]$Profile
    )
    $sourceFiles = Get-FrozenPythonPackageRelativePaths -SourceRoot $SourceRoot -Python $Python `
        -PythonPackages @('common/contracts','projects/rf_multipole_ion_optics/analysis') `
        -PythonModules @('common/paths/repository_root.py')
    $sourcePackage = New-FrozenPythonPackage -Python $Python -SourceRoot $SourceRoot `
        -CodeRoot $SnapshotRoot -RelativePaths $sourceFiles
    $selectionScript = @'
import json, pathlib, sys
root = pathlib.Path(sys.argv[1]).resolve()
sys.path[:0] = [str(root / "src"), str(root)] if (root / "src").is_dir() else [str(root)]
from projects.rf_multipole_ion_optics.analysis import resolve_contract
assert pathlib.Path(resolve_contract.__file__).resolve().is_relative_to(root)
profile = resolve_contract.PROFILES[sys.argv[2]]
print(json.dumps({key: path.relative_to(root).as_posix() for key, path in profile.items()}))
'@
    $selectionText = (& $Python -I -B -c $selectionScript $SnapshotRoot $Profile | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) {throw 'Frozen RF publication resource selection failed.'}
    $selection = $selectionText | ConvertFrom-Json
    $resources = @($selection.PSObject.Properties | ForEach-Object {[string]$_.Value}) + @(
        'src/msplatform/components/rf_multipole/family_contract.json'
    )
    $resourcePackage = New-FrozenPythonPackage -Python $Python -SourceRoot $SourceRoot `
        -CodeRoot $SnapshotRoot -RelativePaths @($resources | Sort-Object -Unique)
    $package = $sourcePackage
    $package.files = @($sourcePackage.files) + @($resourcePackage.files)
    Assert-FrozenPythonPackage -Package $package
    . (Get-FrozenPythonPackageFile -Package $package -RelativePath 'src/msplatform/execution/resources/frozen_python_package.ps1')
    $check = Invoke-IsolatedFrozenPythonModule -Python $Python -Package $package `
        -Module 'projects.rf_multipole_ion_optics.analysis.resolve_contract' `
        -Arguments @('--profile',$Profile,'--check') `
        -DistributionNames @('jsonschema','referencing') `
        -RequiredModuleNames @('projects.rf_multipole_ion_optics.analysis.resolve_contract') `
        -ForbiddenRoots @($SourceRoot)
    [pscustomobject]@{
        profile = $Profile
        package = $package
        execution = $check
        resolved_path = Get-FrozenPythonPackageFile -Package $package -RelativePath ([string]$selection.output)
    }
}

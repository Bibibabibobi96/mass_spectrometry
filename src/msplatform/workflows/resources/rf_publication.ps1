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
        -PythonPackages @('src/msplatform')
    $sourcePackage = New-FrozenPythonPackage -Python $Python -SourceRoot $SourceRoot `
        -CodeRoot $SnapshotRoot -RelativePaths $sourceFiles
    $selectionScript = @'
import json, pathlib, sys
root = pathlib.Path(sys.argv[2]).resolve()
sys.path.insert(0, str(root / "src"))
from msplatform.workflows import rf_publication
assert pathlib.Path(rf_publication.__file__).resolve().is_relative_to(root)
print(json.dumps(rf_publication.PROFILE_RESOURCES[sys.argv[1]]))
'@
    $selectionText = (& $Python -I -B -c $selectionScript $Profile $SnapshotRoot | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) {throw 'Frozen RF publication resource selection failed.'}
    $selection = $selectionText | ConvertFrom-Json
    $resources = @($selection.PSObject.Properties | ForEach-Object {[string]$_.Value})
    $resourcePackage = New-FrozenPythonPackage -Python $Python -SourceRoot $SourceRoot `
        -CodeRoot $SnapshotRoot -RelativePaths @($resources | Sort-Object -Unique)
    $package = $sourcePackage
    $package.files = @($sourcePackage.files) + @($resourcePackage.files)
    Assert-FrozenPythonPackage -Package $package
    . (Get-FrozenPythonPackageFile -Package $package -RelativePath 'src/msplatform/execution/resources/frozen_python_package.ps1')
    $projectRoot = Join-Path $SnapshotRoot 'src/msplatform/components/rf_multipole'
    $check = Invoke-IsolatedFrozenPythonModule -Python $Python -Package $package `
        -Module 'msplatform.workflows.rf_publication' `
        -Arguments @('--project-root',$projectRoot,'--repository-root',$SnapshotRoot,'--profile',$Profile,'--check') `
        -DistributionNames @('jsonschema','referencing') `
        -RequiredModuleNames @('msplatform.workflows.rf_publication') `
        -ForbiddenRoots @($SourceRoot)
    [pscustomobject]@{
        profile = $Profile
        package = $package
        execution = $check
        resolved_path = Get-FrozenPythonPackageFile -Package $package -RelativePath ([string]$selection.output)
    }
}

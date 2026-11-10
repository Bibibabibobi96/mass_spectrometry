param([Parameter(Mandatory)][string]$ExecutionResourcePath)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if (-not [IO.Path]::IsPathFullyQualified($ExecutionResourcePath) -or
    -not (Test-Path -LiteralPath $ExecutionResourcePath -PathType Leaf)) {
    throw "Selected frozen Python execution resource is missing: $ExecutionResourcePath"
}
. $ExecutionResourcePath

function Get-FrozenPythonPackageExecutionPaths {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string[]]$RelativePaths)
    return @($RelativePaths | ForEach-Object {
        'inputs/code/' + ([string]$_ -replace '\\', '/')
    })
}

function Invoke-FrozenPythonInputs {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Python,[Parameter(Mandatory)][hashtable]$Request)
    # The explicit executor identifies the SAME selected installed/frozen provider.
    $resource = (Get-Command Assert-FrozenPythonPackage).ScriptBlock.File
    if (-not $resource) {throw 'Selected frozen Python execution resource has no source identity.'}
    $Request.inputs_module = Join-Path (Split-Path -Parent (Split-Path -Parent $resource)) 'inputs.py'
    if (-not (Test-Path -LiteralPath $Request.inputs_module -PathType Leaf)) {
        throw "Selected Python inputs implementation is missing: $($Request.inputs_module)"
    }
    $command = @'
import json, pathlib, sys, traceback
try:
    request = json.load(sys.stdin)
    selected = pathlib.Path(request['inputs_module']).resolve(strict=True)
    sys.path.insert(0, str(selected.parents[2]))
    from msplatform.execution import inputs
    if pathlib.Path(inputs.__file__).resolve() != selected:
        raise RuntimeError('Python package builder escaped its explicitly selected implementation')
    if request['action'] == 'enumerate':
        root = pathlib.Path(request['source_root']).resolve(strict=True)
        selected_paths = set()
        for selection in request['selections']:
            selected_paths.update(inputs.enumerate_python_sources(root, **selection))
        for relative in request['required_resources']:
            resource = root / relative
            if not resource.is_file() or not resource.resolve().is_relative_to(root):
                raise FileNotFoundError('Selected frozen Python execution resource is missing: ' + str(resource))
            selected_paths.add(relative)
        result = sorted(selected_paths)
    elif request['action'] == 'freeze':
        result = inputs.freeze_python_package(pathlib.Path(request['source_root']), pathlib.Path(request['code_root']),
                                             relative_paths=request['relative_paths'])
    else:
        raise ValueError('Unsupported internal Python inputs operation')
    print(json.dumps({'ok': True, 'value': result}))
except Exception as error:
    print(json.dumps({'ok': False, 'error': {'type': type(error).__name__, 'message': str(error), 'traceback': traceback.format_exc()}}))
    raise SystemExit(1)
'@
    $savedOutputEncoding=$OutputEncoding
    try {
        $OutputEncoding=[Text.UTF8Encoding]::new($false)
        $text=($Request|ConvertTo-Json -Depth 12 -Compress)| & $Python -X utf8 -I -B -c $command | Out-String
        $exitCode=$LASTEXITCODE
    } finally {$OutputEncoding=$savedOutputEncoding}
    $result=$text|ConvertFrom-Json
    if($exitCode-ne0-or-not$result.ok){
        throw "Selected frozen Python inputs operation failed: $($result.error.message)`n$($result.error.traceback)"
    }
    return $result.value
}

function Get-FrozenPythonPackageRelativePaths {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$SourceRoot,
        [Parameter(Mandatory)][string]$Python,
        [string[]]$PythonPackages=@(),[string[]]$PythonModules=@(),[string[]]$RelativePaths=@()
    )
    $selection=@()
    if($PythonPackages.Count-or$PythonModules.Count){
        $selections=@(@{package_roots=@($PythonPackages);module_paths=@($PythonModules)})
        $resources=@()
        if(Test-Path -LiteralPath (Join-Path $SourceRoot 'src/msplatform') -PathType Container){
            $selections+=@{package_roots=@('src/msplatform');provider_root='src/msplatform';resource_suffixes=@('.schema.json')}
            $resources=@('src/msplatform/execution/resources/frozen_python_package.ps1')
        }
        $selection=@(Invoke-FrozenPythonInputs -Python $Python -Request @{
            action='enumerate';source_root=[IO.Path]::GetFullPath($SourceRoot);
            selections=@($selections);required_resources=@($resources)})
    }
    return @($selection)+@($RelativePaths)
}

function New-FrozenPythonPackage {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$SourceRoot,
        [Parameter(Mandatory)][string]$CodeRoot,
        [string[]]$RelativePaths=@(),[string[]]$PythonPackages=@(),[string[]]$PythonModules=@(),
        [Parameter(Mandatory)][string]$Python
    )
    if($PythonPackages.Count-or$PythonModules.Count){
        $RelativePaths=Get-FrozenPythonPackageRelativePaths -SourceRoot $SourceRoot -Python $Python `
            -PythonPackages $PythonPackages -PythonModules $PythonModules -RelativePaths $RelativePaths
    }
    Invoke-FrozenPythonInputs -Python $Python -Request @{
        action='freeze';source_root=[IO.Path]::GetFullPath($SourceRoot);code_root=[IO.Path]::GetFullPath($CodeRoot);
        relative_paths=@($RelativePaths)}
}

function Get-FrozenPythonPackageFile {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]$Package,
        [Parameter(Mandatory)][string]$RelativePath
    )
    $normalized = $RelativePath -replace '\\', '/'
    $matches = @($Package.files | Where-Object {
        [string]$_.relative_path -ceq $normalized
    })
    if ($matches.Count -ne 1) {
        throw "Frozen Python inventory does not contain one file: $normalized"
    }
    [string]$matches[0].path
}

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
        -PythonPackages @(
            'common/contracts',
            'projects/rf_multipole_ion_optics/analysis',
            'projects/rf_multipole_ion_optics/core',
            'projects/rf_multipole_ion_optics/runtime'
        ) -PythonModules @('common/paths/repository_root.py')
    # Ask the frozen original PROFILES authority; do not maintain another profile map.
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
    # The scientific-core package selection already owns its schema resources.
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

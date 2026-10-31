Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-FrozenPythonPackageExecutionPaths {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string[]]$RelativePaths)
    return @($RelativePaths | ForEach-Object {
        'inputs/code/' + ([string]$_ -replace '\\', '/')
    })
}

function Get-FrozenPythonPackageRelativePaths {
    <# Expand Python groups through the common pure selector once before copying. #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$SourceRoot,
        [Parameter(Mandatory)][string]$Python,
        [string[]]$PythonPackages = @(),
        [string[]]$PythonModules = @(),
        [string[]]$RelativePaths = @()
    )
    $selection = @()
    if ($PythonPackages.Count -or $PythonModules.Count) {
        $request = @{source_root=[IO.Path]::GetFullPath($SourceRoot);
            package_roots=@($PythonPackages);module_paths=@($PythonModules)}
        $enumerate = @'
import json, pathlib, sys
request = json.load(sys.stdin)
root = pathlib.Path(request["source_root"]).resolve()
sys.path.insert(0, str(root))
from common.contracts import frozen_inputs
if pathlib.Path(frozen_inputs.__file__).resolve() != root / "common/contracts/frozen_inputs.py":
    raise RuntimeError("Frozen Python source selector escaped the selected source root")
print(json.dumps(frozen_inputs.enumerate_python_sources(
    root, package_roots=request["package_roots"], module_paths=request["module_paths"])))
'@
        $savedOutputEncoding = $OutputEncoding
        try {
            $OutputEncoding = [Text.UTF8Encoding]::new($false)
            $text = ($request | ConvertTo-Json -Depth 8 -Compress) |
                & $Python -X utf8 -I -B -c $enumerate | Out-String
            $selectionExitCode = $LASTEXITCODE
        } finally {
            $OutputEncoding = $savedOutputEncoding
        }
        if ($selectionExitCode -ne 0) {throw 'Frozen Python package/module selection failed.'}
        $selection = @($text | ConvertFrom-Json)
    }
    return @($selection) + @($RelativePaths)
}

function New-FrozenPythonPackage {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$SourceRoot,
        [Parameter(Mandatory)][string]$CodeRoot,
        [string[]]$RelativePaths = @(),
        [string[]]$PythonPackages = @(),
        [string[]]$PythonModules = @(),
        [string]$Python = ''
    )
    if ($PythonPackages.Count -or $PythonModules.Count) {
        if (-not $Python) {throw 'Python package/module selection requires the selected Python executable.'}
        $RelativePaths = Get-FrozenPythonPackageRelativePaths -SourceRoot $SourceRoot -Python $Python `
            -PythonPackages $PythonPackages -PythonModules $PythonModules -RelativePaths $RelativePaths
    }
    $resolvedSourceRoot = [IO.Path]::GetFullPath($SourceRoot)
    $resolvedCodeRoot = [IO.Path]::GetFullPath($CodeRoot)
    $seen = [Collections.Generic.HashSet[string]]::new(
        [StringComparer]::OrdinalIgnoreCase)
    $inventory = @()
    foreach ($relativePath in $RelativePaths) {
        if ([IO.Path]::IsPathRooted($relativePath) -or
            $relativePath -split '[/\\]' -contains '..') {
            throw "Frozen Python dependency path is not relative: $relativePath"
        }
        $normalized = $relativePath -replace '/', '\'
        if (-not $seen.Add($normalized)) {
            throw "Frozen Python dependency path is duplicated: $relativePath"
        }
        $source = [IO.Path]::GetFullPath((Join-Path $resolvedSourceRoot $normalized))
        if (-not $source.StartsWith(
            $resolvedSourceRoot + [IO.Path]::DirectorySeparatorChar,
            [StringComparison]::OrdinalIgnoreCase)) {
            throw "Frozen Python dependency escapes its source root: $relativePath"
        }
        $destination = Join-Path $resolvedCodeRoot $normalized
        Copy-VerifiedRunInput -Source $source -Destination $destination | Out-Null
        $inventory += [ordered]@{
            relative_path = $normalized -replace '\\', '/'
            path = [IO.Path]::GetFullPath($destination)
            sha256 = Get-RunFileSha256 -Path $destination
        }
    }
    [pscustomobject]@{
        schema_version = 1
        code_root = $resolvedCodeRoot
        package_roots = @($resolvedCodeRoot)
        files = $inventory
    }
}

function Assert-FrozenPythonPackage {
    [CmdletBinding()]
    param([Parameter(Mandatory)]$Package)
    $codeRoot = [IO.Path]::GetFullPath([string]$Package.code_root)
    $expectedPaths = [Collections.Generic.HashSet[string]]::new(
        [StringComparer]::OrdinalIgnoreCase)
    foreach ($entry in @($Package.files)) {
        $path = [IO.Path]::GetFullPath([string]$entry.path)
        if (-not $path.StartsWith(
            $codeRoot + [IO.Path]::DirectorySeparatorChar,
            [StringComparison]::OrdinalIgnoreCase) -or
            -not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "Frozen Python dependency is missing or outside its code root: $path"
        }
        if ((Get-RunFileSha256 -Path $path) -cne [string]$entry.sha256) {
            throw "Frozen Python dependency hash differs: $path"
        }
        if (-not $expectedPaths.Add($path)) {
            throw "Frozen Python inventory contains a duplicate path: $path"
        }
    }
    $actualPaths = @(Get-ChildItem -LiteralPath $codeRoot -Recurse -File |
        ForEach-Object { [IO.Path]::GetFullPath($_.FullName) })
    foreach ($path in $actualPaths) {
        if (-not $expectedPaths.Contains($path)) {
            throw "Frozen Python code root contains an untracked file: $path"
        }
    }
    if ($actualPaths.Count -ne $expectedPaths.Count) {
        throw 'Frozen Python code root inventory count differs.'
    }
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

function Invoke-IsolatedFrozenPythonModule {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Python,
        [Parameter(Mandatory)]$Package,
        [Parameter(Mandatory)][string]$Module,
        [Parameter(Mandatory)][string[]]$Arguments,
        [string[]]$DistributionNames = @(),
        [string[]]$RequiredModuleNames = @(),
        [string[]]$ForbiddenRoots = @(),
        [switch]$ProbeOnly
    )
    Assert-FrozenPythonPackage -Package $Package
    $packageRoots = @($Package.package_roots | ForEach-Object {
        [IO.Path]::GetFullPath([string]$_)
    })
    if ($packageRoots.Count -eq 0) {
        throw 'Frozen Python package roots must not be empty.'
    }
    foreach ($packageRoot in $packageRoots) {
        if (-not (Test-Path -LiteralPath $packageRoot -PathType Container)) {
            throw "Frozen Python package root is missing: $packageRoot"
        }
        foreach ($forbiddenRoot in $ForbiddenRoots) {
            $forbidden = [IO.Path]::GetFullPath($forbiddenRoot)
            if ($packageRoot.Equals(
                $forbidden,[StringComparison]::OrdinalIgnoreCase) -or
                $packageRoot.StartsWith(
                    $forbidden + [IO.Path]::DirectorySeparatorChar,
                    [StringComparison]::OrdinalIgnoreCase)) {
                throw "Frozen Python package root overlaps a forbidden live root: $packageRoot"
            }
        }
    }
    $savedPythonPath = $env:PYTHONPATH
    $savedNoUserSite = $env:PYTHONNOUSERSITE
    $savedNoBytecode = $env:PYTHONDONTWRITEBYTECODE
    try {
        $env:PYTHONPATH = $packageRoots -join [IO.Path]::PathSeparator
        $env:PYTHONNOUSERSITE = '1'
        $env:PYTHONDONTWRITEBYTECODE = '1'
        Push-Location -LiteralPath $packageRoots[0]
        try {
            $probe = @'
import importlib.metadata
import importlib.util
import json
import pathlib
import site
import sys

root_count = int(sys.argv[1])
package_roots = [pathlib.Path(value).resolve() for value in sys.argv[2:2 + root_count]]
distribution_count_index = 2 + root_count
distribution_count = int(sys.argv[distribution_count_index])
distribution_names = sys.argv[
    distribution_count_index + 1:distribution_count_index + 1 + distribution_count
]
module_names = sys.argv[distribution_count_index + 1 + distribution_count:]
distributions = []
modules = []
user_site = pathlib.Path(site.getusersitepackages()).resolve()
for name in distribution_names:
    distribution = importlib.metadata.distribution(name)
    root = pathlib.Path(distribution.locate_file("")).resolve()
    spec = importlib.util.find_spec(name)
    module_path = pathlib.Path(spec.origin).resolve() if spec and spec.origin else None
    if root == user_site or user_site in root.parents:
        raise RuntimeError(f"distribution resolved from user site: {name} -> {root}")
    if module_path is None or not (
        module_path == root or root in module_path.parents
    ):
        raise RuntimeError(
            f"distribution module escaped its recorded installation root: "
            f"{name} -> {module_path}"
        )
    distributions.append({
        "name": name,
        "version": distribution.version,
        "distribution_root": str(root),
        "module_path": str(module_path) if module_path else None,
    })
for name in module_names:
    spec = importlib.util.find_spec(name)
    if spec is None or spec.origin is None:
        raise RuntimeError(f"required frozen module has no file origin: {name}")
    origin = pathlib.Path(spec.origin).resolve()
    if not any(origin == root or root in origin.parents for root in package_roots):
        raise RuntimeError(f"required module escaped frozen roots: {name} -> {origin}")
    modules.append({"name": name, "origin": str(origin)})
print(json.dumps({
    "python_executable": sys.executable,
    "python_prefix": sys.prefix,
    "pythonpath": sys.path,
    "python_no_user_site": not site.ENABLE_USER_SITE,
    "distributions": distributions,
    "modules": modules,
}))
'@
            $probeArguments = @([string]$packageRoots.Count) + $packageRoots +
                @([string]$DistributionNames.Count) + $DistributionNames +
                $RequiredModuleNames
            $probeText = (& $Python -c $probe @probeArguments | Out-String).Trim()
            if ($LASTEXITCODE -ne 0) {
                throw 'Frozen Python third-party dependency probe failed.'
            }
            $environment = $probeText | ConvertFrom-Json
            if (-not [bool]$environment.python_no_user_site) {
                throw 'Frozen Python execution did not disable the user site.'
            }
            $pythonPrefix = [IO.Path]::GetFullPath(
                [string]$environment.python_prefix)
            foreach ($searchPath in @($environment.pythonpath)) {
                if ([string]::IsNullOrWhiteSpace([string]$searchPath)) {
                    continue
                }
                $resolvedSearchPath = [IO.Path]::GetFullPath([string]$searchPath)
                foreach ($forbiddenRoot in $ForbiddenRoots) {
                    $forbidden = [IO.Path]::GetFullPath($forbiddenRoot)
                    $underForbidden = $resolvedSearchPath.Equals(
                        $forbidden,[StringComparison]::OrdinalIgnoreCase) -or
                        $resolvedSearchPath.StartsWith(
                            $forbidden + [IO.Path]::DirectorySeparatorChar,
                            [StringComparison]::OrdinalIgnoreCase)
                    $underPythonPrefix = $resolvedSearchPath.Equals(
                        $pythonPrefix,[StringComparison]::OrdinalIgnoreCase) -or
                        $resolvedSearchPath.StartsWith(
                            $pythonPrefix + [IO.Path]::DirectorySeparatorChar,
                            [StringComparison]::OrdinalIgnoreCase)
                    if ($underForbidden -and -not $underPythonPrefix) {
                        throw "Python search path includes a forbidden live root: $resolvedSearchPath"
                    }
                }
            }
            $moduleOutput = ''
            if (-not $ProbeOnly) {
                $moduleOutput = (& $Python -m $Module @Arguments |
                    Out-String).Trim()
                if ($LASTEXITCODE -ne 0) {
                    $failure = [InvalidOperationException]::new(
                        "Frozen Python module failed with exit code $LASTEXITCODE.")
                    $failure.Data['exit_code'] = [int]$LASTEXITCODE
                    throw $failure
                }
            }
        } finally {
            Pop-Location
        }
    } finally {
        $env:PYTHONPATH = $savedPythonPath
        $env:PYTHONNOUSERSITE = $savedNoUserSite
        $env:PYTHONDONTWRITEBYTECODE = $savedNoBytecode
    }
    Assert-FrozenPythonPackage -Package $Package
    [pscustomobject]@{
        schema_version = 1
        module = $Module
        module_invoked = -not [bool]$ProbeOnly
        working_directory = $packageRoots[0]
        package_roots = $packageRoots
        python_path = $packageRoots -join [IO.Path]::PathSeparator
        python_no_user_site = $true
        python_no_bytecode = $true
        third_party = @($environment.distributions)
        frozen_modules = @($environment.modules)
        python_search_path = @($environment.pythonpath)
        python_executable = [string]$environment.python_executable
        python_prefix = [string]$environment.python_prefix
        module_stdout = $moduleOutput
    }
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
            'common/analysis',
            'projects/rf_multipole_ion_optics/analysis',
            'projects/rf_multipole_ion_optics/core',
            'projects/rf_multipole_ion_optics/runtime',
            'common/ion_release'
        )
    # Ask the frozen original PROFILES authority; do not maintain another profile map.
    $sourcePackage = New-FrozenPythonPackage -SourceRoot $SourceRoot `
        -CodeRoot $SnapshotRoot -RelativePaths $sourceFiles
    $selectionScript = @'
import json, pathlib, sys
root = pathlib.Path(sys.argv[1]).resolve()
sys.path.insert(0, str(root))
from projects.rf_multipole_ion_optics.analysis import resolve_contract
assert pathlib.Path(resolve_contract.__file__).resolve().is_relative_to(root)
profile = resolve_contract.PROFILES[sys.argv[2]]
print(json.dumps({key: path.relative_to(root).as_posix() for key, path in profile.items()}))
'@
    $selectionText = (& $Python -I -B -c $selectionScript $SnapshotRoot $Profile | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) {throw 'Frozen RF publication resource selection failed.'}
    $selection = $selectionText | ConvertFrom-Json
    $resources = @($selection.PSObject.Properties | ForEach-Object {[string]$_.Value}) + @(
        'projects/rf_multipole_ion_optics/config/contracts/family_contract.json'
    )
    # Existing schema_registry loads its complete shared metadata set.
    $resources += @(Get-ChildItem -LiteralPath (Join-Path $SourceRoot 'common/contracts/schemas') `
        -Filter '*.schema.json' -File | ForEach-Object {
            [IO.Path]::GetRelativePath($SourceRoot,$_.FullName).Replace('\','/')
        })
    $resourcePackage = New-FrozenPythonPackage -SourceRoot $SourceRoot `
        -CodeRoot $SnapshotRoot -RelativePaths @($resources | Sort-Object -Unique)
    $package = $sourcePackage
    $package.files = @($sourcePackage.files) + @($resourcePackage.files)
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

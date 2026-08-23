Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-FrozenPythonPackageExecutionPaths {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string[]]$RelativePaths)
    return @($RelativePaths | ForEach-Object {
        'inputs/code/' + ([string]$_ -replace '\\', '/')
    })
}

function New-FrozenPythonPackage {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$SourceRoot,
        [Parameter(Mandatory)][string]$CodeRoot,
        [Parameter(Mandatory)][string[]]$RelativePaths
    )
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
                    throw "Frozen Python module failed with exit code $LASTEXITCODE."
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

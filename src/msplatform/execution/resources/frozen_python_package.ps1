Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

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
        if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -cne [string]$entry.sha256) {
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
        [string]$StdoutPath = '',
        [string]$WorkingDirectory = '',
        [switch]$ProbeOnly
    )
    Assert-FrozenPythonPackage -Package $Package
    $selectedWorkingDirectory = [string]$Package.code_root
    if ($PSBoundParameters.ContainsKey('WorkingDirectory')) {
        if (-not [IO.Path]::IsPathFullyQualified($WorkingDirectory) -or
            -not (Test-Path -LiteralPath $WorkingDirectory -PathType Container)) {
            throw "Explicit frozen Python working directory must be absolute and existing: $WorkingDirectory"
        }
        $selectedWorkingDirectory = [IO.Path]::GetFullPath($WorkingDirectory)
    }
    $packageRoots = @($Package.package_roots | ForEach-Object {
        [IO.Path]::GetFullPath([string]$_)
    })
    if(@($Package.files | Where-Object {[string]$_.relative_path -like 'src/msplatform/*'}).Count){
        $RequiredModuleNames=@($RequiredModuleNames)+@('msplatform') | Select-Object -Unique
    }
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
        Push-Location -LiteralPath $selectedWorkingDirectory
        try {
            $isolate = @'
import pathlib, sys
root_count = int(sys.argv[1])
package_roots = [pathlib.Path(value).resolve() for value in sys.argv[2:2 + root_count]]
offset = 2 + root_count
forbidden_count = int(sys.argv[offset])
forbidden_roots = [pathlib.Path(value).resolve() for value in sys.argv[offset + 1:offset + 1 + forbidden_count]]
prefix = pathlib.Path(sys.prefix).resolve()
sys.path = [str(root) for root in package_roots] + [value for value in sys.path
    if value and (pathlib.Path(value).resolve().is_relative_to(prefix)
        or not any(pathlib.Path(value).resolve().is_relative_to(root) for root in forbidden_roots))]
sys.meta_path = [finder for finder in sys.meta_path
    if not getattr(finder, '__module__', '').startswith('__editable__')]
sys.argv = [sys.argv[0], *sys.argv[offset + 1 + forbidden_count:]]
'@
            $probe = $isolate + "`n" + @'
import importlib.metadata
import importlib.util
import json
import os
import pathlib
import site
import sys

distribution_count = int(sys.argv[1])
distribution_names = sys.argv[2:2 + distribution_count]
module_names = sys.argv[2 + distribution_count:]
distributions = []
modules = []
user_site = pathlib.Path(site.getusersitepackages()).resolve()
for name in distribution_names:
    distribution = importlib.metadata.distribution(name)
    root = pathlib.Path(distribution.locate_file("")).resolve()
    # The Pillow distribution provides the PIL import package.
    module_name = "PIL" if name.casefold() == "pillow" else name
    spec = importlib.util.find_spec(module_name)
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
    "working_directory": os.getcwd(),
    "python_executable": sys.executable,
    "python_prefix": sys.prefix,
    "pythonpath": sys.path,
    "python_no_user_site": not site.ENABLE_USER_SITE,
    "distributions": distributions,
    "modules": modules,
}))
'@
            $isolationArguments = @([string]$packageRoots.Count) + $packageRoots +
                @([string]$ForbiddenRoots.Count) + $ForbiddenRoots
            $probeArguments = $isolationArguments +
                @([string]$DistributionNames.Count) + $DistributionNames +
                $RequiredModuleNames
            $probeText = (& $Python -I -X utf8 -B -c $probe @probeArguments | Out-String).Trim()
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
            $execute = $isolate + "`n" + @'
import importlib.util, runpy
module = sys.argv[1]
spec = importlib.util.find_spec(module)
if spec is None or spec.origin is None or not any(
    pathlib.Path(spec.origin).resolve().is_relative_to(root) for root in package_roots
):
    raise RuntimeError('entry module escaped frozen roots: ' + module)
sys.argv = [module, *sys.argv[2:]]
failure = None
try:
    runpy.run_module(module, run_name='__main__', alter_sys=True)
except BaseException as error:
    failure = error
    raise
finally:
    for name, loaded in tuple(sys.modules.items()):
        if name.split('.')[0] in ('common', 'projects', 'msplatform') and getattr(loaded, '__file__', None):
            if not any(pathlib.Path(loaded.__file__).resolve().is_relative_to(root) for root in package_roots):
                detail = 'module escaped frozen roots: ' + name
                if failure is None:
                    raise RuntimeError(detail)
                failure.add_note(detail)
'@
            $invocationArguments = @('-I', '-X', 'utf8', '-B', '-c', $execute) +
                $isolationArguments + @($Module) + $Arguments
            if (-not $ProbeOnly) {
                if ($StdoutPath) {
                    & $Python @invocationArguments 1> $StdoutPath
                    $moduleExitCode = $LASTEXITCODE
                    if ($moduleExitCode -eq 0) {
                        $moduleOutput = [IO.File]::ReadAllText($StdoutPath).Trim()
                    }
                } else {
                    $moduleOutput = (& $Python @invocationArguments |
                        Out-String).Trim()
                    $moduleExitCode = $LASTEXITCODE
                }
                if ($moduleExitCode -ne 0) {
                    $failure = [InvalidOperationException]::new(
                        "Frozen Python module failed with exit code $moduleExitCode.")
                    $failure.Data['exit_code'] = [int]$moduleExitCode
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
    $executionResult = [pscustomobject]@{
        schema_version = 1
        module = $Module
        module_invoked = -not [bool]$ProbeOnly
        working_directory = [string]$environment.working_directory
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
    if ($ProbeOnly) {
        # Managed callers execute the same verified bootstrap through their own
        # process owner, rechecking the package before launch and after success.
        $executionResult | Add-Member -NotePropertyName invocation -NotePropertyValue ([pscustomobject]@{
            file_path = $Python
            arguments = [string[]]$invocationArguments
            working_directory = $selectedWorkingDirectory
        })
    }
    $executionResult
}

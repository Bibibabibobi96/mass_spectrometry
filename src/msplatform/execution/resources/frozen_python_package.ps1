Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

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
    $Request.inputs_module = Join-Path ([IO.Path]::GetFullPath([string]$Request.source_root)) 'src/msplatform/execution/inputs.py'
    if (-not (Test-Path -LiteralPath $Request.inputs_module -PathType Leaf)) {
        throw "Selected Python inputs implementation is missing: $($Request.inputs_module)"
    }
    $command = @'
import json, pathlib, sys, traceback
try:
    request = json.load(sys.stdin)
    selected = pathlib.Path(request['inputs_module']).resolve(strict=True)
    sys.meta_path = [finder for finder in sys.meta_path
        if not getattr(finder, '__module__', '').startswith('__editable__')]
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
    $savedConsoleOutputEncoding = [Console]::OutputEncoding
    try {
        [Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
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
        [Console]::OutputEncoding = $savedConsoleOutputEncoding
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

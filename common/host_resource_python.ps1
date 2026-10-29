# Internal JSON bridge for host_resource_python.py; no user-facing CLI flags.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = [Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$OutputEncoding = [Console]::OutputEncoding
$pythonLease = $null
$pythonExit = 1
$request = $null
try {
    if ($PSVersionTable.PSVersion.Major -lt 7) { throw 'PowerShell 7 is required.' }
    $request = [Console]::In.ReadToEnd() | ConvertFrom-Json -AsHashtable
    if ($request.schema_version -ne 1 -or $request.operation -notin @('enter','assert','call','managed_process')) {
        throw 'Unsupported Python host resource request.'
    }
    $python = [string]$request.python
    if (-not [IO.Path]::IsPathFullyQualified($python) -or -not (Test-Path -LiteralPath $python -PathType Leaf)) {
        throw 'An absolute Python 3.11 executable is required.'
    }
    $env:SIMULATION_PYTHON_EXE = $python
    . (Join-Path $PSScriptRoot 'host_execution_lease.ps1')
    if ($request.operation -eq 'managed_process') {
        . (Join-Path $PSScriptRoot 'resource_budget_support.ps1')
        $completion=Invoke-RepositoryManagedPythonProcess -Python $python -ArgumentList @($request.argv) `
            -WorkingDirectory $request.working_directory -StandardOutputPath $request.stdout_path `
            -StandardErrorPath $request.stderr_path -Environment $request.environment
        [Console]::Out.WriteLine('HOST_RESOURCE_PYTHON_RESULT=' + (@{completion=$completion;error=$null}|ConvertTo-Json -Depth 100 -Compress))
        $pythonExit=0
    } elseif ($request.operation -in @('enter','call')) {
        if ($env:MASS_SPECTROMETRY_PYTHON_HEAVY_REENTRY) { throw 'Duplicate Python heavy reentry.' }
        if ($request.module -notmatch '^[A-Za-z_]\w*(\.[A-Za-z_]\w*)*$' -or $request.module -eq '__main__') {
            throw 'An importable Python module name is required.'
        }
        if ($request.operation -eq 'enter' -and ($request.argv -isnot [array] -or @($request.argv | Where-Object { $_ -isnot [string] }).Count)) {
            throw 'Python arguments must be a JSON string array.'
        }
        if ($request.role -notin @('GATE','SIMION','COMSOL') -or $request.stage -notmatch '^[A-Za-z_]\w*$') {
            throw 'A known role and named stage are required.'
        }
        $pythonLease = Enter-HostResourceStage -Role $request.role -Stage $request.stage `
            -Budget (Get-HostResourceBudget -Role $request.role -Stage $request.stage)
        Assert-HostResourceHeavyStage -Lease $pythonLease
        $env:MASS_SPECTROMETRY_PYTHON_HEAVY_REENTRY = '1'
        # A synchronous foreground child retains ordinary output and exit
        # semantics; its CLI reentry verifies ownership before doing any work.
        if ($request.operation -eq 'call') {
            if ($request.function -notmatch '^[A-Za-z_]\w*$') { throw 'A simple function name is required.' }
            $request | ConvertTo-Json -Depth 100 -Compress | & $python -c 'from common.host_resource_python import _execute_call; _execute_call()'
        } else {
            $arguments = @('-m', [string]$request.module) + @($request.argv)
            & $python @arguments
        }
        $pythonExit = $LASTEXITCODE
    } else {
        Assert-HostResourceHeavyStage
        $value = @{heavy=$true}
        [Console]::Out.WriteLine('HOST_RESOURCE_PYTHON_RESULT=' + ($value | ConvertTo-Json -Depth 12 -Compress))
        $pythonExit = 0
    }
} catch {
    if($null-ne$request-and$request.operation-eq'managed_process'){
        $errorResult=@{completion=$_.Exception.Data['managed_python_completion'];
            error=@{type=$_.Exception.GetType().FullName;message=$_.Exception.Message}}
        [Console]::Out.WriteLine('HOST_RESOURCE_PYTHON_RESULT=' + ($errorResult|ConvertTo-Json -Depth 100 -Compress))
    }
    [Console]::Error.WriteLine('HOST_RESOURCE_PYTHON_ERROR=' + $_.Exception.Message)
    $pythonExit = 1
} finally {
    if ($null -ne $pythonLease) {
        $hostRelease = @{inherited=[bool]$pythonLease.inherited;token=[string]$pythonLease.token;result=$null;error=$null}
        try {
            $hostRelease.result = Exit-HostResourceStage -Lease $pythonLease -PassThru
            if (-not $pythonLease.inherited -and ($null -eq $hostRelease.result -or
                $hostRelease.result.status -ne 'released' -or $hostRelease.result.token -ne $pythonLease.token)) {
                if ($pythonExit -eq 0) { $pythonExit = 1 }
                [Console]::Error.WriteLine('HOST_RESOURCE_PYTHON_RELEASE_UNCONFIRMED')
            }
        }
        catch {
            $hostRelease.error = $_.Exception.Message
            [Console]::Error.WriteLine('HOST_RESOURCE_PYTHON_RELEASE_ERROR=' + $_.Exception.Message)
            if ($pythonExit -eq 0) { $pythonExit = 1 }
        }
        try {
            if ($request.operation -eq 'call') {
                @{result_path=$request.result_path;host_release=$hostRelease} | ConvertTo-Json -Depth 100 -Compress |
                    & $python -c 'from common.host_resource_python import _attach_host_release; _attach_host_release()'
                if ($LASTEXITCODE -ne 0) { throw 'Host release receipt publication failed.' }
            } else {
                [Console]::Out.WriteLine('HOST_RESOURCE_PYTHON_RELEASE=' + ($hostRelease | ConvertTo-Json -Depth 100 -Compress))
            }
        } catch {
            [Console]::Error.WriteLine('HOST_RESOURCE_PYTHON_RELEASE_RECEIPT_ERROR=' + $_.Exception.Message)
            if ($pythonExit -eq 0) { $pythonExit = 1 }
        }
    }
}
exit $pythonExit

# Internal JSON bridge for host_resource_python.py; no user-facing CLI flags.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = [Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$OutputEncoding = [Console]::OutputEncoding
$pythonLease = $null
$pythonExit = 1
try {
    if ($PSVersionTable.PSVersion.Major -lt 7) { throw 'PowerShell 7 is required.' }
    $request = [Console]::In.ReadToEnd() | ConvertFrom-Json -AsHashtable
    if ($request.schema_version -ne 1 -or $request.operation -notin @('enter','assert','call')) {
        throw 'Unsupported Python host resource request.'
    }
    $python = [string]$request.python
    if (-not [IO.Path]::IsPathFullyQualified($python) -or -not (Test-Path -LiteralPath $python -PathType Leaf)) {
        throw 'An absolute Python 3.11 executable is required.'
    }
    $env:SIMULATION_PYTHON_EXE = $python
    . (Join-Path $PSScriptRoot 'host_execution_lease.ps1')
    if ($request.operation -in @('enter','call')) {
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
    [Console]::Error.WriteLine('HOST_RESOURCE_PYTHON_ERROR=' + $_.Exception.Message)
    $pythonExit = 1
} finally {
    if ($null -ne $pythonLease) {
        try { Exit-HostResourceStage -Lease $pythonLease | Out-Null }
        catch {
            [Console]::Error.WriteLine('HOST_RESOURCE_PYTHON_RELEASE_ERROR=' + $_.Exception.Message)
            if ($pythonExit -eq 0) { $pythonExit = 1 }
        }
    }
}
exit $pythonExit

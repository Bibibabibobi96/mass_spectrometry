function Get-ComsolRuntimeWritePaths {
    param(
        [Parameter(Mandatory = $true)]
        [string]$UserProfile,

        [Parameter(Mandatory = $true)]
        [string]$TempPath
    )

    return @(
        (Join-Path $UserProfile '.comsol\v64\configuration\comsol'),
        (Join-Path $UserProfile '.comsol\v64\tomcat\logs'),
        $TempPath
    )
}

function Test-ComsolDirectoryWriteAccess {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $candidate = [IO.Path]::GetFullPath($Path)
    while (-not (Test-Path -LiteralPath $candidate -PathType Container)) {
        $parent = Split-Path -Parent $candidate
        if (-not $parent -or $parent -eq $candidate) { return $false }
        $candidate = $parent
    }
    $probe = Join-Path $candidate ('.mass_spectrometry_write_probe_' + [guid]::NewGuid().ToString('N') + '.tmp')
    try {
        $stream = [IO.File]::Open($probe, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
        $stream.Dispose()
        [IO.File]::Delete($probe)
        return $true
    }
    catch {
        if (Test-Path -LiteralPath $probe -PathType Leaf) {
            try { [IO.File]::Delete($probe) } catch { }
        }
        return $false
    }
}

function Assert-ComsolRuntimeWriteAccess {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Paths
    )

    $blocked = @($Paths | Where-Object { -not (Test-ComsolDirectoryWriteAccess -Path $_) })
    if ($blocked.Count -gt 0) {
        throw ('EXECUTION_ENVIRONMENT_BLOCKED: COMSOL/MATLAB cannot write required runtime paths: ' +
            ($blocked -join ', ') +
            '. Re-run the identical frozen task in a normal user execution context; this is not a model or solver failure.')
    }
}

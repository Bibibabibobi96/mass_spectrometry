param(
    [Parameter(Mandatory = $true)][string]$AssemblyPath,
    [Parameter(Mandatory = $true)][string]$PartsDirectory,
    [Parameter(Mandatory = $true)][string]$ReportPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$assembly = (Resolve-Path -LiteralPath $AssemblyPath).Path
$partsDir = (Resolve-Path -LiteralPath $PartsDirectory).Path
$report = [IO.Path]::GetFullPath($ReportPath)
$reportDir = Split-Path -Parent $report
if (-not (Test-Path -LiteralPath $reportDir -PathType Container)) {
    New-Item -ItemType Directory -Path $reportDir -Force | Out-Null
}

. (Join-Path $PSScriptRoot 'resolve_solidworks_2022.ps1')
$solidWorksPaths = Get-SolidWorks2022Paths
$interopPath = $solidWorksPaths.Interop
$constantsPath = $solidWorksPaths.Constants
if (-not (Test-Path -LiteralPath $interopPath -PathType Leaf)) {
    throw "SolidWorks 2022 Interop assembly was not found: $interopPath"
}
if (-not (Test-Path -LiteralPath $constantsPath -PathType Leaf)) {
    throw "SolidWorks 2022 constants assembly was not found: $constantsPath"
}
Add-Type -Path $interopPath
Add-Type -Path $constantsPath

$sw = $null
try {
    $sw = New-Object -TypeName 'SolidWorks.Interop.sldworks.SldWorksClass'
    [string[]]$dependencies = $sw.GetDocumentDependencies2(
        $assembly, $true, $true, $false)
    if (($dependencies.Count % 2) -ne 0) {
        throw "SolidWorks returned an odd dependency array of $($dependencies.Count) entries."
    }

    $changes = @()
    for ($index = 0; $index -lt $dependencies.Count; $index += 2) {
        $oldPath = [string]$dependencies[$index + 1]
        $newPath = Join-Path $partsDir (Split-Path -Leaf $oldPath)
        if (-not (Test-Path -LiteralPath $newPath -PathType Leaf)) {
            throw "Replacement part is missing: $newPath"
        }
        $changed = [bool]$sw.ReplaceReferencedDocument($assembly, $oldPath, $newPath)
        $changes += [PSCustomObject]@{
            name = [string]$dependencies[$index]
            old_path = $oldPath
            new_path = $newPath
            replaced = $changed
        }
    }

    [string[]]$after = $sw.GetDocumentDependencies2(
        $assembly, $true, $true, $false)
    $resolvedPaths = @()
    for ($index = 1; $index -lt $after.Count; $index += 2) {
        $resolvedPaths += [string]$after[$index]
    }
    $unresolved = @($resolvedPaths | Where-Object {
        -not (Test-Path -LiteralPath $_ -PathType Leaf)
    })
    $outsidePartsDirectory = @($resolvedPaths | Where-Object {
        (Split-Path -Parent $_) -ne $partsDir
    })
    $status = if ($changes.Count -gt 0 -and
        @($changes | Where-Object { -not $_.replaced }).Count -eq 0 -and
        $unresolved.Count -eq 0 -and $outsidePartsDirectory.Count -eq 0) {
        'PASS'
    } else {
        'FAIL'
    }
    $result = [ordered]@{
        schema_version = 1
        repaired_at = (Get-Date).ToString('yyyy-MM-ddTHH:mm:ssK')
        status = $status
        assembly_path = $assembly
        parts_directory = $partsDir
        dependency_count = $resolvedPaths.Count
        unresolved_count = $unresolved.Count
        outside_parts_directory_count = $outsidePartsDirectory.Count
        changes = $changes
    }
    $result | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $report -Encoding UTF8
    $result | ConvertTo-Json -Depth 5
    if ($status -ne 'PASS') {
        throw "Assembly reference repair did not satisfy the post-repair contract. See $report"
    }
}
finally {
    if ($null -ne $sw) {
        try { $sw.ExitApp() } catch {
            Write-Warning "Could not exit SolidWorks cleanly: $($_.Exception.Message)"
        }
        try { [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($sw) } catch {
            Write-Warning "Could not release the SolidWorks COM object: $($_.Exception.Message)"
        }
    }
}

param(
    [Parameter(Mandatory = $true)][string]$AssemblyPath,
    [Parameter(Mandatory = $true)][string]$ReportPath,
    [ValidateRange(1, 10000)][int]$ExpectedComponentCount = 25
)

$ErrorActionPreference = 'Stop'

$assembly = (Resolve-Path -LiteralPath $AssemblyPath).Path
$report = [IO.Path]::GetFullPath($ReportPath)
$reportDir = Split-Path -Parent $report
if (-not (Test-Path -LiteralPath $reportDir -PathType Container)) {
    New-Item -ItemType Directory -Path $reportDir -Force | Out-Null
}

$interopPath = 'D:\SW2022\SOLIDWORKS Corp2022\SOLIDWORKS\SolidWorks.Interop.sldworks.dll'
$constantsPath = 'D:\SW2022\SOLIDWORKS Corp2022\SOLIDWORKS\SolidWorks.Interop.swconst.dll'
if (-not (Test-Path -LiteralPath $interopPath -PathType Leaf)) {
    throw "SolidWorks 2022 Interop assembly was not found: $interopPath"
}
if (-not (Test-Path -LiteralPath $constantsPath -PathType Leaf)) {
    throw "SolidWorks 2022 constants assembly was not found: $constantsPath"
}
Add-Type -Path $interopPath
Add-Type -Path $constantsPath

$sw = $null
$document = $null
$phase = 'start-solidworks'
try {
    $sw = New-Object -TypeName 'SolidWorks.Interop.sldworks.SldWorksClass'
    $phase = 'enumerate-document-dependencies'
    [string[]]$dependencies = $sw.GetDocumentDependencies2(
        $assembly, $true, $true, $false)
    if (($dependencies.Count % 2) -ne 0) {
        throw "SolidWorks returned an odd dependency array of $($dependencies.Count) entries."
    }
    $componentRecords = @()
    for ($index = 0; $index -lt $dependencies.Count; $index += 2) {
        $path = [string]$dependencies[$index + 1]
        $componentRecords += [PSCustomObject]@{
            name = [string]$dependencies[$index]
            path = $path
            pathExists = (-not [string]::IsNullOrWhiteSpace($path)) -and
                (Test-Path -LiteralPath $path -PathType Leaf)
        }
    }

    $openErrors = 0
    $openWarnings = 0
    $phase = 'open-assembly'
    $document = $sw.OpenDoc6(
        $assembly,
        [int][SolidWorks.Interop.swconst.swDocumentTypes_e]::swDocASSEMBLY,
        [int][SolidWorks.Interop.swconst.swOpenDocOptions_e]::swOpenDocOptions_Silent,
        '',
        [ref]$openErrors,
        [ref]$openWarnings)
    if ($null -eq $document) {
        throw "SolidWorks OpenDoc6 failed (error=$openErrors; warning=$openWarnings)."
    }

    $missing = @($componentRecords | Where-Object { -not $_.pathExists })
    $status = if ($openErrors -eq 0 -and
        $componentRecords.Count -eq $ExpectedComponentCount -and
        $missing.Count -eq 0) { 'PASS' } else { 'FAIL' }
    $phase = 'write-report'
    $result = [ordered]@{
        schema_version = 1
        checked_at = (Get-Date).ToString('yyyy-MM-ddTHH:mm:ssK')
        status = $status
        assembly_path = $assembly
        solidworks_revision = [string]$sw.RevisionNumber()
        open_errors = $openErrors
        open_warnings = $openWarnings
        expected_component_count = $ExpectedComponentCount
        component_count = $componentRecords.Count
        missing_reference_count = $missing.Count
        components = $componentRecords
    }
    $result | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $report -Encoding UTF8
    $result | ConvertTo-Json -Depth 5

    if ($status -ne 'PASS') {
        throw ("Assembly reference gate failed: components={0}/{1}, missing={2}, " +
            "openErrors={3}. See {4}") -f $componentRecords.Count,
            $ExpectedComponentCount, $missing.Count, $openErrors, $report
    }
}
catch {
    throw "SolidWorks assembly reference check failed during '$phase' at line $($_.InvocationInfo.ScriptLineNumber): $($_.Exception.Message)"
}
finally {
    if ($null -ne $sw) {
        if ($null -ne $document) {
            try { $sw.CloseAllDocuments($true) } catch {
                Write-Warning "Could not close the checked assembly cleanly: $($_.Exception.Message)"
            }
        }
        try { $sw.ExitApp() } catch {
            Write-Warning "Could not exit SolidWorks cleanly: $($_.Exception.Message)"
        }
        try { [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($sw) } catch {
            Write-Warning "Could not release the SolidWorks COM object: $($_.Exception.Message)"
        }
    }
}

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-SolidWorks2022Paths {
    [CmdletBinding()]
    param([string]$InstallationRoot = $env:SOLIDWORKS_2022_ROOT)

    if ([string]::IsNullOrWhiteSpace($InstallationRoot)) {
        $registryKeys = @(
            'HKLM:\SOFTWARE\SolidWorks\SOLIDWORKS 2022\Setup',
            'HKLM:\SOFTWARE\WOW6432Node\SolidWorks\SOLIDWORKS 2022\Setup'
        )
        foreach ($registryKey in $registryKeys) {
            if (Test-Path -LiteralPath $registryKey) {
                $record = Get-ItemProperty -LiteralPath $registryKey
                if ($record.PSObject.Properties.Name -contains 'SolidWorks Folder') {
                    $InstallationRoot = $record.'SolidWorks Folder'
                    if (-not [string]::IsNullOrWhiteSpace($InstallationRoot)) { break }
                }
            }
        }
    }
    if ([string]::IsNullOrWhiteSpace($InstallationRoot)) {
        throw 'SolidWorks 2022 installation was not found; set SOLIDWORKS_2022_ROOT or repair its registry entry.'
    }

    $root = [IO.Path]::GetFullPath($InstallationRoot)
    $paths = [PSCustomObject]@{
        Root = $root
        Executable = Join-Path $root 'SLDWORKS.exe'
        Interop = Join-Path $root 'SolidWorks.Interop.sldworks.dll'
        Constants = Join-Path $root 'SolidWorks.Interop.swconst.dll'
    }
    foreach ($path in @($paths.Executable, $paths.Interop, $paths.Constants)) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "SolidWorks 2022 installation is incomplete: $path"
        }
    }
    return $paths
}

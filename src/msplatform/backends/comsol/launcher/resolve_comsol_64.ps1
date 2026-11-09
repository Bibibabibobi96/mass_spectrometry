Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-Comsol64Launcher {
    [CmdletBinding()]
    param([string]$ComsolRoot = $env:COMSOL_64_ROOT)

    $candidates = @()
    if (-not [string]::IsNullOrWhiteSpace($ComsolRoot)) {
        $candidates += Join-Path ([IO.Path]::GetFullPath($ComsolRoot)) 'bin\win64\comsolmphserver.exe'
    }
    $uninstallRoots = @(
        'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall',
        'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall'
    )
    foreach ($uninstallRoot in $uninstallRoots) {
        if (-not (Test-Path -LiteralPath $uninstallRoot)) { continue }
        Get-ChildItem -LiteralPath $uninstallRoot | ForEach-Object {
            $record = Get-ItemProperty -LiteralPath $_.PSPath -ErrorAction SilentlyContinue
            if ($null -ne $record -and
                $record.PSObject.Properties.Name -contains 'DisplayName' -and
                $record.DisplayName -like 'COMSOL Multiphysics 6.4*' -and
                $record.PSObject.Properties.Name -contains 'DisplayIcon') {
                $icon = [string]$record.DisplayIcon
                $icon = $icon.Trim('"')
                if (-not [string]::IsNullOrWhiteSpace($icon)) {
                    $candidates += Join-Path (Split-Path -Parent $icon) 'comsolmphserver.exe'
                }
            }
        }
    }
    $launcher = $candidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
    if ([string]::IsNullOrWhiteSpace($launcher)) {
        throw 'COMSOL 6.4 launcher was not found; set COMSOL_64_ROOT or repair its uninstall registry entry.'
    }
    return [IO.Path]::GetFullPath($launcher)
}

function Get-ComsolLauncherParameters {
    <# Project the existing host owner and deployment into explicit launcher argv. #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][hashtable]$HostContext,
          [Parameter(Mandatory)][string]$WorkingDirectory)
    $matlabRoot = Get-MatlabR2025bRoot
    return @{
        HostContextJson=($HostContext | ConvertTo-Json -Depth 8 -Compress)
        WorkingDirectory=[IO.Path]::GetFullPath($WorkingDirectory)
        ComsolLauncherPath=(Get-Comsol64Launcher)
        MatlabRootPath=$matlabRoot
    }
}

function Get-MatlabR2025bRoot {
    [CmdletBinding()]
    param()
    if ($env:MATLAB_R2025B_ROOT) {
        return [IO.Path]::GetFullPath($env:MATLAB_R2025B_ROOT)
    }
    return Join-Path $env:ProgramFiles 'MATLAB\R2025b\MatlabR2025b'
}

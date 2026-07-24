Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$powerShellEdition = $PSVersionTable.PSEdition
$powerShellVersion = $PSVersionTable.PSVersion
if ($powerShellEdition -ne 'Core' -or $powerShellVersion.Major -ne 7) {
    throw "This repository requires PowerShell Core 7; found $powerShellEdition $powerShellVersion."
}

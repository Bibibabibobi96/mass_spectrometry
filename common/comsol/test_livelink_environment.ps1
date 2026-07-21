$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'livelink_environment.ps1')

$paths = @(Get-ComsolRuntimeWritePaths -UserProfile 'C:\Users\example' -TempPath 'C:\Temp')
$expected = @(
    'C:\Users\example\.comsol\v64\configuration\comsol',
    'C:\Users\example\.comsol\v64\tomcat\logs',
    'C:\Temp'
)
if ($paths.Count -ne $expected.Count) {
    throw 'COMSOL runtime write-path count is incorrect.'
}
for ($index = 0; $index -lt $expected.Count; $index++) {
    if ($paths[$index] -ne $expected[$index]) {
        throw "COMSOL runtime write path differs at index $index."
    }
}
if (-not (Test-ComsolDirectoryWriteAccess -Path $PSScriptRoot)) {
    throw 'Writable-directory probe rejected the repository COMSOL directory.'
}
Write-Output 'LIVELINK_ENVIRONMENT_PREFLIGHT=PASS'

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'livelink_failure_classification.ps1')

$startupDisconnect = @'
STATUS=FAIL
ERROR=Error using mphload
com.comsol.util.exceptions.FlException: Not connected to a server.
Error in mphopen
'@
$taskNullPointer = @'
STATUS=FAIL
ERROR=Error using configure_oatof_segmented_output
java.lang.NullPointerException at com.comsol.clientapi.engine.APIEngine.runMethod
'@
$computeDisconnect = @'
STATUS=FAIL
ERROR=Study Compute failed because the server disconnected
Not connected to a server
'@

if (-not (Test-ComsolRetryableStartupReport $startupDisconnect)) {
    throw 'The known mphload/mphopen startup disconnect was not classified as retryable.'
}
if (Test-ComsolRetryableStartupReport $taskNullPointer) {
    throw 'A task API null pointer must not be classified as retryable startup failure.'
}
if (Test-ComsolRetryableStartupReport $computeDisconnect) {
    throw 'A Study Compute disconnect must not be classified as retryable startup failure.'
}
$attemptIds = @(Get-ComsolAttemptServerIds -Before @(10,20) -After @(10,20,30,30,40))
if ($attemptIds.Count -ne 2 -or $attemptIds[0] -ne 30 -or $attemptIds[1] -ne 40) {
    throw 'Attempt-local COMSOL server PID classification is incorrect.'
}
Write-Output 'LIVELINK_FAILURE_CLASSIFICATION=PASS'

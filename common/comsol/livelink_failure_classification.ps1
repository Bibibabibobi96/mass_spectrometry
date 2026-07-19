function Test-ComsolRetryableStartupReport {
    param([Parameter(Mandatory = $true)][string]$ReportText)

    # This is deliberately narrow.  A disconnected server reported by the
    # first model-open call is a startup transport failure.  Null pointers in
    # solver/configuration APIs and any Study Compute failure are task errors
    # and must remain visible to the caller.
    return ($ReportText -match '(?i)Not connected to a server') -and
        ($ReportText -match '(?i)\bmphload\b') -and
        ($ReportText -match '(?i)\bmphopen\b')
}

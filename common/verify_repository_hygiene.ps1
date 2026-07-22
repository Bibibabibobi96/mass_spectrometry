[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$errors = [Collections.Generic.List[string]]::new()

$rootDebrisPatterns = @('hs_err_pid*.log','java_error_in_*.log','matlab_crash_dump.*','core.*','*.dmp')
foreach ($pattern in $rootDebrisPatterns) {
  foreach ($file in @(Get-ChildItem -LiteralPath $repoRoot -File -Filter $pattern -ErrorAction SilentlyContinue)) {
    $errors.Add("repository-root tool artifact must be archived outside Git: $($file.Name)")
  }
}

$tracked = @(& git -C $repoRoot ls-files)
if ($LASTEXITCODE -ne 0) { throw 'git ls-files failed.' }
foreach ($path in $tracked) {
  $normalized = $path.Replace('\','/')
  if ($normalized -match '(^|/)artifacts/' -or
      $normalized -match '(?i)\.(mph|iob|pa(?:\d+|#)?|sldprt|sldasm|step|stp|dmp|log)$') {
    $errors.Add("generated/binary artifact is tracked by Git: $path")
  }
}

if ($errors.Count -gt 0) {
  $errors | ForEach-Object { Write-Error $_ }
  throw "Repository hygiene gate failed with $($errors.Count) error(s)."
}
Write-Output "REPOSITORY_HYGIENE=PASS TRACKED_FILES=$($tracked.Count)"

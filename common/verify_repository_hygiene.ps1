[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$workspaceRoot = Split-Path -Parent $repoRoot
$errors = [Collections.Generic.List[string]]::new()

$allowedWorkspaceEntries = @(
  '.agents','.claude','.codex','.comsol_runtime','.comsol_server_config','.git','.idea',
  '.matlab_pref','.matlab_pref25','.mcp.json','.tools','AGENTS.md','CLAUDE.md',
  'README.md','artifacts','integrations','simulation_repo','scratch'
)
$workspaceManaged =
  (Split-Path -Leaf $repoRoot) -eq 'simulation_repo' -or
  (Test-Path -LiteralPath (Join-Path $workspaceRoot 'AGENTS.md') -PathType Leaf)
if ($workspaceManaged) {
  foreach ($entry in Get-ChildItem -Force -LiteralPath $workspaceRoot) {
    if ($entry.Name -notin $allowedWorkspaceEntries) {
      $errors.Add("workspace root contains unregistered entry: $($entry.Name)")
    }
  }
  foreach ($required in @('AGENTS.md','README.md','simulation_repo','artifacts')) {
    if (-not (Test-Path -LiteralPath (Join-Path $workspaceRoot $required))) {
      $errors.Add("workspace root is missing required entry: $required")
    }
  }
  $artifactsRoot = Join-Path $workspaceRoot 'artifacts'
  if (Test-Path -LiteralPath $artifactsRoot -PathType Container) {
    foreach ($entry in Get-ChildItem -Force -LiteralPath $artifactsRoot) {
      if ($entry.Name -ne 'projects' -or -not $entry.PSIsContainer) {
        $errors.Add("artifacts root contains unregistered entry: $($entry.Name)")
      }
    }
  }
  $toolsRoot = Join-Path $workspaceRoot '.tools'
  if ((Test-Path -LiteralPath $toolsRoot) -and
      -not (Test-Path -LiteralPath $toolsRoot -PathType Container)) {
    $errors.Add('workspace tool cache must be a directory: .tools')
  } elseif (Test-Path -LiteralPath $toolsRoot -PathType Container) {
    $allowedToolEntries = @('cloc','cloc\2.10','cloc\2.10\cloc.exe')
    foreach ($entry in Get-ChildItem -Force -Recurse -LiteralPath $toolsRoot) {
      $relative = [IO.Path]::GetRelativePath($toolsRoot, $entry.FullName)
      if ($relative -notin $allowedToolEntries) {
        $errors.Add("workspace tool cache contains unregistered entry: $relative")
      }
    }
  }
} else {
  Write-Output 'WORKSPACE_HYGIENE=SKIP REASON=standalone_repository_checkout'
}

foreach ($directoryName in @('.tmp', 'scratch')) {
  $directory = Join-Path $repoRoot $directoryName
  if (Test-Path -LiteralPath $directory) {
    $errors.Add("repository root must not contain temporary directory: $directoryName")
  }
}

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

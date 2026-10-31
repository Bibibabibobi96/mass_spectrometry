"""Thin actual runner AST transport to public root/FrozenContext API; no ledger/native."""

from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest
from common.contracts import machine_contracts

PROJECT = Path(__file__).resolve().parents[2]
REPO = Path(machine_contracts.__file__).resolve().parents[2]


def quote(value):
    return "'" + str(value).replace("'", "''") + "'"


class ComsolWorkspaceContextTests(unittest.TestCase):
    def test_actual_entry_context_is_frozen_and_missing_root_does_not_fallback(self):
        for missing in (False, True):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                script = root / "boundary.ps1"
                body = r"""
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$repoRoot=@@REPO@@;$python=@@PYTHON@@;$runner=@@RUNNER@@;$testRoot=@@ROOT@@;$ProjectId='rf_multipole_ion_optics'
. (Join-Path $repoRoot 'common/paths/workspace_paths.ps1')
$env:MASS_SPECTROMETRY_ARTIFACT_ROOT=Join-Path $testRoot 'managed_data'
$env:MASS_SPECTROMETRY_EXECUTION_ROOT=Join-Path $testRoot 'execution'
$env:MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH=Join-Path $testRoot 'shared.sqlite3'
$tokens=$null;$errors=$null;$ast=[System.Management.Automation.Language.Parser]::ParseFile($runner,[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'runner parse failed'}
foreach($name in @('workspacePaths','projectArtifactRoot')){
 $node=@($ast.FindAll({param($n)$n-is[System.Management.Automation.Language.AssignmentStatementAst]-and$n.Left-is[System.Management.Automation.Language.VariableExpressionAst]-and$n.Left.VariablePath.UserPath-eq$name},$true))[0]
 Invoke-Expression $node.Extent.Text
}
$expectedRoot=$env:MASS_SPECTROMETRY_ARTIFACT_ROOT;$expectedHost=$env:MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH
$env:MASS_SPECTROMETRY_ARTIFACT_ROOT=Join-Path $testRoot 'unwanted_fallback'
$env:MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH=Join-Path $testRoot 'unwanted.sqlite3'
$script:ledgerTouched=$false
function New-RunPackage {
 param($Python,$RepoRoot,$ArtifactRoot,$RunId,$Project,$Mode,[switch]$RetentionContractEnabled,[switch]$CapacityLedgerLifecycleEnabled,$RetentionClass,$RetentionReason,$Software,[switch]$UseShortExecutionPath,$ExpectedExecutionRelativePaths,$PathContext)
 # The public owner validates FrozenContext before any capacity/ledger operation.
 $actual=Resolve-WorkspacePaths -SourceRoot $RepoRoot -Python $Python -FrozenContext $PathContext
 if($actual.artifact_root-ne$expectedRoot-or$actual.host_resource_state_path-ne$expectedHost){throw 'Root drifted from frozen context'}
 if($ArtifactRoot-ne(Join-Path $expectedRoot ('projects/'+$Project))){throw 'Wrong project artifact root'}
 $script:ledgerTouched=$true
 return [pscustomobject]@{artifact_run_dir=(Join-Path $ArtifactRoot ('runs/'+$RunId))}
}
$RunId='20261030_000000__test__repo__root-context';$RetentionClass='compact';$RetentionReason='fixture';$executionCapacityPaths=@()
if(@@MISSING@@){$broken=$workspacePaths|ConvertTo-Json|ConvertFrom-Json -AsHashtable;$broken.Remove('artifact_root');$workspacePaths=$broken}
$bootstrap=@($ast.EndBlock.Statements|Where-Object{$_-is[Management.Automation.Language.TryStatementAst]-and@($_.Body.FindAll({param($node)$node-is[Management.Automation.Language.CommandAst]-and$node.GetCommandName()-eq'Enter-ArtifactWorkflowCapacitySession'},$true)).Count})
if($bootstrap.Count-ne1){throw 'Actual normal owner bootstrap is ambiguous'}
$commands=@($bootstrap[0].Body.FindAll({param($n)$n-is[System.Management.Automation.Language.CommandAst]-and$n.GetCommandName()-eq'New-RunPackage'},$true))
if($commands.Count-ne1){throw 'Actual normal package boundary is ambiguous'}
$command=$commands[0]
try { $package=& ([scriptblock]::Create($command.Extent.Text));if(@@MISSING@@){throw 'Incomplete context unexpectedly accepted'} }
catch {if(@@MISSING@@-and-not$script:ledgerTouched-and$_.Exception.Message.Contains('frozen workspace context requires exactly four root fields')){Write-Output 'EXPECTED_INCOMPLETE_FROZEN_CONTEXT';exit 0};throw}
if(-not$script:ledgerTouched){throw 'Valid boundary not reached'}
if(Test-Path -LiteralPath (Join-Path $testRoot 'unwanted_fallback')){throw 'Fallback artifact root accessed'}
Write-Output 'ACTUAL_ROOT_BOUNDARY_PASS'
"""
                for key, value in dict(
                    REPO=quote(REPO),
                    PYTHON=quote(sys.executable),
                    RUNNER=quote(PROJECT / "runtime/run_finite_3d_transport.ps1"),
                    ROOT=quote(root),
                    MISSING="$true" if missing else "$false",
                ).items():
                    body = body.replace("@@" + key + "@@", value)
                script.write_text(body, encoding="utf-8", newline="\n")
                execution = subprocess.run(
                    ["pwsh", "-NoProfile", "-File", str(script)],
                    cwd=root,
                    env=os.environ.copy(),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=30,
                )
                self.assertEqual(
                    execution.returncode, 0, execution.stdout + execution.stderr
                )
                self.assertIn(
                    "EXPECTED_INCOMPLETE_FROZEN_CONTEXT"
                    if missing
                    else "ACTUAL_ROOT_BOUNDARY_PASS",
                    execution.stdout,
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)

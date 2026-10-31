"""Exercise production evidence projection beyond Windows command-line capacity."""
from pathlib import Path
import json
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(shutil.which('pwsh'), 'PowerShell required')
class NativeEvidenceTests(unittest.TestCase):
    def test_large_records_use_file_transport_and_projection_failure_propagates(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            log = root/'native.log'
            log.write_text('actual fixture log\n')
            records = [dict(index=i, padding='x'*4096,
                stdout_path=str(log), stderr_path=str(log), usage_path=str(log)) for i in range(14)]
            encoded = json.dumps(records)
            self.assertGreater(len(encoded), 32767)
            source = root/'records.json'
            source.write_text(encoded)
            script = root/'project.ps1'
            script.write_text(r'''param($Repo,$Python,$Source,$Output,[switch]$FailProjection)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $Repo 'integrations/workflows/single_reflection_flight/execute.ps1'),[ref]$null,[ref]$null)
$assignment=$ast.Find({param($n)$n-is[Management.Automation.Language.AssignmentStatementAst]-and$n.Left.Extent.Text-eq'$evidenceCode'},$true)
$function=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq'Write-NativeExecutionEvidence'},$true)
Invoke-Expression $assignment.Extent.Text
Invoke-Expression $function.Extent.Text
function Write-RunJson {param($Path,$Value,$Depth) [IO.File]::WriteAllText($Path,(ConvertTo-Json -InputObject $Value -Depth $Depth))}
function Invoke-RunToolRootContext {param($RepoRoot,$Operation) Push-Location $RepoRoot;try{& $Operation}finally{Pop-Location}}
$frozen=@{execution_root=$Repo}
if($FailProjection){$evidenceCode='raise RuntimeError("inert projection failure")'}
$records=Get-Content -LiteralPath $Source -Raw|ConvertFrom-Json -AsHashtable
Write-NativeExecutionEvidence -Records $records -Path $Output
''')
            output = root/'evidence.json'
            command = ['pwsh','-NoProfile','-File',str(script),str(ROOT),sys.executable,str(source),str(output)]
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            projected = json.loads(output.read_text())
            self.assertEqual(len(projected), 14)
            self.assertEqual(projected[-1]['padding'], records[-1]['padding'])
            for row in projected:
                for kind in ('stdout','stderr','usage'):
                    self.assertNotIn(kind+'_path', row)
                    self.assertEqual(row[kind+'_record']['path'], str(log))
                    self.assertEqual(row[kind+'_record']['bytes'], log.stat().st_size)
                    self.assertEqual(len(row[kind+'_record']['sha256']), 64)
            self.assertFalse(Path(str(output)+'.input.json').exists())
            failed = root/'failed.json'
            result = subprocess.run(command[:-1]+[str(failed),'-FailProjection'],
                                    cwd=ROOT,capture_output=True,text=True,timeout=60)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Native evidence projection failed.', result.stderr)
            self.assertFalse(failed.exists())
            self.assertEqual(json.loads(Path(str(failed)+'.input.json').read_text()), records)

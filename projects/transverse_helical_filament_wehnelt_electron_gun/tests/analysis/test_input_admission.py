"""Real frozen-triplet resolver wiring and accurate software/science status."""
from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[2]
REPO = PROJECT.parents[1]


class BuildInputAdmissionTests(unittest.TestCase):
    def test_frozen_triplet_rejection_and_summary_without_full_static(self):
        source_path = PROJECT / "run_build_only_smoke.ps1"
        source = source_path.read_text(encoding="utf-8")
        start = source.index("  $failureStage = 'input_freshness'")
        end = source.index("  $failureStage = 'frozen_input_validation'", start)
        block = source[start:end]
        for stale in (False, True):
            with self.subTest(stale=stale), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                files = {"baseline": "baseline.json", "numerical_modes": "numerical_modes.json",
                         "resolved_contract": "resolved_model.json"}
                for filename in files.values():
                    (root / filename).write_bytes((PROJECT / "config" / filename).read_bytes())
                if stale:
                    resolved_path = root / files["resolved_contract"]
                    resolved = json.loads(resolved_path.read_text(encoding="utf-8"))
                    resolved["role"] = "stale_resolved_contract"
                    resolved_path.write_text(json.dumps(resolved), encoding="utf-8")
                fixture = root / "admit.ps1"
                fixture.write_text(r'''param($Repo,$Python,$Root,$Source,$ExpectFailure)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$snapshotRoot=$Repo;$package=@{python=$Python}
$frozenInputs=@{baseline=(Join-Path $Root 'baseline.json');numerical_modes=(Join-Path $Root 'numerical_modes.json');resolved_contract=(Join-Path $Root 'resolved_model.json')}
$downstream=0;$caught=$null
try{
''' + block + r'''
 $downstream++
}catch{$caught=$_.Exception.Message}
if($ExpectFailure-eq'true'){
 if($caught-cne'Frozen Wehnelt baseline, numerical mode, and resolved contract differ.'-or$downstream-ne0){throw 'Stale triplet did not block build'}
}elseif($caught-or$downstream-ne1){throw ('Valid triplet rejected: '+$caught)}
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$null,[ref]$null)
$node=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq'New-BuildSummary'},$true)
Invoke-Expression $node.Extent.Text
$summary=New-BuildSummary -Status interrupted -Reason fixture -FailureStage $(if($ExpectFailure-eq'true'){'input_freshness'}else{'frozen_input_validation'})
if($summary.input_freshness_passed-ne($ExpectFailure-ne'true')-or$summary.Contains('static_gate_passed')-or$summary.formal_gate_passed){throw 'Input admission was misreported as software/scientific qualification'}
'BUILD_INPUT_ADMISSION=PASS'
''', encoding="utf-8")
                result = subprocess.run(["pwsh", "-NoProfile", "-File", str(fixture), str(REPO),
                                         sys.executable, str(root), str(source_path), str(stale).lower()],
                                        cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("BUILD_INPUT_ADMISSION=PASS", result.stdout)

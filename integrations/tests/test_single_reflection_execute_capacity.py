"""Public preparation freezes the actual executable closure in a managed run."""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[2]
EXECUTE = REPO / 'integrations/workflows/single_reflection_flight/execute.ps1'


from integrations.tests.test_support.single_reflection_execute_fixture import SingleReflectionExecuteFixture

@unittest.skipUnless(shutil.which('pwsh'), 'PowerShell 7 is required')
class SingleReflectionExecuteTests(SingleReflectionExecuteFixture):
    def test_priority_point_marker_is_required_before_public_validation(self):
        self._check_public_cases(('workbench_priority_marker',))


    def test_native_stage_uses_one_session_for_standalone_or_borrowed_owner(self):
        # Standalone success/native/planning failure are already exercised by
        # the field-stage test. Borrowing changes capacity ownership, not the
        # pre-admission planning matrix: retain its success and native failure.
        self._check_public_cases(('none', 'native'), borrowed_capacity=True)


    def test_refinement_fly_uses_six_fields_and_rejects_insufficient_flight_budget(self):
        self._check_public_cases(('fly_refinement','refinement_flight_ram_floor'))


    def test_priority_point_evidence_validator_matrix(self):
        """Execute the real validator without repeating geometry/Fly setup."""
        code = r'''param($Owner)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$ast=[Management.Automation.Language.Parser]::ParseFile($Owner,[ref]$null,[ref]$null)
$definition=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq'Get-InstrumentNativePriorityOccupancyEvidence'},$true)
. ([scriptblock]::Create($definition.Extent.Text))
$counts=@{checked_points=2;observation_only_points=1}
$valid='SINGLE_REFLECTION_NATIVE_PRIORITY_OCCUPANCY=PASS CHECKED=2 OBSERVED=1 SCOPE=declared_points_only'
foreach($ending in @('',"`r")){
 $proof=Get-InstrumentNativePriorityOccupancyEvidence -OutputText ($valid+$ending) -ExpectedCounts $counts
 if($proof.status-ne'success'-or$proof.checked_points-ne2-or$proof.observation_only_points-ne1){throw 'valid proof changed'}
}
foreach($invalid in @('',($valid+"`n"+$valid),'SINGLE_REFLECTION_NATIVE_PRIORITY_OCCUPANCY=PASS CHECKED=2',
 $valid.Replace('CHECKED=2','CHECKED=1'),$valid.Replace('OBSERVED=1','OBSERVED=2'),$valid.Replace('CHECKED=2','CHECKED=0'))){
 $rejected=$false
 try{$null=Get-InstrumentNativePriorityOccupancyEvidence -OutputText $invalid -ExpectedCounts $counts}
 catch{if($_.Exception.Message-notlike'*point evidence missing*'){throw};$rejected=$true}
 if(-not$rejected){throw 'invalid point evidence accepted'}
}
'PRIORITY_EVIDENCE_MATRIX=PASS'
'''
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / 'priority.ps1'
            script.write_text(code, encoding='utf-8')
            result = subprocess.run(['pwsh', '-NoProfile', '-File', str(script), str(EXECUTE)],
                cwd=REPO, capture_output=True, text=True, encoding='utf-8', timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('PRIORITY_EVIDENCE_MATRIX=PASS', result.stdout)

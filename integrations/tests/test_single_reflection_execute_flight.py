"""Public preparation freezes the actual executable closure in a managed run."""
from __future__ import annotations

from pathlib import Path
import shutil
import unittest


REPO = Path(__file__).resolve().parents[2]
EXECUTE = REPO / 'integrations/workflows/single_reflection_flight/execute.ps1'


from integrations.tests.test_support.single_reflection_execute_fixture import SingleReflectionExecuteFixture

@unittest.skipUnless(shutil.which('pwsh'), 'PowerShell 7 is required')
class SingleReflectionExecuteTests(SingleReflectionExecuteFixture):
    def test_full_mother_fly_and_default_replay_public_stage(self):
        self._check_public_cases(('fly','missing_fly_budget','missing_replay_budget','flight_ram_floor',
            'flight_native','replay_native','flight_controls','flight_native_controls','flight_marker','flight_mismatch'))


    def test_batch_priority_point_evidence_is_bound_before_any_fly(self):
        self._check_public_cases(('fly', 'flight_priority_marker'))

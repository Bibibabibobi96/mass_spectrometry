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
            'flight_native','replay_native','flight_controls','flight_native_controls','flight_marker','flight_mismatch'), lightweight_seeds=True)


    def test_batch_priority_point_evidence_is_bound_before_any_fly(self):
        # The full-mother test below already covers the successful Fly path.
        self._check_public_cases(('flight_priority_marker',))


    def test_normal_fly_omits_replay_and_its_budget(self):
        # Explicit True is exercised by the full-mother test above. Keep the
        # omitted action and omitted replay budget through the same real freezer.
        self._check_public_cases(('fly',), lightweight_seeds=True, verify_replay=None, omit_replay_budget=True)

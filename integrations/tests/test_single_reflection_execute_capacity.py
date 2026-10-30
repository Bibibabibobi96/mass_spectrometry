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
    def test_priority_point_marker_is_required_before_public_validation(self):
        self._check_public_cases(('workbench', 'workbench_priority_marker', 'workbench_priority_duplicate', 'workbench_priority_truncated', 'workbench_priority_count'))


    def test_native_stage_uses_one_session_for_standalone_or_borrowed_owner(self):
        for borrowed in (False, True):
            with self.subTest(borrowed=borrowed):
                self._check_public_cases(('none', 'native', 'planning'), borrowed_capacity=borrowed)


    def test_refinement_fly_uses_six_fields_and_rejects_insufficient_flight_budget(self):
        self._check_public_cases(('fly_refinement','refinement_flight_ram_floor'))

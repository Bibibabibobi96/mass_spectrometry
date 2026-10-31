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
    def test_field_design_public_stage_consumes_frozen_plan_and_releases_failure(self):
        """Real public freezer/preparation/budget with explicit inert native boundary."""
        # Generic missing-stage/invalid-budget rejection belongs to
        # test_engineering_budget.test_shared_budget_and_actual_entry_loaders;
        # retain the real workbench success/failure wiring and cohort check here.
        self._check_public_cases(('none','native','population','downstream','elapsed','planning','disk_floor','ram_floor',
            'workbench','missing_flight','workbench_build','workbench_verify','workbench_drift','field_drift','publication_pin'))

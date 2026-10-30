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
    def test_discovery_complete_full_and_local_mothers_then_default_replay(self):
        self._check_public_cases(('discovery_fly','local_discovery_fly'))


    def test_renamed_full_and_local_keep_the_same_oa_source_and_clock(self):
        self._check_public_cases(('discovery_fly','local_discovery_fly'), rename_instances=True)


    def test_discovery_missing_candidates_retains_negative_without_timed_successor(self):
        self._check_public_cases(('discovery_missing',))


    def test_discovery_budget_is_required_before_any_native_boundary(self):
        self._check_public_cases(('missing_discovery_budget',))


    def test_explicit_downstream_source_full_mother_and_default_replay(self):
        self._check_public_cases(('downstream_source_fly',))

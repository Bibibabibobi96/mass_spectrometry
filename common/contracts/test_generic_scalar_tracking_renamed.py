"""Reverse-lexical registered providers through the public sampled tracking owner."""
import unittest
from unittest.mock import patch
from common.contracts import test_generic_scalar_tracking_managed as managed
from common.contracts.test_support import generic_scalar_renamed as renamed

class RenamedSampledTrackingTests(unittest.TestCase):
    def test_renamed_reordered_tracking(self):
        case = managed.GenericScalarTrackingManagedTests(methodName="runTest")
        self.addCleanup(case.doCleanups)
        with patch.object(managed.fixture, "GenericScalarTests", renamed.GenericScalarTests):
            case.test_public_sampled_tracking()

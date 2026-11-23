"""Real owner field witness with reverse-lexical registered Assembly identities."""
import unittest
from unittest.mock import patch
from tests.contracts import test_generic_scalar_managed as managed
from tests.contracts.test_support import generic_scalar_renamed as renamed

class RenamedNeutralManagedTests(unittest.TestCase):
    def test_renamed_reordered_public_field(self):
        case=managed.GenericScalarManagedTests(methodName="runTest")
        self.addCleanup(case.doCleanups)
        with patch.object(managed.fixture,"GenericScalarTests",renamed.GenericScalarTests):
            case.test_public_model_then_public_scalar_admission()

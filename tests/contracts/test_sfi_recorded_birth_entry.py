"""The retired SFI producer package has no executable alias."""
import importlib.util
import unittest


class RetiredRecordedBirthEntryTests(unittest.TestCase):
    def test_old_producer_package_is_not_importable(self):
        self.assertIsNone(importlib.util.find_spec("msplatform.workflows.single_reflection_flight"))

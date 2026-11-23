"""Frozen-numerics marker tests; inert process fixture only."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from tests.contracts.test_support.generic_scalar_owner_harness import inert_dynamics_code

class InertGroupingTests(unittest.TestCase):
    def test_frozen_zero_one_and_default(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'tracking_numerics.json'
            for value,expected in ((0,0),(1,1),(None,1)):
                path.write_text(json.dumps({} if value is None else {'grouped':value}),encoding='utf8')
                output=io.StringIO()
                with contextlib.redirect_stdout(output):
                    exec('from pathlib import Path\nimport json\n'+inert_dynamics_code(path),{})
                self.assertEqual(json.loads(output.getvalue().split(': ',1)[1])['grouped'],expected)
    def test_invalid_frozen_value_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'tracking_numerics.json';path.write_text('{"grouped": true}',encoding='utf8')
            with self.assertRaises(AssertionError):
                exec('from pathlib import Path\nimport json\n'+inert_dynamics_code(path),{})

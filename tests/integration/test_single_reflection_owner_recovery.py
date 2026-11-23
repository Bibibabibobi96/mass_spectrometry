"""Current SFI entry rejects retired modes before reading paths or starting owners."""
from contextlib import redirect_stderr
from io import StringIO
import sys
import unittest
from unittest.mock import patch

from msplatform.workflows.single_reflection_flight import recorded_birth

class SingleReflectionOwnerRecoveryTests(unittest.TestCase):
    def test_source_modes_reject_before_environment_or_owner(self):
        common = ['--fields-reference', 'missing-fields.json', '--observations', 'missing-observations.json',
                  '--environment', 'missing-env.json', '--workspace', 'missing-workspace', '--profile', 'missing']
        cases = [
            ['--release-request', 'release.json', '--preparation-manifest', 'manifest.json'],
            ['--release-request', 'release.json'],
            ['--preparation-manifest', 'manifest.json', '--propagation', 'propagation.json'],
        ]
        for values in cases:
            with self.subTest(values=values), patch.object(sys, 'argv', ['entry', *common, *values]), \
                 patch('msplatform.execution.load_environment') as load, \
                 patch.object(recorded_birth.simion, 'track') as track, redirect_stderr(StringIO()):
                with self.assertRaises(SystemExit) as caught:
                    recorded_birth.main()
                self.assertEqual(caught.exception.code, 2)
                load.assert_not_called();track.assert_not_called()

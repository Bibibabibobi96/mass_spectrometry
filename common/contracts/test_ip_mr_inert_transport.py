"""Check inert field-fixture output paths across the supported Lua transports."""
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from common.contracts.test_support import ip_mr_sampled_field_fixture as fixture
from msplatform.backends.simion.native_io import apply_native_io_mode
from msplatform.execution.run_session import RunSession


OPERATIONS = (
    'collision_build_01', 'collision_verify_01', 'background_build',
    'background_verify', 'collision_iob_build', 'collision_iob_verify',
)


class TransportTests(unittest.TestCase):
    def test_protocol_forms_and_io_modes_preserve_output_paths(self):
        cases = 0
        for operation in OPERATIONS:
            collision = operation in ('collision_build_01', 'collision_verify_01')
            for io, state in ((io, state) for io in (None, False)
                              for state in ((False, True) if collision else (False,))):
                with self.subTest(io=io, state=state, operation=operation), tempfile.TemporaryDirectory() as root:
                    root = Path(root)
                    output = str(root / 'result.pa')
                    guard = str(root / 'native_run_path.lua')
                    wrapper = str(root / 'script.lua')
                    if collision:
                        verb = 'build' if operation.endswith('build_01') else 'verify'
                        args = ['lua', wrapper, verb, str(root / 'source.pa#'), output, guard]
                        if state:
                            args.append(str(root / 'state.json'))
                    elif operation.startswith('background_'):
                        args = ['lua', wrapper, output, '9', '9', '9', '0.5', '1', '2', guard]
                    else:
                        verb = 'build_geometry' if operation.endswith('build') else 'verify_geometry'
                        args = ['lua', wrapper, str(root / 'spec.lua'), verb, guard]
                    argv = apply_native_io_mode(
                        ['simion.exe', '--nogui', '--noprompt', *args],
                        allow_asynchronous_io=io)[1:]
                    seen = []

                    def original(session, operation_id, **kwargs):
                        seen.append(kwargs)
                        return 'receipt'

                    with patch.object(RunSession, 'run_process', new=original), fixture.inert_native_leaf([]):
                        result = RunSession.run_process(SimpleNamespace(run_dir=root), operation,
                            arguments=argv, limits={}, immutable_input_records=())
                    self.assertEqual(result, 'receipt')
                    self.assertEqual(len(seen), 1)
                    script = seen[0]['arguments'][-1]
                    compile(script, '<inert-child>', 'exec')
                    if operation in ('collision_build_01', 'background_build'):
                        self.assertIn(repr(output), script)
                        self.assertNotIn(repr(guard) + ').write', script)
                    if operation == 'collision_build_01':
                        self.assertIn(repr(str(Path(output).with_suffix('.pa-surf'))), script)
                    cases += 1
        self.assertEqual(cases, 16)


if __name__ == '__main__':
    unittest.main()

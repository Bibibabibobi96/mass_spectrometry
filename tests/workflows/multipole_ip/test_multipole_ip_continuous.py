"""Pure RF–IP consumer wiring; native stages never execute."""
import unittest
from unittest.mock import Mock, patch

from tests.contracts.test_simion_rf_tracking import rf_tracking_case
from tests.contracts.test_simion_geometry_compiler import independent_rf_inputs
from tests.workflows.multipole_ip import test_ip_compiler as ip_fixture
from msplatform.workflows.multipole_ip import continuous


class ContinuousConsumerTests(unittest.TestCase):
    def setUp(self):
        fixture = ip_fixture.IpCompilerTests(methodName='runTest')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.assembly, self.geometry_numerics = fixture.assembly, fixture.numerics
        _, _, self.birth, _, self.propagation, self.numerics = rf_tracking_case()
        self.propagation['dynamics']['collisions'] = 'hs1'
        self.numerics['grouped'] = 0
        self.hs1 = dict(bath_domain=object(), outer=object(), vendor_record=object(), numerics=object())
        self.context = object()
        self.common = dict(particles=self.birth, propagation=self.propagation,
            observations={'plane_observations':[]}, tracking_numerics=self.numerics,
            hs1_request=self.hs1, context=self.context)
        self.drive = {'clock':{'phase_reference_instrument_time_us':0}, 'clock_authority':{'selected':True}}
        self.physics, self.field_numerics = {'physics':'explicit'}, {'solver':'explicit'}

    def test_real_compile_then_ordered_public_stage_forwarding(self):
        stages = Mock()
        stages.attach_mock(Mock(wraps=continuous.operations.compile_geometry), 'compile')
        stages.attach_mock(Mock(return_value='geometry'), 'build')
        stages.attach_mock(Mock(return_value='model'), 'model')
        stages.attach_mock(Mock(return_value='fields'), 'fields')
        stages.attach_mock(Mock(return_value='trajectory'), 'track')
        with patch.object(continuous.operations, 'compile_geometry', stages.compile), \
             patch.object(continuous.operations, 'build_geometry', stages.build), \
             patch.object(continuous.operations, 'prepare_model', stages.model), \
             patch.object(continuous.operations, 'solve_fields', stages.fields), \
             patch.object(continuous.operations, 'track', stages.track):
            result = continuous.run_continuous(assembly=self.assembly, geometry_numerics=self.geometry_numerics,
                drive=self.drive, physics=self.physics, field_numerics=self.field_numerics,
                birth_source_authority={'manifest':'source'}, unit_size=5, recovery_reference={'path':'prior'},
                dispatch_profiles=({'name':'selected'},), **self.common)
        self.assertEqual(result, 'trajectory')
        self.assertEqual([call[0] for call in stages.mock_calls], ['compile','build','model','fields','track'])
        self.assertIs(stages.compile.call_args.args[0], self.assembly)
        self.assertIs(stages.compile.call_args.kwargs['numerics'], self.geometry_numerics)
        self.assertEqual(stages.build.call_args.args[0].frontend_geometry['role'], 'simion_rf_ip_geometry')
        self.assertIs(stages.model.call_args.kwargs['drive'], self.drive)
        self.assertIs(stages.model.call_args.kwargs['physics'], self.physics)
        self.assertIs(stages.fields.call_args.kwargs['numerics'], self.field_numerics)
        self.assertIs(stages.track.call_args.args[1], self.birth)
        for name, value in [('propagation',self.propagation),('observations',self.common['observations']),
                            ('numerics',self.numerics),('hs1_request',self.hs1),('context',self.context)]:
            self.assertIs(stages.track.call_args.kwargs[name], value)
        self.assertEqual(stages.track.call_args.kwargs['birth_source_authority'], {'manifest':'source'})
        self.assertEqual(stages.track.call_args.kwargs['unit_size'], 5)
        self.assertEqual(stages.track.call_args.kwargs['recovery_reference'], {'path':'prior'})
        self.assertEqual(stages.track.call_args.kwargs['dispatch_profiles'], ({'name':'selected'},))

    def test_actual_reader_bad_reference_no_rebuild_and_explicit_field(self):
        with patch.object(continuous.operations, 'compile_geometry') as compile_:
            with self.assertRaises((ValueError, TypeError, KeyError)):
                continuous.track_existing_fields(fields={}, **self.common)
            compile_.assert_not_called()
        with patch.object(continuous.operations, 'compile_geometry') as compile_, \
             patch.object(continuous.operations, 'track', return_value='trajectory') as track:
            self.assertEqual(continuous.track_existing_fields(fields='explicit', **self.common), 'trajectory')
            compile_.assert_not_called()
            self.assertEqual(track.call_args.args[0], 'explicit')
            self.assertIs(track.call_args.args[1], self.birth)

    def test_expected_component_scope_uses_published_model_and_rejects_rf_ip_for_full_joint(self):
        source = Mock()
        source.data_path.return_value.read_text.return_value = '{}'
        projects = {
            'rf': 'rf_multipole_ion_optics',
            'ip': 'dual_pressure_rectilinear_ion_processor',
        }
        document = {'geometry': {'frontend_geometry': {'composition_plan': {
            'scope': {'instance_ids': list(projects)},
            'components': {key: {'project_id': value} for key, value in projects.items()}}}},
            'components_resolved': {key: {} for key in projects}}
        for expected, accepted in [('rf_ip', True), ('rf_ip_mr', False)]:
            with self.subTest(expected=expected), \
                 patch('msplatform.results.artifacts.open_artifact', return_value=source), \
                 patch('msplatform.backends.simion.model.require_prepared_model', return_value=document), \
                 patch.object(continuous.operations, 'track', return_value='trajectory') as track:
                if accepted:
                    self.assertEqual(continuous.track_existing_fields(
                        fields={'manifest': 'fields'}, expected_component_scope=expected,
                        **self.common), 'trajectory')
                    self.assertIs(track.call_args.args[0], source)
                else:
                    with self.assertRaisesRegex(ValueError, 'exact rf_ip_mr component scope'):
                        continuous.track_existing_fields(fields={'manifest': 'fields'},
                            expected_component_scope=expected, **self.common)
                    track.assert_not_called()
        document['geometry']['frontend_geometry']['composition_plan']['components']['mr'] = {
            'project_id': 'parallel_mirror_dual_stripe_mr_tof'}
        document['geometry']['frontend_geometry']['composition_plan']['scope']['instance_ids'].append('mr')
        document['components_resolved']['mr'] = {}
        with patch('msplatform.results.artifacts.open_artifact', return_value=source), \
             patch('msplatform.backends.simion.model.require_prepared_model', return_value=document), \
             patch.object(continuous.operations, 'track', return_value='trajectory'):
            self.assertEqual(continuous.track_existing_fields(fields={'manifest': 'fields'},
                expected_component_scope='rf_ip_mr', **self.common), 'trajectory')

    def test_sampled_field_arguments_forwarded_to_public_owner(self):
        basis={'explicit':'sampled'}; collision={'explicit':'collision-producer'}
        with patch.object(continuous.operations, 'compile_geometry', return_value='compiled'), \
             patch.object(continuous.operations, 'build_geometry', return_value='geometry'), \
             patch.object(continuous.operations, 'prepare_model', return_value='model'), \
             patch.object(continuous.operations, 'solve_fields', return_value='fields') as solve, \
             patch.object(continuous.operations, 'track', return_value='trajectory'):
            self.assertEqual(continuous.run_continuous(assembly=self.assembly, geometry_numerics=self.geometry_numerics,
                drive=self.drive,physics=self.physics,field_numerics=self.field_numerics,
                scalar_field_basis=basis,reuse_collision_geometry=collision,**self.common),'trajectory')
        self.assertIs(solve.call_args.kwargs['scalar_field_basis'],basis)
        self.assertIs(solve.call_args.kwargs['reuse_collision_geometry'],collision)

    def test_actual_wrong_scope_and_missing_inputs_refuse_before_native(self):
        for changed in ({'particles':None}, {'particles':dict(role='handoff_result')},
                        {'particles':dict(self.birth, rows=[])},
                        {'propagation':dict(self.propagation, scope='segmented_upstream')},
                        {'propagation':dict(self.propagation, scope='state_relaunch')},
                        {'propagation':dict(self.propagation, stop={'observation_id':'interface'})},
                        {'particles':dict(self.birth, clock=None)}, {'hs1_request':None}):
            with self.subTest(changed=changed), patch.object(continuous.operations, 'compile_geometry') as compile_:
                with self.assertRaises(ValueError):
                    continuous.run_continuous(assembly=self.assembly, geometry_numerics=self.geometry_numerics,
                        drive=self.drive, physics=self.physics, field_numerics=self.field_numerics, **(self.common | changed))
                compile_.assert_not_called()
        rf, numerics = independent_rf_inputs()
        with patch.object(continuous.operations, 'build_geometry', side_effect=ValueError('public capability refusal')) as build:
            with self.assertRaisesRegex(ValueError, 'public capability refusal'):
                continuous.run_continuous(assembly=rf, geometry_numerics=numerics, drive=self.drive,
                    physics=self.physics, field_numerics=self.field_numerics, **self.common)
            build.assert_called_once()
        with patch.object(continuous.operations, 'compile_geometry') as compile_:
            with self.assertRaisesRegex(ValueError, 'clock authority'):
                continuous.run_continuous(assembly=self.assembly, geometry_numerics=self.geometry_numerics,
                    drive={}, physics=self.physics, field_numerics=self.field_numerics, **self.common)
            compile_.assert_not_called()


class ContinuousInputTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.vendor = self.root / 'vendor.lua'
        self.vendor.write_text('-- original vendor fixture\n', encoding='utf-8')
        self.request = {
            'schema_version': 1,
            'bath_domain': self.box((0, -10, -10), (211, 10, 10)),
            'outer': {
                'field_id': 'outer', 'frame_id': 'ip_local', 'composition_id': 'one_gas',
                'species': [{'species_id': 'gas', 'mass_amu': 28, 'mole_fraction': 1}],
                'domain': self.box((-200, -40, -40), (300, 40, 40)),
                'source': {'kind': 'prescribed', 'source_id': 'explicit', 'assumptions': []},
                'uniform_state': {'status': 'gas', 'pressure_pa': 4,
                                  'temperature_k': 300, 'bulk_velocity_m_s': [1, 2, 3]}},
            'vendor_path': 'vendor.lua', 'numerics': {'seed': 40, 'hs1_steps_per_mfp': 20}}

    @staticmethod
    def box(lo, hi):
        return {'minimum_mm': lo, 'maximum_mm': hi,
                'lower_closed': [True] * 3, 'upper_closed': [True] * 3}

    def write(self, name, value):
        import json
        path = self.root / name
        path.write_text(json.dumps(value), encoding='utf-8')
        return path

    def test_hs1_document_resolves_typed_inputs_and_relative_vendor(self):
        from msplatform.contracts.gas import BoxDomain, GasFieldSpec
        result = continuous.load_hs1_request(self.write('hs1.json', self.request))
        self.assertIsInstance(result['bath_domain'], BoxDomain)
        self.assertIsInstance(result['outer'], GasFieldSpec)
        self.assertEqual(result['outer'].uniform_state.bulk_velocity_m_s, (1., 2., 3.))
        self.assertEqual(result['vendor_record']['path'], str(self.vendor.resolve()))
        self.assertEqual(result['numerics'], {'seed': 40, 'hs1_steps_per_mfp': 20})

    def test_hs1_document_rejects_unknown_fields_bad_composition_and_missing_vendor(self):
        from copy import deepcopy
        for mutate in (
                lambda value: value.update(extra=True),
                lambda value: value['outer']['species'][0].update(mole_fraction=.5),
                lambda value: value.update(vendor_path='missing.lua')):
            with self.subTest(mutate=mutate):
                value = deepcopy(self.request)
                mutate(value)
                with self.assertRaises((ValueError, FileNotFoundError, AssertionError)):
                    continuous.load_hs1_request(self.write('bad.json', value))

    def test_real_cli_forwards_original_birth_and_explicit_recovery_inputs(self):
        from msplatform.ion_release.authoring import ReleaseRealization
        fixture = ContinuousConsumerTests(methodName='runTest')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        release = fixture.birth if isinstance(fixture.birth, ReleaseRealization) else fixture.birth
        paths = {name: self.write(name + '.json', value) for name, value in (
            ('release', {'role': 'release_fixture'}), ('fields', {'manifest': 'fields'}),
            ('propagation', fixture.propagation), ('observations', {'plane_observations': []}),
            ('numerics', fixture.numerics), ('recovery', {'manifest': 'prior'}),
            ('dispatch', [{'name': 'selected'}]))}
        hs1 = self.write('hs1.json', self.request)
        environment = self.write('environment.json', {'selected': True})
        workspace = self.root / 'workspace'
        argv = ['continuous', '--release-request', str(paths['release']),
            '--fields-reference', str(paths['fields']), '--propagation', str(paths['propagation']),
            '--observations', str(paths['observations']), '--numerics', str(paths['numerics']),
            '--hs1-request', str(hs1), '--environment', str(environment),
            '--workspace', str(workspace), '--profile', 'engineering',
            '--recovery-reference', str(paths['recovery']), '--dispatch-profiles', str(paths['dispatch']),
            '--unit-size', '5']
        result = Mock(reference={'manifest': 'returned'})
        with patch('msplatform.ion_release.sample_release', return_value=release) as sample, \
             patch('msplatform.execution.load_environment', return_value=fixture.context) as load, \
             patch.object(continuous, 'track_existing_fields', return_value=result) as track, \
             patch('sys.argv', argv):
            continuous.main()
        sample.assert_called_once_with({'role': 'release_fixture'})
        load.assert_called_once_with(environment, workspace=workspace, profile='engineering')
        self.assertIs(track.call_args.kwargs['particles'], release)
        self.assertEqual(track.call_args.kwargs['fields'], {'manifest': 'fields'})
        self.assertEqual(track.call_args.kwargs['recovery_reference'], {'manifest': 'prior'})
        self.assertEqual(track.call_args.kwargs['dispatch_profiles'], [{'name': 'selected'}])
        self.assertEqual(track.call_args.kwargs['unit_size'], 5)
        self.assertEqual(track.call_args.kwargs['expected_component_scope'], 'rf_ip')
        self.assertEqual(track.call_args.kwargs['hs1_request']['vendor_record']['path'], str(self.vendor.resolve()))

    def test_powershell_entry_reaches_continuous_owner_with_real_python(self):
        import shutil
        import subprocess
        import sys
        from msplatform import examples
        from pathlib import Path
        repo = Path(continuous.__file__).resolve().parents[5]
        release = self.write('release.json', examples.load_example('rf_oatof_functional_v1').release)
        fields = self.write('fields.json', {})
        propagation = self.write('propagation.json', {})
        observations = self.write('observations.json', {'plane_observations': []})
        numerics = self.write('numerics.json', {})
        hs1 = self.write('hs1.json', self.request)
        environment = self.write('environment.json', {})
        script = repo / 'src/msplatform/workflows/resources/multipole_ip_continuous.ps1'
        command = [shutil.which('pwsh'), '-NoProfile', '-File', str(script),
            '-ReleaseRequest', str(release), '-FieldsReference', str(fields),
            '-Propagation', str(propagation), '-Observations', str(observations),
            '-Numerics', str(numerics), '-Hs1Request', str(hs1),
            '-Environment', str(environment), '-Workspace', str(self.root), '-Profile', 'test',
            '-Python', sys.executable]
        result = subprocess.run(command, cwd=self.root, capture_output=True, text=True, encoding='utf-8',
                                errors='replace', timeout=60)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('continuous.py', result.stdout + result.stderr)
        self.assertIn('load_environment', result.stdout + result.stderr)
        self.assertNotIn('multipole_ip.prepare', result.stdout + result.stderr)

    def test_powershell_external_cwd_returns_public_consumer_reference_and_sources(self):
        import json
        import os
        import shutil
        import subprocess
        import sys
        from msplatform import examples
        from pathlib import Path
        repo = Path(continuous.__file__).resolve().parents[5]
        self.write('release.json', examples.load_example('rf_oatof_functional_v1').release)
        self.write('fields.json', {'manifest': 'selected-fields'})
        self.write('propagation.json', {})
        self.write('observations.json', {'plane_observations': []})
        self.write('numerics.json', {})
        self.write('hs1.json', self.request)
        self.write('environment.json', {})
        outside = self.root / 'external-cwd'
        outside.mkdir()
        runtime = self.root / 'runtime'
        subprocess.run([sys._base_executable, '-m', 'venv', '--system-site-packages', str(runtime)],
            check=True, cwd=self.root, timeout=120)
        installed_python = runtime / 'Scripts/python.exe'
        subprocess.run([str(installed_python), '-m', 'pip', 'install', '--no-deps', str(repo)], check=True,
            cwd=self.root, capture_output=True, text=True, timeout=120)
        locked = Path(sys.executable).resolve().parents[2] / 'Lib/site-packages'
        (runtime / 'Lib/site-packages/_p4_test_lock.pth').write_text(str(locked) + '\n', encoding='utf-8')
        capture = self.root / 'observed.json'
        owner_source = runtime / 'Lib/site-packages/msplatform/workflows/multipole_ip/continuous.py'
        source = owner_source.read_text(encoding='utf-8')
        start = source.index('def track_existing_fields(')
        end = source.index('\ndef run_continuous(', start)
        replacement = (
            'def track_existing_fields(**kwargs):\n'
            '    import json\n'
            f'    Path(r"{capture}").write_text(json.dumps({{"fields": kwargs["fields"], "vendor": kwargs["hs1_request"]["vendor_record"]["path"], "workspace": str(kwargs["context"].workspace)}}), encoding="utf-8")\n'
            '    return SimpleNamespace(reference={"manifest": "returned-trajectory"})\n\n')
        source = source[:start] + replacement + source[end:]
        source = source.replace(
            'context=load_environment(args.environment, workspace=args.workspace, profile=args.profile),',
            'context=SimpleNamespace(workspace=args.workspace),')
        source = source.replace('from typing import Any', 'from typing import Any\nfrom types import SimpleNamespace')
        owner_source.write_text(source, encoding='utf-8')
        script = runtime / 'Lib/site-packages/msplatform/workflows/resources/multipole_ip_continuous.ps1'
        arguments = ['-ReleaseRequest', '../release.json', '-FieldsReference', '../fields.json',
            '-Propagation', '../propagation.json', '-Observations', '../observations.json',
            '-Numerics', '../numerics.json', '-Hs1Request', '../hs1.json',
            '-Environment', '../environment.json', '-Workspace', '..', '-Profile', 'test',
            '-Python', str(installed_python)]
        environment = {key: value for key, value in os.environ.items() if key != 'PYTHONPATH'}
        result = subprocess.run([shutil.which('pwsh'), '-NoProfile', '-File', str(script), *arguments],
            cwd=outside, env=environment, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('OWNER_RETURNED={"manifest": "returned-trajectory"}', result.stdout)
        observed = json.loads(capture.read_text(encoding='utf-8'))
        self.assertEqual(observed['fields'], {'manifest': 'selected-fields'})
        self.assertEqual(observed['vendor'], str(self.vendor.resolve()))
        self.assertEqual(observed['workspace'], str(self.root))

    def test_thin_powershell_entries_require_explicit_python(self):
        import os
        import shutil
        import subprocess
        from pathlib import Path
        repo = Path(continuous.__file__).resolve().parents[5]
        paths = {name: str(self.write(name + '.json', {})) for name in (
            'release', 'fields', 'propagation', 'observations', 'numerics', 'hs1', 'environment')}
        cases = [
            (repo / 'src/msplatform/workflows/resources/multipole_ip_continuous.ps1',
             ['-ReleaseRequest', paths['release'], '-FieldsReference', paths['fields'],
              '-Propagation', paths['propagation'], '-Observations', paths['observations'],
              '-Numerics', paths['numerics'], '-Hs1Request', paths['hs1'],
              '-Environment', paths['environment'], '-Workspace', str(self.root), '-Profile', 'profile']),
            (repo / 'src/msplatform/workflows/resources/single_reflection_flight.ps1',
             ['-FieldsReference', paths['fields'], '-Observations', paths['observations'],
              '-Environment', paths['environment'], '-Workspace', str(self.root), '-Profile', 'profile']),
        ]
        environment = {key: value for key, value in os.environ.items() if key != 'SIMULATION_PYTHON_EXE'}
        for script, arguments in cases:
            with self.subTest(script=script.name):
                result = subprocess.run([shutil.which('pwsh'), '-NoProfile', '-File', str(script), *arguments],
                    cwd=self.root, env=environment, capture_output=True, text=True, encoding='utf-8',
                    errors='replace', timeout=30)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('SIMULATION_PYTHON_EXE is required', result.stdout + result.stderr)

"""Pure RF–IP consumer wiring; native stages never execute."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from common.contracts.test_simion_rf_tracking import rf_tracking_case
from common.contracts.test_simion_geometry_compiler import independent_rf_inputs
from integrations.tests import test_ip_compiler as ip_fixture
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
        self.field = SimpleNamespace(kind='field_bundle', metadata={'field_representation':'producer_owned_rf_ip_fractional_family'})

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
             patch.object(continuous.operations, 'track', stages.track), \
             patch.object(continuous, 'open_artifact', return_value=self.field):
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
        with patch.object(continuous.operations, 'compile_geometry') as compile_, patch.object(continuous.operations, 'track') as track:
            with self.assertRaises((ValueError, TypeError, KeyError)):
                continuous.track_existing_fields(fields={}, **self.common)
            compile_.assert_not_called(); track.assert_not_called()
        with patch.object(continuous.operations, 'compile_geometry') as compile_, \
             patch.object(continuous.operations, 'track', return_value='trajectory') as track, \
             patch.object(continuous, 'open_artifact', return_value=self.field):
            self.assertEqual(continuous.track_existing_fields(fields='explicit', **self.common), 'trajectory')
            compile_.assert_not_called(); self.assertIs(track.call_args.args[1], self.birth)
        with patch.object(continuous, 'open_artifact', return_value=SimpleNamespace(kind='field_bundle',metadata={'field_representation':'producer_owned_rf_fractional_family'})):
            with self.assertRaisesRegex(ValueError, 'complete RF-IP'):
                continuous.track_existing_fields(fields='rf-only', **self.common)

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
        with patch.object(continuous.operations, 'build_geometry') as build:
            with self.assertRaisesRegex(ValueError, 'complete RF and IP'):
                continuous.run_continuous(assembly=rf, geometry_numerics=numerics, drive=self.drive,
                    physics=self.physics, field_numerics=self.field_numerics, **self.common)
            build.assert_not_called()
        with patch.object(continuous.operations, 'compile_geometry') as compile_:
            with self.assertRaisesRegex(ValueError, 'clock authority'):
                continuous.run_continuous(assembly=self.assembly, geometry_numerics=self.geometry_numerics,
                    drive={}, physics=self.physics, field_numerics=self.field_numerics, **self.common)
            compile_.assert_not_called()

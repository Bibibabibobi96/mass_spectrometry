"""Standalone IP selected-geometry and representation software tests."""
import copy
import unittest

from msplatform.backends.simion.ip_geometry import render_gem, represent_selected_ip_design
from msplatform.components.dual_pressure_rectilinear_ion_processor.native_geometry import native_projection, select_legacy_physical_design
from msplatform.workflows.ion_processor.preparation import compile_source, recorded_native_projection
from projects.dual_pressure_rectilinear_ion_processor.tests.test_functional import load_config


class SelectedPhysicalGeometryTests(unittest.TestCase):
    def test_real_compile_source_preserves_legacy_and_fixes_selected_csg(self):
        config = load_config()
        old = native_projection(config['baseline'], config['numerics'])
        legacy = compile_source(config)
        self.assertEqual(legacy['config']['native_projection'], old)
        self.assertNotIn('physical_design_selection', legacy['config'])
        choice = {key: config['numerics'][key] for key in ('native_grid_mm', 'native_aux_segments')}
        config['baseline']['physical_design_selection'] = choice
        same = compile_source(config)
        self.assertEqual(same['config']['native_projection'], old)
        self.assertEqual(render_gem(same['config']['native_projection']), render_gem(old))
        finer = copy.deepcopy(config)
        finer['numerics']['native_grid_mm'] = .2
        changed = compile_source(finer)
        self.assertEqual(changed['config']['native_projection']['electrodes'], old['electrodes'])
        self.assertEqual(changed['config']['physical_design_selection'], same['config']['physical_design_selection'])
        self.assertEqual(changed['states'], same['states'])
        self.assertNotEqual(changed['config']['native_projection']['shape_gu'], old['shape_gu'])
        self.assertEqual(changed['config']['native_projection']['auxiliary_segments'], 60)

    def test_nondefault_partial_and_coarse_geometry_is_not_rewritten(self):
        config = load_config()
        baseline = copy.deepcopy(config['baseline'])
        baseline['geometry']['r0_mm'] = 3.55
        choice = {'native_grid_mm': .1, 'native_aux_segments': 60}
        old = native_projection(baseline, choice)
        selected = select_legacy_physical_design(baseline, selection_grid_mm=.1, auxiliary_segments=60)
        self.assertEqual(represent_selected_ip_design(selected, baseline=baseline, grid_mm=.1), old)
        for grid in (.01, .2, 6.):
            with self.subTest(grid=grid):
                self.assertEqual(represent_selected_ip_design(selected, baseline=baseline, grid_mm=grid)['electrodes'], old['electrodes'])
        self.assertEqual(render_gem(represent_selected_ip_design(selected, baseline=baseline, grid_mm=.1)), render_gem(old))

    def test_rejects_bad_selection_grid_and_changed_baseline(self):
        config = load_config()
        baseline = config['baseline']
        selected = select_legacy_physical_design(baseline, selection_grid_mm=.1, auxiliary_segments=60)
        for grid in (0., -1., float('nan'), True):
            with self.subTest(grid=grid), self.assertRaises(ValueError):
                represent_selected_ip_design(selected, baseline=baseline, grid_mm=grid)
        altered = copy.deepcopy(baseline)
        altered['geometry']['lp_length_mm'] += 1
        with self.assertRaisesRegex(ValueError, 'selected IP physical design differs from its declared source'):
            represent_selected_ip_design(selected, baseline=altered, grid_mm=.1)
        config['baseline']['physical_design_selection'] = {'native_grid_mm': .1}
        with self.assertRaisesRegex(ValueError, 'explicit legacy physical selection'):
            compile_source(config)
        with self.assertRaises(TypeError):
            compile_source(config, physical_selection={'native_grid_mm': .1, 'native_aux_segments': 60})

    def test_public_representation_rejects_mutated_selection_or_csg(self):
        baseline = load_config()['baseline']
        selected = select_legacy_physical_design(baseline, selection_grid_mm=.1, auxiliary_segments=60)
        for name in ('selection', 'cutout'):
            changed = copy.deepcopy(selected)
            if name == 'selection':
                changed['selection']['native_aux_segments'] = 61
            else:
                changed['projection']['electrodes'][4]['cutouts'][0]['min_mm'][1] += .01
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'differs'):
                represent_selected_ip_design(changed, baseline=baseline, grid_mm=.2)

    def test_frozen_selection_must_match_baseline_authority(self):
        config = load_config()
        config['baseline']['physical_design_selection'] = {'native_grid_mm': .1, 'native_aux_segments': 60}
        compiled = compile_source(config)['config']
        self.assertEqual(recorded_native_projection(compiled), compiled['native_projection'])
        for field in ('selection', 'baseline', 'missing_record'):
            altered = copy.deepcopy(compiled)
            if field == 'selection':
                altered['physical_design_selection']['selection']['native_grid_mm'] = .2
            elif field == 'baseline':
                altered['baseline']['physical_design_selection']['native_grid_mm'] = .2
            else:
                del altered['physical_design_selection']
            with self.subTest(field=field), self.assertRaises(ValueError):
                recorded_native_projection(altered)

    def test_numerics_must_match_selected_staircase(self):
        selection = {'native_grid_mm': .1, 'native_aux_segments': 60}
        for count in (61, 9, 60.5):
            config = load_config()
            config['baseline']['physical_design_selection'] = selection
            config['numerics']['native_aux_segments'] = count
            with self.subTest(count=count), self.assertRaisesRegex(ValueError, 'match'):
                compile_source(config)

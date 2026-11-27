"""COMSOL technical author input compiles without running a native solver."""
import json
from pathlib import Path
import unittest

from msplatform import assembly, components
from msplatform.particle_release import sample_release
from msplatform.recipes import load_recipe, validate_recipe
from msplatform.workflows.comsol_tracing import compile_comsol_inputs


class ComsolNativeExampleTests(unittest.TestCase):
    def test_frozen_example_preserves_source_and_compiles_actual_workpoints(self):
        root = Path(__file__).resolve().parents[2] / 'src/msplatform/examples'
        loaded = load_recipe(root / 'oa_split_tof_comsol_small_v1.toml').to_dict()
        self.assertEqual(validate_recipe(loaded), loaded)
        study = loaded['study']['document']
        original = json.loads((root / 'oa_split_tof_native_small_v1.json').read_text(encoding='utf-8'))
        for key in ('component_requests', 'recipe', 'drive', 'release'):
            self.assertEqual(study[key], original[key])
        instrument = assembly.assemble(study['recipe'], {k: components.resolve_component(v)
                                                        for k, v in study['component_requests'].items()})
        result = compile_comsol_inputs(loaded, instrument, sample_release(study['release']))
        self.assertEqual(len(result['projection']['members']), 45)
        self.assertEqual(len(result['requests']['off']['group_voltages']), 43)
        self.assertEqual(len(result['source']['rows']), 3)
        self.assertEqual(result['geometry']['outer_box_mm'], {'min': [-400, -400, -100], 'max': [400, 400, 920]})
        self.assertEqual(result['observation_times_us'], [0.0, 80.0513730009902, 90.0, 100.0])
        off = {(r['instance_id'], r['electrode_group_id']): r['voltage_v'] for r in result['requests']['off']['group_voltages']}
        on = {(r['instance_id'], r['electrode_group_id']): r['voltage_v'] for r in result['requests']['on']['group_voltages']}
        self.assertEqual((off['oa', 'repeller'], on['oa', 'repeller']), (0.0, 2140.0))
        self.assertEqual(off['tof', 'reflectron_backplate'], on['tof', 'reflectron_backplate'])


if __name__ == '__main__':
    unittest.main()

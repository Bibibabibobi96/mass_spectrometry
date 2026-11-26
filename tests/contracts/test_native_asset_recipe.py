"""Public recipe snapshots and identities for COMSOL-to-SIMION authored fields."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from msplatform.recipes import load_recipe, validate_recipe
from tests.contracts.test_native_assets import collision_manifest, manifest


class NativeAssetRecipeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        source = Path(__file__).resolve().parents[2] / 'src/msplatform/examples/oa_split_tof_comsol_small_v1.json'
        study = json.loads(source.read_text(encoding='utf-8'))
        study['numerics']['tracing'] = {'end_policy': {'maximum_particle_age_us': 100.0},
                                      'simion': {'maximum_step_us': 0.01, 'trajectory_quality': 0}}
        self.study = json.dumps(study).encode('utf-8')
        self.comsol = json.dumps(manifest()).encode('utf-8')
        self.simion = json.dumps(collision_manifest()).encode('utf-8')

    def author(self, directory, *, label='example', pitch='1.0', collision=None,
               field_kind='comsol_native', tracer='simion', strategy='sampled_joint_field'):
        directory.mkdir(parents=True, exist_ok=True)
        (directory/'study.json').write_bytes(self.study)
        (directory/'field.json').write_bytes(self.comsol)
        selected = self.simion if collision is None else collision
        (directory/'collision.json').write_bytes(selected)
        sha = lambda value: hashlib.sha256(value).hexdigest()
        body = f'''schema_version = 2
constants_version = "repository_particle_physics_v1"
label = "{label}"
particle_tracer = "{tracer}"
field_assembly_strategy = "{strategy}"
particle_field_coupling = "external_given_field"
[gas_environment]
status = "vacuum"
[study]
path = "study.json"
sha256 = "{sha(self.study)}"
[field_source]
kind = "{field_kind}"
[field_source.reference]
path = "field.json"
sha256 = "{sha(self.comsol)}"
product_id = "background"
[field_source.collision_reference]
path = "collision.json"
sha256 = "{sha(selected)}"
product_id = "fields"
[field_source.sampling]
windows = []
[field_source.sampling.world]
frame_id = "oatof_global"
origin_mm = [-400.0, -400.0, -100.0]
pitch_mm = [{pitch}, 1.0, 1.0]
dimensions = [801, 801, 1021]
block_points = 10000
[recording]
mode = "observation_times"
observation_times_us = [0.0, 80.0, 100.0]
'''
        path = directory/'author.toml'
        path.write_text(body, encoding='utf-8')
        return path

    def test_real_load_one_read_each_and_frozen_validation(self):
        author = self.author(self.root)
        expected = {self.root/'field.json', self.root/'collision.json'}
        reads, original = [], Path.read_bytes
        def observed(path):
            if path in expected:
                reads.append(path)
            return original(path)
        with patch.object(Path, 'read_bytes', observed):
            loaded = load_recipe(author).to_dict()
        self.assertCountEqual(reads, list(expected))
        self.assertEqual(len(reads), 2)
        for path in expected:
            path.write_text('{}', encoding='utf-8')
        with patch.object(Path, 'read_bytes', side_effect=AssertionError('external reread')):
            self.assertEqual(validate_recipe(loaded), loaded)
        self.assertEqual(loaded['field_source']['sampling']['windows'], [])

    def test_identity_is_content_bound_not_path_or_label(self):
        first = load_recipe(self.author(self.root/'first')).to_dict()
        moved = load_recipe(self.author(self.root/'moved', label='another label')).to_dict()
        self.assertEqual(first['recipe_id'], moved['recipe_id'])
        different_grid = load_recipe(self.author(self.root/'grid', pitch='1.25')).to_dict()
        self.assertNotEqual(first['recipe_id'], different_grid['recipe_id'])
        altered = copy.deepcopy(collision_manifest())
        altered['run_id'] = 'different_owner_identity'
        different_collision = load_recipe(self.author(self.root/'collision', collision=json.dumps(altered).encode())).to_dict()
        self.assertNotEqual(first['recipe_id'], different_collision['recipe_id'])

    def test_invalid_field_strategy_combinations_are_rejected(self):
        for index, changes in enumerate(({'field_kind': 'simion_native'}, {'strategy': 'joint_solve'},
                                         {'tracer': 'comsol'})):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                load_recipe(self.author(self.root/str(index), **changes))


if __name__ == '__main__':
    unittest.main()

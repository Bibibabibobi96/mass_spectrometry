"""Native recipe snapshots, assembly identities and unsupported input rejection."""
import base64
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from msplatform.recipes import load_recipe, validate_recipe
from msplatform.recipes.native import _sequence
from msplatform.physics import CONSTANTS

ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / 'src/msplatform/examples/rf_oatof_functional_v1.json'


class NativeRecipeTests(unittest.TestCase):
    def test_comsol_requires_explicit_solver_and_si_birth_validation_controls(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_recipe(root)
            document = json.loads((root / 'study.json').read_text())
            document['numerics']['tracing'] = {
                'end_policy': {'absolute_instrument_end_us': 100.0},
                'comsol': {'maximum_step_us': 0.01, 'relative_tolerance': 1e-4, 'absolute_tolerance': 1e-6},
                'birth_validation': {'position_atol_m': 1e-10, 'velocity_atol_m_s': 1e-6},
            }
            def write(value):
                path = self.write_recipe(root, study_bytes=json.dumps(value).encode())
                text = path.read_text().replace('particle_tracer = "simion"', 'particle_tracer = "comsol"')
                path.write_text(text.replace('simion_native', 'comsol_native').replace('native_domain_composition', 'joint_solve'))
                return path
            self.assertEqual(load_recipe(write(document)).to_dict()['particle_tracer'], 'comsol')
            for key in ('comsol', 'birth_validation'):
                broken = copy.deepcopy(document)
                del broken['numerics']['tracing'][key]
                with self.subTest(key=key), self.assertRaises(ValueError):
                    load_recipe(write(broken))
            broken = copy.deepcopy(document)
            broken['numerics']['tracing']['comsol']['relative_tolerance'] = 1.0
            with self.assertRaisesRegex(ValueError, 'less than one'):
                load_recipe(write(broken))

    def write_recipe(self, root, *, study_bytes=None, label='native study', fields=''):
        study = root / 'study.json'
        if study_bytes is None:
            document = json.loads(STUDY.read_text(encoding='utf-8'))
            document['numerics']['tracing'] = {
                'end_policy': {'maximum_particle_age_us': 100.0},
                'simion': {'maximum_step_us': 0.01, 'trajectory_quality': 0, 'rf_steps_per_period': 32},
            }
            data = json.dumps(document).encode('utf-8')
        else:
            data = study_bytes
        study.write_bytes(data)
        digest = hashlib.sha256(data).hexdigest()
        path = root / 'recipe.toml'
        path.write_text(f'''schema_version = 2
label = "{label}"
particle_tracer = "simion"
field_assembly_strategy = "native_domain_composition"
particle_field_coupling = "external_given_field"
constants_version = "{CONSTANTS['version']}"
{fields}
[gas_environment]
status = "vacuum"
[study]
path = "study.json"
sha256 = "{digest}"
[field_source]
kind = "simion_native"
[recording]
mode = "observation_times"
observation_times_us = [1.0, 2.0, 3.0]
''', encoding='utf-8')
        return path

    def test_snapshot_resolves_real_assembly_and_survives_source_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            recipe = self.write_recipe(root)
            source = (root / 'study.json').read_bytes()
            real_read = Path.read_bytes
            study_reads = []
            def count_read(path):
                value = real_read(path)
                if path == root / 'study.json':
                    study_reads.append(value)
                return value
            with patch.object(Path, 'read_bytes', count_read):
                loaded = load_recipe(recipe)
            self.assertEqual(study_reads, [source])
            result = loaded.to_dict()
            self.assertEqual(loaded.source_bytes, recipe.read_bytes())
            self.assertEqual(base64.b64decode(result['study']['snapshot']['bytes_base64']), source)
            self.assertEqual(result['study']['document'], json.loads(source))
            self.assertEqual(result['assembly']['name'], 'rf_multipole__single_reflection_oa_tof')
            self.assertEqual(result['assembly']['composition_plan']['role'], 'integration_composition_plan_do_not_edit')
            self.assertEqual(set(result['resource_snapshots']), {'instrument_clock_authority_v1.json', 'instrument_epoch_v1.json'})
            (root / 'study.json').write_text('{}', encoding='utf-8')
            self.assertEqual(validate_recipe(result), result)
            for item in ('study', 'resource', 'assembly'):
                changed = copy.deepcopy(result)
                if item == 'study':
                    changed['study']['document']['name'] = 'tampered'
                elif item == 'resource':
                    changed['resource_snapshots']['instrument_epoch_v1.json']['bytes_base64'] = 'e30='
                else:
                    changed['assembly']['assembly_id'] = 'wrong'
                with self.subTest(item=item), self.assertRaises(ValueError):
                    validate_recipe(changed)

    def test_identity_excludes_label_and_source_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = load_recipe(self.write_recipe(root)).to_dict()
            second_dir = root / 'other'
            second_dir.mkdir()
            second = load_recipe(self.write_recipe(second_dir, label='another display')).to_dict()
            self.assertEqual(first['recipe_id'], second['recipe_id'])
            self.assertEqual(first['assembly']['assembly_id'], second['assembly']['assembly_id'])
            self.assertEqual(first['assembly']['name'], second['assembly']['name'])

    def test_invalid_source_and_unsupported_fields_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self.write_recipe(root)
            (root / 'study.json').write_text('{}', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'SHA-256 mismatch'):
                load_recipe(path)
            for key in ('drive', 'physics', 'release', 'numerics', 'component_requests', 'recipe', 'cad_export', 'model_input_sources'):
                source = json.loads(STUDY.read_text(encoding='utf-8'))
                del source[key]
                with self.subTest(key=key), self.assertRaises(ValueError):
                    load_recipe(self.write_recipe(root, study_bytes=json.dumps(source).encode()))
            with self.assertRaises(ValueError):
                load_recipe(self.write_recipe(root, fields='transport_mode = "segmented"'))
            path = self.write_recipe(root)
            path.write_text(path.read_text().replace('external_given_field', 'self_consistent'), encoding='utf-8')
            with self.assertRaises(ValueError):
                load_recipe(path)

    def test_missing_tracing_controls_and_observation_times_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self.write_recipe(root)
            good = json.loads((root / 'study.json').read_text())
            variants = []
            for key in ('tracing',):
                broken = copy.deepcopy(good)
                del broken['numerics'][key]
                variants.append(broken)
            for key in ('end_policy', 'simion'):
                broken = copy.deepcopy(good)
                del broken['numerics']['tracing'][key]
                variants.append(broken)
            for key in ('maximum_step_us', 'trajectory_quality'):
                broken = copy.deepcopy(good)
                del broken['numerics']['tracing']['simion'][key]
                variants.append(broken)
            for broken in variants:
                with self.subTest(broken=broken['numerics']), self.assertRaises(ValueError):
                    load_recipe(self.write_recipe(root, study_bytes=json.dumps(broken).encode()))
            path = self.write_recipe(root)
            path.write_text(path.read_text().replace('observation_times_us = [1.0, 2.0, 3.0]',
                                                     'observation_times_us = [2.0, 1.0]'), encoding='utf-8')
            with self.assertRaises(ValueError):
                load_recipe(path)

    def test_containment_is_directed_and_does_not_create_a_mechanical_connection(self):
        instances = [{'instance_id': 'oa'}, {'instance_id': 'tof'}]
        relation = {'relation_id': 'inside', 'contained_instance_id': 'oa',
                    'container_instance_id': 'tof', 'domain_id': 'vacuum',
                    'coupling_mode': 'monolithic_joint_solve'}
        recipe = {'instances': instances, 'connections': [], 'containments': [relation]}
        self.assertEqual(_sequence(recipe, {'oa': None, 'tof': None}), ['oa', 'tof'])
        for changes in ({'containments': []}, {'instances': list(reversed(instances))},
                        {'containments': [relation, relation]}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                _sequence({**recipe, **changes}, {'oa': None, 'tof': None})


if __name__ == '__main__':
    unittest.main()

"""Tests for explicit author units, physical identity and reference capabilities."""
import copy
from decimal import Decimal
import tempfile
import unittest
from pathlib import Path

from msplatform.contracts.particle_physics import AMU_KG, ELEMENTARY_CHARGE_C, BOLTZMANN_CONSTANT_J_K
from msplatform.physics import CONSTANTS, GasEnvironment
from msplatform.recipes import assembly_name, load_recipe, validate_recipe
from msplatform.tracing import trace_particles

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "recipes/reference/uniform_e.toml"


class ReferenceRecipeTests(unittest.TestCase):
    def test_equivalent_signed_charge_declarations_normalize_across_boundaries(self):
        text = SOURCE.read_text(encoding="utf-8")
        for z in (1, -1, 3, -3):
            with self.subTest(charge_state=z):
                charge = Decimal(z) * Decimal('1.602176634e-19')
                derived_text = text.replace('charge_state = 1', f'charge_state = {z}')
                explicit_text = derived_text.replace(f'charge_state = {z}', f'charge_state = {z}\ncharge_c = {charge}')
                derived, explicit = self.load_text(derived_text), self.load_text(explicit_text)
                self.assertEqual(derived, explicit)
                canonical = z * ELEMENTARY_CHARGE_C
                self.assertEqual(explicit['initial_states'][0]['charge_c'], canonical)
                alternate = copy.deepcopy(derived)
                alternate['initial_states'][0]['charge_c'] = float(charge)
                self.assertEqual(validate_recipe(alternate), derived)
                result = trace_particles(alternate)
                self.assertEqual(result.initial_states[0]['charge_c'], canonical)
                self.assertEqual(result.terminal_states, trace_particles(derived).terminal_states)
                with self.assertRaises(ValueError):
                    self.load_text(explicit_text.replace(f'charge_c = {charge}', 'charge_c = 1e-18'))

    def load_text(self, text):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "recipe.toml"
            path.write_text(text, encoding="utf-8")
            return load_recipe(path).to_dict()

    def test_units_and_label_are_canonical(self):
        text = SOURCE.read_text(encoding="utf-8")
        original = self.load_text(text.replace('position_mm = [0.0, 0.0, 0.0]', 'position_mm = [0.9, 0.0, 0.0]'))
        equivalent = self.load_text(text.replace('position_mm = [0.0, 0.0, 0.0]', 'position_m = [0.0009, 0.0, 0.0]').replace('Uniform electric field', 'Another label'))
        self.assertEqual(original['initial_states'][0]['position_m'][0], 0.0009)
        self.assertEqual(original['recipe_id'], equivalent['recipe_id'])
        self.assertEqual(original['assembly']['assembly_id'], equivalent['assembly']['assembly_id'])
        self.assertEqual(original['initial_states'][0]['mass_kg'], float(Decimal(100) * Decimal(str(AMU_KG))))
        self.assertEqual(original['initial_states'][0]['charge_c'], ELEMENTARY_CHARGE_C)
        self.assertEqual(original['clock'], {'basis': 'experiment_relative', 'unit': 's'})
        self.assertIsNone(original['initial_states'][0]['parent_particle_id'])
        self.assertEqual(original['initial_states'][0]['lineage_status'], 'unavailable_initial_snapshot')

    def test_packaged_reference_data_freezes_existing_constants_and_vacuum(self):
        self.assertEqual(CONSTANTS['atomic_mass_constant_kg'], AMU_KG)
        self.assertEqual(CONSTANTS['elementary_charge_c'], ELEMENTARY_CHARGE_C)
        self.assertEqual(CONSTANTS['boltzmann_constant_j_k'], BOLTZMANN_CONSTANT_J_K)
        self.assertEqual(GasEnvironment('vacuum').to_dict(), {
            'status': 'vacuum', 'pressure_pa': 0.0, 'collision_model': 'none',
            'data_version': 'repository_reference_physics_v1', 'collision_model_ref': 'none'})
        with self.assertRaises(ValueError):
            GasEnvironment('gas')

    def test_physical_change_and_assembly_identity(self):
        text = SOURCE.read_text(encoding="utf-8")
        original = self.load_text(text)
        field = self.load_text(text.replace('2000.0', '2001.0'))
        surface = self.load_text(text.replace('position_m = 0.01', 'position_m = 0.02'))
        self.assertNotEqual(original['recipe_id'], field['recipe_id'])
        self.assertEqual(original['assembly']['assembly_id'], field['assembly']['assembly_id'])
        self.assertNotEqual(original['assembly']['assembly_id'], surface['assembly']['assembly_id'])
        self.assertEqual(assembly_name(['ion_processor', 'multi_reflection_tof', 'multi_reflection_tof']), 'ion_processor__multi_reflection_tof__multi_reflection_tof')

    def test_capability_and_unknown_input_rejected(self):
        text = SOURCE.read_text(encoding="utf-8")
        changes = [text.replace('time_dependence = "static"', 'time_dependence = "dynamic"'),
                   text.replace('status = "vacuum"', 'status = "gas"'),
                   text.replace('particle_tracer = "scipy_dop853"', 'particle_tracer = "unknown"'),
                   text.replace('schema_version = 1', 'schema_version = 1\ntransport_mode = "segmented"'),
                   text.replace('mass_u = 100.0', 'mass_u = 100.0\nmass_kg = 1e-25')]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.load_text(change)

    def test_resolved_input_cannot_bypass_validation(self):
        original = load_recipe(SOURCE).to_dict()
        for mutate in ('charge', 'identity', 'unsupported', 'lineage'):
            value = copy.deepcopy(original)
            if mutate == 'charge':
                value['initial_states'][0]['charge_c'] = 0.0
            elif mutate == 'identity':
                value['assembly']['assembly_id'] = 'wrong'
            elif mutate == 'lineage':
                value['initial_states'][0]['parent_particle_id'] = 1
            else:
                value['field_source']['time_dependence'] = 'dynamic'
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                validate_recipe(value)
        self.assertEqual(validate_recipe(original), original)

    def test_all_reference_recipes_load(self):
        for name in ('no_field', 'uniform_e', 'uniform_b', 'crossed_e_b'):
            with self.subTest(name=name):
                self.assertEqual(load_recipe(ROOT / 'recipes/reference' / (name + '.toml')).to_dict()['gas_environment']['status'], 'vacuum')


if __name__ == '__main__':
    unittest.main()

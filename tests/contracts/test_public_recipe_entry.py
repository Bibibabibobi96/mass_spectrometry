"""Current public dispatch and component namespaces; no commercial solver."""
import importlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from msplatform.components import PROVIDER_DEPENDENCIES
from msplatform.recipes import load_recipe, validate_recipe

ROOT = Path(__file__).resolve().parents[2]


class PublicRecipeEntryTests(unittest.TestCase):
    def test_both_current_author_schemas_and_reject_old_schema(self):
        for path, schema in ((ROOT / 'recipes/reference/uniform_e.toml', 3),
                             (ROOT / 'src/msplatform/examples/oa_split_tof_native_small_v1.toml', 2)):
            recipe = load_recipe(path)
            self.assertEqual(recipe.to_dict()['schema_version'], schema)
            self.assertEqual(validate_recipe(recipe.to_dict()), recipe.to_dict())
        with tempfile.TemporaryDirectory() as tmp:
            old = Path(tmp) / 'old.toml'
            old.write_text('schema_version = 1\n', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'unsupported current recipe'):
                load_recipe(old)
        with self.assertRaisesRegex(ValueError, 'unsupported current recipe'):
            validate_recipe({'schema_version': 1})

    def test_components_have_one_active_namespace_and_packaged_resources(self):
        registry = json.loads((ROOT / 'config/project_registry.json').read_text(encoding='utf-8'))
        registry_text = json.dumps(registry)
        pairs = (('ion_processor', 'dual_pressure_rectilinear_ion_processor'),
                 ('multi_reflection_tof', 'parallel_mirror_dual_stripe_mr_tof'),
                 ('dual_cone_tandem_quadrupole', 'dual_cone_tandem_quadrupole_ion_interface'))
        import tomllib
        package_data = tomllib.loads((ROOT / 'pyproject.toml').read_text(encoding='utf-8'))['tool']['setuptools']['package-data']
        for current, historical in pairs:
            with self.subTest(current=current):
                name = 'msplatform.components.' + current
                self.assertIsNotNone(importlib.util.find_spec(name))
                self.assertIsNone(importlib.util.find_spec('msplatform.components.' + historical))
                self.assertIn(current, PROVIDER_DEPENDENCIES)
                self.assertNotIn(historical, PROVIDER_DEPENDENCIES)
                self.assertIn(name, package_data)
                self.assertIn('src/msplatform/components/' + current + '/config/project.json', registry_text)
                self.assertIn('docs/history/projects/' + current + '/retired_projects/' + historical, registry_text)

    def test_migrated_assembly_geometry_has_no_legacy_module(self):
        for name in ('msplatform.assembly.ip_mr_connection', 'msplatform.assembly.geometry_primitives',
                     'msplatform.components.ion_processor.assembly_geometry',
                     'msplatform.components.multi_reflection_tof.interface_clearance',
                     'msplatform.backends.simion.ip_mr_geometry', 'msplatform.results.component_exit_history'):
            self.assertIsNotNone(importlib.util.find_spec(name), name)
        for name in ('msplatform.assembly.ip_mr_geometry',
                     'msplatform.workflows.prepared_joint',
                     'msplatform.workflows.single_reflection_flight',
                     'msplatform.workflows.pulse_execution',
                     'msplatform.contracts.single_reflection_preparation',
                     'msplatform.backends.simion.field_plan',
                     'msplatform.backends.simion.frontend_fields',
                     'msplatform.backends.simion.downstream_fields'):
            self.assertIsNone(importlib.util.find_spec(name), name)

    def test_reference_implementation_does_not_export_generic_entry_points(self):
        reference = importlib.import_module('msplatform.recipes.reference')
        workflow = importlib.import_module('msplatform.workflows.reference_tracing')
        for name in ('SimulationRecipe', 'load_recipe', 'validate_recipe'):
            self.assertFalse(hasattr(reference, name), name)
        for name in ('run_recipe', 'inspect_results', 'validate_recipe'):
            self.assertFalse(hasattr(workflow, name), name)

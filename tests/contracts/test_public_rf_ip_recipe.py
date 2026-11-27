"""Actual RF-IP Assembly author compilation; no SIMION execution."""
from pathlib import Path
import tempfile
import unittest

from msplatform.recipes import load_recipe, validate_recipe
from msplatform.workflows.native_tracing import compile_simion_model
from tests.contracts.test_support.rf_ip_native_recipe import write_rf_ip_recipe_fixture


class PublicRfIpRecipeTests(unittest.TestCase):
    def test_real_rf_ip_author_frozen_environment_and_complete_model(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);author=write_rf_ip_recipe_fixture(root)
            resolved=load_recipe(author).to_dict()
            model=compile_simion_model(resolved).document
            self.assertEqual(model['geometry']['frontend_geometry']['role'],'simion_rf_ip_geometry')
            self.assertEqual(len(resolved['gas_data']['fields']),2)
            self.assertEqual(resolved['gas_data']['fields'][1]['uniform_state']['pressure_pa'],4.)
            (root/'environment.json').write_bytes(b'changed')
            self.assertEqual(validate_recipe(resolved)['recipe_id'],resolved['recipe_id'])
            with self.assertRaisesRegex(ValueError,'environment_record differs'):
                load_recipe(author)

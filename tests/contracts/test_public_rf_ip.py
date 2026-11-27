"""RF-IP public preflight preserves the original-birth contract."""
import tempfile
import unittest
from pathlib import Path

from msplatform.recipes import load_recipe
from msplatform.workflows.native_tracing import _assembly, _flight_request, _realizations, preflight_native
from tests.contracts.test_support.rf_ip_native_recipe import write_rf_ip_recipe_fixture


class PublicRfIpTests(unittest.TestCase):
    def test_original_birth_contract_and_scientific_preflight(self):
        with tempfile.TemporaryDirectory() as temporary:
            recipe = load_recipe(write_rf_ip_recipe_fixture(Path(temporary))).to_dict()
            instrument = _assembly(recipe)
            particles = _realizations(recipe["study"]["document"]["release"])[0]
            propagation, observations = _flight_request(recipe, instrument, particles)
            self.assertEqual(propagation["publication_contract"], "original_birth_si_v1")
            self.assertEqual(propagation["scope"], "continuous_assembly")
            self.assertEqual(observations["plane_observations"], [])
            report = preflight_native(recipe)
            self.assertTrue(report["implemented"])
            self.assertFalse(report["native_verified"])
            self.assertEqual(report["verification_scope"], "scientific_compilation_only")

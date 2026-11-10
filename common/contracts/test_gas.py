"""Neutral gas input and ideal-gas dimensional checks; no supplier execution."""
from dataclasses import replace
import math
import unittest
from msplatform.contracts.gas import (AxisymmetricRZData, BoxDomain, CollisionSpec,
    GasFieldSpec, GasSample, GasSource, GasSpecies, GasState, UnboundedDomain)
from msplatform.gas.thermodynamics import number_density_m3, mass_density_kg_m3


class GasContractTests(unittest.TestCase):
    def test_explicit_vacuum_and_unavailable_are_not_gas(self):
        self.assertEqual(GasState("vacuum", 0).pressure_pa, 0)
        for status in ("solid", "outside_domain", "no_data"):
            self.assertIsNone(GasState(status).pressure_pa)
            with self.assertRaises(ValueError):
                GasState(status, 0)
        with self.assertRaises(ValueError):
            GasState("gas", 0, 300, (0, 0, 0))

    def test_thermodynamic_and_vector_nonfinite_inputs_reject(self):
        for bad in (float("nan"), float("inf"), -float("inf"), -1, True):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    GasState("gas", bad, 300, (0, 0, 0))
        for bad in (0, -1, float("nan")):
            with self.assertRaises(ValueError):
                GasState("gas", 1, bad, (0, 0, 0))
        with self.assertRaises(ValueError):
            GasState("gas", 1, 300, (0, float("inf"), 0))

    def test_ideal_gas_units_and_mixture_mass_are_explicit(self):
        # Independent high-precision decimal oracle from the V8.3 design vectors.
        n = number_density_m3(400, 300)
        self.assertAlmostEqual(n / 9.657294021386560475e22, 1, places=14)
        rho = mass_density_kg_m3(n, (GasSpecies("N2", 28, 1),))
        self.assertAlmostEqual(rho, 0.0044901679200434, places=16)
        mixed = (GasSpecies("He", 4, .5), GasSpecies("Ar", 40, .5))
        self.assertAlmostEqual(mass_density_kg_m3(n, mixed)/rho, 22/28, places=14)
        self.assertEqual(number_density_m3(0, 300), 0)
        for p, t in ((-1, 300), (1, 0), (1, math.inf)):
            with self.assertRaises(ValueError):
                number_density_m3(p, t)

    def test_only_static_fields_and_normalized_composition_are_supported(self):
        spec = GasFieldSpec("bath", "local", "uniform", "n2", (GasSpecies("N2", 28, 1),),
                            UnboundedDomain(), GasSource("prescribed", "explicit_input", ()), GasState("gas", 1, 300, (0, 0, 0)))
        with self.assertRaisesRegex(ValueError, "only static"):
            replace(spec, time_basis="time_series")
        with self.assertRaises(ValueError):
            replace(spec, composition=(GasSpecies("N2", 28, .5),))
        with self.assertRaises(ValueError):
            replace(spec, composition=(GasSpecies("N2", 28, .5), GasSpecies("N2", 28, .5)))
        with self.assertRaises(ValueError):
            replace(spec, domain=None)

    def test_collision_models_do_not_translate_each_others_parameters(self):
        self.assertEqual(CollisionSpec("none", "actual_nonzero_field", None).model, "none")
        self.assertEqual(CollisionSpec("hs1", "bath", "per_global_particle_seed_v1", 2.27e-18, "from_cross_section", collision_seed=42).model, "hs1")
        self.assertEqual(CollisionSpec("sds", "bath", "per_run", gas_mass_amu=28.0134, gas_diameter_nm=.364, diffusion_enabled=True, collision_seed=20260908).model, "sds")
        with self.assertRaises(ValueError):
            CollisionSpec("hs1", "bath", "per_id", 2.27e-18, "from_cross_section", gas_diameter_nm=.364, collision_seed=42)
        with self.assertRaises(ValueError):
            CollisionSpec("sds", "bath", "per_run", cross_section_m2=1e-18, gas_mass_amu=28, gas_diameter_nm=.3, diffusion_enabled=True, collision_seed=42)
        with self.assertRaises(ValueError):
            CollisionSpec("unknown", "bath", "per_run")

    def test_grid_requires_real_monotone_axes_and_explicit_missing_mask(self):
        good = AxisymmetricRZData((0, 1), (0, 1), (True,)*4, (1,)*4, (300,)*4, (0,)*4, (100,)*4)
        self.assertEqual(len(good.pressure_pa), 4)
        for change in ({"r_values_mm": (0, 0)}, {"pressure_pa": (1,)},
                       {"fluid_mask": (True, True, True, False)},
                       {"r_values_mm": (0, 1e-10, 0)},
                       {"pressure_pa": (1, 1, 1, math.inf)}):
            with self.subTest(change=change):
                with self.assertRaises(ValueError):
                    replace(good, **change)

    def test_box_endpoint_policy_is_explicit_and_immutable(self):
        minimum = [0, 0, 0]
        domain = BoxDomain(minimum, (1, 1, 1), (True,)*3, (False,)*3)
        minimum[0] = 99
        self.assertEqual(domain.minimum_mm, (0, 0, 0))
        with self.assertRaises(ValueError):
            BoxDomain((0, 0, 0), (1, 1, 1), (1, 1, 1), (False,)*3)

    def test_sample_status_does_not_accept_fabricated_density(self):
        with self.assertRaises(ValueError):
            GasSample(GasState("no_data"), "local", None, "n2", 0)
        with self.assertRaises(ValueError):
            GasSample(GasState("gas", 1, 300, (0, 0, 0)), "local", None, "n2", math.inf)
        with self.assertRaises(ValueError):
            number_density_m3(1e308, 1e-308)

    def test_collision_seed_is_explicit_and_separate_from_any_source_seed(self):
        for seed in (None, -1, True, 1.5):
            with self.assertRaises(ValueError):
                CollisionSpec("hs1", "bath", "per_global_particle_seed_v1", 2.27e-18,
                              "from_cross_section", collision_seed=seed)

    def test_source_kind_and_proxy_assumptions_survive_independent_field_use(self):
        assumptions = ["upstream collisions omitted; not measured vacuum"]
        source = GasSource("prescribed_proxy", "upstream_control", assumptions)
        assumptions[0] = "changed by caller"
        self.assertEqual(source.assumptions, ("upstream collisions omitted; not measured vacuum",))
        with self.assertRaisesRegex(ValueError, "approximation assumptions"):
            GasSource("prescribed_proxy", "unexplained_zero", ())
        with self.assertRaises(ValueError):
            GasSource("unknown", "input", ())

    def test_published_source_keeps_existing_record_identity_without_file_access(self):
        from unittest.mock import patch
        record = dict(path="explicit/producer/manifest.json", exists=True, bytes=7, sha256="A"*64)
        record["producer_metadata"] = {"mutable": ["outside identity"]}
        with patch("pathlib.Path.open", side_effect=AssertionError("no IO")), patch("pathlib.Path.resolve", side_effect=AssertionError("no discovery")), patch("hashlib.sha256", side_effect=AssertionError("no hash")):
            source = GasSource("published_cfd", "producer_v1", (), record)
        record["bytes"] = 99
        record["producer_metadata"]["mutable"].append("changed")
        self.assertNotIn("producer_metadata", source.reference)
        self.assertEqual(dict(source.reference), dict(path="explicit/producer/manifest.json", exists=True, bytes=7, sha256="A"*64))
        with self.assertRaises(TypeError):
            source.reference["bytes"] = 99
        with self.assertRaises(ValueError):
            GasSource("published_cfd", "producer_v1", ())
        with self.assertRaises(ValueError):
            GasSource("published_cfd", "producer_v1", (), dict(path="x",exists=True,bytes=True,sha256="A"*64))

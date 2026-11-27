"""Versioned shared gas and electron data preserve dimensional identities."""

import unittest

from msplatform.physics import CONSTANTS, ELECTRON_CONSTANTS, GasEnvironment, HS1_EXAMPLE_ASSUMPTION, NITROGEN
from msplatform.contracts.gas import BoxDomain, GasFieldSpec, GasRegion, GasSource, GasSpecies, GasState
from msplatform.contracts.gas_species import (
    project_nitrogen_hs1_assumption,
    resolve_hs1_example_assumption,
    resolve_nitrogen,
)


class SpeciesDataTests(unittest.TestCase):
    def test_nitrogen_views_derive_from_one_mass_and_diameter(self):
        self.assertEqual(NITROGEN["species_id"], "n2")
        self.assertEqual(NITROGEN["mass_amu"], 28.0134)
        self.assertEqual(NITROGEN["effective_hard_sphere_diameter_m"], 3.64e-10)
        self.assertEqual(NITROGEN["effective_hard_sphere_diameter_nm"], 3.64e-10 * 1e9)
        self.assertEqual(NITROGEN["molar_mass_kg_per_mol"],
                         NITROGEN["mass_amu"] * CONSTANTS["atomic_mass_constant_kg"] * 6.02214076e23)

    def test_electron_is_derived_using_the_frozen_mass_unit(self):
        self.assertEqual(ELECTRON_CONSTANTS["mass_u"],
                         ELECTRON_CONSTANTS["mass_kg"] / CONSTANTS["atomic_mass_constant_kg"])
        self.assertEqual(ELECTRON_CONSTANTS["atomic_mass_constant_version"], CONSTANTS["version"])

    def test_hs1_example_is_an_explicit_uncalibrated_pair_assumption(self):
        self.assertEqual(HS1_EXAMPLE_ASSUMPTION["cross_section_m2"], 2.27e-18)
        self.assertEqual(HS1_EXAMPLE_ASSUMPTION["qualification"], "uncalibrated_assumption")
        self.assertIn("not a measurement or calibration for nitrogen", HS1_EXAMPLE_ASSUMPTION["limitation"])

    def test_references_do_not_admit_old_values_or_unknown_versions(self):
        species = {"species_id": "n2", "version": NITROGEN["version"]}
        model = {"model_id": HS1_EXAMPLE_ASSUMPTION["model_id"], "version": HS1_EXAMPLE_ASSUMPTION["version"]}
        self.assertEqual(resolve_nitrogen(species), NITROGEN)
        self.assertEqual(resolve_hs1_example_assumption(model), HS1_EXAMPLE_ASSUMPTION)
        projection = project_nitrogen_hs1_assumption(species, model)
        self.assertEqual(projection["gas_mass_amu"], 28.0134)
        self.assertEqual(projection["cross_section_m2"], 2.27e-18)
        self.assertEqual(projection["collision_assumption"]["qualification"], "uncalibrated_assumption")
        for bad in ({**species, "mass_amu": 28}, {**species, "version": "old"}, {}):
            with self.subTest(reference=bad), self.assertRaises(ValueError):
                resolve_nitrogen(bad)
        with self.assertRaises(ValueError):
            resolve_hs1_example_assumption({**model, "cross_section_m2": 2.27e-18})

    def test_environment_freezes_one_field_and_model_without_duplicate_conditions(self):
        field = GasFieldSpec(
            field_id="bath", frame_id="local", representation="uniform", composition_id="n2",
            composition=(GasSpecies("n2", NITROGEN["mass_amu"], 1),),
            domain=BoxDomain((0, 0, 0), (1, 1, 1), (True,) * 3, (True,) * 3),
            source=GasSource("prescribed", "experiment", ()),
            uniform_state=GasState("gas", 1, 300, (0, 0, 0)),
        )
        ref = {"gas_field_id": "bath", "model_id": HS1_EXAMPLE_ASSUMPTION["model_id"],
               "version": HS1_EXAMPLE_ASSUMPTION["version"]}
        environment = GasEnvironment("gas", (field,), (ref,))
        ref["model_id"] = "forged"
        frozen = environment.to_dict()
        self.assertEqual(GasEnvironment.from_dict(frozen), environment)
        self.assertEqual(frozen["fields"][0]["uniform_state"]["pressure_pa"], 1)
        self.assertEqual(frozen["collision_models"][0]["data"]["qualification"], "uncalibrated_assumption")
        self.assertEqual(frozen["species_data"][0]["dataset_sha256"], NITROGEN["dataset_sha256"])
        frozen["species_data"][0]["mass_amu"] = 28
        with self.assertRaises(ValueError):
            GasEnvironment.from_dict(frozen)
        with self.assertRaises(ValueError):
            GasEnvironment("gas", (field,), (ref,))
        with self.assertRaises(ValueError):
            GasEnvironment("vacuum", (field,), ())

    def test_two_pressure_regions_round_trip_without_collapsing_conditions(self):
        domain = BoxDomain((0, -1, -1), (3, 1, 1), (True,) * 3, (True,) * 3)
        regions = tuple(GasRegion(name, BoxDomain((low, -1, -1), (high, 1, 1),
                                                   (True,) * 3, (False,) * 3),
                                  GasState("gas", pressure, 300, (0, 0, 0)))
                        for name, low, high, pressure in (("hp", 0, 1, 1), ("lp", 1, 3, 0.2)))
        field = GasFieldSpec(
            field_id="bath", frame_id="local", representation="piecewise_uniform", composition_id="n2",
            composition=(GasSpecies("n2", NITROGEN["mass_amu"], 1),), domain=domain,
            source=GasSource("prescribed_proxy", "experiment", ("not measured",)),
            regions=regions, background_state=GasState("vacuum", 0, 300, (0, 0, 0)),
        )
        ref = {"gas_field_id": "bath", "model_id": HS1_EXAMPLE_ASSUMPTION["model_id"],
               "version": HS1_EXAMPLE_ASSUMPTION["version"]}
        frozen = GasEnvironment("gas", (field,), (ref,)).to_dict()
        self.assertEqual([r["state"]["pressure_pa"] for r in frozen["fields"][0]["regions"]], [1, 0.2])
        self.assertEqual(GasEnvironment.from_dict(frozen).to_dict(), frozen)


if __name__ == "__main__":
    unittest.main()

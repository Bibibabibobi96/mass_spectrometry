"""The split native example preserves its explicit source and physical inputs."""
import unittest
import tempfile
import hashlib
from pathlib import Path

from msplatform import components, examples
from msplatform.components.single_reflection_oa_tof.accelerator_geometry import (
    apply_side_opening, resolve_accelerator_geometry, resolve_oa_provider,
)
from msplatform.ion_release.release import generate_release_states, materialize_release, validate_materialized_release
from msplatform.contracts.particle_physics import kinetic_energy_ev
from msplatform.recipes import load_recipe, validate_recipe
from msplatform.backends.simion.compiler import compile_geometry
from msplatform.backends.simion.model import compile_prepared_model
from msplatform.backends.simion.field_execution import plan_fields_execution
from msplatform.ion_release.dotnet_gaussian_box_ion11 import generate_ion_source


class SplitNativeExampleTests(unittest.TestCase):
    def test_rf_split_study_compiles_with_frozen_physics_and_birth_prefix(self):
        root = Path(__file__).resolve().parents[2] / "src/msplatform/examples"
        loaded = load_recipe(root / "rf_split_oatof_native_small_v1.toml").to_dict()
        self.assertEqual(validate_recipe(loaded), loaded)
        study = loaded["study"]["document"]
        original = examples.load_example("rf_oatof_functional_v1")
        old = components.resolve_component(original.component_requests["oatof"]).resolved_design
        projection = apply_side_opening(resolve_accelerator_geometry(old, variant_id="three_zone_square"),
                                        side_opening=old["mechanical_side_opening"])
        oa = resolve_oa_provider(old, projection=projection, geometry_profile_id=None)
        volts = oa["electrical"]["operating_voltages_v"]
        for group in ("repeller", "intermediate_grid_1", "intermediate_grid_2", "exit_grid"):
            self.assertEqual(study["drive"]["groups"]["oa"][group]["on_voltage_v"], volts[group])
        self.assertEqual(study["drive"]["pulse"], original.drive["pulse"])
        self.assertEqual(study["drive"]["clock"], original.drive["clock"])
        original_spec = original.release["release_spec"]
        small_spec = study["release"]["release_spec"]
        self.assertEqual(generate_release_states(small_spec), generate_release_states(original_spec)[:3])
        self.assertEqual(study["release"]["source_component_id"], "multipole")
        self.assertEqual(loaded["assembly"]["name"], "rf_multipole__orthogonal_accelerator__single_reflection_tof")
        self.assertEqual(loaded["assembly"]["composition_plan"]["scope"]["containment_ids"], ["oa_in_flight_tube"])

    def test_both_examples_reach_field_plan_and_box_retains_ion11_inputs(self):
        root = Path(__file__).resolve().parents[2] / "src/msplatform/examples"
        for name in ("rf_split_oatof_native_small_v1", "oa_split_tof_native_small_v1"):
            with self.subTest(example=name):
                result = load_recipe(root / (name + ".toml")).to_dict()
                study, assembly = result["study"]["document"], result["assembly"]
                compiled = compile_geometry({"composition_plan": assembly["composition_plan"],
                    "components_resolved": assembly["components_resolved"]}, numerics=study["numerics"]["geometry"])
                model = compile_prepared_model(compiled, assembly["components_resolved"],
                    drive={"groups": study["drive"]["groups"], "pulse": study["drive"]["pulse"],
                           "clock": {**study["drive"]["clock"], **study["release"]["clock"]}},
                    physics=study["physics"])
                plan = plan_fields_execution(model, numerics=study["numerics"]["fields"])
                self.assertIn("downstream_fields", plan["expected_operation_ids"])
        spec = study["release"]["release_spec"]
        g, sample, species = spec["geometry"], spec["sampling"], spec["species"]
        lines = generate_ion_source(particle_count=1000, mass_amu=species["mass_amu"], charge=species["charge_state"],
            energy_mean_ev=sample["energy_mean_ev"], energy_std_ev=sample["energy_std_ev"],
            half_width_xyz_mm=tuple(g["half_width_mm"]), center_xyz_mm=tuple(g["center_mm"]), seed=sample["seed"])
        self.assertEqual(hashlib.sha256(("\r\n".join(lines[:3]) + "\r\n").encode("ascii")).hexdigest(),
                         "47dead2ebc4d21dfd87244bbc3c24baa1ea22ecdd0e63f16d620594c5cb5a757")
        states = generate_release_states(spec)
        for state, line in zip(states, lines[:3], strict=True):
            fields = line.split(",")
            self.assertEqual([state["x_mm"], state["y_mm"], state["z_mm"]], [float(x) for x in fields[3:6]])
            self.assertEqual(state["mass_amu"], float(fields[1]))
            self.assertAlmostEqual(kinetic_energy_ev(state["mass_amu"], state["vx_m_s"], 0, 0), float(fields[8]))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            materialize_release(spec, path / "states.csv", path / "receipt.json")
            self.assertEqual(validate_materialized_release(path / "receipt.json")["particle_count"], 3)
            (path / "states.csv").write_text("tampered", encoding="utf-8")
            with self.assertRaises(ValueError):
                validate_materialized_release(path / "receipt.json")


if __name__ == "__main__":
    unittest.main()

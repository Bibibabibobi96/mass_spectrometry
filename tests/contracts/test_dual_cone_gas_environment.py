"""Dual-cone conditions resolve from one author and actual geometry."""
import copy
import json
from pathlib import Path
import unittest

from msplatform.components.dual_cone_tandem_quadrupole.gas_environment import (
    project_dual_cone_flow_science, project_dual_cone_transport_science, require_sds_positive_ion,
    resolve_dual_cone_conditions,
)

CONFIG = Path(__file__).resolve().parents[2] / "src/msplatform/components/dual_cone_tandem_quadrupole/config"


class DualConeEnvironmentTests(unittest.TestCase):
    def test_conditions_bind_one_nitrogen_and_selected_aperture(self):
        author, geometry = (json.loads((CONFIG / name).read_text(encoding="utf-8"))
                            for name in ("gas_environment.json", "resolved_geometry.json"))
        result = resolve_dual_cone_conditions(author, geometry)
        self.assertEqual((result["inlet_pressure_pa"], result["outlet_pressure_pa"], result["temperature_k"]),
                         (101325, 400, 300))
        self.assertEqual((result["rear_start_z_mm"], result["rear_axial_velocity_m_per_s"]), (3, 100))
        self.assertEqual(result["species_data"]["mass_amu"], 28.0134)
        self.assertEqual(result["species_data"]["effective_hard_sphere_diameter_nm"], 0.364)
        changed = copy.deepcopy(geometry)
        changed["geometry_mm"]["second_cone"]["aperture_reference_z_mm"] = 4
        self.assertEqual(resolve_dual_cone_conditions(author, changed)["rear_start_z_mm"], 4)
        bad = copy.deepcopy(author)
        bad["uniform_rear"]["pressure_ref"] = "other"
        with self.assertRaises(ValueError):
            resolve_dual_cone_conditions(bad, geometry)

    def test_flow_and_sds_views_use_same_data_and_reject_duplicate_inputs(self):
        author, geometry, flow, transport = (json.loads((CONFIG / name).read_text(encoding="utf-8"))
            for name in ("gas_environment.json", "resolved_geometry.json", "gas_flow_science.json", "ion_transport_science.json"))
        conditions = resolve_dual_cone_conditions(author, geometry)
        native_flow = project_dual_cone_flow_science(flow, conditions)
        native_sds = project_dual_cone_transport_science(transport, conditions)
        self.assertEqual(native_flow["continuum_scope"]["n2_molecular_collision_diameter_m"], 3.64e-10)
        self.assertEqual(native_sds["gas"]["collision_gas_diameter_nm"], 0.364)
        self.assertEqual(native_sds["gas"]["collision_gas_mass_amu"], conditions["species_data"]["mass_amu"])
        self.assertEqual(native_flow["physics"]["gas_species"]["molar_mass_kg_per_mol"], conditions["species_data"]["molar_mass_kg_per_mol"])
        self.assertEqual(native_flow["gas_environment_identity"]["species_sha256"], native_sds["gas_environment_identity"]["species_sha256"])
        self.assertEqual(native_flow["physics"]["transport_model"]["dynamic_viscosity_pa_s"], 1.76e-5)
        self.assertEqual(native_flow["physics"]["gas_species"]["specific_heat_capacity_cp_j_per_kg_k"], 1039.0)
        self.assertIn("other temperatures is unqualified", native_flow["gas_environment_identity"]["transport_limitation"])
        flow["physics"]["gas_species"]["molar_mass_kg_per_mol"] = 0.028
        with self.assertRaises(ValueError):
            project_dual_cone_flow_science(flow, conditions)
        forged = copy.deepcopy(conditions)
        forged["species_data"]["mass_amu"] = 28
        with self.assertRaises(ValueError):
            project_dual_cone_transport_science(transport, forged)

    def test_comsol_request_binds_environment_and_material_versions(self):
        from msplatform.backends.comsol.gas_flow import resolve_gas_flow_request

        request = resolve_gas_flow_request(*(CONFIG / name for name in (
            "baseline.json", "resolved_geometry.json", "gas_flow_science.json", "comsol_solver_numerics.json", "gas_environment.json")))
        self.assertTrue({"environment", "species_data", "constants_data"} <= set(request["inputs"]))
        science = request["projected_science"]
        self.assertEqual(science["continuum_scope"]["n2_molecular_collision_diameter_m"], 3.64e-10)
        self.assertEqual(science["boundary_conditions"]["inlet"]["static_pressure_pa"], 101325)
        self.assertEqual(science["boundary_conditions"]["outlet"]["static_pressure_pa"], 400)

    def test_sds_does_not_admit_negative_ions_or_electrons(self):
        require_sds_positive_ion({"species": {"species_kind": "ion", "charge_state": 1}})
        for species in ({"species_kind": "ion", "charge_state": -1},
                        {"species_kind": "electron", "charge_state": -1},
                        {"charge_state": 1}):
            with self.subTest(species=species), self.assertRaises(ValueError):
                require_sds_positive_ion({"species": species})


if __name__ == "__main__":
    unittest.main()

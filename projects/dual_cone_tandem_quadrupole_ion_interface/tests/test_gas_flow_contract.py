from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import math
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCIENCE_PATH = PROJECT_ROOT / "config" / "gas_flow_science.json"
NUMERICS_PATH = PROJECT_ROOT / "config" / "comsol_solver_numerics.json"
GEOMETRY_PATH = PROJECT_ROOT / "config" / "resolved_geometry.json"
BUILDER_PATH = PROJECT_ROOT / "comsol" / "build_and_solve_axisymmetric_gas_flow.m"
RUNNER_PATH = PROJECT_ROOT / "comsol" / "run_axisymmetric_gas_flow.m"
INTERFACE_PATH = PROJECT_ROOT / "config" / "gas_field_interface.json"


def _load_validator():
    path = PROJECT_ROOT / "analysis" / "validate_gas_field.py"
    spec = importlib.util.spec_from_file_location("validate_gas_field", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_exporter():
    path = PROJECT_ROOT / "analysis" / "export_simion_gas_runtime.py"
    spec = importlib.util.spec_from_file_location("export_simion_gas_runtime", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _contracts() -> tuple[dict, dict]:
    return (
        json.loads(SCIENCE_PATH.read_text(encoding="utf-8")),
        json.loads(NUMERICS_PATH.read_text(encoding="utf-8")),
    )


def _write_fixture(tmp_path: Path) -> tuple[Path, Path]:
    science, numerics = _contracts()
    columns = science["export_contract"]["columns"]
    r_values = [float(index) for index in range(10)]
    z_values = [float(index) for index in range(10)]
    gas = science["physics"]["gas_species"]
    pressure = 500.0
    temperature = 300.0
    density = pressure * gas["molar_mass_kg_per_mol"] / (
        gas["universal_gas_constant_j_per_mol_k"] * temperature
    )
    csv_path = tmp_path / numerics["artifact_names"]["field_csv"]
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for z_index, z_mm in enumerate(z_values):
            for r_index, r_mm in enumerate(r_values):
                writer.writerow(
                    {
                        "z_index": z_index,
                        "r_index": r_index,
                        "z_mm": z_mm,
                        "r_mm": r_mm,
                        "p_pa": pressure,
                        "temperature_k": temperature,
                        "u_z_m_per_s": 20.0,
                        "u_r_m_per_s": 0.0,
                        "rho_kg_per_m3": f"{density:.17g}",
                        "mach": 0.06,
                        "knudsen_aperture": 0.02,
                        "fluid_mask": 1,
                    }
                )
    metadata = {
        "schema_version": 1,
        "role": "dual_cone_axisymmetric_gas_field_metadata",
        "project_id": science["project_id"],
        "model_id": science["model_id"],
        "claim_scope": science["claim_scope"],
        "field_schema_id": science["export_contract"]["schema_id"],
        "coordinate_order": science["export_contract"]["coordinate_order"],
        "row_count": len(r_values) * len(z_values),
        "grid": {"r_values_mm": r_values, "z_values_mm": z_values},
        "field_csv_sha256": hashlib.sha256(csv_path.read_bytes()).hexdigest(),
        "source_contract_sha256": {
            "gas_flow_science": hashlib.sha256(SCIENCE_PATH.read_bytes()).hexdigest(),
            "comsol_solver_numerics": hashlib.sha256(
                NUMERICS_PATH.read_bytes()
            ).hexdigest(),
            "resolved_geometry": hashlib.sha256(GEOMETRY_PATH.read_bytes()).hexdigest(),
        },
        "solution_summary": {
            "requested_outlet_static_pressure_pa": science["boundary_conditions"][
                "outlet"
            ]["static_pressure_pa"],
            "accepted_isotropic_diffusion": numerics["study"][
                "accepted_terminal_isotropic_diffusion"
            ],
            "mass_balance_relative_error": 0.001,
        },
    }
    metadata_path = tmp_path / numerics["artifact_names"]["field_metadata"]
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    return csv_path, metadata_path


class GasFlowContractTests(unittest.TestCase):
    def test_contract_declares_choked_flow_risk_and_regular_export(self) -> None:
        science, numerics = _contracts()
        self.assertEqual(science["physics"]["comsol_interface"], "HighMachNumberFlow")
        inlet = science["boundary_conditions"]["inlet"]["static_pressure_pa"]
        outlet = science["boundary_conditions"]["outlet"]["static_pressure_pa"]
        gamma = science["physics"]["gas_species"]["specific_heat_ratio"]
        critical_ratio = (2.0 / (gamma + 1.0)) ** (gamma / (gamma - 1.0))
        self.assertLess(outlet / inlet, critical_ratio)
        self.assertEqual(
            science["boundary_conditions"]["inlet"]["velocity_basis"],
            "computed_by_the_internal_solution_not_prescribed",
        )
        self.assertGreater(science["geometry_proxy"]["upstream_plenum_radius_mm"], 1.0)
        self.assertTrue(science["geometry_proxy"]["excluded_geometry"])
        self.assertIn(
            "downstream_aperture_plate_gas_flow_obstruction",
            science["geometry_proxy"]["excluded_geometry"],
        )
        self.assertEqual(
            science["export_contract"]["coordinate_order"],
            "z_major_then_r_minor",
        )
        continuation = numerics["study"]["outlet_pressure_continuation_pa"]
        self.assertEqual(continuation[-1], outlet)
        self.assertTrue(all(a >= b for a, b in zip(continuation, continuation[1:])))
        diffusion = numerics["study"]["isotropic_diffusion_continuation"]
        self.assertEqual(len(continuation), len(diffusion))
        self.assertEqual(
            diffusion[-1], numerics["study"]["accepted_terminal_isotropic_diffusion"]
        )
        self.assertTrue(numerics["solver"]["adaptive_step_tolerance"])
        self.assertEqual(
            numerics["solver"]["linear_solver"], "comsol_iterative_multigrid_i1"
        )
        self.assertEqual(numerics["solver"]["termination"], "tolerance")
        self.assertEqual(numerics["solver"]["cfl_comparison_tolerance"], 0.1)
        self.assertLess(numerics["study"]["initial_axial_velocity_m_per_s"], 300.0)
        self.assertGreater(
            numerics["solver"]["iteration_lower_limits"]["temperature_k"], 0.0
        )
        self.assertGreater(
            numerics["solver"]["iteration_lower_limits"]["pressure_pa"], 0.0
        )
        self.assertEqual(outlet, 400.0)
        self.assertEqual(science["physics"]["gas_species"]["species_id"], "n2")
        geometry = json.loads(GEOMETRY_PATH.read_text(encoding="utf-8"))["geometry_mm"]
        self.assertEqual(
            geometry["downstream_aperture_plate"]["downstream_observation_end_z_mm"],
            120.0,
        )

    def test_valid_field_fixture_passes_fail_closed_validator(self) -> None:
        validator = _load_validator()
        with tempfile.TemporaryDirectory() as directory:
            csv_path, metadata_path = _write_fixture(Path(directory))
            summary = validator.validate_gas_field(
                csv_path, metadata_path, SCIENCE_PATH, NUMERICS_PATH
            )
        self.assertEqual(summary["status"], "PASS")
        self.assertEqual(summary["row_count"], 100)
        self.assertTrue(summary["quantitative_continuum_claim_allowed"])

    def test_tampered_field_is_rejected(self) -> None:
        validator = _load_validator()
        with tempfile.TemporaryDirectory() as directory:
            csv_path, metadata_path = _write_fixture(Path(directory))
            with csv_path.open("a", encoding="utf-8") as stream:
                stream.write("tampered\n")
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                validator.validate_gas_field(
                    csv_path, metadata_path, SCIENCE_PATH, NUMERICS_PATH
                )

    def test_valid_field_compiles_to_hashed_self_contained_lua(self) -> None:
        exporter = _load_exporter()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            csv_path, metadata_path = _write_fixture(root)
            interface = json.loads(INTERFACE_PATH.read_text(encoding="utf-8"))
            interface["runtime_artifact_contract"]["domain"] = {
                "minimum_z_mm": 0.0,
                "maximum_z_mm": 9.0,
                "minimum_radius_mm": 0.0,
                "maximum_radius_mm": 9.0,
            }
            interface_path = root / "interface.json"
            interface_path.write_text(json.dumps(interface), encoding="utf-8")
            lua_path = root / "gas_field_runtime.lua"
            manifest_path = root / "gas_field_manifest.json"
            manifest = exporter.export_runtime(
                csv_path,
                metadata_path,
                lua_path,
                manifest_path,
                SCIENCE_PATH,
                NUMERICS_PATH,
                GEOMETRY_PATH,
                interface_path,
            )
            self.assertEqual(manifest["role"], "dual_cone_gas_field_export")
            self.assertRegex(manifest["runtime_lua"]["sha256"], r"^[0-9a-f]{64}$")
            self.assertEqual(manifest["source"]["kind"], "validated_comsol_axisymmetric_rz")
            self.assertEqual(
                manifest["source"]["field_csv"]["sha256"],
                hashlib.sha256(csv_path.read_bytes()).hexdigest(),
            )
            self.assertEqual(
                manifest["source"]["source_contract_sha256"],
                json.loads(metadata_path.read_text(encoding="utf-8"))["source_contract_sha256"],
            )
            source = lua_path.read_text(encoding="utf-8")
            self.assertIn("local chunk_size=8192", source)
            self.assertIn("local function value(a,i)", source)
            self.assertIn("field.pressure_pa = function", source)
            self.assertIn("field.velocity_m_s = function", source)

    def test_matlab_source_has_high_mach_and_fail_closed_contract(self) -> None:
        builder = BUILDER_PATH.read_text(encoding="utf-8")
        runner = RUNNER_PATH.read_text(encoding="utf-8")
        for token in (
            '"HighMachNumberFlow"',
            "axisymmetric(true)",
            'geom.create("poly_fluid", "Polygon")',
            '"gas_flow_science.json"',
            '"comsol_solver_numerics.json"',
            'study.create("stat", "Stationary")',
            'inlet.set("FlowCondition", "Subsonic")',
            'inlet.set("BoundaryCondition", "Pressure")',
            'inlet.set("p0", "p_in")',
            'inlet.set("TemperatureHeatflux", "Temperature")',
            'inlet.set("T0", "T_in")',
            'outlet.set("FlowCondition", "Subsonic")',
            'outlet.set("BoundaryCondition", "Pressure")',
            'outlet.set("p0", "p_out")',
            'wall.set("BoundaryCondition", "NoSlip")',
            'stationarySolver.create("se1", "Segregated")',
            'segregated.create("ll1", "LowerLimit")',
            'segregated.set("segstabacc", "segcflcmp")',
            'segregated.feature("ss1").set("linsolver", "i1")',
            'segregated.feature("ss1").set("subadapttol", n.solver.adaptive_step_tolerance)',
            'segregated.set("segterm", "tol")',
            'model.sol("sol1").getPVals()',
            'DUAL_CONE_GAS_FLOW_RESUME_MODEL',
            'VariableNames=cellstr(string(science.export_contract.columns))',
            '"GasFlow:ContinuationTerminalState"',
            'hmnf.prop("InconsistentStabilization")',
            'stationary.set("sweeptype", "sparse")',
            'diffusionContinuation(end) ~= terminalDiffusion',
            '{"p", "T", "w", "u"}',
            "))*w",
            '"GasFlow:LowerLimitActive"',
            "mphinterp",
            '"solnum", "end"',
            "mass_balance_relative_error",
            "g.downstream_aperture_plate.downstream_observation_end_z_mm",
        ):
            self.assertIn(token, builder)
        self.assertNotIn('geom.create("poly_upstream", "Polygon")', builder)
        self.assertNotIn('geom.create("poly_downstream", "Polygon")', builder)
        self.assertNotIn('geom.create("uni_fluid", "Union")', builder)
        self.assertNotIn('inlet.set("Ma0"', builder)
        self.assertIn("STATUS=PASS", runner)
        self.assertIn("STATUS=FAIL", runner)
        self.assertIn("STATUS=RUNNING", runner)
        self.assertIn("rethrow(exception)", runner)
        self.assertNotIn('{"p", "T", "v", "u"}', builder)
        for hidden_physical_value in ("101325", "3.7e-10"):
            self.assertNotIn(hidden_physical_value, builder)

    def test_declared_mean_free_path_constants_are_positive(self) -> None:
        science, _ = _contracts()
        gas = science["physics"]["gas_species"]
        self.assertTrue(math.isfinite(gas["boltzmann_constant_j_per_k"]))
        self.assertGreater(gas["boltzmann_constant_j_per_k"], 0.0)
        self.assertGreater(
            science["continuum_scope"]["n2_molecular_collision_diameter_m"], 0.0
        )


if __name__ == "__main__":
    unittest.main()

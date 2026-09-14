from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from common.contracts.file_identity import file_sha256
from projects.dual_cone_tandem_quadrupole_ion_interface.simion.geometry import (
    DEFAULT_NUMERICS,
    DEFAULT_RESOLVED,
    device_to_workbench_offsets,
    render_gem,
)
from projects.dual_cone_tandem_quadrupole_ion_interface.simion.prepare import (
    GAS_INTERFACE,
    SDS_FILES,
    prepare,
    validate_gas_field_manifest,
)
from projects.dual_cone_tandem_quadrupole_ion_interface.analysis.export_uniform_rear_gas_runtime import (
    export_uniform_runtime,
)
from projects.dual_cone_tandem_quadrupole_ion_interface.analysis.plot_simion_trajectory_projection import (
    axial_reach_profile,
    main as plot_trajectory_projection,
)


PROJECT = Path(__file__).resolve().parents[1]
UNIFORM_RUNNER = PROJECT / "workflows" / "gas_assisted_transport" / "run_uniform_400pa_prototype.ps1"
GAS_FIELD_RUNNER = PROJECT / "workflows" / "gas_assisted_transport" / "run_gas_field_prototype.ps1"
COMSOL_FIELD_RUNNER = (
    PROJECT / "workflows" / "gas_assisted_transport" / "run_comsol_field_prototype.ps1"
)


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class SimionGeometryTests(unittest.TestCase):
    def test_default_diagnostic_axial_reach_counts_unique_ions(self) -> None:
        tracks = {
            1: ([-1.0, 2.0, 6.0], [0.0, 0.1, 0.2]),
            2: ([-1.0, 2.0, 4.0, 1.0], [0.0, 0.2, 0.3, 0.1]),
            3: ([-1.0, 2.0, 6.0], [0.0, 0.1, 0.2]),
        }
        edges, counts = axial_reach_profile(tracks, -2.0, 8.0)
        self.assertEqual(edges, [-2.0, 4.0, 6.0, 8.0])
        self.assertEqual(counts, [3, 2, 0])

    def test_axial_reach_rejects_reversed_or_nonfinite_limits(self) -> None:
        with self.assertRaisesRegex(ValueError, "must exceed"):
            axial_reach_profile({}, 1.0, 1.0)
        with self.assertRaisesRegex(ValueError, "finite"):
            axial_reach_profile({}, float("nan"), 1.0)

    def test_default_diagnostic_renders_three_panel_png(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            trajectory = root / "trajectory.csv"
            final_state = root / "final.csv"
            output = root / "diagnostic.png"
            with trajectory.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(
                    stream, fieldnames=("ion_number", "x_mm", "y_mm", "z_mm")
                )
                writer.writeheader()
                for ion, device_z in ((1, -1.0), (1, 120.0), (2, -1.0), (2, 10.0)):
                    writer.writerow(
                        {
                            "ion_number": ion,
                            "x_mm": 25.5,
                            "y_mm": 25.5,
                            "z_mm": device_z + 2.0,
                        }
                    )
            with final_state.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=("ion_number", "splat"))
                writer.writeheader()
                writer.writerows(
                    ({"ion_number": 1, "splat": 1}, {"ion_number": 2, "splat": 3})
                )
            argv = [
                "plot_simion_trajectory_projection.py",
                "--trajectory",
                str(trajectory),
                "--final-state",
                str(final_state),
                "--output",
                str(output),
            ]
            with mock.patch.object(sys, "argv", argv):
                self.assertEqual(plot_trajectory_projection(), 0)
            self.assertGreater(output.stat().st_size, 10_000)

    def test_gem_uses_shared_rod_renderer_and_distinct_namespaces(self) -> None:
        numerics = load(DEFAULT_NUMERICS)
        gem = render_gem(load(DEFAULT_RESOLVED), numerics)
        for electrode in (1, 2, 3, 11, 12, 21, 22):
            self.assertIn(f"e({electrode})", gem)
        self.assertIn("cylinder(0,0,0,4.3,1.88,49.2)", gem)
        self.assertIn("2.39", gem)
        self.assertIn("110.22", gem)
        self.assertIn("0.75", gem)
        self.assertIn("$(122/mmgu+1)", gem)
        self.assertIn("C0 limitation", gem)
        source = (PROJECT / "simion" / "geometry.py").read_text(encoding="utf-8")
        self.assertIn("render_grouped_rod_array_gem", source)
        self.assertNotIn("def _stage_1_rods", source)
        self.assertEqual(device_to_workbench_offsets(numerics), (25.5, 25.5, 2.0))
        self.assertIn("device_to_workbench_offset_mm", source)

    def test_science_contract_makes_simion_the_only_trajectory_authority(self) -> None:
        science = load(PROJECT / "config" / "ion_transport_science.json")
        self.assertEqual(science["trajectory_authority"], "simion")
        self.assertEqual(science["gas"]["collision_model"], "simion_official_collision_sds")
        self.assertEqual(science["gas"]["species_id"], "n2")

    def test_source_cylinder_can_be_wider_than_the_first_aperture(self) -> None:
        source = load(PROJECT / "config" / "cylindrical_ion_source.json")
        resolved = load(PROJECT / "config" / "resolved_geometry.json")
        gas_science = load(PROJECT / "config" / "gas_flow_science.json")
        radius = source["geometry_mm"]["radius_mm"]
        self.assertEqual(radius, 1.5)
        self.assertGreater(radius, resolved["geometry_mm"]["first_cone"]["aperture_radius_mm"])
        self.assertLess(radius, gas_science["geometry_proxy"]["upstream_plenum_radius_mm"])

    def test_rf_operating_point_uses_confirmed_peak_to_ground_voltage(self) -> None:
        field = load(PROJECT / "config" / "ion_transport_science.json")["electric_field"]
        basis = field["operating_point_basis"]
        self.assertEqual(basis["frequency_range_hz"], [550000.0, 590000.0])
        self.assertEqual(basis["selected_nominal_frequency_hz"], 570000.0)
        self.assertEqual(basis["voltage_interpretation"], "peak_to_ground_per_electrode_group")
        self.assertEqual(basis["opposed_group_voltage_v_peak_to_peak"], 1200.0)
        for name in basis["applies_to"]:
            stage = field[name]
            self.assertEqual(stage["waveform"], "sine")
            self.assertEqual(stage["frequency_hz"], 570000.0)
            self.assertEqual(stage["rf_amplitude_v_zero_to_peak_per_group"], 300.0)

    def test_program_composes_shared_rf_and_official_sds_without_python_tracking(self) -> None:
        program = (PROJECT / "simion" / "programs" / "gas_assisted_transport.lua").read_text(
            encoding="utf-8"
        )
        self.assertIn("loadfile(assert(config.rf_drive_kernel))", program)
        self.assertIn("simion.import(assert(config.collision_sds_lua), 'noinstall')", program)
        self.assertIn("SDS.install()", program)
        self.assertNotIn("adj_electrode", program)
        self.assertIn("adj_elect[id] = voltage", program)
        self.assertIn("apply_at(ion_time_of_flight, set_electrode_voltage)", program)
        self.assertIn("stage_1.timestep_cap_us, stage_2.timestep_cap_us", program)
        self.assertEqual(program.count("function segment.fast_adjust()"), 1)
        self.assertEqual(program.count("function segment.tstep_adjust()"), 1)
        self.assertEqual(program.count("function segment.terminate()"), 1)
        self.assertIn("query_or_boundary_loss", program)
        self.assertIn("terminal_code[ion_number] = 3", program)
        self.assertIn("gas-field query has no fluid support", program)
        self.assertIn("ion_splat = 1", program)
        self.assertIn("emit_final(3)", program)
        self.assertLess(
            program.index("function segment.other_actions()"),
            program.index("terminal_code[ion_number] = 3"),
        )
        self.assertIn("trajectory_samples.csv", (PROJECT / "simion" / "prepare.py").read_text(encoding="utf-8"))

    def test_gas_field_runner_reuses_common_iob_builder_and_real_simion_fly(self) -> None:
        runner = GAS_FIELD_RUNNER.read_text(encoding="utf-8")
        self.assertIn("run_c0_gem_smoke.ps1", runner)
        self.assertIn("build_simion_runtime_iob.lua", runner)
        self.assertIn("--nogui --noprompt fly", runner)
        self.assertIn("SDS_collision_gas_mass_amu", runner)
        self.assertIn("common\\simion\\analyze_terminal_plane.py", runner)
        self.assertIn("terminal_plane_metrics.json", runner)
        self.assertIn("downstream_aperture_plate", runner)
        self.assertIn("electric_field=$science.electric_field", runner)
        self.assertIn("terminal_code_definitions", runner)
        self.assertIn("left validated gas-field fluid support", runner)
        self.assertIn("plot_simion_trajectory_projection.py", runner)
        self.assertIn("prototype_run_report.json", runner)
        self.assertIn("New-RunPackage", runner)
        self.assertIn("Write-VerifiedRunManifest", runner)
        self.assertIn("Complete-FailedRun", runner)
        self.assertIn("Enter-HostExecutionLease -Role SIMION", runner)
        self.assertIn("Invoke-ArtifactCapacityGate", runner)
        self.assertIn("Apply-RunArtifactRetention", runner)
        self.assertNotIn("[string]$OutputDir", runner)

    def test_field_specific_wrappers_delegate_to_one_simion_runner(self) -> None:
        uniform = UNIFORM_RUNNER.read_text(encoding="utf-8")
        comsol = COMSOL_FIELD_RUNNER.read_text(encoding="utf-8")
        self.assertIn("build_uniform_rear_gas_runtime.ps1", uniform)
        self.assertIn("run_gas_field_prototype.ps1", uniform)
        self.assertNotIn("--nogui --noprompt fly", uniform)
        self.assertIn("build_gas_runtime.ps1", comsol)
        self.assertIn("run_gas_field_prototype.ps1", comsol)
        self.assertNotIn("--nogui --noprompt fly", comsol)


class GasPreparationTests(unittest.TestCase):
    def test_gas_assisted_mode_fails_before_creating_output_without_field(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            with self.assertRaisesRegex(ValueError, "gas-field-manifest"):
                prepare(output, mode="gas_assisted_transport")
            self.assertFalse(output.exists())

    def test_manifest_hash_and_required_functions_are_fail_closed(self) -> None:
        interface = load(GAS_INTERFACE)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = root / "field.lua"
            runtime.write_text(
                "return {pressure_pa=function() return 400 end,"
                "temperature_k=function() return 300 end,"
                "velocity_m_s=function() return 0,0,0 end}\n",
                encoding="utf-8",
            )
            manifest = {
                "schema_version": 1,
                "role": "dual_cone_gas_field_export",
                "project_id": "dual_cone_tandem_quadrupole_ion_interface",
                "source": {
                    "kind": "prescribed_uniform_rear_gas",
                    "spec_sha256": "1" * 64,
                    "interface_sha256": "2" * 64,
                },
                "coordinate_frame": interface["runtime_artifact_contract"]["coordinate_frame"],
                "domain": interface["runtime_artifact_contract"]["domain"],
                "interpolation_policy": interface["runtime_artifact_contract"]["interpolation_policy"],
                "runtime_lua": {"path": str(runtime), "sha256": "0" * 64},
            }
            path = root / "manifest.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "SHA-256 differs"):
                validate_gas_field_manifest(path, interface)

    def test_valid_gas_package_freezes_official_sds_closure_by_hash(self) -> None:
        interface = load(GAS_INTERFACE)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sds = root / "sds"
            sds.mkdir()
            for name in SDS_FILES:
                (sds / name).write_text(f"fixture {name}\n", encoding="utf-8")
            runtime = root / "field.lua"
            runtime.write_text(
                "return {pressure_pa=function() return 400 end,"
                "temperature_k=function() return 300 end,"
                "velocity_m_s=function() return 0,0,0 end}\n",
                encoding="utf-8",
            )
            manifest = {
                "schema_version": 1,
                "role": "dual_cone_gas_field_export",
                "project_id": "dual_cone_tandem_quadrupole_ion_interface",
                "source": {
                    "kind": "prescribed_uniform_rear_gas",
                    "spec_sha256": "1" * 64,
                    "interface_sha256": "2" * 64,
                },
                "coordinate_frame": interface["runtime_artifact_contract"]["coordinate_frame"],
                "domain": interface["runtime_artifact_contract"]["domain"],
                "interpolation_policy": interface["runtime_artifact_contract"]["interpolation_policy"],
                "runtime_lua": {"path": str(runtime), "sha256": file_sha256(runtime)},
            }
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            receipt = prepare(
                root / "run",
                mode="gas_assisted_transport",
                collision_sds_dir=sds,
                gas_field_manifest=manifest_path,
            )
            self.assertEqual(receipt["trajectory_authority"], "simion")
            frozen = receipt["inputs"]["simion_official_collision_sds"]
            self.assertEqual(set(frozen), set(SDS_FILES))
            for record in frozen.values():
                self.assertEqual(file_sha256(Path(record["frozen_path"])), record["sha256"])
            source_receipt = receipt["inputs"]["cylindrical_ion_source_receipt"]["identity"]
            self.assertEqual(source_receipt["source_region_model"], "ion_source_volume_cylinder_v1")
            self.assertEqual(source_receipt["particle_count"], 100)
            fly2 = Path(receipt["inputs"]["particle_fly2"]["path"])
            source = fly2.read_text(encoding="utf-8")
            self.assertEqual(source.count("standard_beam {"), 100)
            self.assertIn("direction = vector(", source)
            self.assertIn("gas_flow_science", receipt["inputs"])

    def test_uniform_rear_runtime_keeps_400_pa_and_zeroes_upstream_collisions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = root / "field.lua"
            manifest_path = root / "manifest.json"
            manifest = export_uniform_runtime(runtime, manifest_path)
            source = runtime.read_text(encoding="utf-8")
            self.assertEqual(manifest["role"], "dual_cone_gas_field_export")
            self.assertEqual(manifest["source"]["kind"], "prescribed_uniform_rear_gas")
            self.assertIn("local p_rear, p_upstream = 400, 0", source)
            self.assertIn("local z_rear = 3", source)
            self.assertIn("local uz_rear, ur_rear = 100, 0", source)
            self.assertIn("no fluid support outside declared envelope", source)
            validate_gas_field_manifest(manifest_path, load(GAS_INTERFACE))


if __name__ == "__main__":
    unittest.main()

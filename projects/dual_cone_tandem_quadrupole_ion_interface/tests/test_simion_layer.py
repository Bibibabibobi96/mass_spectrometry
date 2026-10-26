from __future__ import annotations

import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from common.contracts.file_identity import file_sha256
from common.ion_release.release import generate_release_states, validate_release_spec
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



def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class SimionGeometryTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 required")
    def test_project_gate_stops_before_ruff_when_unittest_fails(self) -> None:
        source = (PROJECT / "verify_project.ps1").read_text(encoding="utf-8")
        start = source.index("    & $PythonExe -m unittest discover")
        guard = source[source.index("    if ($LASTEXITCODE", start):
                       source.index("    & $PythonExe -m ruff", start)]
        script = (
            "$ErrorActionPreference='Stop'; & '" + sys.executable.replace("'", "''")
            + "' -c 'raise SystemExit(7)'\n" + guard
            + "Write-Output 'PROJECT_GATE=PASS'"
        )
        result = subprocess.run(
            [shutil.which("pwsh"), "-NoProfile", "-Command", script],
            cwd=PROJECT.parents[1], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=30,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Dual-cone interface static tests failed", result.stderr)
        self.assertNotIn("PROJECT_GATE=PASS", result.stdout)

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
        radius = source["geometry"]["radius_mm"]
        validate_release_spec(source)
        states = generate_release_states(source)
        self.assertEqual(len(states), 100)
        self.assertTrue(all(state["vz_m_s"] >= 1.0 for state in states))
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

    def test_validated_comsol_gas_compilation_remains_available(self) -> None:
        compiler = (PROJECT / "workflows/gas_assisted_transport/build_gas_runtime.ps1").read_text(encoding="utf-8")
        self.assertIn("verify_run_manifest.py", compiler)
        self.assertIn("--require-status success", compiler)
        self.assertIn("results\\gas_field_rz.csv", compiler)
        self.assertIn("results\\gas_field_metadata.json", compiler)


class GasPreparationTests(unittest.TestCase):
    def test_c0_pure_preparation_keeps_fractional_geometry_and_no_pa_payload(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "prepared"
            receipt = prepare(output, mode="c0_gem_smoke")
            self.assertEqual(receipt["mode"], "c0_gem_smoke")
            self.assertEqual(receipt["collision_model"], "none")
            self.assertFalse(receipt["qualified_evidence"])
            gem = Path(receipt["inputs"]["gem"]["path"]).read_text(encoding="utf-8")
            self.assertEqual(gem, render_gem(load(DEFAULT_RESOLVED), load(DEFAULT_NUMERICS)))
            self.assertIn("surface=fractional", gem)
            self.assertEqual(list(output.rglob("*.pa*")), [])
            for name in ("resolved_geometry", "simion_solver_numerics", "ion_transport_science",
                         "gas_field_interface", "rf_drive_kernel", "simion_program"):
                record = receipt["inputs"][name]
                self.assertEqual(set(record), {"source_path", "frozen_path", "sha256", "bytes"})
                self.assertEqual(Path(record["frozen_path"]).read_bytes(), Path(record["source_path"]).read_bytes())
            original_receipt = (output / "preparation_receipt.json").read_bytes()
            with self.assertRaises(FileExistsError):
                prepare(output, mode="c0_gem_smoke")
            self.assertEqual((output / "preparation_receipt.json").read_bytes(), original_receipt)

    def test_preparation_rejects_missing_selected_source_and_changed_copy(self) -> None:
        module = "projects.dual_cone_tandem_quadrupole_ion_interface.simion.prepare"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with mock.patch(module + ".PROGRAM", root / "missing.lua"):
                with self.assertRaises(FileNotFoundError):
                    prepare(root / "missing_source", mode="c0_gem_smoke")
            copy_file = shutil.copyfile

            def corrupt_copy(source: Path, target: Path) -> None:
                copy_file(source, target)
                content = target.read_bytes()
                target.write_bytes(bytes([content[0] ^ 1]) + content[1:])

            with mock.patch("common.contracts.frozen_inputs.shutil.copyfile", side_effect=corrupt_copy):
                with self.assertRaisesRegex(AssertionError, "frozen input SHA-256 changed"):
                    prepare(root / "changed_copy", mode="c0_gem_smoke")
            self.assertFalse((root / "changed_copy/preparation_receipt.json").exists())

    def test_preparation_executes_from_detached_sources_with_shared_freezer(self) -> None:
        repo = PROJECT.parents[1]
        with tempfile.TemporaryDirectory() as directory:
            snapshot = Path(directory) / "snapshot"
            for relative in ("common/contracts", "common/ion_release", "common/simion",
                             "projects/" + PROJECT.name + "/config", "projects/" + PROJECT.name + "/simion",
                             "projects/" + PROJECT.name + "/analysis"):
                shutil.copytree(repo / relative, snapshot / relative,
                    ignore=lambda folder, names: [name for name in names
                        if name == "__pycache__" or ((Path(folder)/name).is_file()
                            and Path(name).suffix not in {".py", ".json", ".lua"})])
            for relative in (
                "core/round_rod_geometry.py", "core/connector_geometry.py",
                "core/interface_geometry.py", "core/axial_acceleration.py",
                "simion/simion_geometry.py", "runtime/simion_numerics.py",
            ):
                source = Path("projects/rf_multipole_ion_optics") / relative
                target = snapshot / source
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(repo / source, target)
            code = r"""
from pathlib import Path
from common.contracts import frozen_inputs
from projects.dual_cone_tandem_quadrupole_ion_interface.simion import prepare as p
from projects.dual_cone_tandem_quadrupole_ion_interface.analysis.export_uniform_rear_gas_runtime import export_uniform_runtime
assert Path(p.__file__).resolve().is_relative_to(Path.cwd())
assert Path(frozen_inputs.__file__).resolve().is_relative_to(Path.cwd())
c0 = p.prepare(Path('c0'), mode='c0_gem_smoke')
export_uniform_runtime(Path('field.lua').resolve(), Path('manifest.json').resolve())
sds = Path('sds'); sds.mkdir()
for name in p.SDS_FILES:
    (sds/name).write_text('inert fixture\n', encoding='utf-8')
gas = p.prepare(Path('gas'), mode='gas_assisted_transport',
                collision_sds_dir=sds, gas_field_manifest=Path('manifest.json'))
for receipt in (c0, gas):
    record = receipt['inputs']['resolved_geometry']
    assert set(record) == {'source_path', 'frozen_path', 'sha256', 'bytes'}
    assert Path(record['frozen_path']).read_bytes() == Path(record['source_path']).read_bytes()
assert gas['inputs']['cylindrical_ion_source_receipt']['identity']['particle_count'] == 100
assert not list(Path.cwd().rglob('*.pa*'))
print('DETACHED_DUAL_CONE_PREPARE=PASS MODES=2')
"""
            result = subprocess.run([sys.executable, "-B", "-c", code], cwd=snapshot,
                env={**os.environ, "PYTHONPATH": str(snapshot)}, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=30, check=False)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("DETACHED_DUAL_CONE_PREPARE=PASS MODES=2", result.stdout)

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
                self.assertEqual(set(record), {"source_path", "frozen_path", "sha256", "bytes"})
                self.assertEqual(file_sha256(Path(record["frozen_path"])), record["sha256"])
            source_receipt = receipt["inputs"]["cylindrical_ion_source_receipt"]["identity"]
            self.assertEqual(source_receipt["role"], "repository_ion_release")
            self.assertEqual(source_receipt["release_spec"]["geometry"]["shape"], "cylinder")
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

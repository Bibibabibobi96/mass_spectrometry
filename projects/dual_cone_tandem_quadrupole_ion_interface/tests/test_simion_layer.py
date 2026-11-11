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

from msplatform.io.file_identity import file_sha256
from msplatform.ion_release.release import generate_release_states, validate_release_spec
from msplatform.backends.simion.dual_cone_geometry import (
    device_to_workbench_offsets,
    render_gem,
)
from msplatform.backends.simion.dual_cone_transport import (
    SDS_FILES, prepare_transport, validate_runtime_manifest,
)
from msplatform.backends.simion.resources import native_resource_path
from projects.dual_cone_tandem_quadrupole_ion_interface.analysis.plot_simion_trajectory_projection import (
    axial_reach_profile,
    main as plot_trajectory_projection,
)


PROJECT = Path(__file__).resolve().parents[1]
GAS_INTERFACE = PROJECT / "config" / "gas_field_interface.json"
DEFAULT_RESOLVED = PROJECT / "config" / "resolved_geometry.json"
DEFAULT_NUMERICS = PROJECT / "config" / "simion_solver_numerics.json"
UNIFORM_SPEC = PROJECT / "config" / "uniform_rear_gas_field.json"


def write_uniform_gas_fixture(output_lua, output_manifest, *, spec_path, interface_path):
    """Actual current component projection/compiler over explicit research fixtures."""
    from msplatform.components.dual_cone_tandem_quadrupole_ion_interface.gas_field import prepare_uniform_rear_gas_field
    from msplatform.backends.simion.gas_runtime import materialize_gas_runtime
    from msplatform.contracts.gas import GasSpecies
    from msplatform.io.manifest_records import file_record

    source_science = load(PROJECT / "config/gas_flow_science.json")
    transport_science = load(PROJECT / "config/ion_transport_science.json")
    composition = (GasSpecies(source_science["physics"]["gas_species"]["species_id"],
        transport_science["gas"]["collision_gas_mass_amu"], 1.),)
    field, metadata = prepare_uniform_rear_gas_field(load(spec_path), interface=load(interface_path),
        composition=composition, spec_record=file_record(spec_path, "required_evidence"),
        interface_record=file_record(interface_path, "required_evidence"))
    return materialize_gas_runtime(field, output_lua, output_manifest, manifest_metadata=metadata)


def prepare(output_dir, **kwargs):
    return prepare_transport(output_dir, resolved_path=DEFAULT_RESOLVED,
        numerics_path=DEFAULT_NUMERICS, science_path=PROJECT / "config/ion_transport_science.json",
        interface_path=GAS_INTERFACE, gas_science_path=PROJECT / "config/gas_flow_science.json",
        source_spec_path=PROJECT / "config/cylindrical_ion_source.json", **kwargs)


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
                "--historical-translation-only",
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
        source = (
            PROJECT.parents[1] / "src/msplatform/backends/simion/dual_cone_geometry.py"
        ).read_text(encoding="utf-8")
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
        program = native_resource_path("dual_cone_gas_assisted_transport.lua").read_text(
            encoding="utf-8"
        )
        self.assertIn("loadfile(assert(config.rf_drive_kernel))", program)
        self.assertIn("simion.import(assert(config.collision_sds_lua), 'noinstall')", program)
        binding = native_resource_path("collision_sds_binding.lua").read_text(encoding="utf-8")
        self.assertIn("SDS.install()", binding)
        self.assertNotIn("adj_electrode", program)
        self.assertIn("adj_elect[id] = voltage", program)
        self.assertIn("apply_at(ion_time_of_flight, set_electrode_voltage)", program)
        self.assertIn("stage_1.timestep_cap_us, stage_2.timestep_cap_us", program)
        self.assertEqual(program.count("function segment.fast_adjust()"), 1)
        self.assertEqual(program.count("function segment.tstep_adjust()"), 1)
        self.assertEqual(program.count("function segment.terminate()"), 1)
        self.assertIn("binding.install(SDS,field", program)
        self.assertIn("terminal_code[ion_number] = 3", program)
        self.assertIn("status=='no_data'", binding)
        self.assertIn("options.on_coverage_lost()", binding)
        self.assertIn("ion_splat = 1", program)
        self.assertIn("emit_final(3)", program)
        self.assertLess(
            program.index("function segment.other_actions()"),
            program.index("terminal_code[ion_number] = 3"),
        )
        self.assertIn("trajectory_samples.csv", (PROJECT.parents[1] / "src/msplatform/backends/simion/dual_cone_transport.py").read_text(encoding="utf-8"))

    def test_published_gas_runtime_real_entry_preserves_output_and_rejects_tampering(self) -> None:
        from msplatform.backends.simion.gas_runtime import materialize_gas_runtime
        from msplatform.components.dual_cone_tandem_quadrupole_ion_interface.gas_field import prepare_cfd_gas_field
        from msplatform.io.manifest_records import file_record
        from msplatform.results.gas_field import read_gas_field
        from projects.dual_cone_tandem_quadrupole_ion_interface.tests.test_gas_flow_contract import _write_fixture

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            csv_path, metadata_path = _write_fixture(root)
            config = PROJECT / "config"
            paths = dict(science=config / "gas_flow_science.json",
                numerics=config / "comsol_solver_numerics.json",
                geometry=config / "resolved_geometry.json", field_csv=csv_path, field_metadata=metadata_path)
            records = {name: file_record(path, "required_evidence") for name, path in paths.items()}
            producer = dict(schema_version=2, role="simulation_run_manifest", project=PROJECT.name,
                run_id="explicit-inert-gas-fixture", mode="axisymmetric_gas_flow_screening", status="success",
                inputs={name: records[name] for name in ("science", "numerics", "geometry")},
                outputs=[records["field_csv"], records["field_metadata"]],
                products=dict(gas_field=dict(schema_version=1, kind="gas_field", status="complete",
                    metadata=dict(claim_scope="INERT_PREPARATION_FIXTURE_NOT_NATIVE"), data=records)))
            manifest = root / "run_manifest.json"
            manifest.write_text(json.dumps(producer), encoding="utf-8")
            reference = dict(manifest=file_record(manifest, "required_evidence"), product_id="gas_field")
            reference_path = root / "reference.json"
            reference_path.write_text(json.dumps(reference), encoding="utf-8")
            interface = load(GAS_INTERFACE)
            interface["runtime_artifact_contract"]["domain"] = dict(
                minimum_z_mm=0.0, maximum_z_mm=9.0, minimum_radius_mm=0.0, maximum_radius_mm=9.0)
            interface_path = root / "interface.json"
            interface_path.write_text(json.dumps(interface), encoding="utf-8")
            output = root / "runtime"
            lua, runtime_manifest = output / "gas_field_runtime.lua", output / "gas_field_manifest.json"
            # The pre-migration composition is the byte oracle, at the exact same output paths.
            field = read_gas_field(reference)
            definition, metadata = prepare_cfd_gas_field(field.data, interface=interface,
                producer_reference=field.artifact.reference, source_records=field.artifact.data_records)
            materialize_gas_runtime(definition, lua, runtime_manifest, manifest_metadata=metadata)
            expected = (lua.read_bytes(), runtime_manifest.read_bytes())
            source_bytes = {name: path.read_bytes() for name, path in paths.items()}
            script = PROJECT / "workflows/gas_assisted_transport/build_gas_runtime.ps1"
            shell = shutil.which("pwsh")
            self.assertIsNotNone(shell)
            common = ["-InterfacePath", str(interface_path), "-OutputDir", str(output), "-PythonExe", sys.executable]
            for option, value in (("-ComsolRunDirectory", root), ("-SourceReferencePath", reference_path)):
                with self.subTest(option=option):
                    result = subprocess.run([shell, "-NoProfile", "-File", str(script), option, str(value), *common],
                        cwd=root, timeout=30, capture_output=True, text=True, encoding="utf-8", check=False)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertIn("SIMION_GAS_FIELD_MANIFEST=" + str(runtime_manifest.resolve()), result.stdout)
                    self.assertEqual((lua.read_bytes(), runtime_manifest.read_bytes()), expected)
            for option, value in (("--comsol-run-directory", root), ("--source-reference", reference_path)):
                with self.subTest(installed_cli=option):
                    result = subprocess.run([sys.executable, "-I", "-B", "-X", "utf8", "-m",
                        "msplatform.workflows.dual_cone_transport", option, str(value),
                        "--interface", str(interface_path), "--output-dir", str(output)],
                        cwd=root, timeout=30, capture_output=True, text=True, encoding="utf-8", check=False)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertIn("SIMION_GAS_FIELD_MANIFEST=" + str(runtime_manifest.resolve()), result.stdout)
                    self.assertEqual((lua.read_bytes(), runtime_manifest.read_bytes()), expected)
            self.assertEqual({name: path.read_bytes() for name, path in paths.items()}, source_bytes)
            csv_path.write_bytes(csv_path.read_bytes() + b"tamper")
            failed = subprocess.run([shell, "-NoProfile", "-File", str(script), "-SourceReferencePath",
                str(reference_path), *common], cwd=root, timeout=30, capture_output=True, text=True, encoding="utf-8", check=False)
            self.assertNotEqual(failed.returncode, 0)
            self.assertNotIn("SIMION_GAS_FIELD_MANIFEST=", failed.stdout)
            self.assertEqual((lua.read_bytes(), runtime_manifest.read_bytes()), expected)


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
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with mock.patch("msplatform.backends.simion.resources.native_resource_path", return_value=root / "missing.lua"):
                with self.assertRaises(FileNotFoundError):
                    prepare(root / "missing_source", mode="c0_gem_smoke")
            copy_file = shutil.copyfile

            def corrupt_copy(source: Path, target: Path) -> None:
                copy_file(source, target)
                content = target.read_bytes()
                target.write_bytes(bytes([content[0] ^ 1]) + content[1:])

            with mock.patch("msplatform.execution.inputs.shutil.copyfile", side_effect=corrupt_copy):
                with self.assertRaisesRegex(AssertionError, "frozen input SHA-256 changed"):
                    prepare(root / "changed_copy", mode="c0_gem_smoke")
            self.assertFalse((root / "changed_copy/preparation_receipt.json").exists())

    def test_preparation_executes_from_detached_sources_with_shared_freezer(self) -> None:
        repo = PROJECT.parents[1]
        with tempfile.TemporaryDirectory() as directory:
            snapshot = Path(directory) / "snapshot"
            for relative in ("projects/" + PROJECT.name + "/config",):
                shutil.copytree(repo / relative, snapshot / relative,
                    ignore=lambda folder, names: [name for name in names
                        if name == "__pycache__" or ((Path(folder)/name).is_file()
                            and Path(name).suffix not in {".py", ".json", ".lua"})])
            from msplatform.execution.inputs import freeze_file
            from common.contracts.test_support.run_artifact_workflow import copy_scientific_core

            copy_scientific_core(repo, snapshot)
            kernel = Path("src/msplatform/backends/simion/resources/rf_drive.lua")
            (snapshot / kernel).parent.mkdir(parents=True, exist_ok=True)
            kernel_record = freeze_file(repo / kernel, snapshot / kernel)
            self.assertEqual(kernel_record["sha256"], file_sha256(repo / kernel))
            self.assertEqual((snapshot / kernel).read_bytes(), (repo / kernel).read_bytes())
            program = Path("src/msplatform/backends/simion/resources/dual_cone_gas_assisted_transport.lua")
            program_record = freeze_file(repo / program, snapshot / program)
            self.assertEqual(program_record["sha256"], file_sha256(repo / program))
            self.assertEqual((snapshot / program).read_bytes(), (repo / program).read_bytes())
            binding = Path("src/msplatform/backends/simion/resources/collision_sds_binding.lua")
            binding_record = freeze_file(repo / binding, snapshot / binding)
            self.assertEqual(binding_record["sha256"], file_sha256(repo / binding))
            self.assertEqual((snapshot / binding).read_bytes(), (repo / binding).read_bytes())

            code = r"""
from pathlib import Path
from msplatform.execution import inputs as frozen_inputs
from msplatform.backends.simion import dual_cone_transport as p
from msplatform.components.dual_cone_tandem_quadrupole_ion_interface.gas_field import prepare_uniform_rear_gas_field
from msplatform.backends.simion.gas_runtime import materialize_gas_runtime
from msplatform.contracts.gas import GasSpecies
from msplatform.io.manifest_records import file_record
import json
assert Path(p.__file__).resolve().is_relative_to(Path.cwd())
assert Path(frozen_inputs.__file__).resolve().is_relative_to(Path.cwd())
import sys
case = Path(sys.argv[2]); case.mkdir()
config=Path.cwd() / 'projects/dual_cone_tandem_quadrupole_ion_interface/config'
kwargs=dict(resolved_path=config/'resolved_geometry.json', numerics_path=config/'simion_solver_numerics.json',
 science_path=config/'ion_transport_science.json',interface_path=config/'gas_field_interface.json',
 gas_science_path=config/'gas_flow_science.json',source_spec_path=config/'cylindrical_ion_source.json')
c0 = p.prepare_transport(case / 'c0', mode='c0_gem_smoke',**kwargs)
species=json.loads(kwargs['gas_science_path'].read_text())['physics']['gas_species']['species_id']
mass=json.loads(kwargs['science_path'].read_text())['gas']['collision_gas_mass_amu']
spec_path=config/'uniform_rear_gas_field.json'
field,metadata=prepare_uniform_rear_gas_field(json.loads(spec_path.read_text()),
    interface=json.loads(kwargs['interface_path'].read_text()),composition=(GasSpecies(species,mass,1.),),
    spec_record=file_record(spec_path,'required_evidence'),interface_record=file_record(kwargs['interface_path'],'required_evidence'))
materialize_gas_runtime(field,(case/'field.lua').resolve(),(case/'manifest.json').resolve(),manifest_metadata=metadata)
sds = case / 'sds'; sds.mkdir()
for name in p.SDS_FILES:
    (sds/name).write_text('inert fixture\n', encoding='utf-8')
gas = p.prepare_transport(case / 'gas', mode='gas_assisted_transport',**kwargs,
                collision_sds_dir=sds, gas_field_manifest=case / 'manifest.json')
for receipt in (c0, gas):
    record = receipt['inputs']['resolved_geometry']
    assert set(record) == {'source_path', 'frozen_path', 'sha256', 'bytes'}
    assert Path(record['frozen_path']).read_bytes() == Path(record['source_path']).read_bytes()
assert gas['inputs']['cylindrical_ion_source_receipt']['identity']['particle_count'] == 100
assert not list(Path.cwd().rglob('*.pa*'))
for name, module in tuple(sys.modules.items()):
    if name.startswith('msplatform') and getattr(module, '__file__', None):
        assert Path(module.__file__).resolve().is_relative_to(Path.cwd() / 'src'), (name, module.__file__)
assert not any(name.split('.')[0] in {'common','projects','integrations'} for name in sys.modules)
print('DETACHED_DUAL_CONE_PREPARE=PASS MODES=2')
"""
            # -I ignores inherited author/PYTHONPATH entries; only this selected
            # frozen src/root pair is added before importing its selector.
            code = ("import sys; from pathlib import Path; root=Path(sys.argv[1]); sys.path[:0]=[str(root/'src'),str(root)]; "
                    "from msplatform.execution.inputs import python_import_roots; "
                    "sys.path[:0] = python_import_roots(Path(sys.argv[1]));\n") + code
            command = [sys.executable, "-I", "-B", "-c", code, str(snapshot), str(snapshot / "positive")]
            result = subprocess.run(command, cwd=snapshot,
                env={**os.environ, "PYTHONPATH": str(repo)}, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=30, check=False)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("DETACHED_DUAL_CONE_PREPARE=PASS MODES=2", result.stdout)
            adapter = snapshot/'src/msplatform/backends/simion/rf_electrode_mapping.py'
            adapter_bytes = adapter.read_bytes()
            adapter.unlink()
            try:
                missing = subprocess.run([*command[:-1], str(snapshot / "missing-provider")], cwd=snapshot,
                    env={**os.environ, "PYTHONPATH": str(repo)}, capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=30, check=False)
                self.assertNotEqual(missing.returncode, 0)
                self.assertIn("No module named 'msplatform.backends.simion.rf_electrode_mapping'",
                              missing.stderr)
            finally:
                adapter.write_bytes(adapter_bytes)

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
            path = root / "manifest.json"
            manifest = write_uniform_gas_fixture(runtime, path, spec_path=UNIFORM_SPEC, interface_path=GAS_INTERFACE)
            manifest["runtime_lua"]["sha256"] = "0" * 64
            path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "SHA-256 differs"):
                validate_runtime_manifest(path, interface)
            runtime.write_text("return {}", encoding="utf-8")
            manifest["runtime_lua"]["sha256"] = file_sha256(runtime)
            path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "omits required function sample"):
                validate_runtime_manifest(path, interface)

    def test_valid_gas_package_freezes_official_sds_closure_by_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sds = root / "sds"
            sds.mkdir()
            for name in SDS_FILES:
                (sds / name).write_text(f"fixture {name}\n", encoding="utf-8")
            runtime = root / "field.lua"
            manifest_path = root / "manifest.json"
            write_uniform_gas_fixture(runtime, manifest_path, spec_path=UNIFORM_SPEC, interface_path=GAS_INTERFACE)
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
            manifest = write_uniform_gas_fixture(
                runtime,
                manifest_path,
                spec_path=UNIFORM_SPEC,
                interface_path=GAS_INTERFACE,
            )
            source = runtime.read_text(encoding="utf-8")
            self.assertEqual(manifest["role"], "dual_cone_gas_field_export")
            self.assertEqual(manifest["source"]["kind"], "prescribed_uniform_rear_gas")
            self.assertIn("pressure_pa=400", source)
            self.assertIn("pressure_pa=0", source)
            self.assertIn("lo=3", source)
            self.assertIn("ur=0,uz=100", source)
            self.assertEqual(manifest["sampling"]["outside_domain_policy"], "coverage_loss")
            validate_runtime_manifest(manifest_path, load(GAS_INTERFACE))


if __name__ == "__main__":
    unittest.main()

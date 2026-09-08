from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from common.contracts.file_identity import file_sha256
from projects.dual_cone_tandem_quadrupole_ion_interface.simion.geometry import (
    DEFAULT_NUMERICS,
    DEFAULT_RESOLVED,
    render_gem,
)
from projects.dual_cone_tandem_quadrupole_ion_interface.simion.prepare import (
    GAS_INTERFACE,
    SDS_FILES,
    prepare,
    validate_gas_field_manifest,
)


PROJECT = Path(__file__).resolve().parents[1]


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class SimionGeometryTests(unittest.TestCase):
    def test_gem_uses_shared_rod_renderer_and_distinct_namespaces(self) -> None:
        gem = render_gem(load(DEFAULT_RESOLVED), load(DEFAULT_NUMERICS))
        for electrode in (1, 2, 11, 12, 21, 22):
            self.assertIn(f"e({electrode})", gem)
        self.assertIn("cylinder(0,0,0,4.3,1.88,49.2)", gem)
        self.assertIn("2.39", gem)
        self.assertIn("C0 limitation", gem)
        source = (PROJECT / "simion" / "geometry.py").read_text(encoding="utf-8")
        self.assertIn("render_grouped_rod_array_gem", source)
        self.assertNotIn("def _stage_1_rods", source)

    def test_science_contract_makes_simion_the_only_trajectory_authority(self) -> None:
        science = load(PROJECT / "config" / "ion_transport_science.json")
        self.assertEqual(science["trajectory_authority"], "simion")
        self.assertEqual(science["gas"]["collision_model"], "simion_official_collision_sds")

    def test_program_composes_shared_rf_and_official_sds_without_python_tracking(self) -> None:
        program = (PROJECT / "simion" / "programs" / "gas_assisted_transport.lua").read_text(
            encoding="utf-8"
        )
        self.assertIn("loadfile(assert(config.rf_drive_kernel))", program)
        self.assertIn("simion.import(assert(config.collision_sds_lua), 'noinstall')", program)
        self.assertIn("SDS.install()", program)
        self.assertEqual(program.count("function segment.fast_adjust()"), 1)
        self.assertEqual(program.count("function segment.tstep_adjust()"), 1)


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
                "role": "dual_cone_comsol_gas_field_export",
                "project_id": "dual_cone_tandem_quadrupole_ion_interface",
                "coordinate_frame": interface["runtime_artifact_contract"]["coordinate_frame"],
                "domain": interface["runtime_artifact_contract"]["domain"],
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
                "role": "dual_cone_comsol_gas_field_export",
                "project_id": "dual_cone_tandem_quadrupole_ion_interface",
                "coordinate_frame": interface["runtime_artifact_contract"]["coordinate_frame"],
                "domain": interface["runtime_artifact_contract"]["domain"],
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


if __name__ == "__main__":
    unittest.main()

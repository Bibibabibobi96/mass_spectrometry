from __future__ import annotations

import csv
import importlib.util
import json
import math
import tempfile
import unittest
from pathlib import Path

from common.contracts.component_particle_state import csv_columns
from common.contracts.particle_physics import kinetic_energy_ev

PROJECT_ROOT = Path(__file__).parents[2]
SCRIPT = PROJECT_ROOT / "analysis" / "build_oatof_handoff.py"
SPEC = importlib.util.spec_from_file_location("build_oatof_handoff", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
CONTRACT = PROJECT_ROOT / "config" / "rf_to_oatof_handoff.json"
REGISTRATION = PROJECT_ROOT / "config" / "resolved_rf_to_oatof_s2_spatial_registration.json"


class ComponentChainClockTests(unittest.TestCase):
    def test_clock_accumulates_across_arbitrary_components(self) -> None:
        instrument_time, lineage_age, particle_age = MODULE.advance_chain_clock(12.0, 2.0, 2.0, 5.0)
        self.assertEqual((instrument_time, lineage_age, particle_age), (17.0, 7.0, 7.0))
        instrument_time, lineage_age, particle_age = MODULE.advance_chain_clock(
            instrument_time, lineage_age, particle_age, 3.0
        )
        self.assertEqual((instrument_time, lineage_age, particle_age), (20.0, 10.0, 10.0))

    def test_reaction_product_can_reset_particle_age_without_resetting_lineage(self) -> None:
        instrument_time, lineage_age, _ = MODULE.advance_chain_clock(15.0, 5.0, 5.0, 2.0)
        child_particle_age = 0.0
        self.assertEqual((instrument_time, lineage_age, child_particle_age), (17.0, 7.0, 0.0))

    def test_negative_component_time_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "non-negative"):
            MODULE.advance_chain_clock(0.0, 0.0, 0.0, -1.0)

    def test_mass_to_charge_is_not_misused_as_actual_mass(self) -> None:
        self.assertEqual(MODULE.mass_amu_from_mass_to_charge(100.0, 1), 100.0)
        self.assertEqual(MODULE.mass_amu_from_mass_to_charge(100.0, 2), 200.0)
        with self.assertRaisesRegex(ValueError, "non-zero"):
            MODULE.mass_amu_from_mass_to_charge(100.0, 0)


class OatofHandoffContractTests(unittest.TestCase):
    def test_registration_must_be_supplied_explicitly(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be supplied explicitly"):
            MODULE.validate_contract(CONTRACT)

    def test_draft_contract_is_coherent_but_not_package_qualified(self) -> None:
        validated = MODULE.validate_contract(CONTRACT, REGISTRATION)
        contract = validated["contract"]
        self.assertAlmostEqual(validated["determinant"], 1.0, delta=1e-12)
        self.assertNotEqual(contract["status"], "frozen")
        self.assertFalse(contract["package_generation_allowed"])
        self.assertEqual(contract["electrical_interface"]["status"], "unresolved")
        self.assertIn("time_dependent_fields", contract["timing_contract"]["solver_local_time_policy"])

    def test_rotation_maps_rf_axes_to_oatof_axes(self) -> None:
        transform = MODULE.validate_contract(CONTRACT, REGISTRATION)["spatial_transform"]
        vectors = (
            ((0.0, 0.0, 1.0), (1.0, 0.0, 0.0)),
            ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
            ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
        )
        for source, expected in vectors:
            actual = transform.transform_vector(
                MODULE.FramedVector(transform.from_frame_id, source)
            )
            self.assertEqual(actual.components, expected)

    def test_hybrid_mesh_event_schema_normalizes_without_duplicate_storage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "hybrid.csv"
            fields = sorted(MODULE.HYBRID_MESH_SOURCE_COLUMNS)
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
                writer.writeheader()
                for particle_id in range(1, 101):
                    writer.writerow({
                        "particle_id": particle_id, "event": "handoff", "status": "transmitted",
                        "global_time_us": 12.5, "particle_age_us": 7.5, "rf_phase_rad": 0.2,
                        "x_mm": 0.1, "y_mm": 0.2, "z_mm": 90.2,
                        "vx_m_s": 10, "vy_m_s": 20, "vz_m_s": 2000,
                        "kinetic_energy_eV": 2.1,
                    })
            rows = MODULE.read_handoff_rows(
                path, MODULE.validate_contract(CONTRACT, REGISTRATION)["contract"]
            )
            self.assertEqual(len(rows), 100)
            self.assertEqual(rows[0]["time_us"], "12.5")
            self.assertEqual(rows[0]["axial_z_mm"], "90.2")
            self.assertEqual(rows[0]["velocity_axial_m_s"], "2000")


class OatofHandoffBuildTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "particle_state.csv"
        fieldnames = sorted(MODULE.REQUIRED_SOURCE_COLUMNS)
        mass_th = 100.0
        vx_rf, vy_rf, vz_rf = 100.0, 200.0, 2000.0
        energy = kinetic_energy_ev(mass_th, vx_rf, vy_rf, vz_rf)
        with self.source.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
            writer.writeheader()
            for particle_id in range(100, 0, -1):
                writer.writerow({
                    "particle_id": particle_id,
                    "event": "handoff",
                    "status": "transmitted",
                    "time_us": 10.0 + particle_id * 0.1,
                    "elapsed_time_us": 5.0 + particle_id * 0.01,
                    "rf_phase_rad": 0.25,
                    "axial_z_mm": 90.2,
                    "transverse_x_mm": 0.1,
                    "transverse_y_mm": 0.2,
                    "velocity_axial_m_s": vz_rf,
                    "velocity_x_m_s": vx_rf,
                    "velocity_y_m_s": vy_rf,
                    "kinetic_energy_eV": energy,
                })
        self.manifest = self.root / "run_manifest.json"
        self.manifest.write_text(json.dumps({
            "project": "rf_quadrupole_collision_cooling",
            "mode": "transport_interface_readiness",
            "status": "success",
            "inputs": {
                "baseline": {"sha256": MODULE.sha256(PROJECT_ROOT / "config" / "baseline.json")},
                "mode": {"sha256": MODULE.sha256(PROJECT_ROOT / "config" / "modes" / "transport_interface_readiness.json")},
                "interface_contract": {"sha256": MODULE.sha256(PROJECT_ROOT / "config" / "interface_contract.json")},
            },
            "outputs": [{
                "path": f"C:/pre-migration/location/{self.source.name}",
                "sha256": MODULE.sha256(self.source),
            }],
        }), encoding="utf-8")
        self.canonical = self.root / "handoff.csv"
        self.ion = self.root / "particles.ion"
        self.row_map = self.root / "row_map.csv"
        self.metadata = self.root / "metadata.json"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def build(self) -> dict:
        return MODULE.build_handoff(
            self.source,
            self.manifest,
            CONTRACT,
            self.canonical,
            self.ion,
            self.row_map,
            self.metadata,
            registration_path=REGISTRATION,
        )

    def test_build_preserves_global_clock_and_derives_local_ion(self) -> None:
        metadata = self.build()
        self.assertEqual(metadata["particles"], 100)
        self.assertFalse(metadata["package_generation_allowed"])
        self.assertTrue(metadata["clock"]["canonical_lineage_age_retained"])
        self.assertTrue(metadata["clock"]["canonical_particle_age_retained"])
        with self.canonical.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            self.assertEqual(reader.fieldnames, csv_columns())
            canonical = list(reader)
        with self.row_map.open("r", encoding="utf-8", newline="") as handle:
            row_map = list(csv.DictReader(handle))
        ion = [line.split(",") for line in self.ion.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(len(canonical), 100)
        self.assertEqual(canonical[0]["particle_id"], "1")
        self.assertEqual(canonical[0]["species_id"], "ion_100amu_q1")
        self.assertEqual(float(canonical[0]["particle_weight"]), 1.0)
        self.assertEqual(canonical[0]["phase_reference_id"], "rf_quadrupole_drive.v1")
        self.assertAlmostEqual(float(canonical[0]["phase_rad"]), 0.25)
        self.assertAlmostEqual(float(canonical[0]["instrument_time_us"]), 10.1)
        self.assertAlmostEqual(float(canonical[0]["lineage_age_us"]), 5.01)
        self.assertAlmostEqual(float(canonical[0]["particle_age_us"]), 5.01)
        self.assertAlmostEqual(float(canonical[0]["lineage_birth_time_us"]), 5.09)
        self.assertAlmostEqual(float(canonical[0]["particle_birth_time_us"]), 5.09)
        self.assertEqual(float(canonical[0]["mass_to_charge_Th"]), 100.0)
        self.assertEqual(float(canonical[0]["mass_amu"]), 100.0)
        self.assertAlmostEqual(float(canonical[0]["position_x_mm"]), -48.8)
        self.assertAlmostEqual(float(canonical[0]["position_y_mm"]), 0.1)
        self.assertAlmostEqual(float(canonical[0]["position_z_mm"]), -18.22918680341103)
        self.assertAlmostEqual(float(canonical[0]["velocity_x_m_s"]), 2000.0)
        self.assertAlmostEqual(float(canonical[0]["velocity_y_m_s"]), 100.0)
        self.assertAlmostEqual(float(canonical[0]["velocity_z_m_s"]), 200.0)
        self.assertEqual(row_map[0]["particle_id"], "1")
        self.assertEqual(float(row_map[0]["solver_birth_time_us"]), 0.0)
        self.assertEqual(len(ion[0]), 11)
        self.assertEqual(float(ion[0][0]), 0.0)
        self.assertEqual(float(ion[0][1]), 100.0)
        self.assertAlmostEqual(float(ion[0][3]), -48.8)
        self.assertAlmostEqual(float(ion[0][4]), 0.1)
        self.assertAlmostEqual(float(ion[0][5]), -18.22918680341103)
        self.assertAlmostEqual(
            float(ion[0][6]), math.degrees(math.atan2(-200.0, 2000.0)), delta=1e-12
        )
        self.assertAlmostEqual(
            float(ion[0][7]),
            math.degrees(math.atan2(100.0, math.hypot(2000.0, 200.0))),
            delta=1e-12,
        )

    def test_time_dependent_consumer_uses_instrument_time_as_solver_birth(self) -> None:
        metadata = MODULE.build_handoff(
            self.source, self.manifest, CONTRACT, self.canonical, self.ion,
            self.row_map, self.metadata, solver_clock="instrument_time",
            registration_path=REGISTRATION,
        )
        with self.row_map.open("r", encoding="utf-8", newline="") as handle:
            row_map = list(csv.DictReader(handle))
        ion = [line.split(",") for line in self.ion.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(metadata["clock"]["solver_clock"], "instrument_time")
        self.assertAlmostEqual(float(row_map[0]["solver_birth_time_us"]), 10.1)
        self.assertAlmostEqual(float(ion[0][0]), 10.1)

    def test_functional_entry_projection_uses_explicit_target_origin(self) -> None:
        target = [-62.8, 0.0, -18.42918680341103]
        metadata = MODULE.build_handoff(
            self.source, self.manifest, CONTRACT, self.canonical, self.ion,
            self.row_map, self.metadata, solver_clock="instrument_time",
            target_origin_override_mm=target, registration_path=REGISTRATION,
        )
        with self.canonical.open("r", encoding="utf-8", newline="") as handle:
            canonical = list(csv.DictReader(handle))
        self.assertTrue(metadata["diagnostics"]["target_origin_overridden"])
        self.assertEqual(metadata["diagnostics"]["target_origin_mm"], target)
        self.assertAlmostEqual(float(canonical[0]["position_x_mm"]), -62.8)

    def test_manifest_hash_is_required(self) -> None:
        manifest = json.loads(self.manifest.read_text(encoding="utf-8"))
        manifest["outputs"][0]["sha256"] = "0" * 64
        self.manifest.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "manifest hash"):
            self.build()

    def test_verified_5ev_energy_match_profile_is_an_accepted_source(self) -> None:
        run_config = self.root / "run_config.json"
        run_config.write_text(json.dumps({
            "parameters": {
                "particle_tracking": True,
                "particle_count": 100,
                "energy_match_enabled": True,
                "source_operating_point": "rf_to_oatof_100amu_5eV",
                "end_core_hmax_mm": 0.5,
            }
        }), encoding="utf-8")
        manifest = json.loads(self.manifest.read_text(encoding="utf-8"))
        manifest["mode"] = "rf_to_oatof_energy_match_n100"
        manifest["run_config"] = {
            "path": str(run_config),
            "sha256": MODULE.sha256(run_config),
        }
        manifest["inputs"] = {
            "energy_match_contract": {
                "path": str(PROJECT_ROOT / "config" / "rf_to_oatof_energy_match_candidate.json"),
                "sha256": MODULE.sha256(
                    PROJECT_ROOT / "config" / "rf_to_oatof_energy_match_candidate.json"
                )
            }
        }
        self.manifest.write_text(json.dumps(manifest), encoding="utf-8")
        metadata = self.build()
        self.assertEqual(metadata["particles"], 100)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import csv
import importlib.util
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).parents[2]
ANALYSIS = PROJECT_ROOT / "analysis"
sys.path.insert(0, str(ANALYSIS))
SCRIPT = ANALYSIS / "build_interface_handoff.py"
SPEC = importlib.util.spec_from_file_location("build_interface_handoff", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
CONTRACT = PROJECT_ROOT / "config" / "rf_to_oatof_interface_candidate.json"


class InterfaceContractTests(unittest.TestCase):
    def test_two_boundaries_and_capture_state_remain_distinct(self) -> None:
        contract = MODULE.validate_contract(CONTRACT)["contract"]
        boundaries = contract["boundaries"]
        self.assertEqual(boundaries["source_exit_surface"]["status"], "defined_by_source_component")
        self.assertEqual(
            boundaries["target_entry_surface"]["status"],
            "blocked_by_closed_accelerator_shield",
        )
        self.assertIsNone(boundaries["target_entry_surface"]["physical_aperture"])
        self.assertFalse(boundaries["target_entry_surface"]["reference_surface_is_an_opening"])
        self.assertEqual(boundaries["pulse_capture_state"]["status"], "unresolved")
        self.assertFalse(boundaries["pulse_capture_state"]["stored_by_default"])
        self.assertFalse(contract["target_reference_distribution"]["hard_acceptance"])
        self.assertFalse(contract["package_generation_allowed"])

    def test_target_entry_reference_is_derived_from_the_closed_shield(self) -> None:
        validated = MODULE.validate_contract(CONTRACT)
        reference = MODULE.derive_oatof_entry_reference(validated["target_baseline"])
        self.assertEqual(reference["center_mm"], [-67.8, 0.0, -18.42918680341103])
        self.assertEqual(reference["shield_inner_face_x_mm"], -63.8)
        self.assertEqual(reference["shield_outer_face_x_mm"], -67.8)
        self.assertEqual(reference["shield_wall_thickness_mm"], 4.0)
        audit = validated["contract"]["connector"]["target_entry_topology_audit"]
        self.assertEqual(audit["status"], "FAIL")
        self.assertIn("no physical +x injection opening", audit["conclusion"])

    def test_entry_aperture_is_theory_bounded_before_candidate_selection(self) -> None:
        contract = MODULE.validate_contract(CONTRACT)["contract"]
        aperture = contract["connector"]["entry_aperture_design"]
        self.assertEqual(aperture["status"], "blocked_pending_theoretical_feasibility")
        self.assertIsNone(aperture["shape"])
        self.assertIsNone(aperture["design_semi_axes_mm"])
        self.assertFalse(aperture["unconstrained_candidate_scan_allowed"])
        self.assertEqual(
            aperture["upper_bounds"]["first_gap_geometry"][
                "absolute_axial_semi_height_ceiling_mm"
            ],
            1.5,
        )
        longitudinal = aperture["upper_bounds"]["coupled_longitudinal_envelope"]
        self.assertEqual(
            longitudinal["required_theory_model_id"],
            "oatof.oaaccelerator_reflectron_coupled.ideal_1d.v1",
        )
        self.assertIn("tau_A+tau_R", longitudinal["focus_conditions"])
        self.assertEqual(longitudinal["axial_full_height_ceiling_mm"], 1.0)
        self.assertEqual(longitudinal["axial_semi_height_ceiling_mm"], 0.5)
        self.assertEqual(
            aperture["upper_bounds"]["current_known_axial_full_height_ceiling_mm"], 1.0
        )
        self.assertIsNone(aperture["upper_bounds"]["combined_upper_bound_mm"])

    def test_entry_aperture_l0_gap_and_tube_bounds(self) -> None:
        l0 = MODULE.entry_aperture_l0
        self.assertEqual(
            l0.gap_semi_height_ceiling_mm(-19.92918680341103, -16.92918680341103,
                                          -18.42918680341103),
            1.5,
        )
        self.assertAlmostEqual(
            l0.gap_semi_height_ceiling_mm(-19.92918680341103, -16.92918680341103,
                                          -18.42918680341103, 0.2),
            1.3,
        )
        epsilon = math.exp(-l0.J0_FIRST_ZERO * 2.0)
        self.assertAlmostEqual(l0.grounded_circular_tube_radius_ceiling_mm(4.0, epsilon), 2.0)
        unresolved = l0.evaluate_entry_aperture_l0(
            repeller_z_mm=-19.92918680341103,
            grid1_z_mm=-16.92918680341103,
            entry_center_z_mm=-18.42918680341103,
        )
        self.assertEqual(unresolved["absolute_gap_semi_height_ceiling_mm"], 1.5)
        self.assertIsNone(unresolved["combined_l0_upper_bound_mm"])
        self.assertFalse(unresolved["final_design_value_available"])
        full_width = l0.coupled_longitudinal_full_width_ceiling_mm(
            nominal_energy_per_charge_v=2000.0,
            field1_v_per_mm=160.0,
            reflectron_stage1_voltage_drop_v=1628.8001,
            reflectron_stage2_field_v_per_mm=(2531.1999 - 1628.8001) / 96.1563,
            reflectron_stage2_length_mm=96.1563,
            stage2_margin_fraction=1.0,
        )
        self.assertEqual(full_width, 1.0)

    def test_future_aperture_candidate_must_fit_frozen_interval(self) -> None:
        l0 = MODULE.entry_aperture_l0
        safe_upper = l0.validate_feasible_axial_aperture(
            design_full_height_mm=0.7,
            required_full_height_mm=0.6,
            theoretical_full_height_bounds_mm=[1.0, 3.0],
            safety_factor=0.8,
        )
        self.assertEqual(safe_upper, 0.8)
        with self.assertRaisesRegex(ValueError, "strictly below"):
            l0.validate_feasible_axial_aperture(
                design_full_height_mm=0.8,
                required_full_height_mm=0.6,
                theoretical_full_height_bounds_mm=[1.0, 3.0],
                safety_factor=0.8,
            )

    def test_entry_aperture_l0_rejects_invalid_inputs(self) -> None:
        l0 = MODULE.entry_aperture_l0
        with self.assertRaisesRegex(ValueError, "no positive"):
            l0.gap_semi_height_ceiling_mm(-1.5, 1.5, 0.0, 1.5)
        with self.assertRaisesRegex(ValueError, "strictly between"):
            l0.grounded_circular_tube_radius_ceiling_mm(4.0, 1.0)
        with self.assertRaisesRegex(ValueError, "supplied together"):
            l0.evaluate_entry_aperture_l0(
                repeller_z_mm=-1.5,
                grid1_z_mm=1.5,
                entry_center_z_mm=0.0,
                effective_tube_length_mm=4.0,
            )

    def test_canonical_columns_exclude_derived_quantities(self) -> None:
        contract = MODULE.validate_contract(CONTRACT)["contract"]
        derived = set(contract["state_transfer"]["derived_not_stored"])
        self.assertFalse(derived.intersection(MODULE.EVENT_COLUMNS))
        self.assertNotIn("kinetic_energy_eV", MODULE.EVENT_COLUMNS)
        self.assertNotIn("rf_phase_rad", MODULE.EVENT_COLUMNS)
        self.assertNotIn("divergence_angle_deg", MODULE.EVENT_COLUMNS)

    def test_relative_pose_is_unresolved_and_not_duplicated(self) -> None:
        registration = MODULE.validate_contract(CONTRACT)["contract"]["spatial_registration"]
        self.assertEqual(registration["status"], "unresolved")
        self.assertIsNone(registration["source_component_pose"]["translation_mm"])
        self.assertIsNone(registration["target_component_pose"]["translation_mm"])
        self.assertIsNone(registration["derived_target_from_source_pose"]["translation_mm"])
        self.assertIn("teleport", registration["rigid_transform_rules"]["physical_policy"])

    def test_relative_pose_is_derived_from_component_poses(self) -> None:
        identity = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
        relative = MODULE.derive_target_from_source_pose(
            identity, [10.0, 2.0, 0.0], identity, [4.0, -1.0, 0.0]
        )
        self.assertEqual(relative["rotation_source_to_target"], identity)
        self.assertEqual(relative["translation_mm"], [6.0, 3.0, 0.0])

    def test_rigid_transform_rotates_velocity_but_only_translates_position(self) -> None:
        rotation = [[0.0, -1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]]
        transformed = MODULE.transform_phase_space(
            [1.0, 0.0, 0.0], [100.0, 0.0, 0.0], rotation, [10.0, 20.0, 30.0]
        )
        self.assertEqual(transformed["position_mm"], [10.0, 21.0, 30.0])
        self.assertEqual(transformed["velocity_m_s"], [0.0, 100.0, 0.0])
        with self.assertRaisesRegex(ValueError, "right handed"):
            MODULE.validate_rotation_matrix(
                [[-1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
            )

    def test_time_rebase_and_field_free_snapshot(self) -> None:
        event = {
            "instrument_time_us": 12.0,
            "position_x_mm": 1.0,
            "position_y_mm": 2.0,
            "position_z_mm": 3.0,
            "velocity_x_m_s": 1000.0,
            "velocity_y_m_s": -2000.0,
            "velocity_z_m_s": 500.0,
        }
        self.assertEqual(MODULE.solver_local_time_us(12.0, 10.0), 2.0)
        with self.assertRaisesRegex(ValueError, "precedes"):
            MODULE.solver_local_time_us(9.0, 10.0)
        self.assertIsNone(MODULE.field_free_snapshot(event, 11.0))
        snapshot = MODULE.field_free_snapshot(event, 14.0)
        assert snapshot is not None
        self.assertEqual(snapshot["position_x_mm"], 3.0)
        self.assertEqual(snapshot["position_y_mm"], -2.0)
        self.assertEqual(snapshot["position_z_mm"], 4.0)


class ExitEventBuildTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "particle_state.csv"
        legacy = MODULE.legacy
        fieldnames = sorted(legacy.REQUIRED_SOURCE_COLUMNS)
        vx, vy, vz = 100.0, 200.0, 2000.0
        energy = (
            0.5 * 100.0 * legacy.ATOMIC_MASS_KG * (vx**2 + vy**2 + vz**2)
            / legacy.ELEMENTARY_CHARGE_C
        )
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
                    "velocity_axial_m_s": vz,
                    "velocity_x_m_s": vx,
                    "velocity_y_m_s": vy,
                    "kinetic_energy_eV": energy,
                })
        self.manifest = self.root / "run_manifest.json"
        self.manifest.write_text(json.dumps({
            "project": "rf_quadrupole_collision_cooling",
            "mode": "transport_interface_readiness",
            "status": "success",
            "inputs": {
                "baseline": {"sha256": legacy.sha256(PROJECT_ROOT / "config" / "baseline.json")},
                "mode": {"sha256": legacy.sha256(PROJECT_ROOT / "config" / "modes" / "transport_interface_readiness.json")},
                "interface_contract": {"sha256": legacy.sha256(PROJECT_ROOT / "config" / "interface_contract.json")},
            },
            "outputs": [{"path": str(self.source), "sha256": legacy.sha256(self.source)}],
        }), encoding="utf-8")
        self.events = self.root / "source_exit_events.csv"
        self.metadata = self.root / "source_exit_metadata.json"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_build_is_compact_lossless_and_sorted(self) -> None:
        metadata = MODULE.build_exit_events(
            self.source, self.manifest, CONTRACT, self.events, self.metadata
        )
        with self.events.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            rows = list(reader)
            self.assertEqual(reader.fieldnames, MODULE.EVENT_COLUMNS)
        self.assertEqual(len(rows), 100)
        self.assertEqual(rows[0]["particle_id"], "1")
        self.assertEqual(rows[0]["species_id"], "ion_100amu_z1")
        self.assertAlmostEqual(float(rows[0]["instrument_time_us"]), 10.1)
        self.assertAlmostEqual(float(rows[0]["lineage_birth_time_us"]), 5.09)
        self.assertAlmostEqual(float(rows[0]["position_z_mm"]), 90.2)
        self.assertAlmostEqual(float(rows[0]["velocity_z_m_s"]), 2000.0)
        self.assertEqual(metadata["particles"], 100)
        self.assertEqual(metadata["derived_outputs_written"], [])
        self.assertLess(metadata["diagnostics"]["maximum_energy_velocity_relative_residual"], 1e-12)
        self.assertEqual(metadata["output"]["source_exit_event_sha256"], MODULE.legacy.sha256(self.events))

    def test_backward_crossing_is_rejected(self) -> None:
        with self.source.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        rows[0]["velocity_axial_m_s"] = "-1"
        with self.source.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=sorted(MODULE.legacy.REQUIRED_SOURCE_COLUMNS), lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        manifest = json.loads(self.manifest.read_text(encoding="utf-8"))
        manifest["outputs"][0]["sha256"] = MODULE.legacy.sha256(self.source)
        self.manifest.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "forward crossing"):
            MODULE.build_exit_events(self.source, self.manifest, CONTRACT, self.events, self.metadata)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from common.contracts.machine_contracts import ContractError
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.screen_connector_gap import (
    analyze_request,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_layout import (
    derive_pulse_schedule,
    project_handoff_through_connector,
)


FIELDS = [
    "particle_id", "event", "status", "time_us", "axial_z_mm",
    "transverse_x_mm", "transverse_y_mm", "velocity_axial_m_s",
    "velocity_x_m_s", "velocity_y_m_s", "kinetic_energy_eV",
]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _connection(gap: float) -> dict[str, object]:
    return {
        "spatial_registration": {
            "rotation_upstream_to_downstream": [
                [0.0, 0.0, 1.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0],
            ],
            "translation_mm": [-149.6 - gap, 0.0, 0.0],
            "expected_gap_mm": gap,
            "actual_gap_mm": gap,
            "position_tolerance_mm": 1e-9,
        },
        "connector": {"length_mm": gap},
        "transition_aperture": {
            "center_mm": [-69.0, 0.0, 0.0],
            "full_width_mm": 1.0,
            "full_height_mm": 0.9,
        },
    }


def _rows() -> list[dict[str, object]]:
    rows = []
    for particle_id, y, z, vy, vz in (
        (1, 0.0, 0.0, 10.0, 20.0),
        (2, 0.1, -0.1, -20.0, 10.0),
        (3, -0.1, 0.1, 15.0, -10.0),
    ):
        rows.append({
            "particle_id": particle_id, "event": "source", "status": "alive",
            "time_us": 0.0, "axial_z_mm": -1.5,
            "transverse_x_mm": y / 2, "transverse_y_mm": z / 2,
            "velocity_axial_m_s": 2000.0, "velocity_x_m_s": vy / 2,
            "velocity_y_m_s": vz / 2, "kinetic_energy_eV": 2.0,
        })
        rows.append({
            "particle_id": particle_id, "event": "handoff", "status": "transmitted",
            "time_us": 40.0 + particle_id, "axial_z_mm": 80.6,
            "transverse_x_mm": y, "transverse_y_mm": z,
            "velocity_axial_m_s": 4000.0, "velocity_x_m_s": vy,
            "velocity_y_m_s": vz, "kinetic_energy_eV": 9.0,
        })
    return rows


class ConnectorGapScreenTests(unittest.TestCase):
    def test_gap_zero_projection_is_exact_no_drift(self) -> None:
        handoff = [row for row in _rows() if row["event"] == "handoff"]
        projected = project_handoff_through_connector(
            handoff, _connection(0.0), {"geometry_mm": {"accelerator_shield_wall": 0.2}}
        )
        first = projected["finite_wall_survivors"][0]
        self.assertEqual(first["outer_y_mm"], first["handoff_y_mm"])
        self.assertEqual(first["outer_z_mm"], first["handoff_z_mm"])
        self.assertEqual(first["entry_time_us"], 41.0)
        self.assertEqual([row["particle_id"] for row in projected["finite_wall_survivors"]], [1, 2, 3])

    def test_screen_reads_fixed_matrix_and_reports_stage_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "state.csv"
            with state.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
                writer.writeheader(); writer.writerows(_rows())
            geometry = root / "geometry.json"
            geometry.write_text(json.dumps({"geometry_mm": {"accelerator_shield_wall": 0.2}}))
            candidate_records = []
            for gap in (0.0, 1.0):
                path = root / f"connection_{gap}.json"
                path.write_text(json.dumps(_connection(gap)))
                candidate_records.append({
                    "gap_mm": gap,
                    "resolved_connection": {"path": str(path), "sha256": _sha(path)},
                })
            request = root / "request.json"
            request.write_text(json.dumps({
                "role": "rf_oatof_detector_blind_connector_gap_screen_request",
                "detector_results_used": False,
                "selection_uses_detector_outcome": False,
                "source_state": {"path": str(state), "sha256": _sha(state)},
                "geometry": {"path": str(geometry), "sha256": _sha(geometry)},
                "candidates": candidate_records,
            }))
            result, _ = analyze_request(request)
            self.assertEqual(result["matrix_gap_mm"], [0.0, 1.0])
            self.assertFalse(result["detector_results_used"])
            identity = result["candidates"][0]["stage_particle_identity"]
            self.assertEqual(identity["S0"]["ordered_particle_ids"], [1, 2, 3])
            self.assertIn("initial_z0_vz_residual", result["candidates"][0])
            self.assertIn("aperture_plane_geometric_residual", result["candidates"][0])

    def test_gap_zero_schedule_canonical_digest_is_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.csv"
            with state.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
                writer.writeheader(); writer.writerows(_rows())
            schedule = derive_pulse_schedule(
                state,
                _connection(0.0),
                {
                    "geometry_mm": {"accelerator_shield_wall": 0.2},
                    "particle_source": {"center_x_mm": -60.0},
                },
                {
                    "layout_profile_id": "x", "pulse_timing_method": "m",
                    "claim_status": "FUNCTIONAL",
                },
                campaign_id="c", experiment_id="e", experiment_row_sha256="A" * 64,
                population_declaration_sha256="B" * 64,
                policy={
                    "policy_id": "multipole_handoff_ballistic_centroid_v1",
                    "offset_rf_periods": 0.0, "pulse_width_us": 1.0,
                },
                rf_frequency_hz=1e6,
            )
            schedule["source_state_path"] = "<STATE>"
            digest = hashlib.sha256(json.dumps(
                schedule, sort_keys=True, separators=(",", ":")
            ).encode()).hexdigest().upper()
            self.assertEqual(
                digest,
                "6515221B1A04FF4BF7B98CD1848CD50895B422533483907DE26BD79FC1F669FB",
            )

    def test_rejects_mismatched_actual_gap(self) -> None:
        connection = _connection(1.0)
        connection["spatial_registration"]["actual_gap_mm"] = 0.5
        handoff = [row for row in _rows() if row["event"] == "handoff"]
        with self.assertRaisesRegex(ContractError, "actual gap identity"):
            project_handoff_through_connector(
                handoff, connection, {"geometry_mm": {"accelerator_shield_wall": 0.2}}
            )


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import csv
import json
from pathlib import Path
import tempfile
import unittest

from common.contracts.file_identity import file_sha256
from common.contracts.machine_contracts import ContractError, validate_schema
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.workflows.family_source_closure.publish_run import (
    INTEGRATION_ID,
    N1_RECEIPT_SCHEMA,
    N1_REQUIRED_EVENTS,
    _n1_gate_assessment,
    _publish_n1_solver_authorization_receipt,
)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _record(path: Path) -> dict[str, object]:
    return {
        "path": str(path.resolve()),
        "exists": True,
        "bytes": path.stat().st_size,
        "sha256": file_sha256(path),
    }


def _checkpoint_rows() -> list[dict[str, str]]:
    rows = []
    for index, event in enumerate(N1_REQUIRED_EVENTS):
        at_detector = event == "detector_crossing"
        rows.append(
            {
                "particle_id": "17",
                "event": event,
                "instrument_time_us": str(index),
                "x_mm": "0.1",
                "y_mm": "0.2",
                "z_mm": str(index),
                "vx_mm_per_us": "" if at_detector else "0.01",
                "vy_mm_per_us": "" if at_detector else "0.02",
                "vz_mm_per_us": "" if at_detector else "0.03",
                "survival_status": "detected" if at_detector else "alive",
            }
        )
    return rows


def _write_checkpoints(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _summary(rows: list[dict[str, str]]) -> dict[str, object]:
    return {
        "schema_version": 3,
        "role": "rf_oatof_simion_single_flight_summary",
        "status": "success",
        "census": {
            "launched": 1,
            **{event: sum(row["event"] == event for row in rows) for event in N1_REQUIRED_EVENTS},
        },
        "formal_gate_passed": False,
    }


class N1SolverAuthorizationPublicationTests(unittest.TestCase):
    def _assess(self, rows: list[dict[str, str]]) -> list[str]:
        with tempfile.TemporaryDirectory() as directory:
            checkpoints = Path(directory) / "checkpoints.csv"
            _write_checkpoints(checkpoints, rows)
            return _n1_gate_assessment(_summary(rows), checkpoints)[2]

    def test_pass_requires_one_complete_finite_detected_ordered_path(self) -> None:
        self.assertEqual(self._assess(_checkpoint_rows()), [])

    def test_missing_or_detector_zero_fails(self) -> None:
        rows = [row for row in _checkpoint_rows() if row["event"] != "detector_crossing"]
        failures = self._assess(rows)
        self.assertIn("MISSING_EVENT", failures)
        self.assertIn("DETECTOR_STATUS", failures)

    def test_duplicate_event_fails(self) -> None:
        rows = _checkpoint_rows()
        rows.append(dict(rows[4]))
        self.assertIn("DUPLICATE_EVENT", self._assess(rows))

    def test_out_of_order_event_fails(self) -> None:
        rows = _checkpoint_rows()
        rows[5]["instrument_time_us"] = "2.5"
        self.assertIn("EVENT_ORDER", self._assess(rows))

    def test_nonfinite_state_fails(self) -> None:
        rows = _checkpoint_rows()
        rows[3]["x_mm"] = "nan"
        self.assertIn("NONFINITE_STATE", self._assess(rows))

    def test_receipt_binds_child_manifest_successor_and_scientific_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            stage_dir = workspace / "artifacts/projects/integration/runs/child"
            parent = workspace / "artifacts/projects/integration/runs/parent"
            stage_dir.mkdir(parents=True)
            parent.mkdir(parents=True)
            population = stage_dir / "inputs/resolved_population_contract.json"
            summary_path = stage_dir / "summary.json"
            checkpoints = stage_dir / "results/single_flight_particle_checkpoints.csv"
            rows = _checkpoint_rows()
            _write_json(population, {"execution_population": {"particle_count": 1}})
            _write_json(summary_path, _summary(rows))
            _write_checkpoints(checkpoints, rows)
            source_identity = {
                "source_branch_id": "simion",
                "solver_id": "simion",
                "run_id": "source_run",
                "project_id": "source_project",
                "manifest_sha256": "A" * 64,
                "event_sha256": "B" * 64,
                "particle_source_sha256": "C" * 64,
                "metadata_sha256": "D" * 64,
            }
            run_config = {
                "parameters": {
                    "three_zone_candidate_sha256": "1" * 64,
                    "layout_profile_id": "three_zone_t5_primary_v1",
                    "architecture_generation_id": "three_zone_t5_frozen_primary_v1",
                    "three_zone_topology_id": "three_zone_accelerator_ideal_v1",
                    "three_zone_geometry_id": "three_zone_focus_origin_planes_v1",
                    "three_zone_frontend_electrode_topology_id": "three_zone_frontend_v1",
                    "accelerator_field_profile_id": "accelerator_real_three_zone_pa_real_reflectron",
                    "three_zone_field_id": "three_zone_refined_pa_field_v1",
                    "resolved_region_field_semantic_sha256": "2" * 64,
                }
            }
            _write_json(stage_dir / "run_config.json", run_config)
            manifest = {
                "role": "simulation_run_manifest",
                "run_id": "child",
                "project": INTEGRATION_ID,
                "mode": "rf_to_oatof_simion_single_flight",
                "status": "success",
                "formal_eligible": False,
                "run_config": _record(stage_dir / "run_config.json"),
                "inputs": {"resolved_population_contract": _record(population)},
                "outputs": [_record(summary_path), _record(checkpoints)],
            }
            _write_json(stage_dir / "run_manifest.json", manifest)
            producer = {
                "experiment_id": "three_zone_n1",
                "three_zone_solver_gate": {
                    "gate_id": "three_zone_real_pa_gate_v1",
                    "stage": "n1_smoke_producer",
                },
            }
            successor = {
                "experiment_id": "three_zone_n100",
                "three_zone_solver_gate": {
                    "gate_id": "three_zone_real_pa_gate_v1",
                    "stage": "n100_solver_authorized_consumer",
                    "predecessor_experiment_id": "three_zone_n1",
                },
                "single_flight_population": {"execution_population": {"particle_count": 100}},
            }
            campaign = {
                "campaign_id": "three_zone_gate_campaign",
                "experiments": [producer, successor],
            }
            campaign_path = workspace / "simulation_repo/campaign.json"
            _write_json(campaign_path, campaign)
            output, receipt = _publish_n1_solver_authorization_receipt(
                campaign=campaign,
                campaign_path=campaign_path,
                producer=producer,
                successor=successor,
                integration_run_id="parent",
                stage={"run_id": "child", "path": stage_dir.relative_to(workspace).as_posix()},
                workspace_root=workspace,
                parent_run_dir=parent,
                source_identity=source_identity,
            )
            self.assertTrue(output.is_file())
            self.assertEqual(receipt["decision"], "PASS")
            self.assertEqual(receipt["authorization_status"], "N100_SOLVER_AUTHORIZED")
            self.assertEqual(
                receipt["producer"]["transport_manifest"]["sha256"], file_sha256(stage_dir / "run_manifest.json")
            )
            self.assertEqual(receipt["authorized_successor"]["particle_count"], 100)
            self.assertFalse(receipt["formal_gate_passed"])
            self.assertNotIn("resolution", receipt["evidence"])
            validate_schema(receipt, N1_RECEIPT_SCHEMA)

            manifest["status"] = "failed"
            _write_json(stage_dir / "run_manifest.json", manifest)
            with self.assertRaisesRegex(ContractError, "child manifest identity/status differs"):
                _publish_n1_solver_authorization_receipt(
                    campaign=campaign,
                    campaign_path=campaign_path,
                    producer=producer,
                    successor=successor,
                    integration_run_id="parent",
                    stage={
                        "run_id": "child",
                        "path": stage_dir.relative_to(workspace).as_posix(),
                    },
                    workspace_root=workspace,
                    parent_run_dir=parent,
                    source_identity=source_identity,
                )


if __name__ == "__main__":
    unittest.main()

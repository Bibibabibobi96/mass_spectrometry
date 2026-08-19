from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from common.contracts.machine_contracts import ContractError, validate_schema
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.analyze_single_flight import (
    COLUMNS as CHECKPOINT_COLUMNS,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.materialize_manifest_bound_pre_pulse_restart import (
    RECEIPT_ROLE,
    materialize,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_source import (
    GLOBAL_COLUMNS,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _record(path: Path) -> dict[str, object]:
    return {
        "path": str(path.resolve()),
        "exists": True,
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _id_sha256(values: list[int]) -> str:
    payload = json.dumps(values, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest().upper()


class ManifestBoundPrePulseRestartTest(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[Path, Path]:
        child = root / "artifacts/projects/integration/runs/child"
        inputs = child / "inputs"
        results = child / "results"
        inputs.mkdir(parents=True)
        results.mkdir()

        run_config = child / "run_config.json"
        run_config.write_text("{}\n", encoding="utf-8")
        initial = inputs / "initial_global_state.csv"
        with initial.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle, fieldnames=GLOBAL_COLUMNS, lineterminator="\n"
            )
            writer.writeheader()
            for particle_id in range(1, 4):
                writer.writerow(
                    {
                        "particle_id": particle_id,
                        "instrument_time_us": "0",
                        "mass_amu": "100",
                        "charge_state": "1",
                        "position_x_mm": "-80",
                        "position_y_mm": "0",
                        "position_z_mm": "0",
                        "velocity_x_m_s": "4000",
                        "velocity_y_m_s": "0",
                        "velocity_z_m_s": "0",
                        "kinetic_energy_eV": "8.291201",
                    }
                )
        schedule = inputs / "resolved_single_flight_pulse_schedule.json"
        schedule.write_text(
            json.dumps({"pulse_effective_time_us": 50.0}) + "\n",
            encoding="utf-8",
        )
        population = inputs / "resolved_population_contract.json"
        population.write_text(
            json.dumps(
                {
                    "execution_population": {"particle_count": 3},
                    "denominators": {"population_count": 3},
                }
            )
            + "\n",
            encoding="utf-8",
        )
        geometry = inputs / "resolved_oatof_geometry.json"
        geometry.write_text('{"geometry_id":"fixture"}\n', encoding="utf-8")
        checkpoints = results / "single_flight_particle_checkpoints.csv"
        with checkpoints.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle, fieldnames=CHECKPOINT_COLUMNS, lineterminator="\n"
            )
            writer.writeheader()
            for particle_id, eligibility in (
                (1, "eligible"),
                (2, "outside_transverse_bore"),
                (3, "eligible"),
            ):
                writer.writerow(
                    {
                        "particle_id": particle_id,
                        "event": "pre_pulse_state",
                        "instrument_time_us": "50",
                        "x_mm": str(-69.0 + particle_id / 10),
                        "y_mm": "0",
                        "z_mm": str(-61.0 + particle_id / 10),
                        "vx_mm_per_us": "4",
                        "vy_mm_per_us": "0",
                        "vz_mm_per_us": str(particle_id / 100),
                        "kinetic_energy_eV": "8.3",
                        "pulse_eligibility": eligibility,
                        "pulse_effective_elapsed_us": "0",
                        "survival_status": "alive",
                        "checkpoint_provenance": "native_trace",
                    }
                )
            writer.writerow(
                {
                    "particle_id": 2,
                    "event": "detector_crossing",
                    "instrument_time_us": "80",
                    "x_mm": "0",
                    "y_mm": "0",
                    "z_mm": "0",
                    "vx_mm_per_us": "0",
                    "vy_mm_per_us": "0",
                    "vz_mm_per_us": "0",
                    "kinetic_energy_eV": "0",
                    "pulse_eligibility": "",
                    "pulse_effective_elapsed_us": "30",
                    "survival_status": "detected",
                    "checkpoint_provenance": "native_trace",
                }
            )
        summary = child / "summary.json"
        summary.write_text(
            json.dumps(
                {
                    "role": "rf_oatof_simion_single_flight_summary",
                    "status": "success",
                    "observed_cohort_authority": {
                        "role": "rf_oatof_observed_paired_cohort_authority",
                        "pulse_eligible": {
                            "ordered_particle_ids": [1, 3],
                            "count": 2,
                            "ordered_particle_id_sha256": _id_sha256([1, 3]),
                        },
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )
        manifest = child / "run_manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "role": "simulation_run_manifest",
                    "run_id": "20260819_030000__sim__simion__fixture__n3",
                    "project": (
                        "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
                    ),
                    "mode": "simion_single_flight",
                    "status": "success",
                    "run_config": _record(run_config),
                    "inputs": {
                        "initial_global_state": _record(initial),
                        "pulse_schedule": _record(schedule),
                        "resolved_population_contract": _record(population),
                        "oatof_resolved_geometry": _record(geometry),
                    },
                    "outputs": [_record(summary), _record(checkpoints)],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        return manifest, checkpoints

    def test_materializes_only_detector_blind_pulse_eligible_cohort(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, _ = self._fixture(root)
            state = root / "artifacts/restart/state.csv"
            receipt_path = root / "artifacts/restart/receipt.json"
            receipt = materialize(
                child_manifest_path=manifest,
                workspace_root=root,
                state_output_path=state,
                receipt_output_path=receipt_path,
            )
            validate_schema(
                receipt,
                "rf_oatof_manifest_bound_pre_pulse_restart_materialization_receipt.schema.json",
            )
            with state.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))

        self.assertEqual(receipt["role"], RECEIPT_ROLE)
        self.assertEqual([row["particle_id"] for row in rows], ["1", "2"])
        self.assertEqual(
            receipt["selection"]["restart_to_producer_particle_id"],
            [
                {"restart_particle_id": 1, "producer_particle_id": 1},
                {"restart_particle_id": 2, "producer_particle_id": 3},
            ],
        )
        self.assertFalse(receipt["selection"]["detector_results_used"])
        self.assertEqual(
            receipt["pulse_target_state"]["ordered_particle_id_sha256"],
            _id_sha256([1, 2]),
        )
        self.assertEqual(
            receipt["reuse_scope"]["allowed_variation_axes"],
            [
                "time_integration_profile_id",
                "post_pulse_accelerator_field_profile_id",
            ],
        )

    def test_accepts_real_family_single_flight_manifest_mode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, _ = self._fixture(root)
            document = json.loads(manifest.read_text(encoding="utf-8"))
            document["mode"] = "rf_to_oatof_simion_single_flight"
            manifest.write_text(json.dumps(document) + "\n", encoding="utf-8")
            receipt = materialize(
                child_manifest_path=manifest,
                workspace_root=root,
                state_output_path=root / "artifacts/restart/state.csv",
                receipt_output_path=root / "artifacts/restart/receipt.json",
            )

        self.assertEqual(receipt["status"], "PASS")
        self.assertEqual(receipt["selection"]["producer_particle_count"], 2)

    def test_rejects_manifest_bound_checkpoint_tamper(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, checkpoints = self._fixture(root)
            checkpoints.write_text(
                checkpoints.read_text(encoding="utf-8") + "tamper\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                ContractError, "checkpoint.*identity differs"
            ):
                materialize(
                    child_manifest_path=manifest,
                    workspace_root=root,
                    state_output_path=root / "artifacts/restart/state.csv",
                    receipt_output_path=root / "artifacts/restart/receipt.json",
                )

    def test_rejects_summary_checkpoint_cohort_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, _ = self._fixture(root)
            child = manifest.parent
            summary = child / "summary.json"
            document = json.loads(summary.read_text(encoding="utf-8"))
            document["observed_cohort_authority"]["pulse_eligible"] = {
                "ordered_particle_ids": [1],
                "count": 1,
                "ordered_particle_id_sha256": _id_sha256([1]),
            }
            summary.write_text(json.dumps(document) + "\n", encoding="utf-8")
            manifest_document = json.loads(manifest.read_text(encoding="utf-8"))
            manifest_document["outputs"][0] = _record(summary)
            manifest.write_text(
                json.dumps(manifest_document) + "\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(
                ContractError, "checkpoint pulse-eligible cohort differs"
            ):
                materialize(
                    child_manifest_path=manifest,
                    workspace_root=root,
                    state_output_path=root / "artifacts/restart/state.csv",
                    receipt_output_path=root / "artifacts/restart/receipt.json",
                )


if __name__ == "__main__":
    unittest.main()

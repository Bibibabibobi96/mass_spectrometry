from __future__ import annotations

import csv
import hashlib
import json
import math
import tempfile
import unittest
from pathlib import Path

from common.contracts.particle_physics import kinetic_energy_ev
from common.contracts.machine_contracts import validate_schema
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.observed_pre_pulse_projection import OBSERVED_COLUMNS, TARGET_COLUMNS, project_observed_pre_pulse_states

REPO = Path(__file__).resolve().parents[3]
ARTIFACTS = REPO.parent / "artifacts" / "projects"

def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


class ObservedPrePulseProjectionTests(unittest.TestCase):
    def _fixture(self, root: Path) -> dict[str, Path]:
        paths = {name: root / name for name in (
            "manifest.json", "prepared.json", "observed.csv", "geometry.json",
            "target.csv", "subset.json", "full.csv", "collapsed.csv", "receipt.json",
        )}
        paths["manifest.json"].write_text(json.dumps({
            "role": "simulation_run_manifest",
            "run_id": "20260811_003000__sim__simion__rf-oatof-exact-formal-field-bridge__n1000",
            "project": "rf_octupole_ion_optics",
            "mode": "rf_oatof_resolution_attribution_counterfactual",
            "status": "success",
        }) + "\n")
        missing = {10, 290, 298, 701}
        observed = []
        for source_id in range(1, 1001):
            if source_id in missing:
                continue
            vx, vy, vz = 4000.0 + source_id / 10, -50.0 + source_id / 20, 25.0
            observed.append({
                "simulation_particle_id": source_id,
                "source_particle_id": source_id,
                "arm_id": "observed_restart_control",
                "instrument_time_us": 45.5,
                "mass_amu": 100,
                "charge_state": 1,
                "x_mm": -70 + source_id / 1000,
                "y_mm": source_id / 2000,
                "z_mm": -18 + source_id / 3000,
                "vx_m_s": vx, "vy_m_s": vy, "vz_m_s": vz,
                "kinetic_energy_eV": kinetic_energy_ev(100, vx, vy, vz),
            })
        with paths["observed.csv"].open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=OBSERVED_COLUMNS, lineterminator="\n")
            writer.writeheader(); writer.writerows(observed)
        prepared = {
            "role": "rf_oatof_resolution_attribution_prepared_arms",
            "profile_id": "pre_pulse_phase_space_attribution_v3",
            "pulse_time_us": 45.5, "arms": [{
            "arm_id": "observed_restart_control", "particles": 996,
            "state_sha256": sha(paths["observed.csv"]),
        }]}
        paths["prepared.json"].write_text(json.dumps(prepared) + "\n")
        paths["geometry.json"].write_text(json.dumps({"particle_source": {
            "center_x_mm": -69.0, "center_y_mm": 0.0, "center_z_mm": -18.0,
        }}) + "\n")
        source_ids = [1, 11]
        target = [{
            "particle_id": index, "instrument_time_us": 44.0,
            "mass_amu": 100, "charge_state": 1,
            "position_x_mm": -69, "position_y_mm": 0, "position_z_mm": -61 + index,
            "velocity_x_m_s": 4300, "velocity_y_m_s": 0,
            "velocity_z_m_s": index, "kinetic_energy_eV": 10,
        } for index in (1, 2)]
        with paths["target.csv"].open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=TARGET_COLUMNS, lineterminator="\n")
            writer.writeheader(); writer.writerows(target)
        subset = {
            "resolved_target_center_mm": [-69.0, 0.0, -61.0],
            "resolved_pulse_time_us": 44.0,
            "selection": {"simulation_to_source_particle_id": [
                {"simulation_particle_id": i, "source_particle_id": sid}
                for i, sid in enumerate(source_ids, 1)
            ]},
            "pulse_target_state": {"sha256": sha(paths["target.csv"])},
        }
        paths["subset.json"].write_text(json.dumps(subset) + "\n")
        return paths

    def test_projects_full_and_collapsed_arms_with_strict_pairing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            p = self._fixture(Path(directory))
            receipt = project_observed_pre_pulse_states(
                authority_manifest_path=p["manifest.json"],
                prepared_arms_path=p["prepared.json"], observed_state_path=p["observed.csv"],
                old_geometry_path=p["geometry.json"], current_target_path=p["target.csv"],
                current_subset_receipt_path=p["subset.json"], full_output_path=p["full.csv"],
                collapsed_output_path=p["collapsed.csv"], receipt_output_path=p["receipt.json"],
            )
            validate_schema(
                receipt,
                "rf_oatof_observed_pre_pulse_projection_receipt.schema.json",
            )
            with p["full.csv"].open(encoding="utf-8", newline="") as handle:
                full = list(csv.DictReader(handle))
            with p["collapsed.csv"].open(encoding="utf-8", newline="") as handle:
                collapsed = list(csv.DictReader(handle))
            self.assertEqual(receipt["projection"]["translation_mm"], [0.0, 0.0, -43.0])
            self.assertEqual(receipt["projection"]["simulation_to_source_particle_id"][1]["source_particle_id"], 11)
            self.assertAlmostEqual(float(full[0]["position_z_mm"]), -60.99966666666667)
            self.assertEqual(full[0]["instrument_time_us"], "44")
            self.assertEqual(collapsed[0]["position_x_mm"], "-69")
            self.assertEqual(collapsed[0]["position_y_mm"], "0")
            self.assertEqual(collapsed[0]["velocity_y_m_s"], "0")
            self.assertEqual(collapsed[0]["position_z_mm"], full[0]["position_z_mm"])
            self.assertEqual(collapsed[0]["velocity_z_m_s"], full[0]["velocity_z_m_s"])
            self.assertEqual(collapsed[0]["kinetic_energy_eV"], full[0]["kinetic_energy_eV"])
            self.assertAlmostEqual(float(collapsed[0]["velocity_x_m_s"]), math.hypot(
                float(full[0]["velocity_x_m_s"]), float(full[0]["velocity_y_m_s"]),
            ))

    def test_rejects_state_hash_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            p = self._fixture(Path(directory))
            prepared = json.loads(p["prepared.json"].read_text())
            prepared["arms"][0]["state_sha256"] = "0" * 64
            p["prepared.json"].write_text(json.dumps(prepared))
            with self.assertRaisesRegex(ValueError, "does not bind"):
                project_observed_pre_pulse_states(
                    authority_manifest_path=p["manifest.json"],
                    prepared_arms_path=p["prepared.json"], observed_state_path=p["observed.csv"],
                    old_geometry_path=p["geometry.json"], current_target_path=p["target.csv"],
                    current_subset_receipt_path=p["subset.json"], full_output_path=p["full.csv"],
                    collapsed_output_path=p["collapsed.csv"], receipt_output_path=p["receipt.json"],
                )

    def test_real_authority_projects_current_n100_when_artifacts_exist(self) -> None:
        old_run = ARTIFACTS / "rf_octupole_ion_optics" / "runs" / (
            "20260811_003000__sim__simion__rf-oatof-exact-formal-field-bridge__n1000"
        )
        current_run = ARTIFACTS / (
            "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
        ) / "runs" / (
            "20260817_235900__sim__cross__three-zone-segmented-rings-real-pa-full-width__n100"
        )
        required = [old_run / "run_manifest.json", current_run / "run_manifest.json"]
        if not all(path.is_file() for path in required):
            self.skipTest("local historical artifacts are unavailable")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt = project_observed_pre_pulse_states(
                authority_manifest_path=old_run / "run_manifest.json",
                prepared_arms_path=old_run / "inputs/counterfactual_arms/prepared_arms.json",
                observed_state_path=old_run / "inputs/counterfactual_arms/observed_restart_control__source_state.csv",
                old_geometry_path=old_run / "inputs/oatof_resolved_geometry.json",
                current_target_path=current_run / "inputs/single_flight_pre_pulse_ordered_subset.csv",
                current_subset_receipt_path=current_run / "inputs/single_flight_pre_pulse_ordered_subset_receipt.json",
                full_output_path=root / "full.csv",
                collapsed_output_path=root / "collapsed.csv",
                receipt_output_path=root / "receipt.json",
            )
            validate_schema(
                receipt,
                "rf_oatof_observed_pre_pulse_projection_receipt.schema.json",
            )
            with (root / "full.csv").open(encoding="utf-8", newline="") as handle:
                full = list(csv.DictReader(handle))
            with (root / "collapsed.csv").open(encoding="utf-8", newline="") as handle:
                collapsed = list(csv.DictReader(handle))
            self.assertEqual(len(full), 100)
            self.assertEqual(len(collapsed), 100)
            self.assertEqual(
                receipt["authorities"]["observed_state"]["sha256"],
                "4BCA44684CA3EA533775C20BA04AD34BD36FD9F31B9CB0DF08C8A1BA26583EEC",
            )
            self.assertEqual(
                [item["source_particle_id"] for item in receipt["projection"]["simulation_to_source_particle_id"]][0:2],
                [1, 11],
            )
            for observed, collapsed_row in zip(full, collapsed):
                for field in ("position_z_mm", "velocity_z_m_s", "kinetic_energy_eV", "instrument_time_us"):
                    self.assertEqual(observed[field], collapsed_row[field])
                self.assertEqual(collapsed_row["position_x_mm"], "-69.013621843807044")
                self.assertEqual(collapsed_row["position_y_mm"], "0")
                self.assertEqual(collapsed_row["velocity_y_m_s"], "0")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.workflows.family_source_closure import (
    derive_post_pulse_successor as subject,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_source import (
    ATTRIBUTION_COLUMNS,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


class DerivePostPulseSuccessorTests(unittest.TestCase):
    def test_derives_campaign_from_compact_n1_subset_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parent = root / "parent"
            inputs = parent / "inputs"
            inputs.mkdir(parents=True)
            (parent / "run_manifest.json").write_text(json.dumps({
                "project": "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer",
                "status": "failed",
            }), encoding="utf-8")
            experiment = {
                "experiment_id": "fixture_pre_pulse", "single_flight_layout_profile_id": "three_zone_ideal_acceptance_300mm_square_v1",
                "connection_profile_id": "rf_octupole_to_single_reflection_oatof_direct_mating_gap_102p4mm",
                "accelerator_entrance_local_aperture_mm": {"width": 1.0, "height": 1.0},
                "single_flight_population": {"execution_population": {"particle_count": 5000}, "denominators": {"population_count": 5000}},
                "single_flight_pulse_schedule_policy": {"policy_id": "multipole_handoff_ballistic_centroid_v1", "offset_rf_periods": 0, "pulse_width_us": 1},
            }
            (inputs / "frozen_campaign_experiment.json").write_text(json.dumps({"experiment": experiment}), encoding="utf-8")
            state = root / "subset.csv"
            with state.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=ATTRIBUTION_COLUMNS, lineterminator="\n")
                writer.writeheader()
                writer.writerow({
                    "simulation_particle_id": "1", "source_particle_id": "2", "arm_id": "compact_pre_pulse_trace_handoff",
                    "instrument_time_us": "5", "mass_amu": "100", "charge_state": "1", "x_mm": "-1", "y_mm": "0", "z_mm": "0",
                    "vx_m_s": "4000", "vy_m_s": "0", "vz_m_s": "0", "kinetic_energy_eV": "8.29",
                })
            receipt = root / "subset.json"
            receipt.write_text(json.dumps({
                "role": "rf_oatof_compact_pre_pulse_subset_receipt", "status": "success",
                "selection": {"mother_population_count": 5000},
                "pulse_target_state": {"path": str(state), "sha256": _sha256(state), "particle_count": 1,
                    "ordered_particle_id_sha256": hashlib.sha256(b"[2]").hexdigest().upper(),
                    "source_state_epoch": "pulse_effective_time", "coordinate_frame": "oatof_global_cartesian"},
            }), encoding="utf-8")
            repo_root = Path(__file__).resolve().parents[3]
            output = root / "derived.json"
            with patch.object(subject, "_workspace_relative", side_effect=lambda path, _: str(path)):
                campaign = subject.derive_campaign(repo_root=repo_root, parent_manifest_path=parent / "run_manifest.json", materialization_manifest_path=None, compact_receipt_path=receipt, output_path=output)
                field_campaign = subject.derive_campaign(
                    repo_root=repo_root, parent_manifest_path=parent / "run_manifest.json",
                    materialization_manifest_path=None, compact_receipt_path=receipt,
                    output_path=root / "field.json", execution_mode="program_axis_field_export",
                )
                self.assertEqual(field_campaign["experiments"]["shared"]["single_flight_execution_mode"], "program_axis_field_export")
                self.assertIn("no particle transport", field_campaign["claim_limit"])
                self.assertEqual(field_campaign["experiments"]["shared"]["pre_pulse_source_state"], campaign["experiments"]["shared"]["pre_pulse_source_state"])
                with self.assertRaisesRegex(subject.ContractError, "unsupported post-pulse"):
                    subject.derive_campaign(
                        repo_root=repo_root, parent_manifest_path=parent / "run_manifest.json",
                        materialization_manifest_path=None, compact_receipt_path=receipt,
                        output_path=root / "invalid.json", execution_mode="unknown",
                    )
                frozen_external = root / "recovery_parent_frozen_experiment.json"
                frozen_external.write_bytes((inputs / "frozen_campaign_experiment.json").read_bytes())
                (inputs / "frozen_campaign_experiment.json").unlink()
                recovered_campaign = subject.derive_campaign(
                    repo_root=repo_root,
                    parent_manifest_path=parent / "run_manifest.json",
                    materialization_manifest_path=None,
                    compact_receipt_path=receipt,
                    output_path=root / "derived_from_recovery.json",
                    frozen_experiment_path=frozen_external,
                )
        shared = campaign["experiments"]["shared"]
        self.assertEqual(shared["single_flight_pulse_schedule_policy"]["duration_policy_id"], subject.DURATION_POLICY_ID)
        self.assertEqual(shared["single_flight_population"]["execution_population"]["particle_count"], 1)
        self.assertEqual(shared["single_flight_population"]["denominators"]["population_count"], 5000)
        self.assertEqual(shared["pre_pulse_source_state"]["particle_count"], 1)
        self.assertEqual(
            recovered_campaign["experiments"]["shared"]["single_flight_population"]
            ["execution_population"]["particle_count"],
            1,
        )

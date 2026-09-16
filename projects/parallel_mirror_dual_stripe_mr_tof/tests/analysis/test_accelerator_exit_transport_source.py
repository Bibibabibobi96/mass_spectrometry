from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.accelerator_exit_transport_source import (
    materialize_accelerator_exit_transport_source,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_handoff import (
    ProjectPhaseSpaceState,
)


class AcceleratorExitTransportSourceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.observation_path = self.root / "accelerator_exit_observation.json"
        self.receipt_path = self.root / "transport_source.json"
        self.observation = {
            "schema_version": 1,
            "role": "mrtof_accelerator_exit_observation",
            "status": "observed",
            "qualification": "source_to_accelerator_exit_diagnostic_only",
            "coordinate_frame": "project",
            "inputs": {
                "log_sha256": "1" * 64,
                "source_receipt_sha256": "2" * 64,
            },
            "safe_exit_state": {
                "ion": 1,
                "time_us": 1.85988857545,
                "position_mm": [-0.000116112867956, -52.7829141605, -5.74162639318],
                "velocity_mm_per_us": [-0.000462725978364, 1.38120414927, -39.3194789123],
                "particle_mass_th": 524.0,
                "charge_state": 1,
                "kinetic_energy_ev": 4203.306631819113,
                "from_instance": 2,
                "to_instance": 1,
            },
        }

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _write(self, observation: dict[str, object] | None = None) -> str:
        self.observation_path.write_text(
            json.dumps(self.observation if observation is None else observation, indent=2) + "\n",
            encoding="utf-8",
        )
        return hashlib.sha256(self.observation_path.read_bytes()).hexdigest()

    def _materialize(
        self, *, observation: dict[str, object] | None = None, expected_sha: str | None = None,
    ) -> tuple[ProjectPhaseSpaceState, dict[str, object]]:
        actual_sha = self._write(observation)
        return materialize_accelerator_exit_transport_source(
            observation_path=self.observation_path,
            expected_observation_sha256=actual_sha if expected_sha is None else expected_sha,
            expected_particle_mass_th=524.0,
            expected_charge_state=1,
            receipt_path=self.receipt_path,
        )

    def test_materializes_measured_full_state_and_transverse_diagnostic(self) -> None:
        state, receipt = self._materialize()
        self.assertIsInstance(state, ProjectPhaseSpaceState)
        self.assertEqual(state.position_mm, tuple(self.observation["safe_exit_state"]["position_mm"]))
        self.assertEqual(
            state.velocity_mm_per_us,
            tuple(self.observation["safe_exit_state"]["velocity_mm_per_us"]),
        )
        self.assertEqual(receipt["role"], "mrtof_two_prism_segmented_transport_source")
        self.assertEqual(receipt["status"], "materialized")
        self.assertEqual(receipt["coordinate_frame"], "project")
        self.assertEqual(receipt["particle_mass_th"], 524.0)
        self.assertEqual(receipt["charge_state"], 1)
        self.assertEqual(receipt["kinetic_energy_ev"], 4203.306631819113)
        self.assertAlmostEqual(
            sum(receipt["kinetic_energy_components_ev"][axis] for axis in "xyz"),
            receipt["kinetic_energy_components_ev"]["total"],
        )
        self.assertEqual(receipt["transverse_diagnostic"]["x_mm"], state.position_mm[0])
        self.assertEqual(
            receipt["transverse_diagnostic"]["vx_mm_per_us"], state.velocity_mm_per_us[0],
        )
        persisted = json.loads(self.receipt_path.read_text(encoding="utf-8"))
        self.assertEqual(persisted, receipt)

    def test_rejects_wrong_observation_digest(self) -> None:
        with self.assertRaisesRegex(CandidateContractError, "SHA-256 differs"):
            self._materialize(expected_sha="0" * 64)

    def test_rejects_identity_direction_species_and_missing_state(self) -> None:
        variants = []
        wrong_role = copy.deepcopy(self.observation)
        wrong_role["role"] = "other"
        variants.append(("role", wrong_role, "identity is invalid"))
        wrong_status = copy.deepcopy(self.observation)
        wrong_status["status"] = "candidate"
        variants.append(("status", wrong_status, "identity is invalid"))
        wrong_qualification = copy.deepcopy(self.observation)
        wrong_qualification["qualification"] = "formal"
        variants.append(("qualification", wrong_qualification, "identity is invalid"))
        wrong_frame = copy.deepcopy(self.observation)
        wrong_frame["coordinate_frame"] = "workbench"
        variants.append(("frame", wrong_frame, "identity is invalid"))
        wrong_direction = copy.deepcopy(self.observation)
        wrong_direction["safe_exit_state"]["velocity_mm_per_us"][2] = 0.0
        variants.append(("direction", wrong_direction, "negative project z"))
        wrong_species = copy.deepcopy(self.observation)
        wrong_species["safe_exit_state"]["particle_mass_th"] = 100.0
        variants.append(("species", wrong_species, "species differs"))
        missing_velocity = copy.deepcopy(self.observation)
        del missing_velocity["safe_exit_state"]["velocity_mm_per_us"]
        variants.append(("missing", missing_velocity, "state is incomplete"))
        inconsistent_energy = copy.deepcopy(self.observation)
        inconsistent_energy["safe_exit_state"]["kinetic_energy_ev"] += 1.0
        variants.append(("energy", inconsistent_energy, "recorded velocity components"))
        for label, observation, message in variants:
            with self.subTest(label=label):
                with self.assertRaisesRegex(CandidateContractError, message):
                    self._materialize(observation=observation)

    def test_rejects_malformed_upstream_input_hashes_and_nonfinite_state(self) -> None:
        bad_hash = copy.deepcopy(self.observation)
        bad_hash["inputs"]["log_sha256"] = "not-a-digest"
        with self.assertRaisesRegex(CandidateContractError, "log SHA-256"):
            self._materialize(observation=bad_hash)

        nonfinite = copy.deepcopy(self.observation)
        nonfinite["safe_exit_state"]["position_mm"][1] = float("nan")
        with self.assertRaisesRegex(CandidateContractError, "position\[1\]"):
            self._materialize(observation=nonfinite)


if __name__ == "__main__":
    unittest.main()

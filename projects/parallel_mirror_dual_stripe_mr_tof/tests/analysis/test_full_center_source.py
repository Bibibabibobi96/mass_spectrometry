from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from common.contracts.file_identity import file_sha256
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.full_center_source import (
    materialize_full_center_source,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)


class FullCenterSourceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.fly2 = self.root / "trial.fly2"
        self.fly2.write_text("particles {}\n", encoding="utf-8")
        self.sidecar = self.root / "trial.operating_point.lua"
        self.sidecar.write_text(
            "return { prism_voltages_v = { 177, -180 }, stop_at_drift_phase_origin = true }\n",
            encoding="utf-8",
        )
        self.trial = self.root / "trial.json"
        self.trial.write_text(json.dumps({
            "prism_voltages_v": [177.0, -180.0],
            "fly2_sha256": file_sha256(self.fly2),
            "operating_point_lua_sha256": file_sha256(self.sidecar),
        }), encoding="utf-8")
        self.operating = self.root / "operating.json"
        self.operating.write_text(json.dumps({
            "qualification": "single_center_phase_space_handoff_candidate__K25_pending",
            "selected_prism_voltages_v": [177.0, -180.0],
            "iterations": [{
                "run_id": "trial",
                "run_manifest_sha256": "a",
                "materialization_sha256": file_sha256(self.trial),
                "prism_voltages_v": [177.0, -180.0],
            }],
        }), encoding="utf-8")
        self.contract = self.root / "contract.json"
        self.contract.write_text(json.dumps({
            "particle_source": {
                "center_particle_count": 1,
                "full_mrtof_center": {"status": "pending", "publishable": False},
            },
            "nominal": {"target_oscillation_count": 25},
        }), encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _run(self) -> dict[str, object]:
        return materialize_full_center_source(
            operating_point_summary_path=self.operating,
            selected_contract_path=self.contract,
            trial_materialization_path=self.trial,
            trial_fly2_path=self.fly2,
            trial_sidecar_path=self.sidecar,
            output_contract_path=self.root / "full_contract.json",
            output_fly2_path=self.root / "full.fly2",
            output_sidecar_path=self.root / "full.operating_point.lua",
            output_manifest_path=self.root / "manifest.json",
            output_receipt_path=self.root / "receipt.json",
        )

    def test_changes_only_the_continue_flag_and_publishes_named_source(self) -> None:
        receipt = self._run()
        full_sidecar = (self.root / "full.operating_point.lua").read_text(encoding="utf-8")
        self.assertIn("stop_at_drift_phase_origin = false", full_sidecar)
        self.assertNotIn("stop_at_drift_phase_origin = true", full_sidecar)
        self.assertEqual((self.root / "full.fly2").read_bytes(), self.fly2.read_bytes())
        manifest = json.loads((self.root / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["full_mrtof_center_fly2"]["source_profile_id"], "full_mrtof_center")
        self.assertEqual(receipt["selected_prism_voltages_v"], [177.0, -180.0])

    def test_rejects_a_voltage_mismatch(self) -> None:
        operating = json.loads(self.operating.read_text(encoding="utf-8"))
        operating["selected_prism_voltages_v"] = [4000.0, 4000.0]
        self.operating.write_text(json.dumps(operating), encoding="utf-8")
        with self.assertRaises(CandidateContractError):
            self._run()


if __name__ == "__main__":
    unittest.main()

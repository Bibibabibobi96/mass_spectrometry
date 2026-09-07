from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.first_prism_l0_result import FirstPrismResultError, analyze


class FirstPrismL0ResultTest(unittest.TestCase):
    def _files(self, root: Path, accepted: str = "true") -> tuple[Path, Path, Path]:
        manifest = root / "inputs.json"
        manifest.write_text(json.dumps({"first_prism_iob_fly2": {"filename": "mrtof_first_prism_l0.fly2", "sha256": "A" * 64, "particle_count": 1, "expected_particle_ids": [1]}}), encoding="utf-8")
        receipt = root / "receipt.json"
        receipt.write_text(json.dumps({"status": "reference_static_prism_candidate__first_prism_l0_only", "target_plane_z_mm": -101, "target_plane_x_mm": 0, "target_plane_y_acceptance_mm": [35, 75]}), encoding="utf-8")
        log = root / "flight.log"
        log.write_text("MRTOF_FIRST_PRISM_EVENT interface ion=1 t_us=2.5 x_mm=-0.02 y_mm=54 z_mm=-101 x_offset_mm=-0.02 accepted_y=" + accepted + "\nMRTOF_FIRST_PRISM_EVENT terminal ion=1 splat=1 t_us=2.5 x_mm=-0.02 y_mm=54 z_mm=-101 interface_reached=true\n", encoding="utf-8")
        return log, manifest, receipt

    def test_accepts_one_complete_interface_crossing(self) -> None:
        with TemporaryDirectory() as directory:
            result = analyze(*self._files(Path(directory)))
        self.assertEqual(result["status"], "prototype_first_prism_interface_observed")
        self.assertEqual(result["interface"]["position_project_mm"], [-0.02, 54.0, -101.0])

    def test_rejects_interface_outside_accepted_y(self) -> None:
        with TemporaryDirectory() as directory:
            with self.assertRaises(FirstPrismResultError):
                analyze(*self._files(Path(directory), accepted="false"))


if __name__ == "__main__":
    unittest.main()

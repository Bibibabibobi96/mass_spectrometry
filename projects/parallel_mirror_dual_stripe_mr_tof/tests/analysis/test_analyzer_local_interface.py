from __future__ import annotations

import csv
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.analyzer_local_interface import (
    FACES,
    analyze_interface_convergence,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)


class AnalyzerLocalInterfaceTest(unittest.TestCase):
    def _input(self, root: Path, *, fine_samples: int = 10) -> Path:
        groups = [f"group_{index}" for index in range(8)]
        records = []
        for scale in (1.0, 0.5):
            for region in ("central_transport", "mirror_turn_positive"):
                for group in groups:
                    path = root / f"{scale}_{region}_{group}.csv"
                    with path.open("w", encoding="utf-8", newline="") as stream:
                        writer = csv.DictWriter(stream, fieldnames=(
                            "face", "total_nodes", "vacuum_potential_samples",
                            "field_samples", "face_physical_nodes",
                            "near_physical_vacuum_nodes",
                            "max_abs_potential_V", "rms_potential_V",
                            "max_abs_normal_field_V_per_mm", "rms_normal_field_V_per_mm",
                            "max_abs_reference_potential_V",
                            "max_abs_reference_normal_field_V_per_mm",
                        ))
                        writer.writeheader()
                        for face in FACES:
                            writer.writerow({
                                "face": face,
                                "total_nodes": fine_samples if scale == 0.5 else 10,
                                "vacuum_potential_samples": (fine_samples if scale == 0.5 else 10) - 2,
                                "field_samples": (fine_samples if scale == 0.5 else 10) - 3,
                                "face_physical_nodes": 2,
                                "near_physical_vacuum_nodes": 1,
                                "max_abs_potential_V": 1e-12,
                                "rms_potential_V": 1e-13,
                                "max_abs_normal_field_V_per_mm": scale,
                                "rms_normal_field_V_per_mm": scale / 2,
                                "max_abs_reference_potential_V": 1,
                                "max_abs_reference_normal_field_V_per_mm": 2,
                            })
                    records.append({
                        "scale_factor": scale,
                        "region": region,
                        "group": group,
                        "csv_path": str(path),
                    })
        input_path = root / "input.json"
        input_path.write_text(json.dumps({
            "role": "mrtof_analyzer_local_interface_measurement_input",
            "scale_factors": [1.0, 0.5],
            "physical_sample_spacing_mm": 1.0,
            "regions": ["central_transport", "mirror_turn_positive"],
            "response_groups": groups,
            "comparisons": records,
            "native_face_scans": records,
        }), encoding="utf-8")
        return input_path

    def test_aggregates_complete_matched_matrix(self) -> None:
        with TemporaryDirectory() as directory:
            result = analyze_interface_convergence(self._input(Path(directory)))
        self.assertEqual(result["comparison_count"], 96)
        self.assertEqual(
            result["maximum_abs_normal_field_mismatch_V_per_mm"]["fine_over_coarse"],
            0.5,
        )
        self.assertEqual(result["qualification"], "measured_interface_convergence__acceptance_threshold_not_defined")

    def test_rejects_unmatched_physical_sample_lattice(self) -> None:
        with TemporaryDirectory() as directory:
            with self.assertRaises(CandidateContractError):
                analyze_interface_convergence(
                    self._input(Path(directory), fine_samples=11)
                )


if __name__ == "__main__":
    unittest.main()

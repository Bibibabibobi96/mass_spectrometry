"""oa-TOF contract consumption of the independent accelerator provider."""
from __future__ import annotations

import json
from pathlib import Path
import unittest

from projects.orthogonal_accelerator.analysis.accelerator_time_focus import derive

PROJECT_DIR = Path(__file__).resolve().parents[2]


class AcceleratorTimeFocusTest(unittest.TestCase):
    def test_grid_aligned_candidate_preserves_global_focus(self) -> None:
        contract_path = (
            PROJECT_DIR
            / "config"
            / "candidates"
            / "accelerator_grid_aligned_strict_focus.json"
        )
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        result = derive(contract)

        for actual, expected in zip(
            result["ring_centers_local_mm"], [5.8, 8.6, 11.4, 14.2, 17.0], strict=True
        ):
            self.assertAlmostEqual(actual, expected)
        self.assertAlmostEqual(result["focus_drift_after_grid2_mm"], 0.12918680341103)
        self.assertAlmostEqual(result["assembly_translation_z_mm"], -0.098642137223724)
        self.assertAlmostEqual(
            result["focus_global_z_mm"], result["reference_global_focus_z_mm"], places=12
        )
        self.assertAlmostEqual(result["canonical_origin_shift_z_mm"], -19.8305446661873)
        self.assertAlmostEqual(result["canonical_repeller_z_mm"], -19.92918680341103)
        self.assertAlmostEqual(result["canonical_grid1_z_mm"], -16.92918680341103)
        self.assertAlmostEqual(result["canonical_grid2_z_mm"], -0.12918680341103)
        self.assertAlmostEqual(result["canonical_focus_and_detector_z_mm"], 0.0)

    def test_coupled_analyzer_uses_one_provider_implementation(self) -> None:
        from projects.single_reflection_oa_tof_mass_analyzer.analysis import oatof_oaaccelerator_coupling as consumer
        from projects.orthogonal_accelerator.analysis import accelerator_time_focus as provider

        self.assertIs(consumer.accelerator_state, provider.accelerator_state)

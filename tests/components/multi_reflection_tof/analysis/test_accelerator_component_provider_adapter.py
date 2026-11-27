"""Contract tests for MR's narrow request into the accelerator provider."""
from __future__ import annotations

import unittest
from pathlib import Path

from msplatform.workflows.oa_focus_workflow import (
    compile_workflow,
)


class AcceleratorComponentProviderAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project = Path(__file__).resolve().parents[4] / "src/msplatform/components/multi_reflection_tof"

    def test_active_mr_request_compiles_with_the_existing_common_release(self) -> None:
        request = self.project / "config" / "accelerator_component_request_n100.json"
        release = self.project / "config" / "accelerator_component_release_n100.json"
        result = compile_workflow(request, release)

        self.assertEqual(result["consumer_project_id"], "multi_reflection_tof")
        self.assertEqual(result["campaign"]["release_spec"]["geometry"]["center_mm"], [0.0, 0.0, 32.0])
        self.assertEqual(result["pa_plan"]["geometry_profile_id"], "closed_two_zone_compact_mr_axial_r3_gap1_4mm")
        self.assertEqual(result["pa_plan"]["layout"]["source_cylinder"], {"radius_mm": 1.0, "height_mm": 1.0})


if __name__ == "__main__":
    unittest.main()

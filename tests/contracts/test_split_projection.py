"""Resolved OA physical design projects to separate current component authors."""
import copy
import json
from pathlib import Path
import unittest

from msplatform import components, examples
from msplatform.components.single_reflection_oa_tof.split_projection import (
    project_split_component_requests, validate_split_study_physical_author,
)


class SplitProjectionTests(unittest.TestCase):
    def resolved(self):
        study = examples.load_example("rf_oatof_functional_v1")
        return components.resolve_component(study.component_requests["oatof"]).resolved_design

    def test_exact_existing_two_component_authors_without_input_mutation(self):
        resolved = self.resolved()
        before = copy.deepcopy(resolved)
        actual = project_split_component_requests(resolved)
        reference = json.loads((Path(__file__).resolve().parents[2] /
            "src/msplatform/examples/oa_split_tof_native_small_v1.json").read_text(encoding="utf-8"))
        self.assertEqual(actual, reference["component_requests"])
        self.assertEqual(resolved, before)
        self.assertEqual(components.resolve_component(actual["oa"]).provider_id, "orthogonal_accelerator")
        self.assertEqual(components.resolve_component(actual["tof"]).provider_id, "single_reflection_tof")

    def test_explicit_study_geometry_and_on_voltages_only(self):
        resolved = self.resolved()
        study = json.loads((Path(__file__).resolve().parents[2] /
            "src/msplatform/examples/oa_split_tof_native_small_v1.json").read_text(encoding="utf-8"))
        result = validate_split_study_physical_author(resolved, study, oa_instance_id="oa", tof_instance_id="tof")
        self.assertEqual(result["scope"], "geometry_and_on_workpoint_only")
        self.assertIn("pulse", result["not_verified"])
        for group in ("repeller", "ring_0001"):
            changed = copy.deepcopy(study)
            changed["drive"]["groups"]["oa"][group]["on_voltage_v"] += 1
            with self.subTest(group=group), self.assertRaisesRegex(ValueError, "on-workpoint voltage"):
                validate_split_study_physical_author(resolved, changed, oa_instance_id="oa", tof_instance_id="tof")
        changed = copy.deepcopy(study)
        del changed["drive"]["groups"]["tof"]["reflectron_backplate"]
        with self.assertRaisesRegex(ValueError, "electrode groups"):
            validate_split_study_physical_author(resolved, changed, oa_instance_id="oa", tof_instance_id="tof")
        changed = copy.deepcopy(study)
        changed["drive"]["pulse"]["width_us"] *= 2
        self.assertEqual(validate_split_study_physical_author(resolved, changed, oa_instance_id="oa",
            tof_instance_id="tof")["scope"], "geometry_and_on_workpoint_only")

    def test_explicit_physical_change_is_projected_and_missing_opening_rejected(self):
        resolved = self.resolved()
        original = project_split_component_requests(resolved)
        resolved["geometry_mm"]["detector_radius"] += 1.0
        changed = project_split_component_requests(resolved)
        self.assertEqual(changed["tof"]["design"]["geometry_mm"]["detector_radius"],
                         original["tof"]["design"]["geometry_mm"]["detector_radius"] + 1.0)
        self.assertEqual(changed["oa"], original["oa"])
        del resolved["mechanical_side_opening"]
        with self.assertRaisesRegex(ValueError, "explicit mechanical side opening"):
            project_split_component_requests(resolved)


if __name__ == "__main__":
    unittest.main()

"""Shared producer/consumer validation of COMSOL native detector facts."""
import copy
import unittest

from msplatform.backends.comsol.detector_facts import validate_comsol_particle_facts


class ComsolDetectorFactsTests(unittest.TestCase):
    def test_same_native_validation_accepts_exact_numeric_count(self):
        plan = {"observation_times_us":[0.0,20.0], "detector_active_face":{"surface_id":"detector_active_face"}}
        facts = {"comsol_version":"6.4", "study_completed":True, "particle_count":4.0,
            "stored_times_us":[0.0,20.0], "boundary_policy":"metal_and_outer_freeze_ideal_pass",
            "detector_faces":[3,5], "detector_observation_native":True}
        self.assertEqual(validate_comsol_particle_facts(facts, plan, particle_count=4), "6.4")
        for name, value in (("particle_count", True), ("study_completed", False),
                            ("stored_times_us", [0.0,21.0]), ("detector_faces", []),
                            ("detector_faces", [3,3]), ("detector_observation_native", False)):
            with self.subTest(name=name, value=value):
                altered = copy.deepcopy(facts)
                altered[name] = value
                with self.assertRaises(ValueError):
                    validate_comsol_particle_facts(altered, plan, particle_count=4)
        with self.assertRaises(ValueError):
            validate_comsol_particle_facts(facts, {}, particle_count=4)


if __name__ == "__main__":
    unittest.main()

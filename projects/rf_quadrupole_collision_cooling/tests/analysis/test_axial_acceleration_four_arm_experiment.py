from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from projects.rf_quadrupole_collision_cooling.analysis.generate_interface_particle_table import (
    generate_bundle,
)
from projects.rf_quadrupole_collision_cooling.analysis.validate_axial_acceleration_four_arm_experiment import (
    validate_experiment,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONTRACT = PROJECT_ROOT / "config" / "axial_acceleration_four_arm_experiment.json"
SOURCE_FAMILY = PROJECT_ROOT / "config" / "interface_readiness_particle_source.json"
DISTRIBUTION = PROJECT_ROOT / "config" / "official_particle_source.json"
RESOLVED = PROJECT_ROOT / "config" / "resolved_design_official.json"


class AxialAccelerationFourArmExperimentTests(unittest.TestCase):
    def _write_contract(self, root: Path, document: dict) -> Path:
        path = root / "experiment.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        return path

    def test_static_contract_is_valid_but_not_run_ready_without_bundle(self) -> None:
        result = validate_experiment(CONTRACT)
        self.assertEqual(result["static_contract"], "PASS")
        self.assertEqual(result["C_D_resolved_axial_drive_identity"], "PASS")
        self.assertEqual(result["acceptance_detector_z_mm"], 95.2)
        self.assertEqual(result["status"], "BLOCKED_MISSING_PAIRED_BUNDLE_METADATA")
        self.assertFalse(result["run_ready"])

    def test_real_generated_bundle_closes_static_source_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            generate_bundle(SOURCE_FAMILY, DISTRIBUTION, RESOLVED, root)
            result = validate_experiment(
                CONTRACT, bundle_metadata_path=root / "paired_particle_bundle.json"
            )
        self.assertEqual(result["status"], "READY_FOR_COMSOL_FIRST_EXECUTION")
        self.assertTrue(result["run_ready"])
        self.assertNotEqual(result["A_C_D_source_sha256"], result["B_source_sha256"])

    def test_arm_source_drift_is_rejected(self) -> None:
        document = json.loads(CONTRACT.read_text(encoding="utf-8"))
        document["arms"][2]["source_selector"] = "candidate_5eV_n100"
        with tempfile.TemporaryDirectory() as directory:
            path = self._write_contract(Path(directory), document)
            with self.assertRaisesRegex(ValueError, "binding differs"):
                validate_experiment(path)

    def test_selector_and_future_bundle_identity_drift_are_rejected(self) -> None:
        original = json.loads(CONTRACT.read_text(encoding="utf-8"))
        selector = copy.deepcopy(original)
        selector["source_selectors"]["control_2eV_n100"][
            "operating_point_id"
        ] = "rf_to_oatof_100amu_5eV"
        bundle_keys = copy.deepcopy(original)
        bundle_keys["bundle_binding"]["required_identity_keys"].remove(
            "latent_sha256"
        )
        for document in (selector, bundle_keys):
            with self.subTest(document=document), tempfile.TemporaryDirectory() as directory:
                path = self._write_contract(Path(directory), document)
                with self.assertRaises(ValueError):
                    validate_experiment(path)

    def test_loss_filtering_and_execution_reordering_are_rejected(self) -> None:
        original = json.loads(CONTRACT.read_text(encoding="utf-8"))
        mutations = []
        loss = copy.deepcopy(original)
        loss["comparison_contract"]["paired_population"]["loss_filtering_allowed"] = True
        mutations.append(loss)
        reordered = copy.deepcopy(original)
        reordered["comparison_contract"]["execution_order"][0:2] = [
            "COMSOL_B",
            "COMSOL_A",
        ]
        mutations.append(reordered)
        for document in mutations:
            with self.subTest(document=document), tempfile.TemporaryDirectory() as directory:
                path = self._write_contract(Path(directory), document)
                with self.assertRaises(ValueError):
                    validate_experiment(path)

    def test_equivalence_claim_is_blocked_until_tolerance_is_frozen(self) -> None:
        document = json.loads(CONTRACT.read_text(encoding="utf-8"))
        comparison = document["comparison_contract"]["C_vs_D"]
        comparison["reporting_mode"] = "equivalent"
        comparison["equivalence_tolerance"] = 0.1
        comparison["equivalence_claim_allowed"] = True
        with tempfile.TemporaryDirectory() as directory:
            path = self._write_contract(Path(directory), document)
            with self.assertRaisesRegex(ValueError, "delta-only"):
                validate_experiment(path)


if __name__ == "__main__":
    unittest.main()

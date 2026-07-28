from __future__ import annotations

import json
import unittest
from pathlib import Path

from common.multipole.runtime_profile import resolve_runtime_profile


PROJECT_ROOT = Path(__file__).parents[2]
REPO_ROOT = PROJECT_ROOT.parents[1]
PAIRING_CONTRACT = (
    PROJECT_ROOT
    / "config"
    / "modes"
    / "axial_acceleration_explicit_paired_diagnostic.json"
)
EXPLICIT_AXIAL_CONTRACT = (
    PROJECT_ROOT
    / "config"
    / "modes"
    / "axial_acceleration_explicit_functional_test.json"
)


class ExplicitAxialPairingContractTests(unittest.TestCase):
    def test_pairing_contract_selects_explicit_axial_input_and_two_rf_on_arms(self) -> None:
        contract = json.loads(PAIRING_CONTRACT.read_text(encoding="utf-8"))
        self.assertEqual(contract["axial_contract_file"], EXPLICIT_AXIAL_CONTRACT.name)
        self.assertEqual(
            {
                arm["arm_id"]: (
                    arm["case_id"],
                    arm["axial_scale"],
                    arm["rf_scale"],
                )
                for arm in contract["arms"]
            },
            {
                "axial_field_on": ("axial_acceleration_rf_on", 1, 1),
                "axial_field_off": ("zero_axial_drop_rf_on", 0, 1),
            },
        )
        self.assertFalse(contract["independent_5ev_source_allowed"])

    def test_single_state_legacy_runs_are_excluded_from_paired_claim(self) -> None:
        contract = json.loads(PAIRING_CONTRACT.read_text(encoding="utf-8"))
        self.assertEqual(
            set(contract["excluded_legacy_run_ids"]),
            {
                "20260723_230600__sim__simion__rf-quadrupole-explicit-axial__n100__r05",
                "20260723_231100__sim__comsol__rf-quadrupole-explicit-axial__n100__r02",
            },
        )

    def test_no_collision_workflow_cannot_select_explicit_axial_profile(self) -> None:
        entry = (
            PROJECT_ROOT
            / "workflows"
            / "no_collision_transport"
            / "run_comsol.ps1"
        ).read_text(encoding="utf-8")
        self.assertNotIn("AxialAccelerationContractPath", entry)
        self.assertNotIn("[string]$DesignProfileId", entry)
        self.assertNotIn("explicit_axial_reference", entry)
        self.assertIn("[string]$RuntimeProfileId", entry)
        for runtime_profile_id in (
            "no_acceleration_full_length",
            "segmented_rod_axial_acceleration",
            "exit_aperture_plate_acceleration",
        ):
            self.assertIn(runtime_profile_id, entry)
        resolved = resolve_runtime_profile(
            REPO_ROOT, "rf_quadrupole_ion_optics", "no_acceleration_full_length"
        )
        self.assertEqual(
            resolved["design_profile_id"], "no_acceleration_full_length"
        )
        with self.assertRaisesRegex(ValueError, "unknown runtime profile"):
            resolve_runtime_profile(
                REPO_ROOT,
                "rf_quadrupole_ion_optics",
                "explicit_axial_reference",
            )
        self.assertIn("common\\multipole\\run_finite_3d_transport.ps1", entry)


if __name__ == "__main__":
    unittest.main()

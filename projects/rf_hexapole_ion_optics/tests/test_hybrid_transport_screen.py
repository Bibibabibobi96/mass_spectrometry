from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest import mock

from common.multipole.design_profile import resolve_design_profile
from common.multipole.numerical_qualification import (
    physical_resolved_design_sha256,
)
from common.multipole.resource_budget import validate_pilot_budget
from common.multipole.runtime_profile import resolve_runtime_profile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT_ROOT.parents[1]
CONFIG_ROOT = PROJECT_ROOT / "config"
QUALIFICATION_ROOT = CONFIG_ROOT / "qualification"
PROJECT_ID = "rf_hexapole_ion_optics"
RUNTIME_PROFILE_ID = (
    "exit_aperture_plate_acceleration_n100_hybrid_transport_screen"
)
NUMERICS_PROFILE_ID = "hybrid_d2_transport_screen"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class HybridTransportScreenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.preregistration = load(
            QUALIFICATION_ROOT
            / "comsol_hybrid_transport_screen_preregistration.json"
        )
        cls.budget_path = QUALIFICATION_ROOT / "engineering_budget.json"
        cls.budget = load(cls.budget_path)
        cls.runtime = resolve_runtime_profile(
            REPO_ROOT, PROJECT_ID, RUNTIME_PROFILE_ID
        )

    def test_single_run_scope_and_frozen_baseline(self) -> None:
        plan = self.preregistration
        self.assertEqual(plan["status"], "COMPLETED_REJECTED_RESOURCE_BUDGET")
        self.assertTrue(plan["preregistered_before_run"])
        self.assertEqual(plan["maximum_commercial_run_count"], 2)
        self.assertEqual(plan["commercial_run_count_authorized"], 0)
        self.assertEqual(plan["commercial_run_count_executed"], 2)
        self.assertEqual(plan["scope"]["runtime_profile_id"], RUNTIME_PROFILE_ID)
        self.assertEqual(plan["scope"]["particle_count"], 100)
        self.assertEqual(plan["scope"]["automatic_retry_count"], 0)
        self.assertRegex(
            plan["frozen_baseline"]["run_manifest_sha256"], r"^[A-F0-9]{64}$"
        )
        self.assertRegex(
            plan["frozen_baseline"]["parent_resolved_design_sha256"],
            r"^[A-F0-9]{64}$",
        )
        self.assertRegex(
            plan["frozen_baseline"]["particle_source_sha256"], r"^[A-F0-9]{64}$"
        )
        self.assertEqual(
            plan["frozen_baseline"]["physical_resolved_design_sha256"],
            plan["unique_change"]["candidate_physical_resolved_design_sha256"],
        )
        prior = plan["prior_attempts"]
        self.assertEqual(len(prior), 2)
        self.assertEqual(
            prior[0]["status"],
            "INCONCLUSIVE_DIAGNOSTIC_IMPLEMENTATION_FAILURE",
        )
        self.assertFalse(prior[0]["automatic_retry"])
        self.assertEqual(
            prior[1]["status"], "INCONCLUSIVE_RESOURCE_BUDGET_EXCEEDED"
        )
        self.assertFalse(prior[1]["automatic_retry"])

    def test_only_mesh_strategy_changes_from_baseline(self) -> None:
        candidate = self.runtime["solver_numerics"]["comsol"]["values"]
        baseline = resolve_runtime_profile(
            REPO_ROOT, PROJECT_ID, "exit_aperture_plate_acceleration"
        )["solver_numerics"]["comsol"]["values"]
        self.assertEqual(candidate["trajectory"], baseline["trajectory"])
        self.assertEqual(candidate["mesh"]["global_auto_level"], 6)
        self.assertEqual(
            candidate["mesh"]["strategy"],
            "physical_segment_hybrid_swept_tetra_v1",
        )
        self.assertIsNone(
            candidate["mesh"]["working_region_maximum_element_size_mm"]
        )
        self.assertEqual(
            self.runtime["design_profile_id"],
            "exit_aperture_plate_acceleration",
        )
        self.assertEqual(
            self.runtime["particle_source"]["profile_id"],
            "family_mother_sample_v1_n100",
        )
        self.assertEqual(
            self.runtime["solver_numerics"]["comsol"]["profile_id"],
            NUMERICS_PROFILE_ID,
        )
        current_resolved = resolve_design_profile(
            REPO_ROOT,
            PROJECT_ID,
            "exit_aperture_plate_acceleration",
        )["resolved_design"]
        self.assertEqual(
            physical_resolved_design_sha256(current_resolved),
            self.preregistration["unique_change"][
                "candidate_physical_resolved_design_sha256"
            ],
        )

    def test_closed_transport_identity_is_not_reauthorized_by_field_screen(self) -> None:
        with self.assertRaisesRegex(ValueError, "pilot is not authorized"):
            validate_pilot_budget(
                repo_root=REPO_ROOT,
                budget_path=self.budget_path,
                project_id=PROJECT_ID,
                solver="comsol",
                runtime_profile_id=RUNTIME_PROFILE_ID,
                design_profile_id=self.runtime["design_profile_id"],
                particle_source_path=Path(self.runtime["particle_source"]["path"]),
                retention_class="compact",
            )
        with mock.patch(
            "common.multipole.resource_budget._load",
            return_value={
                **self.budget,
                "pilot_authorization": {
                    **self.budget["pilot_authorization"],
                    "authorized": True,
                    "scope": {
                        **self.budget["pilot_authorization"]["scope"],
                        "stop_stage": self.runtime["stop_stage"],
                        "runtime_profile_id": (
                            "exit_aperture_plate_acceleration_n100_hybrid_d2_mesh_build"
                        ),
                    },
                },
            },
        ):
            with self.assertRaisesRegex(ValueError, "requested pilot identity differs"):
                validate_pilot_budget(
                    repo_root=REPO_ROOT,
                    budget_path=self.budget_path,
                    project_id=PROJECT_ID,
                    solver="comsol",
                    runtime_profile_id=RUNTIME_PROFILE_ID,
                    design_profile_id=self.runtime["design_profile_id"],
                    particle_source_path=Path(
                        self.runtime["particle_source"]["path"]
                    ),
                    retention_class="compact",
                )

    def test_claim_stays_functional_and_resource_only(self) -> None:
        plan = self.preregistration
        self.assertEqual(
            plan["continuous_diagnostics"]["qualification_status"],
            "INCONCLUSIVE_NO_SOURCED_ERROR_BUDGET",
        )
        self.assertEqual(
            plan["acceptance_authority"]["path"],
            "common/multipole/functional_transport_acceptance.json",
        )
        self.assertEqual(
            plan["engineering_gates"]["maximum_mesh_cells"], 1_000_000
        )
        for forbidden in (
            "continuous_numerical_equivalence",
            "spatial_convergence",
            "Candidate",
            "Formal",
        ):
            self.assertIn(
                forbidden, plan["decision_policy"]["forbidden_claims"]
            )
        self.assertEqual(
            plan["final_decision"]["status"],
            "REJECT_CURRENT_HYBRID_FOR_PARTICLE_TRACKING",
        )
        self.assertFalse(plan["final_decision"]["further_run_authorized"])


if __name__ == "__main__":
    unittest.main()

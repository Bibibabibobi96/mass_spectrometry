"""Contract tests for the stage-gated three-zone theory campaign."""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from projects.single_reflection_oa_tof_mass_analyzer.analysis.three_zone_theory_numeric_execution import (
    NumericStageOutcome,
    _evaluate_outer,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.three_zone_theory_experiment import (
    canonical_sha256,
    execute_stage,
    load_campaign,
    resolve_stage_plan,
    verify_resolved_plan,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CAMPAIGN_PATH = (
    PROJECT_ROOT / "config" / "experiments" / "three_zone_solver_free_funnel_v1.json"
)


class ThreeZoneCampaignContractTests(unittest.TestCase):
    """Freeze row cardinalities and non-default scientific-policy boundaries."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.campaign = json.loads(CAMPAIGN_PATH.read_text(encoding="utf-8"))
        cls.stages = {
            stage["stage_id"]: stage for stage in cls.campaign["stages"]
        }

    @staticmethod
    def _grid_count(grid: dict[str, float]) -> int:
        return round((grid["maximum"] - grid["minimum"]) / grid["step"]) + 1

    def _write_receipt(
        self,
        directory: Path,
        *,
        stage_id: str,
        conclusion: str,
        status: str = "success",
        next_stage_authorized: bool = True,
        selected_outer_points: list[dict[str, float]] | None = None,
        frozen_primary: dict[str, float] | None = None,
        best_feasible_two_zone: dict[str, float] | None = None,
    ) -> Path:
        receipt = {
            "schema_version": 1,
            "role": "oatof_three_zone_stage_receipt",
            "campaign_id": self.campaign["campaign_id"],
            "campaign_sha256": hashlib.sha256(
                CAMPAIGN_PATH.read_bytes()
            ).hexdigest().upper(),
            "stage_id": stage_id,
            "plan_sha256": "A" * 64,
            "status": status,
            "conclusion": conclusion,
            "next_stage_authorized": next_stage_authorized,
            "assessment_design_status": self.campaign["assessment_design_status"],
            "solver_execution_performed": False,
            "performance_metrics_read": False,
            "completed_rows": 1,
            "planned_rows": 1,
            "selected_outer_points": selected_outer_points or [],
            "frozen_primary": frozen_primary,
            "best_feasible_two_zone": best_feasible_two_zone,
            "report": {
                "path": str((directory / "synthetic_report.json").resolve()),
                "bytes": 1,
                "sha256": "B" * 64,
            },
            "recorded_at_utc": "2026-08-17T00:00:00+00:00",
            "claim_limit": self.campaign["claim_limit"],
        }
        path = directory / f"{stage_id}_{conclusion}.json"
        path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        return path

    def test_stage_graph_is_single_stage_only_and_t4c_is_manual_non_default(self) -> None:
        self.assertEqual(self.campaign["status"], "authorized")
        self.assertEqual(
            [stage["stage_id"] for stage in self.campaign["stages"]],
            ["T0", "T1", "T2", "G1", "T3", "T4a", "T4b", "T4c", "G2", "T5"],
        )
        self.assertEqual(self.campaign["stage_execution_mode"], "single_stage_only")
        self.assertEqual(self.campaign["automatic_retry_count"], 0)
        self.assertFalse(self.campaign["solver_execution_allowed"])
        self.assertEqual(self.stages["T4c"]["allowed_predecessors"], ["G2"])
        self.assertIn("Optionally", self.stages["T4c"]["purpose"])
        self.assertEqual(
            self.stages["G2"]["conclusions"],
            ["G2_PRIMARY_FROZEN", "G2_AUTHORIZE_OPTIONAL_FULL_GRID", "G2_STOP"],
        )

    def test_preregistered_grid_cardinalities_are_2535_41_and_625(self) -> None:
        domain = self.campaign["theory_domain"]
        self.assertAlmostEqual(
            self.campaign["fixtures"]["current_exact_baseline"]["outer"][
                "delta_v1_v"
            ],
            315.077618429449,
            delta=1e-12,
        )
        d1_count = self._grid_count(domain["d1_mm"])
        l23_count = self._grid_count(domain["l23_mm"])
        lambda_count = self._grid_count(domain["lambda"])
        delta_v1_count = self._grid_count(domain["delta_v1_v"])
        self.assertEqual(d1_count * l23_count * delta_v1_count, 2535)
        self.assertEqual(32 + 8 + 1, 41)
        self.assertEqual(5**4, 625)
        self.assertTrue(
            self.campaign["stage_design"]["T4a"][
                "include_predecessor_selected_points_in_ranking"
            ]
        )
        self.assertEqual(
            d1_count * l23_count * lambda_count * delta_v1_count, 32955
        )
        self.assertEqual(
            self.stages["T2"]["row_policy"],
            "complete_2535_two_zone_grid_plus_current_baseline",
        )
        self.assertEqual(
            self.stages["T3"]["row_policy"],
            "revised_32_three_zone_plus_8_controls_plus_current_baseline",
        )
        self.assertEqual(
            self.stages["T4a"]["row_policy"],
            "deterministic_5x5x5x5_coarse_grid",
        )

    def test_root_branch_policy_never_selects_by_first_success_or_performance(self) -> None:
        policy = self.campaign["root_policy"]
        self.assertEqual(
            policy["seed_order"], "eta_hat_then_two_zone_seed;collect_all_roots"
        )
        self.assertEqual(
            policy["branch_selection"],
            "baseline_continuation_then_parameter_distance_never_performance",
        )
        self.assertEqual(
            policy["three_zone_branch_reference_fixture_id"],
            "low_contrast_c3_anchor",
        )
        self.assertEqual(
            policy["branch_distance_coordinates"], ["u", "f", "eta_hat"]
        )
        self.assertEqual(policy["branch_distance_metric"], "scaled_euclidean")
        self.assertTrue(policy["branch_selection_requires_unique_nearest"])
        self.assertTrue(policy["branch_selection_never_uses_performance"])
        self.assertEqual(
            policy["two_zone_branch_selection"], "unique_accepted_root_only"
        )
        self.assertFalse(policy["pilot_warm_start_allowed"])

    def test_post_root_composite_and_t4b_ranking_are_machine_frozen(self) -> None:
        self.assertEqual(
            self.campaign["root_policy"]["post_root_composite_audit"],
            {
                "central_difference_steps_h": [0.00005, 0.0001, 0.0002],
                "required_checks_at_each_step": [
                    "scaled_derivative_residual",
                    "full_numerical_rank",
                    "jacobian_condition_number",
                    "gamma3_uncertainty_separation",
                ],
                "require_all_checks_at_all_steps": True,
                "cross_step_quantities": ["scaled_jacobian", "gamma3_scaled"],
                "maximum_cross_step_relative_change": 0.01,
            },
        )
        t4b = self.campaign["stage_design"]["T4b"]
        self.assertEqual(t4b["contrast_tier_upper_bounds"], [3.0, 4.0, 6.0, 10.0])
        self.assertEqual(
            t4b["ranking_tuple"],
            [
                "contrast_tier_index",
                "boundary_limited",
                "target_gate_failed",
                "sigma_2p2_population_ns",
                "fwhm_2p2_ns",
                "sigma_1p0_population_ns",
                "jacobian_condition",
                "d1_mm",
                "l23_mm",
                "delta_v1_v",
                "lambda",
            ],
        )
        self.assertNotIn("ranking_policy", t4b)

    def test_engineering_envelopes_are_annotations_not_scientific_gates(self) -> None:
        annotations = self.campaign["engineering_annotations"]
        self.assertEqual(
            annotations,
            {
                "current_approved_voltage_envelope_gating": False,
                "real_fringe_gating": False,
                "manufacturing_gating": False,
            },
        )
        self.assertIn("non-gating", self.campaign["claim_limit"])

    def test_authority_hash_drift_fails_campaign_load_closed(self) -> None:
        required = {
            "three_zone_funnel_schema",
            "three_zone_resolved_plan_schema",
            "three_zone_stage_receipt_schema",
            "three_zone_stage_report_schema",
            "three_zone_theory",
            "three_zone_root_solver",
            "three_zone_numeric_execution",
            "three_zone_experiment",
            "three_zone_cli",
        }
        validated = load_campaign(CAMPAIGN_PATH)
        self.assertLessEqual(required, set(validated["authorities"]))
        for name in required:
            digest = validated["authorities"][name]["sha256"]
            self.assertEqual(digest, digest.upper())

        with tempfile.TemporaryDirectory() as temporary:
            temp_root = Path(temporary)
            drifted = copy.deepcopy(self.campaign)
            drifted["authorities"]["baseline"]["sha256"] = "0" * 64
            campaign_path = temp_root / "drifted_campaign.json"
            campaign_path.write_text(
                json.dumps(drifted, indent=2) + "\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "authority SHA-256 differs"):
                load_campaign(campaign_path, repository_root=PROJECT_ROOT.parents[1])

    def test_plan_and_individual_row_hash_tampering_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temp_root = Path(temporary)
            t0_receipt = self._write_receipt(
                temp_root,
                stage_id="T0",
                conclusion="CONTRACT_READY_FOR_ORACLE",
            )
            plan = resolve_stage_plan(
                CAMPAIGN_PATH,
                "T1",
                predecessor_receipt_path=t0_receipt,
            )

            plan_tamper = copy.deepcopy(plan)
            plan_tamper["claim_limit"] += " tampered"
            with self.assertRaisesRegex(ValueError, "plan content SHA-256 differs"):
                verify_resolved_plan(plan_tamper)

            row_tamper = copy.deepcopy(plan)
            row_tamper["rows"][0]["outer"]["d1_mm"] += 0.01
            unsigned_plan = {
                key: value
                for key, value in row_tamper.items()
                if key != "plan_sha256"
            }
            row_tamper["plan_sha256"] = canonical_sha256(unsigned_plan)
            with self.assertRaisesRegex(ValueError, "row SHA-256 differs"):
                verify_resolved_plan(row_tamper)

    def test_missing_wrong_and_g1_predecessors_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temp_root = Path(temporary)
            with self.assertRaisesRegex(ValueError, "requires a predecessor receipt"):
                resolve_stage_plan(CAMPAIGN_PATH, "T1")

            t0_receipt = self._write_receipt(
                temp_root,
                stage_id="T0",
                conclusion="CONTRACT_READY_FOR_ORACLE",
            )
            with self.assertRaisesRegex(ValueError, "predecessor stage is not allowed"):
                resolve_stage_plan(
                    CAMPAIGN_PATH,
                    "T2",
                    predecessor_receipt_path=t0_receipt,
                )

            wrong_g1 = self._write_receipt(
                temp_root,
                stage_id="G1",
                conclusion="G1_REQUIRE_SUCCESSOR_CONTRACT",
            )
            with self.assertRaisesRegex(
                ValueError, "requires explicit G1 third-direction authorization"
            ):
                resolve_stage_plan(
                    CAMPAIGN_PATH,
                    "T3",
                    predecessor_receipt_path=wrong_g1,
                )

            authorized_g1 = self._write_receipt(
                temp_root,
                stage_id="G1",
                conclusion="G1_AUTHORIZE_THIRD_DIRECTION_TEST",
            )
            t3_plan = resolve_stage_plan(
                CAMPAIGN_PATH,
                "T3",
                predecessor_receipt_path=authorized_g1,
            )
            self.assertEqual(len(t3_plan["rows"]), 41)
            self.assertEqual(
                t3_plan["manual_gate"]["conclusion"],
                "G1_AUTHORIZE_THIRD_DIRECTION_TEST",
            )

    def test_t4c_requires_the_specific_g2_manual_authorization(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temp_root = Path(temporary)
            primary = dict(self.campaign["fixtures"]["low_contrast_anchor"]["outer"])
            benchmark = {
                "d1_mm": 3.25,
                "l23_mm": 17.0,
                "lambda": 0.5,
                "delta_v1_v": 250.0,
            }
            frozen_g2 = self._write_receipt(
                temp_root,
                stage_id="G2",
                conclusion="G2_PRIMARY_FROZEN",
                frozen_primary=primary,
                best_feasible_two_zone=benchmark,
            )
            with self.assertRaisesRegex(
                ValueError, "requires predecessor conclusion"
            ):
                resolve_stage_plan(
                    CAMPAIGN_PATH,
                    "T4c",
                    predecessor_receipt_path=frozen_g2,
                )

            authorized_g2 = self._write_receipt(
                temp_root,
                stage_id="G2",
                conclusion="G2_AUTHORIZE_OPTIONAL_FULL_GRID",
            )
            t4c_plan = resolve_stage_plan(
                CAMPAIGN_PATH,
                "T4c",
                predecessor_receipt_path=authorized_g2,
            )
            self.assertEqual(len(t4c_plan["rows"]), 32955)
            self.assertEqual(
                t4c_plan["manual_gate"]["conclusion"],
                "G2_AUTHORIZE_OPTIONAL_FULL_GRID",
            )

            t5_after_g2 = resolve_stage_plan(
                CAMPAIGN_PATH,
                "T5",
                predecessor_receipt_path=frozen_g2,
            )
            self.assertEqual(
                t5_after_g2["manual_gate"]["conclusion"], "G2_PRIMARY_FROZEN"
            )
            self.assertEqual(len(t5_after_g2["rows"]), 4)
            self.assertEqual(
                [row["arm_role"] for row in t5_after_g2["rows"]],
                [
                    "three_zone_confirmation",
                    "two_zone_benchmark",
                    "paired_two_zone_control",
                    "current_exact_baseline",
                ],
            )
            self.assertEqual(
                t5_after_g2["rows"][0]["matched_control_row_id"],
                t5_after_g2["rows"][2]["row_id"],
            )
            with self.assertRaisesRegex(ValueError, "requires a frozen-primary"):
                resolve_stage_plan(
                    CAMPAIGN_PATH,
                    "T5",
                    predecessor_receipt_path=authorized_g2,
                )

            t4c_receipt = self._write_receipt(
                temp_root,
                stage_id="T4c",
                conclusion="FULL_DOMAIN_TARGET_CANDIDATE_FOUND",
                frozen_primary=primary,
                best_feasible_two_zone=benchmark,
            )
            t5_after_t4c = resolve_stage_plan(
                CAMPAIGN_PATH,
                "T5",
                predecessor_receipt_path=t4c_receipt,
            )
            self.assertIsNone(t5_after_t4c["manual_gate"])

    def test_small_numeric_stage_dispatch_publishes_mocked_outcome(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temp_root = Path(temporary)
            primary = dict(self.campaign["fixtures"]["low_contrast_anchor"]["outer"])
            benchmark = {
                "d1_mm": 3.25,
                "l23_mm": 17.0,
                "lambda": 0.5,
                "delta_v1_v": 250.0,
            }
            t4c_receipt = self._write_receipt(
                temp_root,
                stage_id="T4c",
                conclusion="FULL_DOMAIN_TARGET_CANDIDATE_FOUND",
                frozen_primary=primary,
                best_feasible_two_zone=benchmark,
            )
            plan = resolve_stage_plan(
                CAMPAIGN_PATH,
                "T5",
                predecessor_receipt_path=t4c_receipt,
            )
            outcome = NumericStageOutcome(
                status="success",
                conclusion="PRIMARY_THEORY_ONLY_SUPPORTED",
                next_stage_authorized=False,
                results={"fixture_dispatch": True},
                completed_rows=4,
                failed_rows=0,
                selected_outer_points=[primary],
                frozen_primary=primary,
                best_feasible_two_zone=benchmark,
            )
            target = (
                "projects.single_reflection_oa_tof_mass_analyzer.analysis."
                "three_zone_theory_experiment.execute_numeric_stage"
            )
            with patch(target, return_value=outcome) as dispatch:
                report, receipt = execute_stage(
                    CAMPAIGN_PATH,
                    plan,
                    temp_root / "fixture_numeric_run",
                )
            dispatch.assert_called_once()
            self.assertEqual(report["results"], {"fixture_dispatch": True})
            self.assertTrue(receipt["performance_metrics_read"])
            self.assertEqual(receipt["conclusion"], "PRIMARY_THEORY_ONLY_SUPPORTED")

    def test_t1_derivative_fixture_and_c3_branch_audit_are_explicit(self) -> None:
        expected = {
            "d1": 0.0,
            "d2": 2.541098841762901e-21,
            "d3": -1.9025154088719637e-23,
            "d4": 2.4892814297124147e-10,
        }
        anchor = self.campaign["fixtures"]["low_contrast_anchor"]
        self.assertEqual(anchor["expected_derivatives"], expected)
        evaluated = _evaluate_outer(
            self.campaign,
            anchor["outer"],
            three_zone=True,
            row_id="c3_branch_audit_fixture",
        )
        audit = evaluated.record["branch_selection_audit"]
        self.assertFalse(audit["performance_used"])
        self.assertIsNotNone(evaluated.inner)
        self.assertAlmostEqual(
            evaluated.inner.eta,
            anchor["inner"]["eta"],
            delta=1e-10,
        )

        with tempfile.TemporaryDirectory() as temporary:
            temp_root = Path(temporary)
            t0_receipt = self._write_receipt(
                temp_root,
                stage_id="T0",
                conclusion="CONTRACT_READY_FOR_ORACLE",
            )
            plan = resolve_stage_plan(
                CAMPAIGN_PATH,
                "T1",
                predecessor_receipt_path=t0_receipt,
            )
            report, _ = execute_stage(CAMPAIGN_PATH, plan, temp_root / "t1_run")
            self.assertTrue(report["results"]["derivative_fixture_passed"])

    def test_stage_execution_never_overwrites_an_existing_output_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary) / "t0_run"
            plan = resolve_stage_plan(CAMPAIGN_PATH, "T0")
            execute_stage(CAMPAIGN_PATH, plan, output_dir)
            original_receipt = (output_dir / "stage_receipt.json").read_bytes()
            with self.assertRaises(FileExistsError):
                execute_stage(CAMPAIGN_PATH, plan, output_dir)
            self.assertEqual(
                (output_dir / "stage_receipt.json").read_bytes(), original_receipt
            )

    def test_cli_t0_publishes_standard_nonformal_run_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_id = "20260817_120000__analysis__python__three-zone-t0"
            run_dir = Path(temporary) / run_id
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    (
                        "projects.single_reflection_oa_tof_mass_analyzer.workflows."
                        "three_zone_ideal_theory.run_theory"
                    ),
                    str(CAMPAIGN_PATH),
                    "--stage",
                    "T0",
                    "--output-dir",
                    str(run_dir),
                    "--execute",
                ],
                cwd=PROJECT_ROOT.parents[1],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=120,
            )
            self.assertEqual(
                completed.returncode,
                0,
                completed.stdout + completed.stderr,
            )
            manifest = json.loads(
                (run_dir / "run_manifest.json").read_text(encoding="utf-8")
            )
            self.assertFalse(manifest["formal_eligible"])
            self.assertEqual(
                {Path(item["path"]).name for item in manifest["outputs"]},
                {
                    "resolved_plan.json",
                    "stage_report.json",
                    "stage_receipt.json",
                    "summary.json",
                },
            )
            summary = json.loads(
                (run_dir / "summary.json").read_text(encoding="utf-8")
            )
            self.assertFalse(summary["formal_gate_passed"])


if __name__ == "__main__":
    unittest.main()

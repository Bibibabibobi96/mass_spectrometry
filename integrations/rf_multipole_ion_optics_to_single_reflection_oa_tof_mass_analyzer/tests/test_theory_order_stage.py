import copy
from pathlib import Path
import tempfile
import unittest

from common.contracts.machine_contracts import load_json, validate_schema
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis import (
    analyze_theory_order_stage as theory_order,
)


CAMPAIGN = (
    Path(__file__).resolve().parents[1]
    / "config"
    / "diagnostics"
    / "zero_match_long_all_ideal_theory_order_stage_v2_successor_campaign.json"
)
LEGACY_CAMPAIGN = CAMPAIGN.with_name(
    "zero_match_long_all_ideal_theory_order_stage_campaign.json"
)
SCHEMA = CAMPAIGN.parents[1] / "schemas" / "rf_oatof_theory_order_stage_campaign.schema.json"


class TheoryOrderStageTests(unittest.TestCase):
    def test_legacy_provisional_campaign_remains_byte_immutable(self):
        legacy = load_json(LEGACY_CAMPAIGN)
        validate_schema(legacy, SCHEMA)
        self.assertEqual(
            theory_order.file_sha256(LEGACY_CAMPAIGN),
            "BF539E187EDE523F055E2C8B5F91AE2FAEC84CB4E2338F14AF3CFB05803C5D2A",
        )
        self.assertEqual(
            legacy["inputs"]["phase_space_match_contract"]["sha256"],
            "B6E374251F85012DAD4633C94290C74DE912D801A7732D77C91B1BB1607FCBEB",
        )

    def test_campaign_is_schema_valid_and_rejects_unknown_fields(self):
        campaign = load_json(CAMPAIGN)
        validate_schema(campaign, SCHEMA)
        self.assertEqual(
            campaign["assessment_design_status"],
            "DECLARED_PROVISIONAL_NOT_PREREGISTERED",
        )
        self.assertIn("c3=T'''/3!", campaign["claim_limit"])
        self.assertEqual(
            campaign["campaign_id"],
            "zero_match_long_all_ideal_theory_order_stage_v2_successor",
        )
        self.assertIn("finite_interval_compiler_policy", campaign["inputs"])
        changed = copy.deepcopy(campaign)
        changed["posthoc_threshold"] = 0.5
        with self.assertRaises(Exception):
            validate_schema(
                changed, SCHEMA
            )

    def test_symmetric_multistep_audit_recovers_cubic_and_quartic(self):
        c1 = 2.0e-12
        c2 = -3.0e-12
        c3 = 4.0e-12
        c4 = -5.0e-12

        def timing(offset_mm: float) -> float:
            return (
                30.0e-6
                + c1 * offset_mm
                + c2 * offset_mm**2
                + c3 * offset_mm**3
                + c4 * offset_mm**4
                + 1.0e-14 * offset_mm**5
                + 2.0e-14 * offset_mm**6
            )

        result = theory_order._numeric_order_audit(
            timing,
            1.0,
            (0.5, 0.25, 0.125, 0.0625),
            c1,
            c2,
            {
                "numeric_floor_multiplier": 10.0,
                "absolute_time_floor_s": 1.0e-18,
                "d1_d2_effect_relative_agreement": 0.01,
                "richardson_effect_relative_convergence": 0.05,
            },
        )
        self.assertTrue(
            result["d1_numeric_audit"]["agrees_with_solver_authority"]
        )
        self.assertTrue(
            result["d2_numeric_audit"]["agrees_with_solver_authority"]
        )
        self.assertEqual(
            result["c3_numeric_taylor_coefficient_audit"]["status"],
            "CONVERGED_NUMERIC_TAYLOR_COEFFICIENT_AUDIT",
        )
        self.assertEqual(
            result["c4_numeric_taylor_coefficient_audit"]["status"],
            "CONVERGED_NUMERIC_TAYLOR_COEFFICIENT_AUDIT",
        )
        self.assertAlmostEqual(
            result["c3_numeric_taylor_coefficient_audit"]["small_step_value"],
            c3,
            delta=2.0e-15,
        )
        self.assertAlmostEqual(
            result["c4_numeric_taylor_coefficient_audit"]["small_step_value"],
            c4,
            delta=3.0e-15,
        )

    def test_bound_input_fails_closed_on_byte_mismatch(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "input.json"
            path.write_text("{}\n", encoding="utf-8")
            record = {
                "path": "input.json",
                "bytes": path.stat().st_size + 1,
                "sha256": theory_order.file_sha256(path),
            }
            with self.assertRaisesRegex(ValueError, "byte count differs"):
                theory_order._bound_json(root, record, "fixture")

    def test_coefficient_significance_uses_terminal_not_maximum_richardson_value(self):
        def timing(offset_mm: float) -> float:
            return 30.0e-6 + 1.0e-8 * offset_mm**7

        base_thresholds = {
            "numeric_floor_multiplier": 10.0,
            "absolute_time_floor_s": 1.0e-30,
            "d1_d2_effect_relative_agreement": 0.01,
            "richardson_effect_relative_convergence": 0.05,
        }
        initial = theory_order._numeric_order_audit(
            timing, 1.0, (0.5, 0.25, 0.125, 0.0625), 0.0, 0.0,
            base_thresholds,
        )
        audit = initial["c3_numeric_taylor_coefficient_audit"]
        h_min = 0.0625
        effects = [abs(value) * h_min**3 for value in audit["values"]]
        floor = (max(effects) + effects[-1]) / 2.0
        thresholds = dict(base_thresholds)
        thresholds["absolute_time_floor_s"] = floor / 10.0
        result = theory_order._numeric_order_audit(
            timing, 1.0, (0.5, 0.25, 0.125, 0.0625), 0.0, 0.0,
            thresholds,
        )["c3_numeric_taylor_coefficient_audit"]
        self.assertGreater(max(effects), floor)
        self.assertLess(effects[-1], floor)
        self.assertFalse(result["significant_above_numeric_floor"])

    def test_real_theory_report_independently_matches_all_three_widths(self):
        report = theory_order.compute_theory_order_report(CAMPAIGN)
        self.assertFalse(report["solver_execution_performed"])
        self.assertEqual(report["evidence_level"], "PROVISIONAL")
        self.assertEqual(report["status"], "PROVISIONAL_THRESHOLDS_PASSED")
        assessment = report["declared_provisional_assessment"]
        self.assertEqual(
            assessment["allowed_claim"],
            "SUPPORTED_NUMERIC_LOCAL_THIRD_AND_HIGHER_DOMINANCE",
        )
        self.assertTrue(
            assessment[
                "target_2p2mm_terminal_c3_or_c4_significant_above_numeric_floor"
            ]
        )
        self.assertTrue(assessment["cross_arm_sigma_exponents_within_2p7_to_3p3"])
        self.assertEqual(
            [arm["source_full_width_mm"] for arm in report["arms"]],
            [0.5, 1.0, 2.2],
        )
        expected = {
            0.5: (2155.7871097690413, 1843.8751188310866, 43.70135977598513,
                  1600.1891388903637, 9.21419607822776, 8.917661707518572e-12,
                  -1.5017658971146216e-09, -3.781720890039541e-10, False, False),
            1.0: (2156.2711501073695, 1843.3900290157967, 43.23958026582353,
                  1600.7337316376493, 9.217335305109735, 7.26383715449499e-11,
                  -1.510594598495449e-09, -3.789962596958096e-10, True, False),
            2.2: (2158.4115056040364, 1841.2450328856826, 41.24601972015288,
                  1603.0228996319736, 9.230574421787614, 8.458712748919988e-10,
                  -1.5515447357422659e-09, -3.844827200863079e-10, True, False),
        }
        for arm in report["arms"]:
            values = expected[arm["source_full_width_mm"]]
            match = arm["independent_theory_match"]
            for key, value in zip(
                ("repeller_v", "intermediate_v", "focus_drift_mm",
                 "reflectron_stage1_voltage_drop_v",
                 "reflectron_stage2_field_v_per_mm"), values[:5], strict=True,
            ):
                self.assertAlmostEqual(match[key], value, delta=abs(value) * 1e-13)
            self.assertAlmostEqual(
                arm["sample_metrics"]["2001"]["detector_population_sigma_s"],
                values[5], delta=abs(values[5]) * 1e-12,
            )
            c3 = arm["local_order_audit"]["c3_numeric_taylor_coefficient_audit"]
            c4 = arm["local_order_audit"]["c4_numeric_taylor_coefficient_audit"]
            self.assertAlmostEqual(c3["small_step_value"], values[6], delta=1e-20)
            self.assertAlmostEqual(c4["small_step_value"], values[7], delta=1e-20)
            self.assertIs(c3["significant_above_numeric_floor"], values[8])
            self.assertIs(c4["significant_above_numeric_floor"], values[9])
            self.assertIsNone(
                match["total_third_derivative"]
            )
            self.assertEqual(
                arm["local_order_audit"]["interpretation"],
                "D1_D2_are_solver_authorities; c3_equals_T3_over_3_factorial_and_"
                "c4_equals_T4_over_4_factorial_are_symmetric_multistep_Richardson_"
                "numeric_Taylor_coefficient_audits_not_analytic_authorities",
            )
        exponents = [
            row["sigma_log_width_exponent"]
            for row in report["cross_arm_sigma_scaling"]
        ]
        self.assertAlmostEqual(exponents[0], 3.025994482693024, places=12)
        self.assertAlmostEqual(exponents[1], 3.113515071599914, places=12)

    def test_report_schema_rejects_unlisted_claim(self):
        report = theory_order.compute_theory_order_report(CAMPAIGN)
        changed = copy.deepcopy(report)
        changed["declared_provisional_assessment"]["allowed_claim"] = "THIRD_ORDER_ONLY"
        with self.assertRaises(Exception):
            validate_schema(changed, "rf_oatof_theory_order_stage_report.schema.json")


if __name__ == "__main__":
    unittest.main()

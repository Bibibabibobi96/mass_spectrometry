from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

from common.contracts.machine_contracts import ContractError, validate_schema
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.register_n100_baseline import (
    build_receipt,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.workflows.family_source_closure.prepare import (
    validate_pulse_resolution_optimization_campaign,
    write_pulse_resolution_screening_prefix,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
INTEGRATION_ROOT = (
    REPO_ROOT
    / "integrations"
    / "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
)
CAMPAIGN_PATH = INTEGRATION_ROOT / "config" / "pulse_resolution_optimization_campaign.json"
LEGACY_CAMPAIGN_PATH = INTEGRATION_ROOT / "config" / "experiment_campaign.json"
SCHEMA_NAME = "rf_multipole_oatof_experiment_campaign.schema.json"


def load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


class PulseResolutionOptimizationCampaignTests(unittest.TestCase):
    def test_declares_complete_fail_closed_optimization_contract(self) -> None:
        campaign = load(CAMPAIGN_PATH)
        validate_schema(campaign, SCHEMA_NAME)
        validate_pulse_resolution_optimization_campaign(
            campaign, execution_requested=False
        )
        contract = campaign["pulse_resolution_optimization"]
        self.assertEqual(contract["population_contract"]["mother_sample_count"], 1000)
        self.assertEqual(contract["population_contract"]["screening_prefix_count"], 100)
        self.assertEqual(contract["population_contract"]["parallel_batch_count"], 5)
        self.assertFalse(
            contract["acceptance_window"]["selection_uses_detector_outcome"]
        )
        self.assertEqual(
            contract["acceptance_window"]["minimum_pulse_eligible_coverage"],
            0.70,
        )
        self.assertEqual(contract["bootstrap"]["resample_count"], 5000)
        self.assertEqual(
            contract["bootstrap"]["relative_interval_width_maximum"], 0.10
        )

    def test_only_arm1_registration_row_is_executable(self) -> None:
        campaign = load(CAMPAIGN_PATH)
        row = campaign["experiments"][0]
        validate_pulse_resolution_optimization_campaign(
            campaign, execution_requested=True, experiment=row
        )
        invalid = copy.deepcopy(row)
        invalid["pulse_resolution_attribution_arm_id"] = "real_beam_ideal_stage1"
        with self.assertRaisesRegex(ContractError, "not executable"):
            validate_pulse_resolution_optimization_campaign(
                campaign, execution_requested=True, experiment=invalid
            )

    def test_deterministic_prefix_is_first_100_canonical_rows(self) -> None:
        columns = [
            "particle_id", "birth_time_s", "x_mm", "y_mm", "z_mm",
            "vx_m_s", "vy_m_s", "vz_m_s", "mass_amu", "charge_state",
        ]
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "mother.csv"
            target = Path(temporary) / "prefix.csv"
            source.write_text(
                ",".join(columns) + "\n" + "\n".join(
                    f"{particle_id},0,0,0,0,0,0,1,100,1"
                    for particle_id in range(1, 1001)
                ) + "\n", encoding="utf-8"
            )
            digest = write_pulse_resolution_screening_prefix(
                source, target, mother_count=1000, prefix_count=100
            )
            rows = target.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(rows), 101)
            self.assertTrue(rows[-1].startswith("100,"))
            self.assertEqual(len(digest), 64)

    def test_registration_receipt_is_terminal_and_non_promoting(self) -> None:
        campaign = load(CAMPAIGN_PATH)
        summary = {
            "census": {"launched": 100, "detector_crossing": 95},
            "clock_basis": "absolute_birth_time",
            "resolution_time_basis": "detector_time_minus_pulse_effective_time",
            "pulse_effective_time_us": 1.25,
            "transmission": {"eligible_to_detector_fraction": 0.95},
            "pulse_effective_peak": {"mass_resolution": 8000.0},
        }
        checkpoints = [
            {"particle_id": str(particle_id), "event": "source_release"}
            for particle_id in range(1, 101)
        ]
        receipt = build_receipt(
            campaign, summary, checkpoints,
            campaign_sha256="A" * 64, experiment_row_sha256="B" * 64,
            source_identity={"particle_source_sha256": "C" * 64},
            prefix_path="inputs/pulse_resolution_arm1_all_real_screening_prefix_n100.csv",
            prefix_sha256="D" * 64, registration_authority_sha256="E" * 64,
            experiment_id="pulse_resolution_baseline",
            arm_id="real_beam_all_real",
            execution_mode="screening_prefix_n100_baseline_registration",
        )
        self.assertEqual(
            receipt["execution_status"], "baseline_registered_not_candidate"
        )
        self.assertFalse(receipt["promotion_gate_invoked"])
        self.assertFalse(receipt["formal_gate_passed"])
        self.assertEqual(receipt["prefix"]["ordered_particle_ids"], list(range(1, 101)))

    def test_adapter_and_runner_restrict_registration_prefix(self) -> None:
        adapter = (INTEGRATION_ROOT / "workflows" / "family_source_closure" /
                   "adapter.ps1").read_text(encoding="utf-8-sig")
        runner = (INTEGRATION_ROOT / "runtime" / "run_single_flight.ps1").read_text(
            encoding="utf-8-sig"
        )
        name = "pulse_resolution_arm1_all_real_screening_prefix_n100.csv"
        self.assertIn(name, adapter)
        self.assertIn(name, runner)
        self.assertIn("PulseResolutionN100Screening", runner)
        self.assertIn("baseline_registered_not_candidate", runner)
        self.assertIn("Published baseline cross/SIMION result evidence", adapter)
        self.assertIn("Published baseline checkpoints are not frozen", adapter)
        self.assertIn("pulse_resolution_baseline_result_reference.json", adapter)

    def test_only_second_paired_screening_row_is_newly_open(self) -> None:
        campaign = load(CAMPAIGN_PATH)
        candidate = campaign["experiments"][1]
        validate_pulse_resolution_optimization_campaign(
            campaign, execution_requested=True, experiment=candidate
        )
        self.assertEqual(
            candidate["experiment_id"],
            "pulse_resolution_real_beam_ideal_stage1_real_stage2_real_reflectron_n100",
        )
        self.assertEqual(
            candidate["single_flight_accelerator_field_profile_id"],
            "accelerator_ideal_stage1_real_stage2",
        )
        statuses = [
            arm["implementation_status"]
            for arm in campaign["pulse_resolution_optimization"]["attribution_arms"]
        ]
        self.assertEqual(statuses[4:], ["planning_only_until_adapter_support"] * 4)
        prepare_text = (INTEGRATION_ROOT / "workflows" / "family_source_closure" /
                        "prepare.py").read_text(encoding="utf-8-sig")
        self.assertIn(
            '+ experiment["pulse_resolution_attribution_arm_id"]', prepare_text
        )
        self.assertNotIn(
            '"pulse_resolution_attribution_arm_id=real_beam_all_real"', prepare_text
        )

    def test_third_paired_screening_is_stage1_stage2_only(self) -> None:
        campaign = load(CAMPAIGN_PATH)
        candidate = campaign["experiments"][2]
        validate_pulse_resolution_optimization_campaign(
            campaign, execution_requested=True, experiment=candidate
        )
        self.assertEqual(candidate["pulse_resolution_attribution_arm_id"],
                         "real_beam_ideal_stage1_stage2")
        self.assertEqual(candidate["single_flight_accelerator_field_profile_id"],
                         "accelerator_ideal_stage1_stage2_real_reflectron")

    def test_deprecated_hard_mask_is_blocked_and_arm8_global_field_is_open(self) -> None:
        campaign = load(CAMPAIGN_PATH)
        deprecated = campaign["experiments"][3]
        with self.assertRaisesRegex(ContractError, "deprecated hard-mask"):
            validate_pulse_resolution_optimization_campaign(
                campaign, execution_requested=True, experiment=deprecated
            )
        candidate = campaign["experiments"][4]
        validate_pulse_resolution_optimization_campaign(
            campaign, execution_requested=True, experiment=candidate
        )
        self.assertEqual(candidate["pulse_resolution_attribution_arm_id"],
                         "real_beam_all_ideal")
        self.assertEqual(candidate["single_flight_accelerator_field_profile_id"],
                         "arm8_closed_global_piecewise_theoretical_field")
        self.assertEqual(
            campaign["pulse_resolution_optimization"]["attribution_arms"][3][
                "implementation_status"
            ],
            "executable_paired_screening_with_arm8_closure",
        )
        adapter = (INTEGRATION_ROOT / "workflows" / "family_source_closure" /
                   "adapter.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("Deprecated hard-mask real-beam all-ideal", adapter)
        self.assertIn("pulse_resolution_arm8_contract_sha256", adapter)
        self.assertEqual(candidate["run_id"],
                         "20260814_000000__sim__cross__pulse-real-arm8-global-theory__n100")

    def test_rejects_arm_8_stop_rule_bound_to_another_arm(self) -> None:
        campaign = load(CAMPAIGN_PATH)
        campaign["pulse_resolution_optimization"]["screening_promotion"][
            "axial_ideal_closure_arm_id"
        ] = "finite_source_all_ideal"
        with self.assertRaisesRegex(ContractError, "bind attribution arm 8"):
            validate_pulse_resolution_optimization_campaign(
                campaign, execution_requested=False
            )

    def test_rejects_swapped_dual_acceptance_thresholds(self) -> None:
        campaign = load(CAMPAIGN_PATH)
        campaign["pulse_resolution_optimization"]["acceptance_gates"][
            "full_beam"
        ]["mass_resolution_minimum"] = 30000
        validate_schema(campaign, SCHEMA_NAME)
        with self.assertRaisesRegex(ContractError, "full_beam gate differs"):
            validate_pulse_resolution_optimization_campaign(
                campaign, execution_requested=False
            )

    def test_schema_rejects_detector_selected_or_undercoverage_window(self) -> None:
        for field, value in (
            ("selection_uses_detector_outcome", True),
            ("minimum_pulse_eligible_coverage", 0.69),
        ):
            with self.subTest(field=field):
                campaign = load(CAMPAIGN_PATH)
                campaign["pulse_resolution_optimization"]["acceptance_window"][
                    field
                ] = value
                with self.assertRaises(ContractError):
                    validate_schema(campaign, SCHEMA_NAME)

    def test_schema_rejects_relaxed_grid_and_bootstrap_limits(self) -> None:
        mutations = (
            ("grid_convergence", "mass_resolution_relative_change_maximum", 0.03),
            ("grid_convergence", "hit_rate_change_maximum_percentage_points", 2.0),
            ("bootstrap", "resample_count", 1000),
            ("bootstrap", "relative_interval_width_maximum", 0.20),
        )
        for section, field, value in mutations:
            with self.subTest(section=section, field=field):
                campaign = load(CAMPAIGN_PATH)
                campaign["pulse_resolution_optimization"][section][field] = value
                with self.assertRaises(ContractError):
                    validate_schema(campaign, SCHEMA_NAME)

    def test_legacy_campaign_remains_compatible(self) -> None:
        campaign = copy.deepcopy(load(LEGACY_CAMPAIGN_PATH))
        validate_schema(campaign, SCHEMA_NAME)
        validate_pulse_resolution_optimization_campaign(
            campaign, execution_requested=True
        )


if __name__ == "__main__":
    unittest.main()

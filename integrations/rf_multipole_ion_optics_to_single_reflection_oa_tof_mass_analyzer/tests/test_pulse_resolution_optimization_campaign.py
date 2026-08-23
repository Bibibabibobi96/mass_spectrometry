from __future__ import annotations

import copy
import csv
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from common.contracts.machine_contracts import ContractError, validate_schema
from common.contracts.file_identity import file_sha256
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.tests.fixtures.campaign_fixture import (
    current_campaign_fixture,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.register_pulse_resolution_result import (
    _canonical_sha,
    _observed_cohort_authority,
    _screening_arm,
    build_receipt,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.workflows.family_source_closure.prepare import (
    validate_pulse_resolution_optimization_campaign,
    write_pulse_resolution_screening_prefix,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.workflows.family_source_closure.refresh_campaign_source_bindings import (
    write_campaign,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
INTEGRATION_ROOT = (
    REPO_ROOT
    / "integrations"
    / "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
)
HISTORICAL_CAMPAIGNS = INTEGRATION_ROOT / "docs" / "history" / "retired_campaigns" / "root_campaigns"
BASELINE_PATH = HISTORICAL_CAMPAIGNS / "pulse_resolution_direct_baseline_successor_r09_campaign.json"
CANDIDATE_PATH = (
    HISTORICAL_CAMPAIGNS / "pulse_resolution_direct_candidate_campaign.json"
)
LEGACY_CAMPAIGN_PATH = HISTORICAL_CAMPAIGNS / "experiment_campaign.json"
SCHEMA_NAME = "rf_multipole_oatof_experiment_campaign.schema.json"
CHECKPOINT_PATH = (
    REPO_ROOT.parent
    / "artifacts"
    / "projects"
    / "rf_octupole_ion_optics"
    / "runs"
    / "20260812_210000__sim__simion__rf-oatof-single-flight-gap0__n100"
    / "results"
    / "single_flight_particle_checkpoints.csv"
)
R09_BASELINE_RECEIPT_PATH = (
    REPO_ROOT.parent
    / "artifacts"
    / "projects"
    / "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
    / "runs"
    / "20260815_160000__sim__simion__rf-oatof-single-flight-gap0__n100__r09"
    / "results"
    / "pulse_resolution_pulse_resolution_baseline_result.json"
)
R02_PROMOTION_RECEIPT_PATH = (
    REPO_ROOT.parent
    / "artifacts"
    / "projects"
    / "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
    / "runs"
    / "20260815_160100__sim__simion__rf-oatof-single-flight-gap0__n100__r02"
    / "results"
    / (
        "pulse_resolution_pulse_resolution_real_beam_ideal_stage1_"
        "real_stage2_real_reflectron_n100_promotion_receipt.json"
    )
)


def load(path: Path) -> dict[str, object]:
    return current_campaign_fixture(json.loads(path.read_text(encoding="utf-8-sig")))


def checkpoint_rows() -> list[dict[str, str]]:
    if not CHECKPOINT_PATH.is_file():
        raise unittest.SkipTest("local pulse-resolution checkpoint evidence is unavailable")
    if file_sha256(CHECKPOINT_PATH) != (
        "D46986FC918605D9EB2AD1BA059BB76F9E6AFA24156C30C20A5880375F6B9044"
    ):
        raise AssertionError("frozen checkpoint fixture identity differs")
    with CHECKPOINT_PATH.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def authorized_candidate() -> dict[str, object]:
    campaign = load(CANDIDATE_PATH)
    campaign["status"] = "authorized"
    campaign["pulse_resolution_baseline_evidence"] = {
        "authority_id": "pulse_resolution_direct_baseline_v5_r09_pulse_resolution_baseline",
        "baseline_campaign_id": "pulse_resolution_direct_baseline_v5_r09",
        "baseline_campaign_sha256": "A" * 64,
        "path": "formal/pulse_resolution_baseline_result.json",
        "sha256": "B" * 64,
    }
    campaign["preregistration"] = {
        "status": "REGISTERED_EXECUTION_REQUIRES_EXPLICIT_AUTHORIZATION",
        "document": {"path": "config/preregistration.json", "bytes": 1, "sha256": "C" * 64},
        "frozen_experiment_row_sha256": {
            row["experiment_id"]: _canonical_sha(row).upper()
            for row in campaign["experiments"]
        },
    }
    for matrix in campaign["pulse_resolution_optimization"]["comparison_matrix"]:
        matrix["authority_status"] = "direct_executable_contract"
    return campaign


def summary(
    campaign: dict[str, object], rows: list[dict[str, str]] | None = None
) -> dict[str, object]:
    authority = campaign["experiments"][0]["single_flight_pulse_schedule_policy"][
        "fixed_execution_authority"
    ]
    observed, handoff = _observed_cohort_authority(rows or checkpoint_rows())
    return {
        "census": {"launched": 100, "detector_crossing": 50},
        "clock_basis": "canonical_instrument_time_us",
        "resolution_time_basis": "detector_time_minus_pulse_effective_time",
        "pulse_effective_time_us": authority["pulse_effective_time_us"],
        "transmission": {"eligible_to_detector_fraction": 1.0},
        "pulse_effective_peak": {"mass_resolution": 8000.0},
        "observed_cohort_authority": observed,
        "observed_handoff": handoff,
    }


def source_identity(campaign: dict[str, object]) -> dict[str, str]:
    source = campaign["experiments"][0]["source"]
    return {
        "event_sha256": source["state"]["sha256"],
        "particle_source_sha256": source["particle_source"]["sha256"],
    }


class PulseResolutionOptimizationCampaignTests(unittest.TestCase):
    def test_screening_arm_uses_canonical_pulse_elapsed_checkpoint(self) -> None:
        if not R09_BASELINE_RECEIPT_PATH.is_file():
            self.skipTest("local pulse-resolution baseline receipt is unavailable")
        self.assertEqual(
            file_sha256(R09_BASELINE_RECEIPT_PATH),
            "EA4BB4084A754F5442B016B7D3744141A107C291B8DDABA8CCD9C193D759E37E",
        )
        rows = load(R09_BASELINE_RECEIPT_PATH)["paired_checkpoint_rows"]
        arm = _screening_arm(rows, "baseline")
        detector = next(
            row for row in rows if row["event"] == "detector_crossing"
        )
        particle_id = int(detector["particle_id"])
        index = arm["particle_ids"].index(particle_id)
        self.assertEqual(
            arm["pulse_effective_tof_ns"][index],
            float(detector["pulse_effective_elapsed_us"]) * 1000.0,
        )

    def test_r02_promotion_receipt_final_sha_covers_result_bindings(self) -> None:
        if not R02_PROMOTION_RECEIPT_PATH.is_file():
            self.skipTest("local pulse-resolution promotion receipt is unavailable")
        published = load(R02_PROMOTION_RECEIPT_PATH)
        published.pop("receipt_sha256")
        self.assertIn("baseline_result_sha256", published)
        self.assertIn("candidate_result_sha256", published)
        published["receipt_sha256"] = _canonical_sha(published)
        without_self_sha = dict(published)
        claimed = without_self_sha.pop("receipt_sha256")
        self.assertEqual(claimed, _canonical_sha(without_self_sha))

    def test_schema_v4_still_requires_explicit_pa_cache_policy(self) -> None:
        campaign = load(
            INTEGRATION_ROOT
            / "config"
            / "diagnostics"
            / "canonical_source_architecture_accelerator_field_matrix_n1000_v3_successor_campaign.json"
        )
        campaign["schema_version"] = 4
        campaign["pulse_resolution_optimization"] = load(BASELINE_PATH)[
            "pulse_resolution_optimization"
        ]
        for row in campaign["experiments"]:
            row["single_flight_pa_cache_policy"] = "require_existing"
        validate_schema(campaign, SCHEMA_NAME)
        missing = copy.deepcopy(campaign)
        missing["experiments"][0].pop("single_flight_pa_cache_policy")
        with self.assertRaises(ContractError):
            validate_schema(missing, SCHEMA_NAME)

    def test_split_campaign_lifecycle_and_rows(self) -> None:
        baseline = load(BASELINE_PATH)
        candidates = load(CANDIDATE_PATH)
        validate_schema(baseline, SCHEMA_NAME)
        validate_schema(candidates, SCHEMA_NAME)
        validate_pulse_resolution_optimization_campaign(
            candidates, execution_requested=False
        )
        self.assertEqual(baseline["status"], "retired")
        self.assertEqual(len(baseline["experiments"]), 1)
        self.assertEqual(
            baseline["experiments"][0]["experiment_id"], "pulse_resolution_baseline"
        )
        self.assertEqual(candidates["status"], "PENDING_PREREGISTRATION")
        self.assertEqual(len(candidates["experiments"]), 3)
        self.assertEqual(
            [row["sequence"] for row in candidates["experiments"]], [2, 3, 4]
        )
        with self.assertRaisesRegex(ContractError, "pending"):
            validate_pulse_resolution_optimization_campaign(
                candidates,
                execution_requested=True,
                experiment=candidates["experiments"][0],
            )

    def test_physical_field_profiles_remain_the_direct_1_to_4_sequence(self) -> None:
        baseline = load(BASELINE_PATH)
        candidates = load(CANDIDATE_PATH)
        rows = baseline["experiments"] + candidates["experiments"]
        self.assertEqual(
            [row["single_flight_accelerator_field_profile_id"] for row in rows],
            [
                "accelerator_real_pa",
                "accelerator_ideal_stage1_real_stage2",
                "accelerator_ideal_stage1_stage2_real_reflectron",
                "full_domain_piecewise_ideal_field",
            ],
        )
        for campaign in (baseline, candidates):
            for matrix, row in zip(
                campaign["pulse_resolution_optimization"]["comparison_matrix"],
                campaign["experiments"],
                strict=True,
            ):
                self.assertEqual(matrix["experiment_id"], row["experiment_id"])
                self.assertEqual(matrix["source_profile_id"], row["source_profile_id"])
                self.assertEqual(
                    matrix["field_profile_id"],
                    row["single_flight_accelerator_field_profile_id"],
                )
        self.assertIn("field-semantics successor", candidates["claim_limit"])
        self.assertIn("neither implementation nor numerical equivalence", candidates["claim_limit"])

    def test_d469_cohort_reference_remains_historical_and_count_free(self) -> None:
        baseline = load(BASELINE_PATH)
        candidates = load(CANDIDATE_PATH)
        authority = baseline["pulse_resolution_cohort_authority"]
        self.assertEqual(authority, candidates["pulse_resolution_cohort_authority"])
        self.assertEqual(
            authority["checkpoint"]["sha256"],
            "D46986FC918605D9EB2AD1BA059BB76F9E6AFA24156C30C20A5880375F6B9044",
        )
        expected = {
            "source_release": "F9E2DBDE0AE4640704FB66EE02C101CF84ABE35137363D62647622606DF61279",
            "pre_pulse_state": "0A4B33799A1C310F3F23E1260B52EF05E9517A7CEA20C2117A9E3607BDCD611D",
            "pulse_eligible": "19D70E6F7633B0E783B52BC56B5A35CBA4E83C0051CE290853917A96992AA8E2",
            "outside_transverse_bore": "B1317E6AF8C4B33CEE6C795E10F8DC0FF508BA3898762E4FAD45BC6A2D7FADC2",
        }
        for event, digest in expected.items():
            self.assertEqual(authority[event]["ordered_particle_id_sha256"], digest)
        self.assertFalse(any("count" in key for key in authority))
        self.assertEqual(
            authority["observed_eligibility_policy"],
            "exact_count_and_ordered_id_sha_fail_closed",
        )
        self.assertEqual(authority["detector_survivor_reselection"], "prohibited")

    def test_prefix_writer_consumes_exact_ordered_ids(self) -> None:
        columns = [
            "particle_id", "birth_time_s", "x_mm", "y_mm", "z_mm",
            "vx_m_s", "vy_m_s", "vz_m_s", "mass_amu", "charge_state",
        ]
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "mother.csv"
            target = Path(temporary) / "prefix.csv"
            source.write_text(
                ",".join(columns)
                + "\n"
                + "\n".join(
                    f"{particle_id},0,0,0,0,0,0,1,100,1"
                    for particle_id in range(1, 1001)
                )
                + "\n",
                encoding="utf-8",
            )
            digest = write_pulse_resolution_screening_prefix(
                source, target, ordered_particle_ids=list(range(1, 101))
            )
            rows = target.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(rows), 101)
            self.assertTrue(rows[-1].startswith("100,"))
            self.assertEqual(len(digest), 64)
            with self.assertRaisesRegex(ContractError, "cohort"):
                write_pulse_resolution_screening_prefix(
                    source, target, ordered_particle_ids=[1, 3]
                )

    def test_baseline_receipt_uses_row_randomness_and_is_non_promoting(self) -> None:
        campaign = load(BASELINE_PATH)
        experiment = campaign["experiments"][0]
        receipt = build_receipt(
            campaign,
            summary(campaign),
            checkpoint_rows(),
            campaign_sha256="A" * 64,
            experiment_row_sha256=_canonical_sha(experiment),
            source_identity=source_identity(campaign),
            prefix_path="inputs/prefix.csv",
            prefix_sha256="D" * 64,
            registration_authority_sha256="E" * 64,
            experiment_id=experiment["experiment_id"],
        )
        self.assertEqual(receipt["execution_status"], "baseline_registered_not_candidate")
        self.assertEqual(
            receipt["analysis_randomness"],
            experiment["single_flight_population"]["analysis_randomness"],
        )
        self.assertEqual(
            receipt["cohort_authority_mode"], "establish_observed_authority"
        )
        self.assertEqual(
            receipt["observed_cohort_authority"]["source_release"]["count"], 100
        )
        self.assertEqual(
            receipt["historical_migration_reference"]["status"],
            "historical_migration_reference_only",
        )
        self.assertFalse(receipt["promotion_gate_invoked"])
        self.assertFalse(receipt["formal_gate_passed"])

    def test_baseline_establishes_transport_observation_instead_of_d469_counts(self) -> None:
        campaign = load(BASELINE_PATH)
        experiment = campaign["experiments"][0]
        rows = checkpoint_rows()
        removed = next(
            index for index, row in enumerate(rows)
            if row["event"] == "pre_pulse_state"
            and row["pulse_eligibility"] == "eligible"
        )
        rows.pop(removed)
        receipt = build_receipt(
            campaign,
            summary(campaign, rows),
            rows,
            campaign_sha256="A" * 64,
            experiment_row_sha256=_canonical_sha(experiment),
            source_identity=source_identity(campaign),
            prefix_path="inputs/prefix.csv",
            prefix_sha256="D" * 64,
            registration_authority_sha256="E" * 64,
            experiment_id=experiment["experiment_id"],
        )
        self.assertEqual(receipt["cohort_census"]["source_release"]["count"], 100)
        self.assertEqual(receipt["cohort_census"]["pre_pulse_state"]["count"], 65)
        self.assertEqual(receipt["cohort_census"]["pulse_eligible"]["count"], 49)
        without_self_sha = dict(receipt)
        self_sha = without_self_sha.pop("receipt_sha256")
        self.assertEqual(self_sha, _canonical_sha(without_self_sha))
        duplicate_rows = checkpoint_rows()
        duplicate_rows.append(copy.deepcopy(next(
            row for row in duplicate_rows if row["event"] == "pre_pulse_state"
        )))
        with self.assertRaisesRegex(ValueError, "duplicate checkpoints"):
            build_receipt(
                campaign,
                summary(campaign),
                duplicate_rows,
                campaign_sha256="A" * 64,
                experiment_row_sha256=_canonical_sha(experiment),
                source_identity=source_identity(campaign),
                prefix_path="inputs/prefix.csv",
                prefix_sha256="D" * 64,
                registration_authority_sha256="E" * 64,
                experiment_id=experiment["experiment_id"],
            )
        bad_clock = summary(campaign)
        bad_clock["pulse_effective_time_us"] += 1e-6
        with self.assertRaisesRegex(ValueError, "pulse clock authority differs"):
            build_receipt(
                campaign, bad_clock, checkpoint_rows(),
                campaign_sha256="A" * 64,
                experiment_row_sha256=_canonical_sha(experiment),
                source_identity=source_identity(campaign),
                prefix_path="inputs/prefix.csv", prefix_sha256="D" * 64,
                registration_authority_sha256="E" * 64,
                experiment_id=experiment["experiment_id"],
            )

        serialized_clock = summary(campaign)
        serialized_clock["pulse_effective_time_us"] = 31.8136698715
        rounded_receipt = build_receipt(
            campaign, serialized_clock, checkpoint_rows(),
            campaign_sha256="A" * 64,
            experiment_row_sha256=_canonical_sha(experiment),
            source_identity=source_identity(campaign),
            prefix_path="inputs/prefix.csv", prefix_sha256="D" * 64,
            registration_authority_sha256="E" * 64,
            experiment_id=experiment["experiment_id"],
        )
        self.assertEqual(
            rounded_receipt["clock"]["pulse_effective_time_us"],
            31.81366987147908,
        )
        self.assertEqual(
            rounded_receipt["clock"][
                "observed_serialized_pulse_effective_time_us"
            ],
            31.8136698715,
        )
        self.assertAlmostEqual(
            rounded_receipt["clock"]["observed_minus_planned_us"],
            31.8136698715 - 31.81366987147908,
        )
        self.assertEqual(
            rounded_receipt["clock"]["clock_abs_tolerance_us"], 1e-9
        )

        outside_clock_tolerance = summary(campaign)
        outside_clock_tolerance["pulse_effective_time_us"] = (
            31.81366987147908 + 2e-9
        )
        with self.assertRaisesRegex(ValueError, "pulse clock authority differs"):
            build_receipt(
                campaign, outside_clock_tolerance, checkpoint_rows(),
                campaign_sha256="A" * 64,
                experiment_row_sha256=_canonical_sha(experiment),
                source_identity=source_identity(campaign),
                prefix_path="inputs/prefix.csv", prefix_sha256="D" * 64,
                registration_authority_sha256="E" * 64,
                experiment_id=experiment["experiment_id"],
            )
        bad_source = source_identity(campaign)
        bad_source["event_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "source identity differs"):
            build_receipt(
                campaign, summary(campaign), checkpoint_rows(),
                campaign_sha256="A" * 64,
                experiment_row_sha256=_canonical_sha(experiment),
                source_identity=bad_source,
                prefix_path="inputs/prefix.csv", prefix_sha256="D" * 64,
                registration_authority_sha256="E" * 64,
                experiment_id=experiment["experiment_id"],
            )

    def test_candidate_requires_exact_observed_baseline_cohort_authority(self) -> None:
        baseline_campaign = load(BASELINE_PATH)
        baseline_experiment = baseline_campaign["experiments"][0]
        baseline_receipt = build_receipt(
            baseline_campaign,
            summary(baseline_campaign),
            checkpoint_rows(),
            campaign_sha256="A" * 64,
            experiment_row_sha256=_canonical_sha(baseline_experiment),
            source_identity=source_identity(baseline_campaign),
            prefix_path="inputs/prefix.csv",
            prefix_sha256="D" * 64,
            registration_authority_sha256="E" * 64,
            experiment_id=baseline_experiment["experiment_id"],
        )
        candidate = authorized_candidate()
        candidate["pulse_resolution_baseline_evidence"]["sha256"] = "E" * 64
        experiment = candidate["experiments"][0]
        accepted = build_receipt(
            candidate,
            summary(candidate),
            checkpoint_rows(),
            campaign_sha256="F" * 64,
            experiment_row_sha256=_canonical_sha(experiment),
            source_identity=source_identity(candidate),
            prefix_path="inputs/prefix.csv",
            prefix_sha256="D" * 64,
            registration_authority_sha256="E" * 64,
            experiment_id=experiment["experiment_id"],
            baseline_evidence=baseline_receipt,
        )
        self.assertEqual(
            accepted["cohort_authority_mode"],
            "require_frozen_baseline_authority",
        )
        changed_rows = checkpoint_rows()
        changed_rows.pop(next(
            index for index, row in enumerate(changed_rows)
            if row["event"] == "pre_pulse_state"
            and row["pulse_eligibility"] == "eligible"
        ))
        with self.assertRaisesRegex(
            ValueError, "observed pre_pulse_state cohort differs"
        ):
            build_receipt(
                candidate,
                summary(candidate, changed_rows),
                changed_rows,
                campaign_sha256="F" * 64,
                experiment_row_sha256=_canonical_sha(experiment),
                source_identity=source_identity(candidate),
                prefix_path="inputs/prefix.csv",
                prefix_sha256="D" * 64,
                registration_authority_sha256="E" * 64,
                experiment_id=experiment["experiment_id"],
                baseline_evidence=baseline_receipt,
            )

    def test_pending_candidate_cannot_publish_result(self) -> None:
        campaign = load(CANDIDATE_PATH)
        experiment = campaign["experiments"][0]
        with self.assertRaisesRegex(ValueError, "pending comparison"):
            build_receipt(
                campaign,
                summary(campaign),
                checkpoint_rows(),
                campaign_sha256="A" * 64,
                experiment_row_sha256=_canonical_sha(experiment),
                source_identity={},
                prefix_path="inputs/prefix.csv",
                prefix_sha256="D" * 64,
                registration_authority_sha256="E" * 64,
                experiment_id=experiment["experiment_id"],
            )

    def test_fixed_pulse_and_analysis_authorities_are_single(self) -> None:
        baseline = load(BASELINE_PATH)
        candidates = load(CANDIDATE_PATH)
        self.assertNotIn("bootstrap", baseline["pulse_resolution_optimization"])
        self.assertNotIn("bootstrap", candidates["pulse_resolution_optimization"])
        for campaign in (baseline, candidates):
            for row in campaign["experiments"]:
                authority = row["single_flight_pulse_schedule_policy"][
                    "fixed_execution_authority"
                ]
                self.assertEqual(authority["pulse_effective_time_us"], 31.81366987147908)
                self.assertEqual(
                    authority["source_schedule"]["sha256"],
                    "AC9B99A3769C72A0980387D599EF6BC0DDA74DBB388069C27368EC28E19837D1",
                )
                self.assertEqual(
                    authority["source_state_sha256"],
                    "F8F77CFA0A3A21D06BC779FAAC2CB2F066AC38BBC986E3A6A60F28A1E58AE409",
                )
                self.assertNotIn("baseline_receipt", authority)
                self.assertNotIn("prefix_sha256", authority)
                self.assertEqual(
                    row["single_flight_population"]["analysis_randomness"],
                    {"bootstrap_resample_count": 5000, "bootstrap_seed": 20260812},
                )

    def test_candidate_has_no_baseline_evidence_before_preregistration(self) -> None:
        campaign = load(CANDIDATE_PATH)
        self.assertNotIn("pulse_resolution_baseline_authority_id", campaign)
        self.assertNotIn("pulse_resolution_baseline_evidence", campaign)
        serialized = json.dumps(campaign, sort_keys=True)
        self.assertNotIn("97495F4B0A49D4FF", serialized)
        self.assertNotIn("pulse_resolution_baseline_result", serialized)
        self.assertNotIn("pulse_resolution_baseline_checkpoints", serialized)

    def test_adapter_consumes_only_plan_local_baseline_evidence(self) -> None:
        adapter = (
            INTEGRATION_ROOT / "workflows" / "family_source_closure" / "adapter.ps1"
        ).read_text(encoding="utf-8-sig")
        self.assertIn("inputs/pulse_resolution_baseline_evidence.json", adapter)
        self.assertIn("Join-Path $runDirectory", adapter)
        self.assertIn("pulse_resolution_registration_filename", adapter)
        self.assertNotIn("pulse_resolution_baseline_result_reference.json", adapter)
        self.assertNotIn("Published baseline checkpoints are not frozen", adapter)
        self.assertNotIn("pulse_resolution_baseline_checkpoints", adapter)

    def test_authorized_candidate_requires_preregistration(self) -> None:
        campaign = authorized_candidate()
        campaign.pop("preregistration")
        with self.assertRaises(ContractError):
            validate_schema(campaign, SCHEMA_NAME)

    def test_authorized_candidate_requires_baseline_evidence(self) -> None:
        campaign = authorized_candidate()
        campaign.pop("pulse_resolution_baseline_evidence")
        with self.assertRaises(ContractError):
            validate_schema(campaign, SCHEMA_NAME)

    def test_authorized_candidate_rejects_any_wrong_frozen_row_sha(self) -> None:
        for experiment_id in tuple(
            authorized_candidate()["preregistration"][
                "frozen_experiment_row_sha256"
            ]
        ):
            with self.subTest(experiment_id=experiment_id):
                campaign = authorized_candidate()
                campaign["preregistration"]["frozen_experiment_row_sha256"][
                    experiment_id
                ] = "D" * 64
                validate_schema(campaign, SCHEMA_NAME)
                with self.assertRaisesRegex(ContractError, "row SHA"):
                    validate_pulse_resolution_optimization_campaign(
                        campaign, execution_requested=False
                    )

    def test_pending_candidate_rejects_direct_authority_status(self) -> None:
        campaign = load(CANDIDATE_PATH)
        campaign["pulse_resolution_optimization"]["comparison_matrix"][0][
            "authority_status"
        ] = "direct_executable_contract"
        with self.assertRaises(ContractError):
            validate_schema(campaign, SCHEMA_NAME)

    def test_authorized_candidate_rejects_pending_authority_status(self) -> None:
        campaign = authorized_candidate()
        campaign["pulse_resolution_optimization"]["comparison_matrix"][1][
            "authority_status"
        ] = "pending_preregistration"
        with self.assertRaises(ContractError):
            validate_schema(campaign, SCHEMA_NAME)

    def test_candidate_rejects_invalid_baseline_receipt_before_mode_output(self) -> None:
        baseline_campaign = load(BASELINE_PATH)
        baseline_experiment = baseline_campaign["experiments"][0]
        base_receipt = build_receipt(
            baseline_campaign,
            summary(baseline_campaign),
            checkpoint_rows(),
            campaign_sha256="A" * 64,
            experiment_row_sha256=_canonical_sha(baseline_experiment),
            source_identity=source_identity(baseline_campaign),
            prefix_path="inputs/prefix.csv",
            prefix_sha256="D" * 64,
            registration_authority_sha256="E" * 64,
            experiment_id=baseline_experiment["experiment_id"],
        )
        execute = INTEGRATION_ROOT / "workflows/family_source_closure/execute.ps1"
        scratch = REPO_ROOT.parent / "artifacts" / "projects" / (
            "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
        ) / "scratch"
        scratch.mkdir(parents=True, exist_ok=True)
        runs = scratch.parent / "runs"
        # Temporary mutated campaigns are intentionally not lifecycle-registered.
        # The family entry must reject them before any baseline receipt is read.
        cases = (
            (
                "self_sha",
                "Campaign is not an active lifecycle authority; execution is forbidden",
            ),
            (
                "deleted_row",
                "Campaign is not an active lifecycle authority; execution is forbidden",
            ),
        )
        with tempfile.TemporaryDirectory(dir=scratch) as evidence_directory:
            evidence_root = Path(evidence_directory)
            for case_index, (mutation, expected_error) in enumerate(cases, start=7):
                with self.subTest(mutation=mutation):
                    receipt = copy.deepcopy(base_receipt)
                    if mutation == "self_sha":
                        receipt["receipt_sha256"] = "0" * 64
                    else:
                        rows = receipt["paired_checkpoint_rows"]
                        deleted_index = next(
                            index for index, row in enumerate(rows)
                            if row["event"] == "pre_pulse_state"
                            and row["pulse_eligibility"] == "eligible"
                        )
                        rows.pop(deleted_index)
                        receipt_without_sha = dict(receipt)
                        receipt_without_sha.pop("receipt_sha256")
                        receipt["receipt_sha256"] = _canonical_sha(receipt_without_sha)
                    receipt_path = evidence_root / f"{mutation}.json"
                    receipt_path.write_text(
                        json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
                    )
                    campaign = authorized_candidate()
                    run_id = (
                        f"20991231_2359{case_index:02d}__sim__cross__"
                        f"pulse-evidence-{mutation.replace('_', '-')}__n100"
                    )
                    campaign["experiments"][0]["run_id"] = run_id
                    campaign["pulse_resolution_baseline_evidence"] = {
                        "authority_id": receipt["baseline_authority_id"],
                        "baseline_campaign_id": receipt["campaign_id"],
                        "baseline_campaign_sha256": receipt["campaign_sha256"],
                        "path": receipt_path.relative_to(REPO_ROOT.parent).as_posix(),
                        "sha256": file_sha256(receipt_path),
                    }
                    campaign["preregistration"]["frozen_experiment_row_sha256"] = {
                        row["experiment_id"]: _canonical_sha(row).upper()
                        for row in campaign["experiments"]
                    }
                    with tempfile.TemporaryDirectory(
                        dir=INTEGRATION_ROOT / "config"
                    ) as campaign_dir:
                        campaign_path = Path(campaign_dir) / "campaign.json"
                        campaign_path.write_text(
                            json.dumps(campaign, indent=2) + "\n", encoding="utf-8"
                        )
                        write_campaign(REPO_ROOT, campaign_path)
                        prepare_output = evidence_root / f"{mutation}_prepare_output"
                        solver_output = runs / run_id
                        self.assertFalse(prepare_output.exists())
                        self.assertFalse(solver_output.exists())
                        completed = subprocess.run(
                            [
                                "pwsh", "-NoProfile", "-File", str(execute),
                                "-Campaign", str(campaign_path.relative_to(REPO_ROOT)),
                                "-ExperimentId",
                                campaign["experiments"][0]["experiment_id"],
                                "-PrepareOnly", "-OutputDirectory", str(prepare_output),
                            ],
                            cwd=REPO_ROOT,
                            text=True,
                            encoding="utf-8",
                            errors="replace",
                            capture_output=True,
                            check=False, timeout=300,
                        )
                        output = completed.stdout + completed.stderr
                        self.assertNotEqual(completed.returncode, 0)
                        self.assertIn(expected_error, output)
                        self.assertNotIn("SIMION", output)
                        self.assertFalse(prepare_output.exists())
                        self.assertFalse(solver_output.exists())

    def test_acceptance_and_grid_limits_remain_fail_closed(self) -> None:
        for field, value in (
            ("selection_uses_detector_outcome", True),
            ("minimum_pulse_eligible_coverage", 0.69),
        ):
            mutated = load(BASELINE_PATH)
            mutated["pulse_resolution_optimization"]["acceptance_window"][field] = value
            with self.assertRaises(ContractError):
                validate_schema(mutated, SCHEMA_NAME)
        for field, value in (
            ("mass_resolution_relative_change_maximum", 0.03),
            ("hit_rate_change_maximum_percentage_points", 2.0),
        ):
            mutated = load(BASELINE_PATH)
            mutated["pulse_resolution_optimization"]["grid_convergence"][field] = value
            with self.assertRaises(ContractError):
                validate_schema(mutated, SCHEMA_NAME)

    def test_legacy_campaign_remains_compatible(self) -> None:
        campaign = copy.deepcopy(load(LEGACY_CAMPAIGN_PATH))
        validate_schema(campaign, SCHEMA_NAME)
        validate_pulse_resolution_optimization_campaign(
            campaign, execution_requested=True
        )


if __name__ == "__main__":
    unittest.main()

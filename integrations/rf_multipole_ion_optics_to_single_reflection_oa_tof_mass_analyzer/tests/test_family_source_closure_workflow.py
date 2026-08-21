"""Contract tests for the campaign-only multipole-to-oaTOF workflow."""

from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from common.contracts.machine_contracts import ContractError, validate_schema
from common.integration.resolve_connection import derive_mating_translation_with_gap
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.tests.fixtures.campaign_fixture import (
    current_campaign_fixture,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.workflows.family_source_closure.prepare import (
    _automatic_pulse_population_binding,
    _repo_byte_record,
    _workspace_record,
    prepare_family_source_closure,
    resolve_single_flight_batch_count,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_source import (
    materialize_staged_grid2_restart,
    resolve_source_materialization_profile,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.ordered_pre_pulse_subset import (
    ordered_subset_source_particle_ids,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.workflows.family_source_closure.publish_run import (
    INTEGRATION_ID,
    _retry_suffix,
    _single_flight_run_stem,
    publish_family_source_closure_run,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_layout import (
    compile_geometry_and_port,
    select_profile,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
INTEGRATION_ROOT = REPO_ROOT / "integrations" / INTEGRATION_ID
CONFIG_ROOT = INTEGRATION_ROOT / "config"
CAMPAIGN_PATH = CONFIG_ROOT / "experiment_campaign.json"
N1000_CAMPAIGN_PATH = (
    CONFIG_ROOT / "diagnostics" / "octupole_simion_aperture050_n1000_campaign.json"
)
SINGLE_FLIGHT_CAMPAIGN_PATH = (
    CONFIG_ROOT / "diagnostics" / "octupole_simion_single_flight_aperture100_n1000_campaign.json"
)
TERMINAL_DESIGN_REFERENCE_CAMPAIGN_PATH = (
    CONFIG_ROOT / "diagnostics"
    / "octupole_terminal_15mm_sleeve_single_flight_n1000_campaign.json"
)
Z_ACCEPTANCE_CAMPAIGN_PATH = (
    CONFIG_ROOT / "diagnostics" / "octupole_z_acceptance_d1_4mm_n1000_campaign.json"
)
GRID_CONVERGENCE_CAMPAIGN_PATH = (
    CONFIG_ROOT / "diagnostics" / "octupole_frontend_grid_convergence_n1000_campaign.json"
)
ACCELERATION_AXIS_GRID_CAMPAIGN_PATH = (
    CONFIG_ROOT / "diagnostics"
    / "octupole_frontend_acceleration_axis_grid_n1000_campaign.json"
)
IDEAL_FIELD_CAMPAIGN_PATH = (
    CONFIG_ROOT / "diagnostics" / "octupole_accelerator_ideal_field_n1000_campaign.json"
)
SOURCE_ARCH_FIELD_MATRIX_PATH = (
    CONFIG_ROOT / "diagnostics" /
    "canonical_source_architecture_accelerator_field_matrix_n1000_campaign.json"
)
PROFILE_REGISTRY = CONFIG_ROOT / "connection_profiles.json"
ADAPTER_REGISTRY = CONFIG_ROOT / "execution_adapter_profiles.json"
OCTUPOLE_RUNTIME_BINDING = (
    CONFIG_ROOT / "family_octupole_direct_mating_gap_0mm_runtime_binding.json"
)
STAGED_GRID2_R03_CAMPAIGN = (
    CONFIG_ROOT / "diagnostics" /
    "staged_grid2_restart_legacy_n34_successor_r03_campaign.json"
)
AUTO_N1000_CONNECTOR_CAMPAIGN = (
    CONFIG_ROOT / "diagnostics" /
    "connector_gap_three_zone_real_pa_full_n1000_campaign_v11.json"
)


def load(path: Path) -> dict[str, object]:
    return current_campaign_fixture(
        json.loads(path.read_text(encoding="utf-8-sig"))
    )


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def use_current_time_grid_profile(campaign: dict[str, object]) -> None:
    """Upgrade legacy test copies to the current native-dt profile contract."""
    for row in campaign.get("experiments", []):
        policy = row.get("single_flight_pulse_schedule_policy", {})
        cache_miss = policy.get("cache_miss_policy", {})
        cache_miss["time_grid_profile_id"] = (
            "ballistic_seed_native_dt_minus0p35_plus1p65_v1"
        )


def migrate_v3_campaign(campaign: dict[str, object]) -> dict[str, object]:
    campaign["schema_version"] = 3
    layout_profiles = {
        item["layout_profile_id"]: item
        for item in load(CONFIG_ROOT / "single_flight_layout_profiles.json")["profiles"]
    }
    single_flight_configuration = load(CONFIG_ROOT / "simion_single_flight.json")
    grid_profiles = {
        item["profile_id"]: item
        for item in single_flight_configuration["frontend_grid_profiles"]
    }
    for row in campaign["experiments"]:
        if row.get("execution_strategy") != "simion_single_flight":
            continue
        row.setdefault("source_release_mode", "continuous_frontend")
        row.setdefault(
            "architecture_generation_id",
            layout_profiles[row["single_flight_layout_profile_id"]]["architecture_generation_id"],
        )
        row.setdefault(
            "field_overlay_id",
            grid_profiles[row.get(
                "single_flight_frontend_grid_profile_id",
                single_flight_configuration["default_frontend_grid_profile_id"],
            )]["field_overlay_id"],
        )
        count = int(
            row.get("single_flight_particle_source", {}).get(
                "particle_count",
                row.get("pre_pulse_source_state", {}).get(
                    "particle_count", row["source"]["launched_particle_count"]
                ),
            )
        )
        materialization = row.get("single_flight_source_materialization_profile_id")
        row.setdefault("source_profile_id", materialization or "campaign_source_population")
        if row.get("source_release_mode") == "pre_pulse_restart":
            mode, role, binding = (
                "pre_pulse_restart", "pre_pulse_source_state",
                "experiment_pre_pulse_source_state",
            )
        elif row.get("single_flight_particle_source") is not None:
            source = row["single_flight_particle_source"]
            mode, role, binding = (
                (
                    "pulse_eligible_conditional"
                    if source["sampling_mode"] == "steady_candidate_pool"
                    else source["sampling_mode"]
                ), "single_flight_particle_source",
                "experiment_single_flight_particle_source",
            )
        elif materialization and materialization != "canonical_real_octupole_n1000":
            mode, role, binding = (
                "resolved_layout_pulse_ideal_linear_z_vz",
                "single_flight_materialized_particle_source",
                "prepared_materialized_particle_source",
            )
        else:
            mode, role, binding = (
                "continuous_injection_full_population",
                row["source"]["particle_source_manifest_input_role"],
                "source_contract_particle_source",
            )
        offset = row.pop("single_flight_pulse_offset_rf_periods", 0.0)
        row["single_flight_pulse_schedule_policy"] = {
            "policy_id": "multipole_handoff_ballistic_centroid_v1",
            "offset_rf_periods": offset,
            "pulse_width_us": 1.0,
        }
        ordered_hash = hashlib.sha256(
            json.dumps(list(range(1, count + 1)), separators=(",", ":")).encode()
        ).hexdigest().upper()
        row["single_flight_population"] = {
            "population_id": "test_population",
            "population_mode": mode,
            "source_authority": {
                "input_role": role, "table_binding": binding,
                "ordered_particle_id_encoding": "canonical_compact_json_integer_array_v1",
            },
            "execution_population": {
                "particle_count": count,
                "ordered_particle_id_sha256": ordered_hash,
                "selection_algorithm": "all_rows_in_frozen_file_order",
                "selection_seed": 0,
            },
            "denominators": {
                "population_count": count, "eligible_population_count": count,
            },
            "analysis_randomness": {
                "bootstrap_resample_count": 0, "bootstrap_seed": 20260812,
            },
            "postselection_policy": (
                "pulse_eligibility_only"
                if mode == "pulse_eligible_conditional"
                else "prohibited"
            ),
        }
    return campaign


def write_current_policy_campaign(source: Path, destination: Path) -> dict[str, object]:
    """Clone one immutable historical campaign with the active governed policy."""
    campaign = load(source)
    campaign["execution_policy"] = load(OCTUPOLE_RUNTIME_BINDING)["contracts"][
        "execution_policy_contract"
    ]
    migrate_v3_campaign(campaign)
    write_json(destination, campaign)
    return campaign


class FamilySourceClosureWorkflowTests(unittest.TestCase):
    def test_automatic_full_population_binding_uses_declared_count(self) -> None:
        population = {
            "population_mode": "continuous_injection_full_population",
            "source_authority": {
                "table_binding": "source_contract_particle_source",
            },
            "execution_population": {
                "particle_count": 123,
                "selection_algorithm": "all_rows_in_frozen_file_order",
            },
        }
        self.assertEqual(
            _automatic_pulse_population_binding(population),
            ("source_contract_particle_source", 123),
        )
        population["execution_population"]["particle_count"] = 0
        with self.assertRaisesRegex(ContractError, "population differs"):
            _automatic_pulse_population_binding(population)

    def test_batch_count_is_execution_only_and_defaults_to_one(self) -> None:
        self.assertEqual(
            resolve_single_flight_batch_count({}, execution_particle_count=100),
            1,
        )
        self.assertEqual(
            resolve_single_flight_batch_count(
                {"single_flight_batch_count": 2}, execution_particle_count=1000,
            ),
            2,
        )
        for invalid in (0, 1001, True, 2.0):
            with self.subTest(invalid=invalid), self.assertRaises(ContractError):
                resolve_single_flight_batch_count(
                    {"single_flight_batch_count": invalid},
                    execution_particle_count=1000,
                )

    def test_memory_policy_freezes_selected_count_and_fails_when_no_batch_fits(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            receipt = workspace / "resource_usage.json"
            receipt.write_text(
                json.dumps({"peak_process_tree_working_set_bytes": 12 * 1024**3}),
                encoding="utf-8",
            )
            policy = {
                "single_flight_batch_count": 3,
                "single_flight_time_integration_profile_id": "dt40",
                "single_flight_batch_memory_policy": {
                    "resource_usage_receipt": {
                        "path": "resource_usage.json",
                        "sha256": hashlib.sha256(receipt.read_bytes()).hexdigest().upper(),
                    },
                    "default_batch_count": 2,
                    "maximum_batch_count": 3,
                    "reserve_available_memory_bytes": 1024**3,
                },
            }
            with patch(
                "common.simion.resource_scheduler.available_physical_memory_bytes",
                return_value=15 * 1024**3,
            ):
                self.assertEqual(
                    resolve_single_flight_batch_count(
                        policy, execution_particle_count=5000, workspace=workspace
                    ),
                    1,
                )
            with patch(
                "common.simion.resource_scheduler.available_physical_memory_bytes",
                return_value=12 * 1024**3,
            ), self.assertRaisesRegex(ContractError, "memory batch policy is invalid"):
                resolve_single_flight_batch_count(
                    policy, execution_particle_count=5000, workspace=workspace
                )

    def test_single_flight_batching_is_one_wave_only(self) -> None:
        runner = (INTEGRATION_ROOT / "runtime" / "run_single_flight.ps1").read_text(
            encoding="utf-8-sig"
        )
        prepare_source = (INTEGRATION_ROOT / "workflows" / "family_source_closure" / "prepare.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("must fit in one dispatch wave", runner)
        self.assertIn("one-wave parallel capacity", prepare_source)

    def test_auto_pulse_full_n1000_compiles_source_contract_population(self) -> None:
        campaign = load(AUTO_N1000_CONNECTOR_CAMPAIGN)
        use_current_time_grid_profile(campaign)
        row = campaign["experiments"][0]
        scratch = REPO_ROOT.parent / "artifacts" / "projects" / INTEGRATION_ID / "scratch"
        scratch.mkdir(parents=True, exist_ok=True)
        mapping = next(
            item for item in load(ADAPTER_REGISTRY)["mappings"]
            if item["connection_profile_id"] == row["connection_profile_id"]
        )
        with tempfile.TemporaryDirectory(dir=scratch) as directory, \
            tempfile.TemporaryDirectory(dir=CONFIG_ROOT) as config_directory, patch(
            "integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer."
            "workflows.family_source_closure.prepare."
            "_resolve_cached_verified_pulse_schedule",
            return_value=None,
        ), patch(
            "integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer."
            "workflows.family_source_closure.prepare.resolve_execution_mapping",
            return_value=mapping,
        ):
            output = Path(directory)
            campaign["execution_policy"] = load(OCTUPOLE_RUNTIME_BINDING)[
                "contracts"
            ]["execution_policy_contract"]
            campaign_path = Path(config_directory) / "campaign.json"
            write_json(campaign_path, campaign)
            _, plan_path = prepare_family_source_closure(
                repo_root=REPO_ROOT,
                profile_registry_path=PROFILE_REGISTRY,
                adapter_registry_path=ADAPTER_REGISTRY,
                campaign_path=campaign_path,
                experiment_id=row["experiment_id"],
                resolved_output=output / "resolved_connection.json",
                plan_output=output / "composition_plan.json",
            )
            arguments = {
                item.split("=", 1)[0]: item.split("=", 1)[1]
                for item in load(plan_path)["execution_steps"][0]["arguments"]
            }
            self.assertEqual(
                arguments["pre_pulse_time_series_prefix_filename"],
                row["source"]["particle_source"]["path"],
            )
            self.assertEqual(
                arguments["pre_pulse_time_series_prefix_sha256"],
                row["source"]["particle_source"]["sha256"],
            )
            self.assertEqual(arguments["pre_pulse_time_series_prefix_count"], "1000")
            self.assertEqual(arguments["single_flight_batch_count"], "2")
            self.assertFalse(
                (output / "inputs" / "automatic_pulse_timing_prefix_n100.csv").exists()
            )
            population = load(output / "resolved_population_contract.json")
            self.assertEqual(
                population["source_authority"]["table_binding"],
                "source_contract_particle_source",
            )
            self.assertEqual(population["execution_population"]["particle_count"], 1000)
            self.assertEqual(
                load(output / "resolved_pulse_timing_orchestration.json")["state"],
                "discovery_required",
            )
        adapter_source = (
            INTEGRATION_ROOT / "workflows" / "family_source_closure" / "adapter.ps1"
        ).read_text(encoding="utf-8-sig")
        self.assertIn("'single_flight_batch_count'", adapter_source)
        self.assertIn("$runnerArguments.ExecutionBatchCount", adapter_source)
        self.assertIn("-gt $expectedExecutionParticleCount", adapter_source)
        self.assertIn("$resolvedBatchCount = [int]$frozenArguments.single_flight_batch_count", adapter_source)
        self.assertNotIn("$declaredBatchCount", adapter_source)

    def test_generated_ordered_subset_selectors_are_exact_and_fresh(self) -> None:
        n1 = ordered_subset_source_particle_ids("n1_center_source_id_500_v1")
        n100 = ordered_subset_source_particle_ids(
            "n100_file_order_source_ids_1_to_100_v1"
        )
        self.assertEqual(n1, [500])
        self.assertEqual(n100, list(range(1, 101)))
        n100.append(101)
        self.assertEqual(
            ordered_subset_source_particle_ids(
                "n100_file_order_source_ids_1_to_100_v1"
            ),
            list(range(1, 101)),
        )
        with self.assertRaisesRegex(ValueError, "unsupported"):
            ordered_subset_source_particle_ids("arbitrary_postselection")

    def test_generated_ordered_subset_schema_is_mutually_exclusive_and_count_bound(
        self,
    ) -> None:
        path = (
            CONFIG_ROOT
            / "diagnostics"
            / "canonical_long_full_domain_restart_affine_width_numerics_n1000_v3_successor_campaign.json"
        )
        external = load(path)
        validate_schema(
            external, "rf_multipole_oatof_experiment_campaign.schema.json"
        )
        campaign = json.loads(json.dumps(external))
        row = campaign["experiments"][2]
        del row["pre_pulse_source_state"]
        row["generated_pre_pulse_ordered_subset"] = {
            "selection_id": "n100_file_order_source_ids_1_to_100_v1"
        }
        population = row["single_flight_population"]
        population["execution_population"]["particle_count"] = 100
        population["execution_population"]["ordered_particle_id_sha256"] = (
            hashlib.sha256(
                json.dumps(
                    list(range(1, 101)), separators=(",", ":")
                ).encode()
            ).hexdigest().upper()
        )
        population["denominators"] = {
            "population_count": 100,
            "eligible_population_count": 100,
        }
        validate_schema(
            campaign, "rf_multipole_oatof_experiment_campaign.schema.json"
        )
        full_width = json.loads(json.dumps(campaign))
        full_width["experiments"][2]["generated_pre_pulse_ordered_subset"] = {
            "selection_id": "n100_uniform_full_width_source_ids_1_to_1000_v1"
        }
        validate_schema(
            full_width, "rf_multipole_oatof_experiment_campaign.schema.json"
        )

        conflicting = json.loads(json.dumps(campaign))
        conflicting["experiments"][2]["pre_pulse_source_state"] = external[
            "experiments"
        ][2]["pre_pulse_source_state"]
        with self.assertRaises(ContractError):
            validate_schema(
                conflicting,
                "rf_multipole_oatof_experiment_campaign.schema.json",
            )

        wrong_count = json.loads(json.dumps(campaign))
        wrong_count["experiments"][2]["single_flight_population"][
            "execution_population"
        ]["particle_count"] = 1
        with self.assertRaises(ContractError):
            validate_schema(
                wrong_count,
                "rf_multipole_oatof_experiment_campaign.schema.json",
            )

    def test_prepare_generates_and_freezes_n100_ordered_restart_subset(self) -> None:
        source_run = (
            REPO_ROOT.parent
            / "artifacts/projects/rf_octupole_ion_optics/runs"
            / "20260805_132100__sim__simion__oct-terminal-10ev-h15__n1000"
        )
        if not source_run.is_dir():
            self.skipTest("local frozen N=1000 mother source is unavailable")
        source_campaign = (
            CONFIG_ROOT
            / "diagnostics"
            / "canonical_pulse_state_source_acc_ii_n1000_campaign.json"
        )
        with tempfile.TemporaryDirectory(
            dir=REPO_ROOT.parent
            / "artifacts/projects/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
        ) as directory, tempfile.TemporaryDirectory(
            dir=CONFIG_ROOT
        ) as config_directory:
            output = Path(directory)
            campaign_path = Path(config_directory) / "campaign.json"
            campaign = migrate_v3_campaign(load(source_campaign))
            campaign["execution_policy"] = load(OCTUPOLE_RUNTIME_BINDING)[
                "contracts"
            ]["execution_policy_contract"]
            row = campaign["experiments"][4]
            del row["pre_pulse_source_state"]
            row["generated_pre_pulse_ordered_subset"] = {
                "selection_id": "n100_file_order_source_ids_1_to_100_v1"
            }
            population = row["single_flight_population"]
            population["execution_population"]["particle_count"] = 100
            population["execution_population"][
                "ordered_particle_id_sha256"
            ] = hashlib.sha256(
                json.dumps(
                    list(range(1, 101)), separators=(",", ":")
                ).encode()
            ).hexdigest().upper()
            population["denominators"] = {
                "population_count": 100,
                "eligible_population_count": 100,
            }
            write_json(campaign_path, campaign)
            _, plan_path = prepare_family_source_closure(
                repo_root=REPO_ROOT,
                profile_registry_path=PROFILE_REGISTRY,
                adapter_registry_path=ADAPTER_REGISTRY,
                campaign_path=campaign_path,
                experiment_id=row["experiment_id"],
                resolved_output=output / "resolved.json",
                plan_output=output / "plan.json",
            )
            subset_path = output / "inputs/single_flight_pre_pulse_ordered_subset.csv"
            receipt_path = output / (
                "inputs/single_flight_pre_pulse_ordered_subset_receipt.json"
            )
            receipt = load(receipt_path)
            plan = load(plan_path)
            arguments = dict(
                item.split("=", 1)
                for item in plan["execution_steps"][0]["arguments"]
                if "=" in item
            )
            self.assertTrue(subset_path.is_file())
            self.assertEqual(
                receipt["selection"]["ordered_source_particle_ids"],
                list(range(1, 101)),
            )
            self.assertEqual(arguments["pre_pulse_source_state_count"], "100")
            self.assertEqual(
                arguments["pre_pulse_source_state_sha256"],
                hashlib.sha256(subset_path.read_bytes()).hexdigest().upper(),
            )
            self.assertEqual(
                arguments["pre_pulse_restart_validation_sha256"],
                hashlib.sha256(
                    (output / "canonical_pulse_restart_target_state_validation.json").read_bytes()
                ).hexdigest().upper(),
            )

    def test_three_zone_candidate_binding_is_layout_scoped_and_hash_bound(self) -> None:
        campaign = load(
            CONFIG_ROOT
            / "diagnostics/short_focus_rr_tqual108_stratified_n100_campaign.json"
        )
        row = campaign["experiments"][0]
        row["single_flight_layout_profile_id"] = "three_zone_t5_primary_v1"
        row["single_flight_three_zone_candidate"] = {
            "path": (
                "artifacts/projects/single_reflection_oa_tof_mass_analyzer/"
                "runs/t5/three_zone_candidate.json"
            ),
            "sha256": "A" * 64,
        }
        validate_schema(
            campaign, "rf_multipole_oatof_experiment_campaign.schema.json"
        )

        missing = json.loads(json.dumps(campaign))
        del missing["experiments"][0]["single_flight_three_zone_candidate"]
        with self.assertRaises(ContractError):
            validate_schema(
                missing, "rf_multipole_oatof_experiment_campaign.schema.json"
            )

        wrong_layout = json.loads(json.dumps(campaign))
        wrong_layout["experiments"][0][
            "single_flight_layout_profile_id"
        ] = "theory_source_z10_d1_3"
        with self.assertRaises(ContractError):
            validate_schema(
                wrong_layout, "rf_multipole_oatof_experiment_campaign.schema.json"
            )

    def test_three_zone_candidate_workspace_binding_rejects_escape_and_stale_sha(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            candidate = workspace / "artifacts/projects/oatof/runs/t5/candidate.json"
            candidate.parent.mkdir(parents=True)
            candidate.write_text('{"role":"fixture"}\n', encoding="utf-8")
            record = {
                "path": candidate.relative_to(workspace).as_posix(),
                "sha256": hashlib.sha256(candidate.read_bytes()).hexdigest().upper(),
            }
            self.assertEqual(
                _workspace_record(workspace, record, "three-zone T5 Candidate"),
                candidate,
            )
            stale = dict(record)
            stale["sha256"] = "A" * 64
            with self.assertRaisesRegex(ContractError, "SHA-256 is stale"):
                _workspace_record(
                    workspace, stale, "three-zone T5 Candidate"
                )
            outside = workspace / "outside.json"
            outside.write_text("{}\n", encoding="utf-8")
            escaped = {
                "path": outside.relative_to(workspace).as_posix(),
                "sha256": hashlib.sha256(outside.read_bytes()).hexdigest().upper(),
            }
            with self.assertRaisesRegex(
                ContractError, "missing or escapes workspace artifacts"
            ):
                _workspace_record(
                    workspace, escaped, "three-zone T5 Candidate"
                )

    def test_three_zone_field_profiles_publish_selectable_identities(self) -> None:
        configuration = load(CONFIG_ROOT / "simion_single_flight.json")
        profiles = {
            item["profile_id"]: item
            for item in configuration["accelerator_field_profiles"]
        }
        expected = {
            "topology_id": "three_zone_accelerator_ideal_v1",
            "geometry_id": "three_zone_focus_origin_planes_v1",
            "frontend_electrode_topology_id": "three_zone_frontend_v1",
        }
        field_ids = {
            "accelerator_ideal_three_zone_real_reflectron":
                "three_zone_piecewise_uniform_ideal_field_v1",
            "accelerator_real_three_zone_ideal_reflectron":
                "three_zone_real_pa_plus_reflectron_piecewise_uniform_ideal_field_v1",
            "accelerator_real_three_zone_pa_real_reflectron":
                "three_zone_refined_pa_field_v1",
            "three_zone_explicit_region_modes":
                "three_zone_explicit_region_modes_v1",
        }
        for profile_id, field_id in field_ids.items():
            with self.subTest(profile_id=profile_id):
                profile = profiles[profile_id]
                self.assertTrue(
                    all(profile[key] == value for key, value in expected.items())
                )
                self.assertEqual(profile["field_id"], field_id)

    def test_loader_budget_requires_campaign_v5_and_staged_mode_both_ways(self) -> None:
        campaign = load(
            CONFIG_ROOT / "diagnostics" /
            "staged_grid2_restart_legacy_n34_successor_r06_campaign.json"
        )
        validate_schema(
            campaign, "rf_multipole_oatof_experiment_campaign.schema.json"
        )
        invalid = json.loads(json.dumps(campaign))
        invalid["schema_version"] = 4
        with self.assertRaises(ContractError):
            validate_schema(
                invalid, "rf_multipole_oatof_experiment_campaign.schema.json"
            )
        invalid = json.loads(json.dumps(campaign))
        invalid["experiments"][0]["source_release_mode"] = "pre_pulse_restart"
        with self.assertRaises(ContractError):
            validate_schema(
                invalid, "rf_multipole_oatof_experiment_campaign.schema.json"
            )
        invalid = json.loads(json.dumps(campaign))
        del invalid["experiments"][0]["staged_grid2_source_state"][
            "loader_authorization_budget"
        ]
        with self.assertRaises(ContractError):
            validate_schema(
                invalid, "rf_multipole_oatof_experiment_campaign.schema.json"
            )

    def test_loader_receipt_identity_is_raw_bytes_not_normalized_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt = root / "receipt.json"
            crlf = b'{\r\n  "status": "PASS"\r\n}\r\n'
            receipt.write_bytes(crlf)
            record = {
                "path": "receipt.json",
                "sha256": hashlib.sha256(crlf).hexdigest().upper(),
            }
            self.assertEqual(
                _repo_byte_record(root, record, "loader receipt"), receipt
            )
            receipt.write_bytes(crlf.replace(b"\r\n", b"\n"))
            with self.assertRaisesRegex(ContractError, "missing, stale"):
                _repo_byte_record(root, record, "loader receipt")

    def test_adapter_rejects_prepared_pa_cache_policy_and_budget_tampering(self) -> None:
        campaign = load(STAGED_GRID2_R03_CAMPAIGN)
        experiment_id = campaign["experiments"][0]["experiment_id"]
        adapter = (
            INTEGRATION_ROOT / "workflows" / "family_source_closure" / "adapter.ps1"
        )
        scratch = REPO_ROOT.parent / "artifacts" / "projects" / INTEGRATION_ID / "scratch"
        scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as directory, \
                tempfile.TemporaryDirectory(dir=CONFIG_ROOT) as config_directory:
            output = Path(directory)
            current_campaign_path = Path(config_directory) / "campaign.json"
            campaign["execution_policy"] = load(OCTUPOLE_RUNTIME_BINDING)[
                "contracts"
            ]["execution_policy_contract"]
            write_json(current_campaign_path, campaign)
            resolved_path = output / "resolved_connection.json"
            plan_path = output / "composition_plan.json"
            prepare_family_source_closure(
                repo_root=REPO_ROOT,
                profile_registry_path=PROFILE_REGISTRY,
                adapter_registry_path=ADAPTER_REGISTRY,
                campaign_path=current_campaign_path,
                experiment_id=experiment_id,
                resolved_output=resolved_path,
                plan_output=plan_path,
            )
            original_plan = load(plan_path)
            budget_path = output / "resolved_engineering_budget.json"
            original_budget = load(budget_path)

            def invoke_adapter() -> subprocess.CompletedProcess[str]:
                return subprocess.run(
                    [
                        "pwsh", "-NoProfile", "-File", str(adapter),
                        "-CompositionPlan", str(plan_path),
                        "-ResolvedConnection", str(resolved_path),
                        "-PythonExe", str(REPO_ROOT / ".venv" / "Scripts" / "python.exe"),
                        "-RepoRoot", str(REPO_ROOT), "-PrepareOnly",
                    ],
                    cwd=REPO_ROOT, text=True, encoding="utf-8", errors="replace",
                    capture_output=True, check=False, timeout=300,
                )

            tampered_plan = json.loads(json.dumps(original_plan))
            arguments = tampered_plan["execution_steps"][0]["arguments"]
            policy_index = next(
                index for index, value in enumerate(arguments)
                if value.startswith("single_flight_pa_cache_policy=")
            )
            arguments[policy_index] = "single_flight_pa_cache_policy=require_existing"
            write_json(plan_path, tampered_plan)
            plan_result = invoke_adapter()
            self.assertNotEqual(plan_result.returncode, 0)
            self.assertIn(
                "Frozen PA cache policy differs from the exact campaign row",
                plan_result.stdout + plan_result.stderr,
            )

            tampered_budget = json.loads(json.dumps(original_budget))
            tampered_budget["single_flight_pa_cache_policy"] = "require_existing"
            write_json(budget_path, tampered_budget)
            budget_hash = hashlib.sha256(budget_path.read_bytes()).hexdigest().upper()
            budget_plan = json.loads(json.dumps(original_plan))
            arguments = budget_plan["execution_steps"][0]["arguments"]
            budget_index = next(
                index for index, value in enumerate(arguments)
                if value.startswith("resolved_budget_sha256=")
            )
            arguments[budget_index] = f"resolved_budget_sha256={budget_hash}"
            write_json(plan_path, budget_plan)
            budget_result = invoke_adapter()
            self.assertNotEqual(budget_result.returncode, 0)
            self.assertIn(
                "Campaign budget and runtime source identities differ before stage 1",
                budget_result.stdout + budget_result.stderr,
            )

    def test_adapter_validates_pulse_orchestration_argument_group_and_file(self) -> None:
        adapter = (
            INTEGRATION_ROOT / "workflows" / "family_source_closure" / "adapter.ps1"
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            orchestration = root / "resolved_pulse_timing_orchestration.json"
            write_json(orchestration, {"state": "ready_verified"})
            script = r"""
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
  $env:RF_ADAPTER_PATH, [ref]$null, [ref]$parseErrors
)
if ($parseErrors) { throw $parseErrors[0] }
$functionAst = $ast.Find({
  param($node)
  $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
    $node.Name -eq 'Resolve-RfPulseTimingOrchestrationArguments'
}, $true)
if ($null -eq $functionAst) { throw 'orchestration resolver is missing' }
. ([scriptblock]::Create($functionAst.Extent.Text))
$frozen = @{
  pulse_timing_orchestration_filename = 'resolved_pulse_timing_orchestration.json'
  pulse_timing_orchestration_sha256 = $env:RF_ORCHESTRATION_SHA256
  pulse_timing_orchestration_state = 'ready_verified'
}
$names = @(Resolve-RfPulseTimingOrchestrationArguments `
  -FrozenArguments $frozen -PreparedRoot $env:RF_PREPARED_ROOT)
if ($names.Count -ne 3) { throw 'valid orchestration group did not resolve' }
'VALID=PASS'
$missing = $frozen.Clone()
$missing.Remove('pulse_timing_orchestration_sha256')
try {
  $null = Resolve-RfPulseTimingOrchestrationArguments -FrozenArguments $missing
  throw 'partial orchestration group was accepted'
} catch {
  if ($_.Exception.Message -notmatch 'all-or-none') { throw }
}
'PARTIAL=REJECTED'
$invalidState = $frozen.Clone()
$invalidState.pulse_timing_orchestration_state = 'fallback'
try {
  $null = Resolve-RfPulseTimingOrchestrationArguments -FrozenArguments $invalidState
  throw 'invalid orchestration state was accepted'
} catch {
  if ($_.Exception.Message -notmatch 'filename or state') { throw }
}
'STATE=REJECTED'
$stale = $frozen.Clone()
$stale.pulse_timing_orchestration_sha256 = '0' * 64
try {
  $null = Resolve-RfPulseTimingOrchestrationArguments `
    -FrozenArguments $stale -PreparedRoot $env:RF_PREPARED_ROOT
  throw 'stale orchestration file was accepted'
} catch {
  if ($_.Exception.Message -notmatch 'missing, misplaced or stale') { throw }
}
'SHA=REJECTED'
"""
            environment = os.environ.copy()
            environment.update({
                "RF_ADAPTER_PATH": str(adapter),
                "RF_PREPARED_ROOT": str(root),
                "RF_ORCHESTRATION_SHA256": hashlib.sha256(
                    orchestration.read_bytes()
                ).hexdigest().upper(),
            })
            completed = subprocess.run(
                ["pwsh", "-NoProfile", "-Command", script],
                cwd=REPO_ROOT,
                env=environment,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                check=False, timeout=300,
            )
            self.assertEqual(
                completed.returncode, 0, completed.stdout + completed.stderr
            )
            self.assertIn("VALID=PASS", completed.stdout)
            self.assertIn("PARTIAL=REJECTED", completed.stdout)
            self.assertIn("STATE=REJECTED", completed.stdout)
            self.assertIn("SHA=REJECTED", completed.stdout)

    def test_adapter_authorizes_base_prepare_only_discovery_arguments(self) -> None:
        adapter = (
            INTEGRATION_ROOT / "workflows" / "family_source_closure" / "adapter.ps1"
        )
        script = r"""
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
  $env:RF_ADAPTER_PATH, [ref]$null, [ref]$parseErrors
)
if ($parseErrors) { throw $parseErrors[0] }
function Get-UniqueExtent([scriptblock]$Predicate) {
  $matches = @($ast.FindAll($Predicate, $true))
  if ($matches.Count -ne 1) { throw "expected one adapter logic node" }
  return $matches[0].Extent.Text
}
$discoveryRequired = Get-UniqueExtent {
  param($node)
  $node -is [System.Management.Automation.Language.AssignmentStatementAst] -and
    $node.Left.Extent.Text -eq '$pulseTimingDiscoveryRequired'
}
$authorityMismatch = Get-UniqueExtent {
  param($node)
  $node -is [System.Management.Automation.Language.IfStatementAst] -and
    $node.Extent.Text -match
      'Pre-pulse time-series campaign and prepared authority differ'
}
$screening = Get-UniqueExtent {
  param($node)
  $node -is [System.Management.Automation.Language.AssignmentStatementAst] -and
    $node.Left.Extent.Text -eq '$prePulseTimeSeriesScreening'
}
$logic = [scriptblock]::Create(
  $discoveryRequired + [Environment]::NewLine +
  $authorityMismatch + [Environment]::NewLine + $screening
)
function Invoke-BasePrepareOnlyCase([string]$State, [bool]$HasArguments) {
  $automaticPulseTiming = $true
  $frozenArguments = @{ pulse_timing_orchestration_state = $State }
  $campaignHasPrePulseTimeSeries = $false
  $pulseTimingDiscovery = $false
  $hasPrePulseTimeSeriesArguments = $HasArguments
  . $logic
  return [bool]$prePulseTimeSeriesScreening
}
if (-not (Invoke-BasePrepareOnlyCase 'discovery_required' $true)) {
  throw 'base PrepareOnly discovery authority was not enabled'
}
'VALID=PASS'
foreach ($case in @(
    @{ state = 'ready_verified'; arguments = $true },
    @{ state = 'discovery_required'; arguments = $false }
  )) {
  try {
    $null = Invoke-BasePrepareOnlyCase $case.state $case.arguments
    throw 'mismatched base discovery authority was accepted'
  } catch {
    if ($_.Exception.Message -notmatch 'prepared authority differ') { throw }
  }
}
'MISMATCHES=REJECTED'
"""
        completed = subprocess.run(
            ["pwsh", "-NoProfile", "-Command", script],
            cwd=REPO_ROOT,
            env={**os.environ, "RF_ADAPTER_PATH": str(adapter)},
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False, timeout=300,
        )
        self.assertEqual(
            completed.returncode, 0, completed.stdout + completed.stderr
        )
        self.assertIn("VALID=PASS", completed.stdout)
        self.assertIn("MISMATCHES=REJECTED", completed.stdout)

    def test_adapter_base_discovery_accepts_artifact_population_and_input_contract(
        self,
    ) -> None:
        adapter = (
            INTEGRATION_ROOT / "workflows" / "family_source_closure" / "adapter.ps1"
        )
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            run_directory = workspace / "run"
            inputs = run_directory / "inputs"
            artifacts = workspace / "artifacts"
            inputs.mkdir(parents=True)
            artifacts.mkdir()
            prefix = artifacts / "source.csv"
            contract = inputs / "pre_pulse_time_series_screening_contract.json"
            prefix.write_text("particle_id\n1\n", encoding="utf-8")
            contract.write_text("{}\n", encoding="utf-8")
            script = r"""
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
  $env:RF_ADAPTER_PATH, [ref]$null, [ref]$parseErrors
)
if ($parseErrors) { throw $parseErrors[0] }
function Get-UniqueExtent([scriptblock]$Predicate) {
  $matches = @($ast.FindAll($Predicate, $true))
  if ($matches.Count -ne 1) { throw 'expected one adapter input-authority node' }
  return $matches[0].Extent.Text
}
$authorityLogic = [scriptblock]::Create((Get-UniqueExtent {
  param($node)
  $node -is [System.Management.Automation.Language.AssignmentStatementAst] -and
    $node.Left.Extent.Text -eq '$pulseTimingDiscoveryAuthority'
}))
$expectedPrefixLogic = [scriptblock]::Create((Get-UniqueExtent {
  param($node)
  $node -is [System.Management.Automation.Language.AssignmentStatementAst] -and
    $node.Left.Extent.Text -eq '$expectedTimeSeriesPrefix'
}))
$validationLogic = [scriptblock]::Create((Get-UniqueExtent {
  param($node)
  $node -is [System.Management.Automation.Language.IfStatementAst] -and
    $node.Extent.Text -match '^if \(\[IO\.Path\]::IsPathRooted' -and
    $node.Extent.Text -match 'Plan-bound pre-pulse time-series inputs'
}))
$runDirectory = [IO.Path]::GetFullPath($env:RF_RUN_DIRECTORY)
$workspaceRoot = [IO.Path]::GetFullPath($env:RF_WORKSPACE)
$inputsRoot = (Join-Path $runDirectory 'inputs') +
  [IO.Path]::DirectorySeparatorChar
$artifactsRoot = (Join-Path $workspaceRoot 'artifacts') +
  [IO.Path]::DirectorySeparatorChar
$prePulseTimeSeriesPrefixBinding = 'artifacts/source.csv'
$prePulseTimeSeriesPrefixPath = [IO.Path]::GetFullPath($env:RF_PREFIX_PATH)
$prePulseTimeSeriesContractPath = [IO.Path]::GetFullPath($env:RF_CONTRACT_PATH)
$frozenArguments = @{
  pre_pulse_time_series_prefix_filename = $prePulseTimeSeriesPrefixBinding
  pre_pulse_time_series_prefix_sha256 = $env:RF_PREFIX_SHA256
  pre_pulse_time_series_prefix_count = '1'
  pre_pulse_time_series_contract_filename =
    'inputs/pre_pulse_time_series_screening_contract.json'
  pre_pulse_time_series_contract_sha256 = $env:RF_CONTRACT_SHA256
}
$experiment = [pscustomobject]@{
  single_flight_population = [pscustomobject]@{
    execution_population = [pscustomobject]@{ particle_count = 1 }
  }
}
$connectorGapScreening = $false
$pulseTimingDiscovery = $false
$pulseTimingDiscoveryRequired = $true
. $authorityLogic
. $expectedPrefixLogic
. $validationLogic
'BASE_DISCOVERY_INPUTS=PASS'
$pulseTimingDiscoveryRequired = $false
. $authorityLogic
. $expectedPrefixLogic
try {
  . $validationLogic
  throw 'artifact population was accepted without discovery authority'
} catch {
  if ($_.Exception.Message -notmatch 'missing or stale') { throw }
}
'NO_AUTHORITY=REJECTED'
"""
            environment = os.environ.copy()
            environment.update({
                "RF_ADAPTER_PATH": str(adapter),
                "RF_WORKSPACE": str(workspace),
                "RF_RUN_DIRECTORY": str(run_directory),
                "RF_PREFIX_PATH": str(prefix),
                "RF_PREFIX_SHA256": hashlib.sha256(prefix.read_bytes())
                .hexdigest().upper(),
                "RF_CONTRACT_PATH": str(contract),
                "RF_CONTRACT_SHA256": hashlib.sha256(contract.read_bytes())
                .hexdigest().upper(),
            })
            completed = subprocess.run(
                ["pwsh", "-NoProfile", "-Command", script],
                cwd=REPO_ROOT,
                env=environment,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                check=False, timeout=300,
            )
            self.assertEqual(
                completed.returncode, 0, completed.stdout + completed.stderr
            )
            self.assertIn("BASE_DISCOVERY_INPUTS=PASS", completed.stdout)
            self.assertIn("NO_AUTHORITY=REJECTED", completed.stdout)

    def test_execute_reads_only_the_prepared_pulse_orchestration_identity(self) -> None:
        entry = (
            INTEGRATION_ROOT / "workflows" / "family_source_closure" / "execute.ps1"
        )
        source = entry.read_text(encoding="utf-8")
        self.assertIn("'discovery_required'", source)
        self.assertIn("'confirmation_required'", source)
        self.assertIn("'ready_verified'", source)
        self.assertIn("--pulse-timing-transition", source)
        self.assertIn("transition_relative_path", source)
        self.assertNotIn("Get-ChildItem -Recurse", source)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            orchestration_path = root / "resolved_pulse_timing_orchestration.json"
            orchestration = {
                "role": "rf_oatof_resolved_pulse_timing_orchestration",
                "campaign_id": "test_campaign",
                "experiment_id": "test_experiment",
                "original_run_id": "20260818_235900__sim__cross__test__n1",
                "state": "ready_verified",
            }
            write_json(orchestration_path, orchestration)
            plan_path = root / "composition_plan.json"
            write_json(
                plan_path,
                {
                    "execution_steps": [{
                        "arguments": [
                            "pulse_timing_orchestration_filename="
                            + orchestration_path.name,
                            "pulse_timing_orchestration_sha256="
                            + hashlib.sha256(orchestration_path.read_bytes())
                            .hexdigest().upper(),
                            "pulse_timing_orchestration_state=ready_verified",
                        ]
                    }]
                },
            )
            script = r"""
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
  $env:RF_EXECUTE_PATH, [ref]$null, [ref]$parseErrors
)
if ($parseErrors) { throw $parseErrors[0] }
foreach ($name in @(
    'Get-CompositionPlanArgumentMap', 'Get-PulseTimingOrchestration'
  )) {
  $functionAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
      $node.Name -eq $name
  }, $true)
  if ($null -eq $functionAst) { throw "missing function: $name" }
  . ([scriptblock]::Create($functionAst.Extent.Text))
}
$campaignDocument = [pscustomobject]@{ campaign_id = 'test_campaign' }
$ExperimentId = 'test_experiment'
$campaignRunId = '20260818_235900__sim__cross__test__n1'
$result = Get-PulseTimingOrchestration `
  -PlanPath $env:RF_PLAN_PATH -PreparedRoot $env:RF_PREPARED_ROOT
"STATE=$($result.state)"
"""
            environment = os.environ.copy()
            environment.update({
                "RF_EXECUTE_PATH": str(entry),
                "RF_PLAN_PATH": str(plan_path),
                "RF_PREPARED_ROOT": str(root),
            })
            result = subprocess.run(
                ["pwsh", "-NoProfile", "-Command", script],
                cwd=REPO_ROOT,
                env=environment,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                check=False, timeout=300,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("STATE=ready_verified", result.stdout)

            orchestration["state"] = "discovery_required"
            write_json(orchestration_path, orchestration)
            stale = subprocess.run(
                ["pwsh", "-NoProfile", "-Command", script],
                cwd=REPO_ROOT,
                env=environment,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                check=False, timeout=300,
            )
            self.assertNotEqual(stale.returncode, 0)
            self.assertIn(
                "Prepared pulse-timing orchestration SHA-256 differs",
                stale.stdout + stale.stderr,
            )

    def test_all_modes_reject_retired_campaign_before_schema_or_prepare(self) -> None:
        campaign = CONFIG_ROOT / "diagnostics" / (
            "staged_grid2_restart_legacy_n34_successor_campaign.json"
        )
        execute = INTEGRATION_ROOT / "workflows" / "family_source_closure" / (
            "execute.ps1"
        )
        execute_source = execute.read_text(encoding="utf-8")
        self.assertIn("@('retired', 'archived_invalid')", execute_source)
        campaign_schema = load(
            REPO_ROOT / "common" / "contracts" / "schemas" /
            "rf_multipole_oatof_experiment_campaign.schema.json"
        )
        self.assertIn(
            "PENDING_PREREGISTRATION",
            campaign_schema["properties"]["status"]["enum"],
        )
        self.assertIn("retired", campaign_schema["properties"]["status"]["enum"])
        completed = subprocess.run(
            [
                "pwsh", "-NoProfile", "-File", str(execute),
                "-Campaign", str(campaign.relative_to(REPO_ROOT)),
                "-ExperimentId", "staged_grid2_restart_legacy_n34_functional",
                "-ValidateOnly",
            ],
            cwd=REPO_ROOT,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False, timeout=300,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn(
            "Campaign is not an active lifecycle authority; execution is forbidden",
            completed.stdout + completed.stderr,
        )
        self.assertNotIn("CAMPAIGN_SOURCE_BINDINGS=STALE", completed.stdout)

    def test_authorized_campaigns_are_exactly_registry_bound(self) -> None:
        campaigns = []
        for path in INTEGRATION_ROOT.rglob("*.json"):
            try:
                document = load(path)
            except Exception:
                continue
            if document.get("role") == "rf_multipole_oatof_experiment_campaign":
                campaigns.append((path, document))
        authorized = [(path, row) for path, row in campaigns if row["status"] == "authorized"]
        self.assertGreater(len(authorized), 0)
        registry = load(CONFIG_ROOT / "family_source_closure_execution_registry.json")
        registered = {
            (REPO_ROOT / row["path"]).resolve()
            for row in registry["current_campaigns"]
        }
        self.assertEqual({path.resolve() for path, _ in authorized}, registered)

    def test_staged_n34_runner_filters_fly2_framing_before_batch_slice(self) -> None:
        campaign = load(
            CONFIG_ROOT / "diagnostics" /
            "staged_grid2_restart_legacy_n34_successor_r02_campaign.json"
        )
        source = REPO_ROOT.parent / campaign["experiments"][0][
            "staged_grid2_source_state"
        ]["path"]
        fly2_text, rows = materialize_staged_grid2_restart(source)
        self.assertEqual(len(rows), 34)
        with tempfile.TemporaryDirectory() as directory:
            fly2 = Path(directory) / "staged_n34.fly2"
            fly2.write_text(fly2_text, encoding="utf-8")
            runner = INTEGRATION_ROOT / "runtime" / "run_single_flight.ps1"
            script = r"""
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
  $env:RF_RUNNER_TEST_PATH, [ref]$null, [ref]$parseErrors
)
if ($parseErrors) { throw $parseErrors[0] }
$functionAst = $ast.Find({
  param($node)
  $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
    $node.Name -eq 'Get-RfSingleFlightParticleLines'
}, $true)
if ($null -eq $functionAst) { throw 'runner particle parser is missing' }
. ([scriptblock]::Create($functionAst.Extent.Text))
$particleRows = @(Get-RfSingleFlightParticleLines `
  -ParticleInput $env:RF_FLY2_TEST_PATH -RestartFly2 $true)
$batchRows = [string[]]$particleRows[0..33]
[ordered]@{
  particle_row_count = $particleRows.Count
  non_particle_row_count = @($particleRows | Where-Object {
    $_ -notmatch '^  standard_beam '
  }).Count
  batch_particle_row_count = @($batchRows | Where-Object {
    $_ -match '^  standard_beam '
  }).Count
} | ConvertTo-Json -Compress
"""
            environment = os.environ.copy()
            environment["RF_RUNNER_TEST_PATH"] = str(runner)
            environment["RF_FLY2_TEST_PATH"] = str(fly2)
            completed = subprocess.run(
                ["pwsh", "-NoProfile", "-Command", script],
                cwd=REPO_ROOT,
                env=environment,
                text=True,
                capture_output=True,
                check=False, timeout=300,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        receipt = json.loads(completed.stdout)
        self.assertEqual(receipt["particle_row_count"], 34)
        self.assertEqual(receipt["non_particle_row_count"], 0)
        self.assertEqual(receipt["batch_particle_row_count"], 34)

    def test_adapter_freezes_campaign_and_row_before_solver_authorization(self) -> None:
        adapter = (
            INTEGRATION_ROOT / "workflows" / "family_source_closure" / "adapter.ps1"
        ).read_text(encoding="utf-8")
        campaign_hash = adapter.index("$frozenArguments.campaign_sha256")
        row_hash = adapter.index("$frozenArguments.experiment_row_sha256")
        solver_boundary = adapter.index("if (-not $SolverAuthorized)")
        runner_call = adapter.index("& $runtime.implementation.single_flight_runner")
        self.assertLess(campaign_hash, solver_boundary)
        self.assertLess(row_hash, solver_boundary)
        self.assertLess(solver_boundary, runner_call)

    def test_optional_pa_generation_binding_is_initialized_after_campaign_resolution(self) -> None:
        adapter = (
            INTEGRATION_ROOT / "workflows" / "family_source_closure" / "adapter.ps1"
        ).read_text(encoding="utf-8")
        experiment_resolution = adapter.index("$experiment = $experiments[0]")
        run_directory = adapter.index("$runDirectory = [IO.Path]::GetFullPath")
        optional_binding = adapter.index("$campaignHasPaCacheGenerationBinding =")
        solver_boundary = adapter.index("if (-not $SolverAuthorized)")
        runner_call = adapter.index("& $runtime.implementation.single_flight_runner")
        self.assertLess(experiment_resolution, optional_binding)
        self.assertLess(run_directory, optional_binding)
        self.assertLess(optional_binding, solver_boundary)
        self.assertLess(solver_boundary, runner_call)

    def test_adapter_fails_closed_on_connector_gap_prefix_before_solver(self) -> None:
        adapter = (
            INTEGRATION_ROOT / "workflows" / "family_source_closure" / "adapter.ps1"
        ).read_text(encoding="utf-8")
        argument_gate = adapter.index("'connector_gap_prefix_filename'")
        campaign_gate = adapter.index(
            "Connector-gap campaign and prepared prefix authority differ."
        )
        mutual_exclusion = adapter.index(
            "Pulse-resolution and connector-gap prefix authorities are mutually exclusive."
        )
        path_gate = adapter.index("$expectedConnectorGapPrefix")
        missing_gate = adapter.index(
            "Test-Path -LiteralPath $connectorGapPrefixPath", path_gate
        )
        tamper_gate = adapter.index(
            "Get-FileHash -LiteralPath $connectorGapPrefixPath", path_gate
        )
        assignment = adapter.index(
            "$runnerArguments.MotherParticleSource = $preparedPrefixPath"
        )
        source_root_assignment = adapter.index(
            "$runnerArguments.MotherParticleSourceRunRoot = $runDirectory"
        )
        runner_call = adapter.index("& $runtime.implementation.single_flight_runner")
        self.assertIn("'connector_gap_prefix_sha256'", adapter[argument_gate:campaign_gate])
        self.assertIn(
            "inputs/connector_gap_screening_prefix_n100.csv",
            adapter[path_gate:assignment],
        )
        self.assertIn("-ne 100", adapter[path_gate:assignment])
        self.assertLess(argument_gate, campaign_gate)
        self.assertLess(campaign_gate, mutual_exclusion)
        self.assertLess(mutual_exclusion, path_gate)
        self.assertLess(path_gate, missing_gate)
        self.assertLess(missing_gate, tamper_gate)
        self.assertLess(tamper_gate, assignment)
        self.assertLess(assignment, source_root_assignment)
        self.assertLess(source_root_assignment, runner_call)
        self.assertLess(assignment, runner_call)

    def test_adapter_uses_only_frozen_canonical_region_field_profile(self) -> None:
        adapter = (
            INTEGRATION_ROOT / "workflows" / "family_source_closure" / "adapter.ps1"
        ).read_text(encoding="utf-8")
        prepare = (
            INTEGRATION_ROOT / "workflows" / "family_source_closure" / "prepare.py"
        ).read_text(encoding="utf-8")
        common_execute = (
            REPO_ROOT / "common" / "integration" / "execute_connection.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn('"resolved_region_field_profile_id="', prepare)
        self.assertIn(
            "$runnerArguments.PulseResolutionFieldProfileId =\n"
            "      [string]$frozenArguments.resolved_region_field_profile_id",
            adapter,
        )
        self.assertNotIn(
            "$frozenArguments.single_flight_accelerator_field_profile_id",
            adapter,
        )
        validate_exit = common_execute.index("if ($ValidateOnly)")
        adapter_call = common_execute.index("& $AdapterEntrypoint @adapterArguments")
        self.assertLess(validate_exit, adapter_call)
        self.assertIn("exit 0", common_execute[validate_exit:adapter_call])

    def test_staged_grid2_schema_forbids_pulse_schedule_and_binds_instance_overlay(self) -> None:
        campaign_path = CONFIG_ROOT / "diagnostics" / (
            "staged_grid2_restart_legacy_n34_successor_r02_campaign.json"
        )
        campaign = load(campaign_path)
        validate_schema(campaign, "rf_multipole_oatof_experiment_campaign.schema.json")
        row = campaign["experiments"][0]
        self.assertNotIn("single_flight_pulse_schedule_policy", row)
        self.assertEqual(row["source"]["authority_scope"], "connection_lineage_only")
        with_schedule = json.loads(json.dumps(campaign))
        with_schedule["experiments"][0]["single_flight_pulse_schedule_policy"] = {
            "policy_id": "multipole_handoff_ballistic_centroid_v1",
            "offset_rf_periods": 0,
            "pulse_width_us": 1.0,
        }
        with self.assertRaises(ContractError):
            validate_schema(
                with_schedule, "rf_multipole_oatof_experiment_campaign.schema.json"
            )
        wrong_instance = json.loads(json.dumps(campaign))
        wrong_instance["experiments"][0]["staged_grid2_source_state"][
            "simion_start_instance"
        ] = 5
        with self.assertRaises(ContractError):
            validate_schema(
                wrong_instance, "rf_multipole_oatof_experiment_campaign.schema.json"
            )

    def test_affine_source_profile_resolves_only_from_phase_space_authority(self) -> None:
        registry = load(CONFIG_ROOT / "simion_single_flight.json")
        profile = next(
            item for item in registry["source_materialization_profiles"]
            if item["profile_id"] == "canonical_ideal_linear_z_vz_1mm_n1000"
        )
        self.assertNotIn("mean_velocity_z_m_per_s", profile)
        self.assertNotIn("velocity_z_slope_m_per_s_per_mm", profile)
        resolved = resolve_source_materialization_profile(profile, INTEGRATION_ROOT)
        authority = load(CONFIG_ROOT / "accelerator_phase_space_match.json")[
            "frozen_phase_space_input"
        ]
        self.assertEqual(
            resolved["mean_velocity_z_m_per_s"],
            authority["mean_initial_velocity_m_per_s"],
        )
        self.assertEqual(
            resolved["velocity_z_slope_m_per_s_per_mm"],
            authority["velocity_slope_m_per_s_per_mm"],
        )

    def test_zero_vz_match_layouts_use_solver_native_zero_zero_inputs(self) -> None:
        registry = load(CONFIG_ROOT / "single_flight_layout_profiles.json")
        base_geometry = load(
            REPO_ROOT
            / "projects/single_reflection_oa_tof_mass_analyzer/config/resolved_geometry.json"
        )
        base_port = load(
            REPO_ROOT
            / "projects/single_reflection_oa_tof_mass_analyzer/config/interfaces/required/oatof_accelerator_entry.json"
        )
        expected = {
            "zero_match_short_1mm": (
                "zero_match_short_1mm_v1",
                1.0,
            ),
            "zero_match_long_2p2mm": (
                "zero_match_long_2p2mm_v1",
                2.2,
            ),
        }
        for layout_id, (generation_id, width_mm) in expected.items():
            profile = select_profile(registry, layout_id)
            self.assertEqual(profile["architecture_generation_id"], generation_id)
            self.assertEqual(
                profile["finite_interval_accelerator_profile"],
                "config/accelerator_phase_space_match.json",
            )
            frozen = profile["finite_interval_phase_space_input"]
            self.assertEqual(frozen["mean_initial_velocity_m_per_s"], 0.0)
            self.assertEqual(frozen["velocity_slope_m_per_s_per_mm"], 0.0)
            self.assertEqual(profile["finite_interval_source_full_width_mm"], width_mm)
            geometry, _, _ = compile_geometry_and_port(
                base_geometry, base_port, profile
            )
            derivation = geometry["single_flight_layout_derivation"][
                "design_compilation"
            ]
            self.assertEqual(
                derivation["method"], "finite_interval_uniform_two_field_theory_v1"
            )
            self.assertEqual(
                derivation["simion_rebuild_plan"],
                {
                    "frontend_pa": True,
                    "flight_tube_pa": True,
                    "reflectron_pa": False,
                },
            )
            accelerator = geometry["geometry_derivation"]["accelerator"]
            self.assertEqual(accelerator["canonical_focus_z_mm"], 0.0)
            self.assertEqual(
                accelerator["finite_interval_theory"]["solver_phase_space_input"],
                {
                    name: frozen[name]
                    for name in (
                        "mass_to_charge_Th",
                        "release_position_mm",
                        "mean_initial_velocity_m_per_s",
                        "velocity_slope_m_per_s_per_mm",
                    )
                },
            )
            self.assertEqual(
                geometry["single_flight_layout_derivation"]
                ["finite_interval_input_provenance"],
                {
                    "profile_path": "config/accelerator_phase_space_match.json",
                    "phase_space_input": frozen,
                },
            )
            self.assertEqual(geometry["particle_source"]["size_z_mm"], width_mm)
            for electrode in ("repeller", "grid1", "midgrid", "backplate"):
                self.assertIsInstance(geometry["electrodes_V"][electrode], float)

    def test_canonical_source_architecture_field_matrix_has_strict_24_rows(self) -> None:
        campaign = load(SOURCE_ARCH_FIELD_MATRIX_PATH)
        validate_schema(campaign, "rf_multipole_oatof_experiment_campaign.schema.json")
        rows = campaign["experiments"]
        self.assertEqual(len(rows), 24)
        self.assertEqual([row["sequence"] for row in rows], list(range(1, 25)))
        self.assertEqual(
            {row["single_flight_source_materialization_profile_id"] for row in rows},
            {
                "canonical_ideal_linear_z_vz_1mm_n1000",
                "canonical_ideal_linear_z_vz_2p2mm_n1000",
                "canonical_real_octupole_n1000",
            },
        )
        self.assertEqual(
            {row["single_flight_accelerator_field_profile_id"] for row in rows},
            {
                "accelerator_real_pa",
                "accelerator_ideal_stage1_real_stage2",
                "accelerator_real_stage1_ideal_stage2",
                "accelerator_ideal_stage1_stage2_real_reflectron",
            },
        )
        self.assertTrue(all(
            row["single_flight_frontend_grid_profile_id"]
            == "frontend_isotropic_020_accelerator_overlay_z005"
            and row["single_flight_oatof_numerical_profile_id"]
            == "oatof_formal_mesh"
            and row["single_flight_trajectory_quality_profile_id"] == "tqual_8"
            for row in rows
        ))
        configuration = load(CONFIG_ROOT / "simion_single_flight.json")
        selected_grid = next(
            profile for profile in configuration["frontend_grid_profiles"]
            if profile["profile_id"]
            == "frontend_isotropic_020_accelerator_overlay_z005"
        )
        batching = configuration["batching_policy"]
        self.assertEqual(selected_grid["max_parallel_batches"], 2)
        selected_grid_parallel3 = next(
            profile for profile in configuration["frontend_grid_profiles"]
            if profile["profile_id"]
            == "frontend_isotropic_020_accelerator_overlay_z005_parallel3"
        )
        self.assertEqual(selected_grid_parallel3["max_parallel_batches"], 3)
        self.assertEqual(
            batching["parallel_batch_memory_reservation_bytes"], 10 * 1024**3,
        )
        self.assertEqual(
            batching["parallel_batch_observed_peak_working_set_bytes"],
            8_700_387_328,
        )
        self.assertGreater(
            batching["parallel_batch_memory_reservation_bytes"],
            batching["parallel_batch_observed_peak_working_set_bytes"],
        )
        for retired in (
            "enabled_at_particle_count", "default_batch_count",
            "parallel_after_cache_warmup", "cache_warmup_batch_count",
        ):
            self.assertNotIn(retired, batching)

    def test_n1000_v3_changes_only_identity_and_execution_batching(self) -> None:
        v2 = load(
            CONFIG_ROOT / "diagnostics" /
            "connector_gap_three_zone_real_pa_full_n1000_campaign_v2.json"
        )
        v3 = load(AUTO_N1000_CONNECTOR_CAMPAIGN)
        use_current_time_grid_profile(v2)
        use_current_time_grid_profile(v3)
        validate_schema(v3, "rf_multipole_oatof_experiment_campaign.schema.json")
        self.assertIn("single_flight_batch_count=2", v3["claim_limit"])
        self.assertEqual(len(v2["experiments"]), len(v3["experiments"]))
        for before, after in zip(v2["experiments"], v3["experiments"], strict=True):
            self.assertEqual(after["single_flight_batch_count"], 2)
            normalized_before = dict(before)
            normalized_after = dict(after)
            for key in ("experiment_id", "run_id"):
                normalized_before.pop(key)
                normalized_after.pop(key)
            normalized_after.pop("single_flight_batch_count")
            self.assertEqual(normalized_before, normalized_after)

    def test_native_grid_short_focus_row_rebuilds_current_reflectron(self) -> None:
        campaign_path = (
            CONFIG_ROOT / "diagnostics" /
            "octupole_native_grid_short_focus_r100_n100_campaign.json"
        )
        campaign = load(campaign_path)
        validate_schema(campaign, "rf_multipole_oatof_experiment_campaign.schema.json")
        row = campaign["experiments"][0]
        self.assertIn("native-grid diagnostic", campaign["claim_limit"])
        self.assertNotIn("Candidate claim", campaign["claim_limit"])
        self.assertEqual(row["single_flight_layout_profile_id"], "theory_source_z10_d1_3")
        self.assertEqual(row["single_flight_frontend_grid_profile_id"], "frontend_isotropic_020_accelerator_overlay_z005")
        self.assertEqual(row["single_flight_oatof_numerical_profile_id"], "oatof_reflectron_z010_r100")
        self.assertEqual(row["source"]["launched_particle_count"], 100)
        scratch = (
            REPO_ROOT.parent / "artifacts" / "projects" / INTEGRATION_ID / "scratch"
        )
        scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as directory, \
                tempfile.TemporaryDirectory(dir=CONFIG_ROOT) as config_directory:
            output = Path(directory)
            current_campaign_path = Path(config_directory) / "campaign.json"
            write_current_policy_campaign(campaign_path, current_campaign_path)
            prepare_family_source_closure(
                repo_root=REPO_ROOT,
                profile_registry_path=PROFILE_REGISTRY,
                adapter_registry_path=ADAPTER_REGISTRY,
                campaign_path=current_campaign_path,
                experiment_id=row["experiment_id"],
                resolved_output=output / "resolved.json",
                plan_output=output / "plan.json",
            )
            geometry = load(output / "resolved_oatof_geometry.json")
        rebuild = geometry["single_flight_layout_derivation"]["design_compilation"][
            "simion_rebuild_plan"
        ]
        self.assertTrue(rebuild["frontend_pa"])
        self.assertTrue(rebuild["flight_tube_pa"])
        self.assertTrue(rebuild["reflectron_pa"])

    def test_ideal_accelerator_field_is_a_registered_counterfactual(self) -> None:
        campaign = load(IDEAL_FIELD_CAMPAIGN_PATH)
        validate_schema(
            campaign, "rf_multipole_oatof_experiment_campaign.schema.json"
        )
        row = campaign["experiments"][0]
        configuration = load(CONFIG_ROOT / "simion_single_flight.json")
        profiles = {
            item["profile_id"]: item
            for item in configuration["accelerator_field_profiles"]
        }
        self.assertEqual(
            configuration["default_accelerator_field_profile_id"],
            "accelerator_real_pa",
        )
        selected = profiles[row["single_flight_accelerator_field_profile_id"]]
        self.assertEqual(selected["accelerator_stage1"], "analytic_ideal_field")
        self.assertEqual(selected["accelerator_stage2"], "analytic_ideal_field")
        self.assertEqual(
            row["single_flight_frontend_grid_profile_id"],
            "frontend_isotropic_0125",
        )

    def test_grid_convergence_campaign_uses_registered_single_variable_profiles(self) -> None:
        campaign = load(GRID_CONVERGENCE_CAMPAIGN_PATH)
        validate_schema(
            campaign, "rf_multipole_oatof_experiment_campaign.schema.json"
        )
        configuration = load(CONFIG_ROOT / "simion_single_flight.json")
        profiles = {
            item["profile_id"]: item
            for item in configuration["frontend_grid_profiles"]
        }
        self.assertEqual(
            configuration["default_frontend_grid_profile_id"],
            "frontend_isotropic_020",
        )
        selected = [
            row["single_flight_frontend_grid_profile_id"]
            for row in campaign["experiments"]
        ]
        self.assertEqual(
            [profiles[profile_id]["cell_mm_xyz"] for profile_id in selected],
            [
                {"x": 0.2, "y": 0.2, "z": 0.2},
                {"x": 0.15, "y": 0.15, "z": 0.15},
                {"x": 0.125, "y": 0.125, "z": 0.125},
            ],
        )
        frozen_physics = [
            (
                row["single_flight_layout_profile_id"],
                row["single_flight_design_overrides"],
                row["single_flight_particle_source"],
            )
            for row in campaign["experiments"]
        ]
        self.assertTrue(all(item == frozen_physics[0] for item in frozen_physics))

    def test_acceleration_axis_grid_campaign_changes_only_z_discretization(self) -> None:
        campaign = load(ACCELERATION_AXIS_GRID_CAMPAIGN_PATH)
        validate_schema(
            campaign, "rf_multipole_oatof_experiment_campaign.schema.json"
        )
        configuration = load(CONFIG_ROOT / "simion_single_flight.json")
        profiles = {
            item["profile_id"]: item
            for item in configuration["frontend_grid_profiles"]
        }
        rows = campaign["experiments"]
        cells = [
            profiles[row["single_flight_frontend_grid_profile_id"]]["cell_mm_xyz"]
            for row in rows
        ]
        self.assertEqual(cells, [
            {"x": 0.2, "y": 0.2, "z": 0.1},
            {"x": 0.2, "y": 0.2, "z": 0.05},
        ])
        self.assertTrue(all("single_flight_design_overrides" not in row for row in rows))
        frozen_physics = [
            (
                row["single_flight_layout_profile_id"],
                row["single_flight_particle_source"],
                row["source"],
                row["single_flight_design_reference"],
            )
            for row in rows
        ]
        self.assertEqual(frozen_physics[0], frozen_physics[1])

    def test_unknown_frontend_grid_profile_is_rejected_before_execution(self) -> None:
        campaign = migrate_v3_campaign(load(GRID_CONVERGENCE_CAMPAIGN_PATH))
        campaign["experiments"][0][
            "single_flight_frontend_grid_profile_id"
        ] = "missing_grid_profile"
        with tempfile.TemporaryDirectory(dir=CONFIG_ROOT) as directory:
            root = Path(directory)
            campaign_path = root / "campaign.json"
            write_json(campaign_path, campaign)
            with self.assertRaisesRegex(
                ContractError, "grid profile must resolve exactly once"
            ):
                prepare_family_source_closure(
                    repo_root=REPO_ROOT,
                    profile_registry_path=PROFILE_REGISTRY,
                    adapter_registry_path=ADAPTER_REGISTRY,
                    campaign_path=campaign_path,
                    experiment_id="octupole_frontend_grid_020_n1000",
                    resolved_output=root / "resolved.json",
                    plan_output=root / "plan.json",
                )

    def test_pulse_policy_is_a_governed_campaign_value_without_a_default(self) -> None:
        campaign = migrate_v3_campaign(load(GRID_CONVERGENCE_CAMPAIGN_PATH))
        experiment = campaign["experiments"][0]
        source_run = (
            REPO_ROOT.parent / "artifacts/projects/rf_octupole_ion_optics/runs"
            / experiment["single_flight_design_reference"]["run_id"]
        )
        if not source_run.is_dir():
            self.skipTest("local single-flight design reference is unavailable")
        experiment["single_flight_pulse_schedule_policy"]["offset_rf_periods"] = -0.125
        experiment_policy = load(OCTUPOLE_RUNTIME_BINDING)["contracts"][
            "execution_policy_contract"
        ]
        campaign["execution_policy"] = experiment_policy
        validate_schema(
            campaign, "rf_multipole_oatof_experiment_campaign.schema.json"
        )
        with tempfile.TemporaryDirectory(dir=CONFIG_ROOT) as config_directory, \
                tempfile.TemporaryDirectory(
                    dir=REPO_ROOT.parent / "artifacts/projects/rf_octupole_ion_optics"
                ) as output_directory:
            campaign_path = Path(config_directory) / "campaign.json"
            write_json(campaign_path, campaign)
            output = Path(output_directory)
            prepare_family_source_closure(
                repo_root=REPO_ROOT,
                profile_registry_path=PROFILE_REGISTRY,
                adapter_registry_path=ADAPTER_REGISTRY,
                campaign_path=campaign_path,
                experiment_id=experiment["experiment_id"],
                resolved_output=output / "resolved.json",
                plan_output=output / "plan.json",
            )
            schedule = load(output / "resolved_single_flight_pulse_schedule.json")
            self.assertEqual(schedule["policy"]["offset_rf_periods"], -0.125)
            self.assertLess(
                schedule["pulse_effective_time_us"],
                schedule["pulse_base_time_us"],
            )
            self.assertAlmostEqual(
                schedule["base_predicted_centroid_error_x_mm"], 0.0, places=9
            )
            self.assertNotEqual(schedule["predicted_centroid_error_x_mm"], 0.0)

    def test_single_flight_design_overrides_are_optional_contract_data(self) -> None:
        default_campaign = load(SINGLE_FLIGHT_CAMPAIGN_PATH)
        self.assertNotIn(
            "single_flight_design_overrides", default_campaign["experiments"][0]
        )
        candidate = load(Z_ACCEPTANCE_CAMPAIGN_PATH)
        validate_schema(
            candidate, "rf_multipole_oatof_experiment_campaign.schema.json"
        )
        overrides = candidate["experiments"][0]["single_flight_design_overrides"]
        self.assertEqual(
            [item["variable"] for item in overrides],
            [
                "accelerator_stage1_length",
                "accelerator_stage2_length",
                "accelerator_grid1_voltage",
            ],
        )

    def test_campaign_rows_select_registered_runtime_bound_profiles(self) -> None:
        campaign = load(CAMPAIGN_PATH)
        validate_schema(campaign, "rf_multipole_oatof_experiment_campaign.schema.json")
        profiles = load(PROFILE_REGISTRY)["profiles"]
        profile_by_id = {
            profile["connection_profile_id"]: profile for profile in profiles
        }
        self.assertEqual(len(profile_by_id), len(profiles))
        for experiment in campaign["experiments"]:
            profile = profile_by_id[experiment["connection_profile_id"]]
            self.assertEqual(
                profile["upstream"]["port_binding"],
                "source_run_resolved_design",
            )
            self.assertNotIn("port_contract", profile["upstream"])

    def test_nonzero_octupole_connections_freeze_gap_geometry_and_bindings(self) -> None:
        profiles = {
            item["connection_profile_id"]: item
            for item in load(PROFILE_REGISTRY)["profiles"]
        }
        adapter_registry = load(ADAPTER_REGISTRY)
        validate_schema(adapter_registry, "execution_adapter_registry.schema.json")
        mappings = {
            item["connection_profile_id"]: item
            for item in adapter_registry["mappings"]
        }
        expected = {
            "3p2": (3.2, -151.6),
            "6p4": (6.4, -154.8),
            "12p8": (12.8, -161.2),
            "25p6": (25.6, -174.0),
            "51p2": (51.2, -199.6),
        }
        for slug, (length_mm, translation_x_mm) in expected.items():
            profile_id = (
                "rf_octupole_to_single_reflection_oatof_direct_mating_gap_51p2mm"
                if slug == "51p2"
                else "rf_octupole_oatof_shield_terminal_direct_mating_gap_"
                f"{slug}mm"
            )
            profile = profiles[profile_id]
            validate_schema(profile, "connection_profile.schema.json")
            self.assertEqual(profile["connector"]["length_mm"], length_mm)
            self.assertEqual(
                profile["spatial_registration"]["expected_gap_mm"], length_mm
            )
            self.assertEqual(
                profile["spatial_registration"]["translation_mm"][0],
                translation_x_mm,
            )
            direct = profiles[
                "rf_octupole_oatof_shield_terminal_direct_mating_gap_0mm"
            ]["spatial_registration"]["translation_mm"]
            derived_translation = derive_mating_translation_with_gap(
                profile["spatial_registration"]["rotation_upstream_to_downstream"],
                [0.0, 0.0, 0.0],
                [0.0, 0.0, 1.0],
                direct,
                length_mm,
            )
            for actual, derived in zip(
                profile["spatial_registration"]["translation_mm"],
                derived_translation,
                strict=True,
            ):
                self.assertAlmostEqual(actual, derived, places=12)
            self.assertEqual(
                profile["transition_aperture"],
                {
                    "shape": "rectangle",
                    "full_width_mm": 1.0,
                    "full_height_mm": 0.9,
                    "width_axis_downstream_frame": [0.0, 1.0, 0.0],
                    "height_axis_downstream_frame": [0.0, 0.0, 1.0],
                },
            )
            self.assertEqual(
                profile["field_ownership_segments"],
                [{"start_mm": 0.0, "end_mm": length_mm, "owner": "integration"}],
            )
            binding_path = CONFIG_ROOT / (
                f"family_octupole_direct_mating_gap_{slug}mm_runtime_binding.json"
            )
            self.assertEqual(
                mappings[profile_id]["runtime_binding_path"],
                binding_path.relative_to(REPO_ROOT).as_posix(),
            )
            binding = load(binding_path)
            validate_schema(binding, "rf_multipole_oatof_runtime_binding.schema.json")
            self.assertEqual(binding["connection_profile_id"], profile_id)

    def test_single_flight_run_stem_uses_resolved_connector_gap(self) -> None:
        for length_mm, expected in (
            (0.0, "__sim__simion__rf-oatof-single-flight-gap0__n"),
            (3.2, "__sim__simion__rf-oatof-single-flight-gap3p2__n"),
            (6.4, "__sim__simion__rf-oatof-single-flight-gap6p4__n"),
            (10, "__sim__simion__rf-oatof-single-flight-gap10__n"),
            (12.8, "__sim__simion__rf-oatof-single-flight-gap12p8__n"),
            (25.6, "__sim__simion__rf-oatof-single-flight-gap25p6__n"),
            (51.2, "__sim__simion__rf-oatof-single-flight-gap51p2__n"),
        ):
            self.assertEqual(
                _single_flight_run_stem({"connector": {"length_mm": length_mm}}),
                expected,
            )
        with self.assertRaises(ContractError):
            _single_flight_run_stem({"connector": {"length_mm": -1.0}})
        self.assertEqual(_retry_suffix("20260818_120000__sim__family__n100__r03"), "__r03")

    def test_pulse_discovery_child_run_stem_is_distinct_without_renaming_full_flight(
        self,
    ) -> None:
        resolved = {"connector": {"length_mm": 3.2}}
        full_flight = _single_flight_run_stem(resolved)
        confirmation = _single_flight_run_stem(
            resolved,
            pulse_timing_internal_stage="pulse_timing_confirmation",
        )
        discovery = _single_flight_run_stem(
            resolved,
            pulse_timing_internal_stage="pulse_timing_discovery",
        )
        self.assertEqual(
            full_flight,
            "__sim__simion__rf-oatof-single-flight-gap3p2__n",
        )
        self.assertEqual(confirmation, full_flight)
        self.assertEqual(
            discovery,
            "__sim__simion__rf-oatof-pulse-screen-gap3p2__n",
        )
        self.assertLessEqual(len(discovery), len(full_flight))
        adapter = (
            INTEGRATION_ROOT / "workflows" / "family_source_closure" / "adapter.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn("if ($pulseTimingDiscovery)", adapter)
        self.assertIn("'rf-oatof-pulse-screen'", adapter)
        self.assertIn("$expectedExecutionParticleCount$retrySuffix", adapter)

    def test_campaign_and_experiment_identities_are_unique(self) -> None:
        campaign = load(CAMPAIGN_PATH)
        experiment_ids = [row["experiment_id"] for row in campaign["experiments"]]
        sequences = [row["sequence"] for row in campaign["experiments"]]
        run_ids = [row["run_id"] for row in campaign["experiments"]]
        self.assertEqual(len(experiment_ids), len(set(experiment_ids)))
        self.assertEqual(len(sequences), len(set(sequences)))
        self.assertEqual(len(run_ids), len(set(run_ids)))

    def test_n1000_campaign_freezes_population_specific_handoff_contract(self) -> None:
        campaign = load(N1000_CAMPAIGN_PATH)
        validate_schema(campaign, "rf_multipole_oatof_experiment_campaign.schema.json")
        source = campaign["experiments"][0]["source"]
        record = source["handoff_publication_contract"]
        contract = load(REPO_ROOT / record["path"])
        self.assertEqual(source["launched_particle_count"], 1000)
        self.assertEqual(
            contract["population"]["expected_source_particle_count"],
            source["launched_particle_count"],
        )
        self.assertEqual(
            contract["canonical_state"]["source_component_id"],
            "rf_octupole_ion_optics",
        )

    def test_single_flight_can_reuse_population_with_a_frozen_design_reference(self) -> None:
        campaign = load(TERMINAL_DESIGN_REFERENCE_CAMPAIGN_PATH)
        validate_schema(campaign, "rf_multipole_oatof_experiment_campaign.schema.json")
        experiment = campaign["experiments"][0]
        self.assertEqual(experiment["source"]["launched_particle_count"], 1000)
        self.assertEqual(
            experiment["single_flight_design_reference"]["launched_particle_count"],
            100,
        )
        reference_run = (
            REPO_ROOT.parent / "artifacts/projects/rf_octupole_ion_optics/runs"
            / experiment["single_flight_design_reference"]["run_id"]
        )
        if not reference_run.is_dir():
            self.skipTest("local corrected terminal design reference is unavailable")
        with tempfile.TemporaryDirectory(
            dir=REPO_ROOT.parent / "artifacts/projects/rf_octupole_ion_optics"
        ) as directory, tempfile.TemporaryDirectory(dir=CONFIG_ROOT) as config_directory:
            output = Path(directory)
            campaign_path = Path(config_directory) / "campaign.json"
            write_current_policy_campaign(
                TERMINAL_DESIGN_REFERENCE_CAMPAIGN_PATH, campaign_path
            )
            _, plan = prepare_family_source_closure(
                repo_root=REPO_ROOT,
                profile_registry_path=PROFILE_REGISTRY,
                adapter_registry_path=ADAPTER_REGISTRY,
                campaign_path=campaign_path,
                experiment_id=experiment["experiment_id"],
                resolved_output=output / "resolved.json",
                plan_output=output / "plan.json",
            )
            design = load(plan.with_name("upstream_resolved_design.json"))
            source_contract = load(plan.with_name("resolved_source_contract.json"))
            sleeve = design["axial_dc"]["entrance_reference_sleeve"]
            self.assertEqual(sleeve["inner_radius_mm"], 0.75)
            self.assertEqual(sleeve["downstream_face_z_mm"], 0.0)
            self.assertEqual(
                source_contract["design_reference"]["run_id"],
                experiment["single_flight_design_reference"]["run_id"],
            )

    def test_prepare_rejects_campaign_outside_repository(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            outside = Path(directory)
            campaign = outside / "campaign.json"
            write_json(campaign, load(CAMPAIGN_PATH))
            with self.assertRaisesRegex(ContractError, "repository-managed"):
                prepare_family_source_closure(
                    repo_root=REPO_ROOT,
                    profile_registry_path=PROFILE_REGISTRY,
                    adapter_registry_path=ADAPTER_REGISTRY,
                    campaign_path=campaign,
                    experiment_id="unused",
                    resolved_output=outside / "resolved.json",
                    plan_output=outside / "plan.json",
                )

    def test_parent_publisher_requires_campaign_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            run_id = "20260803_220000__sim__cross__campaign-parent__n100"
            run_dir = workspace / run_id
            run_dir.mkdir()
            receipt = run_dir / "receipt.json"
            resolved = run_dir / "resolved.json"
            plan = run_dir / "plan.json"
            budget = run_dir / "budget.json"
            write_json(
                receipt,
                {
                    "role": "integration_family_source_closure_execution_receipt",
                    "integration_run_id": run_id,
                    "execution_status": "completed_pending_paired_analysis",
                },
            )
            write_json(resolved, {"integration_id": INTEGRATION_ID})
            write_json(plan, {"integration_id": INTEGRATION_ID})
            write_json(budget, {})
            with self.assertRaisesRegex(ContractError, "execution strategy is missing"):
                publish_family_source_closure_run(
                    repo_root=REPO_ROOT,
                    workspace_root=workspace,
                    integration_run_dir=run_dir,
                    receipt_path=receipt,
                    resolved_path=resolved,
                    plan_path=plan,
                    budget_path=budget,
                )


if __name__ == "__main__":
    unittest.main()

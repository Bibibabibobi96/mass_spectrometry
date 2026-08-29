"""Contract tests for the campaign-only multipole-to-oaTOF workflow."""

from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
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
    expand_flat_experiment_authoring,
    _resolve_single_flight_profiles,
    semantic_diff_experiments,
    _repo_byte_record,
    _workspace_record,
    prepare_family_source_closure,
    resolve_single_flight_dispatch_plan,
    resolve_generated_pre_pulse_ordered_subset,
    validate_three_zone_candidate_binding,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_source import (
    resolve_source_materialization_profile,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.ordered_pre_pulse_subset import (
    ordered_subset_source_particle_ids,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.workflows.family_source_closure.publish_run import (
    INTEGRATION_ID,
    _retry_suffix,
    _selection_is_explicitly_authorized,
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
SCHEMA_ROOT = CONFIG_ROOT / "schemas"
ACTIVE_CAMPAIGN_SCHEMA = CONFIG_ROOT / "schemas" / (
    "rf_multipole_oatof_experiment_campaign.schema.json"
)
ARCHIVAL_CAMPAIGN_SCHEMA = CONFIG_ROOT / "schemas" / "archive" / (
    "rf_multipole_oatof_experiment_campaign_v1_to_v6.schema.json"
)
HISTORICAL_ROOT_CAMPAIGNS = (
    INTEGRATION_ROOT / "docs" / "history" / "retired_campaigns" / "root_campaigns"
)
RETIRED_CAMPAIGNS = INTEGRATION_ROOT / "docs" / "history" / "retired_campaigns"
CAMPAIGN_PATH = HISTORICAL_ROOT_CAMPAIGNS / "experiment_campaign.json"
N1000_CAMPAIGN_PATH = (
    RETIRED_CAMPAIGNS / "octupole_simion_aperture050_n1000_campaign.json"
)
SINGLE_FLIGHT_CAMPAIGN_PATH = (
    RETIRED_CAMPAIGNS / "octupole_simion_single_flight_aperture100_n1000_campaign.json"
)
TERMINAL_DESIGN_REFERENCE_CAMPAIGN_PATH = (
    RETIRED_CAMPAIGNS
    / "octupole_terminal_15mm_sleeve_single_flight_n1000_campaign.json"
)
Z_ACCEPTANCE_CAMPAIGN_PATH = (
    RETIRED_CAMPAIGNS / "octupole_z_acceptance_d1_4mm_n1000_campaign.json"
)
GRID_CONVERGENCE_CAMPAIGN_PATH = (
    RETIRED_CAMPAIGNS / "octupole_frontend_grid_convergence_n1000_campaign.json"
)
ACCELERATION_AXIS_GRID_CAMPAIGN_PATH = (
    RETIRED_CAMPAIGNS
    / "octupole_frontend_acceleration_axis_grid_n1000_campaign.json"
)
IDEAL_FIELD_CAMPAIGN_PATH = (
    RETIRED_CAMPAIGNS / "octupole_accelerator_ideal_field_n1000_campaign.json"
)
SOURCE_ARCH_FIELD_MATRIX_PATH = (
    RETIRED_CAMPAIGNS /
    "canonical_source_architecture_accelerator_field_matrix_n1000_campaign.json"
)
PROFILE_REGISTRY = CONFIG_ROOT / "connection_profiles.json"
ADAPTER_REGISTRY = CONFIG_ROOT / "execution_adapter_profiles.json"
OCTUPOLE_RUNTIME_BINDING = (
    CONFIG_ROOT / "family_octupole_direct_mating_gap_0mm_runtime_binding.json"
)
AUTO_N1000_CONNECTOR_CAMPAIGN = (
    RETIRED_CAMPAIGNS /
    "connector_gap_three_zone_real_pa_full_n1000_campaign_v11.json"
)
COMPACT_GAP_FIELD_CAMPAIGN = (
    CONFIG_ROOT / "diagnostics" / "connector_gap_field_matrix_compact_auto_replay_v2.json"
)


def load(path: Path) -> dict[str, object]:
    return current_campaign_fixture(
        json.loads(path.read_text(encoding="utf-8-sig"))
    )


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def temporary_config_directory() -> tempfile.TemporaryDirectory[str]:
    root = CONFIG_ROOT / ".tmp"
    root.mkdir(exist_ok=True)
    return tempfile.TemporaryDirectory(dir=root)


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
        elif materialization == "independent_ion_source_volume_n5000":
            mode, role, binding = (
                "independent_spatial_velocity_ion_source_snapshot",
                "single_flight_materialized_ion_source_volume",
                "prepared_materialized_ion_source_volume",
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

    def test_automatic_deterministic_prefix_binding_uses_declared_count(self) -> None:
        population = {
            "population_mode": "first_n_rows_in_frozen_file_order",
            "source_authority": {"table_binding": "prepared_deterministic_prefix"},
            "execution_population": {
                "particle_count": 37,
                "selection_algorithm": "first_n_rows_in_frozen_file_order",
            },
        }
        self.assertEqual(
            _automatic_pulse_population_binding(population),
            ("prepared_deterministic_prefix", 37),
        )
        population["execution_population"]["selection_algorithm"] = (
            "first_100_rows_in_frozen_file_order"
        )
        with self.assertRaisesRegex(ContractError, "population differs"):
            _automatic_pulse_population_binding(population)

    def test_dispatch_plan_uses_only_repository_resource_policy_without_legacy_receipt(self) -> None:
        plan = resolve_single_flight_dispatch_plan(
            {
                "single_flight_time_integration_profile_id": "dt64",
            },
            execution_particle_count=8,
            rf_steps_per_period=64,
        )
        self.assertEqual(plan["role"], "simion_repository_dispatch_plan")
        self.assertEqual(plan["estimation"]["kind"], "formal_first_batch_observation")
        self.assertEqual(plan["limits"]["formal_observation_seconds"], 45)
        self.assertEqual(plan["limits"]["launch_stagger_seconds"], 5)
        self.assertNotIn("cpu_cores_per_batch", plan["limits"])

    def test_dispatch_plan_bootstraps_when_exploration_has_no_memory_receipt(self) -> None:
        plan = resolve_single_flight_dispatch_plan(
            {
                "single_flight_time_integration_profile_id": "dt64",
            },
            execution_particle_count=1000,
            rf_steps_per_period=64,
        )
        self.assertEqual(plan["estimation"]["kind"], "formal_first_batch_observation")
        self.assertEqual(plan["waves"][0]["batch_count"], 1)
        self.assertEqual(plan["waves"][0]["batches"][0]["count"], 100)
        self.assertTrue(plan["estimation"]["first_batch_result_retained"])

    def test_dispatch_plan_uses_discovered_profile_without_memory_receipt(self) -> None:
        profile = {
            "resource_identity": {
                "solver": "SIMION", "field_kind": "rf",
                "rf_steps_per_period": 64,
                "time_integration_profile_id": "dt64",
            },
            "per_batch_peak_working_set_bytes": 10,
        }
        with patch(
            "common.simion.resource_scheduler.available_physical_memory_bytes",
            return_value=1000,
        ), patch("common.simion.resource_scheduler.os.cpu_count", return_value=8):
            plan = resolve_single_flight_dispatch_plan(
                {"single_flight_time_integration_profile_id": "dt64"},
                execution_particle_count=8, rf_steps_per_period=64,
                resource_profiles=[profile],
            )
        self.assertEqual(plan["estimation"]["kind"], "exact_resource_profile")
        self.assertEqual(plan["waves"][0]["batch_count"], 8)

    def test_dispatch_plan_uses_resolved_inline_numerics_for_profile_match(self) -> None:
        profile = {
            "resource_identity": {
                "solver": "SIMION", "field_kind": "rf",
                "rf_steps_per_period": 64,
                "time_integration_profile_id": "dt64",
            },
            "per_batch_peak_working_set_bytes": 10,
        }
        execution_profile = {
            "frontend_cell_mm_xyz": {"x": 0.02, "y": 0.02, "z": 0.02},
            "accelerator_overlay_cell_mm_xyz": {"x": 0.02, "y": 0.02, "z": 0.005},
            "reflectron_cell_mm": {"axial": 0.02, "radial": 0.02},
            "trajectory_quality": 17,
        }
        with patch(
            "common.simion.resource_scheduler.available_physical_memory_bytes",
            return_value=1000,
        ), patch("common.simion.resource_scheduler.os.cpu_count", return_value=8):
            plan = resolve_single_flight_dispatch_plan(
                {"single_flight_time_integration_profile_id": "dt64"},
                execution_particle_count=8, rf_steps_per_period=64,
                execution_profile=execution_profile, resource_profiles=[profile],
            )
        self.assertEqual(plan["estimation"]["kind"], "formal_first_batch_observation")
        self.assertEqual(plan["waves"][0]["batch_count"], 1)
        self.assertEqual(plan["resource_identity"]["trajectory_quality"], 17)
        self.assertEqual(
            plan["resource_identity"]["frontend_cell_mm_xyz"],
            execution_profile["frontend_cell_mm_xyz"],
        )

    def test_flat_authoring_expands_shared_controls_and_gap_rows(self) -> None:
        authored = {
            "experiments": {
                "shared": {"execution_strategy": "simion_single_flight", "source_profile_id": "n100"},
                "variation_axes": ["connection_profile_id", "connector_gap_evidence_role"],
                "rows": [
                    {"sequence": 1, "experiment_id": "gap0", "run_id": "run_gap0", "overrides": {"connection_profile_id": "gap0", "connector_gap_evidence_role": "primary"}},
                    {"sequence": 2, "experiment_id": "gap3", "run_id": "run_gap3", "overrides": {"connection_profile_id": "gap3", "connector_gap_evidence_role": "primary"}},
                ],
            }
        }
        expanded = expand_flat_experiment_authoring(authored)
        self.assertEqual([row["connection_profile_id"] for row in expanded["experiments"]], ["gap0", "gap3"])
        self.assertEqual(expanded["experiments"][0]["source_profile_id"], "n100")
        self.assertEqual(authored["experiments"]["rows"][0]["overrides"], {"connection_profile_id": "gap0", "connector_gap_evidence_role": "primary"})

    def test_flat_authoring_preserves_fifty_six_gap_field_rows(self) -> None:
        """A large matrix must remain ordered and must not share mutable row state."""
        field_modes = (
            ("gap0", "full_ideal", 116),
            ("gap6p4", "partial_ideal", 482),
            ("gap12p8", "full_real", 482),
        )
        authored = {
            "experiments": {
                "shared": {
                    "execution_strategy": "simion_single_flight",
                    "source_profile_id": "post_pulse_source_zvz_theory",
                    "time_integration_profile_id": "dt40",
                },
                "variation_axes": [
                    "connection_profile_id", "field_realization",
                    "execution_particle_count",
                ],
                "rows": [
                    {
                        "sequence": sequence,
                        "experiment_id": f"gap_field_{sequence:02d}",
                        "run_id": f"matrix_run_{sequence:02d}",
                        "overrides": {
                            "connection_profile_id": mode[0],
                            "field_realization": mode[1],
                            "execution_particle_count": mode[2],
                        },
                    }
                    for sequence, mode in enumerate(
                        (field_modes[index % len(field_modes)] for index in range(56)),
                        start=1,
                    )
                ],
            }
        }

        expanded = expand_flat_experiment_authoring(authored)

        self.assertEqual(len(expanded["experiments"]), 56)
        self.assertEqual(
            [row["sequence"] for row in expanded["experiments"]], list(range(1, 57)),
        )
        self.assertEqual(
            expanded["experiments"][0]["field_realization"], "full_ideal",
        )
        self.assertEqual(
            expanded["experiments"][1]["field_realization"], "partial_ideal",
        )
        self.assertEqual(
            expanded["experiments"][2]["field_realization"], "full_real",
        )
        expanded["experiments"][0]["source_profile_id"] = "mutated"
        self.assertEqual(
            expanded["experiments"][1]["source_profile_id"],
            "post_pulse_source_zvz_theory",
        )
        self.assertEqual(
            authored["experiments"]["shared"]["source_profile_id"],
            "post_pulse_source_zvz_theory",
        )

    def test_flat_authoring_rejects_undeclared_parameter_change(self) -> None:
        with self.assertRaisesRegex(ContractError, "allowed variation axis"):
            expand_flat_experiment_authoring({"experiments": {
                "shared": {"execution_strategy": "simion_single_flight"},
                "variation_axes": ["connection_profile_id"],
                "rows": [{"sequence": 1, "experiment_id": "gap", "run_id": "run_gap", "overrides": {"source_profile_id": "other"}}],
            }})

    def test_flat_authoring_rejects_malformed_shapes_and_identity_overrides(self) -> None:
        valid = {
            "shared": {"execution_strategy": "simion_single_flight"},
            "variation_axes": ["connection_profile_id"],
            "rows": [{
                "sequence": 1, "experiment_id": "one", "run_id": "run_one",
                "overrides": {"connection_profile_id": "gap0"},
            }],
        }
        invalid = (
            {"shared": {}, "variation_axes": [], "rows": []},
            {"shared": {}, "variation_axes": ["gap", "gap"], "rows": valid["rows"]},
            {"shared": {}, "variation_axes": ["run_id"], "rows": valid["rows"]},
            {"shared": {"run_id": "forbidden"}, "variation_axes": ["gap"], "rows": valid["rows"]},
            {"shared": {}, "variation_axes": ["gap"], "rows": [{"sequence": 1, "experiment_id": "one", "run_id": "run_one", "overrides": []}]},
            {"shared": {}, "variation_axes": ["gap"], "rows": [{"sequence": 1, "experiment_id": "one", "run_id": "run_one", "overrides": {}, "extra": True}]},
            {"shared": {}, "variation_axes": ["gap"], "rows": [] , "extra": True},
        )
        for authoring in invalid:
            with self.subTest(authoring=authoring), self.assertRaises(ContractError):
                expand_flat_experiment_authoring({"experiments": authoring})

    def test_semantic_diff_reports_materialized_field_changes_without_policy_effect(self) -> None:
        before = {
            "experiment_id": "before",
            "run_id": "run-before",
            "connection_profile_id": "gap0",
            "single_flight_population": {"particle_count": 100},
            "source": {"sha256": "A" * 64},
        }
        after = {
            "experiment_id": "after",
            "run_id": "run-after",
            "connection_profile_id": "gap3",
            "single_flight_population": {"particle_count": 1000},
            "source": {"sha256": "B" * 64},
        }
        diff = semantic_diff_experiments(before, after)
        self.assertEqual(diff["classification_scope"], "review_only_not_execution_policy")
        self.assertEqual(diff["changed_field_count"], 5)
        categories = {item["path"]: item["category"] for item in diff["changes"]}
        self.assertEqual(categories["connection_profile_id"], "physical_design_or_field")
        self.assertEqual(categories["single_flight_population.particle_count"], "source_cohort_or_sampling")
        self.assertEqual(categories["source.sha256"], "evidence_or_provenance")

    def test_flat_cli_lists_sorted_ids_and_prints_the_materialized_row(self) -> None:
        campaign = load(CAMPAIGN_PATH)
        rows = campaign["experiments"]
        shared = {
            key: rows[0][key] for key in rows[0]
            if all(key in row and row[key] == rows[0][key] for row in rows)
            and key not in {"sequence", "experiment_id", "run_id"}
        }
        axes = sorted(
            set().union(*(row.keys() for row in rows)) - set(shared)
            - {"sequence", "experiment_id", "run_id"}
        )
        compact_rows = [
            {
                "sequence": row["sequence"], "experiment_id": row["experiment_id"],
                "run_id": row["run_id"],
                "overrides": {key: row[key] for key in axes if key in row},
            }
            for row in reversed(rows)
        ]
        campaign["experiments"] = {
            "shared": shared, "variation_axes": axes, "rows": compact_rows,
        }
        expected = expand_flat_experiment_authoring(campaign)
        module = (
            "integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer."
            "workflows.family_source_closure.prepare"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "flat_campaign.json"
            path.write_text(json.dumps(campaign, indent=2) + "\n", encoding="utf-8")
            common = [
                sys.executable, "-m", module, "--repo-root", str(REPO_ROOT),
                "--profile-registry", str(PROFILE_REGISTRY), "--adapter-registry", str(ADAPTER_REGISTRY),
                "--campaign", str(path),
            ]
            listed = subprocess.run(
                [*common, "--list-experiment-ids"], capture_output=True, text=True,
                encoding="utf-8", errors="replace", check=False, timeout=30, cwd=REPO_ROOT,
            )
            self.assertEqual(listed.returncode, 0, listed.stderr)
            self.assertEqual(
                listed.stdout.splitlines(),
                [row["experiment_id"] for row in sorted(expected["experiments"], key=lambda row: row["sequence"])],
            )
            selected = expected["experiments"][0]
            printed = subprocess.run(
                [*common, "--print-experiment-json", selected["experiment_id"]],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                check=False, timeout=30, cwd=REPO_ROOT,
            )
            self.assertEqual(printed.returncode, 0, printed.stderr)
            self.assertEqual(json.loads(printed.stdout), selected)
            compared = expected["experiments"][1]
            semantic_diff = subprocess.run(
                [
                    *common,
                    "--semantic-diff-experiment-json",
                    selected["experiment_id"],
                    compared["experiment_id"],
                ],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                check=False, timeout=30, cwd=REPO_ROOT,
            )
            self.assertEqual(semantic_diff.returncode, 0, semantic_diff.stderr)
            self.assertEqual(
                json.loads(semantic_diff.stdout),
                semantic_diff_experiments(selected, compared),
            )
            missing = subprocess.run(
                [*common, "--print-experiment-json", "missing"], capture_output=True,
                text=True, encoding="utf-8", errors="replace", check=False, timeout=30,
                cwd=REPO_ROOT,
            )
            self.assertNotEqual(missing.returncode, 0)
            self.assertIn("must resolve exactly one experiment", missing.stderr)

    def test_public_entrypoint_exposes_read_only_semantic_diff(self) -> None:
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("PowerShell 7 is unavailable")
        campaign = expand_flat_experiment_authoring(load(COMPACT_GAP_FIELD_CAMPAIGN))
        before, after = campaign["experiments"][:2]
        command = [
            pwsh,
            "-NoProfile",
            "-File",
            str(INTEGRATION_ROOT / "workflows" / "family_source_closure" / "execute.ps1"),
            "-Campaign",
            str(COMPACT_GAP_FIELD_CAMPAIGN),
            "-ExperimentId",
            before["experiment_id"],
            "-SemanticDiffAgainst",
            after["experiment_id"],
        ]
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(
            json.loads(completed.stdout), semantic_diff_experiments(before, after)
        )
        incompatible = subprocess.run(
            [*command, "-ValidateOnly"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
        self.assertNotEqual(incompatible.returncode, 0)
        self.assertIn("cannot be combined", incompatible.stderr)

    def test_resource_policy_falls_back_to_one_lane_when_memory_is_tight(self) -> None:
        policy = {
            "single_flight_time_integration_profile_id": "dt40",
        }
        profile = {
            "resource_identity": {
                "solver": "SIMION", "field_kind": "rf",
                "rf_steps_per_period": 40,
                "time_integration_profile_id": "dt40",
            },
            "per_batch_peak_working_set_bytes": 12 * 1024**3,
        }
        with patch(
            "common.simion.resource_scheduler.physical_memory_bytes",
            return_value=(15 * 1024**3, 16 * 1024**3),
        ):
            self.assertEqual(
                resolve_single_flight_dispatch_plan(
                    policy, execution_particle_count=5000, rf_steps_per_period=40,
                    resource_profiles=[profile],
                )["limits"]["maximum_concurrency"],
                1,
            )
        with patch(
            "common.simion.resource_scheduler.physical_memory_bytes",
            return_value=(12 * 1024**3, 16 * 1024**3),
        ):
            constrained = resolve_single_flight_dispatch_plan(
                policy, execution_particle_count=5000, rf_steps_per_period=40,
                resource_profiles=[profile],
            )
        self.assertEqual(constrained["limits"]["maximum_concurrency"], 1)
        # Memory determines concurrent lanes. With one allowed lane, all
        # independent particles belong to its one complete work batch.
        self.assertEqual(constrained["waves"][0]["batch_count"], 1)
        self.assertEqual(constrained["waves"][0]["batches"][0]["count"], 5_000)

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

    def test_generated_ordered_subset_semantics_are_registry_resolved(
        self,
    ) -> None:
        path = (
            RETIRED_CAMPAIGNS
            / "canonical_long_full_domain_restart_affine_width_numerics_n1000_v3_successor_campaign.json"
        )
        external = load(path)
        validate_schema(
            external, ARCHIVAL_CAMPAIGN_SCHEMA
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
            campaign, ARCHIVAL_CAMPAIGN_SCHEMA
        )
        profile = {
            "materialization_mode": "resolved_layout_pulse_ideal_linear_z_vz",
            "particle_count": 1000,
        }
        self.assertEqual(
            resolve_generated_pre_pulse_ordered_subset(row, profile),
            list(range(1, 101)),
        )
        full_width = json.loads(json.dumps(campaign))
        full_width["experiments"][2]["generated_pre_pulse_ordered_subset"] = {
            "selection_id": "n100_uniform_full_width_source_ids_1_to_1000_v1"
        }
        validate_schema(
            full_width, ARCHIVAL_CAMPAIGN_SCHEMA
        )
        self.assertEqual(
            len(resolve_generated_pre_pulse_ordered_subset(
                full_width["experiments"][2], profile
            )),
            100,
        )

        arbitrary_n = json.loads(json.dumps(campaign))
        arbitrary_row = arbitrary_n["experiments"][2]
        arbitrary_row["generated_pre_pulse_ordered_subset"] = {
            "selector": {
                "algorithm": "first_n_source_ids_in_frozen_file_order_v1",
                "particle_count": 37,
            }
        }
        arbitrary_population = arbitrary_row["single_flight_population"]
        arbitrary_population["execution_population"]["particle_count"] = 37
        arbitrary_population["execution_population"]["ordered_particle_id_sha256"] = (
            hashlib.sha256(json.dumps(list(range(1, 38)), separators=(",", ":")).encode()).hexdigest().upper()
        )
        arbitrary_population["denominators"] = {
            "population_count": 37, "eligible_population_count": 37,
        }
        validate_schema(arbitrary_n, ARCHIVAL_CAMPAIGN_SCHEMA)
        self.assertEqual(
            resolve_generated_pre_pulse_ordered_subset(arbitrary_row, profile),
            list(range(1, 38)),
        )
        large_n = json.loads(json.dumps(arbitrary_n))
        large_row = large_n["experiments"][2]
        large_count = 10001
        large_row["generated_pre_pulse_ordered_subset"]["selector"][
            "particle_count"
        ] = large_count
        large_population = large_row["single_flight_population"]
        large_population["execution_population"]["particle_count"] = large_count
        large_population["execution_population"]["ordered_particle_id_sha256"] = (
            hashlib.sha256(
                json.dumps(list(range(1, large_count + 1)), separators=(",", ":")).encode()
            ).hexdigest().upper()
        )
        large_population["denominators"] = {
            "population_count": large_count,
            "eligible_population_count": large_count,
        }
        validate_schema(large_n, ARCHIVAL_CAMPAIGN_SCHEMA)
        insufficient_mother = {**profile, "particle_count": 36}
        with self.assertRaisesRegex(ContractError, "exceeds mother"):
            resolve_generated_pre_pulse_ordered_subset(
                arbitrary_row, insufficient_mother
            )

        conflicting = json.loads(json.dumps(campaign))
        conflicting["experiments"][2]["pre_pulse_source_state"] = external[
            "experiments"
        ][2]["pre_pulse_source_state"]
        with self.assertRaises(ContractError):
            validate_schema(
                conflicting,
                ARCHIVAL_CAMPAIGN_SCHEMA,
            )

        wrong_count = json.loads(json.dumps(campaign))
        wrong_count["experiments"][2]["single_flight_population"][
            "execution_population"
        ]["particle_count"] = 1
        validate_schema(wrong_count, ARCHIVAL_CAMPAIGN_SCHEMA)
        with self.assertRaisesRegex(ContractError, "population identity"):
            resolve_generated_pre_pulse_ordered_subset(
                wrong_count["experiments"][2], profile
            )

        unknown_selection = json.loads(json.dumps(campaign))
        unknown_selection["experiments"][2]["generated_pre_pulse_ordered_subset"] = {
            "selection_id": "unregistered_selection_v1"
        }
        validate_schema(unknown_selection, ARCHIVAL_CAMPAIGN_SCHEMA)
        with self.assertRaisesRegex(ContractError, "selection is invalid"):
            resolve_generated_pre_pulse_ordered_subset(
                unknown_selection["experiments"][2], profile
            )

    def test_three_zone_candidate_binding_is_layout_method_scoped_and_hash_bound(self) -> None:
        campaign = load(
            RETIRED_CAMPAIGNS
            / "short_focus_rr_tqual108_stratified_n100_campaign.json"
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
            campaign, ARCHIVAL_CAMPAIGN_SCHEMA
        )

        t5_layout = {"method": "t5_frozen_three_zone_candidate_v1"}
        self.assertEqual(validate_three_zone_candidate_binding(row, t5_layout), row[
            "single_flight_three_zone_candidate"
        ])
        missing = json.loads(json.dumps(row))
        del missing["single_flight_three_zone_candidate"]
        with self.assertRaisesRegex(ContractError, "requires a Candidate"):
            validate_three_zone_candidate_binding(missing, t5_layout)
        with self.assertRaisesRegex(ContractError, "requires a three-zone T5"):
            validate_three_zone_candidate_binding(row, {"method": "other"})

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
                candidate.resolve(),
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

    def test_three_zone_field_profiles_publish_complete_selectable_identities(self) -> None:
        configuration = load(CONFIG_ROOT / "simion_single_flight.json")
        profiles = {
            item["profile_id"]: item
            for item in configuration["accelerator_field_profiles"]
        }
        three_zone_profiles = [
            profile
            for profile in profiles.values()
            if isinstance(profile.get("topology_id"), str)
        ]
        self.assertTrue(three_zone_profiles)
        for profile in three_zone_profiles:
            with self.subTest(profile_id=profile["profile_id"]):
                self.assertTrue(all(
                    isinstance(profile.get(key), str) and profile[key]
                    for key in (
                        "topology_id",
                        "geometry_id",
                        "frontend_electrode_topology_id",
                        "field_id",
                    )
                )
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
                _repo_byte_record(root, record, "loader receipt"), receipt.resolve()
            )
            receipt.write_bytes(crlf.replace(b"\r\n", b"\n"))
            with self.assertRaisesRegex(ContractError, "missing, stale"):
                _repo_byte_record(root, record, "loader receipt")

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

    def test_solver_failure_preserves_unpublished_pulse_evidence(self) -> None:
        entry = (
            INTEGRATION_ROOT / "workflows" / "family_source_closure" / "execute.ps1"
        )
        source = entry.read_text(encoding="utf-8")
        self.assertIn("Preserve that negative result for audit and", source)
        self.assertNotIn(
            "Remove-Item -LiteralPath $unpublishedDiscoveryRoot", source
        )
        self.assertIn(
            "if ($cleanupOutput -and (Test-Path -LiteralPath $outputRoot))",
            source,
        )

    def test_terminal_interruption_can_create_a_distinct_recovery_identity(self) -> None:
        """An external stop is terminal evidence, not an immutable retry dead end."""
        execute = (
            INTEGRATION_ROOT / "workflows" / "family_source_closure" / "execute.ps1"
        ).read_text(encoding="utf-8")
        adapter = (
            INTEGRATION_ROOT / "workflows" / "family_source_closure" / "adapter.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn("$publishedManifest.status -in @('failed','interrupted')", execute)
        self.assertIn("function Resolve-RfRecoveryFailureAncestor", adapter)

    def test_recovery_chain_skips_partial_suffix_only_for_same_campaign_failure(
        self,
    ) -> None:
        """A partial unpublished suffix may not hide the last terminal retry result."""
        adapter = (
            INTEGRATION_ROOT / "workflows" / "family_source_closure" / "adapter.ps1"
        )
        with tempfile.TemporaryDirectory() as directory:
            script = r"""
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
  $env:RF_ADAPTER_PATH, [ref]$null, [ref]$parseErrors
)
if ($parseErrors) { throw $parseErrors[0] }
$functionAst = $ast.Find({
  param($node)
  $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
  $node.Name -eq 'Resolve-RfRecoveryFailureAncestor'
}, $true)
if ($null -eq $functionAst) { throw 'missing recovery ancestor resolver' }
. ([scriptblock]::Create($functionAst.Extent.Text))

function Write-RecoveryEvidence {
  param([string]$RunId, [string]$Status, [string]$CampaignId)
  $dir = Join-Path $env:RF_RECOVERY_ROOT $RunId
  New-Item -ItemType Directory -Path $dir -Force | Out-Null
  @{ run_id = $RunId; status = $Status } |
    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $dir 'run_manifest.json')
  @{ campaign_id = $CampaignId } |
    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $dir 'run_config.json')
}

$expected = '20260826_160000__sim__cross__case__n100'
$requested = $expected + '__r03'
$partial = Join-Path $env:RF_RECOVERY_ROOT ($expected + '__r02')
New-Item -ItemType Directory -Path $partial -Force | Out-Null

Write-RecoveryEvidence -RunId ($expected + '__r01') -Status 'failed' -CampaignId 'campaign_a'
$accepted = Resolve-RfRecoveryFailureAncestor -RequestedRunId $requested `
  -ExpectedRunId $expected -RunsRoot $env:RF_RECOVERY_ROOT -CampaignId 'campaign_a'
if ($null -eq $accepted -or $accepted.run_id -ne ($expected + '__r01') -or $accepted.status -ne 'failed') {
  throw 'partial suffix did not recover prior same-campaign failure'
}

Write-RecoveryEvidence -RunId ($expected + '__r01') -Status 'failed' -CampaignId 'campaign_b'
if ($null -ne (Resolve-RfRecoveryFailureAncestor -RequestedRunId $requested `
    -ExpectedRunId $expected -RunsRoot $env:RF_RECOVERY_ROOT -CampaignId 'campaign_a')) {
  throw 'wrong campaign was accepted'
}

Write-RecoveryEvidence -RunId ($expected + '__r01') -Status 'success' -CampaignId 'campaign_a'
if ($null -ne (Resolve-RfRecoveryFailureAncestor -RequestedRunId $requested `
    -ExpectedRunId $expected -RunsRoot $env:RF_RECOVERY_ROOT -CampaignId 'campaign_a')) {
  throw 'successful ancestor was accepted'
}

Write-RecoveryEvidence -RunId ($expected + '__r01') -Status 'created' -CampaignId 'campaign_a'
if ($null -ne (Resolve-RfRecoveryFailureAncestor -RequestedRunId $requested `
    -ExpectedRunId $expected -RunsRoot $env:RF_RECOVERY_ROOT -CampaignId 'campaign_a')) {
  throw 'nonterminal ancestor was accepted'
}

$sameCampaignPartial = Join-Path $env:RF_RECOVERY_ROOT ($expected + '__r02')
New-Item -ItemType Directory -Path (Join-Path $sameCampaignPartial 'inputs') -Force | Out-Null
@{ campaign = @{ campaign_id = 'campaign_a' }; experiment = @{ run_id = $expected } } |
  ConvertTo-Json | Set-Content -LiteralPath (Join-Path $sameCampaignPartial 'inputs\frozen_campaign_experiment.json')
$accepted = Resolve-RfRecoveryFailureAncestor -RequestedRunId $requested `
  -ExpectedRunId $expected -RunsRoot $env:RF_RECOVERY_ROOT -CampaignId 'campaign_a'
if ($null -eq $accepted -or $accepted.run_id -ne ($expected + '__r02') -or
    $accepted.status -ne 'unpublished') {
  throw 'same-campaign unpublished suffix was not accepted'
}
Write-Output 'RECOVERY_CHAIN=PASS'
"""
            environment = os.environ.copy()
            environment.update({
                "RF_ADAPTER_PATH": str(adapter),
                "RF_RECOVERY_ROOT": directory,
            })
            completed = subprocess.run(
                ["pwsh", "-NoProfile", "-Command", script],
                cwd=REPO_ROOT,
                env=environment,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                check=False,
                timeout=300,
            )
            self.assertEqual(
                completed.returncode, 0, completed.stdout + completed.stderr
            )
            self.assertIn("RECOVERY_CHAIN=PASS", completed.stdout)

    def test_archived_campaign_is_rejected_before_schema_or_prepare(self) -> None:
        campaign = SINGLE_FLIGHT_CAMPAIGN_PATH
        execute = INTEGRATION_ROOT / "workflows" / "family_source_closure" / (
            "execute.ps1"
        )
        completed = subprocess.run(
            [
                "pwsh", "-NoProfile", "-File", str(execute),
                "-Campaign", str(campaign.relative_to(REPO_ROOT)),
                "-ExperimentId", "octupole_segmented_aperture100_simion_single_flight",
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

    def test_active_schema_is_v6_only_while_archive_reader_preserves_v1(self) -> None:
        active = expand_flat_experiment_authoring(load(COMPACT_GAP_FIELD_CAMPAIGN))
        archived = load(CAMPAIGN_PATH)
        validate_schema(active, ACTIVE_CAMPAIGN_SCHEMA)
        validate_schema(archived, ARCHIVAL_CAMPAIGN_SCHEMA)
        with self.assertRaises(ContractError):
            validate_schema(archived, ACTIVE_CAMPAIGN_SCHEMA)

    def test_active_v6_single_flight_requires_pa_cache_policy(self) -> None:
        active = expand_flat_experiment_authoring(load(COMPACT_GAP_FIELD_CAMPAIGN))
        del active["experiments"][0]["single_flight_pa_cache_policy"]
        with self.assertRaises(ContractError):
            validate_schema(active, ACTIVE_CAMPAIGN_SCHEMA)

    def test_active_v6_rejects_retired_fixed_batch_controls(self) -> None:
        active = expand_flat_experiment_authoring(load(COMPACT_GAP_FIELD_CAMPAIGN))
        for path in (
            ("single_flight_batch_count",),
            ("single_flight_batch_memory_policy",),
        ):
            with self.subTest(path=path):
                candidate = json.loads(json.dumps(active))
                target = candidate["experiments"][0]
                target[path[-1]] = 2 if path[-1] == "single_flight_batch_count" else {
                    "reserve_available_memory_bytes": 1
                }
                with self.assertRaises(ContractError):
                    validate_schema(candidate, ACTIVE_CAMPAIGN_SCHEMA)

    def test_registry_is_the_only_active_campaign_authority(self) -> None:
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
        registry = load(CONFIG_ROOT / "diagnostics" / "lifecycle_registry.json")
        registered = {
            (REPO_ROOT / row["path"]).resolve()
            for row in registry["active_campaigns"]
        }
        self.assertTrue(registered)
        self.assertTrue(registered.issubset({path.resolve() for path, _ in authorized}))
        self.assertEqual(
            {path.name for path in registered},
            {"connector_gap_field_matrix_compact_auto_replay_v2.json"},
        )

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
        self.assertIn("$runnerArguments.ResolvedRegionFieldContract =", adapter)
        runner_arguments_init = adapter.index("$runnerArguments = @{")
        axis_export_flags = adapter.index("$runnerArguments.BuildOnly = $true")
        self.assertLess(
            runner_arguments_init,
            axis_export_flags,
            "axis-field export must not write the runner request before it exists",
        )
        self.assertNotIn(
            "$frozenArguments.single_flight_accelerator_field_profile_id",
            adapter,
        )
        validate_exit = common_execute.index("if ($ValidateOnly)")
        adapter_call = common_execute.index("& $AdapterEntrypoint @adapterArguments")
        self.assertLess(validate_exit, adapter_call)
        self.assertIn("exit 0", common_execute[validate_exit:adapter_call])

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
        validate_schema(campaign, ARCHIVAL_CAMPAIGN_SCHEMA)
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
        self.assertNotIn("max_parallel_batches", selected_grid)
        self.assertNotIn("batching_policy", configuration)

    def test_n1000_v3_changes_only_identity_and_execution_batching(self) -> None:
        v2 = load(
            RETIRED_CAMPAIGNS /
            "connector_gap_three_zone_real_pa_full_n1000_campaign_v2.json"
        )
        v3 = load(AUTO_N1000_CONNECTOR_CAMPAIGN)
        use_current_time_grid_profile(v2)
        use_current_time_grid_profile(v3)
        validate_schema(v3, ARCHIVAL_CAMPAIGN_SCHEMA)
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

    def test_three_zone_region_mode_authority_comes_from_field_profile(self) -> None:
        explicit_profile = "three_zone_explicit_region_modes"
        selected_modes = {
            "accelerator_zone1": "analytic_ideal_field",
            "accelerator_zone2": "real_pa_field",
            "accelerator_zone3": "zero_field",
            "drift": "real_pa_field",
            "reflectron_stage1": "analytic_ideal_field",
            "reflectron_stage2": "real_pa_field",
        }
        with self.assertRaisesRegex(ContractError, "requires all region modes"):
            _resolve_single_flight_profiles(
                REPO_ROOT,
                {"single_flight_accelerator_field_profile_id": explicit_profile},
                "simion_single_flight",
            )
        resolved = _resolve_single_flight_profiles(
            REPO_ROOT,
            {
                "single_flight_accelerator_field_profile_id": explicit_profile,
                "single_flight_three_zone_region_modes": selected_modes,
            },
            "simion_single_flight",
        )
        self.assertEqual(resolved.three_zone_region_modes, selected_modes)
        with self.assertRaisesRegex(ContractError, "require their explicit field profile"):
            _resolve_single_flight_profiles(
                REPO_ROOT,
                {
                    "single_flight_accelerator_field_profile_id": (
                        "accelerator_ideal_three_zone_real_reflectron"
                    ),
                    "single_flight_three_zone_region_modes": selected_modes,
                },
                "simion_single_flight",
            )

    def test_single_flight_profile_resolution_remains_the_numerical_authority(self) -> None:
        for field in (
            "single_flight_trajectory_quality_profile_id",
            "single_flight_spatial_window_profile_id",
        ):
            with self.subTest(field=field), self.assertRaisesRegex(
                ContractError, "single-flight numerical configuration is invalid"
            ):
                _resolve_single_flight_profiles(
                    REPO_ROOT,
                    {field: "unknown_profile"},
                    "simion_single_flight",
                )
        with self.assertRaisesRegex(
            ContractError, "trajectory-quality profile must resolve exactly once"
        ):
            _resolve_single_flight_profiles(
                REPO_ROOT,
                {"single_flight_trajectory_quality_profile_id": "unknown_profile"},
                "staged_three_stage",
            )

    def test_ideal_accelerator_field_is_a_registered_counterfactual(self) -> None:
        campaign = load(IDEAL_FIELD_CAMPAIGN_PATH)
        validate_schema(
            campaign, ARCHIVAL_CAMPAIGN_SCHEMA
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
            campaign, ARCHIVAL_CAMPAIGN_SCHEMA
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
            campaign, ARCHIVAL_CAMPAIGN_SCHEMA
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

    def test_single_flight_design_overrides_are_optional_contract_data(self) -> None:
        default_campaign = load(SINGLE_FLIGHT_CAMPAIGN_PATH)
        self.assertNotIn(
            "single_flight_design_overrides", default_campaign["experiments"][0]
        )
        candidate = load(Z_ACCEPTANCE_CAMPAIGN_PATH)
        validate_schema(
            candidate, ARCHIVAL_CAMPAIGN_SCHEMA
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
        validate_schema(campaign, ARCHIVAL_CAMPAIGN_SCHEMA)
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
            validate_schema(
                binding, SCHEMA_ROOT / "rf_multipole_oatof_runtime_binding.schema.json"
            )
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
        validate_schema(campaign, ARCHIVAL_CAMPAIGN_SCHEMA)
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

    def test_prepare_rejects_unregistered_campaign_before_reading_artifacts(self) -> None:
        """The Python preparation entrypoint has the same default-deny boundary.

        `execute.ps1` already guards its public route.  This regression covers
        direct module/CLI use, where no source manifest or solver input may be
        read before lifecycle authorization is established.
        """
        campaign = load(COMPACT_GAP_FIELD_CAMPAIGN)
        row = expand_flat_experiment_authoring(campaign)["experiments"][0]
        with temporary_config_directory() as directory:
            root = Path(directory)
            campaign_path = root / "unregistered_campaign.json"
            campaign_path.write_text("{ not valid JSON", encoding="utf-8")
            with self.assertRaisesRegex(
                ContractError, "not an active lifecycle authority",
            ):
                prepare_family_source_closure(
                    repo_root=REPO_ROOT,
                    profile_registry_path=PROFILE_REGISTRY,
                    adapter_registry_path=ADAPTER_REGISTRY,
                    campaign_path=campaign_path,
                    experiment_id=row["experiment_id"],
                    resolved_output=root / "resolved.json",
                    plan_output=root / "plan.json",
                )

    def test_exploration_preparation_freezes_inputs_accepted_by_runtime_resolver(
        self,
    ) -> None:
        campaign = load(COMPACT_GAP_FIELD_CAMPAIGN)
        campaign["status"] = "exploration"
        campaign["experiments"]["shared"]["single_flight_numerical_overrides"] = {
            "trajectory_quality": 17,
            "rf_steps_per_period": 73,
        }
        row = expand_flat_experiment_authoring(campaign)["experiments"][0]
        with temporary_config_directory() as directory:
            root = Path(directory)
            artifact_root = REPO_ROOT.parent / "artifacts" / "projects" / INTEGRATION_ID
            artifact_root.mkdir(parents=True, exist_ok=True)
            campaign_path = root / "exploration_campaign.json"
            write_json(campaign_path, campaign)
            with tempfile.TemporaryDirectory(dir=artifact_root) as output_directory:
                output = Path(output_directory)
                resolved, plan = prepare_family_source_closure(
                    repo_root=REPO_ROOT,
                    profile_registry_path=PROFILE_REGISTRY,
                    adapter_registry_path=ADAPTER_REGISTRY,
                    campaign_path=campaign_path,
                    experiment_id=row["experiment_id"],
                    resolved_output=output / "resolved.json",
                    plan_output=output / "plan.json",
                    exploration=True,
                )
                self.assertTrue(resolved.is_file())
                self.assertTrue(plan.is_file())
                execution_profile = load(
                    output / "inputs" / "resolved_single_flight_execution_profile.json"
                )
                self.assertEqual(execution_profile["trajectory_quality"], 17)
                self.assertEqual(execution_profile["rf_steps_per_period"], 73)
                arguments = load(plan)["execution_steps"][0]["arguments"]
                self.assertIn(
                    "adapter_sha256="
                    + hashlib.sha256(
                        (INTEGRATION_ROOT / "workflows" / "family_source_closure" / "adapter.ps1")
                        .read_bytes()
                    ).hexdigest().upper(),
                    arguments,
                )
                self.assertFalse(any(
                    item.startswith("adapter_registry_sha256=") for item in arguments
                ))
                self.assertIn(
                    "resolved_single_flight_execution_profile_filename="
                    "inputs/resolved_single_flight_execution_profile.json",
                    arguments,
                )
                frozen = dict(argument.split("=", 1) for argument in arguments)
                frozen_authoring = load(
                    output / frozen["frozen_campaign_experiment_filename"]
                )
                self.assertEqual(
                    frozen_authoring["role"], "rf_oatof_frozen_campaign_experiment"
                )
                self.assertEqual(
                    frozen_authoring["campaign"]["campaign_id"],
                    campaign["campaign_id"],
                )
                self.assertEqual(
                    frozen_authoring["experiment"], row,
                )
                self.assertEqual(
                    hashlib.sha256(
                        (output / frozen["frozen_campaign_experiment_filename"])
                        .read_bytes()
                    ).hexdigest().upper(),
                    frozen["frozen_campaign_experiment_sha256"],
                )
                execution_plan = load(output / frozen["resolved_execution_plan_filename"])
                self.assertEqual(execution_plan["role"], "rf_oatof_resolved_execution_plan")
                self.assertEqual(execution_plan["experiment_id"], row["experiment_id"])
                self.assertEqual(
                    execution_plan["arguments"],
                    {
                        key: value for key, value in frozen.items()
                        if key not in {
                            "resolved_execution_plan_filename",
                            "resolved_execution_plan_sha256",
                        }
                    },
                )
                self.assertEqual(
                    hashlib.sha256(
                        (output / frozen["resolved_execution_plan_filename"]).read_bytes()
                    ).hexdigest().upper(),
                    frozen["resolved_execution_plan_sha256"],
                )
                runtime_binding = REPO_ROOT / frozen["runtime_binding_path"]
                resolved_source = output / frozen[
                    "resolved_source_contract_filename"
                ]
                upstream_design = output / frozen[
                    "upstream_resolved_design_filename"
                ]
                runtime_support = INTEGRATION_ROOT / "runtime" / "run_artifacts.ps1"
                runtime_resolver = INTEGRATION_ROOT / "runtime" / "runtime_binding.ps1"
                script = f"""
$OutputEncoding = [Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
. '{runtime_support}'
. '{runtime_resolver}'
$runtime = Resolve-RfOatofRuntimeBinding `
  -RepoRoot '{REPO_ROOT}' `
  -ResolvedConnection '{resolved}' `
  -RuntimeBinding '{runtime_binding}' `
  -ExpectedConnectionProfileId '{load(resolved)["selection"]["connection_profile_id"]}' `
  -SourceBranchId '{frozen["source_branch_id"]}' `
  -ResolvedSourceContract '{resolved_source}' `
  -ResolvedSourceContractSha256 '{frozen["resolved_source_contract_sha256"]}' `
  -UpstreamResolvedDesign '{upstream_design}' `
  -UpstreamResolvedDesignSha256 '{frozen["upstream_resolved_design_sha256"]}'
if ($runtime.binding.schema_version -ne 4) {{ throw 'runtime binding schema differs' }}
if ($runtime.contracts.resolved_source_contract -ne '{resolved_source}') {{
  throw 'runtime resolver did not preserve the frozen source contract'
}}
'EXPLORATION_RUNTIME_RESOLUTION=PASS'
"""
                result = subprocess.run(
                    ["pwsh", "-NoProfile", "-Command", script],
                    cwd=REPO_ROOT,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=90,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("EXPLORATION_RUNTIME_RESOLUTION=PASS", result.stdout)
                campaign_path.write_text("{\"superseded\": true}\n", encoding="utf-8")
                adapter = INTEGRATION_ROOT / "workflows" / "family_source_closure" / "adapter.ps1"
                prepared = subprocess.run(
                    [
                        "pwsh", "-NoProfile", "-ExecutionPolicy", "Bypass",
                        "-File", str(adapter),
                        "-CompositionPlan", str(plan),
                        "-ResolvedConnection", str(resolved),
                        "-PythonExe", sys.executable,
                        "-RepoRoot", str(REPO_ROOT),
                        "-PrepareOnly",
                    ],
                    cwd=REPO_ROOT,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=90,
                )
                self.assertEqual(
                    prepared.returncode, 0, prepared.stdout + prepared.stderr
                )
                self.assertIn("FAMILY_SOURCE_CLOSURE_ADAPTER=PREPARED", prepared.stdout)

    def test_exploration_preparation_requires_explicit_status(self) -> None:
        campaign = load(COMPACT_GAP_FIELD_CAMPAIGN)
        row = expand_flat_experiment_authoring(campaign)["experiments"][0]
        with temporary_config_directory() as directory:
            root = Path(directory)
            campaign_path = root / "unregistered_authorized_campaign.json"
            write_json(campaign_path, campaign)
            with self.assertRaisesRegex(
                ContractError, "requires campaign.status=exploration",
            ):
                prepare_family_source_closure(
                    repo_root=REPO_ROOT,
                    profile_registry_path=PROFILE_REGISTRY,
                    adapter_registry_path=ADAPTER_REGISTRY,
                    campaign_path=campaign_path,
                    experiment_id=row["experiment_id"],
                    resolved_output=root / "resolved.json",
                    plan_output=root / "plan.json",
                    exploration=True,
                )

    def test_exploration_post_pulse_restart_does_not_require_theory_working_point(
        self,
    ) -> None:
        campaign = load(COMPACT_GAP_FIELD_CAMPAIGN)
        campaign["status"] = "exploration"
        campaign["experiments"]["variation_axes"].remove(
            "single_flight_source_zvz_theory_working_point"
        )
        for row in campaign["experiments"]["rows"]:
            overrides = row["overrides"]
            overrides.pop("single_flight_source_zvz_theory_working_point")
            overrides["post_pulse_restart_reuse_authority"][
                "post_pulse_variation_axis"
            ] = "accelerator_field_profile_id"
        experiment_id = campaign["experiments"]["rows"][0]["experiment_id"]
        with temporary_config_directory() as directory:
            root = Path(directory)
            artifact_root = REPO_ROOT.parent / "artifacts" / "projects" / INTEGRATION_ID
            artifact_root.mkdir(parents=True, exist_ok=True)
            campaign_path = root / "exploration_post_pulse_restart.json"
            write_json(campaign_path, campaign)
            with tempfile.TemporaryDirectory(dir=artifact_root) as output_directory:
                resolved, plan = prepare_family_source_closure(
                    repo_root=REPO_ROOT,
                    profile_registry_path=PROFILE_REGISTRY,
                    adapter_registry_path=ADAPTER_REGISTRY,
                    campaign_path=campaign_path,
                    experiment_id=experiment_id,
                    resolved_output=Path(output_directory) / "resolved.json",
                    plan_output=Path(output_directory) / "plan.json",
                    exploration=True,
                )
                self.assertTrue(resolved.is_file())
                self.assertTrue(plan.is_file())

    def test_public_exploration_validate_only_accepts_unregistered_campaign(self) -> None:
        campaign = load(COMPACT_GAP_FIELD_CAMPAIGN)
        campaign["status"] = "exploration"
        experiment_id = campaign["experiments"]["rows"][0]["experiment_id"]
        with temporary_config_directory() as directory:
            campaign_path = Path(directory) / "exploration_campaign.json"
            write_json(campaign_path, campaign)
            result = subprocess.run(
                [
                    "pwsh", "-NoProfile", "-File", str(
                        INTEGRATION_ROOT / "workflows" / "family_source_closure" / "execute.ps1"
                    ),
                    "-Campaign", str(campaign_path.relative_to(REPO_ROOT)),
                    "-ExperimentId", experiment_id,
                    "-ValidateOnly", "-Exploration",
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("INTEGRATION_EXECUTION=VALIDATED", result.stdout)

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

    def test_pre_pulse_selection_requires_explicit_frozen_selection_order(self) -> None:
        smoke = {"pre_pulse_time_series_screening": {"mode": "screen"}}
        self.assertFalse(
            _selection_is_explicitly_authorized(
                smoke, pulse_timing_internal_stage=None
            )
        )
        selected = {
            "pre_pulse_time_series_screening": {
                "mode": "screen", "selection_order": ["alive_count"]
            }
        }
        self.assertTrue(
            _selection_is_explicitly_authorized(
                selected, pulse_timing_internal_stage=None
            )
        )
        self.assertTrue(
            _selection_is_explicitly_authorized(
                smoke, pulse_timing_internal_stage="pulse_timing_discovery"
            )
        )


if __name__ == "__main__":
    unittest.main()

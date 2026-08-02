"""Static contracts for no-acceleration family direct-mating profiles."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from common.contracts.machine_contracts import ContractError, validate_schema
from common.contracts.file_identity import file_sha256, repository_text_sha256
from common.integration.resolve_connection import (
    load_connection_profile_registry,
    resolve_connection_profile,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.refresh_family_repository_bindings import (
    publication_differences,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
WORKSPACE_ROOT = REPO_ROOT.parent
INTEGRATION_ROOT = Path(__file__).resolve().parents[1]
PROFILE_REGISTRY_PATH = INTEGRATION_ROOT / "config" / "connection_profiles.json"
ADAPTER_REGISTRY_PATH = (
    INTEGRATION_ROOT / "config" / "execution_adapter_profiles.json"
)
BUDGET_PATH = (
    INTEGRATION_ROOT / "config" / "family_source_closure_budget.json"
)
PREREGISTRATION_PATH = (
    INTEGRATION_ROOT
    / "config"
    / "family_source_closure_preregistration.json"
)
FAMILY_PROFILE_IDS = {
    "rf_quadrupole_no_acceleration_full_length_direct_mating_gap_0mm",
    "rf_hexapole_no_acceleration_full_length_direct_mating_gap_0mm",
    "rf_octupole_no_acceleration_full_length_direct_mating_gap_0mm",
}
EXPECTED_PORT_PATHS = {
    "rf_quadrupole_ion_optics": (
        "projects/rf_quadrupole_ion_optics/config/interfaces/provided/"
        "rf_multipole_exit_no_acceleration_full_length.json"
    ),
    "rf_hexapole_ion_optics": (
        "projects/rf_hexapole_ion_optics/config/interfaces/provided/"
        "rf_multipole_exit.json"
    ),
    "rf_octupole_ion_optics": (
        "projects/rf_octupole_ion_optics/config/interfaces/provided/"
        "rf_multipole_exit.json"
    ),
}
FAMILY_NAMES = ("quadrupole", "hexapole", "octupole")
PROJECTS = {
    "quadrupole": "rf_quadrupole_ion_optics",
    "hexapole": "rf_hexapole_ion_optics",
    "octupole": "rf_octupole_ion_optics",
}
EXPECTED_RUN_IDS = {
    ("quadrupole", "comsol"): (
        "20260728_202856__sim__comsol__rf-quadrupole-ion-optics-"
        "no-acceleration-full-length__resolved-l3"
    ),
    ("quadrupole", "simion"): (
        "20260728_202457__sim__simion__rf-quadrupole-ion-optics-"
        "no-acceleration-full-length__resolved-l3"
    ),
    ("hexapole", "comsol"): (
        "20260728_212550__sim__comsol__rf-hexapole-ion-optics-"
        "no-acceleration-full-length__resolved-l3"
    ),
    ("hexapole", "simion"): (
        "20260728_212111__sim__simion__rf-hexapole-ion-optics-"
        "no-acceleration-full-length__resolved-l3"
    ),
    ("octupole", "comsol"): (
        "20260728_222324__sim__comsol__rf-octupole-ion-optics-"
        "no-acceleration-full-length__resolved-l3"
    ),
    ("octupole", "simion"): (
        "20260728_221813__sim__simion__rf-octupole-ion-optics-"
        "no-acceleration-full-length__resolved-l3"
    ),
}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def family_source_evidence_available() -> bool:
    for family in FAMILY_NAMES:
        contract = load(
            INTEGRATION_ROOT
            / "config"
            / f"family_{family}_n100_source_contract.json"
        )
        for branch in contract["source_branches"].values():
            for record_name in (
                "manifest",
                "state",
                "particle_source",
                "metadata",
            ):
                if not (
                    WORKSPACE_ROOT
                    / branch["source"][record_name]["path"]
                ).is_file():
                    return False
    return True


FAMILY_SOURCE_EVIDENCE_AVAILABLE = family_source_evidence_available()


class NoAccelerationFamilyProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = load_connection_profile_registry(PROFILE_REGISTRY_PATH)
        cls.family_profiles = {
            profile["connection_profile_id"]: profile
            for profile in cls.registry["profiles"]
            if "_no_acceleration_full_length_" in profile["connection_profile_id"]
        }

    def test_family_repository_publications_are_compiler_fresh(self) -> None:
        self.assertEqual(publication_differences(REPO_ROOT), [])

    def test_first_round_contains_exactly_three_direct_mating_profiles(self) -> None:
        self.assertEqual(set(self.family_profiles), FAMILY_PROFILE_IDS)
        self.assertEqual(
            {
                profile["upstream"]["project_id"]
                for profile in self.family_profiles.values()
            },
            set(EXPECTED_PORT_PATHS),
        )
        for profile in self.family_profiles.values():
            project_id = profile["upstream"]["project_id"]
            self.assertEqual(
                profile["upstream"]["port_contract"],
                EXPECTED_PORT_PATHS[project_id],
            )
            port = load(REPO_ROOT / EXPECTED_PORT_PATHS[project_id])
            self.assertEqual(
                port["profile_scope"],
                {
                    "scope_id": "no_acceleration_full_length",
                    "scope_kind": "design_profile",
                    "family_experiment_port": True,
                },
            )

    def test_family_profiles_resolve_the_same_zero_gap_contract(self) -> None:
        for profile_id in sorted(FAMILY_PROFILE_IDS):
            with self.subTest(profile_id=profile_id):
                resolved = resolve_connection_profile(
                    self.registry,
                    profile_id,
                    repo_root=REPO_ROOT,
                )
                self.assertEqual(resolved["compatibility"]["status"], "pass")
                self.assertEqual(
                    resolved["spatial_registration"]["translation_mm"],
                    [-148.4, 0.0, -18.42918680341103],
                )
                registration = resolved["spatial_registration"]
                self.assertLessEqual(
                    abs(
                        registration["actual_gap_mm"]
                        - registration["expected_gap_mm"]
                    ),
                    registration["position_tolerance_mm"],
                )
                self.assertEqual(resolved["connector"]["length_mm"], 0.0)
                self.assertEqual(resolved["effective_clear_radius_mm"], 0.45)
                self.assertEqual(
                    resolved["potential_alignment"],
                    {
                        "mode": "continuous",
                        "tolerance_V": 0.0,
                        "actual_step_V": 0.0,
                    },
                )
                self.assertEqual(resolved["field_ownership_segments"], [])
                self.assertEqual(
                    resolved["port_geometry"]["upstream"]["mating_surface"],
                    {
                        "center_mm": [0.0, 0.0, 80.6],
                        "outward_normal": [0.0, 0.0, 1.0],
                        "aperture_radius_mm": 3.6,
                        "potential_V": 0.0,
                    },
                )

    def test_each_family_profile_has_one_runtime_binding(self) -> None:
        mappings = load(ADAPTER_REGISTRY_PATH)["mappings"]
        self.assertEqual(len(mappings), len(self.registry["profiles"]))
        self.assertEqual(
            {mapping["connection_profile_id"] for mapping in mappings},
            {
                profile["connection_profile_id"]
                for profile in self.registry["profiles"]
            },
        )
        family_mappings = [
            mapping
            for mapping in mappings
            if mapping["connection_profile_id"] in FAMILY_PROFILE_IDS
        ]
        self.assertEqual(
            {mapping["connection_profile_id"] for mapping in family_mappings},
            FAMILY_PROFILE_IDS,
        )
        self.assertEqual(len(family_mappings), 3)
        self.assertEqual(
            {mapping["adapter_entrypoint"] for mapping in family_mappings},
            {
                "integrations/"
                "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/"
                "workflows/family_source_closure/adapter.ps1"
            },
        )
        for mapping in family_mappings:
            binding_path = REPO_ROOT / mapping["runtime_binding_path"]
            self.assertEqual(
                mapping["runtime_binding_sha256"],
                repository_text_sha256(binding_path),
            )
            binding = load(binding_path)
            validate_schema(
                binding,
                "rf_multipole_oatof_runtime_binding.schema.json",
            )
            self.assertEqual(
                binding["connection_profile_id"],
                mapping["connection_profile_id"],
            )
            contract_records = {
                name: record
                for name, record in binding["contracts"].items()
                if name != "dependency_contract"
            }
            contract_records.update(
                {
                    f"dependency_contract_{name}": record
                    for name, record in binding["contracts"][
                        "dependency_contract"
                    ].items()
                }
            )
            contract_records["implementation_binding"] = binding[
                "implementation_binding"
            ]
            for name, record in contract_records.items():
                frozen = REPO_ROOT / record["path"]
                self.assertTrue(frozen.is_file(), (name, frozen))
                self.assertEqual(
                    record["sha256"], repository_text_sha256(frozen), name
                )
            implementation_registry = load(
                REPO_ROOT / binding["implementation_binding"]["path"]
            )
            self.assertEqual(len(implementation_registry["implementation"]), 10)
            for name, record in implementation_registry["implementation"].items():
                frozen = REPO_ROOT / record["path"]
                self.assertTrue(frozen.is_file(), (name, frozen))
                self.assertEqual(
                    record["sha256"], repository_text_sha256(frozen), name
                )

    @unittest.skipUnless(
        FAMILY_SOURCE_EVIDENCE_AVAILABLE,
        "family source manifest/state/source evidence is incomplete",
    )
    def test_family_source_contracts_freeze_two_real_solver_branches(self) -> None:
        mother_source_sha256 = {
            "0125C3AB02B2321EF26A3A913CF6EC04325FD0D48597D2CB439D0CE42411662F"
        }
        manifest_hashes = set()
        state_hashes = set()
        for family in FAMILY_NAMES:
            source_path = (
                INTEGRATION_ROOT
                / "config"
                / f"family_{family}_n100_source_contract.json"
            )
            source_contract = load(source_path)
            validate_schema(
                source_contract,
                "rf_multipole_oatof_source_contract.schema.json",
            )
            self.assertEqual(source_contract["schema_version"], 2)
            self.assertEqual(
                source_contract["upstream_project_id"],
                PROJECTS[family],
            )
            self.assertEqual(
                source_contract["canonical_state"]["frame_id"],
                "multipole_cartesian_z_axis_v1",
            )
            self.assertEqual(
                source_contract["canonical_state"]["clock_epoch_id"],
                "instrument_clock_epoch_v1",
            )
            self.assertEqual(
                set(source_contract["source_branches"]),
                {"comsol", "simion"},
            )
            adapter = source_contract["adapter"]
            self.assertEqual(
                adapter["sha256"],
                repository_text_sha256(REPO_ROOT / adapter["path"]),
            )
            publication = adapter["dependencies"][
                "handoff_publication_contract"
            ]
            self.assertEqual(
                publication["sha256"],
                repository_text_sha256(REPO_ROOT / publication["path"]),
            )
            for branch_id, branch in source_contract["source_branches"].items():
                self.assertEqual(branch["solver_id"], branch_id)
                self.assertEqual(branch["recorded_project_id"], PROJECTS[family])
                source = branch["source"]
                self.assertEqual(
                    source["run_id"],
                    EXPECTED_RUN_IDS[(family, branch_id)],
                )
                self.assertEqual(source["particle_count"], 100)
                self.assertEqual(
                    source["particle_source_manifest_input_role"],
                    "particle_source",
                )
                for record_name in (
                    "manifest",
                    "state",
                    "particle_source",
                    "metadata",
                ):
                    record = source[record_name]
                    artifact = WORKSPACE_ROOT / record["path"]
                    self.assertTrue(artifact.is_file(), artifact)
                    self.assertEqual(record["sha256"], file_sha256(artifact))
                manifest_hashes.add(source["manifest"]["sha256"])
                state_hashes.add(source["state"]["sha256"])
                mother_source_sha256.add(source["particle_source"]["sha256"])
        self.assertEqual(len(manifest_hashes), 6)
        self.assertEqual(len(state_hashes), 6)
        self.assertEqual(
            mother_source_sha256,
            {
                "0125C3AB02B2321EF26A3A913CF6EC04325FD0D48597D2CB439D0CE42411662F"
            },
        )

    def test_family_bindings_use_own_no_acceleration_resolved_design(self) -> None:
        shared_contract_records = None
        for family in FAMILY_NAMES:
            binding = load(
                INTEGRATION_ROOT
                / "config"
                / f"family_{family}_direct_mating_gap_0mm_runtime_binding.json"
            )
            project = PROJECTS[family]
            resolved = binding["contracts"]["upstream_resolved_design"]
            self.assertEqual(
                resolved["path"],
                f"projects/{project}/config/"
                "resolved_design_no_acceleration_full_length.json",
            )
            self.assertEqual(
                repository_text_sha256(REPO_ROOT / resolved["path"]),
                resolved["sha256"],
            )
            dependency_binding = binding["contracts"]["dependency_contract"]
            dependency_base = load(REPO_ROOT / dependency_binding["base"]["path"])
            dependency_overlay = load(
                REPO_ROOT / dependency_binding["overlay"]["path"]
            )
            dependencies = (
                dependency_base["dependencies"]
                + dependency_overlay["dependencies"]
            )
            records = {item["id"]: item for item in dependencies}
            self.assertEqual(len(records), 52)
            self.assertEqual(
                dependency_base["consumer_project"], INTEGRATION_ROOT.name
            )
            self.assertNotIn("rf_oatof_handoff_builder", records)
            family_publisher = records["rf_family_source_bundle_publisher"]
            self.assertEqual(
                family_publisher["provider_scope"],
                "integration",
            )
            self.assertEqual(
                family_publisher["source_repo_path"],
                "integrations/"
                "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/"
                "analysis/publish_family_source_bundle.py",
            )
            self.assertEqual(
                family_publisher["frozen_filename"],
                "runtime_snapshot/integrations/"
                "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/"
                "analysis/publish_family_source_bundle.py",
            )
            self.assertEqual(
                family_publisher["consumers"],
                ["pre_pulse_interface_transport"],
            )
            self.assertEqual(
                records["rf_resolved_design"]["source_repo_path"],
                resolved["path"],
            )
            self.assertEqual(
                records["rf_project_descriptor"]["provider_project"],
                project,
            )
            self.assertNotIn("rf_dependency_contract_snapshot", records)
            self.assertTrue(
                records["rf_shared_joint_geometry"]["source_repo_path"].endswith(
                    "/config/family_shared_physical_port_joint_geometry.json"
                )
            )
            self.assertEqual(
                records["rf_analyzer_transport_simion_input_adapter"][
                    "source_repo_path"
                ],
                "integrations/"
                "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/"
                "analysis/write_oatof_simion_input.py",
            )
            self.assertEqual(
                set(
                    records["rf_analyzer_transport_simion_input_adapter"][
                        "consumers"
                    ]
                ),
                {"pre_pulse_interface_transport", "analyzer_transport"},
            )
            resolved_connection_schema = records[
                "common_resolved_connection_schema"
            ]
            self.assertEqual(
                resolved_connection_schema["source_repo_path"],
                "common/contracts/schemas/resolved_connection.schema.json",
            )
            self.assertEqual(
                resolved_connection_schema["frozen_filename"],
                "runtime_snapshot/common/contracts/schemas/"
                "resolved_connection.schema.json",
            )
            self.assertEqual(
                resolved_connection_schema["consumers"],
                ["pre_pulse_interface_transport"],
            )
            for dependency_id, schema_name in (
                (
                    "common_connection_profile_schema",
                    "connection_profile.schema.json",
                ),
                (
                    "common_component_port_schema",
                    "component_port.schema.json",
                ),
            ):
                schema_record = records[dependency_id]
                self.assertEqual(
                    schema_record["source_repo_path"],
                    f"common/contracts/schemas/{schema_name}",
                )
                self.assertEqual(
                    schema_record["frozen_filename"],
                    f"runtime_snapshot/common/contracts/schemas/{schema_name}",
                )
                self.assertEqual(
                    schema_record["consumers"],
                    ["pre_pulse_interface_transport"],
                )
            self.assertLessEqual(
                {
                    "common/contracts/machine_contracts.py",
                    "common/contracts/particle_state.py",
                    "common/contracts/particle_count_policy.py",
                    "common/multipole/numerical_qualification.py",
                    "common/multipole/numerical_observables.py",
                    "common/multipole/three_mode_dispersion.py",
                    "common/multipole/publish_three_mode_binding.py",
                },
                {
                    item["source_repo_path"]
                    for item in dependencies
                },
            )
            current_shared = {
                name: binding["contracts"][name]
                for name in (
                    "pre_pulse_contract",
                    "pulse_capture_contract",
                    "pulse_timing_contract",
                    "handoff_contract",
                )
            }
            if shared_contract_records is None:
                shared_contract_records = current_shared
            self.assertEqual(current_shared, shared_contract_records)

    def test_family_publisher_schema_is_in_pre_pulse_snapshot(self) -> None:
        publisher = (
            INTEGRATION_ROOT
            / "analysis"
            / "publish_family_source_bundle.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            'validate_schema(resolved, "resolved_connection.schema.json")',
            publisher,
        )

    def test_handoff_publication_contracts_are_family_specific(self) -> None:
        for family in FAMILY_NAMES:
            contract = load(
                INTEGRATION_ROOT
                / "config"
                / f"family_{family}_handoff_publication_contract.json"
            )
            self.assertEqual(
                set(contract),
                {
                    "schema_version",
                    "role",
                    "selector",
                    "geometry",
                    "population",
                    "canonical_state",
                },
            )
            self.assertEqual(
                contract["role"],
                "multipole_handoff_publication_contract",
            )
            self.assertEqual(
                contract["geometry"],
                {
                    "axial_plane_mm": 80.6,
                    "absolute_tolerance_mm": 1e-9,
                    "require_positive_axial_velocity": True,
                },
            )
            self.assertEqual(
                contract["population"]["expected_source_particle_count"],
                100,
            )
            canonical = contract["canonical_state"]
            self.assertEqual(canonical["source_component_id"], PROJECTS[family])
            self.assertEqual(
                canonical["target_component_id"],
                INTEGRATION_ROOT.name,
            )
            self.assertEqual(
                canonical["frame_id"],
                "multipole_cartesian_z_axis_v1",
            )
            self.assertEqual(
                canonical["clock_epoch_id"],
                "instrument_clock_epoch_v1",
            )
            self.assertEqual(
                canonical["lineage_policy"],
                "root_birth_time_plus_component_elapsed_time",
            )

    def test_family_budget_and_preregistration_are_independent_and_exact(self) -> None:
        budget = load(BUDGET_PATH)
        preregistration = load(PREREGISTRATION_PATH)
        validate_schema(
            budget,
            "integration_family_source_closure_budget.schema.json",
        )
        validate_schema(
            preregistration,
            "integration_family_source_closure_preregistration.schema.json",
        )
        self.assertNotIn("legacy_oracle", preregistration)
        self.assertNotIn("equivalence_status", preregistration)
        self.assertNotIn("comparison_requirements", preregistration)
        self.assertEqual(
            preregistration["engineering_budget"]["sha256"],
            repository_text_sha256(BUDGET_PATH),
        )
        self.assertEqual(
            {
                record["connection_profile_id"]
                for record in preregistration["profiles"]
            },
            FAMILY_PROFILE_IDS,
        )
        self.assertEqual(
            {
                record["connection_profile_id"]
                for record in budget["authorization"]["scope"][
                    "profile_source_contracts"
                ]
            },
            FAMILY_PROFILE_IDS,
        )
        for stage in budget["authorization"]["stage_limits"].values():
            self.assertEqual(stage["automatic_retry_count"], 0)

    def test_source_contract_schema_rejects_missing_or_mismatched_branch(self) -> None:
        source = load(
            INTEGRATION_ROOT
            / "config"
            / "family_quadrupole_n100_source_contract.json"
        )
        missing = json.loads(json.dumps(source))
        del missing["source_branches"]["simion"]
        with self.assertRaises(ContractError):
            validate_schema(
                missing,
                "rf_multipole_oatof_source_contract.schema.json",
            )
        mismatched = json.loads(json.dumps(source))
        mismatched["source_branches"]["comsol"]["solver_id"] = "simion"
        with self.assertRaises(ContractError):
            validate_schema(
                mismatched,
                "rf_multipole_oatof_source_contract.schema.json",
            )


if __name__ == "__main__":
    unittest.main()

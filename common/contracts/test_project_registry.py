from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from artifact_identity_archive import (
    historical_project_identities,
    legacy_artifact_location,
    load_retired_project_descriptors,
)
from build_project_registry import (
    ContractError,
    REPO_ROOT,
    build_registry,
    consistent_profile_identity,
    descriptor_paths,
    validate_descriptor,
    validate_legacy_identity_mappings,
)
from machine_contracts import load_json, validate_schema
from file_identity import repository_text_sha256


MULTIPOLE_PROJECT_ID = "rf_multipole_ion_optics"
RETIRED_MULTIPOLE_IDS = {
    "rf_quadrupole_ion_optics",
    "rf_hexapole_ion_optics",
    "rf_octupole_ion_optics",
}


def pending_location(current: str, retired: str, suffix: str) -> dict:
    archive_id = f"20260801_130000__migration-snapshot__repo__{suffix}"
    archive = f"artifacts/projects/{current}/archive/{archive_id}"
    return {
        "schema_version": 1,
        "state": "source_pending_relocation",
        "source_root": f"artifacts/projects/{retired}",
        "archive_id": archive_id,
        "archive_root": f"{archive}/legacy-project-root",
        "migration_manifest": f"{archive}/identity_migration_manifest.json",
    }


class ProjectRegistryTests(unittest.TestCase):
    def test_nonmultipole_profiles_register_without_pole_counts_or_rf_geometry(self) -> None:
        descriptor = load_json(REPO_ROOT / "projects/orthogonal_accelerator/config/project.json")
        descriptor["contracts"]["interface"] = None
        descriptor["contracts"]["execution"] = None
        for capability in descriptor["capabilities"]:
            capability["modes"] = []
        descriptor["contracts"]["design_profiles"] = "config/design_profiles.json"
        identity = {key: descriptor[key] for key in ("project_id", "family_id")}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "projects" / descriptor["project_id"]
            config = project / "config"
            config.mkdir(parents=True)
            profiles = {"schema_version": 3, "role": "project_design_profile_registry", **identity, "profiles": []}
            for variant in descriptor["structural_variants"]:
                name = variant["variant_id"]
                request = {"identity": identity, "gap_mm": 5}
                variables = {"schema_version": 1, "role": "project_design_variable_catalog", **identity,
                             "variables": [{"variable_id": "gap", "json_pointer": "/gap_mm", "unit": "mm", "minimum": 1, "maximum": 10}]}
                request_path = config / f"{name}_request.json"
                request_path.write_text(json.dumps(request), encoding="utf-8")
                envelope = {"schema_version": 1, "role": "project_optimization_envelope", **identity,
                            "reference": {"design_request": request_path.relative_to(project).as_posix(),
                                          "design_request_sha256": repository_text_sha256(request_path)}}
                documents = {"design_request": request, "design_variables": variables, "optimization_envelope": envelope}
                sources = {"design_request": request_path}
                for label in ("design_variables", "optimization_envelope"):
                    sources[label] = config / f"{name}_{label}.json"
                    sources[label].write_text(json.dumps(documents[label]), encoding="utf-8")
                profiles["profiles"].append({
                    "design_profile_id": name, "structural_variant_id": name, "identity": identity,
                    **{label: path.relative_to(project).as_posix() for label, path in sources.items()},
                    "sha256": {label: repository_text_sha256(path) for label, path in sources.items()},
                })
            for capability in descriptor["capabilities"]:
                capability["design_variables"] = ["gap"]
            (config / "project.json").write_text(json.dumps(descriptor), encoding="utf-8")
            (config / "design_profiles.json").write_text(json.dumps(profiles), encoding="utf-8")
            registered = build_registry(root)
            self.assertEqual(registered["projects"], [descriptor])
            self.assertNotIn("radial_order_n", json.dumps(profiles))
            self.assertNotIn("electrode_count", json.dumps(profiles))
            self.assertTrue(all(set(profile["identity"]) == {"project_id", "family_id"} for profile in profiles["profiles"]))

    def test_nonmultipole_structures_validate_ownership_without_design_profiles(self) -> None:
        path = REPO_ROOT / "projects/orthogonal_accelerator/config/project.json"
        descriptor = load_json(path)
        validate_descriptor(descriptor, path, REPO_ROOT)
        for change, message in (("duplicate", "duplicate structural variant"),
                                ("shared", "capability ownership"),
                                ("missing", "one structural variant owner")):
            with self.subTest(change=change):
                changed = copy.deepcopy(descriptor)
                variants = changed["structural_variants"]
                if change == "duplicate":
                    variants[1]["variant_id"] = variants[0]["variant_id"]
                elif change == "shared":
                    variants[1]["capability_ids"] += variants[0]["capability_ids"]
                else:
                    variants.pop()
                with self.assertRaisesRegex(ContractError, message):
                    validate_descriptor(changed, path, REPO_ROOT)

    def test_public_structure_schema_does_not_accept_project_physics(self) -> None:
        descriptor = load_json(REPO_ROOT / "projects/rf_multipole_ion_optics/config/project.json")
        descriptor["structural_variants"][0]["electrode_count"] = 4
        with self.assertRaises(ContractError):
            validate_schema(descriptor, "project.schema.json")

    def test_registry_algorithm_orders_inputs_normalizes_eol_and_rejects_invalid_inventory(self):
        # Descriptor/schema contracts are tested separately; this isolates the
        # registry algorithm without copying a real project and its history.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = []
            for project_id in ("beta", "alpha"):
                path = root / "projects" / project_id / "config/project.json"
                path.parent.mkdir(parents=True)
                path.write_text(json.dumps({"project_id": project_id}, indent=2) + "\n", encoding="utf-8", newline="\n")
                paths.append(path)
            with patch("build_project_registry.validate_descriptor"), patch(
                "build_project_registry.validate_legacy_identity_mappings"
            ), patch("build_project_registry.validate_schema"):
                lf = build_registry(root)
                self.assertEqual([item["project_id"] for item in lf["projects"]], ["alpha", "beta"])
                for path in paths:
                    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
                self.assertEqual(build_registry(root), lf)
                paths[0].write_text('{"project_id":"alpha"}', encoding="utf-8")
                with self.assertRaisesRegex(ContractError, "duplicate project_id"):
                    build_registry(root)
                (root / "projects" / "missing").mkdir()
                with self.assertRaisesRegex(ContractError, "missing config/project.json"):
                    build_registry(root)

    def test_multipole_registration_uses_one_consistent_profile_identity(self) -> None:
        identities = [
            {
                "project_id": "rf_hexapole_ion_optics",
                "family_id": "rf_multipole_ion_optics",
                "radial_order_n": 3,
                "electrode_count": 6,
            },
            {
                "project_id": "rf_hexapole_ion_optics",
                "family_id": "rf_multipole_ion_optics",
                "radial_order_n": 3,
                "electrode_count": 6,
            },
        ]
        profiles_path = REPO_ROOT / "profiles.json"
        self.assertEqual(
            consistent_profile_identity(identities, profiles_path),
            identities[0],
        )
        identities[1] = {**identities[1], "radial_order_n": 4}
        with self.assertRaisesRegex(ContractError, "design profile identities differ"):
            consistent_profile_identity(identities, profiles_path)
        with self.assertRaisesRegex(ContractError, "require an identity"):
            consistent_profile_identity([], profiles_path)

    def test_rf_multipole_descriptors_do_not_register_legacy_baselines(self) -> None:
        path = REPO_ROOT / "projects" / MULTIPOLE_PROJECT_ID / "config/project.json"
        descriptor = load_json(path)
        self.assertIsNone(descriptor["contracts"]["baseline"])
        validate_descriptor(descriptor, path, REPO_ROOT)
        retired = load_retired_project_descriptors(descriptor, REPO_ROOT)
        self.assertEqual({item["project_id"] for item in retired}, RETIRED_MULTIPOLE_IDS)
        for previous in retired:
            with self.subTest(project_id=previous["project_id"]):
                self.assertIsNone(previous["contracts"]["baseline"])
                validate_schema(previous, "project.schema.json")

        registry = load_json(REPO_ROOT / "config/project_registry.json")
        active = {item["project_id"]: item for item in registry["projects"]}
        historical_ids = {
            identity.project_id for identity in historical_project_identities(descriptor, REPO_ROOT)
        }
        self.assertTrue(historical_ids.isdisjoint(active))
        self.assertEqual(active[MULTIPOLE_PROJECT_ID]["capabilities"], descriptor["capabilities"])
        self.assertEqual(
            sum(item["family_id"] == MULTIPOLE_PROJECT_ID for item in registry["projects"]),
            1,
        )

    def test_all_project_directories_have_descriptors(self) -> None:
        project_directories = sorted(path.name for path in (REPO_ROOT / "projects").iterdir() if path.is_dir())
        described = sorted(path.parents[1].name for path in descriptor_paths(REPO_ROOT))
        self.assertEqual(project_directories, described)

    def test_mrtof_descriptor_registers_current_candidate_baseline(self) -> None:
        descriptor = load_json(
            REPO_ROOT
            / "projects/parallel_mirror_dual_stripe_mr_tof/config/project.json"
        )
        self.assertEqual(descriptor["lifecycle_status"], "candidate")
        self.assertEqual(
            descriptor["contracts"]["baseline"],
            "config/simion_candidate_two_zone.json",
        )
        self.assertIsNone(descriptor["contracts"]["resolved"])
        self.assertIn("simion", descriptor["toolchains"])
        self.assertEqual(descriptor["capabilities"][0]["status"], "candidate")

    def test_project_id_must_match_directory(self) -> None:
        path = REPO_ROOT / "projects" / "single_reflection_oa_tof_mass_analyzer" / "config" / "project.json"
        descriptor = copy.deepcopy(load_json(path))
        descriptor["project_id"] = "wrong_project"
        with self.assertRaisesRegex(ContractError, "differs from directory"):
            validate_descriptor(descriptor, path, REPO_ROOT)

    def test_schema_rejects_unknown_maturity(self) -> None:
        path = REPO_ROOT / "projects" / "single_reflection_oa_tof_mass_analyzer" / "config" / "project.json"
        descriptor = copy.deepcopy(load_json(path))
        descriptor["lifecycle_status"] = "finished"
        with self.assertRaises(ContractError):
            validate_schema(descriptor, "project.schema.json")

    def test_execution_runtime_binding_schema_rejects_invalid_declarations(self) -> None:
        original = load_json(REPO_ROOT / "projects/rf_multipole_ion_optics/config/execution_profiles.json")
        valid = original["profiles"][0]["runtime_binding"]
        invalid = [None, {}, {**valid, "callable": "other_function"}, {**valid, "required_bindings": []},
                   {**valid, "required_bindings": ["runtime_profile_id", "runtime_profile_id"]}]
        invalid.extend({**valid, "entrypoint": entrypoint} for entrypoint in (
            "../other_project/runtime.py", "/external.py", "C:/external.py", "runtime/not-python.json",
        ))
        for declaration in invalid:
            document = copy.deepcopy(original)
            document["profiles"][0]["runtime_binding"] = declaration
            with self.subTest(declaration=declaration), self.assertRaises(ContractError):
                validate_schema(document, "execution_profiles.schema.json")

    def test_project_registration_rejects_missing_runtime_resolver_and_unknown_selectors(self) -> None:
        project_root = REPO_ROOT / "projects/rf_multipole_ion_optics"
        descriptor_path = project_root / "config/project.json"
        descriptor = load_json(descriptor_path)
        execution_path = project_root / "config/execution_profiles.json"
        for field, value, message in (
            ("entrypoint", "runtime/missing_resolver.py", "entrypoint is missing"),
            ("required_bindings", ["not_a_profile_binding"], "must be required bindings"),
        ):
            execution = load_json(execution_path)
            execution["profiles"][0]["runtime_binding"][field] = value

            def changed_load(path):
                return execution if Path(path) == execution_path else load_json(path)

            with self.subTest(field=field), patch("build_project_registry.load_json", side_effect=changed_load):
                with self.assertRaisesRegex(ContractError, message):
                    validate_descriptor(descriptor, descriptor_path, REPO_ROOT)

    def test_formal_project_retains_contracts_and_identity_requirement(self) -> None:
        path = REPO_ROOT / "projects" / "single_reflection_oa_tof_mass_analyzer" / "config" / "project.json"
        descriptor = copy.deepcopy(load_json(path))
        self.assertEqual(descriptor["lifecycle_status"], "formal")
        self.assertIn("science", descriptor["contracts"])
        self.assertIn("solver_numerics", descriptor["contracts"])
        validate_descriptor(descriptor, path, REPO_ROOT)

        descriptor["formal_assets"]["identity_contract"] = None
        with self.assertRaisesRegex(ContractError, "identity contract"):
            validate_descriptor(descriptor, path, REPO_ROOT)

    def test_legacy_identity_schema_freezes_recorded_evidence_semantics(self) -> None:
        path = REPO_ROOT / "projects" / "single_reflection_oa_tof_mass_analyzer" / "config" / "project.json"
        descriptor = copy.deepcopy(load_json(path))
        legacy = descriptor["legacy_identities"][0]
        self.assertEqual(legacy["verification_identity"], "recorded_project_id")
        self.assertEqual(legacy["artifact_access"], "read_only")
        self.assertFalse(legacy["new_runs_allowed"])

        legacy["verification_identity"] = "current_project_id"
        with self.assertRaises(ContractError):
            validate_schema(descriptor, "project.schema.json")

        descriptor = copy.deepcopy(load_json(path))
        legacy = descriptor["legacy_identities"][0]
        legacy.pop("artifact_location")
        legacy["artifact_root"] = "artifacts/projects/oa_tof"
        with self.assertRaises(ContractError):
            validate_schema(descriptor, "project.schema.json")

    def test_legacy_identity_rejects_active_id_and_wrong_artifact_location(self) -> None:
        descriptors = [
            {
                "project_id": "current_project",
                "legacy_identities": [
                    {
                        "mapping_id": "rename_1",
                        "project_id": "other_active_project",
                        "artifact_location": pending_location(
                            "current_project", "other_active_project", "other-active"
                        ),
                    }
                ],
            },
            {"project_id": "other_active_project"},
        ]
        with self.assertRaisesRegex(ContractError, "still active"):
            validate_legacy_identity_mappings(descriptors)

        descriptors.pop()
        descriptors[0]["legacy_identities"][0]["project_id"] = "retired_project"
        with self.assertRaisesRegex(ContractError, "legacy artifact location differs"):
            validate_legacy_identity_mappings(descriptors)

    def test_multipole_relocation_has_one_governed_archive(self) -> None:
        descriptor = load_json(
            REPO_ROOT / "projects" / MULTIPOLE_PROJECT_ID / "config/project.json"
        )
        retired = load_retired_project_descriptors(descriptor, REPO_ROOT)
        identities = {
            identity.project_id: identity
            for identity in historical_project_identities(descriptor, REPO_ROOT)
        }
        self.assertEqual({item["project_id"] for item in retired}, RETIRED_MULTIPOLE_IDS)
        for previous in retired:
            project_id = previous["project_id"]
            owner = identities[project_id]
            self.assertEqual(owner.artifact_owner_project_id, project_id)
            self.assertIsNone(owner.legacy_mapping)
            self.assertEqual(owner.policy["artifact_access"], "read_only")
            self.assertFalse(owner.policy["new_runs_allowed"])
            self.assertEqual(owner.policy["verification_identity"], "recorded_project_id")
            self.assertTrue(previous["legacy_identities"])
            for mapping in previous["legacy_identities"]:
                identity = identities[mapping["project_id"]]
                self.assertEqual(identity.artifact_owner_project_id, project_id)
                self.assertEqual(identity.legacy_mapping, mapping)
                location = mapping["artifact_location"]
                validated = legacy_artifact_location(mapping, identity.artifact_owner_project_id)
                self.assertIn(
                    location["state"], {"source_pending_relocation", "archived_verified"}
                )
                if location["state"] == "source_pending_relocation":
                    self.assertEqual(
                        location["source_root"],
                        f"artifacts/projects/{mapping['project_id']}",
                    )
                    self.assertEqual(validated["active_root"], location["source_root"])
                else:
                    self.assertNotIn("source_root", location)
                    self.assertEqual(validated["active_root"], location["archive_root"])
                self.assertNotIn("artifact_root", mapping)
                self.assertTrue(location["archive_root"].startswith(
                    f"artifacts/projects/{project_id}/archive/"
                ))
                self.assertEqual(
                    location["migration_manifest"],
                    location["archive_root"].removesuffix("/legacy-project-root")
                    + "/identity_migration_manifest.json",
                )

    def test_legacy_identity_rejects_duplicate_ids_and_mapping_ids(self) -> None:
        descriptors = [
            {
                "project_id": "current_a",
                "legacy_identities": [
                    {
                        "mapping_id": "rename_shared",
                        "project_id": "retired_shared",
                        "artifact_location": pending_location(
                            "current_a", "retired_shared", "retired-shared-a"
                        ),
                    }
                ],
            },
            {
                "project_id": "current_b",
                "legacy_identities": [
                    {
                        "mapping_id": "rename_other",
                        "project_id": "retired_shared",
                        "artifact_location": pending_location(
                            "current_b", "retired_shared", "retired-shared-b"
                        ),
                    }
                ],
            },
        ]
        with self.assertRaisesRegex(ContractError, "duplicate legacy project_id"):
            validate_legacy_identity_mappings(descriptors)

        descriptors[1]["legacy_identities"][0].update(
            {
                "mapping_id": "rename_shared",
                "project_id": "retired_other",
                "artifact_location": pending_location(
                    "current_b", "retired_other", "retired-other"
                ),
            }
        )
        with self.assertRaisesRegex(ContractError, "duplicate legacy mapping_id"):
            validate_legacy_identity_mappings(descriptors)


class RetiredProjectRegistryTests(unittest.TestCase):
    def test_retired_owners_and_aliases_are_not_active_or_duplicate(self) -> None:
        from common.contracts.test_artifact_identity_archive import CURRENT, LEGACY, retirement_fixture

        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory)
            descriptor, _ = retirement_fixture(repository)
            validate_legacy_identity_mappings([descriptor], repository)
            for project_id in (CURRENT, LEGACY):
                with self.subTest(project_id=project_id):
                    with self.assertRaisesRegex(ContractError, "still active"):
                        validate_legacy_identity_mappings([descriptor, {"project_id": project_id}], repository)
            duplicate = {"project_id": "other", "legacy_identities": [{
                "mapping_id": "other_alias", "project_id": CURRENT,
                "artifact_location": pending_location("other", CURRENT, "other-alias"),
            }]}
            with self.assertRaisesRegex(ContractError, "duplicate legacy project_id"):
                validate_legacy_identity_mappings([descriptor, duplicate], repository)
            self.assertNotIn("capabilities", descriptor)

    def test_retired_descriptor_schema_requires_identity_and_read_only_fields(self) -> None:
        from common.contracts.test_artifact_identity_archive import retirement_fixture

        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory)
            retired, _ = retirement_fixture(repository)
            descriptor = load_json(REPO_ROOT / "projects/orthogonal_accelerator/config/project.json")
            descriptor["retired_project_descriptors"] = retired["retired_project_descriptors"]
            validate_schema(descriptor, "project.schema.json")
            for field in ("source_commit", "sha256", "path", "new_runs_allowed"):
                changed = copy.deepcopy(descriptor)
                changed["retired_project_descriptors"][0].pop(field)
                with self.subTest(field=field), self.assertRaises(ContractError):
                    validate_schema(changed, "project.schema.json")
            descriptor["retired_project_descriptors"][0]["new_runs_allowed"] = True
            with self.assertRaises(ContractError):
                validate_schema(descriptor, "project.schema.json")


if __name__ == "__main__":
    unittest.main()

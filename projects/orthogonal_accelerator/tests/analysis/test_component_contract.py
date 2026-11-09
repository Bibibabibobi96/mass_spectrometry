"""Guard the accelerator's independent project and explicit consumer boundary."""
from __future__ import annotations

import ast
import json
import shutil
import tempfile
from pathlib import Path
import unittest

from common.contracts.build_project_registry import validate_descriptor
from projects.orthogonal_accelerator.analysis.component_contract import load_accelerator_dependency, load_component_contract


PROJECT = Path(__file__).resolve().parents[2]
REPO = PROJECT.parents[1]


class ComponentContractTest(unittest.TestCase):
    def test_project_descriptor_and_structural_variants(self) -> None:
        path = PROJECT / "config/project.json"
        descriptor = json.loads(path.read_text(encoding="utf-8"))
        validate_descriptor(descriptor, path, REPO)
        api = json.loads((PROJECT / descriptor["contracts"]["interface"]).read_text(encoding="utf-8"))
        self.assertEqual(api["schema_version"], 1)
        self.assertEqual(api["api_version"], 2)
        self.assertEqual(api["project_id"], descriptor["project_id"])
        variants = {row["variant_id"]: row for row in api["structural_variants"]}
        self.assertEqual(set(variants), {"two_zone", "three_zone"})
        public_variants = {row["variant_id"]: row for row in descriptor["structural_variants"]}
        self.assertEqual(set(public_variants), set(variants))
        for variant, count in (("two_zone", 2), ("three_zone", 3)):
            self.assertEqual(public_variants[variant]["capability_ids"], [variant + "_orthogonal_acceleration"])
            self.assertEqual(variants[variant]["field_region_count"], count)
            self.assertEqual(len(variants[variant]["primary_electrode_roles"]), count + 1)
        for relative in api["implementation_modules"]:
            self.assertTrue(((REPO if Path(relative).parts[:2] == ("src", "msplatform") else PROJECT) / relative).is_file(), relative)
        self.assertEqual(api["request_api"]["two_zone"]["role"],
                         "orthogonal_accelerator_two_zone_requirements")
        self.assertEqual(api["request_api"]["two_zone"]["requirements_schema_versions"], {
            "1": "closed_sidewalls", "2": "explicit_negative_y_side_entry__provider_centered_in_first_gap",
        })
        self.assertEqual(api["request_api"]["two_zone"]["fixed_topology"],
                         "solid_positive_z_repeller_and_grounded_cap__negative_z_exit_grid")
        self.assertEqual(api["request_api"]["two_zone"]["flight_source"],
                         "caller_supplied_repository_ion_release_spec__run_input_only__excluded_from_pa_geometry_identity")
        self.assertEqual(api["request_api"]["two_zone"]["geometry_authority"],
                         "provider_owned__consumer_requests_only_source_envelope_mesh_and_rigid_placement")
        self.assertTrue((REPO / "src/msplatform/backends/simion/two_zone_candidate.py").is_file())
        self.assertEqual(api["request_api"]["three_zone"]["role"], "orthogonal_accelerator_bare_three_zone_requirements")
        self.assertTrue((REPO / "src/msplatform/backends/simion/bare_three_zone_component.py").is_file())
        self.assertEqual(descriptor["formal_assets"]["status"], "none")

    def test_consumers_explicitly_declare_provider_and_variant(self) -> None:
        for consumer in ("single_reflection_oa_tof_mass_analyzer", "parallel_mirror_dual_stripe_mr_tof"):
            contract = REPO / "projects" / consumer / "config/accelerator_dependency.json"
            dependency = json.loads(contract.read_text(encoding="utf-8"))
            self.assertEqual(dependency["consumer_project_id"], consumer)
            self.assertEqual(dependency["provider_project_id"], PROJECT.name)
            provider = json.loads((REPO / dependency["provider_contract"]).read_text(encoding="utf-8"))
            self.assertEqual(dependency["api_version"], provider["api_version"])
            available = {row["variant_id"] for row in provider["structural_variants"]}
            self.assertTrue(set(dependency["structural_variants"]) <= available)

    def test_current_api3_and_explicit_api2_preserve_distinct_role_meanings(self) -> None:
        current = load_component_contract(REPO)
        legacy = load_component_contract(REPO, api_version=2)
        self.assertEqual(current["api_version"], 3)
        self.assertEqual(current["provider_contract_path"].name, "component_contract_v3.json")
        self.assertEqual(legacy["api_version"], 2)
        self.assertEqual(legacy["provider_contract_path"].name, "component_contract.json")
        modern = {row["variant_id"]: row["primary_electrode_roles"] for row in current["provider"]["structural_variants"]}
        old = {row["variant_id"]: row["primary_electrode_roles"] for row in legacy["provider"]["structural_variants"]}
        self.assertEqual(modern, {"two_zone": ["repeller", "intermediate_grid_1", "exit_grid"],
                                  "three_zone": ["repeller", "intermediate_grid_1", "intermediate_grid_2", "exit_grid"]})
        self.assertEqual(old["three_zone"], ["repeller", "grid1", "grid2", "exit_grid"])
        self.assertEqual(current["provider"]["geometry_profiles"], legacy["provider"]["geometry_profiles"])
        self.assertEqual(current["provider"]["request_api"], legacy["provider"]["request_api"])
        self.assertTrue(all(path.is_file() for path in current["implementation_sources"]))

    def _current_dependency_fixture(self, root: Path) -> tuple[Path, Path]:
        contract = load_component_contract(REPO)
        provider_path = root / contract["provider_contract_path"].relative_to(REPO)
        provider_path.parent.mkdir(parents=True)
        shutil.copyfile(contract["provider_contract_path"], provider_path)
        for source in contract["implementation_sources"]:
            target = root / source.relative_to(REPO)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        dependency = json.loads((REPO / "projects/single_reflection_oa_tof_mass_analyzer/config/accelerator_dependency.json").read_text(encoding="utf-8"))
        dependency.update(api_version=3, provider_contract="projects/orthogonal_accelerator/config/component_contract_v3.json")
        path = root / "projects/single_reflection_oa_tof_mass_analyzer/config/accelerator_dependency.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(dependency), encoding="utf-8")
        return path, provider_path

    def test_declared_dependency_versions_are_not_inferred_from_role_aliases(self) -> None:
        for consumer in ("single_reflection_oa_tof_mass_analyzer", "parallel_mirror_dual_stripe_mr_tof"):
            dependency = REPO / "projects" / consumer / "config/accelerator_dependency.json"
            result = load_accelerator_dependency(REPO, dependency, consumer_project_id=consumer, required_variant="two_zone")
            self.assertEqual(result["api_version"], 2)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dependency, _ = self._current_dependency_fixture(root)
            result = load_accelerator_dependency(root, dependency, consumer_project_id="single_reflection_oa_tof_mass_analyzer", required_variant="three_zone")
            self.assertEqual(result["api_version"], 3)
            original = json.loads(dependency.read_text(encoding="utf-8"))
            for changed in ({**original, "api_version": 99},
                            {**original, "provider_contract": "projects/orthogonal_accelerator/config/component_contract.json"}):
                dependency.write_text(json.dumps(changed), encoding="utf-8")
                with self.subTest(changed=changed), self.assertRaises(ValueError):
                    load_accelerator_dependency(root, dependency, consumer_project_id="single_reflection_oa_tof_mass_analyzer", required_variant="three_zone")

    def test_current_provider_rejects_old_grid2_alias_and_unknown_versions(self) -> None:
        for version in (1, 4, True, None, "3", 3.0):
            with self.subTest(version=version), self.assertRaisesRegex(ValueError, "api_version"):
                load_component_contract(REPO, api_version=version)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, provider = self._current_dependency_fixture(root)
            document = json.loads(provider.read_text(encoding="utf-8"))
            document["structural_variants"][1]["primary_electrode_roles"] = ["repeller", "grid1", "grid2", "exit_grid"]
            provider.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "topology"):
                load_component_contract(root)

    def test_both_provider_versions_require_the_canonical_renderer_without_fallback(self) -> None:
        renderer = "src/msplatform/backends/simion/accelerator_renderer.py"
        for version in (2,3):
            with self.subTest(api_version=version), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                contract = load_component_contract(REPO, api_version=version)
                self.assertIn(renderer, contract["provider"]["implementation_modules"])
                self.assertIn(REPO / renderer, contract["implementation_sources"])
                provider = root / contract["provider_contract_path"].relative_to(REPO)
                provider.parent.mkdir(parents=True)
                shutil.copyfile(contract["provider_contract_path"], provider)
                for source in contract["implementation_sources"]:
                    target = root / source.relative_to(REPO)
                    target.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copyfile(source,target)
                (root / renderer).unlink()
                retired = root / "projects/orthogonal_accelerator/simion/sectioned_accelerator.py"
                retired.parent.mkdir(parents=True,exist_ok=True)
                retired.write_text("# Old alternate location must not satisfy the canonical declaration.\n")
                with self.assertRaisesRegex(ValueError,"source is missing: src/msplatform/backends/simion/accelerator_renderer.py"):
                    load_component_contract(root, api_version=version)

    def test_explicit_historical_project_relative_declaration_is_not_rewritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            contract=load_component_contract(REPO, api_version=2)
            document=json.loads(contract["provider_contract_path"].read_text(encoding="utf-8"))
            canonical="src/msplatform/backends/simion/accelerator_renderer.py"
            historical="simion/sectioned_accelerator.py"
            document["implementation_modules"]=[historical if name==canonical else name for name in document["implementation_modules"]]
            provider=root/contract["provider_contract_path"].relative_to(REPO)
            provider.parent.mkdir(parents=True)
            frozen_bytes=(json.dumps(document)+"\n").encode("utf-8")
            provider.write_bytes(frozen_bytes)
            for relative in document["implementation_modules"]:
                target=(root/relative if relative.startswith('src/msplatform/') else provider.parents[1]/relative)
                target.parent.mkdir(parents=True,exist_ok=True)
                target.write_text("# Historical declared-source identity fixture; never executed.\n")
            result=load_component_contract(root, api_version=2)
            self.assertEqual(provider.read_bytes(),frozen_bytes)
            self.assertIn(provider.parents[1]/historical,result["implementation_sources"])
            self.assertEqual(result["provider"]["implementation_modules"],document["implementation_modules"])
            self.assertNotIn(root/canonical,result["implementation_sources"])

    def test_provider_python_does_not_depend_on_instrument_implementations(self) -> None:
        for folder in ("analysis", "simion"):
            for path in (PROJECT / folder).glob("*.py"):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                for node in ast.walk(tree):
                    names = ([node.module or ""] if isinstance(node, ast.ImportFrom)
                             else [alias.name for alias in node.names] if isinstance(node, ast.Import) else [])
                    for name in names:
                        self.assertFalse(name.startswith(("projects.single_reflection_", "projects.parallel_mirror_", "integrations.")),
                                         f"reverse dependency in {path.name}: {name}")


if __name__ == "__main__":
    unittest.main()

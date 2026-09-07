"""Guard the accelerator's independent project and explicit consumer boundary."""
from __future__ import annotations

import ast
import json
from pathlib import Path
import unittest

from common.contracts.build_project_registry import validate_descriptor


PROJECT = Path(__file__).resolve().parents[2]
REPO = PROJECT.parents[1]


class ComponentContractTest(unittest.TestCase):
    def test_project_descriptor_and_structural_variants(self) -> None:
        path = PROJECT / "config/project.json"
        descriptor = json.loads(path.read_text(encoding="utf-8"))
        validate_descriptor(descriptor, path, REPO)
        api = json.loads((PROJECT / descriptor["contracts"]["interface"]).read_text(encoding="utf-8"))
        self.assertEqual(api["schema_version"], 1)
        self.assertEqual(api["api_version"], 1)
        self.assertEqual(api["project_id"], descriptor["project_id"])
        variants = {row["variant_id"]: row for row in api["structural_variants"]}
        self.assertEqual(set(variants), {"two_zone", "three_zone"})
        for variant, count in (("two_zone", 2), ("three_zone", 3)):
            self.assertEqual(variants[variant]["field_region_count"], count)
            self.assertEqual(len(variants[variant]["primary_electrode_roles"]), count + 1)
        for relative in api["implementation_modules"]:
            self.assertTrue((PROJECT / relative).is_file(), relative)
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

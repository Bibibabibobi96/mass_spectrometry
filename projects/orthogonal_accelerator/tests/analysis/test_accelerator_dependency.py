"""Runtime rejection tests for accelerator provider identity and versions."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from projects.orthogonal_accelerator.analysis.component_contract import load_accelerator_dependency


REPO = Path(__file__).resolve().parents[4]
CONSUMER = "single_reflection_oa_tof_mass_analyzer"


class AcceleratorDependencyTest(unittest.TestCase):
    def fixture(self, root: Path) -> tuple[Path, Path]:
        dependency_path = root / "projects" / CONSUMER / "config/accelerator_dependency.json"
        provider_path = root / "projects/orthogonal_accelerator/config/component_contract.json"
        for path in (dependency_path, provider_path):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((REPO / path.relative_to(root)).read_bytes())
        provider = json.loads(provider_path.read_text(encoding="utf-8"))
        for relative in provider["implementation_modules"]:
            path = provider_path.parents[1] / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# module fixture\n", encoding="utf-8")
        return dependency_path, provider_path

    def test_live_contract_resolves_one_provider_and_real_paths(self) -> None:
        result = load_accelerator_dependency(
            REPO, REPO / "projects" / CONSUMER / "config/accelerator_dependency.json",
            consumer_project_id=CONSUMER, required_variant="two_zone",
        )
        self.assertEqual(result["api_version"], 1)
        self.assertTrue(all(path.is_file() for path in result["implementation_sources"]))
        self.assertIn(Path(__file__).parents[2] / "analysis/component_contract.py",
                      result["implementation_sources"])

    def test_consumer_and_provider_version_drift_fail_closed(self) -> None:
        for which in ("consumer", "provider"):
            with self.subTest(which=which), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                dependency, provider = self.fixture(root)
                target = dependency if which == "consumer" else provider
                document = json.loads(target.read_text(encoding="utf-8"))
                document["api_version"] = 2
                target.write_text(json.dumps(document), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "api_version"):
                    load_accelerator_dependency(root, dependency, consumer_project_id=CONSUMER,
                                                required_variant="two_zone")

    def test_missing_field_and_unavailable_variant_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dependency, _ = self.fixture(root)
            with self.assertRaisesRegex(ValueError, "variant"):
                load_accelerator_dependency(root, dependency, consumer_project_id=CONSUMER,
                                            required_variant="four_zone")
            document = json.loads(dependency.read_text(encoding="utf-8"))
            del document["api_version"]
            dependency.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "missing or unknown"):
                load_accelerator_dependency(root, dependency, consumer_project_id=CONSUMER,
                                            required_variant="two_zone")

    def test_provider_topology_and_source_escape_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dependency, provider = self.fixture(root)
            document = json.loads(provider.read_text(encoding="utf-8"))
            document["implementation_modules"] = ["../outside.py"]
            provider.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "escapes"):
                load_accelerator_dependency(root, dependency, consumer_project_id=CONSUMER,
                                            required_variant="two_zone")
            document["structural_variants"][0]["field_region_count"] = 3
            provider.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "topology"):
                load_accelerator_dependency(root, dependency, consumer_project_id=CONSUMER,
                                            required_variant="two_zone")

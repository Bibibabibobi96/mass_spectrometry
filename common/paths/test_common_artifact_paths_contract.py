"""Static regression for explicit component-test artifact contexts."""

import re
import unittest
from pathlib import Path


COMMON = Path(__file__).resolve().parents[1]


class CommonArtifactPathContractTests(unittest.TestCase):
    def test_component_consumers_require_and_forward_context(self) -> None:
        consumers = [
            path for path in (COMMON / "comsol").glob("test_*.m")
            if "common_artifact_paths(" in path.read_text(encoding="utf-8")
        ]
        self.assertEqual(len(consumers), 16)
        for path in consumers:
            with self.subTest(path=path.name):
                source = path.read_text(encoding="utf-8")
                self.assertRegex(source.splitlines()[0], r"\(runDir(?:,|\))")
                self.assertIn("paths = common_artifact_paths(runDir);", source)
                self.assertNotIn("common_artifact_paths()", source)

    def test_output_roles_are_run_local_and_context_must_exist(self) -> None:
        source = (COMMON / "paths/common_artifact_paths.m").read_text(encoding="utf-8")
        self.assertIn("~isfolder(runDir)", source)
        self.assertIn('numel(parts) ~= 3', source)
        self.assertIn('["runs", "scratch"]', source)
        self.assertIn("fullfile(workspace.artifactRoot, 'projects')", source)
        self.assertIn("fullfile(runDir, 'comsol')", source)
        self.assertIn("fullfile(runDir, 'results')", source)
        self.assertNotIn("paths.scratchDir", source)
        self.assertNotRegex(source, r"mkdir\(runDir\)")
        self.assertIn("common_artifact_paths:PublishedContext", source)
        self.assertIn("~strcmp(manifest.status, 'checkpoint')", source)

    def test_optional_physics_defaults_keep_their_argument_positions(self) -> None:
        for name, expected in {
            "test_collision_cell.m": [2, 3, 4],
            "test_resonant_charge_exchange.m": [2, 3, 4],
            "test_space_charge.m": [2, 3],
            "test_multipole_geometry.m": [2],
            "test_multipole_es.m": [2],
        }.items():
            with self.subTest(name=name):
                source = (COMMON / "comsol" / name).read_text(encoding="utf-8")
                self.assertEqual([int(n) for n in re.findall(r"nargin\s*<\s*(\d+)", source)], expected)

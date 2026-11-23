"""Static regression for explicit component-test artifact contexts."""

import re
import unittest
from pathlib import Path


COMMON = Path(__file__).resolve().parents[1]


class CommonArtifactPathContractTests(unittest.TestCase):
    def test_component_consumers_pass_an_explicit_context(self) -> None:
        for path in (COMMON / "comsol").glob("*.m"):
            with self.subTest(path=path.name):
                source = re.sub(r"%[^\n]*", "", path.read_text(encoding="utf-8"))
                source = source.replace("...", "")
                self.assertNotRegex(
                    source, r"\bcommon_artifact_paths\s*(?:\(\s*\)|(?=[;,\n]|$))",
                    "component output paths require an explicit run/scratch context",
                )

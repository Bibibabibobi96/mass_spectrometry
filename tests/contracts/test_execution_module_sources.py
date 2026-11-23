"""Execution source lookup does not execute the selected target module."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from msplatform.execution.inputs import resolve_python_module_sources


class ModuleSourceResolutionTests(unittest.TestCase):
    def test_target_not_executed_and_dotted_parent_semantics(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / "fixture_source_parent"
            package.mkdir()
            marker = root / "parent_imported"
            (package / "__init__.py").write_text(f"from pathlib import Path\nPath({str(marker)!r}).write_text('yes')\n", encoding="utf8")
            target = package / "unexecuted.py"
            target.write_text("raise RuntimeError('TARGET EXECUTED')\n", encoding="utf8")
            with patch.object(sys, "path", [str(root), *sys.path]):
                try:
                    result = resolve_python_module_sources(["fixture_source_parent.unexecuted"])
                    self.assertEqual(result["fixture_source_parent.unexecuted"], target.resolve())
                    self.assertTrue(marker.is_file())
                    self.assertNotIn("fixture_source_parent.unexecuted", sys.modules)
                    with self.assertRaises((ValueError, ModuleNotFoundError)):
                        resolve_python_module_sources(["fixture_source_parent.missing"])
                    with self.assertRaisesRegex(ValueError, "source module"):
                        resolve_python_module_sources(["sys"])
                finally:
                    sys.modules.pop("fixture_source_parent", None)
                    sys.modules.pop("fixture_source_parent.unexecuted", None)

    def test_names_must_be_explicit(self):
        for name in ("", "a..b", "../invalid", "with-hyphen"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                resolve_python_module_sources([name])
        with self.assertRaises(ValueError):
            resolve_python_module_sources("sys")

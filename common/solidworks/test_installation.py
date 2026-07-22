from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from common.solidworks.installation import resolve_solidworks_2022_root


class SolidWorksInstallationTests(unittest.TestCase):
    def test_environment_override_resolves_valid_installation(self) -> None:
        with tempfile.TemporaryDirectory() as root_text:
            root = Path(root_text)
            (root / "SLDWORKS.exe").touch()
            with patch.dict("os.environ", {"SOLIDWORKS_2022_ROOT": str(root)}, clear=False):
                self.assertEqual(resolve_solidworks_2022_root(), root.resolve())

    def test_missing_environment_and_registry_fail_closed(self) -> None:
        with (
            patch.dict("os.environ", {}, clear=True),
            patch("common.solidworks.installation.REGISTRY_KEYS", ()),
        ):
            with self.assertRaisesRegex(FileNotFoundError, "SOLIDWORKS_2022_ROOT"):
                resolve_solidworks_2022_root()


if __name__ == "__main__":
    unittest.main()

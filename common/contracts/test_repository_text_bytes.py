from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from common.verify_repository_text_bytes import carriage_return_paths


class RepositoryTextBytesTests(unittest.TestCase):
    def test_effective_git_attributes_detect_crlf_and_honor_binary_exception(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(
                ["git", "init", "-q"], cwd=root, check=True, timeout=30
            )
            (root / ".gitattributes").write_bytes(
                b"*.json text eol=lf\nfixtures/*.json -text -eol\n"
            )
            (root / "clean.json").write_bytes(b"{}\n")
            (root / "bad.json").write_bytes(b"{}\r\n")
            (root / "fixtures").mkdir()
            (root / "fixtures" / "frozen.json").write_bytes(b"{}\r\n")
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(root),
                    "add",
                    ".gitattributes",
                    "clean.json",
                    "bad.json",
                    "fixtures/frozen.json",
                ],
                cwd=root,
                check=True,
                timeout=30,
            )
            self.assertEqual(carriage_return_paths(root), [Path("bad.json")])


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from common import verify_repository_text_bytes as text_gate
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
            with patch("sys.argv", ["text_gate", "--repo-root", str(root)]):
                with patch.object(text_gate, "_git", wraps=text_gate._git) as git_calls:
                    with self.assertRaisesRegex(SystemExit, "bad.json"):
                        text_gate.main()
                    self.assertEqual(git_calls.call_count, 2)
                (root / "bad.json").write_bytes(b"{}\n")
                output = StringIO()
                with patch.object(text_gate, "_git", wraps=text_gate._git) as git_calls:
                    with redirect_stdout(output):
                        text_gate.main()
                    self.assertEqual(git_calls.call_count, 2)
                self.assertEqual(output.getvalue(), "REPOSITORY_TEXT_BYTES=PASS FILES=2\n")


if __name__ == "__main__":
    unittest.main()

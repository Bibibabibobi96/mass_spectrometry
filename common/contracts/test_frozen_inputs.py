"""Raw-byte freezing and failure boundaries, without solver payloads."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from common.contracts.frozen_inputs import freeze_file
from common.contracts.write_run_manifest import file_record


class FrozenInputTests(unittest.TestCase):
    def test_freezes_original_bytes_and_returns_destination_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source, target = (Path(directory)/name for name in ("source.json", "copy.json"))
            source.write_bytes(b'{"line":"raw"}\r\n')
            expected = file_record(source)
            frozen = freeze_file(source, target)
            self.assertEqual(target.read_bytes(), source.read_bytes())
            self.assertEqual(frozen, {**expected, "path": str(target.resolve()),
                                     "source_path": str(source.resolve())})
            with self.assertRaises(FileExistsError):
                freeze_file(source, target)
            self.assertEqual(target.read_bytes(), source.read_bytes())

    def test_missing_source_leaves_no_destination(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source, target = (Path(directory)/name for name in ("missing", "copy"))
            with self.assertRaises(FileNotFoundError):
                freeze_file(source, target)
            self.assertFalse(target.exists())

    def test_rejects_changed_bytes_during_copy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source, target = (Path(directory)/name for name in ("source", "copy"))
            source.write_bytes(b"original")

            def changing_copy(incoming: Path, outgoing: Path) -> None:
                incoming.write_bytes(b"modified")
                outgoing.write_bytes(incoming.read_bytes())

            with patch("common.contracts.frozen_inputs.shutil.copyfile", side_effect=changing_copy):
                with self.assertRaisesRegex(AssertionError, "frozen input SHA-256 changed"):
                    freeze_file(source, target)


if __name__ == "__main__":
    unittest.main()

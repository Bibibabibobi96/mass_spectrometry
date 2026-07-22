import tempfile
import unittest
from pathlib import Path

from artifact_project import ensure_artifact_project


class ArtifactProjectTests(unittest.TestCase):
    def test_index_is_created_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = ensure_artifact_project(root, "example_project")
            second = ensure_artifact_project(root, "example_project")
            self.assertEqual(first, second)
            self.assertTrue((first / "00_README.txt").read_text(encoding="utf-8").startswith("PROJECT: example_project\n"))

    def test_existing_different_identity_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "example_project"
            project.mkdir()
            (project / "00_README.txt").write_text("PROJECT: wrong_project\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "identity"):
                ensure_artifact_project(Path(directory), "example_project")


if __name__ == "__main__":
    unittest.main()

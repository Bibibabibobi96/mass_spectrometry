"""The public validator uses the selected Store without creating an execution."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from msplatform.cli import main
from msplatform.storage import ArtifactStore


class CliValidationTests(unittest.TestCase):
    def test_native_validation_passes_explicit_store_without_starting_run(self):
        recipe = Path(__file__).resolve().parents[2] / "src/msplatform/examples/oa_split_tof_native_small_v1.toml"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "selected-store"

            def admission(resolved, *, context, artifact_store):
                self.assertEqual(resolved["schema_version"], 2)
                self.assertIsNone(context)
                self.assertIsInstance(artifact_store, ArtifactStore)
                self.assertEqual(artifact_store.root, root.resolve())
                return {"native_verified": False}

            output = io.StringIO()
            with patch("msplatform.workflows.native_tracing.preflight_native", admission), redirect_stdout(output):
                self.assertEqual(main(["validate", str(recipe), "--artifact-root", str(root)]), 0)
            self.assertFalse(json.loads(output.getvalue())["capabilities"]["native_verified"])
            self.assertEqual(list((root / "work").iterdir()), [])
            self.assertEqual(list((root / "runs").iterdir()), [])

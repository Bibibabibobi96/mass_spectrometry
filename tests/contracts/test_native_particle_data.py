"""Synthetic format fixtures; they do not establish native execution evidence."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

from msplatform.recipes import load_recipe
from msplatform.results.model import TraceResult
from msplatform.results.particle_data import read_particle_data, write_particle_data
from msplatform.tracing import TraceResult as PublicTraceResult, trace_particles

ROOT = Path(__file__).resolve().parents[2]


class NativeParticleDataTests(unittest.TestCase):
    def result(self):
        recipe = load_recipe(ROOT / "recipes/reference/uniform_e.toml").to_dict()
        result = trace_particles(recipe)
        result.initial_states[0]["lineage_status"] = "primary_birth"
        metadata = dict(schema_version=2, initial_state_basis="native_birth_verified",
                        frame_id=recipe["frame_id"], clock=recipe["clock"])
        return result, metadata

    def test_version2_primary_birth_roundtrip_and_public_result_identity(self):
        self.assertIs(PublicTraceResult, TraceResult)
        result, metadata = self.result()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_particle_data(root, result, metadata=metadata)
            data = read_particle_data(root)
            self.assertEqual(data["schema_version"], 2)
            self.assertEqual(data["initial_states"], result.initial_states)
            self.assertEqual(data["terminal_states"], result.terminal_states)
            self.assertEqual(data["metadata"]["initial_state_basis"], "native_birth_verified")
            execution = json.loads((root / "execution.json").read_text())
            execution["schema_version"] = 1
            (root / "execution.json").write_text(json.dumps(execution))
            with self.assertRaisesRegex(ValueError, "versions disagree"):
                read_particle_data(root)

    def test_birth_cannot_be_asserted_as_legacy_snapshot_or_secondary_lineage(self):
        result, metadata = self.result()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, "birth provenance"):
                write_particle_data(root, result, metadata={k: v for k, v in metadata.items() if k != "initial_state_basis"})
            legacy = {k: v for k, v in metadata.items() if k not in {"schema_version", "initial_state_basis"}}
            write_particle_data(root, result, metadata=legacy)
            with self.assertRaisesRegex(ValueError, "lineage"):
                read_particle_data(root)
        invalid = copy.deepcopy(result)
        invalid.initial_states[0]["parent_particle_id"] = 44
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_particle_data(root, invalid, metadata=metadata)
            with self.assertRaisesRegex(ValueError, "lineage"):
                read_particle_data(root)


if __name__ == "__main__":
    unittest.main()

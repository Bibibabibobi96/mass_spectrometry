"""Synthetic format fixtures; they do not establish native execution evidence."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest
import h5py
import pyarrow.parquet as pq

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
                        frame_id=recipe["frame_id"], clock=recipe["clock"], species=recipe["species"])
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
            with self.assertRaisesRegex(ValueError, "historical read-only"):
                write_particle_data(root, result, metadata=legacy)
            # Synthetic historical fixture: preserve the old columns and identities;
            # this does not claim a native run or create a new v1 product via the API.
            write_particle_data(root, result, metadata=metadata)
            for kind in ("initial_states", "terminal_states", "events"):
                path = root / f"{kind}.parquet"
                table = pq.read_table(path)
                info = {"schema_version": 1, "frame_id": metadata["frame_id"],
                        "clock": metadata["clock"], "unit_system": "SI", "kind": kind}
                table = table.replace_schema_metadata({b"msplatform": json.dumps(info, sort_keys=True).encode()})
                pq.write_table(table, path)
            with h5py.File(root / "trajectories.h5", "r+") as stream:
                stream.attrs["msplatform"] = json.dumps({"schema_version": 1, "frame_id": metadata["frame_id"],
                    "clock": metadata["clock"], "unit_system": "SI"})
            execution_path = root / "execution.json"
            execution = json.loads(execution_path.read_text(encoding="utf-8"))
            execution["schema_version"] = 1
            execution_path.write_text(json.dumps(execution), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "lineage"):
                read_particle_data(root)
            initial_path = root / "initial_states.parquet"
            initial_table = pq.read_table(initial_path)
            initial_rows = initial_table.to_pylist()
            initial_rows[0]["lineage_status"] = "unavailable_initial_snapshot"
            import pyarrow as pa
            pq.write_table(pa.Table.from_pylist(initial_rows, schema=initial_table.schema), initial_path)
            self.assertEqual(read_particle_data(root)["metadata"]["species_status"], "kind_unrecorded")
        invalid = copy.deepcopy(result)
        invalid.initial_states[0]["parent_particle_id"] = 44
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_particle_data(root, invalid, metadata=metadata)
            with self.assertRaisesRegex(ValueError, "lineage"):
                read_particle_data(root)


if __name__ == "__main__":
    unittest.main()

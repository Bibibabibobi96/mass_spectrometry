"""Real reference pipeline: data fidelity, cache invalidation and retained evidence."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile
import unittest
from unittest.mock import patch

from msplatform.recipes import load_recipe
from msplatform.results.particle_data import read_particle_data, summarize_particle_data, write_particle_data
from msplatform.storage import ArtifactStore
from msplatform.tracing import trace_particles
from msplatform.workflows.reference_tracing import inspect_results, run_recipe

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "recipes/reference/uniform_e.toml"


class ReferenceWorkflowTests(unittest.TestCase):
    def test_author_snapshot_is_read_once_and_matches_computation_archive_and_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "author.toml"
            original = SOURCE.read_bytes()
            changed = original.replace(b"2000.0", b"4000.0")
            self.assertNotEqual(original, changed)
            source.write_bytes(original)
            read_bytes = Path.read_bytes
            reads = []

            def mutate_after_read(path):
                data = read_bytes(path)
                if path == source:
                    reads.append(data)
                    source.write_bytes(changed)
                return data

            with patch.object(Path, "read_bytes", mutate_after_read):
                first = run_recipe(source, artifact_root=base / "store")
            self.assertEqual(reads, [original])
            second = run_recipe(source, artifact_root=base / "store")
            times = []
            for run, snapshot, field in ((first, original, 2000.0), (second, changed, 4000.0)):
                work = Path(run["run_path"])
                self.assertEqual((work / "author.toml").read_bytes(), snapshot)
                self.assertEqual(run["provenance"]["author_sha256"], hashlib.sha256(snapshot).hexdigest().upper())
                resolved = json.loads((work / "resolved.json").read_text(encoding="utf-8"))
                self.assertEqual(resolved, load_recipe(work / "author.toml").to_dict())
                self.assertEqual(resolved["field_source"]["electric_field_v_m"][0], field)
                data = read_particle_data(work)
                initial, event = data["initial_states"][0], data["events"][0]
                acceleration = initial["charge_c"] * field / initial["mass_kg"]
                elapsed = event["time_s"] - initial["time_s"]
                expected = initial["position_m"][0] + initial["velocity_m_s"][0] * elapsed + 0.5 * acceleration * elapsed**2
                self.assertAlmostEqual(expected, resolved["surfaces"][0]["position_m"], delta=1e-10)
                times.append(elapsed)
            self.assertLess(times[1], times[0])
            self.assertFalse(second["provenance"]["field"]["reused"])

    def test_real_publication_reuse_local_recompute_and_gc(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            text = SOURCE.read_text(encoding="utf-8")
            particle = text[text.index("[[initial_states]]"):text.index("[numerics]")]
            text = text.replace("[numerics]", particle.replace("particle_id = 1", "particle_id = 9007199254740993") + "[numerics]")
            source = base / "input.toml"
            source.write_text(text, encoding="utf-8")
            root = base / "store"
            first = run_recipe(source, artifact_root=root, source_revision="b94e0818a4823102425b6ad77327106b07143250")
            self.assertEqual(first["summary"]["census"]["mother_count"], 2)
            self.assertEqual(first["run_state"]["execution_status"], "succeeded")
            self.assertEqual(first["run_state"]["publication_status"], "ready")
            self.assertEqual(first["provenance"]["repository_source"]["status"], "declared")
            second = run_recipe(source, artifact_root=root)
            self.assertTrue(all(b["reused"] for b in second["provenance"]["batches"]))
            self.assertEqual(second["provenance"]["repository_source"]["status"], "unavailable")
            self.assertNotEqual(first["run_id"], second["run_id"])
            source.write_text(text.replace("Uniform electric field", "Label only"), encoding="utf-8")
            label = run_recipe(source, artifact_root=root)
            self.assertTrue(all(b["reused"] for b in label["provenance"]["batches"]))
            store = ArtifactStore(root)
            batch = label["provenance"]["batches"][0]
            # Controlled loss of one disposable cache file; published evidence remains intact.
            with store.claim_key(batch["task_key"]) as hit:
                (hit[1] / "terminal_states.parquet").unlink()
            partial = run_recipe(source, artifact_root=root)
            self.assertEqual([b["reused"] for b in partial["provenance"]["batches"]], [False, True])
            self.assertTrue(partial["provenance"]["field"]["reused"])
            source.write_text(text.replace("2000.0", "2001.0"), encoding="utf-8")
            changed = run_recipe(source, artifact_root=root)
            self.assertFalse(changed["provenance"]["field"]["reused"])
            self.assertFalse(any(b["reused"] for b in changed["provenance"]["batches"]))
            # Watermark is a soft trigger: automatic collection precedes the next run.
            after_gc = run_recipe(source, artifact_root=root, high_water_bytes=0, low_water_bytes=0)
            self.assertFalse(after_gc["provenance"]["field"]["reused"])
            self.assertEqual(inspect_results(first["run_id"], artifact_root=root)["summary"], first["summary"])
            data = read_particle_data(Path(after_gc["run_path"]))
            self.assertEqual(data["initial_states"][1]["particle_id"], 9007199254740993)
            self.assertGreater(len(data["events"]), 0)
            self.assertEqual(data["trajectories"]["particle_id"].dtype.name, "int64")

    def test_negative_result_cancellation_and_failure_remain_distinct(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            text = SOURCE.read_text(encoding="utf-8")
            text = text.replace("position_m = 0.01", "position_m = 10.0")
            source = base / "input.toml"
            source.write_text(text, encoding="utf-8")
            root = base / "store"
            zero = run_recipe(source, artifact_root=root)
            self.assertEqual(zero["summary"]["execution_status"], "succeeded")
            self.assertEqual(zero["summary"]["arrival_analysis"]["status"], "not_applicable")
            self.assertEqual(zero["summary"]["stop_reasons"], {"time_limit": 1})
            cancelled = run_recipe(source, artifact_root=root, cancelled=lambda: True)
            self.assertEqual(cancelled["summary"]["execution_status"], "cancelled")
            self.assertEqual(cancelled["summary"]["missing_terminal_ids"], [1])
            # A solver-reported failure exercises the normal writer/reader, not a fake success chain.
            class Failure:
                success = False
                message = "controlled numerical failure diagnostic"
            with patch("msplatform.tracing.solve_ivp", return_value=Failure()):
                failed = run_recipe(source, artifact_root=root, cancelled=lambda: False)
            failure_data = read_particle_data(Path(failed["run_path"]))
            self.assertEqual(failed["summary"]["execution_status"], "failed")
            self.assertEqual(failure_data["terminal_states"][0]["detail"], Failure.message)
            self.assertIsNone(failure_data["terminal_states"][0]["native_entity_id"])
            self.assertIn("scipy_", failure_data["terminal_states"][0]["backend_version"])
            incomplete = copy.deepcopy(failure_data)
            incomplete["terminal_states"] = []
            self.assertEqual(summarize_particle_data(incomplete)["census"]["counts"]["missing_record"], 1)
            source.write_text(text.replace("2000.0", "1e308"), encoding="utf-8")
            overflow = run_recipe(source, artifact_root=root)
            self.assertEqual(overflow["run_state"]["execution_status"], "failed")
            self.assertEqual(overflow["summary"]["stop_reasons"], {"numerical_failure": 1})
            self.assertIn("overflow", read_particle_data(Path(overflow["run_path"]))["terminal_states"][0]["detail"])

    def test_unknown_result_fields_and_modified_evidence_fail_closed(self):
        recipe = load_recipe(SOURCE).to_dict()
        result = trace_particles(recipe)
        result.terminal_states[0]["unrecognized_critical_fact"] = "must not disappear"
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            with self.assertRaisesRegex(ValueError, "silent data loss"):
                write_particle_data(base, result, metadata={"frame_id": recipe["frame_id"], "clock": recipe["clock"]})
            run = run_recipe(SOURCE, artifact_root=base / "store")
            path = Path(run["run_path"]) / "summary.json"
            path.write_text(json.dumps({}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "incomplete or modified"):
                inspect_results(run["run_id"], artifact_root=base / "store")

    def test_cancellation_is_latched_across_complete_batches(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            text = SOURCE.read_text(encoding="utf-8")
            particle = text[text.index("[[initial_states]]"):text.index("[numerics]")]
            text = text.replace("[numerics]", particle.replace("particle_id = 1", "particle_id = 2") + "[numerics]")
            source = base / "recipe.toml"
            source.write_text(text, encoding="utf-8")
            pulses = iter([True, False, False])
            run = run_recipe(source, artifact_root=base / "store", cancelled=lambda: next(pulses))
            records = read_particle_data(Path(run["run_path"]))["terminal_states"]
            self.assertEqual([row["started"] for row in records], [False, False])
            self.assertEqual(run["summary"]["missing_terminal_ids"], [1, 2])

    def test_physical_admission_preserves_queued_identity_and_frozen_input(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "store"
            # Request more than the actual free space, without filling a real disk.
            with self.assertRaises(OSError) as caught:
                run_recipe(SOURCE, artifact_root=root, reserve_bytes=shutil.disk_usage(base).free + 1)
            run_id = re.search(r"run ([a-f0-9]{32}):", str(caught.exception)).group(1)
            result = inspect_results(run_id, artifact_root=root)
            self.assertEqual(result["run_state"]["execution_status"], "queued")
            self.assertIn("insufficient physical", result["run_state"]["reason"])
            self.assertIsNone(result["summary"])


if __name__ == "__main__":
    unittest.main()

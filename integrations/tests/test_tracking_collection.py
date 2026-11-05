"""Installed collector parses the existing wire without source loaders or tools."""
from __future__ import annotations

import copy
import math
from pathlib import Path
import tempfile
import unittest

from msplatform.backends.simion import tracking_collection as collection
from msplatform.contracts.particle_state import binary64_serialization_close


class TrackingCollectionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.log = Path(self.temporary.name) / "native.log"
        self.source = {41: dict(particle_id="41", instrument_time_us="7", mass_amu="100",
            position_x_mm="2", position_y_mm="3", position_z_mm="4",
            velocity_x_m_s="1000", velocity_y_m_s="2000", velocity_z_m_s="3000")}
        state = "x_mm=2 y_mm=3 z_mm=4 vx_mm_per_us=1 vy_mm_per_us=2 vz_mm_per_us=3"
        self.lines = [f"TRACE: source_release ion=1 particle_id=41 instrument_time_us=7 {state}",
            f"TRACE: handoff_terminal_raw ion=1 instance=3 instrument_time_us=8 {state}",
            "TRACE: non_detector_splat ion=1 instance=3 t=8 x=2 y=3 z=4 zmax=4",
            "status,Fly completed. 1 splats"]
        self.batch = dict(source_row_range=[1, 1], expected_particle_ids=[41], build_metadata={})

    def collect(self, *, provenance=None):
        self.log.write_text("\n".join(self.lines) + "\n", encoding="utf-8")
        return collection.collect_tracking_logs([self.log], source_rows=self.source,
            source_provenance=provenance or {}, flight={"pulse": {"mode": "held_off"}},
            batches=[self.batch])

    def test_direct_sparse_state_collection_preserves_raw_velocity_and_full_mother(self):
        provenance = dict(schema_version=2, mother_particle_ids=[41, 99],
            mother_records=[{"particle_id": 41, "weight": 2, "particle_birth_time_us": 1},
                            {"particle_id": 99, "weight": 3, "particle_birth_time_us": 2}],
            mother_fates={"99": "unknown"}, clock_authority_sha256="A" * 64,
            clock_records={"clock_authority": {"sha256": "A" * 64}})
        original = copy.deepcopy((self.source, provenance, self.batch))
        result = self.collect(provenance=provenance)
        self.assertEqual(result["census"]["census"]["launched"], 1)
        self.assertEqual(result["native_terminals"][0]["particle_id"], 41)
        self.assertEqual(result["native_terminals"][0]["vx_mm_per_us"], 1)
        self.assertEqual(result["canonical_events"][0]["instrument_time_us"], 7)
        self.assertEqual(result["original_mother"]["mother_records"], provenance["mother_records"])
        self.assertEqual(result["original_mother"]["mother_fates"], {"99": "unknown"})
        self.assertEqual((self.source, provenance, self.batch), original)
        self.assertFalse(result["census"]["formal_gate_passed"])

    def test_original_completion_and_per_id_terminal_are_mandatory(self):
        with self.subTest("missing native completion"):
            self.lines.pop()
            with self.assertRaisesRegex(ValueError, "completion sentinel"):
                self.collect()
        with self.subTest("missing raw terminal"):
            self.lines.append("status,Fly completed. 1 splats")
            self.lines = [line for line in self.lines if "handoff_terminal_raw" not in line]
            with self.assertRaisesRegex(ValueError, "raw terminal"):
                self.collect()

    def test_batch_and_source_birth_mismatch_rejected(self):
        with self.subTest("batch identity"):
            self.batch["expected_particle_ids"] = [99]
            with self.assertRaisesRegex(ValueError, "source-row binding"):
                self.collect()
        with self.subTest("actual source state"):
            self.batch["expected_particle_ids"] = [41]
            self.lines[0] = self.lines[0].replace("vx_mm_per_us=1", "vx_mm_per_us=9")
            with self.assertRaisesRegex(ValueError, "actual birth differs"):
                self.collect()

    def test_legacy_census_is_same_canonical_module(self):
        from integrations.workflows.single_reflection_flight import census
        self.assertIs(census, collection)
        self.assertEqual(Path(collection.__file__).resolve().parts[-5:],
                         ("src", "msplatform", "backends", "simion", "tracking_collection.py"))

    def test_serialization_boundary_is_unchanged_and_not_cross_run_tolerance(self):
        self.assertTrue(binary64_serialization_close(1., 1. + 32 * math.ulp(1.)))
        self.assertFalse(binary64_serialization_close(1., 1. + 33 * math.ulp(1.)))
        self.assertTrue(binary64_serialization_close(-1., -1. - 32 * math.ulp(1.)))
        self.assertFalse(binary64_serialization_close(0., 33 * math.ulp(1.)))

from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from common.contracts.file_identity import file_sha256
from common.contracts.particle_state import PARTICLE_STATE_COLUMNS
from common.simion.finalize_completed_batches import finalize_completed_batches
from common.simion.particle_batching import plan_single_wave_batches


class FinalizeCompletedBatchesTest(unittest.TestCase):
    def _write_state(self, path: Path, count: int) -> None:
        rows = []
        for particle_id in range(1, count + 1):
            for event, status, z in (("source", "alive", 0.0), ("terminal", "timeout", 1.0)):
                row = {name: "0" for name in PARTICLE_STATE_COLUMNS}
                row.update(particle_id=str(particle_id), event=event, status=status, terminal_reason="timeout",
                           axial_z_mm=str(z), kinetic_energy_eV="0", radial_position_mm="0")
                rows.append(row)
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=PARTICLE_STATE_COLUMNS)
            writer.writeheader(); writer.writerows(rows)

    def _fixture(self, root: Path) -> tuple[Path, Path]:
        parent = root / "parent"; results = parent / "results"; inputs = parent / "inputs"
        results.mkdir(parents=True); inputs.mkdir()
        source = inputs / "source.csv"
        source.write_text("particle_id,birth_time_s,mass_amu,x_mm,y_mm,z_mm,vx_m_s,vy_m_s,vz_m_s\n1,0,1,0,0,0,0,0,0\n2,0,1,0,0,0,0,0,0\n", encoding="utf-8")
        plan_path = inputs / "simion_execution_batch_plan.json"; plan_path.write_text(json.dumps(plan_single_wave_batches(2, 2)), encoding="utf-8")
        metadata = inputs / "particle_source_metadata.json"; metadata.write_text("{\"role\": \"fixture\"}\n", encoding="utf-8")
        design = inputs / "multipole_resolved_design.json"; design.write_text("{\"role\": \"fixture\"}\n", encoding="utf-8")
        outputs = []
        for index in (1, 2):
            state = results / f"particle_states__case__batch_{index:02d}.csv"; self._write_state(state, 1)
            summary = results / f"simion_summary__case__batch_{index:02d}.json"
            summary.write_text(json.dumps({"solver":"SIMION", "mode":"m", "operating_point":"p", "parent_resolved_design_sha256":"x", "particles":1, "census_plane_crossings":0, "hits":0}), encoding="utf-8")
            outputs.extend(({"path":str(state.resolve()),"exists":True,"sha256":file_sha256(state)}, {"path":str(summary.resolve()),"exists":True,"sha256":file_sha256(summary)}))
        config = {"run_id":"20260820_000000__sim__simion__fixture__n2", "project":"fixture", "parameters":{"design_profile_id":"fixture"}, "inputs":{"simion_execution_batch_plan":str(plan_path.resolve()), "particle_source_metadata":str(metadata.resolve()), "multipole_resolved_design":str(design.resolve())}}
        (parent / "run_config.json").write_text(json.dumps(config), encoding="utf-8")
        manifest = {"run_id":config["run_id"], "status":"failed", "inputs":{"simion_execution_batch_plan":{"path":str(plan_path.resolve()),"exists":True,"sha256":file_sha256(plan_path)}, "particle_source":{"path":str(source.resolve()),"exists":True,"sha256":file_sha256(source)}, "particle_source_metadata":{"path":str(metadata.resolve()),"exists":True,"sha256":file_sha256(metadata)}, "multipole_resolved_design":{"path":str(design.resolve()),"exists":True,"sha256":file_sha256(design)}}, "outputs":outputs}
        (parent / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return parent, source

    def test_finalizes_immutable_batches_into_child(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            parent, source = self._fixture(Path(temp))
            manifest = finalize_completed_batches(
                parent, Path(temp) / "20260820_000100__sim__simion__fixture-recovery__n2",
                "case", source, 1, 0, 1, 1,
            )
            document = json.loads(manifest.read_text())
            self.assertEqual(document["status"], "success")
            self.assertEqual(document["inputs"]["particle_source"]["sha256"], file_sha256(source))
            self.assertIn("particle_source_metadata", document["inputs"])
            self.assertIn("multipole_resolved_design", document["inputs"])
            self.assertTrue((parent / "run_manifest.json").is_file())

    def test_rejects_tampered_raw_batch(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            parent, source = self._fixture(Path(temp))
            with (parent / "results" / "particle_states__case__batch_01.csv").open("a", encoding="utf-8") as stream:
                stream.write("tamper")
            with self.assertRaisesRegex(ValueError, "hash differs"):
                finalize_completed_batches(
                    parent, Path(temp) / "20260820_000100__sim__simion__fixture-recovery__n2",
                    "case", source, 1, 0, 1, 1,
                )

import csv
import json
import tempfile
import unittest
from pathlib import Path

from projects.rf_quadrupole_collision_cooling.analysis import analyze_s3_end_to_end as analyze
from projects.rf_quadrupole_collision_cooling.analysis import build_simion_input_from_canonical as adapter
from projects.rf_quadrupole_collision_cooling.analysis.build_oatof_handoff import CANONICAL_COLUMNS


def canonical_row(particle_id: int) -> dict[str, object]:
    return {
        "particle_id": particle_id, "parent_particle_id": "", "generation": 0,
        "source_component_id": "s3", "target_component_id": "oatof_analyzer",
        "state_event": "local_accelerator_exit", "frame_id": "oatof_global",
        "clock_epoch_id": "instrument_clock_epoch.v1", "instrument_time_us": 36.75,
        "lineage_age_us": 36.0, "particle_age_us": 36.0,
        "last_component_elapsed_time_us": 7.0, "lineage_birth_time_us": 0.75,
        "particle_birth_time_us": 0.75, "mass_to_charge_Th": 100,
        "mass_amu": 100, "charge_state": 1, "position_x_mm": -47,
        "position_y_mm": 0.2, "position_z_mm": 4.87, "velocity_x_m_s": 4000,
        "velocity_y_m_s": 300, "velocity_z_m_s": 58000,
        "kinetic_energy_eV": 1750, "source_rf_phase_rad": 2.7,
    }


def write_csv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)


class S3EndToEndTests(unittest.TestCase):
    def test_canonical_adapter_preserves_state_and_clock(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); source = root / "source.csv"
            write_csv(source, CANONICAL_COLUMNS, [canonical_row(8), canonical_row(2)])
            canonical = root / "canonical.csv"; ion = root / "input.ion"
            mapping = root / "map.csv"; metadata = root / "metadata.json"
            result = adapter.build(source, canonical, ion, mapping, metadata)
            self.assertEqual(result["particles"], 2)
            self.assertFalse(result["transform"]["position_projection_applied"])
            self.assertTrue(ion.read_text(encoding="utf-8").splitlines()[0].startswith(
                "36.75,100,1,-47,0.2,4.87,"))
            with mapping.open(encoding="utf-8") as handle:
                self.assertEqual(list(csv.DictReader(handle))[0]["particle_id"], "2")

    def test_s3_audit_requires_identity_clock_and_pulse(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); canonical = root / "canonical.csv"
            write_csv(canonical, CANONICAL_COLUMNS, [canonical_row(2)])
            ion = root / "input.ion"; mapping = root / "map.csv"; metadata = root / "meta.json"
            adapter.build(canonical, root / "copy.csv", ion, mapping, metadata)
            summary = root / "summary.json"
            summary.write_text(json.dumps({"status": "success", "source_particles": 100,
                                           "oatof_entry_crossings": 61,
                                           "active_at_pulse": 31}), encoding="utf-8")
            downstream = root / "downstream.csv"
            fields = ["Ion", "X0Mm", "Y0Mm", "Z0Mm", "TofUs", "InstrumentTimeUs", "XMm", "YMm", "Hit"]
            write_csv(downstream, fields, [{"Ion": 1, "X0Mm": -47, "Y0Mm": 0.2,
                                            "Z0Mm": 4.87, "TofUs": 10,
                                            "InstrumentTimeUs": 46.75, "XMm": 0,
                                            "YMm": 0, "Hit": "True"}])
            stdout = root / "stdout.log"
            stdout.write_text(
                "handoff_pulse_contract mode=1 time_us=36.112 width_us=1\n", encoding="utf-8")
            result = analyze.analyze(
                summary, canonical, ion, mapping, downstream, stdout, 36.112, 1.0)
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["census"]["detector_hit"], 1)
            self.assertFalse(result["s3_stage_passed"])


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "analysis"))
import build_s1_downstream_handoff as module  # noqa: E402


class S1DownstreamHandoffTests(unittest.TestCase):
    def test_preserves_exit_position_time_and_identity(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            entry = root / "entry.csv"
            events = root / "events.csv"
            fields = module.CANONICAL_COLUMNS
            row = {field: "" for field in fields}
            row.update({
                "particle_id": "7", "generation": "0", "frame_id": "instrument_global",
                "clock_epoch_id": "epoch", "instrument_time_us": "10", "lineage_age_us": "8",
                "particle_age_us": "8", "lineage_birth_time_us": "2", "particle_birth_time_us": "2",
                "mass_to_charge_Th": "100", "mass_amu": "100", "charge_state": "1",
            })
            module.write_csv(entry, fields, [row])
            event_fields = ["particle_id", "event", "status", "instrument_time_us", "x_mm", "y_mm",
                            "z_mm", "vx_m_s", "vy_m_s", "vz_m_s", "kinetic_energy_eV", "rf_phase_rad"]
            speed = 1000.0
            energy = 0.5 * 100 * module.ATOMIC_MASS_KG * speed**2 / module.ELEMENTARY_CHARGE_C
            module.write_csv(events, event_fields, [{
                "particle_id": 7, "event": "local_joint_exit", "status": "transmitted",
                "instrument_time_us": 12.5, "x_mm": -47.2, "y_mm": 0.3, "z_mm": 4.87,
                "vx_m_s": 0, "vy_m_s": 0, "vz_m_s": speed,
                "kinetic_energy_eV": energy, "rf_phase_rad": 1.2,
            }])
            canonical, ion, mapping, metadata = (root / name for name in
                                                   ("canonical.csv", "particles.ion", "map.csv", "meta.json"))
            result = module.build(events, entry, canonical, ion, mapping, metadata)
            self.assertEqual(result["particles"], 1)
            with canonical.open(encoding="utf-8", newline="") as handle:
                output = next(csv.DictReader(handle))
            self.assertEqual(float(output["position_x_mm"]), -47.2)
            self.assertEqual(float(output["instrument_time_us"]), 12.5)
            self.assertEqual(float(output["last_component_elapsed_time_us"]), 2.5)
            values = ion.read_text(encoding="utf-8").strip().split(",")
            self.assertEqual(float(values[0]), 12.5)
            self.assertEqual(float(values[3]), -47.2)
            self.assertAlmostEqual(float(values[6]), -90.0)
            self.assertAlmostEqual(float(values[7]), 0.0)


if __name__ == "__main__":
    unittest.main()

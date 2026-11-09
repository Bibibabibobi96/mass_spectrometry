from __future__ import annotations

import unittest
import csv
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from msplatform.backends.simion.source import project_direct_velocity, render_source_states, render_standard_beams


class StandardBeamTests(unittest.TestCase):
    def test_direct_velocity_projection_preserves_six_dimensions_and_target_frame(self) -> None:
        state, beam = project_direct_velocity(particle_id=7, time_us=12.5, position_mm=[1., 2., 3.],
            velocity_m_s=[100., -200., 300.], energy_ev=4., mass_amu=524., charge_state=1,
            beam_position_mm=[8., 9., 10.], beam_direction=[-200., 300., 100.], weight=3.5, color=0)
        self.assertEqual(state, dict(particle_id=7, t=12.5, x=1., y=2., z=3., vx=.1, vy=-.2, vz=.3, ke=4.))
        self.assertEqual(beam["direction"], [-200., 300., 100.])
        self.assertEqual((beam["x"], beam["y"], beam["z"], beam["cwf"]), (8., 9., 10., 3.5))
        self.assertIn("direction = vector(-200.0,300.0,100.0)", render_standard_beams([beam]))

    def test_source_state_precision_default_is_legacy_and_17_roundtrips(self) -> None:
        value = 1.2345678901234567
        state = dict(particle_id=7, t=value, x=value, y=value, z=value, vx=value, vy=value, vz=value, ke=value)
        legacy = render_source_states([state])
        self.assertEqual(legacy, "return {\n  [7]={t=1.23456789012346,x=1.23456789012346,y=1.23456789012346,z=1.23456789012346,vx=1.23456789012346,vy=1.23456789012346,vz=1.23456789012346,ke=1.23456789012346},\n}\n")
        precise = render_source_states([state], significant_digits=17)
        self.assertIn(f"x={value!r}", precise)

    def test_source_state_precision_rejects_unsupported_values(self) -> None:
        for value in (True, 16, 0, "17", 17.0):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "15 or 17"):
                render_source_states([], significant_digits=value)

    def test_legacy_angles_remain_byte_stable(self) -> None:
        source = render_standard_beams(
            [{
                "tob": 0, "mass": 100, "charge": 1,
                "x": 1, "y": 2, "z": 3, "ke": 4,
                "az": 5, "el": 6, "cwf": 1, "color": 2,
            }]
        )
        self.assertIn("    x = 1,\n    y = 2,\n    z = 3,", source)
        self.assertIn("    az = 5,\n    el = 6,", source)
        self.assertNotIn("direction = vector", source)

    def test_explicit_direction_uses_simion_vector_form(self) -> None:
        source = render_standard_beams(
            [{
                "tob": 0, "mass": 500, "charge": 1,
                "x": 25.5, "y": 25.5, "z": 1,
                "direction": (0, 0, 20), "ke": 0.001,
                "cwf": 1, "color": 3,
            }]
        )
        self.assertIn("position = vector(25.5,25.5,1)", source)
        self.assertIn("direction = vector(0,0,20)", source)
        self.assertNotIn("    az =", source)

    def test_direction_must_be_three_dimensional(self) -> None:
        with self.assertRaisesRegex(ValueError, "three components"):
            render_standard_beams(
                [{
                    "tob": 0, "mass": 500, "charge": 1,
                    "x": 0, "y": 0, "z": 0, "direction": (0, 1),
                    "ke": 1, "cwf": 1, "color": 1,
                }]
            )


class InitialStateRecordTests(unittest.TestCase):
    def test_bom_sparse_ids_and_per_row_clocks_velocities_preserve_input(self):
        from msplatform.backends.simion.source import load_initial_state
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "explicit.csv"
            for id_column in ("particle_id", "simulation_particle_id"):
                with self.subTest(id_column=id_column):
                    path.write_text(id_column + ",instrument_time_us,velocity_x_m_s,velocity_y_m_s,velocity_z_m_s,unused\n"
                                    "37,0,1000,-250,0,kept\n7,12.5,-125,2000,3.5,kept\n", encoding="utf-8-sig")
                    original = path.read_bytes()
                    self.assertEqual(load_initial_state(path), ([0., 12.5], [37, 7], [[1., -.25, 0.], [-.125, 2., .0035]]))
                    self.assertEqual(path.read_bytes(), original)

    def test_original_empty_id_clock_velocity_and_missing_field_errors(self):
        from msplatform.backends.simion.source import load_initial_state
        fields = ["particle_id", "instrument_time_us", "velocity_x_m_s", "velocity_y_m_s", "velocity_z_m_s"]
        cases = [([], ValueError, "initial state is empty"),
                 ([[0, 0, 1, 2, 3]], ValueError, "unique and positive"),
                 ([[7, 0, 1, 2, 3], [7, 1, 4, 5, 6]], ValueError, "unique and positive"),
                 ([[7, -1, 1, 2, 3]], ValueError, "birth times must be non-negative"),
                 ([[7, "nan", 1, 2, 3]], ValueError, "birth times must be non-negative"),
                 ([[7, 0, "inf", 2, 3]], ValueError, "initial velocities must be finite"),
                 ([["7.0", 0, 1, 2, 3]], ValueError, "invalid literal")]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "explicit.csv"
            for rows, error, message in cases:
                with self.subTest(rows=rows):
                    with path.open("w", encoding="utf-8", newline="") as handle:
                        writer = csv.writer(handle); writer.writerow(fields); writer.writerows(rows)
                    original = path.read_bytes()
                    with self.assertRaisesRegex(error, message):
                        load_initial_state(path)
                    self.assertEqual(path.read_bytes(), original)
            path.write_text("particle_id,instrument_time_us\n7,1\n", encoding="utf-8")
            with self.assertRaisesRegex(KeyError, "velocity_x_m_s"):
                load_initial_state(path)

    def test_cold_source_owner_and_missing_module_never_use_author_checkout(self):
        import msplatform.backends.simion.source as source
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = Path(source.__file__).resolve().parents[2]
            shutil.copytree(package, root / "msplatform", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            record = root / "state.csv"
            record.write_text("particle_id,instrument_time_us,velocity_x_m_s,velocity_y_m_s,velocity_z_m_s\n"
                              "91,3.25,-1000,250,0\n", encoding="utf-8")
            code = """import json,sys
from pathlib import Path
root=Path(sys.argv[1]);sys.path[:0]=[str(root),*json.loads(sys.argv[2])]
from msplatform.backends.simion.source import load_initial_state
assert Path(sys.modules[load_initial_state.__module__].__file__).resolve().is_relative_to(root)
assert load_initial_state(root/'state.csv')==([3.25],[91],[[-1.,.25,0.]])
assert not any(k.split('.')[0] in {'common','integrations','projects'} for k in sys.modules)
print(json.dumps({'origin':load_initial_state.__module__,'status':'PASS'}))
"""
            command = [sys.executable, "-I", "-S", "-B", "-c", code, str(root), json.dumps([p for p in sys.path if Path(p).name == "site-packages"])]
            result = subprocess.run(command, cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(json.loads(result.stdout)["origin"], "msplatform.backends.simion.source")
            target = root / "msplatform/backends/simion/source.py"
            original = hashlib.sha256(target.read_bytes()).hexdigest()
            hidden = target.with_suffix(".missing")
            target.rename(hidden)
            try:
                missing = subprocess.run(command, cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=30)
                self.assertNotEqual(missing.returncode, 0)
                self.assertIn("msplatform.backends.simion.source", missing.stderr)
            finally:
                hidden.rename(target)
            self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(), original)


if __name__ == "__main__":
    unittest.main()

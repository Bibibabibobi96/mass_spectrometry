"""Contracts for trajectory and strict static vector-field comparison inputs."""

from __future__ import annotations

import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd
from PIL import Image

from projects.single_reflection_oa_tof_mass_analyzer.analysis import compare_vector_field_samples as comparison
from projects.single_reflection_oa_tof_mass_analyzer.analysis.compare_vector_field_samples import (
    main,
)


class CompareVectorFieldSamplesTests(unittest.TestCase):
    def test_cli_round_trips_equivalent_decimal_coordinates_but_rejects_one_ulp(self) -> None:
        pairs = [('89.94434260835371', '89.944342608353708'),
                 ('201.4266955495302', '201.42669554953019')]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            c, s, out = root/'comsol.csv', root/'simion.csv', root/'out'
            header = 'point_id,x_mm,y_mm,z_mm,Ex_V_per_m,Ey_V_per_m,Ez_V_per_m\n'
            c.write_text(header + ''.join(f'{i},{a},0,0,1,2,3\n' for i, (a, _) in enumerate(pairs)), encoding='utf-8')
            s.write_text(header + ''.join(f'{i},{b},0,0,1,2,3\n' for i, (_, b) in enumerate(pairs)), encoding='utf-8')
            for a, b in pairs:
                self.assertEqual(float(a), float(b))
            command = [sys.executable, '-B', '-m', comparison.__name__, str(c), str(s), '--output', str(out)]
            result = subprocess.run(command, cwd=Path(__file__).resolve().parents[4], capture_output=True,
                                    text=True, encoding='utf-8', timeout=60, check=False)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            metrics = json.loads((out/'accelerator_vector_field_metrics.json').read_text())
            self.assertEqual(metrics['sample_points'], 2)
            self.assertEqual(metrics['aggregate']['Ex']['difference_max_abs_V_per_m'], 0.)
            merged = pd.read_csv(out/'accelerator_vector_field_comparison.csv', float_precision='round_trip')
            self.assertEqual(list(merged.x_mm), [float(a) for a, _ in pairs])
            self.assertTrue((out/'accelerator_vector_field_comparison.png').is_file())
            changed = math.nextafter(float(pairs[0][0]), math.inf)
            self.assertNotEqual(changed, float(pairs[0][0]))
            s.write_text(header + f'0,{changed!r},0,0,1,2,3\n1,{pairs[1][1]},0,0,1,2,3\n', encoding='utf-8')
            result = subprocess.run(command, cwd=Path(__file__).resolve().parents[4], capture_output=True,
                                    text=True, encoding='utf-8', timeout=60, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('coverage differs', result.stderr)

    def test_hundreds_of_static_points_use_three_axes_without_losing_id_associations(self) -> None:
        count = 512
        identifiers = list(range(1000, 1000 + count))
        comsol = pd.DataFrame(dict(point_id=identifiers, x_mm=identifiers, y_mm=0., z_mm=1.,
            Ex_V_per_m=[value * 2. for value in identifiers],
            Ey_V_per_m=[value * 3. for value in identifiers],
            Ez_V_per_m=[value * 4. for value in identifiers]))
        simion = comsol.copy()
        simion['Ez_V_per_m'] += 2.
        figures = []
        subplots = comparison.plt.subplots
        def capture(*args, **kwargs):
            figure, axes = subplots(*args, **kwargs)
            figures.append(figure)
            return figure, axes
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            c, s, out = root/'comsol.csv', root/'simion.csv', root/'out'
            comsol.to_csv(c, index=False)
            simion.iloc[::-1].to_csv(s, index=False)
            with patch.object(sys, 'argv', ['compare', str(c), str(s), '--output', str(out)]), \
                    patch.object(comparison.plt, 'subplots', side_effect=capture):
                main()
            figure = figures[0]
            self.assertEqual(len(figure.axes), 3)
            self.assertEqual(tuple(figure.get_size_inches()), (8., 11.))
            for axis, component in zip(figure.axes, ('Ex', 'Ey', 'Ez'), strict=True):
                self.assertEqual(axis.get_xlabel(), 'point ID')
                self.assertEqual(axis.get_ylabel(), f'{component} [V/mm]')
                self.assertEqual([line.get_label() for line in axis.lines], ['COMSOL', 'SIMION'])
                for line, source in zip(axis.lines, (comsol, simion), strict=True):
                    self.assertEqual(list(line.get_xdata()), identifiers)
                    self.assertEqual(list(line.get_ydata()), list(source[f'{component}_V_per_m']/1000))
                    self.assertEqual(line.get_linestyle(), 'None')
            merged = pd.read_csv(out/'accelerator_vector_field_comparison.csv')
            self.assertEqual(len(merged), count)
            self.assertEqual(set(merged.point_id), set(identifiers))
            metrics = json.loads((out/'accelerator_vector_field_metrics.json').read_text())
            self.assertEqual(metrics['sample_points'], count)
            self.assertEqual(metrics['status'], 'COMPARISON_COMPLETE')
            self.assertEqual(metrics['aggregate']['Ez']['difference_rms_V_per_m'], 2.)
            self.assertEqual(metrics['display']['field_unit'], 'V/mm')
            with Image.open(out/'accelerator_vector_field_comparison.png') as image:
                description = json.loads(image.info['Description'])
                self.assertEqual(description['source_files'], {'COMSOL': str(c.resolve()), 'SIMION': str(s.resolve())})
                self.assertIn('No numerical-equivalence decision', description['claim_limit'])

    @staticmethod
    def _run(comsol: pd.DataFrame, simion: pd.DataFrame) -> dict:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            comsol_path, simion_path, output = root / "comsol.csv", root / "simion.csv", root / "out"
            comsol.to_csv(comsol_path, index=False)
            simion.to_csv(simion_path, index=False)
            with patch.object(sys, "argv", ["compare", str(comsol_path), str(simion_path), "--output", str(output)]):
                main()
            return json.loads((output / "accelerator_vector_field_metrics.json").read_text(encoding="utf-8"))

    def test_static_points_report_metrics_without_an_equivalence_pass_claim(self) -> None:
        comsol = pd.DataFrame(
            {
                "point_id": [2, 1],
                "x_mm": [2.0, 1.0],
                "y_mm": [0.0, 0.0],
                "z_mm": [3.0, 2.0],
                "Ex_V_per_m": [10.0, 20.0],
                "Ey_V_per_m": [0.0, 1.0],
                "Ez_V_per_m": [3.0, 4.0],
            }
        )
        simion = comsol.copy()
        simion["Ez_V_per_m"] += 2.0

        metrics = self._run(comsol, simion)

        self.assertEqual(metrics["status"], "COMPARISON_COMPLETE")
        self.assertEqual(metrics["sample_contract"], "static_point_id")
        self.assertIn("No numerical-equivalence decision", metrics["claim_limit"])
        self.assertEqual(metrics["sample_points"], 2)

    def test_static_rejects_duplicate_ids_invalid_ids_and_nonfinite_values(self) -> None:
        frame=pd.DataFrame(dict(point_id=[1,2],x_mm=[0.,1.],y_mm=[0.,0.],z_mm=[0.,0.],
            Ex_V_per_m=[1.,1.],Ey_V_per_m=[0.,0.],Ez_V_per_m=[0.,0.]))
        for column, values in (("point_id",[1,1]),("point_id",[-1,2]),("point_id",[1.5,2]),
                               ("x_mm",[float("nan"),1.]),("z_mm",[float("inf"),0.]),
                               ("Ex_V_per_m",[float("inf"),1.])):
            with self.subTest(column=column,values=values):
                invalid=frame.copy();invalid[column]=values
                with self.assertRaisesRegex(ValueError,"static"):
                    self._run(invalid,invalid.copy())

    def test_legacy_trajectory_contract_keeps_its_existing_status(self) -> None:
        frame = pd.DataFrame(
            {
                "particle_id": [4, 4],
                "time_us": [0.0, 1.0],
                "x_mm": [0.0, 0.0],
                "y_mm": [0.0, 0.0],
                "z_mm": [0.0, 1.0],
                "Ex_V_per_m": [1.0, 2.0],
                "Ey_V_per_m": [3.0, 4.0],
                "Ez_V_per_m": [5.0, 6.0],
            }
        )

        metrics = self._run(frame, frame.copy())

        self.assertEqual(metrics["status"], "PASS")
        self.assertEqual(metrics["sample_contract"], "trajectory")
        self.assertIn("4", metrics["particles"])

    def test_rejects_static_and_trajectory_contract_mix(self) -> None:
        static = pd.DataFrame(
            {
                "point_id": [1],
                "x_mm": [0.0],
                "y_mm": [0.0],
                "z_mm": [0.0],
                "Ex_V_per_m": [1.0],
                "Ey_V_per_m": [2.0],
                "Ez_V_per_m": [3.0],
            }
        )
        trajectory = pd.DataFrame(
            {
                "particle_id": [1],
                "time_us": [0.0],
                "x_mm": [0.0],
                "y_mm": [0.0],
                "z_mm": [0.0],
                "Ex_V_per_m": [1.0],
                "Ey_V_per_m": [2.0],
                "Ez_V_per_m": [3.0],
            }
        )

        with self.assertRaisesRegex(ValueError, "different contracts"):
            self._run(static, trajectory)


if __name__ == "__main__":
    unittest.main()

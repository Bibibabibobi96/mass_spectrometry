"""Dual-cone Program terminal codes in the actual trajectory projection."""
from __future__ import annotations
import csv
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from projects.dual_cone_tandem_quadrupole_ion_interface.analysis import plot_simion_trajectory_projection as projection


def write_rows(path, fields, rows):
    with path.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


class TrajectoryProjectionTests(unittest.TestCase):
    def test_reader_preserves_terminal_codes_and_missing_records(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'final.csv'
            write_rows(path, ('ion_number', 'splat'), [
                dict(ion_number=i, splat=code) for i, code in ((1,1),(2,0),(3,2),(4,3),(9,1))])
            groups, unsampled = projection.classify_terminal_states(path, {1,2,3,4,5})
            self.assertEqual(groups, dict(arrived={1}, unknown={2,5}, timeout={3}, coverage_loss={4}))
            self.assertEqual(unsampled, 1)
            self.assertEqual(set.union(*groups.values()), {1,2,3,4,5})
            for rows in ([dict(ion_number=1, splat=0), dict(ion_number=1, splat=1)],
                         [dict(ion_number=1, splat=4)]):
                write_rows(path, ('ion_number', 'splat'), rows)
                with self.assertRaises(ValueError):
                    projection.classify_terminal_states(path, {1})

    def test_actual_plot_and_cli_do_not_label_unknown_as_physical_loss(self):
        import matplotlib.axes
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            trajectory, final, image = root/'trajectory.csv', root/'final.csv', root/'projection.png'
            write_rows(trajectory, ('ion_number','x_mm','y_mm','z_mm'), [
                dict(ion_number=i, x_mm=25.5, y_mm=25.5, z_mm=2+i) for i in (1,2,3,4,5)])
            write_rows(final, ('ion_number','splat'), [
                dict(ion_number=i, splat=code) for i,code in ((1,1),(2,0),(3,2),(4,3),(9,1))])
            args = ['plot_simion_trajectory_projection.py', '--historical-translation-only',
                '--trajectory', str(trajectory), '--final-state', str(final), '--output', str(image)]
            titles, collections = [], []
            old_title, old_add = matplotlib.axes.Axes.set_title, matplotlib.axes.Axes.add_collection
            def capture_title(axis, label, *values, **kwargs):
                titles.append(label)
                return old_title(axis, label, *values, **kwargs)
            def capture_collection(axis, collection, *values, **kwargs):
                collections.append((collection.get_label(), len(collection.get_segments())))
                return old_add(axis, collection, *values, **kwargs)
            before = (trajectory.read_bytes(), final.read_bytes())
            with mock.patch.object(sys, 'argv', args), mock.patch.object(matplotlib.axes.Axes, 'set_title', capture_title), \
                 mock.patch.object(matplotlib.axes.Axes, 'add_collection', capture_collection):
                self.assertEqual(projection.main(), 0)
            self.assertEqual(collections[:4], [('terminal plane',1), ('unknown or missing final state',2),
                ('time limit',1), ('gas-support loss',1)])
            self.assertIn('terminal rows without tracks=1', titles[0])
            self.assertIn('physical wall loss is not separately identified', titles[0])
            self.assertEqual((trajectory.read_bytes(), final.read_bytes()), before)
            cli = subprocess.run([sys.executable, '-I', '-B', '-X', 'utf8', str(Path(projection.__file__)), *args[1:]],
                cwd=root, timeout=30, capture_output=True, text=True, encoding='utf-8', check=False)
            self.assertEqual(cli.returncode, 0, cli.stdout + cli.stderr)
            self.assertIn('SIMION_TRAJECTORY_PROJECTION=PASS', cli.stdout)
            self.assertTrue(image.is_file())
            self.assertEqual((trajectory.read_bytes(), final.read_bytes()), before)


if __name__ == '__main__':
    unittest.main()

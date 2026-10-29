import csv
import io
import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from common.contracts.write_run_manifest import file_record
from projects.rf_multipole_ion_optics.runtime.design_profile import resolve_design_profile
from projects.rf_multipole_ion_optics.runtime import run_round_rod_transport

ROOT = Path(__file__).resolve().parents[4]
PROJECT = ROOT / 'projects/rf_multipole_ion_optics'


class RoundRodBindingTest(unittest.TestCase):
    def test_verified_source_and_tampering(self):
        project = 'rf_multipole_ion_optics'
        run_id = '20260729_120001__test__python__field-screen-binding'
        design = resolve_design_profile(ROOT, project, 'hexapole_no_acceleration_full_length')['resolved_design']
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / project / 'runs' / run_id
            (source / 'inputs').mkdir(parents=True)
            (source / 'results').mkdir()
            design_path = source / 'inputs/multipole_resolved_design.json'
            design_path.write_text(json.dumps(design), encoding='utf-8')
            contract_path = source / 'inputs/round_rod_field_screen.json'
            contract_path.write_bytes((PROJECT / 'variants/hexapole/config/round_rod_field_screen.json').read_bytes())
            samples = source / 'results/round_rod_potential_samples.csv'
            contract = json.loads(contract_path.read_text(encoding='utf-8'))
            geometry = design['geometry_mm']
            rods = geometry['rod_array']['rods']
            gap = min(math.hypot(a['center_x_mm'] - b['center_x_mm'], a['center_y_mm'] - b['center_y_mm'])
                      - a['radius_mm'] - b['radius_mm'] for a, b in zip(rods, rods[1:] + rods[:1], strict=True))
            fields = ['rod_radius_ratio', 'rod_radius_mm', 'rod_center_radius_mm', 'adjacent_surface_gap_mm',
                      'sample_radius_mm', 'theta_rad', 'x_mm', 'y_mm', 'potential_V']
            rows = []
            for fraction in contract['sampling']['radius_fraction_of_r0']:
                radius = fraction * geometry['inscribed_radius_r0']
                for index in range(contract['sampling']['azimuth_samples_per_radius']):
                    theta = 2 * math.pi * index / contract['sampling']['azimuth_samples_per_radius']
                    rows.append(dict(zip(fields, [geometry['rod_radius_ratio'], geometry['rod_radius'],
                        geometry['rod_center_radius'], gap, radius, theta, radius * math.cos(theta),
                        radius * math.sin(theta), 100 * (radius / 4)**3 * math.cos(3 * theta)], strict=True)))
            def write_rows(items):
                output = io.StringIO(newline='')
                writer = csv.DictWriter(output, fieldnames=fields)
                writer.writeheader()
                writer.writerows(items)
                samples.write_text(output.getvalue(), encoding='utf-8')
            write_rows(rows)
            config = source / 'run_config.json'
            config.write_text(json.dumps({'run_id': run_id, 'project': project, 'mode': 'round_rod_field_screen'}), encoding='utf-8')
            manifest = {'status': 'success', 'run_id': run_id, 'project': project, 'mode': 'round_rod_field_screen',
                        'run_config': file_record(config), 'outputs': [file_record(path) for path in (design_path, contract_path, samples)]}
            (source / 'run_manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
            with patch.object(run_round_rod_transport, 'ARTIFACT_PROJECTS_ROOT', root):
                _, _, rows = run_round_rod_transport._load_source(project, run_id, expected_design=design)
                self.assertEqual(rows[0]['rod_radius_ratio'], '0.5')
                for key in ('rod_radius_mm', 'rod_center_radius_mm', 'adjacent_surface_gap_mm', 'x_mm', 'y_mm', 'theta_rad', 'sample_radius_mm', 'potential_V'):
                    damaged = [dict(row) for row in rows]
                    damaged[0][key] = 'nan' if key == 'potential_V' else '999'
                    with self.subTest(key=key), self.assertRaises(ValueError):
                        run_round_rod_transport._validated_selected_samples(damaged, contract, design)
                with self.assertRaisesRegex(ValueError, 'incomplete'):
                    run_round_rod_transport._validated_selected_samples(rows[:-1], contract, design)
                with self.assertRaisesRegex(ValueError, 'duplicate'):
                    run_round_rod_transport._validated_selected_samples(rows + rows[:1], contract, design)
                frozen = {}
                for name, path in (("field_screen_manifest", source / "run_manifest.json"),
                                   ("field_screen_design", design_path), ("field_screen_contract", contract_path),
                                   ("field_screen_samples", samples)):
                    frozen[name] = root / name
                    frozen[name].write_bytes(path.read_bytes())
                run_round_rod_transport._verify_frozen_source(frozen, source, manifest)
                frozen["field_screen_samples"].write_text('replaced', encoding='utf-8')
                with self.assertRaises(AssertionError):
                    run_round_rod_transport._verify_frozen_source(frozen, source, manifest)
                frozen["field_screen_manifest"].write_text('{}', encoding='utf-8')
                with self.assertRaisesRegex(ValueError, 'manifest changed'):
                    run_round_rod_transport._verify_frozen_source(frozen, source, manifest)
                samples.write_text('tampered', encoding='utf-8')
                with self.assertRaises((ValueError, AssertionError)):
                    run_round_rod_transport._load_source(project, run_id, expected_design=design)

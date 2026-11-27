"""A single field-intervention case retains declared controls and census."""
from pathlib import Path
import tempfile
import unittest

from msplatform.backends.simion.field_intervention import (
    analyze_field_intervention,
    build_field_intervention_argv,
    resolve_field_selector,
)


class FieldInterventionTests(unittest.TestCase):
    def test_declared_case_projects_existing_regional_controls_without_new_source(self):
        case = {'id': 'combined', 'selector': 'ideal:accel.ez+stage2.ez'}
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            particles, iob = root/'original.ion', root/'original.iob'
            argv = build_field_intervention_argv(case=case, particle_count=2,
                particle_table=particles, iob=iob, trajectory_quality=8)
            self.assertEqual(argv[argv.index('--particles')+1], str(particles))
            self.assertEqual(argv[-1], str(iob))
            self.assertEqual(argv.count('fly'), 1)
            for setting in ('ideal_accel_ez_enable=1', 'ideal_drift_ez_enable=0',
                            'ideal_refl_stage1_ez_enable=0', 'ideal_refl_stage2_ez_enable=1'):
                self.assertIn(setting, argv)
            self.assertFalse(particles.exists())
            self.assertFalse(iob.exists())
        self.assertEqual(resolve_field_selector('real'), {'A': 0, 'D': 0, 'S1': 0, 'S2': 0})
        self.assertEqual(resolve_field_selector('ideal:reflectron.ez'), {'A': 0, 'D': 0, 'S1': 1, 'S2': 1})
        for invalid in ('ideal:stage1.ex', 'ideal:unknown.ez', 'ideal:', 'other'):
            with self.subTest(selector=invalid), self.assertRaises(ValueError):
                resolve_field_selector(invalid)

    def test_complete_zero_hit_census_preserves_null_metrics_and_missing_rejects(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            ion, log = root/'source.ion', root/'flight.log'
            ion.write_text('0,524,1,0,0,0,0,0,5,1,0\n'*2, encoding='ascii')
            log.write_text(''.join(f'TRACE: detector_crossing ion={i} t=10 x=41 y=0 z=0 r=41 zmax=4\n'
                                   for i in (1, 2)), encoding='utf-8')
            args = dict(case={'id': 'zero_hit', 'selector': 'real'}, log=log,
                        particle_table=ion, particle_count=2, detector_radius_mm=40.)
            frame, summary = analyze_field_intervention(**args)
            self.assertEqual(frame['Ion'].tolist(), [1, 2])
            self.assertEqual((summary['Emitted'], summary['Hit']), (2, 0))
            self.assertEqual(summary['PeakStatus'], 'no_hits')
            self.assertIsNone(summary['MeanTofUs'])
            self.assertIsNone(summary['MaxHitRadiusMm'])
            with self.assertRaisesRegex(ValueError, 'particle count differs'):
                analyze_field_intervention(**{**args, 'particle_count': 3})
            log.write_text('TRACE: detector_crossing ion=1 t=10 x=41 y=0 z=0 r=41 zmax=4\n', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'Incomplete detector-plane census'):
                analyze_field_intervention(**args)


if __name__ == '__main__':
    unittest.main()

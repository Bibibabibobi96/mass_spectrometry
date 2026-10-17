"""Synthetic integration checks; no solver or physical qualification."""
import json
import unittest
from unittest.mock import patch
from matplotlib import pyplot as plt
from projects.dual_pressure_rectilinear_ion_processor.analysis import diagnostics as d
from projects.dual_pressure_rectilinear_ion_processor.tests import test_diagnostics as fixtures

class DefaultDiagnosticsIntegrationTests(unittest.TestCase):
    write_csv=staticmethod(fixtures.DiagnosticsTests.write_csv)
    def setUp(self):
        fixtures.DiagnosticsTests.setUp(self)
        (self.run/'inputs/source_context.json').write_text('{"sha":"synthetic"}',encoding='utf-8')
        self.output=self.run/'preview'
    def sections(self,run,out):
        self.assertTrue((out/'diagnostic_snapshots.csv').is_file())
        for role in ('structure_sections','timed_clouds_sections','extraction_clouds_sections'):
            for ext in ('png','svg','metadata.json'):(out/f'{role}.{ext}').write_text('{}',encoding='utf-8')
    def packet(self,run,out):
        for ext in ('png','svg','metadata.json'):(out/f'post_extraction_packet.{ext}').write_text('{}',encoding='utf-8')
        (out/'post_extraction_statistics.json').write_text(json.dumps({'status':'diagnostic_only','packet_status':'no_extracted_ions'}),encoding='utf-8')
        for name in ('plane','common_time'):(out/f'post_extraction_{name}_states.csv').write_text('particle_id\n',encoding='utf-8')
        return {'status':'diagnostic_only','packet_status':'no_extracted_ions'}
    def test_one_entry_and_physical_status(self):
        measured=self.run/'results/summary.json';measured.write_text('{"functional_status":"functional_incomplete"}',encoding='utf-8');before=measured.read_bytes()
        with patch.object(d,'build_figures',return_value={}) as build,patch.object(d,'export_sections',side_effect=self.sections) as sections,patch.object(d,'export_post_extraction',side_effect=self.packet) as packet:
            result=d.export_diagnostics(self.run,self.output)
            sections.assert_called_once_with(self.run,self.output);packet.assert_called_once_with(self.run,self.output)
            self.assertFalse(build.call_args.kwargs['include_projected_geometry'])
            self.assertEqual(result['post_extraction_status'],'no_extracted_ions');self.assertEqual(measured.read_bytes(),before)
            with self.assertRaises(FileExistsError):d.export_diagnostics(self.run,self.output)
    def test_missing_mandatory_output_fails(self):
        with patch.object(d,'build_figures',return_value={}),patch.object(d,'export_sections'),patch.object(d,'export_post_extraction'):
            with self.assertRaisesRegex(ValueError,'mandatory default diagnostic output missing'):d.export_diagnostics(self.run,self.output)
    def test_no_old_geometry_in_default_statistics(self):
        data=d.prepare_data(self.run);snapshots=[];counts=[]
        for label,time in data['snapshots']:
            count,states=d.census(data,time);counts.append(count);snapshots.extend(dict(snapshot=label,**state) for state in states)
        with patch.object(d,'add_geometry',side_effect=AssertionError('obsolete geometry')):
            figures=d.build_figures(data,snapshots,counts,include_projected_geometry=False)
        self.assertEqual(set(figures),{'stage_phase_space','cooling_stage_energy','population_evolution'})
        for fig in figures.values():plt.close(fig)
if __name__=='__main__':unittest.main()

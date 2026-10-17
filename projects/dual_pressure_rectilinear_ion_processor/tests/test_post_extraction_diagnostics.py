"""Lightweight regression of automatic observation time and honest empty diagnostics."""
import csv
import json
from pathlib import Path
import tempfile
import unittest

from projects.dual_pressure_rectilinear_ion_processor.analysis import post_extraction_diagnostics as m

def row(pid,t):
    return dict(particle_id=pid,t_us=t,x_mm=.1*pid,y_mm=170,z_mm=1-t,vx_mm_us=0,vy_mm_us=0,vz_mm_us=-1)

class AutomaticTimeTests(unittest.TestCase):
    def fixture(self,spacing=.005,shift=0):
        tracks={p:{t+shift:row(p,t+shift) for t in (.995-spacing,.995)} for p in (1,2)}
        crossings={1:row(1,1+shift),2:row(2,1.003+shift)}
        return tracks,crossings
    def test_time_translation(self):
        a=m.common_packet(*self.fixture(),.02)
        b=m.common_packet(*self.fixture(shift=200),.02)
        self.assertEqual(len(a[0]),2);self.assertEqual(len(b[0]),2)
        self.assertAlmostEqual(b[1]-a[1],200,places=10)
        self.assertEqual(a[2],'available');self.assertEqual(b[2],'available')
    def test_cadence_changes_observation_time(self):
        a=m.common_packet(*self.fixture(spacing=.005),.02)
        b=m.common_packet(*self.fixture(spacing=.002),.02)
        self.assertAlmostEqual(a[3]['first_arrival_margin_us'],.0025)
        self.assertAlmostEqual(b[3]['first_arrival_margin_us'],.001)
        self.assertNotEqual(a[1],b[1])
    def test_missing_records_are_explicit(self):
        result=m.common_packet({1:{}},{1:row(1,1)},.02)
        self.assertFalse(result[0]);self.assertIsNone(result[1]);self.assertIn('No valid',result[2])
    def test_wide_gap_refuses_fabricated_packet(self):
        result=m.common_packet(*self.fixture(spacing=.5),.02)
        self.assertFalse(result[0]);self.assertNotEqual(result[2],'available')
    def test_no_extraction_generates_complete_diagnostics(self):
        with tempfile.TemporaryDirectory(prefix='packet_empty_',) as temporary:
            run=Path(temporary)/'run';out=Path(temporary)/'out'
            for name in ('inputs','simion','results'):(run/name).mkdir(parents=True)
            (run/'inputs/resolved_model.json').write_text(json.dumps({'source':{'species':{'mass_amu':524}}}))
            (run/'inputs/diagnostics.json').write_text('{}')
            fields=['event','particle_id','reason','t_us',*m.VARS]
            with (run/'simion/events.csv').open('w',newline='') as stream:
                w=csv.DictWriter(stream,fieldnames=fields);w.writeheader()
                for event,reason,t in [('source','none',0),('terminal','timeout',20)]:
                    w.writerow(dict(event=event,reason=reason,particle_id=1,t_us=t,**{k:0 for k in m.VARS}))
            (run/'simion/samples.csv').write_text('particle_id,t_us\n')
            (run/'results/particle_state.csv').write_text('particle_id,event,status\n')
            result=m.export_post_extraction(run,out)
            self.assertEqual(result['packet_status'],'no_extracted_ions')
            self.assertEqual(len(list(out.iterdir())),6)
            for name in ('post_extraction_common_time_states.csv','post_extraction_plane_states.csv'):
                self.assertEqual(len((out/name).read_text().splitlines()),1)
            self.assertEqual(json.loads((out/'post_extraction_packet.metadata.json').read_text())['cohort']['extracted_count'],0)
            with self.assertRaises(FileExistsError):m.export_post_extraction(run,out)

if __name__=='__main__':unittest.main(verbosity=2)

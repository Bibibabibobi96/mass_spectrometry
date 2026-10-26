"""Mechanical pairing contracts; scientific validity belongs to consumers."""
import unittest

from common.analysis.particle_events import group_particle_events, iter_particle_event_fields


class ParticleEventTests(unittest.TestCase):
    def test_original_cohort_and_repeated_event_order_are_preserved(self):
        rows=[dict(particle_id=41,event='cross',x=1),dict(particle_id=7,event='birth',x=2),
              dict(particle_id=41,event='cross',x=3)]
        grouped=group_particle_events(iter(rows),[41,7])
        self.assertEqual(list(grouped),[41,7])
        self.assertEqual(grouped[41],[rows[0],rows[2]])
        self.assertIs(grouped[41][0],rows[0])

    def test_existing_csv_id_adapter_does_not_rewrite_records(self):
        row=dict(particle_id='41',event='birth')
        self.assertEqual(group_particle_events([row],[41],key=lambda r:int(r['particle_id'])),{41:[row]})
        self.assertEqual(row['particle_id'],'41')

    def test_unknown_id_is_not_silently_filtered(self):
        with self.assertRaises(KeyError):
            group_particle_events([dict(particle_id=7)],[41])

    def test_empty_events_have_no_invented_rows_or_acceptance(self):
        groups=group_particle_events([],[41,7])
        self.assertEqual(groups,{41:[],7:[]})
        self.assertEqual(list(iter_particle_event_fields(groups,groups,particle_ids=[41,7],fields=['event'])),[])

    def test_count_difference_precedes_original_event_and_explicit_field_order(self):
        a={41:[dict(event='birth',x=1),dict(event='stop',x=2)],7:[dict(event='birth',x=3)]}
        b={41:[dict(event='birth',x=4)],7:[dict(event='stop',x=5)]}
        self.assertEqual(list(iter_particle_event_fields(a,b,particle_ids=[41,7],fields=['x','event'])),[
            (41,-1,'event_count',2,1),(41,0,'x',1,4),(41,0,'event','birth','birth'),
            (7,0,'x',3,5),(7,0,'event','birth','stop')])

    def test_missing_declared_field_is_not_synthesized(self):
        with self.assertRaises(KeyError):
            list(iter_particle_event_fields({41:[{}]},{41:[{}]},particle_ids=[41],fields=['event']))


if __name__=='__main__':
    unittest.main()

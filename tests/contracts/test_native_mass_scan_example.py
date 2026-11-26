"""Public small-N mass scan input contract; no native result is asserted."""
import copy
import json
from pathlib import Path
import tomllib
import unittest

from msplatform.recipes import load_recipe
from msplatform.workflows.mass_scan import prepare_mass_scan
from msplatform.workflows.native_tracing import preflight_native


EXAMPLES = Path(__file__).resolve().parents[2]/'src/msplatform/examples'


class NativeMassScanExampleTests(unittest.TestCase):
    def test_original_science_and_recording_are_identical(self):
        original=json.loads((EXAMPLES/'oa_split_tof_native_small_v1.json').read_text(encoding='utf8'))
        example=json.loads((EXAMPLES/'oa_split_tof_mass_scan_small_v1.json').read_text(encoding='utf8'))
        scan=example.pop('release'); old_release=original.pop('release')
        self.assertEqual(example, original)
        self.assertEqual(scan['species_requests'][0],old_release)
        second=copy.deepcopy(scan['species_requests'][1])
        self.assertEqual(second['species_id'],'m100_charge2')
        self.assertEqual(second['release_spec']['particle_count'],2)
        self.assertEqual(second['release_spec']['species']['charge_state'],2)
        self.assertEqual(second['particle_ids'],[4,5])
        self.assertEqual(second['relative_weights'],{'4':.5,'5':.5})
        second['species_id']=old_release['species_id']
        second['release_spec']['particle_count']=old_release['release_spec']['particle_count']
        second['release_spec']['species']['charge_state']=old_release['release_spec']['species']['charge_state']
        second['particle_ids']=old_release['particle_ids']
        second['relative_weights']=old_release['relative_weights']
        self.assertEqual(second,old_release)
        first_toml=tomllib.loads((EXAMPLES/'oa_split_tof_native_small_v1.toml').read_text(encoding='utf8'))
        scan_toml=tomllib.loads((EXAMPLES/'oa_split_tof_mass_scan_small_v1.toml').read_text(encoding='utf8'))
        self.assertIn('mass_scan',scan_toml['label'])
        for value in (first_toml,scan_toml):
            value.pop('label');value.pop('study')
        self.assertEqual(first_toml,scan_toml)

    def test_public_preflight_and_complete_original_population(self):
        loaded=load_recipe(EXAMPLES/'oa_split_tof_mass_scan_small_v1.toml').to_dict()
        report=preflight_native(loaded)
        self.assertTrue(report['implemented'])
        self.assertFalse(report['native_verified'])
        requests=loaded['study']['document']['release']
        realization=prepare_mass_scan(requests)
        self.assertEqual([len(item.rows) for item in realization],[3,2])
        rows=[row for item in realization for row in item.rows]
        self.assertEqual([row['particle_id'] for row in rows],[1,2,3,4,5])
        self.assertEqual([row['charge_state'] for row in rows],[1,1,1,2,2])
        self.assertEqual({row['mass_amu'] for row in rows},{100.})
        self.assertEqual([row['particle_weight'] for row in rows],[1.,1.,1.,.5,.5])
        self.assertEqual([row['species_id'] for row in rows],['mz100_z1']*3+['m100_charge2']*2)
        self.assertEqual(len({row['clock_epoch_id'] for row in rows}),1)


if __name__ == '__main__': unittest.main()

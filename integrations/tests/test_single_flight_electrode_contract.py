"""Scientific RF voltage/probe adapters retain provider values and identities."""
from __future__ import annotations

import copy
import unittest
from unittest.mock import patch

from msplatform.backends.simion.electrode_contract import (
    physical_multipole_voltages, scientific_multipole_voltages, scientific_multipole_rod_pieces,
)
from projects.rf_multipole_ion_optics.core.compile_design_request import compile_design_request
from projects.rf_multipole_ion_optics.core.electrode_topology import build_electrode_topology
from projects.rf_multipole_ion_optics.tests.domain.test_capacity_contract_versions import request
from projects.rf_multipole_ion_optics.tests.domain.test_simion_geometry import resolved_design, shell


class SingleFlightElectrodeContractTests(unittest.TestCase):
    def test_continuous_common_dc_polarity_and_shell_are_hand_computable(self):
        source = resolved_design(shell())
        source['drive'].update(common_mode_offset_V=7., dc_amplitude_V_per_group=2.5,
                               frequency_Hz=1100000., phase_rad=.3)
        source['particle_source'] = dict(original_ids=[7,19], birth_time_s=[.1,.2])
        before = copy.deepcopy(source)
        mapping = dict(rod_group_1=23, rod_group_2=17, grounded_shell=31)
        with patch('msplatform.backends.simion.electrode_contract.physical_electrode_view',
                   side_effect=AssertionError('scientific path called legacy view')):
            carrier, groups = scientific_multipole_voltages(source, mapping)
        self.assertEqual(carrier, {23:9.5,17:4.5,31:0.})
        self.assertEqual(groups, {23:1,17:2})
        self.assertEqual(physical_multipole_voltages(source,{1:23,2:17,3:31}), (carrier,groups))
        self.assertEqual(source, before)

    def test_compiler_three_and_four_segmented_drives_are_identical(self):
        results = []
        for version in (3,4):
            author = request(version,2)
            author['geometry_mm']['enclosure'] = dict(model='cylindrical_grounded_shell',
                inner_radius_mm=20.,wall_thickness_mm=1.,z_min_mm=2.,z_max_mm=89.,endcaps={})
            author['static_electrodes_V'] = dict(role='grounded_shell_static_electrodes',ground_V=0.)
            source = compile_design_request(author,expected_identity=author['identity'])
            before = copy.deepcopy(source)
            mapping = dict(zip((g['electrode_group_id'] for g in build_electrode_topology(source)),
                               [17,23,31,37,41],strict=True))
            results.append(scientific_multipole_voltages(source,mapping))
            self.assertEqual(source,before)
        self.assertEqual(results[0],results[1])
        self.assertEqual(results[0],({17:-5.5,23:-10.5,31:-5.5,37:-10.5,41:0.},
                                     {17:1,23:2,31:1,37:2}))

    def test_real_piece_references_keep_geometry_and_existing_continuous_segment_meaning(self):
        for segmented in (False,True):
            source = resolved_design(shell(),segmented=segmented)
            before = copy.deepcopy(source)
            pieces = scientific_multipole_rod_pieces(source)
            self.assertEqual(len(pieces),8 if segmented else 4)
            original = (source['segmentation']['segmented_rod_array']['electrodes'] if segmented
                        else source['geometry_mm']['rod_array']['rods'])
            by_pair = {(p.get('segment_id',1),p.get('parent_rod_id',p.get('rod_id'))):p for p in original}
            for piece in pieces:
                expected = by_pair[(piece['segment_id'],piece['parent_rod_id'])]
                for name in ('center_x_mm','center_y_mm','z_min_mm','z_max_mm','radius_mm','electrode_group'):
                    self.assertEqual(piece[name],expected[name])
                self.assertNotIn('electrode_id',piece)
                self.assertNotIn('scientific_id',piece)
                self.assertEqual(piece['electrode_group_id'],
                    f"segment_{piece['segment_id']:04d}_rf_group_{piece['electrode_group']}" if segmented
                    else f"rod_group_{piece['electrode_group']}")
            pieces[0]['center_x_mm'] = 999
            self.assertEqual(source,before)

    def test_new_array_without_native_fields_yields_complete_probe_pieces(self):
        author = request(count=2)
        source = compile_design_request(author,expected_identity=author['identity'])
        pieces = scientific_multipole_rod_pieces(source)
        self.assertEqual(len(pieces),8)
        self.assertEqual({(p['segment_id'],p['parent_rod_id']) for p in pieces},
                         {(s,r) for s in (1,2) for r in (1,2,3,4)})
        self.assertTrue(all('electrode_id' not in p for p in pieces))

    def test_invalid_scientific_maps_reuse_backend_rejection(self):
        source = resolved_design()
        for mapping in ({},dict(rod_group_1=17),dict(rod_group_1=17,rod_group_2=23,extra=31),
                        dict(rod_group_1=True,rod_group_2=23),dict(rod_group_1=17,rod_group_2=17),
                        dict(rod_group_1=17,rod_group_2=1001)):
            with self.subTest(mapping=mapping),self.assertRaises(ValueError):
                scientific_multipole_voltages(source,mapping)


if __name__ == '__main__':
    unittest.main()

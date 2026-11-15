"""Focused neutral HS1 domain derivation; no native or gas qualification."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from msplatform.backends.simion import rf_tracking_execution as subject


class NeutralHs1DomainTests(unittest.TestCase):
    def test_actual_shared_adapter_receives_intersection(self):
        geometry = SimpleNamespace(frontend_geometry={'domain': {
            'frame_id': 'world', 'minimum_mm': [-3, -4, -5],
            'maximum_mm': [3, 4, 5]}})
        basis = {'grid': {'frame_id': 'world', 'origin_mm': [-2, -9, -3],
                          'pitch_mm': [2, 2.75, 1.75], 'dimensions': [5, 5, 5]}}
        with patch.object(subject, 'model_geometry', return_value=geometry), \
             patch.object(subject, '_prepare_ip_hs1', return_value={'ok': True}) as prepare:
            self.assertEqual(subject.prepare_neutral_ip_hs1(object(), {}, basis=basis), {'ok': True})
            domain = prepare.call_args.kwargs['common_world_domain']
            self.assertEqual(domain.minimum_mm, (-2, -4, -3))
            self.assertEqual(domain.maximum_mm, (3, 2, 4))
            self.assertEqual(prepare.call_args.kwargs['role'], 'simion_neutral_world_collision_geometry')

    def test_frame_or_empty_intersection_rejected_before_adapter(self):
        geometry = SimpleNamespace(frontend_geometry={'domain': {
            'frame_id': 'world', 'minimum_mm': [-1, -1, -1],
            'maximum_mm': [1, 1, 1]}})
        with patch.object(subject, 'model_geometry', return_value=geometry), \
             patch.object(subject, '_prepare_ip_hs1') as prepare:
            for grid in ({'frame_id': 'other', 'origin_mm': [0]*3, 'pitch_mm': [1]*3, 'dimensions': [2]*3},
                         {'frame_id': 'world', 'origin_mm': [2]*3, 'pitch_mm': [1]*3, 'dimensions': [2]*3}):
                with self.assertRaises(ValueError):
                    subject.prepare_neutral_ip_hs1(object(), {}, basis={'grid': grid})
            prepare.assert_not_called()

    def test_ordered_window_outside_base_is_covered(self):
        geometry = SimpleNamespace(frontend_geometry={'domain': {'frame_id':'world', 'minimum_mm':[-10]*3, 'maximum_mm':[10]*3}})
        grid={'frame_id':'world','origin_mm':[-1]*3,'pitch_mm':[1]*3,'dimensions':[3]*3}
        window={'grid':{'frame_id':'world'},'active_box_mm':[[4,6],[-1,1],[-1,1]]}
        basis={'grid':grid,'bases':{'a':{'refinement_windows':[window]}}}
        with patch.object(subject,'model_geometry',return_value=geometry), patch.object(subject,'_prepare_ip_hs1',return_value={}) as prepare:
            subject.prepare_neutral_ip_hs1(object(),{},basis=basis)
            domain=prepare.call_args.kwargs['common_world_domain']
            self.assertEqual(domain.minimum_mm,(-1,-1,-1))
            self.assertEqual(domain.maximum_mm,(6,1,1))

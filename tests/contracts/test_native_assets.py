"""Freeze small explicit co-resident manifest inputs without opening payloads."""
import base64
import copy
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from msplatform.recipes.native_assets import (freeze_field_source, validate_field_reference, field_reference_identity,
    validate_collision_reference, collision_reference_identity, normalize_sampling)


def manifest():
    def record(name):
        return {'path': 'external/' + name, 'exists': True, 'bytes': 10, 'sha256': 'A'*64,
                'retention_role': 'required_evidence'}
    common = {key: record(key) for key in ('model', 'projection', 'descriptor', 'geometry_validation',
              'reopen_geometry', 'solve_pulse_basis', 'reopen_pulse_basis')}
    products = {}
    for name, tag in (('background', '1'), ('on', '2')):
        data = {**common, 'request': record(name+'_request'), 'reopen_solution': record(name+'_reopen')}
        products[name] = {'schema_version': 1, 'kind': 'field_solution', 'status': 'complete',
            'metadata': {'backend': 'comsol', 'scope': 'co_resident_stationary_workpoint',
                'co_resident_workpoint': name, 'field_status': 'solved', 'native_reopen_verified': True,
                'solution': {'solution_tag': 'sol'+tag, 'dataset_tag': 'dset'+tag}}, 'data': data}
    return {'schema_version': 2, 'role': 'simulation_run_manifest', 'status': 'success',
            'inputs': {}, 'outputs': [row for product in products.values() for row in product['data'].values()],
            'products': products}


def collision_manifest():
    record = {'path': 'external/collision.pa0', 'exists': True, 'bytes': 10, 'sha256': 'B'*64,
              'retention_role': 'solver_native_binary'}
    return {'schema_version': 2, 'role': 'simulation_run_manifest', 'status': 'success',
            'inputs': {}, 'outputs': [record], 'products': {'fields': {'schema_version': 1,
                'kind': 'field_bundle', 'status': 'complete', 'data': {'carrier': record},
                'metadata': {'backend': 'simion', 'source_status': 'not_requested', 'field_status': 'available'}}}}


def sampling():
    grid = {'frame_id': 'world', 'origin_mm': [Decimal('-1.25'), 0, 0], 'pitch_mm': [Decimal('0.1')]*3,
            'dimensions': [11, 12, 13], 'block_points': 100}
    return {'world': grid, 'windows': []}


class NativeAssetsTests(unittest.TestCase):
    def test_one_read_freeze_survives_source_change_and_excludes_path_from_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = json.dumps(manifest()).encode('utf-8')
            source = root / 'manifest.json'
            source.write_bytes(payload)
            author = root / 'study.toml'
            item = {'kind': 'comsol_native', 'reference': {'path': source.name,
                'sha256': hashlib.sha256(payload).hexdigest(), 'product_id': 'background'}}
            real_read = Path.read_bytes
            seen = []
            def observe(path):
                if path == source:
                    seen.append(path)
                return real_read(path)
            with patch.object(Path, 'read_bytes', observe):
                frozen = freeze_field_source(item, author)['reference']
            self.assertEqual(seen, [source])
            source.write_text('{}', encoding='utf-8')
            self.assertEqual(validate_field_reference(frozen), frozen)
            moved = copy.deepcopy(frozen)
            moved['reference']['manifest']['path'] = str(root / 'elsewhere.json')
            self.assertEqual(field_reference_identity(frozen), field_reference_identity(moved))
            self.assertEqual(base64.b64decode(frozen['snapshot']['bytes_base64']), payload)

    def test_closed_reference_and_snapshot_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = json.dumps(manifest()).encode('utf-8')
            (root / 'manifest.json').write_bytes(payload)
            ref = {'path': 'manifest.json', 'sha256': hashlib.sha256(payload).hexdigest(), 'product_id': 'background'}
            for source in ({'kind': 'simion_native', 'reference': ref},
                           {'kind': 'comsol_native', 'reference': {**ref, 'product_id': 'on'}},
                           {'kind': 'comsol_native', 'reference': {**ref, 'sha256': 'z'*64}},
                           {'kind': 'comsol_native', 'reference': {**ref, 'path': str(root / 'manifest.json')}}):
                with self.subTest(source=source), self.assertRaises(ValueError):
                    freeze_field_source(source, root / 'study.toml')
            self.assertEqual(freeze_field_source({'kind': 'simion_native'}, root / 'study.toml'), {'kind': 'simion_native'})
            frozen = freeze_field_source({'kind': 'comsol_native', 'reference': ref}, root / 'study.toml')['reference']
            for mutate in (lambda x: x['snapshot'].__setitem__('bytes_base64', base64.b64encode(b'{}').decode()),
                           lambda x: x['reference']['manifest'].__setitem__('bytes', 1),
                           lambda x: x['reference']['manifest'].__setitem__('sha256', '0'*64),
                           lambda x: x['reference'].__setitem__('product_id', 'on')):
                changed = copy.deepcopy(frozen)
                mutate(changed)
                with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                    validate_field_reference(changed)

    def test_rejects_manifest_with_unbound_or_mixed_workpoints(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for mutate in (lambda x: x['products']['on']['data'].__setitem__('model', {'path': 'other'}),
                           lambda x: x['products']['on']['metadata']['solution'].__setitem__('dataset_tag', 'dset1'),
                           lambda x: x.__setitem__('status', 'failed')):
                doc = manifest()
                mutate(doc)
                payload = json.dumps(doc).encode('utf-8')
                (root / 'manifest.json').write_bytes(payload)
                ref = {'kind': 'comsol_native', 'reference': {'path': 'manifest.json',
                    'sha256': hashlib.sha256(payload).hexdigest(), 'product_id': 'background'}}
                with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                    freeze_field_source(ref, root / 'author.toml')

    def test_two_explicit_manifests_and_sampling_are_frozen_once(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payloads = {'comsol.json': json.dumps(manifest()).encode(), 'simion.json': json.dumps(collision_manifest()).encode()}
            for name, payload in payloads.items():
                (root/name).write_bytes(payload)
            def ref(name, product):
                return {'path': name, 'sha256': hashlib.sha256(payloads[name]).hexdigest(), 'product_id': product}
            source = {'kind': 'comsol_native', 'reference': ref('comsol.json', 'background'),
                      'collision_reference': ref('simion.json', 'fields'), 'sampling': sampling()}
            original = Path.read_bytes
            reads = []
            def observe(path):
                reads.append(path)
                return original(path)
            with patch.object(Path, 'read_bytes', observe):
                frozen = freeze_field_source(source, root/'author.toml')
            self.assertEqual(reads, [root/'comsol.json', root/'simion.json'])
            self.assertEqual(frozen['sampling']['world']['pitch_mm'], [0.1]*3)
            (root/'simion.json').write_text('{}', encoding='utf-8')
            value = frozen['collision_reference']
            self.assertEqual(validate_collision_reference(value), value)
            moved = copy.deepcopy(value)
            moved['reference']['manifest']['path'] = str(root/'moved.json')
            self.assertEqual(collision_reference_identity(value), collision_reference_identity(moved))
            changed = copy.deepcopy(value)
            changed['snapshot']['bytes_base64'] = base64.b64encode(b'{}').decode()
            with self.assertRaises(ValueError):
                validate_collision_reference(changed)
            source['kind'] = 'simion_native'
            with self.assertRaises(ValueError):
                freeze_field_source(source, root/'author.toml')

    def test_collision_recursion_and_invalid_sampling_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for mutate in (lambda d: d['products']['fields']['metadata'].__setitem__('field_representation', 'split_scalar_world_with_collision_geometry'),
                           lambda d: d['products']['fields']['metadata'].__setitem__('source_status', 'sampled'),
                           lambda d: d['products']['fields']['metadata'].__setitem__('backend', 'comsol'),
                           lambda d: d.__setitem__('status', 'failed')):
                doc = collision_manifest(); mutate(doc)
                payload = json.dumps(doc).encode(); (root/'collision.json').write_bytes(payload)
                from msplatform.recipes.native_assets import freeze_collision_reference
                with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                    freeze_collision_reference({'path':'collision.json','product_id':'fields',
                        'sha256':hashlib.sha256(payload).hexdigest()}, root/'author.toml')
        for mutate in (lambda d: d.pop('windows'), lambda d: d['world']['pitch_mm'].__setitem__(0, Decimal('Infinity')),
                       lambda d: d['world']['origin_mm'].__setitem__(0, Decimal('1e9999')),
                       lambda d: d['world']['origin_mm'].__setitem__(0, Decimal('1e-9999')),
                       lambda d: d['world']['dimensions'].__setitem__(0, True),
                       lambda d: d['world'].__setitem__('block_points', 0)):
            value = sampling(); mutate(value)
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                normalize_sampling(value)
        value = sampling()
        value['windows'] = [{'name': 'oa', 'grid': copy.deepcopy(value['world']),
                             'active_box_mm': [[-1,1], [0,1], [0,1]]}]
        self.assertEqual(normalize_sampling(value)['windows'][0]['active_box_mm'][0], [-1.0, 1.0])
        value['windows'].append(copy.deepcopy(value['windows'][0]))
        with self.assertRaises(ValueError):
            normalize_sampling(value)


if __name__ == '__main__':
    unittest.main()

"""Freeze small native field manifest bytes; payload ownership stays external."""
from __future__ import annotations

import base64
import binascii
import copy
import hashlib
import json
import math
from decimal import Decimal
from pathlib import Path, PureWindowsPath
from typing import Any, Mapping


def _hash(value: Any) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdefABCDEF' for c in value):
        raise ValueError('field manifest SHA-256 must be 64 hexadecimal characters')
    return value.upper()


def _document(payload: bytes) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate field manifest key: ' + key)
            result[key] = value
        return result
    def invalid(value):
        raise ValueError('nonfinite field manifest value: ' + value)
    document = json.loads(payload.decode('utf-8-sig'), object_pairs_hook=pairs, parse_constant=invalid)
    if not isinstance(document, dict):
        raise ValueError('field manifest must be an object')
    return document


def _check_manifest(document: dict) -> None:
    if (type(document.get('schema_version')) is not int or document['schema_version'] not in (1, 2)
            or document.get('role') != 'simulation_run_manifest' or document.get('status') != 'success'
            or document.get('lifecycle_state') == 'provisional'
            or not isinstance(document.get('inputs'), dict) or not isinstance(document.get('outputs'), list)):
        raise ValueError('field reference requires a successful terminal manifest snapshot')
    products = document.get('products')
    if not isinstance(products, dict):
        raise ValueError('field manifest requires both co-resident workpoint products')
    selected = []
    for name in ('background', 'on'):
        product = products.get(name)
        if (not isinstance(product, dict) or type(product.get('schema_version')) is not int
                or product['schema_version'] != 1 or product.get('kind') != 'field_solution'
                or product.get('status') != 'complete' or not isinstance(product.get('metadata'), dict)
                or not isinstance(product.get('data'), dict)):
            raise ValueError('field manifest requires complete co-resident field_solution products')
        meta, data = product['metadata'], product['data']
        if (meta.get('backend') != 'comsol' or meta.get('scope') != 'co_resident_stationary_workpoint'
                or meta.get('co_resident_workpoint') != name or meta.get('field_status') != 'solved'
                or meta.get('native_reopen_verified') is not True):
            raise ValueError('field workpoint metadata differs')
        for key in ('model', 'request', 'projection', 'descriptor', 'geometry_validation', 'reopen_geometry',
                    'solve_pulse_basis', 'reopen_pulse_basis', 'reopen_solution'):
            record = data.get(key)
            if not isinstance(record, dict) or record not in [*document['inputs'].values(), *document['outputs']]:
                raise ValueError('field workpoint record is absent or not owner-bound: ' + key)
        selected.append(product)
    for key in ('model', 'projection', 'descriptor', 'geometry_validation', 'reopen_geometry',
                'solve_pulse_basis', 'reopen_pulse_basis'):
        if selected[0]['data'][key] != selected[1]['data'][key]:
            raise ValueError('field workpoints must share their sealed ' + key)
    off, on = (item['metadata'].get('solution') for item in selected)
    if (not isinstance(off, dict) or not isinstance(on, dict)
            or not all(isinstance(row.get(key), str) and row[key] for row in (off, on) for key in ('solution_tag', 'dataset_tag'))
            or off['solution_tag'] == on['solution_tag'] or off['dataset_tag'] == on['dataset_tag']):
        raise ValueError('field workpoints require distinct solution and dataset identities')


def _freeze_reference(reference: Mapping[str, Any], author_path: Path, *, product_id: str, check) -> dict:
    if not isinstance(reference, Mapping) or set(reference) != {'path', 'sha256', 'product_id'}:
        raise ValueError('field reference requires path, sha256 and product_id')
    path = reference['path']
    if (not isinstance(path, str) or not path or Path(path).is_absolute() or PureWindowsPath(path).is_absolute()
            or PureWindowsPath(path).drive):
        raise ValueError('field manifest path must be relative to the author recipe')
    if reference['product_id'] != product_id:
        raise ValueError('field reference selects an unsupported product')
    expected = _hash(reference['sha256'])
    location = (Path(author_path).absolute().parent / path).resolve(strict=True)
    payload = location.read_bytes()
    digest = hashlib.sha256(payload).hexdigest().upper()
    if digest != expected:
        raise ValueError('field manifest SHA-256 mismatch')
    check(_document(payload))
    return {'reference': {'manifest': {'path': str(location), 'exists': True, 'bytes': len(payload),
                                       'sha256': digest, 'retention_role': 'required_evidence'},
                          'product_id': product_id},
            'snapshot': {'sha256': digest, 'bytes_base64': base64.b64encode(payload).decode('ascii')}}


def freeze_field_reference(reference: Mapping[str, Any], author_path: Path) -> dict:
    """Read the explicitly identified small manifest exactly once, never the MPH."""
    return _freeze_reference(reference, author_path, product_id='background', check=_check_manifest)


def _validate_reference(value: Mapping[str, Any], *, product_id: str, check) -> dict:
    if not isinstance(value, Mapping) or set(value) != {'reference', 'snapshot'}:
        raise ValueError('resolved field reference requires reference and snapshot')
    data = copy.deepcopy(dict(value))
    reference, snapshot = data['reference'], data['snapshot']
    if not isinstance(reference, dict) or set(reference) != {'manifest', 'product_id'} or reference['product_id'] != product_id:
        raise ValueError('resolved field product differs')
    record = reference['manifest']
    if (not isinstance(record, dict) or set(record) != {'path', 'exists', 'bytes', 'sha256', 'retention_role'}
            or not isinstance(record['path'], str) or not Path(record['path']).is_absolute() or record['exists'] is not True
            or type(record['bytes']) is not int or record['bytes'] <= 0 or record['retention_role'] != 'required_evidence'):
        raise ValueError('resolved manifest record differs')
    if not isinstance(snapshot, dict) or set(snapshot) != {'sha256', 'bytes_base64'}:
        raise ValueError('field snapshot differs')
    try:
        payload = base64.b64decode(snapshot['bytes_base64'], validate=True)
    except (TypeError, ValueError, binascii.Error) as error:
        raise ValueError('invalid field snapshot encoding') from error
    digest = hashlib.sha256(payload).hexdigest().upper()
    if (len(payload) != record['bytes'] or digest != _hash(record['sha256'])
            or digest != _hash(snapshot['sha256']) or record['sha256'] != digest or snapshot['sha256'] != digest):
        raise ValueError('field manifest snapshot identity differs')
    check(_document(payload))
    return data


def validate_field_reference(value: Mapping[str, Any]) -> dict:
    """Revalidate only frozen bytes and metadata, without rereading source paths."""
    return _validate_reference(value, product_id='background', check=_check_manifest)


def field_reference_identity(value: Mapping[str, Any]) -> dict:
    """Scientific identity excludes external path and duplicate serialized bytes."""
    frozen = validate_field_reference(value)
    return {'manifest_sha256': frozen['snapshot']['sha256'], 'product_id': frozen['reference']['product_id']}


def _check_collision_manifest(document: dict) -> None:
    if (type(document.get('schema_version')) is not int or document['schema_version'] not in (1, 2)
            or document.get('role') != 'simulation_run_manifest' or document.get('status') != 'success'
            or document.get('lifecycle_state') == 'provisional'
            or not isinstance(document.get('inputs'), dict) or not isinstance(document.get('outputs'), list)):
        raise ValueError('collision source requires a successful terminal manifest snapshot')
    product = document.get('products', {}).get('fields') if isinstance(document.get('products'), dict) else None
    if (not isinstance(product, dict) or type(product.get('schema_version')) is not int or product['schema_version'] != 1
            or product.get('kind') != 'field_bundle' or product.get('status') != 'complete'
            or not isinstance(product.get('metadata'), dict) or not isinstance(product.get('data'), dict) or not product['data']):
        raise ValueError('collision source requires a complete field_bundle')
    meta = product['metadata']
    if (meta.get('backend') != 'simion' or meta.get('source_status') != 'not_requested'
            or meta.get('field_status') != 'available'
            or meta.get('field_representation') not in (None, 'native_domain_composition', 'assembly_sampled_basis_with_collision_geometry', 'neutral_sampled_basis_with_collision_geometry', 'producer_owned_rf_ip_fractional_family')):
        raise ValueError('collision source must be an original source-independent native SIMION field bundle')
    bound = [*document['inputs'].values(), *document['outputs']]
    for name, record in product['data'].items():
        if not isinstance(name, str) or not name or not isinstance(record, dict) or record not in bound:
            raise ValueError('collision source data member is not bound by its owner')


def freeze_collision_reference(reference: Mapping[str, Any], author_path: Path) -> dict:
    """Freeze only the source field bundle manifest, never its PA payloads."""
    return _freeze_reference(reference, author_path, product_id='fields', check=_check_collision_manifest)


def validate_collision_reference(value: Mapping[str, Any]) -> dict:
    return _validate_reference(value, product_id='fields', check=_check_collision_manifest)


def collision_reference_identity(value: Mapping[str, Any]) -> dict:
    frozen = validate_collision_reference(value)
    return {'manifest_sha256': frozen['snapshot']['sha256'], 'product_id': frozen['reference']['product_id']}


def _number(value: Any, label: str) -> float:
    if type(value) not in (int, float, Decimal):
        raise ValueError(label + ' must be numeric')
    try:
        number = float(value)
    except (OverflowError, ValueError) as error:
        raise ValueError(label + ' must be finite float64') from error
    if not math.isfinite(number) or (value != 0 and number == 0):
        raise ValueError(label + ' must be finite float64')
    return number


def _grid(value: Any) -> dict:
    if not isinstance(value, Mapping) or set(value) != {'frame_id', 'origin_mm', 'pitch_mm', 'dimensions', 'block_points'}:
        raise ValueError('sampling grid requires five explicit fields')
    if not isinstance(value['frame_id'], str) or not value['frame_id'].strip() or value['frame_id'] != value['frame_id'].strip():
        raise ValueError('sampling grid requires a frame identity')
    vectors = {}
    for name in ('origin_mm', 'pitch_mm', 'dimensions'):
        vector = value[name]
        if not isinstance(vector, list) or len(vector) != 3:
            raise ValueError('sampling grid vectors require three axes')
        if name == 'dimensions':
            if any(type(n) is not int or n < 2 for n in vector):
                raise ValueError('sampling dimensions must be integer and at least two')
            vectors[name] = list(vector)
        else:
            vectors[name] = [_number(n, name) for n in vector]
    if any(n <= 0 for n in vectors['pitch_mm']) or type(value['block_points']) is not int or value['block_points'] <= 0:
        raise ValueError('sampling pitch and block size must be positive')
    return {'frame_id': value['frame_id'], **vectors, 'block_points': value['block_points']}


def normalize_sampling(value: Any) -> dict:
    """Normalize explicit world and named window numeric data, without claiming coverage."""
    if not isinstance(value, Mapping) or set(value) != {'world', 'windows'} or not isinstance(value['windows'], list):
        raise ValueError('sampling requires explicit world and windows list')
    world, windows, seen = _grid(value['world']), [], set()
    for window in value['windows']:
        if not isinstance(window, Mapping) or set(window) != {'name', 'grid', 'active_box_mm'}:
            raise ValueError('sampling window requires name, grid and active box')
        name, box = window['name'], window['active_box_mm']
        if not isinstance(name, str) or not name.strip() or name != name.strip() or name in seen:
            raise ValueError('sampling window names must be distinct and nonempty')
        seen.add(name)
        if not isinstance(box, list) or len(box) != 3 or any(not isinstance(x, list) or len(x) != 2 for x in box):
            raise ValueError('sampling active box requires three intervals')
        intervals = [[_number(v, 'active box') for v in interval] for interval in box]
        if any(lo >= hi for lo, hi in intervals):
            raise ValueError('sampling active box intervals must be ordered')
        windows.append({'name': name, 'grid': _grid(window['grid']), 'active_box_mm': intervals})
    return {'world': world, 'windows': windows}


def freeze_field_source(source: Mapping[str, Any], author_path: Path) -> dict:
    """Freeze an explicit source manifest without copying its native payload."""
    if (not isinstance(source, Mapping) or set(source) not in ({'kind'}, {'kind', 'reference'},
                                                                {'kind', 'reference', 'collision_reference', 'sampling'})
            or source.get('kind') not in {'simion_native', 'comsol_native'}):
        raise ValueError('unsupported native field source')
    if 'reference' not in source:
        return {'kind': source['kind']}
    if source['kind'] == 'simion_native':
        if set(source) != {'kind', 'reference'}:
            raise ValueError('SIMION field reference cannot contain a second source')
        return {'kind': source['kind'], 'reference': freeze_collision_reference(source['reference'], author_path)}
    result = {'kind': source['kind'], 'reference': freeze_field_reference(source['reference'], author_path)}
    if 'collision_reference' in source:
        result.update(collision_reference=freeze_collision_reference(source['collision_reference'], author_path),
                      sampling=normalize_sampling(source['sampling']))
    return result

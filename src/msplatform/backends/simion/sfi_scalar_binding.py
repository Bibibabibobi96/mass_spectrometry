"""Admit explicit public scalar workpoints for an existing SFI model.

Admission establishes source identities and geometry/drive agreement. It does
not establish interpolation coverage, coupling, convergence or flight validity.
"""
from __future__ import annotations

import copy
import math
from collections.abc import Mapping
from typing import Any

from msplatform.backends.comsol.assembly_geometry import project_assembly_geometry
from msplatform.backends.simion.frontend import native_frontend_instances
from msplatform.backends.simion.tracking_program import _bound_tracking_model, validate_native_flight
from msplatform.io.manifest_records import record_path, validate_file_record, verify_record
from msplatform.results.artifacts import OpenedArtifact
from .scalar_sample_binding import _ideal_sheet_projection as _ideal_sheet_projection
from .scalar_sample_binding import _read, _small_product, verify_scalar_sample

_NAMES = ('carrier', 'rf_reference', 'pulse_delta')


def _group_vectors(drive: Mapping[str, Any]) -> tuple[dict[str, dict[tuple[str, str], float]], dict[str, Any]]:
    vectors = {name: {} for name in _NAMES}
    signatures = set()
    for instance, groups in drive['groups'].items():
        for group, item in groups.items():
            kind = item['kind']
            if kind == 'static': values = (item['voltage_v'], 0., 0.)
            elif kind == 'pulse': values = (item['off_voltage_v'], 0., item['on_voltage_v'] - item['off_voltage_v'])
            elif kind == 'rf':
                signatures.add(tuple(item[k] for k in ('frequency_hz', 'phase_rad', 'waveform')))
                values = (item['common_mode_v'] + item['dc_v'], item['polarity'] * item['rf_amplitude_v'], 0.)
            else: raise ValueError('unsupported scientific drive kind')
            if not all(type(x) in (int, float) and math.isfinite(x) for x in values):
                raise ValueError('nonfinite scientific drive')
            for name, value in zip(_NAMES, values, strict=True): vectors[name][(instance, group)] = value
    if len(signatures) != 1: raise ValueError('one common RF phase, waveform and frequency required')
    frequency, phase, waveform = next(iter(signatures))
    if frequency <= 0 or waveform not in ('sine', 'cosine'):
        raise ValueError('unsupported RF coefficient')
    return vectors, dict(frequency_hz=frequency, phase_rad=phase, waveform=waveform)


def resolve_sfi_scalar_basis(*, model: Any, geometry: Mapping[str, Any], field_design: Mapping[str, Any],
                             flight: Mapping[str, Any], geometry_artifact: Mapping[str, Any] | OpenedArtifact,
                             samples: Mapping[str, Mapping[str, Any] | OpenedArtifact]) -> dict[str, Any]:
    """Verify public geometry and three scalar products for the existing SFI model.

    All paths remain owned by their producers; callers must protect returned
    producer references and records through their existing managed owner.
    """
    if not isinstance(samples, Mapping) or set(samples) != set(_NAMES):
        raise ValueError('three explicit named scalar products required')
    flight = validate_native_flight(flight, requires_rf=True)
    upstream, tof = native_frontend_instances(geometry['composition_plan'])
    doc0 = model.document
    document = _bound_tracking_model(model, {k: doc0['components_resolved'][k] for k in upstream},
                                     doc0['components_resolved'][tof], geometry, field_design, flight)
    vectors, rf = _group_vectors(document['drive'])
    producer, geo, geo_manifest = _small_product(geometry_artifact, 'geometry_artifact', ('projection',))
    meta = geo['metadata']
    if meta.get('backend') != 'comsol' or meta.get('scope') != 'geometry_only' or meta.get('native_reopen_verified') is not True:
        raise ValueError('successful reopened public geometry required')
    record = validate_file_record(producer['inputs']['execution_request'], 'geometry execution request')
    path = record_path(record, base_dir=geo_manifest.parent)
    verify_record('geometry execution request', record, base_dir=geo_manifest.parent)
    frozen = _read(path)
    payload = frozen['payload']
    if frozen.get('role') != 'run_artifact_workflow_request' or payload.get('action') != 'build_comsol_geometry':
        raise ValueError('geometry producer action differs')
    snapshot = payload['assembly']; projection = _read(record_path(geo['data']['projection'], base_dir=geo_manifest.parent))
    if snapshot['components_resolved'] != document['components_resolved'] or snapshot['composition_plan'] != geometry['composition_plan']:
        raise ValueError('geometry source components or physical plan differ')
    if payload['projection'] != projection or project_assembly_geometry(snapshot, outer_box_mm=projection['outer_box_mm']) != projection:
        raise ValueError('geometry canonical reprojection differs')
    expected = {(r['instance_id'], r['electrode_group_id']) for r in projection['electrode_groups']}
    if len(expected) != len(projection['electrode_groups']) or any(set(v) != expected for v in vectors.values()):
        raise ValueError('physical group coverage differs')
    bindings = {}; shared_request = None; carrier_exterior = None
    for name in _NAMES:
        def check_workpoint(request):
            nonlocal carrier_exterior, shared_request
            rows = request['group_voltages']; actual = {(r['instance_id'], r['electrode_group_id']): r['voltage_v'] for r in rows}
            if len(actual) != len(rows) or actual != vectors[name]: raise ValueError('scalar group workpoint differs')
            exterior = request['exterior']
            if exterior['kind'] != 'potential': raise ValueError('unsupported exterior boundary kind')
            if name == 'carrier': carrier_exterior = exterior['voltage_v']
            elif exterior['voltage_v'] != 0.: raise ValueError('RF and pulse response exterior must be zero')
            other = {k: copy.deepcopy(v) for k, v in request.items() if k != 'group_voltages'}
            other['exterior'] = {'kind': exterior['kind']}
            if shared_request is not None and shared_request != other: raise ValueError('scalar BVP operator or mesh differs')
            shared_request = other
        bindings[name] = verify_scalar_sample(samples[name], projection, check_workpoint=check_workpoint)
    return dict(model_identity_sha256=document['model_identity_sha256'], clock=copy.deepcopy(document['drive']['clock']),
                pulse=copy.deepcopy(document['drive']['pulse']), rf=rf, carrier_exterior_voltage_v=carrier_exterior,
                geometry_reference=geometry_artifact.reference if isinstance(geometry_artifact, OpenedArtifact) else copy.deepcopy(dict(geometry_artifact)), geometry_execution_request=dict(record, path=str(path)),
                bases=bindings, scope='identity_admission_only_not_coverage_or_qualification')

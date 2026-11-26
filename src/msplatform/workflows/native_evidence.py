"""Read native owner worker observations; never infer solver Compute or Fly calls."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from msplatform.io.manifest_records import file_record
from msplatform.execution.host_resource_scheduler import _same_creation_time


def _read(path: Path):
    payload = path.read_bytes()
    record = file_record(path, 'required_evidence')
    if len(payload) != record['bytes'] or hashlib.sha256(payload).hexdigest().upper() != record['sha256']:
        raise ValueError('native control changed during observation')
    value = json.loads(payload.decode('utf-8-sig'))
    if not isinstance(value, dict):
        raise ValueError('native control must be an object')
    return value, record


def _identity(registration, observation):
    if not isinstance(registration, dict) or registration.get('registration') not in {'registered', 'quick_exit'}:
        raise ValueError('native worker registration unavailable')
    pid, started = registration.get('process_id'), registration.get('started_at_utc_ticks')
    if type(pid) is not int or pid <= 0 or type(started) is not int or started <= 0:
        raise ValueError('native worker identity unavailable')
    if (not isinstance(observation, dict) or observation.get('root_process_id') != pid
            or type(observation.get('root_process_started_at_utc_ticks')) is not int
            or not _same_creation_time(str(observation['root_process_started_at_utc_ticks']), str(started))
            or type(observation.get('exit_code')) is not int):
        raise ValueError('native worker exit observation differs from registration')
    return pid, started, observation['exit_code']


def _control(documents):
    receipt, worker, host, ack = (documents[name] for name in ('receipt', 'worker', 'host', 'ack'))
    nonce, binding = receipt.get('nonce'), receipt.get('binding_id')
    if (not isinstance(nonce, str) or not nonce or not isinstance(binding, str) or not binding
            or any(doc.get('nonce') != nonce for doc in (worker, host, ack))
            or worker.get('binding_id') != binding or ack.get('binding_id') != binding
            or host.get('inherited') is not False or not isinstance(host.get('token'), str) or not host['token']):
        raise ValueError('native control registration identities differ')
    native = receipt.get('receipt')
    if not isinstance(native, dict):
        raise ValueError('native owner completion unavailable')
    release = native.get('host_release')
    if (not isinstance(release, dict) or release.get('token') != host['token'] or release.get('inherited') is not False
            or release.get('error') is not None or release.get('result') != {'status': 'released', 'token': host['token']}):
        raise ValueError('native owner host release unavailable')
    result = []
    if 'workers' in worker:
        registrations, observations, pending = worker['workers'], native.get('observations'), native.get('not_started')
        if not isinstance(registrations, list) or not registrations or not isinstance(observations, dict) or not isinstance(pending, list):
            raise ValueError('native group worker completion unavailable')
        if any(not isinstance(row, dict) or not isinstance(row.get('operation_id'), str) or not row['operation_id'] for row in registrations):
            raise ValueError('native group operation identity unavailable')
        by_name = {row['operation_id']: row for row in registrations}
        if (len(by_name) != len(registrations) or set(by_name) != set(observations)
                or any(not isinstance(name, str) or not name for name in pending)
                or len(set(pending)) != len(pending) or set(pending) & set(by_name)):
            raise ValueError('native group registrations and completions differ')
        for name in sorted(by_name):
            pid, started, code = _identity(by_name[name], observations[name])
            result.append(dict(operation_id=name, process_id=pid, started_at_utc_ticks=started, returncode=code))
    else:
        pid, started, code = _identity(worker, native.get('observation'))
        result.append(dict(operation_id=None, process_id=pid, started_at_utc_ticks=started, returncode=code))
    return result


def summarize_native_workers(work_directory: str | Path) -> dict:
    """Summarize observed stopped worker processes, not scientific solver calls.

    No controls means unavailable, not zero. Missing or inconsistent siblings
    keep the aggregate count unavailable; successfully verified partial rows
    remain visible as observations. No Store or owner state is modified.
    """
    root = Path(work_directory)
    if not root.is_absolute() or not root.is_dir():
        raise ValueError('native evidence requires an existing absolute work directory')
    suffixes = ('receipt', 'worker', 'host', 'ack')
    paths = [path for path in root.glob('native-control-*.json')
             if any(path.name.endswith('.' + suffix + '.json') for suffix in suffixes)]
    prefixes = sorted({path.name.rsplit('.', 2)[0] for path in paths})
    result = dict(status='unavailable', scope='native_owner_worker_observations_not_solver_calls',
                  observed_completed_worker_count=None, workers=[], controls=[], reason=None)
    if not prefixes:
        result['reason'] = 'no_native_control_evidence'
        return result
    seen = []
    errors = []
    for prefix in prefixes:
        documents, records = {}, {}
        try:
            if not re.fullmatch(r'native-control-[0-9a-f]{32}', prefix):
                raise ValueError('native control filename identity differs')
            for suffix in suffixes:
                documents[suffix], records[suffix] = _read(root / (prefix + '.' + suffix + '.json'))
            if documents['receipt'].get('nonce') != prefix.removeprefix('native-control-'):
                raise ValueError('native control filename and nonce differ')
            workers = _control(documents)
            identities = [(row['process_id'], row['started_at_utc_ticks']) for row in workers]
            all_identities = seen + identities
            if any(a[0] == b[0] and _same_creation_time(str(a[1]), str(b[1]))
                   for i, a in enumerate(all_identities) for b in all_identities[i+1:]):
                raise ValueError('duplicate native worker process identity')
            seen.extend(identities)
            result['workers'].extend(workers)
            result['controls'].append(dict(prefix=prefix, records=records))
        except (OSError, ValueError, KeyError, TypeError) as error:
            errors.append(dict(prefix=prefix, reason=str(error)))
            if records:
                result['controls'].append(dict(prefix=prefix, records=records))
    if errors:
        result['reason'] = errors
    else:
        result['status'] = 'available'
        result['observed_completed_worker_count'] = len(result['workers'])
    return result

"""Inert transport for actual RunSession grouped tracking fixture children."""

import json
from pathlib import Path
import sys


def grouped_inert_transport(actual_group, payload, calls, *, is_failed=None, sort_failed=None):
    """Replace only executable/arguments; keep dispatcher, guards and receipts."""
    def group(session, specs, **kwargs):
        failed = is_failed(session) if is_failed is not None else 'failed' in session.run_id
        prepared = []
        for spec in specs:
            item = dict(spec)
            name = item['operation_id']
            item.update(executable=Path(sys.executable), arguments=payload(
                session, name, item['arguments'],
                partial_log=failed and name.endswith('0002')))
            prepared.append(item)
        if failed:
            key = sort_failed or (lambda row: {3: 0, 1: 1, 2: 2, 4: 3}[row['scheduler_batch']['index']])
            prepared.sort(key=key)
        kwargs.update(role='GATE', stage='unclassified')
        try:
            return actual_group(session, prepared, **kwargs)
        finally:
            saved = session.log_dir / 'group_tracking_fly.process.json'
            if saved.exists():
                for attempt in json.loads(saved.read_text())['attempts']:
                    calls.append((session.run_id, attempt['operation_id']))
    return group

"""Rehydrate captured history bytes under a synthetic receipt; never run an old producer."""
import base64
import hashlib
import json
from pathlib import Path

from msplatform.io.manifest_records import file_record


def captured_measured_fixture(directory: Path) -> dict:
    witness = Path(__file__).resolve().parents[2]/'components/multi_reflection_tof/fixtures/mr_measured_source_old_witness.json'
    population = json.loads(witness.read_text(encoding='utf-8'))['stages']['population']
    directory.mkdir(parents=True, exist_ok=False)
    outputs = {}
    for name, item in population['artifacts'].items():
        data = base64.b64decode(item['base64'], validate=True)
        if len(data) != item['bytes'] or hashlib.sha256(data).hexdigest() != item['sha256'].lower():
            raise ValueError('frozen measured history bytes differ')
        path = directory/name; path.write_bytes(data)
        outputs[path.stem] = file_record(path)
    # The captured scientific payload is unchanged; this wrapper is synthetic
    # test metadata and does not claim to be an original published manifest.
    receipt = dict(population['semantic_report'], inputs={}, outputs=outputs)
    (directory/'source_receipt.json').write_text(json.dumps(receipt), encoding='utf-8')
    return receipt

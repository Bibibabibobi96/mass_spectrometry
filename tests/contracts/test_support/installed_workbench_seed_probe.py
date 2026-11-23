"""Installed seed transport acceptance; this does not qualify a native Workbench."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import sysconfig


_CHILD = r"""
import hashlib, importlib, importlib.abc, json, os, pathlib, sys, sysconfig
blocked = [pathlib.Path(p).resolve() for p in json.loads(sys.argv[1])]
def deny_read(event, arguments):
    if event == 'open' and arguments and isinstance(arguments[0], (str, bytes)):
        path = pathlib.Path(os.fsdecode(arguments[0])).resolve()
        if any(path.is_relative_to(base) for base in blocked):
            raise AssertionError('author source read: ' + str(path))
sys.addaudithook(deny_read)
class DenyRepository(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'common', 'projects', 'integrations'}:
            raise AssertionError('author import: ' + fullname)
sys.meta_path.insert(0, DenyRepository())
api = importlib.import_module('msplatform.backends.simion.workbench_seed')
from msplatform.backends.simion.resources import structural_seed_path, STRUCTURAL_SEEDS
pure = pathlib.Path(sysconfig.get_path('purelib')).resolve()
assert pathlib.Path(api.__file__).resolve() == pure / 'msplatform/backends/simion/workbench_seed.py'
base = pathlib.Path(sys.argv[2]).resolve()
mode = sys.argv[3]
placeholder = base / 'placeholder.pa0'
if mode == 'resource':
    api.freeze_workbench_seed(base / 'resource-output', placeholder_path=placeholder)
    raise AssertionError('missing installed seed accepted')
seed = structural_seed_path(1).resolve()
assert seed == pure / 'msplatform/backends/simion/resources/1_instance_seed.iob'
seed_bytes = seed.read_bytes()
assert (len(seed_bytes), hashlib.sha256(seed_bytes).hexdigest()) == STRUCTURAL_SEEDS[1]
explicit = base / 'explicit.iob'
originals = {path: path.read_bytes() for path in (seed, placeholder, explicit)}
for label, selected in (('default', None), ('explicit', explicit)):
    destination = base / label
    kwargs = {'placeholder_path': placeholder}
    if selected is not None:
        kwargs['seed_path'] = selected
    records = api.freeze_workbench_seed(destination, **kwargs)
    assert set(records) == {'seed', 'placeholder'}
    for role, source, filename in (
        ('seed', seed if selected is None else explicit, '1_instance_seed.iob'),
        ('placeholder', placeholder, 'iob_seed_placeholder_01.pa0'),
    ):
        row = records[role]
        data = originals[source]
        target = (destination / 'simion/iob_seed' / filename).resolve()
        source_record = {'path': str(source.resolve()), 'exists': True, 'bytes': len(data),
                         'sha256': hashlib.sha256(data).hexdigest().upper()}
        assert set(row) == {'source', 'frozen', 'frozen_path_utf16_units'}
        assert row['source'] == source_record
        assert row['frozen'] == {**source_record, 'path': str(target)}
        assert row['frozen_path_utf16_units'] == len(str(target).encode('utf-16-le')) // 2
        assert target.read_bytes() == data
assert all(path.read_bytes() == data for path, data in originals.items())
print('INSTALLED_WORKBENCH_SEED_PASS')
"""


def run(fixture, root, blocked_roots, case, timer):
    """Exercise the installed seed and explicit placeholder in an isolated child."""
    del fixture  # This probe constructs only small inert test-owned inputs.
    root = Path(root).resolve()
    probe_root = root / ("workbench-seed-" + str(case) + "-中文")
    probe_root.mkdir(parents=True, exist_ok=False)
    inputs = {
        probe_root / "placeholder.pa0": b"inert-placeholder-contents",
        probe_root / "explicit.iob": b"inert-explicit-iob",
    }
    for path, data in inputs.items():
        path.write_bytes(data)
    blocked = json.dumps([str(Path(path).resolve()) for path in blocked_roots])
    command = [sys.executable, "-I", "-B", "-X", "utf8", "-c", _CHILD,
               blocked, str(probe_root)]
    pure = Path(sysconfig.get_path("purelib")).resolve()
    module = pure / "msplatform/backends/simion/workbench_seed.py"
    resource = pure / "msplatform/backends/simion/resources/1_instance_seed.iob"
    with timer("workbench_seed", str(case)):
        positive = subprocess.run(command + ["normal"], cwd=probe_root,
                                  capture_output=True, text=True, encoding="utf-8",
                                  timeout=60, check=False)
        assert positive.returncode == 0 and positive.stdout.strip() == "INSTALLED_WORKBENCH_SEED_PASS", (positive.stdout, positive.stderr)
        for path, mode, expected in (
            (module, "normal", "ModuleNotFoundError: No module named 'msplatform.backends.simion.workbench_seed'"),
            (resource, "resource", "FileNotFoundError: installed SIMION structural seed is missing: 1_instance_seed.iob"),
        ):
            saved = path.read_bytes()
            held = path.with_name(path.name + ".installed-seed-probe-held")
            assert not held.exists()
            path.rename(held)
            try:
                result = subprocess.run(command + [mode], cwd=probe_root,
                                        capture_output=True, text=True, encoding="utf-8",
                                        timeout=60, check=False)
                lines = result.stderr.strip().splitlines()
                assert result.returncode != 0 and lines and lines[-1] == expected, (result.stdout, result.stderr)
            finally:
                held.rename(path)
            assert path.read_bytes() == saved
    assert all(path.read_bytes() == data for path, data in inputs.items())
    print("INSTALLED_WORKBENCH_SEED=PASS")

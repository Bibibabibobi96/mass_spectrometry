"""Test-only installed strict JSON witness; run in an isolated consumer process."""

import hashlib
import importlib.abc
import json
import os
import pathlib
import subprocess
import sys
import sysconfig
import time
from contextlib import contextmanager


@contextmanager
def section_timing(section, case):
    started = time.perf_counter_ns()
    try:
        yield
    finally:
        try:
            print('INSTALLED_SECTION_TIMING='+json.dumps(dict(section=section, case=case,
                elapsed_ns=time.perf_counter_ns()-started, exception=sys.exc_info()[0] is not None)), flush=True)
        except BaseException:
            pass


def run_strict_json(fixture, root, blocked_source_roots, case, timer=section_timing):
    # STRICT_JSON_INSTALLED_BEGIN
    with timer('strict_json', case):
        import base64
        from msplatform.io import strict_json as sj_owner
        sj_path = pathlib.Path(sj_owner.__file__).resolve()
        assert sj_path == pathlib.Path(sysconfig.get_path('purelib')).resolve() / 'msplatform/io/strict_json.py'
        sj_fixture = fixture['strict_json_old_witness']
        sj_root = root / ('strict-json-' + case)
        sj_root.mkdir()
        def sj_observe(call):
            try:
                value = call()
                return dict(return_type=type(value).__module__ + '.' + type(value).__qualname__, **{'return': value})
            except Exception as exc:
                cause = exc.__cause__
                return dict(exception_type=type(exc).__module__ + '.' + type(exc).__qualname__, exception_message=str(exc),
                    cause_type=None if cause is None else type(cause).__module__ + '.' + type(cause).__qualname__,
                    cause_message=None if cause is None else str(cause))
        def sj_expected(result, path=None):
            result = dict(result)
            if result.get('exception_type') == 'common.contracts.strict_json.StrictJsonError':
                result['exception_type'] = 'msplatform.io.strict_json.StrictJsonError'
            for key in ('exception_message', 'cause_message'):
                if path is not None and result.get(key) is not None:
                    result[key] = result[key].replace('<PATH_REPR>', repr(str(path))).replace('<PATH>', str(path))
            return result
        assert len(sj_fixture['files']) == 10 and len(sj_fixture['methods']) == 11
        for sj_case in sj_fixture['files']:
            sj_input = sj_root / (sj_case['name'] + '.json')
            if not sj_case.get('absent'):
                sj_raw = base64.b64decode(sj_case['input_base64'], validate=True)
                assert len(sj_raw) == sj_case['bytes'] and hashlib.sha256(sj_raw).hexdigest() == sj_case['sha256']
                sj_input.write_bytes(sj_raw)
            assert sj_observe(lambda: sj_owner.load_json_object(sj_input)) == sj_expected(sj_case['result'], sj_input)
            if not sj_case.get('absent'):
                assert sj_input.read_bytes() == sj_raw
            else:
                assert not sj_input.exists()
        sj_calls = dict(exact_keys=lambda: sj_owner.require_exact_keys({'extra': 1}, {'required'}, 'contract'),
            dict=lambda: sj_owner.require_dict([], 'item'), bool=lambda: sj_owner.require_bool(1, 'flag'),
            string=lambda: sj_owner.require_string('', 'label'), number_bool=lambda: sj_owner.require_number(True, 'value'),
            number_overflow=lambda: sj_owner.require_number(10**1000, 'value'),
            number_minimum=lambda: sj_owner.require_number(0, 'value', minimum=0, strict_minimum=True),
            number_maximum=lambda: sj_owner.require_number(3, 'value', maximum=2.0),
            number_valid=lambda: sj_owner.require_number(-2, 'value'),
            integer_bool=lambda: sj_owner.require_positive_integer(True, 'count'),
            integer_valid=lambda: sj_owner.require_positive_integer(3, 'count'))
        assert set(sj_calls) == {case['name'] for case in sj_fixture['methods']}
        for sj_case in sj_fixture['methods']:
            assert sj_observe(sj_calls[sj_case['name']]) == sj_expected(sj_case['result'])
        sj_owned = sj_path.read_bytes()
        sj_held = sj_path.with_suffix('.strict-json-held')
        assert not sj_held.exists()
        sj_path.rename(sj_held)
        try:
            sj_missing_code = r"""import importlib.abc,json,os,pathlib,sys
blocked=[pathlib.Path(p).resolve() for p in json.loads(sys.argv[1])]
def deny(event,args):
 if event=='open' and args and isinstance(args[0],(str,bytes)):
  p=pathlib.Path(os.fsdecode(args[0])).resolve()
  if any(p.is_relative_to(b) for b in blocked): raise AssertionError('author access: '+str(p))
sys.addaudithook(deny)
class Deny(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname.split('.')[0] in {'common','projects','integrations'}: raise AssertionError('author import: '+fullname)
sys.meta_path.insert(0,Deny())
import msplatform.io.strict_json
"""
            sj_missing = subprocess.run([sys.executable, '-I', '-B', '-X', 'utf8', '-c', sj_missing_code,
                json.dumps([str(path) for path in blocked_source_roots])], cwd=root, capture_output=True,
                text=True, encoding='utf-8', timeout=30, check=False)
            assert sj_missing.returncode != 0 and "No module named 'msplatform.io.strict_json'" in sj_missing.stderr, sj_missing.stderr
        finally:
            sj_held.rename(sj_path)
        assert sj_path.read_bytes() == sj_owned
    # STRICT_JSON_INSTALLED_END


def main():
    # The caller provides the original fixture and every author root explicitly.
    if len(sys.argv) != 4:
        raise SystemExit('usage: strict_json_probe.py FIXTURE BLOCKED_ROOTS_JSON CASE')
    fixture = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding='utf-8'))
    root = pathlib.Path.cwd().resolve()
    blocked = [pathlib.Path(p).resolve() for p in json.loads(sys.argv[2])]
    required = [pathlib.Path(fixture['repo_root']).resolve()]
    required.extend(pathlib.Path(p).resolve() for p in fixture.get('author_source_roots', []))
    required.extend(pathlib.Path(p).resolve() for p in fixture.get('additional_blocked_source_roots', []))
    if (any(p not in blocked for p in required) or
            not blocked or any(root.is_relative_to(p) for p in blocked)):
        raise ValueError('Explicit blocked author roots and an outside working directory are required')
    def reject(event, arguments):
        if event == 'open' and arguments and isinstance(arguments[0], (str, bytes)):
            candidate = pathlib.Path(os.fsdecode(arguments[0])).resolve()
            if any(candidate.is_relative_to(source) for source in blocked):
                raise AssertionError('installed action accessed an author tree: ' + str(candidate))
    sys.addaudithook(reject)
    class RejectRepositoryImports(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname.split('.')[0] in {'common', 'projects', 'integrations'}:
                raise AssertionError('installed action imported a repository owner: ' + fullname)
    sys.meta_path.insert(0, RejectRepositoryImports())
    run_strict_json(fixture, root, blocked, sys.argv[3])


if __name__ == '__main__':
    main()

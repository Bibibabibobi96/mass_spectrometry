"""Authenticated parent caches may yield clean source evidence, never executable caches."""
from pathlib import Path
import json
import marshal
import py_compile
import sys
import tempfile
import unittest

from common.contracts.machine_contracts import sha256
from common.contracts.write_run_manifest import file_record
from projects.single_reflection_oa_tof_mass_analyzer.analysis.candidate_source_closure import (
    ROLE, derive_candidate_source_closure, verify_candidate_source_closure,
)


class FrozenBytecodeReuseTests(unittest.TestCase):
    def fixture(self, root):
        parent = root / "parent"
        code = parent / "inputs/code"
        source = code / "example.py"
        source.parent.mkdir(parents=True)
        source.write_text("def nested(x):\n try:\n  return x + 1\n except TypeError:\n  return None\nraise RuntimeError('never execute')\n", encoding="utf-8", newline="\n")
        cache = Path(py_compile.compile(str(source), doraise=True))
        closure = {"schema_version": 2, "role": ROLE, "code_root": str(code),
                   "runtime": {"python_executable": sys.executable, "python_sha256": sha256(Path(sys.executable)),
                               "candidate_artifact_root": str(root)},
                   "sources": [{"source_id": "example.py", "bytes": source.stat().st_size, "sha256": sha256(source)}]}
        closure_path = parent / "inputs/source_closure.json"
        closure_path.write_text(json.dumps(closure), encoding="utf-8")
        manifest = {"role": "simulation_run_manifest", "status": "success", "inputs": {"closure": file_record(closure_path)},
                    "outputs": [file_record(cache)]}
        manifest_path = parent / "run_manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        return manifest_path, closure_path, source, cache, closure

    def test_bound_cache_derives_clean_evidence_and_parent_stays_unchanged(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest, closure_path, source, cache, closure = self.fixture(root)
            before = {p: p.read_bytes() for p in manifest.parent.rglob("*") if p.is_file()}
            with self.assertRaisesRegex(ValueError, "extra files"):
                verify_candidate_source_closure(closure)
            result = derive_candidate_source_closure(manifest, closure_path, root / "child/evidence/code")
            verify_candidate_source_closure(result["closure"])
            self.assertEqual(result["derivation"]["copied_sources"], 1)
            self.assertEqual(len(result["derivation"]["validated_bytecode"]), 1)
            self.assertEqual(result["closure"]["sources"], closure["sources"])
            self.assertEqual((Path(result["closure"]["code_root"]) / "example.py").read_bytes(), source.read_bytes())
            self.assertFalse(any(Path(result["closure"]["code_root"]).rglob("*.pyc")))
            self.assertEqual(before, {p: p.read_bytes() for p in manifest.parent.rglob("*") if p.is_file()})
            self.assertTrue(cache.exists())

    def test_missing_or_inconsistent_evidence_rejects_without_copying(self):
        for case in ("unbound", "modified_cache", "source", "header", "filename", "exception_table", "line_table", "constant", "trailer", "extra", "runtime"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                manifest, closure_path, source, cache, closure = self.fixture(root)
                document = json.loads(manifest.read_text(encoding="utf-8"))
                if case == "unbound":
                    document["outputs"] = []
                elif case == "source":
                    source.write_text("print('different science')", encoding="utf-8")
                elif case == "extra":
                    extra = cache.parent / "unexpected.txt"
                    extra.write_text("unknown", encoding="utf-8")
                    document["outputs"].append(file_record(extra))
                elif case == "runtime":
                    closure["runtime"]["python_sha256"] = "0" * 64
                    closure_path.write_text(json.dumps(closure), encoding="utf-8")
                    document["inputs"]["closure"] = file_record(closure_path)
                else:
                    payload = cache.read_bytes()
                    if case == "header":
                        payload = b"bad!" + payload[4:]
                    elif case in {"filename", "exception_table", "line_table", "constant"}:
                        code = marshal.loads(payload[16:])
                        if case == "filename":
                            code = code.replace(co_filename="unrelated.py")
                        elif case == "line_table":
                            code = code.replace(co_linetable=b"")
                        elif case == "constant":
                            code = code.replace(co_consts=code.co_consts + ("changed",))
                        else:
                            constants = list(code.co_consts)
                            nested = next(i for i, value in enumerate(constants) if hasattr(value, "co_exceptiontable"))
                            constants[nested] = constants[nested].replace(co_exceptiontable=b"")
                            code = code.replace(co_consts=tuple(constants))
                        payload = payload[:16] + marshal.dumps(code)
                    else:
                        payload += b"changed"
                    cache.write_bytes(payload)
                    if case != "modified_cache":
                        document["outputs"] = [file_record(cache)]
                manifest.write_text(json.dumps(document), encoding="utf-8")
                destination = root / "child/evidence/code"
                with self.assertRaises(ValueError):
                    derive_candidate_source_closure(manifest, closure_path, destination)
                self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()

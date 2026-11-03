"""Behavioral checks for the gate unittest runner."""
import os
import hashlib
import json
from unittest.mock import patch
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class GateUnittestTests(unittest.TestCase):
    def test_failure_and_duration_are_reported_before_suite_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test_probe.py"
            path.write_text(
                "import unittest\nclass Probe(unittest.TestCase):\n"
                "    def test_a_failure(self): self.fail('FIRST_FAILURE')\n"
                "    def test_b_pass(self): pass\n", encoding="utf-8")
            root = Path(__file__).resolve().parents[2]
            env = dict(os.environ, PYTHONPATH=str(root))
            result = subprocess.run(
                [sys.executable, "-m", "common.gate_unittest", "test_probe"], cwd=directory,
                env=env, capture_output=True, text=True, encoding="utf-8", timeout=30,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stderr.count("TEST_DURATION_SECONDS="), 2)
            self.assertLess(result.stderr.index("TEST_FAILURE_IMMEDIATE="),
                            result.stderr.index("TEST_DURATION_SECONDS="))
            self.assertLess(result.stderr.index("FIRST_FAILURE"), result.stderr.index("Ran 2 tests"))


    def test_failed_subtest_reports_traceback_immediately(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test_probe.py"
            path.write_text(
                "import unittest\nclass Probe(unittest.TestCase):\n"
                "    def test_subtests(self):\n"
                "        for value in (1, 2):\n"
                "            with self.subTest(value=value): self.assertEqual(value, 0, 'SUBTEST_FAILURE')\n",
                encoding="utf-8")
            root = Path(__file__).resolve().parents[2]
            result = subprocess.run(
                [sys.executable, "-m", "common.gate_unittest", "test_probe"], cwd=directory,
                env=dict(os.environ, PYTHONPATH=str(root)), capture_output=True, text=True,
                encoding="utf-8", timeout=30,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stderr.count("TEST_FAILURE_IMMEDIATE="), 2)
            self.assertLess(result.stderr.index("SUBTEST_FAILURE"), result.stderr.index("Ran 1 test"))


class GateOutcomeTests(unittest.TestCase):
    def invoke(self, directory, names, *, extra=()):
        root = Path(__file__).resolve().parents[2]
        result = subprocess.run(
            [sys.executable, "-m", "common.gate_unittest", *extra, *names],
            cwd=directory, env=dict(os.environ, PYTHONPATH=str(root)),
            capture_output=True, text=True, encoding="utf-8", timeout=30)
        records = [json.loads(line.split("=", 1)[1]) for line in result.stdout.splitlines()
                   if line.startswith("TEST_OUTCOME_JSON=")]
        receipts = [json.loads(line.split("=", 1)[1]) for line in result.stdout.splitlines()
                    if line.startswith("TEST_OUTCOME_INVOCATION_JSON=")]
        return result, records, receipts

    def test_actual_outcomes_include_subtests_skips_xfail_xpass_and_failures(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "test_matrix.py").write_text("""import unittest
class Matrix(unittest.TestCase):
 def test_success(self): print('unterminated output',end='')
 @unittest.skip('explicit skip reason')
 def test_skip(self): pass
 @unittest.expectedFailure
 def test_xfail(self): self.fail('expected')
 @unittest.expectedFailure
 def test_xpass(self): pass
 def test_failure(self): self.fail('failure sentinel')
 def test_error(self): raise ValueError('error sentinel')
 def test_subtests(self):
  with self.subTest(case='bad'): self.fail('subtest sentinel')
  with self.subTest(case='good'): pass
 def test_subskip(self):
  with self.subTest(case='skipped'): self.skipTest('subskip reason')
""", encoding="utf-8")
            output = root / "outcomes.json"
            result, records, receipts = self.invoke(root, ["test_matrix"], extra=(
                "--outcomes-path", str(output), "--source-sha", "f" * 40, "--stage", "matrix"))
            self.assertNotEqual(result.returncode, 0)
            terminal = receipts[-1]
            self.assertEqual([x["event"] for x in receipts], ["started", "completed"])
            self.assertTrue(terminal["completed"])
            self.assertEqual(terminal["tests_run"], 8)
            self.assertEqual(terminal["record_count"], len(records))
            self.assertEqual(terminal["status"], "failure")
            self.assertEqual(json.loads(output.read_text())["records"], records)
            parents = {x["class_method"]: x for x in records if x["entity_kind"] == "test"}
            expected = dict(test_success="success", test_skip="skip", test_xfail="expected_failure",
                            test_xpass="unexpected_success", test_failure="failure", test_error="error",
                            test_subtests="failure", test_subskip="skip")
            for method, outcome in expected.items():
                self.assertEqual(parents["Matrix." + method]["outcome"], outcome)
            self.assertEqual(parents["Matrix.test_skip"]["reason"], "explicit skip reason")
            self.assertEqual(parents["Matrix.test_subskip"]["reason"], "subskip reason")
            self.assertEqual(len([x for x in records if x["entity_kind"] == "subtest"]), 3)
            for row in records:
                self.assertEqual(row["source_path"], str(root / "test_matrix.py"))
                self.assertEqual(row["source_file_sha256"], hashlib.sha256((root / "test_matrix.py").read_bytes()).hexdigest())
                self.assertEqual(row["source_sha"], "f" * 40)
                self.assertEqual(row["stage"], "matrix")
                self.assertEqual(row["invocation_id"], terminal["invocation_id"])
                if row["entity_kind"] == "subtest":
                    self.assertIn(row["subtest_parent"], {x["test_key"] for x in parents.values()})
            self.assertEqual(result.stderr.count("TEST_DURATION_SECONDS="), 8)

    def test_fixture_and_loader_errors_have_no_fabricated_method_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "test_class.py").write_text("import unittest\nclass Bad(unittest.TestCase):\n @classmethod\n def setUpClass(cls): raise RuntimeError('class setup')\n def test_never(self): pass\n", encoding="utf-8")
            (root / "test_module.py").write_text("import unittest\ndef setUpModule(): raise unittest.SkipTest('module setup skip')\nclass Bad(unittest.TestCase):\n def test_never(self): pass\n", encoding="utf-8")
            result, records, receipts = self.invoke(root, ["test_class", "test_module", "module_missing_probe"])
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(len(records), 3)
            self.assertEqual(sorted(x["entity_kind"] for x in records), ["fixture", "fixture", "loader"])
            self.assertFalse(any(x["outcome"] == "success" for x in records))
            loader = next(x for x in records if x["entity_kind"] == "loader")
            self.assertIsNone(loader["source_path"])
            self.assertEqual(loader["identity_status"], "unknown")
            fixtures = [x for x in records if x["entity_kind"] == "fixture"]
            self.assertEqual({x["outcome"] for x in fixtures}, {"skip", "error"})
            self.assertTrue(all(x["duration_seconds"] is None for x in fixtures))
            self.assertTrue(all(x["source_path"] for x in fixtures))
            self.assertEqual(receipts[-1]["record_count"], 3)

    def test_module_setup_error_and_class_teardown_are_fixture_entities(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "test_setup.py").write_text("import unittest\ndef setUpModule(): raise RuntimeError('module setup error')\nclass Never(unittest.TestCase):\n def test_never(self): pass\n", encoding="utf-8")
            (root / "test_teardown.py").write_text("import unittest\nclass Ends(unittest.TestCase):\n def test_ok(self): pass\n @classmethod\n def tearDownClass(cls): raise RuntimeError('class teardown error')\n", encoding="utf-8")
            result, rows, receipts = self.invoke(root, ["test_setup", "test_teardown"])
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(receipts[-1]["tests_run"], 1)
            self.assertEqual([row["seq"] for row in rows], [1, 2, 3])
            fixtures = [row for row in rows if row["entity_kind"] == "fixture"]
            self.assertEqual({row["class_method"] for row in fixtures}, {"setUpModule", "Ends.tearDownClass"})
            self.assertTrue(all(row["outcome"] == "error" for row in fixtures))
            self.assertFalse(any("test_never" in row["class_method"] for row in rows))
            self.assertEqual(sum(receipts[-1]["outcome_counts"].values()), len(rows))

    def test_nested_default_invocation_cannot_overwrite_explicit_parent_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "test_child.py").write_text("import unittest\nclass Child(unittest.TestCase):\n def test_child(self): pass\n", encoding="utf-8")
            (root / "test_parent.py").write_text("import unittest,subprocess,sys,json\nclass Parent(unittest.TestCase):\n def test_parent(self):\n  child=subprocess.run([sys.executable,'-m','common.gate_unittest','test_child'],capture_output=True,text=True,encoding='utf-8',timeout=10,cwd='.')\n  self.assertEqual(child.returncode,0,child.stderr)\n  rows=[json.loads(line.split('=',1)[1]) for line in child.stdout.splitlines() if line.startswith('TEST_OUTCOME_JSON=')]\n  self.assertEqual(len(rows),1)\n  self.assertIsNone(rows[0]['source_sha'])\n  self.assertIsNone(rows[0]['stage'])\n", encoding="utf-8")
            output = root / "parent.json"
            result, rows, terminal = self.invoke(root, ["test_parent"], extra=("--outcomes-path", str(output), "--source-sha", "parent", "--stage", "outer"))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["class_method"], "Parent.test_parent")
            document = json.loads(output.read_text())
            self.assertEqual(document["records"], rows)
            self.assertEqual(document["invocation"]["invocation_id"], terminal[-1]["invocation_id"])

    def test_same_short_id_in_two_loaded_sources_has_distinct_source_keys(self):
        from common.gate_unittest import _source_identity
        import importlib.util

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tests = []
            for index in (1, 2):
                path = root / f"source{index}.py"
                path.write_text("import unittest\nclass Same(unittest.TestCase):\n def test_same(self): pass\n", encoding="utf-8")
                spec = importlib.util.spec_from_file_location("same_legacy_module", path)
                module = importlib.util.module_from_spec(spec)
                with patch.dict(sys.modules, same_legacy_module=module):
                    spec.loader.exec_module(module)
                    tests.append(module.Same("test_same"))
            identities = [_source_identity(test) for test in tests]
            self.assertEqual(identities[0]["legacy_test_id"], identities[1]["legacy_test_id"])
            self.assertNotEqual(identities[0]["test_key"], identities[1]["test_key"])
            self.assertEqual({x["source_path"] for x in identities}, {str(root / "source1.py"), str(root / "source2.py")})

    def test_output_failure_is_nonzero_and_default_signals_have_unique_invocations(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "test_pass.py").write_text("import unittest\nclass Good(unittest.TestCase):\n def test_ok(self): pass\n", encoding="utf-8")
            first, rows, receipts = self.invoke(root, ["test_pass"])
            second, _, other = self.invoke(root, ["test_pass"])
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(rows[0]["outcome"], "success")
            self.assertNotEqual(receipts[-1]["invocation_id"], other[-1]["invocation_id"])
            self.assertIsNone(rows[0]["source_sha"])
            blocked = root / "existing.json"
            blocked.write_text("ORIGINAL", encoding="utf-8")
            failed, _, terminal = self.invoke(root, ["test_pass"], extra=("--outcomes-path", str(blocked)))
            self.assertNotEqual(failed.returncode, 0)
            self.assertEqual(blocked.read_text(), "ORIGINAL")
            self.assertEqual(terminal[-1]["status"], "evidence_error")
            self.assertFalse(terminal[-1]["completed"])
            self.assertEqual(list(root.glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()

"""Pure evidence projection and cross-run reconciliation regressions."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from common.gate_outcome_report import compare_reports, main, summary_to_report


def row(path="a/test_same.py", outcome="success", **extra):
    return dict(source_path=path, class_method="Tests.test_same", test_key=path+"::Tests.test_same",
                legacy_test_id="test_same.Tests.test_same", entity_kind="test", outcome=outcome,
                source_sha="source", source_file_sha256="bytes", invocation_id="random", **extra)


def report(rows, **stage):
    return summary_to_report(dict(source_sha="exact", environment={"python": "3.11"}, stages=[
        dict(name="owner", selected=True, status="PASS", test_outcomes=rows, **stage)]))


class GateOutcomeReportTests(unittest.TestCase):
    def test_two_sources_with_same_short_id_and_repeated_attempts_are_preserved(self):
        records = [row(), row("b/test_same.py"), row()]
        result = report(records)
        self.assertEqual(len(result["executions"]), 3)
        self.assertEqual([r["execution_sequence"] for r in result["executions"]], [0, 1, 2])
        pairs = compare_reports(result, report(records))["comparisons"]
        self.assertEqual(sorted(len(p["left"]) for p in pairs), [1, 2])

    def test_random_invocation_and_stage_do_not_change_canonical_matching(self):
        left = report([row()])
        right = deepcopy(left)
        right["executions"][0].update(invocation_id="other", summary_stage_name="different")
        self.assertEqual(compare_reports(left, right)["comparisons"][0]["differences"], [])

    def test_subtest_fixture_and_unknown_identity_keep_original_facts(self):
        sub = row(); sub.update(entity_kind="subtest", legacy_test_id="test_same (n=2)",
                                subtest_parent=sub["test_key"], outcome="failure", exception_summary="AssertionError: bad")
        fixture = row(); fixture.update(entity_kind="fixture", outcome="error", duration_seconds=None)
        unknown = row(); unknown.update(source_path=None, test_key=None, identity_status="unknown")
        result = report([sub, fixture, unknown])
        self.assertEqual(result["executions"][0]["subtest_parent"], sub["test_key"])
        self.assertEqual(result["executions"][1]["entity_kind"], "fixture")
        comparison = compare_reports(result, result)
        self.assertEqual(len(comparison["unidentified_left"]), 1)
        self.assertEqual(len(comparison["comparisons"]), 2)

    def test_stage_nonselection_blocking_and_legacy_duration_are_not_test_skip_or_pass(self):
        result = summary_to_report(dict(stages=[
            dict(name="unselected", selected=False, status="NOT_APPLICABLE"),
            dict(name="blocked", selected=True, status="BLOCKED"),
            dict(name="pending", selected=True, status="PENDING"),
            dict(name="old", selected=True, status="PASS", test_durations=[dict(test="x", seconds=1)])]))
        self.assertEqual([s["execution_evidence"] for s in result["stages"]],
                         ["not_selected", "blocked", "not_executed", "unknown"])
        self.assertEqual(result["executions"], [])
        self.assertTrue(result["stages"][3]["legacy_duration_only"])
        changed = deepcopy(result)
        changed["stages"][2].update(selected=False, execution_evidence="not_selected")
        changed["stages"].pop(1)
        delta = compare_reports(result, changed)
        self.assertEqual([s["name"] for s in delta["stage_comparisons"]], ["blocked", "pending"])
        self.assertEqual(delta["comparisons"], [])
        empty = summary_to_report(dict(stages=[dict(name="empty", selected=True, status="PASS",
            test_outcome_invocations=[dict(event="completed", completed=True, tests_run=0, record_count=0)])]))
        self.assertEqual(empty["stages"][0]["execution_evidence"], "observed")
        self.assertEqual(empty["executions"], [])

    def test_outcome_hash_reason_and_multiplicity_differences_are_explicit(self):
        a = row(outcome="skip", reason="no vendor")
        b = deepcopy(a); b.update(reason="no environment", source_sha="other")
        comparison = compare_reports(report([a]), report([b]))["comparisons"][0]
        self.assertEqual(comparison["differences"], ["source_identity", "reason"])
        b["outcome"] = "failure"
        self.assertIn("outcome", compare_reports(report([a]), report([b]))["comparisons"][0]["differences"])
        self.assertIn("multiplicity", compare_reports(report([a, a]), report([a]))["comparisons"][0]["differences"])
        self.assertIn("only_left", compare_reports(report([a]), report([]))["comparisons"][0]["differences"])

    def test_receipt_completeness_metadata_and_input_immutability(self):
        receipt = dict(invocation_id="x", completed=False, record_count=1, tests_run=0, repository_root="root")
        source = dict(source_sha=None, environment={"python": "exact"}, stages=[dict(
            name="fixture", selected=True, status="FAIL", test_outcomes=[row(outcome="not_completed")],
            test_outcome_invocations=[receipt])])
        before = deepcopy(source)
        result = summary_to_report(source, metadata={"source_sha": "explicit"})
        self.assertEqual(source, before)
        self.assertIsNone(result["metadata"]["source_sha"])
        self.assertEqual(result["supplied_metadata"]["source_sha"], "explicit")
        self.assertEqual(result["stages"][0]["test_outcome_invocations"], [receipt])
        self.assertEqual(result["executions"][0]["outcome"], "not_completed")

    def test_cli_report_and_compare_read_real_json_and_refuse_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root/"summary.json"; output = root/"report.json"
            source.write_text(json.dumps(dict(stages=[dict(name="actual", test_outcomes=[row()])])), encoding="utf-8")
            self.assertEqual(main(["report", "--summary", str(source), "--output", str(output)]), 0)
            comparison = root/"comparison.json"
            self.assertEqual(main(["compare", "--left", str(output), "--right", str(output), "--output", str(comparison)]), 0)
            self.assertEqual(json.loads(comparison.read_text())["comparisons"][0]["differences"], [])
            with self.assertRaises(FileExistsError):
                main(["report", "--summary", str(source), "--output", str(output)])


if __name__ == "__main__":
    unittest.main()

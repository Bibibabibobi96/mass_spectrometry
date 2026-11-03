"""Run unittest with immediate failures, timings and actual outcome evidence."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import inspect
import json
from pathlib import Path
import re
import sys
import time
import unittest
import uuid


REPO_ROOT = Path(__file__).resolve().parents[1]


def _source_identity(test: unittest.TestCase) -> dict:
    """Identify loaded source, never infer a source file from a short test ID."""
    parent = getattr(test, "test_case", test)
    legacy = test.id()
    kind = "subtest" if parent is not test else "test"
    cls = type(parent)
    method = getattr(parent, "_testMethodName", None)
    module = sys.modules.get(cls.__module__)
    class_method = f"{cls.__qualname__}.{method}" if method else legacy
    source = None
    if cls.__name__ == "_ErrorHolder" and cls.__module__ == "unittest.suite":
        kind = "fixture"
        match = re.fullmatch(r"(\w+) \((.+)\)", legacy)
        if match:
            operation, target = match.groups()
            parts = target.split(".")
            module = None
            for count in range(len(parts), 0, -1):
                module = sys.modules.get(".".join(parts[:count]))
                if module is not None:
                    class_method = ".".join([*parts[count:], operation])
                    break
    elif cls.__name__ == "_FailedTest" and cls.__module__ == "unittest.loader":
        kind = "loader"
        module = sys.modules.get(method)
        class_method = method or legacy
    else:
        try:
            source = inspect.getsourcefile(inspect.unwrap(getattr(parent, method))) if method else inspect.getsourcefile(cls)
        except (TypeError, OSError):
            source = None
    source = source or getattr(module, "__file__", None)
    path = Path(source).resolve() if source else None
    if path is not None and not path.is_file():
        path = None
    if path is None:
        source_path, digest = None, None
    else:
        try:
            source_path = path.relative_to(REPO_ROOT).as_posix()
        except ValueError:
            source_path = str(path)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return dict(source_path=source_path, source_file_sha256=digest,
                class_method=class_method, legacy_test_id=legacy, entity_kind=kind,
                identity_status="known" if path else "unknown",
                test_key=f"{source_path}::{class_method}" if path else None)


class TimedResult(unittest.TextTestResult):
    """Preserve unittest semantics while recording actual callbacks and sources."""

    def __init__(self, *args, source_sha=None, stage=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.invocation_id = uuid.uuid4().hex
        self.source_sha = source_sha
        self.stage = stage
        self.records = []
        self._pending = {}
        self._signal_stream = sys.stdout
        self._emit("TEST_OUTCOME_INVOCATION_JSON", self.receipt("started"))

    def _emit(self, prefix, value):
        self._signal_stream.write("\n" + prefix + "=" + json.dumps(value, ensure_ascii=True, separators=(",", ":")) + "\n")
        self._signal_stream.flush()

    def receipt(self, event):
        return dict(schema_version=1, invocation_id=self.invocation_id,
                    source_sha=self.source_sha, stage=self.stage, repository_root=str(REPO_ROOT), event=event,
                    completed=event == "completed", record_count=len(self.records),
                    tests_run=self.testsRun,
                    outcome_counts=dict(Counter(row["outcome"] for row in self.records)))

    def startTest(self, test):
        self._pending[id(test)] = dict(start=time.perf_counter(), outcome=None, reason=None, exception=None)
        super().startTest(test)

    def _record(self, test, outcome, reason=None, exception=None, duration=None):
        identity = _source_identity(test)
        parent = getattr(test, "test_case", None)
        row = dict(schema_version=1, invocation_id=self.invocation_id, seq=len(self.records) + 1,
                   source_sha=self.source_sha, stage=self.stage, **identity,
                   outcome=outcome, reason=reason, duration_seconds=duration,
                   exception_summary=exception,
                   subtest_parent=_source_identity(parent)["test_key"] if parent else None)
        self.records.append(row)
        self._emit("TEST_OUTCOME_JSON", row)

    def _note(self, test, outcome, reason=None, err=None):
        exception = f"{err[0].__name__}: {err[1]}" if err else None
        pending = self._pending.get(id(test))
        if pending is None:
            self._record(test, outcome, reason, exception)
        else:
            # Later successful subtests must never overwrite failure or error.
            priority = {None: -1, "success": 0, "skip": 1, "expected_failure": 2,
                        "unexpected_success": 3, "failure": 4, "error": 5}
            if priority[outcome] >= priority[pending["outcome"]]:
                pending.update(outcome=outcome, reason=reason, exception=exception)

    def stopTest(self, test):
        pending = self._pending.pop(id(test))
        elapsed = time.perf_counter() - pending["start"]
        self._record(test, pending["outcome"] or "not_completed", pending["reason"], pending["exception"], elapsed)
        self.stream.writeln(f"TEST_DURATION_SECONDS={elapsed:.6f} TEST={test.id()}")
        self.stream.flush()
        super().stopTest(test)

    def addSuccess(self, test):
        super().addSuccess(test)
        self._note(test, "success")

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self._note(test, "failure", err=err)
        self._report_error(test, err)

    def addError(self, test, err):
        super().addError(test, err)
        self._note(test, "error", err=err)
        self._report_error(test, err)

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self._note(test, "skip", reason=reason)
        parent = getattr(test, "test_case", None)
        if parent is not None:
            self._note(parent, "skip", reason=reason)

    def addExpectedFailure(self, test, err):
        super().addExpectedFailure(test, err)
        self._note(test, "expected_failure", err=err)

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        self._note(test, "unexpected_success")

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        outcome = "success" if err is None else "failure" if issubclass(err[0], test.failureException) else "error"
        self._record(subtest, outcome, exception=f"{err[0].__name__}: {err[1]}" if err else None)
        if err is not None:
            self._note(test, outcome, err=err)
            self._report_error(subtest, err)

    def _report_error(self, test, err):
        self.stream.writeln(f"TEST_FAILURE_IMMEDIATE={test.id()}")
        self.stream.writeln(self._exc_info_to_string(err, test))
        self.stream.writeln("TEST_FAILURE_IMMEDIATE_END")
        self.stream.flush()


def _publish(path, document):
    """Publish one invocation's evidence, rejecting existing output identities."""
    path = Path(path)
    if path.exists():
        raise FileExistsError(f"Outcome evidence already exists: {path}")
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(document, stream, ensure_ascii=True)
            stream.write("\n")
        temporary.rename(path)
    finally:
        temporary.unlink(missing_ok=True)


def main(argv=None):
    """Run the existing unittest CLI; explicit metadata is never inherited."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--outcomes-path")
    parser.add_argument("--source-sha")
    parser.add_argument("--stage")
    metadata, arguments = parser.parse_known_args(sys.argv[1:] if argv is None else argv)
    def result_class(*args, **kwargs):
        result = TimedResult(*args, source_sha=metadata.source_sha, stage=metadata.stage, **kwargs)
        return result

    program = unittest.main(module=None, argv=[sys.argv[0], *arguments], exit=False,
                            testRunner=unittest.TextTestRunner(resultclass=result_class))
    result = program.result
    terminal = result.receipt("completed")
    unknown = any(row["outcome"] == "not_completed" for row in result.records)
    terminal["status"] = "evidence_error" if unknown else "success" if result.wasSuccessful() else "failure"
    try:
        if metadata.outcomes_path:
            _publish(metadata.outcomes_path, dict(schema_version=1, invocation=terminal, records=result.records))
    except OSError as error:
        terminal.update(status="evidence_error", completed=False, evidence_error=str(error))
        result._emit("TEST_OUTCOME_INVOCATION_JSON", terminal)
        raise
    result._emit("TEST_OUTCOME_INVOCATION_JSON", terminal)
    return 0 if result.wasSuccessful() and not unknown else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Run the standard unittest CLI with immediate failures and per-test timings."""

from __future__ import annotations

import time
import unittest


class TimedResult(unittest.TextTestResult):
    """Report each completed test and expose exceptions before the suite ends."""

    def startTest(self, test: unittest.TestCase) -> None:
        self._test_started = time.perf_counter()
        super().startTest(test)

    def stopTest(self, test: unittest.TestCase) -> None:
        elapsed = time.perf_counter() - self._test_started
        self.stream.writeln(f"TEST_DURATION_SECONDS={elapsed:.6f} TEST={test.id()}")
        self.stream.flush()
        super().stopTest(test)

    def addFailure(self, test: unittest.TestCase, err: tuple) -> None:
        super().addFailure(test, err)
        self._report_error(test, err)

    def addError(self, test: unittest.TestCase, err: tuple) -> None:
        super().addError(test, err)
        self._report_error(test, err)

    def addSubTest(self, test: unittest.TestCase, subtest: unittest.TestCase, err: tuple | None) -> None:
        super().addSubTest(test, subtest, err)
        if err is not None:
            self._report_error(subtest, err)

    def _report_error(self, test: unittest.TestCase, err: tuple) -> None:
        self.stream.writeln(f"TEST_FAILURE_IMMEDIATE={test.id()}")
        self.stream.writeln(self._exc_info_to_string(err, test))
        self.stream.writeln("TEST_FAILURE_IMMEDIATE_END")
        self.stream.flush()


if __name__ == "__main__":
    unittest.main(module=None, testRunner=unittest.TextTestRunner(resultclass=TimedResult))

"""Owned Job PID-query tests; no solver or foreign process interaction."""

import ctypes
import subprocess
import sys
import unittest
from ctypes import wintypes
from pathlib import Path

from common.contracts.test_support import fixture_process as fixture


def result_query(responses):
    calls = []

    def query(job, kind, buffer, size, returned):
        status, assigned, ids, error = responses[len(calls)]
        calls.append((job, kind, size))
        wintypes.DWORD.from_buffer(buffer, 0).value = assigned
        wintypes.DWORD.from_buffer(buffer, 4).value = len(ids)
        for index, pid in enumerate(ids):
            ctypes.c_size_t.from_buffer(
                buffer, 8 + index * ctypes.sizeof(ctypes.c_size_t)
            ).value = pid
        last[0] = error
        return status

    last = [0]
    return query, lambda: last[0], calls


@unittest.skipUnless(
    sys.platform == "win32", "Windows Job Objects and WinError required"
)
class JobPidQueryTests(unittest.TestCase):
    def test_more_data_and_success_partial_retry_without_losing_large_pid(self):
        pid = 2**40 + 71 if ctypes.sizeof(ctypes.c_size_t) == 8 else 2**31 + 71
        query, error, calls = result_query(
            [(False, 40, [], 234), (True, 2, [1], 0), (True, 2, [1, pid], 0)]
        )
        self.assertEqual(
            fixture._job_process_ids(42, query=query, last_error=error), [1, pid]
        )
        self.assertEqual(len(calls), 3)
        self.assertTrue(calls[0][2] < calls[1][2] < calls[2][2])

    def test_winerror_inconsistent_counts_and_bounded_partial_refuse(self):
        query, error, _ = result_query([(False, 0, [], 5)])
        with self.assertRaises(OSError):
            fixture._job_process_ids(42, query=query, last_error=error)
        query, error, _ = result_query([(True, 1, [1, 2], 0)])
        with self.assertRaisesRegex(ValueError, "inconsistent"):
            fixture._job_process_ids(42, query=query, last_error=error)
        query, error, calls = result_query([(True, 2, [1], 0)] * 8)
        with self.assertRaisesRegex(RuntimeError, "assigned=2, returned=1"):
            fixture._job_process_ids(42, query=query, last_error=error)
        self.assertEqual(len(calls), 8)

    def test_actual_owned_job_empty_live_and_exited(self):
        import win32job
        from uuid import uuid4

        job = win32job.CreateJobObject(None, "owned-query-" + uuid4().hex)
        process = None
        try:
            self.assertEqual(fixture._job_process_ids(job), [])
            process = subprocess.Popen(
                [
                    sys._base_executable,
                    "-I",
                    "-B",
                    "-c",
                    "import sys;sys.stdin.buffer.read(1)",
                ],
                stdin=subprocess.PIPE,
                cwd=Path(__file__).resolve().parent,
            )
            win32job.AssignProcessToJobObject(job, int(process._handle))
            self.assertIn(process.pid, fixture._job_process_ids(job))
            process.stdin.write(b"x")
            process.stdin.flush()
            process.stdin.close()
            self.assertEqual(process.wait(timeout=10), 0)
            process._handle.Close()
            self.assertEqual(fixture._job_process_ids(job), [])
        finally:
            if process is not None and process.poll() is None:
                if process.stdin and not process.stdin.closed:
                    process.stdin.close()
                process.wait(timeout=10)
            job.Close()

"""The existing process-owned OS file lock shared by publication and capacity."""
from __future__ import annotations
import os
import time
from contextlib import contextmanager
from pathlib import Path


def acquire_exclusive_byte_lock(stream) -> None:
    """Acquire the original nonblocking exclusive byte lock; preserve OS errors."""
    if os.name == "nt":
        import msvcrt
        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def release_exclusive_byte_lock(stream) -> None:
    """Release the same process-owned lock, without changing file metadata."""
    if os.name == "nt":
        import msvcrt
        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


@contextmanager
def shared_process_file_lock(path: Path, *, timeout_seconds: float = 30.0):
    """Share the original terminal-consumption byte; exclude its publisher.

    Windows uses the existing LockFileEx protocol: FAIL_IMMEDIATELY without
    EXCLUSIVE_LOCK, offset zero, length one, including an empty lock file.
    A shared reader must never initialize the byte while another reader owns it.
    """
    if timeout_seconds < 0:
        raise ValueError("process lock timeout must be nonnegative")
    path = path.absolute()
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = path.open("a+b")
    deadline = time.monotonic() + timeout_seconds
    primary = None
    try:
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes as w
            import msvcrt

            class Overlapped(ctypes.Structure):
                _fields_ = [("Internal", ctypes.c_size_t), ("InternalHigh", ctypes.c_size_t),
                            ("Offset", w.DWORD), ("OffsetHigh", w.DWORD), ("Event", w.HANDLE)]

            api = ctypes.WinDLL("kernel32", use_last_error=True)
            api.LockFileEx.argtypes = [w.HANDLE, w.DWORD, w.DWORD, w.DWORD, w.DWORD,
                                      ctypes.POINTER(Overlapped)]
            api.LockFileEx.restype = w.BOOL
            api.UnlockFileEx.argtypes = [w.HANDLE, w.DWORD, w.DWORD, w.DWORD, ctypes.POINTER(Overlapped)]
            api.UnlockFileEx.restype = w.BOOL
            handle = msvcrt.get_osfhandle(stream.fileno())
            overlapped = Overlapped()
            while not api.LockFileEx(handle, 1, 0, 1, 0, ctypes.byref(overlapped)):
                code = ctypes.get_last_error()
                if code != 33:  # Original ERROR_LOCK_VIOLATION is the sole retryable result.
                    raise ctypes.WinError(code)
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"terminal publication is busy: {path.parent}")
                time.sleep(0.05)
            try:
                yield
            except BaseException as failure:
                primary = failure
                raise
            finally:
                if not api.UnlockFileEx(handle, 0, 1, 0, ctypes.byref(overlapped)):
                    error = ctypes.WinError(ctypes.get_last_error())
                    if primary is None:
                        raise error
                    primary.add_note(f"Shared publication guard release failed: {error!r}")
        else:
            import fcntl

            while True:
                try:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError(f"terminal publication is busy: {path.parent}")
                    time.sleep(0.05)
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
    except BaseException as failure:
        primary = failure
        raise
    finally:
        try:
            stream.close()
        except BaseException as secondary:
            if primary is None:
                raise
            primary.add_note(f"Shared publication guard close failed: {secondary!r}")


@contextmanager
def process_file_lock(path: Path, *, timeout_seconds: float = 30.0):
    """Hold an OS-owned exclusive lock, automatically released on exit."""
    if timeout_seconds < 0:
        raise ValueError("process lock timeout must be nonnegative")
    path = path.absolute()
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = path.open("a+b")
    deadline = time.monotonic() + timeout_seconds
    try:
        if os.name == "nt":
            while True:
                try:
                    stream.seek(0)
                    acquire_exclusive_byte_lock(stream)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError(f"process lock is held: {path}")
                    time.sleep(0.05)
            try:
                # Windows byte-range locks may extend beyond EOF. Initialize
                # only after exclusive acquisition: a shared terminal reader
                # can legitimately hold the first byte of an empty lock file.
                if path.stat().st_size == 0:
                    stream.write(b"\0")
                    stream.flush()
                yield
            finally:
                stream.seek(0)
                release_exclusive_byte_lock(stream)
        else:
            while True:
                try:
                    acquire_exclusive_byte_lock(stream)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError(f"process lock is held: {path}")
                    time.sleep(0.05)
            try:
                yield
            finally:
                release_exclusive_byte_lock(stream)
    finally:
        stream.close()

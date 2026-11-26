"""Host executable version evidence."""
import os
from pathlib import Path


def windows_binary_version(executable):
    """Read the selected executable's embedded fixed version, failing closed."""
    import ctypes
    from ctypes import wintypes
    if os.name != 'nt' or executable is None or not Path(executable).is_file():
        raise ValueError('SIMION executable version evidence is unavailable')
    api = ctypes.WinDLL('version', use_last_error=True)
    api.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
    api.GetFileVersionInfoSizeW.restype = wintypes.DWORD
    api.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
    api.VerQueryValueW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.UINT)]
    size = api.GetFileVersionInfoSizeW(str(executable), None)
    if not size:
        raise ValueError('SIMION executable has no version evidence')
    data = ctypes.create_string_buffer(size)
    pointer, length = ctypes.c_void_p(), wintypes.UINT()
    if not api.GetFileVersionInfoW(str(executable), 0, size, data) or not api.VerQueryValueW(data, '\\', ctypes.byref(pointer), ctypes.byref(length)) or length.value < 16:
        raise ValueError('SIMION executable version evidence is unreadable')
    words = ctypes.cast(pointer, ctypes.POINTER(wintypes.DWORD))
    if words[0] != 0xFEEF04BD:
        raise ValueError('SIMION executable version evidence is invalid')
    high, low = words[2], words[3]
    return '.'.join(str(v) for v in (high >> 16, high & 65535, low >> 16, low & 65535))

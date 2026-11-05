"""Explicit SIMION headless Lua/Fly I/O controls; no process or global policy changes.

SIMION2020 Issue468 documents allow_asynchronous_io=false as a debug option.
The caller chooses a mode for this one invocation. Getter/type/readback facts
are emitted and flushed before the command, not proof of a physical fix.
"""
from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path


_ASYNC_IO_PRELUDE = (
    "local d=assert(simion.debug,'async IO debug interface unavailable'); "
    "local before=d.allow_asynchronous_io; "
    "assert(type(before)=='boolean','async IO flag getter unverified'); "
    "print('ASYNC_IO_CONTROL before='..tostring(before)); io.stdout:flush(); "
    "d.allow_asynchronous_io=false; "
    "assert(d.allow_asynchronous_io==false,'async IO flag readback failed'); "
    "print('ASYNC_IO_CONTROL applied=false'); io.stdout:flush()"
)


def apply_native_io_mode(arguments: Sequence[str], *, allow_asynchronous_io: bool | None) -> list[str]:
    """Return a fresh argv with an explicit verified mode, or unchanged for None.

    Accept only executable + --nogui --noprompt lua|fly + payload/arguments.
    Official SIMION2020 CLI --lua executes before the given command; this
    readback is therefore pre-command, not a post-IOB-load assertion.
    Tool identity, licensing and admission remain with the execution owner.
    An existing --lua prelude is rejected rather than reordered or overwritten.
    The bundled Lua requires a readable boolean debug flag and exact readback.
    """
    if isinstance(arguments, (str, bytes)):
        raise TypeError("native arguments must be an argument sequence")
    original = list(arguments)
    if allow_asynchronous_io is None:
        return original
    if type(allow_asynchronous_io) is not bool:
        raise TypeError("allow_asynchronous_io must be boolean or None")
    if any(isinstance(value, str) and (value == '--lua' or value.startswith('--lua=')) for value in original):
        raise ValueError("Explicit native I/O mode conflicts with an existing Lua prelude")
    if (len(original) < 5 or any(not isinstance(value, str) or not value for value in original)
            or Path(original[0]).name.casefold() not in {'simion', 'simion.exe'}
            or original[1:3] != ['--nogui', '--noprompt'] or original[3] not in {'lua', 'fly'}):
        raise ValueError("Explicit native I/O mode requires a headless SIMION Lua or Fly command")
    prelude = _ASYNC_IO_PRELUDE if not allow_asynchronous_io else _ASYNC_IO_PRELUDE.replace('false', 'true')
    return original[:3] + ['--lua', prelude] + original[3:]

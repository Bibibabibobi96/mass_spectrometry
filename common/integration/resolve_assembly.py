"""Single-direction compatibility bridge to msplatform.assembly.resolve_assembly.

Retire after the named legacy consumers migrate, no later than P4.
"""
import sys
from msplatform.assembly import resolve_assembly as _core

sys.modules[__name__] = _core

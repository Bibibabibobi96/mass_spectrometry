"""Single-direction compatibility bridge to msplatform.contracts.rigid_transform.

Retire after the named legacy consumers migrate, no later than P4.
"""
import sys
from msplatform.contracts import rigid_transform as _core

sys.modules[__name__] = _core

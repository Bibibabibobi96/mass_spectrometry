"""Single-direction compatibility bridge to msplatform.contracts.particle_physics.

Retire after the named legacy consumers migrate, no later than P4.
"""
import sys
from msplatform.contracts import particle_physics as _core

sys.modules[__name__] = _core

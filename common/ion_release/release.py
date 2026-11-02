"""Single-direction compatibility bridge to msplatform.ion_release.release.

Retire after the named legacy consumers migrate, no later than P4.
"""
import sys
from msplatform.ion_release import release as _core

sys.modules[__name__] = _core

"""Single-direction compatibility bridge to msplatform.ion_release.continuous_axial_volume.

Retire after the named legacy consumers migrate, no later than P4.
"""
import sys
from msplatform.ion_release import continuous_axial_volume as _core

sys.modules[__name__] = _core

"""Single-direction compatibility bridge to msplatform.ion_release.numpy_box_cone.

Retire after the named legacy consumers migrate, no later than P4.
"""
import sys
from msplatform.ion_release import numpy_box_cone as _core

sys.modules[__name__] = _core

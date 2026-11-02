"""Single-direction compatibility bridge to msplatform.ion_release.numpy_ion11_box.

Retire after the named legacy consumers migrate, no later than P4.
"""
import sys
from msplatform.ion_release import numpy_ion11_box as _core

sys.modules[__name__] = _core

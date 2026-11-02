"""Single-direction compatibility bridge to msplatform.ion_release.mt19937_disk_cone_rf_phase.

Retire after the named legacy consumers migrate, no later than P4.
"""
import sys
from msplatform.ion_release import mt19937_disk_cone_rf_phase as _core

sys.modules[__name__] = _core

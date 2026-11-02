"""Single-direction compatibility bridge to msplatform.analysis.peak_metrics.

Retire after the named legacy consumers migrate, no later than P4.
"""
import sys
from msplatform.analysis import peak_metrics as _core

sys.modules[__name__] = _core

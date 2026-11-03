"""Single-direction bridge to msplatform.analysis.particle_census.

Legacy callers: RF component_port; IP admission/component_exit/functional;
MR handoff/measured_component source+analysis; local_frontend analysis and
frozen inventories. Migrate named callers and remove this bridge by P4.
"""
import sys
from msplatform.analysis import particle_census as _core

sys.modules[__name__] = _core

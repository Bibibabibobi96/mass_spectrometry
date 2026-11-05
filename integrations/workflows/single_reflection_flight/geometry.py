"""One-way compatibility bridge; retire named outer consumers no later than P4."""
import sys
from msplatform.backends.simion import geometry as _backend

sys.modules[__name__] = _backend

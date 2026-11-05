"""One-way compatibility bridge; retire named outer consumers no later than P4."""
import sys
from msplatform.backends.simion import accelerator_renderer as _backend

sys.modules[__name__] = _backend

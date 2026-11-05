"""Legacy import bridge to the installed native tracking collector."""
import sys
from msplatform.backends.simion import tracking_collection as _core

sys.modules[__name__] = _core

"""Repository-only single-way bridge; canonical implementation: msplatform.execution.immutable_pa_parity."""
from msplatform.execution import immutable_pa_parity as _core

import sys
sys.modules[__name__] = _core

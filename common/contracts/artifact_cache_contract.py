"""Repository-only single-way bridge; canonical implementation: msplatform.execution.artifact_cache_contract."""
from msplatform.execution import artifact_cache_contract as _core

import sys
sys.modules[__name__] = _core

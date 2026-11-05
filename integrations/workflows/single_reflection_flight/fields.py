"""One-way field science bridge; execution and receipts remain outside."""
import sys
from msplatform.backends.simion import fields as _backend
sys.modules[__name__] = _backend

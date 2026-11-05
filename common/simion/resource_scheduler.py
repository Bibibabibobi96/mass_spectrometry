"""Legacy dispatch import/CLI bridge; canonical execution owner, retire by P4."""
from msplatform.execution import simion_dispatch as _core

if __name__ == "__main__":
    raise SystemExit(_core.main())
else:
    import sys
    sys.modules[__name__] = _core

"""Single-direction compatibility bridge to msplatform.ion_release.dotnet_gaussian_box_ion11.

Retire after the named legacy consumers migrate, no later than P4.
"""
import sys
from msplatform.ion_release import dotnet_gaussian_box_ion11 as _core

if __name__ == "__main__":
    raise SystemExit(_core.main())

sys.modules[__name__] = _core

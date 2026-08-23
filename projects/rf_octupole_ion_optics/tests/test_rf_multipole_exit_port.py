import unittest
from pathlib import Path

from common.multipole.rf_multipole_exit_port_test_support import (
    assert_authority_bindings_and_freshness,
    assert_derived_exit_geometry_clock_and_field_boundary,
    set_up_exit_port_contract,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
class RfMultipoleExitPortTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        set_up_exit_port_contract(cls, PROJECT_ROOT, "rf_octupole_ion_optics")

    def test_schema_authority_bindings_and_freshness(self) -> None:
        assert_authority_bindings_and_freshness(self)

    def test_exit_geometry_clock_and_field_boundary_are_derived(self) -> None:
        assert_derived_exit_geometry_clock_and_field_boundary(self)


if __name__ == "__main__":
    unittest.main()

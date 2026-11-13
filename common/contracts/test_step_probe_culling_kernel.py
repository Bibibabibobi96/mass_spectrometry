"""Compare STEP probe culling with exhaustive OCCT classification."""
import hashlib
import importlib.util
import importlib.metadata
from pathlib import Path
import unittest


class StepProbeCullingKernelTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec('cadquery'), 'optional CadQuery engine unavailable')
    def test_real_solids_match_exhaustive_classification(self):
        import cadquery as cq
        import OCP
        from msplatform.exporters import step

        tolerance = step._cad_precision_profile()["occt_confusion"]
        box = cq.Workplane("XY").box(4, 6, 8).val()
        tube = (cq.Workplane("XY").circle(3).circle(1).extrude(5).val()
                .translate((12, -3, 2)))
        curved = (cq.Workplane("XY").circle(2).extrude(7).val()
                  .rotate((0, 0, 0), (0, 1, 0), 37).translate((-10, 5, -4)))
        solids = [box, tube, curved]
        cached = step._probe_solid_bounds(solids)
        points = [(0., 0., 0.), (12., -3., 4.), (14., -3., 4.),
                  (-10., 5., -4.), (100., 100., 100.), (-100., -100., -100.)]
        # Probe both ends of every actual kernel box, on the exact boundary and
        # at one existing OCCT confusion distance on either side. No new tolerance.
        for solid in solids:
            bounds = solid.BoundingBox()
            axes = ((bounds.xmin, bounds.xmax), (bounds.ymin, bounds.ymax),
                    (bounds.zmin, bounds.zmax))
            center = [(lo + hi) / 2 for lo, hi in axes]
            for axis, pair in enumerate(axes):
                for boundary in pair:
                    for offset in (-tolerance, 0., tolerance):
                        point = center.copy()
                        point[axis] = boundary + offset
                        points.append(tuple(point))
        # Include reversed and overlapping lists so the original any() order and
        # early exit are exercised with overlapping solids and empty input.
        for sequence in (solids, list(reversed(solids)), [box, box], []):
            bounded = step._probe_solid_bounds(sequence)
            for point in points:
                expected = any(solid.isInside(point, tolerance) for solid in sequence)
                self.assertEqual(step._probe_inside(bounded, point, tolerance), expected,
                                 (point, tolerance, len(sequence)))
        self.assertEqual(len(cached), len(solids))
        for label, module in (("cadquery", cq), ("OCP", OCP), ("exporter", step)):
            path = Path(module.__file__).resolve()
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            print(f"CULLING_MODULE {label} {path} sha256={digest}")
        print("CULLING_VERSIONS cadquery=" + importlib.metadata.version("cadquery")
              + " cadquery-ocp=" + importlib.metadata.version("cadquery-ocp")
              + f" occt_confusion={tolerance!r} points={len(points)}")

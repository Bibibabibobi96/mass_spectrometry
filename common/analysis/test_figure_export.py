"""Real raster/vector export and fail-closed batch destination regressions."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

import matplotlib
matplotlib.use("Agg")
from matplotlib import pyplot as plt
from PIL import Image

from common.analysis.figure_export import export_figures


class FigureExportTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory(prefix="figure_export_")
        self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        self.figure,self.axes=plt.subplots(figsize=(2.,1.))
        self.axes.plot([0.,1.],[1.,0.]);self.axes.set_title("Recorded data")
        self.addCleanup(plt.close,self.figure)

    def test_real_png_svg_records_match_dimensions_format_size_and_explicit_style(self):
        # Dots in an explicit stem are preserved, not treated as extensions.
        records=export_figures({self.root/"source.v1":self.figure},formats=("png","svg"),dpi=80,facecolor="white")
        self.assertEqual([Path(row["path"]).name for row in records],["source.v1.png","source.v1.svg"])
        self.assertEqual(json.loads(json.dumps(records)),records)
        for row in records:
            self.assertEqual(row["size_inches"],[2.,1.])
            self.assertEqual(row["bytes"],Path(row["path"]).stat().st_size)
            self.assertGreater(row["bytes"],0)
            self.assertEqual(row["savefig_dpi"],80)
            self.assertEqual(row["facecolor"],"white")
        with Image.open(records[0]["path"]) as image:
            self.assertEqual(image.format,"PNG")
            self.assertEqual(image.size,(160,80))
            self.assertEqual(image.getpixel((0,0)),(255,255,255,255))
        vector=ET.parse(records[1]["path"]).getroot()
        self.assertEqual(vector.tag,"{http://www.w3.org/2000/svg}svg")
        self.assertEqual(vector.attrib["width"],"144pt")
        self.assertEqual(vector.attrib["height"],"72pt")
        self.assertTrue(plt.fignum_exists(self.figure.number))

    def test_entire_batch_is_preflighted_before_any_save(self):
        protected=self.root/"later.svg";protected.write_bytes(b"existing owned result")
        with patch.object(self.figure,"savefig",wraps=self.figure.savefig) as save:
            with self.assertRaises(FileExistsError):
                export_figures({self.root/"first":self.figure,self.root/"later":self.figure},
                               formats=("png","svg"),dpi=80,facecolor="white")
            save.assert_not_called()
        self.assertEqual(sorted(p.name for p in self.root.iterdir()),["later.svg"])
        self.assertEqual(protected.read_bytes(),b"existing owned result")

    def test_alias_destination_duplicate_and_missing_parent_are_preflight_errors(self):
        (self.root/"nested").mkdir()
        with patch.object(self.figure,"savefig",wraps=self.figure.savefig) as save:
            with self.assertRaisesRegex(ValueError,"duplicate figure destination"):
                export_figures({self.root/"same":self.figure,self.root/"nested/../same":self.figure},
                               formats=("png",),dpi=80,facecolor="white")
            with self.assertRaises(FileNotFoundError):
                export_figures({self.root/"missing/figure":self.figure},formats=("png",),dpi=80,facecolor="white")
            save.assert_not_called()

    def test_failed_later_save_cleans_only_this_batch_and_propagates_original_error(self):
        protected=self.root/"unrelated.txt";protected.write_bytes(b"keep")
        original=self.figure.savefig
        def fail_svg(stream,**kwargs):
            if kwargs["format"]=="svg":
                stream.write(b"partial vector")
                raise RuntimeError("render failed")
            return original(stream,**kwargs)
        with patch.object(self.figure,"savefig",side_effect=fail_svg):
            with self.assertRaisesRegex(RuntimeError,"render failed"):
                export_figures({self.root/"failed":self.figure},formats=("png","svg"),dpi=80,facecolor="white")
        self.assertEqual(sorted(p.name for p in self.root.iterdir()),["unrelated.txt"])
        self.assertEqual(protected.read_bytes(),b"keep")
        self.assertTrue(plt.fignum_exists(self.figure.number))

    def test_invalid_formats_and_dpi_do_not_write(self):
        for formats,dpi in ((("png","png"),80),(("not-a-format",),80),(("png",),0),
                            (("png",),float("nan")),(("png",),float("inf")),(("png",),True)):
            with self.subTest(formats=formats,dpi=dpi),self.assertRaises(ValueError):
                export_figures({self.root/"invalid":self.figure},formats=formats,dpi=dpi,facecolor="white")
        self.assertEqual(list(self.root.iterdir()),[])


if __name__=="__main__":
    unittest.main()

"""Regression checks for the shipped fonts: python -m unittest discover -s revival."""
import unittest

from fontTools.ttLib import TTFont

from finish_fonts import FONTS, glyph_bounds, update_ink_metrics


class FontTests(unittest.TestCase):
    def test_windows_metrics_contain_every_outline(self):
        for path in sorted(FONTS.glob("*.otf")):
            font = TTFont(path)
            os2 = font["OS/2"]
            for name in font.getGlyphOrder():
                with self.subTest(font=path.name, glyph=name):
                    box = glyph_bounds(font, name)
                    if box:
                        self.assertLessEqual(box[3], os2.usWinAscent)
                        self.assertGreaterEqual(box[1], -os2.usWinDescent)

    def test_clipping_repair_preserves_leading_and_outlines(self):
        font = TTFont(FONTS / "Mills8A-Regular.otf")
        metrics = (font["hhea"].ascent, font["hhea"].descent,
                   font["hhea"].lineGap, font["OS/2"].sTypoAscender,
                   font["OS/2"].sTypoDescender, font["OS/2"].sTypoLineGap)
        box = glyph_bounds(font, "Aring")
        font["OS/2"].usWinAscent = 900
        update_ink_metrics(font)
        self.assertEqual(box, glyph_bounds(font, "Aring"))
        self.assertEqual(metrics, (font["hhea"].ascent, font["hhea"].descent,
                                  font["hhea"].lineGap, font["OS/2"].sTypoAscender,
                                  font["OS/2"].sTypoDescender, font["OS/2"].sTypoLineGap))


if __name__ == "__main__":
    unittest.main()

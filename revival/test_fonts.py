"""Regression checks for the shipped fonts: python -m unittest discover -s revival."""
import unittest
import unicodedata
import uharfbuzz as hb

from fontTools.ttLib import TTFont

from finish_fonts import FONTS, glyph_bounds, normalize_accent_advances, update_ink_metrics


def shape(path, text, features=None):
    font = TTFont(path)
    hbfont = hb.Font(hb.Face(path.read_bytes()))
    hbfont.scale = (1000, 1000)
    buffer = hb.Buffer()
    buffer.add_str(text)
    buffer.guess_segment_properties()
    hb.shape(hbfont, buffer, {"rand": False, **(features or {})})
    return [(font.getGlyphName(info.codepoint), pos)
            for info, pos in zip(buffer.glyph_infos, buffer.glyph_positions)]


class FontTests(unittest.TestCase):
    def test_smallcaps_are_selectable_in_every_roman_style(self):
        for style in ("Regular", "Regular9", "Bold"):
            with self.subTest(style=style):
                glyphs = shape(FONTS / f"Mills8A-{style}.otf", "abcxyz", {"smcp": True})
                self.assertEqual([name for name, _ in glyphs],
                                 [ch + ".sc" for ch in "abcxyz"])

    def test_accents_keep_the_base_letter_advance(self):
        for path in sorted(FONTS.glob("*.otf")):
            font = TTFont(path)
            if "MATH" in font:
                continue
            cmap = font.getBestCmap()
            for cp, name in cmap.items():
                ch = chr(cp)
                d = unicodedata.normalize("NFD", ch)
                if (ch.isalpha() and len(d) > 1 and ord(d[0]) in cmap
                        and all(unicodedata.combining(c) for c in d[1:])):
                    with self.subTest(font=path.name, character=ch):
                        self.assertEqual(font["hmtx"][name][0],
                                         font["hmtx"][cmap[ord(d[0])]][0])

    def test_accent_spacing_repair_keeps_traced_ink(self):
        font = TTFont(FONTS / "Mills8A-Regular.otf")
        box = glyph_bounds(font, "aacute")
        font["hmtx"].metrics["aacute"] = (378, font["hmtx"]["aacute"][1])
        normalize_accent_advances(font)
        self.assertEqual(box, glyph_bounds(font, "aacute"))
        self.assertEqual(font["hmtx"]["a"][0], font["hmtx"]["aacute"][0])

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

"""Finish the committed OpenType fonts, without repeating OCR or tracing.

Also run at the end of build.sh, before the pdfTeX conversion. The typographic
line metrics are kept separate from the Windows metrics used for clipping.
"""
import argparse
import math
from pathlib import Path

from fontTools.pens.boundsPen import BoundsPen
from fontTools.ttLib import TTFont

FONTS = Path(__file__).resolve().parent / "fonts"


def glyph_bounds(font, name):
    glyphs = font.getGlyphSet()
    pen = BoundsPen(glyphs)
    glyphs[name].draw(pen)
    return pen.bounds


def update_ink_metrics(font):
    boxes = [glyph_bounds(font, name) for name in font.getGlyphOrder()]
    boxes = [box for box in boxes if box is not None]
    os2 = font["OS/2"]
    # These are clipping bounds, not a request to change the document's leading.
    os2.usWinAscent = max(os2.usWinAscent, math.ceil(max(b[3] for b in boxes)))
    os2.usWinDescent = max(os2.usWinDescent, math.ceil(-min(b[1] for b in boxes)))
    cmap = font.getBestCmap()
    for ch, field in (("x", "sxHeight"), ("H", "sCapHeight")):
        if ord(ch) in cmap:
            setattr(os2, field, round(glyph_bounds(font, cmap[ord(ch)])[3]))


def finish(font):
    update_ink_metrics(font)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fonts", nargs="*", type=Path,
                        help="OTF files; defaults to revival/fonts/*.otf")
    args = parser.parse_args()
    for path in args.fonts or sorted(FONTS.glob("*.otf")):
        font = TTFont(path)
        finish(font)
        font.save(path)
        print(f"Finished {path.name}")


if __name__ == "__main__":
    main()

"""Consistency checks over the built fonts; prints what looks wrong.

* baseline: letters with flat (serif) bottoms sit within +-TOL units of 0;
* descenders: g j p q y Q (and the roman J) reach below the line;
* x-height: flat-topped lowercase reach the same height;
* cap height: flat-topped capitals reach the same height;
* side bearings: no glyph's left or right bearing is far outside its kind's;
* figures: one width;
* script sorts (math font .st/.sts and ssty variants): their shape, scaled to
  the text glyph's box, overlaps the text glyph (a misfiled impression,
  e.g. an i filed as s, does not).
"""
import os
import sys

import numpy as np
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.freetypePen import FreeTypePen
from fontTools.ttLib import TTFont

HERE = os.path.dirname(os.path.abspath(__file__))
FONTS = os.path.join(HERE, "fonts")
TOL = 14
FLAT_BOTTOM_LC = "hiklmnrx"
FLAT_BOTTOM_UC = "BDEFHIKLMPRTXZ"
FLAT_TOP_LC = "vwxyz"
FLAT_TOP_UC = "BDEFHIKLMNPRTXZ"
DESCENDERS = "gjpqyQ"                # and the roman J, below the line in Modern 8A
problems = []


def report(msg):
    problems.append(msg)
    print("  " + msg)


def bounds(gs, n):
    p = BoundsPen(gs)
    gs[n].draw(p)
    return p.bounds


def check_text(name, italic=False, smallcaps=False):
    f = TTFont(os.path.join(FONTS, name))
    gs, cm, hm = f.getGlyphSet(), f.getBestCmap(), f["hmtx"]
    print(name)

    def g(ch):
        n = cm.get(ord(ch))
        return n if n in gs else None

    def band(label, chars, idx, ref=None):
        vals = {c: bounds(gs, g(c))[idx] for c in chars if g(c)}
        if len(vals) < 3:
            return
        med = np.median(list(vals.values())) if ref is None else ref
        for c, v in vals.items():
            if abs(v - med) > TOL:
                report(f"{name}: {label} {c} at {v:.0f} (others {med:.0f})")

    band("baseline", FLAT_BOTTOM_LC, 1, 0)
    band("baseline", FLAT_BOTTOM_UC, 1, 0)
    for c in DESCENDERS + ("" if italic else "J"):
        if g(c) and bounds(gs, g(c))[1] > -80:
            report(f"{name}: descender {c} reaches only {bounds(gs, g(c))[1]:.0f}")
    band("x-height", FLAT_TOP_LC, 3)
    band("cap height", FLAT_TOP_UC, 3)
    # side bearings: lowercase and capitals separately, robust z-score
    for chars in ("abcdeghkmnopqrsuvwxyz", "ABCDEFGHIKLMNOPRSTUVWXYZ"):
        lsb, rsb = {}, {}
        for c in chars:
            n = g(c)
            if not n:
                continue
            b = bounds(gs, n)
            lsb[c], rsb[c] = b[0], hm[n][0] - b[2]
        for label, d in (("left", lsb), ("right", rsb)):
            v = np.array(list(d.values()))
            med, mad = np.median(v), np.median(np.abs(v - np.median(v))) + 5
            for c, x in d.items():
                if abs(x - med) > 5 * mad and abs(x - med) > 40:
                    report(f"{name}: {label} side bearing of {c} {x:.0f} (typical {med:.0f})")
    widths = {d: hm[g(d)][0] for d in "0123456789" if g(d)}
    if widths and len(set(widths.values())) > 1:
        report(f"{name}: figures of unequal width {widths}")
    if smallcaps:
        sc = {c: bounds(gs, c.lower() + ".sc") for c in FLAT_TOP_UC if c.lower() + ".sc" in gs}
        if sc:
            tops = {c: b[3] for c, b in sc.items()}
            med = np.median(list(tops.values()))
            for c, t in tops.items():
                if abs(t - med) > TOL:
                    report(f"{name}: small cap {c} top {t:.0f} (others {med:.0f})")
            for c, b in sc.items():
                if c in FLAT_BOTTOM_UC and abs(b[1]) > TOL:
                    report(f"{name}: small cap {c} baseline {b[1]:.0f}")


def raster(gs, n, box, size=64):
    """Glyph n drawn into a size x size grid, its ink box scaled to box."""
    pen = FreeTypePen(gs)
    gs[n].draw(pen)
    b = bounds(gs, n)
    x0, y0, x1, y1 = b
    sx, sy = size / max(1, x1 - x0), size / max(1, y1 - y0)
    img = pen.array(width=size, height=size,
                    transform=(sx, 0, 0, sy, -x0 * sx, -y0 * sy), contain=False)
    return img > 0.5


def check_scripts():
    name = "Mills8A-Math.otf"
    f = TTFont(os.path.join(FONTS, name))
    gs = f.getGlyphSet()
    print(name, "script variants")
    ssty = {}
    for fr in f["GSUB"].table.FeatureList.FeatureRecord:
        if fr.FeatureTag == "ssty":
            for li in fr.Feature.LookupListIndex:
                for st in f["GSUB"].table.LookupList.Lookup[li].SubTable:
                    if hasattr(st, "alternates"):
                        ssty.update(st.alternates)
    cm = f.getBestCmap()
    base = set(cm.values())
    for n, vs in ssty.items():
        if n not in base or n not in gs:
            continue
        try:
            a = raster(gs, n, None)
        except Exception:
            continue
        if a.sum() < 30:
            continue
        for v in vs:
            if v not in gs:
                continue
            try:
                b = raster(gs, v, None)
            except Exception:
                continue
            iou = (a & b).sum() / max(1, (a | b).sum())
            ba, bb = bounds(gs, n), bounds(gs, v)
            ra = (ba[2] - ba[0]) / max(1, ba[3] - ba[1])
            rb = (bb[2] - bb[0]) / max(1, bb[3] - bb[1])
            if iou < 0.45 or abs(np.log(rb / ra)) > 0.45:
                ch = next((chr(k) for k, x in cm.items() if x == n), n)
                report(f"{name}: script variant {v} of {ch} unlike its text glyph "
                       f"(overlap {iou:.2f}, aspect {rb:.2f} vs {ra:.2f})")


def main():
    check_text("Mills8A-Regular.otf", smallcaps=True)
    check_text("Mills8A-Italic.otf", italic=True)
    check_text("Mills8A-Bold.otf")
    check_text("Mills8A-BoldItalic.otf", italic=True)
    check_text("Mills8A-Regular9.otf")
    check_text("Mills8A-Italic9.otf", italic=True)
    check_scripts()
    print(f"{len(problems)} problems")
    return 1 if problems and "--strict" in sys.argv else 0


if __name__ == "__main__":
    sys.exit(main())

"""The other members of the family, built on the 11pt fonts:

  Mills8A-Bold.otf      11pt bold, for titles: the 1947 bold title capitals
                        where the scans have them, the rest the regular
                        glyphs thickened to the measured bold stem weight
  Mills8A-Regular9.otf  9pt (footnotes, references): the 1947 9pt sorts with
  Mills8A-Italic9.otf   their own fitted spacing, the rest the 11pt glyphs
                        thickened to the 9pt sorts' relative weight

A font used at 9pt scales its glyphs by 9/11 against the 11pt fonts, so the
fill-in glyphs keep the 11pt outlines and are only thickened; real 9pt sorts
are traced at their printed size in units of the 9pt em.
"""
import os
import pickle

import numpy as np
from fontTools.fontBuilder import FontBuilder
from fontTools.feaLib.builder import addOpenTypeFeaturesFromString
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.t2CharStringPen import T2CharStringPen
from fontTools.ttLib import TTFont

import build_font as bf
from build_math import outline_from_glyph, outline_from_master, charstring, bounds

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, "work")
FONTS = os.path.join(HERE, "fonts")
UP = bf.UP


def stem(m):
    return bf.stem_width(m["img"]) / UP                      # scan px


def measured_grow(M, style, size, letters, ratio):
    """Half the difference between the stems of real `size` sorts and the
    11pt stems scaled by `ratio` (scan px at the printed size)."""
    d = [(stem(M[(g, style, size)]) - ratio * stem(M[(g, base_style, 11)])) / 2
         for g in letters for base_style in [style if style != "B" else "R"]
         if (g, style, size) in M and (g, base_style, 11) in M and M[(g, style, size)]["n"] >= 3]
    return max(0.0, float(np.median(d))) if d else 0.0


def make(out, family, style_name, base_otf, real, em_pt, grow_print, spacing=None,
         features="", italic=False):
    """real: {char: master}; grow_print: scan px of extra weight per edge at
    the printed size for glyphs taken from base_otf; spacing: {char: (lsb,
    adv)} in scan px at the printed size, for real sorts."""
    base = TTFont(base_otf)
    gs = base.getGlyphSet()
    cmap = base.getBestCmap()
    names = {}
    for k, v in sorted(cmap.items(), reverse=True):   # plain letters win over
        names[v] = chr(k)                             # their math-italic code points
    keep = [n for n in base.getGlyphOrder()
            if n in names or n in ("fi", "fl", "f_f", "f_f_i", "f_f_l") or n.endswith(".sc")]
    u_print = 1000 / (em_pt * bf.PX_PER_PT)                   # units per scan px
    f = 11 / em_pt                                            # 11pt units -> these units
    top = TTFont(os.path.join(FONTS, "Mills8A-Regular.otf"))["CFF "].cff.topDictIndex[0]
    private, gsubrs = top.Private, top.GlobalSubrs
    cs, adv = {}, {}
    n_real = 0
    for n in keep:
        ch = names.get(n)
        a = base["hmtx"][n][0]
        bp = BoundsPen(gs)
        gs[n].draw(bp)
        b = bp.bounds or (0, 0, 0, 0)
        if ch in real:
            contours, dx, dy, w = outline_from_master(real[ch], bf.INK_PX)
            # traced at 11pt units; this font's em is em_pt
            w_u = w * f
            if spacing and ch in spacing:
                lsb_u, adv_u = spacing[ch][0] * u_print, spacing[ch][1] * u_print
            else:                                 # the base glyph's side bearings
                lsb_u, adv_u = b[0], b[0] + w_u + (a - b[2])
            cs[n] = charstring(contours, dx * f + lsb_u, dy * f, bf.U_PER_UPX * f, adv_u,
                               private, gsubrs)
            # sit on the baseline like the base glyph (a real sort's master
            # inherits its lines' baseline errors)
            shift = b[1] * (w_u / max(1, b[2] - b[0])) - bounds(cs[n])[1]
            if abs(shift) > 2:
                cs[n] = charstring(contours, dx * f + lsb_u, dy * f + shift,
                                   bf.U_PER_UPX * f, adv_u, private, gsubrs)
            adv[n] = round(adv_u)
            n_real += 1
        else:
            g11 = grow_print * em_pt / 11                     # the same px at 11pt scale
            o = outline_from_glyph(gs, n, g11) if b != (0, 0, 0, 0) else None
            if o is None:
                pen = T2CharStringPen(a, gs)
                gs[n].draw(pen)
                cs[n] = pen.getCharString(private, gsubrs)
                adv[n] = a
                continue
            contours, dx, dy = o
            gu = g11 * bf.U_PER_PX
            cs[n] = charstring(contours, dx + gu, dy, bf.U_PER_UPX, a + 2 * gu, private, gsubrs)
            adv[n] = round(a + 2 * gu)
    order = [".notdef", "space"] + [n for n in keep if n not in (".notdef", "space")]
    pen = T2CharStringPen(500, None)
    pen.moveTo((50, 0)); pen.lineTo((450, 0)); pen.lineTo((450, 700)); pen.lineTo((50, 700))
    pen.closePath()
    cs[".notdef"] = pen.getCharString(private, gsubrs)
    cs["space"] = T2CharStringPen(bf.SPACE, None).getCharString(private, gsubrs)
    adv[".notdef"], adv["space"] = 500, bf.SPACE
    fb = FontBuilder(1000, isTTF=False)
    fb.setupGlyphOrder(order)
    fb.setupCharacterMap({k: v for k, v in cmap.items() if v in cs})
    ps = f"{family}-{style_name}".replace(" ", "")
    fb.setupCFF(ps, {"FullName": f"{family} {style_name}"}, {n: cs[n] for n in order}, {})
    fb.setupHorizontalMetrics({n: (adv[n], round(bounds(cs[n])[0])) for n in order})
    fb.setupHorizontalHeader(ascent=800, descent=-250)
    fb.setupNameTable({"familyName": family, "styleName": style_name})
    fb.setupOS2(sTypoAscender=800, sTypoDescender=-250, usWinAscent=900, usWinDescent=300,
                sxHeight=440, sCapHeight=650,
                fsSelection=(0x01 if italic else 0) | (0x20 if "Bold" in style_name else 0) or 0x40,
                usWeightClass=700 if "Bold" in style_name else 400)
    fb.setupPost(italicAngle=-14 if italic else 0)
    fb.updateHead(macStyle=(2 if italic else 0) | (1 if "Bold" in style_name else 0))
    if features:
        addOpenTypeFeaturesFromString(fb.font, features)
    fb.save(out)
    print(f"wrote {out}: {len(order)} glyphs, {n_real} traced from real "
          f"{em_pt}pt{' bold' if 'Bold' in style_name else ''} sorts")


def liga(names):
    rules = [r for r, need in (("sub f f i by f_f_i;", "f_f_i"), ("sub f f l by f_f_l;", "f_f_l"),
                               ("sub f f by f_f;", "f_f"), ("sub f i by fi;", "fi"),
                               ("sub f l by fl;", "fl")) if need in names]
    if not rules:
        return ""
    return ("languagesystem DFLT dflt;\nlanguagesystem latn dflt;\n"
            "feature liga { " + " ".join(rules) + " } liga;\n")


def main():
    M = pickle.load(open(os.path.join(WORK, "masters.pkl"), "rb"))
    reg = os.path.join(FONTS, "Mills8A-Regular.otf")
    ita = os.path.join(FONTS, "Mills8A-Italic.otf")

    # bold: thicken by half the measured difference of bold and roman stems
    bold = {g: m for (g, s, z), m in M.items() if s == "B" and z == "T" and m["n"] >= 2}
    gb = measured_grow(M, "B", "T", "ABEILMNPRT", 1.0)
    print(f"bold: {len(bold)} real capitals ({''.join(sorted(bold))}); "
          f"the rest thickened by {gb:.2f} px per edge")
    make(os.path.join(FONTS, "Mills8A-Bold.otf"), "Mills 8A", "Bold", reg, bold, 11, gb,
         features=liga(TTFont(reg).getGlyphOrder()))
    # bold italic: no 1947 source at all; the italic thickened like the
    # bold fill-ins
    make(os.path.join(FONTS, "Mills8A-BoldItalic.otf"), "Mills 8A", "Bold Italic", ita, {}, 11,
         gb, features=liga(TTFont(ita).getGlyphOrder()), italic=True)

    # 9pt: real sorts with their own spacing fit
    for style, base, name in (("R", reg, "Regular9"), ("I", ita, "Italic9")):
        real = {g: m for (g, s, z), m in M.items() if s == style and z == 9 and m["n"] >= 3
                and len(g) == 1}
        g9 = measured_grow(M, style, 9, "nmhuoeadlri1234", 9 / 11)
        widths = {g: (np.ptp(np.nonzero((bf.despeckle(m["img"]) > 0.5).any(0))[0]) + 1) / UP
                  for g, m in real.items()}
        # both have enough footnote and reference lines for their own fit
        # (glyphs without measured pairs keep the 11pt side bearings, scaled)
        sp = bf.fit_spacing(style, 9, widths) if widths else {}
        sp = {g: v for g, v in sp.items() if g in real}
        print(f"9pt {style}: {len(real)} real sorts; the rest thickened by {g9:.2f} px per edge")
        make(os.path.join(FONTS, f"Mills8A-{name}.otf"), "Mills 8A", name, base, real, 9, g9,
             spacing=sp, features=liga(TTFont(base).getGlyphOrder()), italic=style == "I")


if __name__ == "__main__":
    main()

"""Accented letters for the Mills 8A text fonts (run after build_font.py).

The 1947 pages contain one accent: the dieresis of Erdos's o, which becomes
the roman dieresis.  The other accents have no 1947 source; they are Latin
Modern's (Computer Modern descends from the same Monotype Modern), thickened
to the measured Mills 8A stroke weight.  Composites are built for every
Latin-1 and Latin Extended-A letter that decomposes into a base letter and
one supported accent, using the dotless i and j cut from the 1947 i and j.
"""
import os
import subprocess
import unicodedata

import numpy as np
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.recordingPen import RecordingPen
from fontTools.pens.t2CharStringPen import T2CharStringPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from fontTools.pens.freetypePen import FreeTypePen

import build_font as bf
from build_math import outline_from_glyph, charstring, bounds

HERE = os.path.dirname(os.path.abspath(__file__))
FONTS = os.path.join(HERE, "fonts")

MARKS = {0x300: "grave", 0x301: "acute", 0x302: "circumflex", 0x303: "tilde",
         0x308: "dieresis", 0x30A: "ring", 0x30C: "caron", 0x306: "breve", 0x304: "macron",
         0x30B: "hungarumlaut", 0x307: "dotaccent", 0x327: "cedilla"}
SPACING = {"grave": 0x60, "acute": 0xB4, "dieresis": 0xA8, "macron": 0xAF, "cedilla": 0xB8,
           "circumflex": 0x2C6, "caron": 0x2C7, "breve": 0x2D8, "dotaccent": 0x2D9,
           "ring": 0x2DA, "tilde": 0x2DC, "hungarumlaut": 0x2DD}
SIDE_CARON = set("dlLt")                  # ď ľ Ľ ť take a raised comma, not a caron
SLANT = {"Regular": 0.0, "Italic": 0.25}


def lm(style):
    name = {"Regular": "lmroman10-regular.otf", "Italic": "lmroman10-italic.otf"}[style]
    return TTFont(subprocess.run(["kpsewhich", name], check=True, capture_output=True,
                                 text=True).stdout.strip())


def record(gs, name, dx=0, dy=0):
    rec = RecordingPen()
    gs[name].draw(TransformPen(rec, (1, 0, 0, 1, dx, dy)))
    return rec


def gbounds(gs, name):
    bp = BoundsPen(gs)
    gs[name].draw(bp)
    return bp.bounds


def stem(gs, name):
    """Typical vertical stem width in font units (raster at 4 px/unit^-1)."""
    pen = FreeTypePen(gs)
    gs[name].draw(pen)
    b = gbounds(gs, name)
    s = 0.5
    img = pen.array(width=int((b[2] - b[0]) * s) + 8, height=int((b[3] - b[1]) * s) + 8,
                    transform=(s, 0, 0, s, 4 - b[0] * s, 4 - b[1] * s))
    return bf.stem_width(img) / bf.UP / s * bf.UP                 # px -> units


def contours_filtered(gs, name, keep):
    """RecordingPen of the contours of `name` whose bounds satisfy keep()."""
    rec = RecordingPen()
    gs[name].draw(rec)
    out, cur = RecordingPen(), []
    for op, args in rec.value:
        cur.append((op, args))
        if op in ("closePath", "endPath"):
            pts = [p for _, a in cur for p in a]
            ys = [p[1] for p in pts]
            if pts and keep(min(ys), max(ys)):
                out.value += cur
            cur = []
    return out


def main():
    for style in ("Regular", "Italic"):
        path = os.path.join(FONTS, f"Mills8A-{style}.otf")
        font = TTFont(path)
        gs = font.getGlyphSet()
        cmap = font.getBestCmap()
        names = {chr(k): v for k, v in cmap.items()}
        L = lm(style)
        lgs = L.getGlyphSet()
        xh = np.median([gbounds(gs, names[c])[3] for c in "xvwz" if c in names])
        cap = np.median([gbounds(gs, names[c])[3] for c in "HIETL" if c in names])
        lm_xh, lm_cap = L["OS/2"].sxHeight, L["OS/2"].sCapHeight
        # weight: thicken Latin Modern's accents to the Mills 8A stems
        grow_u = max(0.0, (stem(gs, names["l"]) - stem(lgs, "l")) / 2)
        grow_px = grow_u / bf.U_PER_PX
        print(f"{style}: x-height {xh:.0f}, cap height {cap:.0f}; "
              f"Latin Modern accents thickened by {grow_u:.0f} units per edge")

        top = font["CFF "].cff.topDictIndex[0]
        private, gsubrs = top.Private, top.GlobalSubrs
        new = {}                                   # name -> (T2CharString, adv)

        def add_from_pen(name, rec, adv):
            pen = T2CharStringPen(round(adv), None)
            rec.replay(pen)
            new[name] = (pen.getCharString(private, gsubrs), round(adv))

        # accent shapes: (pen, bounds) for lowercase and capital use
        accents = {}
        for acc in MARKS.values():
            for variant in ("lower", "cap"):
                src = f"{acc}.cap" if variant == "cap" and f"{acc}.cap" in lgs else acc
                o = outline_from_glyph(lgs, src, grow_px)
                if o is None:
                    continue
                contours, dx, dy = o
                pen = T2CharStringPen(0, None)
                cs = charstring(contours, dx, dy, bf.U_PER_UPX, 0, private, gsubrs)
                rec = RecordingPen()
                cs.draw(rec)
                # the gap between letter and accent: Latin Modern's for the
                # lowercase accent (its .cap variants are drawn lower), the
                # same above capitals
                gap = gbounds(lgs, acc)[1] - lm_xh if acc != "cedilla" else 0
                accents[(acc, variant)] = (rec, bounds(cs), gap)
        if style == "Regular" and "odieresis" in gs:
            # the 1947 dieresis: the dots of Erdos's o
            rec = contours_filtered(gs, "odieresis", lambda y0, y1: y0 > xh * 0.95)
            bp = BoundsPen(None)
            rec.replay(bp)
            for v in ("lower", "cap"):
                accents[("dieresis", v)] = (rec, bp.bounds, bp.bounds[1] - xh)
            print("  dieresis: the 1947 sort's (from Erdos's o)")

        # dotless i and j from the 1947 letters
        for base, dotless, cp in (("i", "dotlessi", 0x131), ("j", "uni0237", 0x237)):
            if base in names:
                rec = contours_filtered(gs, names[base], lambda y0, y1: y0 < xh * 0.9)
                add_from_pen(dotless, rec, font["hmtx"][names[base]][0])
                names[chr(cp)] = dotless

        # ASCII apostrophe: the 1947 right quote
        if "\u2019" in names and "'" not in names:
            names["'"] = names["\u2019"]
            new_cmap_only = {"'": names["\u2019"]}
        else:
            new_cmap_only = {}

        # punctuation the scans lack.  Built from 1947 sorts where possible:
        # colon and ellipsis from the period, the opening quote is the
        # closing one turned round, double quotes are pairs.
        rq = names.get("\u2019")
        if "." in names and ":" not in names:
            pb = gbounds(gs, names["."])
            rec = record(gs, names["."])
            rec.value += record(gs, names["."], 0, xh - pb[3]).value
            add_from_pen("colon", rec, font["hmtx"][names["."]][0])
            names[":"] = "colon"
        if "." in names and "\u2026" not in names:
            a = font["hmtx"][names["."]][0]
            rec = RecordingPen()
            for k in range(3):
                rec.value += record(gs, names["."], k * a).value
            add_from_pen("ellipsis", rec, 3 * a)
            names["\u2026"] = "ellipsis"
        if rq:
            qb = gbounds(gs, rq)
            a = font["hmtx"][rq][0]
            cx, cy = (qb[0] + qb[2]) / 2, (qb[1] + qb[3]) / 2
            lq = RecordingPen()
            gs[rq].draw(TransformPen(lq, (-1, 0, 0, -1, 2 * cx, 2 * cy)))
            add_from_pen("quoteleft", lq, a)
            names["\u2018"] = "quoteleft"
            step = (qb[2] - qb[0]) * 1.15
            for nm, src, cp in (("quotedblright", record(gs, rq), "\u201d"), ("quotedblleft", lq, "\u201c")):
                rec = RecordingPen()
                rec.value += src.value
                src.replay(TransformPen(rec, (1, 0, 0, 1, step, 0)))
                add_from_pen(nm, rec, a + step)
                names[cp] = nm
            names['"'] = "quotedblright"
        # the rest have no 1947 or 1922 source: Latin Modern's, thickened
        borrowed = ""
        for ch in ("?#%&*@\\^_{}~\u00a7\u2020\u2021\u00b6\u00a1\u00bf\u00ab\u00bb"
                   "\u00df\u00c6\u00e6\u0152\u0153\u00d8\u00f8\u0141\u0142\u00d0\u00f0\u00de\u00fe"):
            if ch in names or ord(ch) not in L.getBestCmap():
                continue
            src = L.getBestCmap()[ord(ch)]
            o = outline_from_glyph(lgs, src, grow_px)
            if o is None:
                continue
            contours, dx, dy = o
            a = L["hmtx"][src][0] + 2 * grow_u
            # lifted by the thickening, so the bottom stays on the baseline
            new_cs = charstring(contours, dx + grow_u, dy + grow_u, bf.U_PER_UPX, a, private,
                                gsubrs)
            rec = RecordingPen()
            new_cs.draw(rec)
            add_from_pen(src, rec, a)
            names[ch] = src
            borrowed += ch
        print(f"  punctuation from 1947 sorts: :…‘“”; from Latin Modern: {borrowed}")

        # spacing accents
        for acc, cp in SPACING.items():
            if (acc, "lower") in accents and chr(cp) not in names:
                rec, b, gap = accents[(acc, "lower")]
                w = b[2] - b[0]
                shifted = RecordingPen()
                y = (xh + gap - b[1]) if acc != "cedilla" else 0
                rec.replay(TransformPen(shifted, (1, 0, 0, 1, 60 - b[0], y)))
                add_from_pen(f"{acc}", shifted, w + 120)
                names[chr(cp)] = acc

        # composites
        made = []
        for cp in list(range(0xC0, 0x100)) + list(range(0x100, 0x180)):
            ch = chr(cp)
            d = unicodedata.decomposition(ch).split()
            if len(d) != 2 or d[0].startswith("<") or ch in names:
                continue
            base, mark = chr(int(d[0], 16)), int(d[1], 16)
            if mark not in MARKS or (mark == 0x30C and base in SIDE_CARON):
                continue
            bname = names.get({"i": "ı", "j": "ȷ"}.get(base, base))
            if bname is None:
                continue
            gname = (bf.UV2AGL.get(cp) or f"uni{cp:04X}")
            acc = MARKS[mark]
            variant = "cap" if base.isupper() else "lower"
            if (acc, variant) not in accents:
                continue
            arec, ab, gap = accents[(acc, variant)]
            bb = gbounds(gs, bname if bname in gs else names[base]) if bname in gs else \
                gbounds_rec(new[bname][0])
            if acc == "cedilla":
                y = 0                              # Latin Modern's cedilla hangs from y=0
                cy = 0
            else:
                ref = cap if variant == "cap" else xh
                y = max(ref, bb[3] if base not in "ij" else ref) + gap - ab[1]
                cy = (ab[1] + ab[3]) / 2 + y
            mid_y = (bb[1] + bb[3]) / 2
            x = (bb[0] + bb[2]) / 2 + SLANT[style] * (cy - mid_y) - (ab[0] + ab[2]) / 2
            rec = RecordingPen()
            if bname in gs:
                gs[bname].draw(rec)
            else:
                new[bname][0].draw(rec)
            arec.replay(TransformPen(rec, (1, 0, 0, 1, x, y)))
            adv = font["hmtx"][names[base]][0] if base not in "ij" else font["hmtx"][names[base]][0]
            add_from_pen(gname, rec, adv)
            names[ch] = gname
            made.append(ch)
        print(f"  {len(made)} accented letters: {''.join(made)}")

        # write the new glyphs into the font
        cff = font["CFF "].cff
        td = cff.topDictIndex[0]
        cs = td.CharStrings
        order = list(font.getGlyphOrder())       # (may be the charset list itself)
        for name, (charstr, adv) in new.items():
            if name in cs:
                cs[name] = charstr
            else:
                cs.charStringsIndex.append(charstr)
                cs.charStrings[name] = len(cs.charStringsIndex) - 1
                order.append(name)
            b = bounds(charstr)
            font["hmtx"].metrics[name] = (adv, round(b[0]))
        td.charset = order
        font.setGlyphOrder(order)
        font["maxp"].numGlyphs = len(order)
        for t in font["cmap"].tables:
            if t.isUnicode():
                for ch, name in names.items():
                    if (name in new or ch in new_cmap_only or ch == '"') and (t.format != 4 or ord(ch) < 0x10000):
                        t.cmap[ord(ch)] = name
        font.save(path)
        print(f"  wrote {path}: {len(order)} glyphs")


def gbounds_rec(charstr):
    return bounds(charstr)


if __name__ == "__main__":
    main()

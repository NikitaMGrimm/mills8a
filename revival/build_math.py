"""Mills 8A Math: an OpenType MATH font for unicode-math.

Latin Modern Math supplies the MATH table, the extensible delimiters and
every symbol the 1947 scans do not contain.  On top of it:

* math italic letters and Greek, upright letters, figures and operators are
  replaced by the Mills 8A text glyphs (fonts/Mills8A-{Regular,Italic}.otf);
* the script ('ssty' .st) and scriptscript (.sts) variants of those glyphs
  are the real first- and second-order script sorts of the 1947 pages
  where they exist (sizes S1, S2 in work/masters.pkl), otherwise the text
  glyph thickened to the stroke weight the real script sorts have;
* the display summation, product and integral are the 1947 display sorts;
* script sizes and positions are measured from the scans
  (ScriptPercentScaleDown, ScriptScriptPercentScaleDown, superscript and
  subscript shifts).

Latin Modern Math is distributed under the GUST Font License; this derived
font therefore has its own name.
"""
import os
import pickle
import subprocess
from collections import defaultdict

import numpy as np
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.freetypePen import FreeTypePen
from fontTools.pens.t2CharStringPen import T2CharStringPen
from fontTools.ttLib import TTFont

import build_font as bf

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, "work")
FONTS = os.path.join(HERE, "fonts")
UP = bf.UP
U = bf.U_PER_UPX                      # font units per master px
OPERATORS = "+−±=<>()[]/|≦≧≤∞→,.;!′∑⊗÷≃{}:*×∈⊂∪ΔΠΩℭ𝔖𝔄𝔅𝔇𝔊≠∩≅∂←≡𝔛𝒞𝒜"
# cast centred on their body: even side bearings (TeX adds the spacing)
CENTRED = set("+−±=<>≦≧≤×÷≃≠≡≅∈⊂∪∩⊗→←")
CENTRED_SB = 30
MIN_MATH_LSB = 20                     # units, for math italic letters


def lm_path():
    return subprocess.run(["kpsewhich", "latinmodern-math.otf"], check=True,
                          capture_output=True, text=True).stdout.strip()


# ---------------------------------------------------------------- measuring

# script sorts set from the scaled text glyph although real ones exist: the
# real 2 and 3 average into closed, hard-to-read shapes at index size, and the
# second-order "5" group holds 2s
SYNTH_SCRIPT = {("2", "S1"), ("2", "S2"), ("3", "S1"), ("3", "S2"), ("5", "S2")}


def script_scales(M):
    """Script and scriptscript scale factors: the size of the 1947 script
    sorts relative to the 11pt ones, measured on glyph heights with the
    ink spread (2 px per edge, which does not scale) taken off."""
    def h(m):
        ys = np.nonzero((m["img"] > 0.5).any(1))[0]
        return (ys.max() - ys.min() + 1) / UP
    out = {}
    for lvl in ("S1", "S2"):
        r = [(h(M[(g, s, lvl)]) - 4) / (h(M[(g, s, 11)]) - 4)
             for (g, s, z) in M if z == lvl and (g, s, 11) in M
             and len(g) == 1 and g.isalnum() and M[(g, s, lvl)]["n"] >= 3]
        out[lvl] = float(np.median(r))
        print(f"{lvl}: scale {out[lvl]:.3f} from {len(r)} sorts")
    return out


def script_positions():
    """Baselines of first-order scripts relative to the line, from the
    bottoms of S1 sorts without descenders: superscripts form one cluster
    above the line, subscripts one just below it.  Returns font units."""
    inst = pickle.load(open(os.path.join(WORK, "instances.pkl"), "rb"))
    cl = {c["id"]: c for c in pickle.load(open(os.path.join(WORK, "clusters.pkl"), "rb"))}
    sorts = pickle.load(open(os.path.join(WORK, "sorts.pkl"), "rb"))
    b = []
    for (g, s, z), cids in sorts.items():
        if z == "S1" and g in "0123468mnuxikdtNE":
            for c in cids:
                for i in cl[c]["members"]:
                    x = inst[i]
                    if x["baseline_ref"] is not None:
                        b.append(x["bbox"][3] - x["baseline_ref"])
    b = np.array(b)
    sup = -np.median(b[(b < -18) & (b > -36)]) * bf.U_PER_PX
    sub = np.median(b[(b > 3) & (b < 15)]) * bf.U_PER_PX
    print(f"superscripts raised {sup:.0f} units, subscripts lowered {sub:.0f} "
          f"({len(b)} script impressions)")
    return sup, sub


def stem(img):
    return bf.stem_width(img) / UP                          # scan px


# ---------------------------------------------------------------- glyphs

def outline_from_glyph(gs, name, grow_px=0.0):
    """Rasterise a glyph at master resolution, optionally grow its ink by
    grow_px scan px per edge, and retrace it.  Returns (contours, dx, dy)
    for bf.charstring at scale U (font units), and the ink grow in units."""
    pen = FreeTypePen(gs)
    gs[name].draw(pen)
    from fontTools.pens.boundsPen import BoundsPen
    bp = BoundsPen(gs)
    gs[name].draw(bp)
    if bp.bounds is None:
        return None
    x0, y0, x1, y1 = bp.bounds
    s = 1 / U                                               # px per unit
    m = int(grow_px * UP) + 8
    W = int((x1 - x0) * s) + 2 * m
    H = int((y1 - y0) * s) + 2 * m
    img = pen.array(width=W, height=H, transform=(s, 0, 0, s, m - x0 * s, m - y0 * s))
    img = bf.embolden(img, grow_px)
    contours = bf.trace(np.pad(img, 2))
    # potrace px (y up from the padded bottom) -> units
    dx = x0 - (m + 2) * U
    dy = y0 - (m + 2) * U
    return contours, dx, dy


def outline_from_master(m, ink_px):
    """A script master traced at its real size (units of the 11pt em)."""
    img = bf.despeckle(m["img"])
    ys, xs = np.nonzero(img > 0.5)
    g = int(np.ceil(ink_px * UP)) + 1
    img = bf.embolden(np.pad(img, g), ink_px)
    base = m["base"] + g
    r0, r1, c0, c1 = ys.min(), ys.max() + 1 + 2 * g, xs.min(), xs.max() + 1 + 2 * g
    contours, dx, dy = bf.traced(img, r0, r1, c0, c1, base, c0 + g, 0.0)
    return contours, dx, dy, (xs.max() - xs.min() + 1) * U   # ink width, units


def charstring(contours, dx, dy, scale, adv, private, gsubrs):
    pen = T2CharStringPen(round(adv), None)
    for c in contours:
        for op, pts in c:
            q = [(round(x * scale + dx), round(y * scale + dy)) for x, y in pts]
            if op == "M":
                pen.moveTo(q[0])
            elif op == "L":
                pen.lineTo(q[0])
            else:
                pen.curveTo(*q)
        pen.closePath()
    return pen.getCharString(private, gsubrs)


def bounds(cs):
    b = cs.calcBounds(None)
    return b if b else (0, 0, 0, 0)


# ---------------------------------------------------------------- assembly

def pair_gaps():
    """{(a, b): (median over papers of the median ink gap, in font units; count)} for neighbouring 11 pt
    math italic letters and roman parentheses in the scans."""
    import json
    inst = pickle.load(open(os.path.join(WORK, "instances.pkl"), "rb"))
    sorts = pickle.load(open(os.path.join(WORK, "sorts.pkl"), "rb"))
    clusters = pickle.load(open(os.path.join(WORK, "clusters.pkl"), "rb"))
    p = os.path.join(WORK, "docscale.json")
    scale = json.load(open(p)) if os.path.exists(p) else {}
    lab = {}
    for (g, s, z), cids in sorts.items():
        if z == 11 and ((s == "I" and len(g) == 1 and g.isalpha()) or (s == "R" and g in "()")):
            for c in cids:
                for i in clusters[c]["members"]:
                    lab[i] = g
    byline = defaultdict(list)
    for i, g in enumerate(inst):
        if g["line"] >= 0 and i in lab:
            byline[(g["page"], g["line"])].append(i)
    gaps = defaultdict(lambda: defaultdict(list))
    for ids in byline.values():
        ids.sort(key=lambda i: inst[i]["bbox"][0])
        for a, b in zip(ids, ids[1:]):
            doc = inst[a]["page"].rsplit("-", 1)[0]
            gap = scale.get(doc, 1.0) * (inst[b]["bbox"][0] - inst[a]["bbox"][2])
            if -10 < gap < 20:                   # wider: a space between
                gaps[(lab[a], lab[b])][doc].append(gap)
    # one vote per paper: compositors differed (Kleene's quantifiers (x)
    # are set tight and are most of the (x pairs)
    out = {}
    for k, per in gaps.items():
        meds = [np.median(v) for v in per.values() if len(v) >= 3]
        if meds:
            out[k] = (float(np.median(meds)) * bf.U_PER_PX, sum(len(v) for v in per.values()))
    return out


def shifted(cs, dx, private, gsubrs, adv):
    """The charstring moved right by dx with a new advance."""
    from fontTools.pens.transformPen import TransformPen
    pen = T2CharStringPen(adv, None)
    cs.draw(TransformPen(pen, (1, 0, 0, 1, dx, 0)))
    return pen.getCharString(private, gsubrs)


def wmedian(pairs):
    """Median of values weighted by counts: [(value, count)]."""
    pairs = sorted(pairs)
    tot, acc = sum(n for _, n in pairs), 0
    for v, n in pairs:
        acc += n
        if acc >= tot / 2:
            return v
    return 0.0


def main():
    M = pickle.load(open(os.path.join(WORK, "masters.pkl"), "rb"))
    k = script_scales(M)
    sup, sub = script_positions()
    lm = TTFont(lm_path())
    lm_gs = lm.getGlyphSet()
    order = list(lm.getGlyphOrder())
    lm_cmap = lm.getBestCmap()
    ours = {s: TTFont(os.path.join(FONTS, f"Mills8A-{n}.otf")) for s, n in (("R", "Regular"), ("I", "Italic"))}
    our_gs = {s: f.getGlyphSet() for s, f in ours.items()}
    our_cmap = {s: f.getBestCmap() for s, f in ours.items()}
    our_hmtx = {s: f["hmtx"] for s, f in ours.items()}

    # target LM glyph -> (style, char)
    targets = {}
    for i, c in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
        targets[lm_cmap[bf.MATH_IT_CAP + i]] = ("I", c)
        targets[lm_cmap[ord(c)]] = ("R", c)
    for i, c in enumerate("abcdefghijklmnopqrstuvwxyz"):
        cp = 0x210E if c == "h" else bf.MATH_IT_LOW + i
        targets[lm_cmap[cp]] = ("I", c)
        targets[lm_cmap[ord(c)]] = ("R", c)
    for g, cp in bf.GREEK_MATH_IT.items():
        targets[lm_cmap[cp]] = ("I", g)
    for c in "0123456789" + OPERATORS:
        if ord(c) in lm_cmap:
            targets[lm_cmap[ord(c)]] = ("R", c)
    targets = {t: v for t, v in targets.items() if ord(v[1]) in our_cmap[v[0]]}

    # ssty alternates in Latin Modern: base -> [script, scriptscript]
    gsub = lm["GSUB"].table
    ssty = {}
    for fr in gsub.FeatureList.FeatureRecord:
        if fr.FeatureTag == "ssty":
            for li in fr.Feature.LookupListIndex:
                for st in gsub.LookupList.Lookup[li].SubTable:
                    ssty.update(st.alternates)
            break

    # stroke growth for script variants without a real 1947 script sort:
    # make the scaled text glyph as heavy as the real script sorts are
    grow = {}
    for lvl in ("S1", "S2"):
        pairs = [(stem(M[(g, s, 11)]["img"]), stem(M[(g, s, lvl)]["img"]))
                 for (g, s, z) in M if z == lvl and (g, s, 11) in M
                 and g in "nmu1IlhdN" and M[(g, s, lvl)]["n"] >= 3]
        if pairs:
            s11, sS = np.median(pairs, axis=0)
            grow[lvl] = max(0.0, (sS / k[lvl] - s11) / 2)
        else:
            grow[lvl] = 0.0
        print(f"{lvl}: synthesised script variants thickened by {grow[lvl]:.2f} px per edge")

    # start from all LM glyphs, drawn into fresh charstrings
    top = lm["CFF "].cff.topDictIndex[0]
    private, gsubrs = top.Private, top.GlobalSubrs
    cs, adv = {}, {}
    for name in order:
        pen = T2CharStringPen(lm["hmtx"][name][0], lm_gs)
        lm_gs[name].draw(pen)
        cs[name] = pen.getCharString(private, gsubrs)
        adv[name] = lm["hmtx"][name][0]

    new_glyphs, italic_ic, accents = [], {}, {}
    replaced = 0
    real = defaultdict(int)
    for target, (style, ch) in sorted(targets.items()):
        src = our_cmap[style][ord(ch)]
        a = our_hmtx[style][src][0]
        pen = T2CharStringPen(a, our_gs[style])
        our_gs[style][src].draw(pen)
        cs[target] = pen.getCharString(private, gsubrs)
        adv[target] = a
        if style == "I" and bounds(cs[target])[0] < MIN_MATH_LSB:
            # text italic f hangs left over the preceding letter (a kerned
            # sort); in math it would eat the space before f(x)
            d = MIN_MATH_LSB - bounds(cs[target])[0]
            pen = T2CharStringPen(a + d, our_gs[style])
            from fontTools.pens.transformPen import TransformPen
            our_gs[style][src].draw(TransformPen(pen, (1, 0, 0, 1, d, 0)))
            cs[target] = pen.getCharString(private, gsubrs)
            a = adv[target] = round(a + d)
        replaced += 1
        variants = ssty.get(target)
        if not variants:
            variants = [target + ".st", target + ".sts"]
            ssty[target] = variants
            new_glyphs += variants
        b = bounds(cs[target])
        for lvl, vname in zip(("S1", "S2"), variants):
            kk = k[lvl]
            mkey = (ch, style, lvl)
            if (mkey in M and M[mkey]["n"] >= 5      # fewer: often misfiled impressions
                    and (ch, lvl) not in SYNTH_SCRIPT):
                # a real script sort: its ink at real size, side bearings
                # scaled from the text glyph by the ratio of ink widths
                contours, dx, dy, w_real = outline_from_master(M[mkey], bf.INK_PX)
                w_text = max(1, b[2] - b[0])
                f = w_real / w_text
                lsb, rsb = b[0] * f, (a - b[2]) * f
                # a script master sits where its impressions were cut, raised
                # or lowered with them; put it on its own baseline: its
                # bottom where the text glyph's is, scaled to its size
                cs[vname] = charstring(contours, (dx + lsb) / kk, dy / kk, U / kk,
                                       (lsb + w_real + rsb) / kk, private, gsubrs)
                shift = b[1] * f / kk - bounds(cs[vname])[1]
                cs[vname] = charstring(contours, (dx + lsb) / kk, dy / kk + shift, U / kk,
                                       (lsb + w_real + rsb) / kk, private, gsubrs)
                adv[vname] = round((lsb + w_real + rsb) / kk)
                real[lvl] += 1
            else:
                o = outline_from_glyph(our_gs[style], src, grow[lvl])
                if o is None:
                    continue
                contours, dx, dy = o
                g_u = grow[lvl] * bf.U_PER_PX
                cs[vname] = charstring(contours, dx + g_u, dy, U, a + 2 * g_u, private, gsubrs)
                adv[vname] = round(a + 2 * g_u)
        if style == "I":
            for n in [target] + [v for v in variants if v in cs]:
                bb = bounds(cs[n])
                italic_ic[n] = max(0, round(bb[2] - adv[n]) + 20)
                accents[n] = round((bb[0] + bb[2]) / 2 + 0.12 * (bb[3] - bb[1]) / 2)
        else:
            for n in [target] + [v for v in variants if v in cs]:
                bb = bounds(cs[n])
                accents[n] = round((bb[0] + bb[2]) / 2)
    # binary operators, relations and arrows: centred, whatever spacing the
    # text fit gave them (the text minus had 267 units on its right)
    for n, (st, ch) in targets.items():
        if st == "R" and ch in CENTRED and n in cs:
            bb = bounds(cs[n])
            adv[n] = round(bb[2] - bb[0] + 2 * CENTRED_SB)
            cs[n] = shifted(cs[n], CENTRED_SB - bb[0], private, gsubrs, adv[n])
            for v in ssty.get(n, []):
                if v in cs:
                    b2 = bounds(cs[v])
                    sb2 = round(CENTRED_SB * (b2[2] - b2[0]) / max(1, bb[2] - bb[0]))
                    adv[v] = round(b2[2] - b2[0] + 2 * sb2)
                    cs[v] = shifted(cs[v], sb2 - b2[0], private, gsubrs, adv[v])
    # for pdfLaTeX (TeX centres a math accent by its advance): spacing copies
    # of the combining accents, and the bar of \mapsto
    for cp in (0x300, 0x301, 0x302, 0x303, 0x304, 0x306, 0x307, 0x308, 0x30A, 0x30C, 0x20D7):
        src = lm_cmap.get(cp)
        if not src:
            continue
        name = f"tex.acc.{cp:04X}"
        c0 = cs.get(src)
        if c0 is None:
            pen = T2CharStringPen(0, lm_gs)
            lm_gs[src].draw(pen)
            c0 = pen.getCharString(private, gsubrs)
        bb = bounds(c0)
        adv[name] = round(bb[2] - bb[0])
        cs[name] = shifted(c0, -bb[0], private, gsubrs, adv[name])
        new_glyphs.append(name)
    pen = T2CharStringPen(0, None)
    for x, y in ((56, -10), (96, -10), (96, 510), (56, 510)):
        (pen.moveTo if (x, y) == (56, -10) else pen.lineTo)((x, y))
    pen.closePath()
    cs["tex.mapstochar"], adv["tex.mapstochar"] = pen.getCharString(private, gsubrs), 0
    new_glyphs.append("tex.mapstochar")

    # spacing around parentheses from print (f(x) is set tight in 1947).
    # 1) italic correction: the gaps from a letter to a following "(" or ")",
    #    weighted by how often each occurs;
    # 2) ")" left side bearing, for letters the italic correction cannot
    #    bring closer, and the "(" right side bearing: the median gap, over
    #    letters, after it;
    # 3) letters still further from a preceding "(" than in print (f, A:
    #    kerned sorts) get a smaller left side bearing, down to -20 units.
    G = pair_gaps()
    letters = {n: ch for n, (st, ch) in targets.items() if st == "I" and n in cs}
    if "parenleft" in cs and "parenright" in cs:
        lp, rp = "parenleft", "parenright"
        tuned = []
        for n, ch in letters.items():
            # each printed pair after the letter implies an italic correction
            bb = bounds(cs[n])
            implied = []
            for p_, pg in (("(", lp), (")", rp)):
                g = G.get((ch, p_))
                if g and g[1] >= 10:
                    implied.append((g[0] + bb[2] - adv[n] - bounds(cs[pg])[0], g[1]))
            if implied:
                v = max(0, round(wmedian(implied)))
                tuned.append(f"{ch}{v - italic_ic.get(n, 0):+d}")
                italic_ic[n] = v
        print("italic corrections from print, change: " + " ".join(tuned))
        # ")": letters whose italic correction is already 0 and still sit
        # further from a following ")" than in print (x, e, h ...) want a
        # smaller left side bearing on the parenthesis
        d = []
        for n, ch in letters.items():
            g = G.get((ch, ")"))
            if g and g[1] >= 10 and italic_ic.get(n, 0) == 0:
                bb = bounds(cs[n])
                d.append((adv[n] - bb[2] + bounds(cs[rp])[0] - g[0], g[1]))
        if d:
            dr = max(0, round(wmedian(d)))
            adv[rp] -= dr
            cs[rp] = shifted(cs[rp], -dr, private, gsubrs, adv[rp])
            print(f'")" left side bearing {-dr:+d} units')
        # "(" before a letter
        d = []
        for n, ch in letters.items():
            g = G.get(("(", ch))
            if g and g[1] >= 10:
                ours = adv[lp] - bounds(cs[lp])[2] + bounds(cs[n])[0]
                d.append((ours - g[0], g[1]))
        if d:
            dl = round(wmedian(d))
            adv[lp] = adv[lp] - dl
            cs[lp] = shifted(cs[lp], 0, private, gsubrs, adv[lp])
            print(f'"(" advance {-dl:+d} units')
        kerned = []
        for n, ch in letters.items():
            g = G.get(("(", ch))
            if g and g[1] >= 30:
                bb = bounds(cs[n])
                ours = adv[lp] - bounds(cs[lp])[2] + bb[0]
                extra = ours - g[0]
                new_lsb = max(-20, bb[0] - extra)
                if bb[0] - new_lsb > 15:
                    dx = round(new_lsb - bb[0])
                    adv[n] += dx
                    cs[n] = shifted(cs[n], dx, private, gsubrs, adv[n])
                    kerned.append(f"{ch}{dx:+d}")
        if kerned:
            print("left side bearings from print: " + " ".join(kerned))
    print(f"replaced {replaced} glyphs; real script sorts used: "
          f"{real['S1']} first-order, {real['S2']} second-order")

    # display operators: the 1947 display sorts as first size variant
    mvar = lm["MATH"].table.MathVariants
    for ch, lmname in (("∑", "summation"), ("∏", "product"), ("∫", "integral")):
        mkey = (ch, "R", "D")
        if mkey not in M:
            continue
        i = mvar.VertGlyphCoverage.glyphs.index(lmname)
        recs = mvar.VertGlyphConstruction[i].MathGlyphVariantRecord
        if len(recs) < 2:
            continue
        vname = recs[1].VariantGlyph
        contours, dx, dy, w = outline_from_master(M[mkey], bf.INK_PX)
        sb = 40
        cs[vname] = charstring(contours, dx + sb, dy, U, w + 2 * sb, private, gsubrs)
        adv[vname] = round(w + 2 * sb)
        bb = bounds(cs[vname])
        recs[1].AdvanceMeasurement = round(bb[3] - bb[1])
        print(f"display {ch}: 1947 sort as {vname}")

    # ---- MATH table
    mt = lm["MATH"].table
    mc = mt.MathConstants
    mc.ScriptPercentScaleDown = round(100 * k["S1"])
    mc.ScriptScriptPercentScaleDown = round(100 * k["S2"])
    mc.SuperscriptShiftUp.Value = round(sup)
    mc.SuperscriptShiftUpCramped.Value = round(0.8 * sup)
    mc.SubscriptShiftDown.Value = round(sub)
    mc.SubscriptTopMax.Value = round(0.8 * 440)
    gi = mt.MathGlyphInfo
    ic = gi.MathItalicsCorrectionInfo
    cur = dict(zip(ic.Coverage.glyphs, ic.ItalicsCorrection))
    for n, v in italic_ic.items():
        rec = type(ic.ItalicsCorrection[0])()
        rec.Value = v
        cur[n] = rec
    for n in list(cur):                      # upright replacements: none
        if n in targets and targets[n][0] == "R":
            del cur[n]
    ic.Coverage.glyphs = list(cur)
    ic.ItalicsCorrection = list(cur.values())
    ic.ItalicsCorrectionCount = len(cur)
    ta = gi.MathTopAccentAttachment
    cur = dict(zip(ta.TopAccentCoverage.glyphs, ta.TopAccentAttachment))
    for n, v in accents.items():
        rec = type(ta.TopAccentAttachment[0])()
        rec.Value = v
        cur[n] = rec
    ta.TopAccentCoverage.glyphs = list(cur)
    ta.TopAccentAttachment = list(cur.values())
    ta.TopAccentAttachmentCount = len(cur)
    kern = gi.MathKernInfo                   # LM's cut-ins fit LM's shapes only
    if kern is not None:
        keep = [(g, r) for g, r in zip(kern.MathKernCoverage.glyphs, kern.MathKernInfoRecords)
                if g not in targets and not any(g in v for v in ssty.values() if False)]
        kern.MathKernCoverage.glyphs = [g for g, _ in keep]
        kern.MathKernInfoRecords = [r for _, r in keep]
        kern.MathKernCount = len(keep)

    # ---- ssty: Latin Modern's lookup, extended to the glyphs it lacked
    for fr in gsub.FeatureList.FeatureRecord:
        if fr.FeatureTag == "ssty":
            st = gsub.LookupList.Lookup[fr.Feature.LookupListIndex[0]].SubTable[0]
            for base, v in ssty.items():
                if base not in st.alternates:
                    st.alternates[base] = v
            break

    # ---- build
    glyph_order = order + [g for g in new_glyphs if g not in order]
    fb = FontBuilder(1000, isTTF=False)
    fb.setupGlyphOrder(glyph_order)
    fb.setupCharacterMap(lm_cmap)
    fb.setupCFF("Mills8A-Math", {"FullName": "Mills 8A Math", "FamilyName": "Mills 8A Math"},
                cs, {})
    fb.setupHorizontalMetrics({n: (adv[n], round(bounds(cs[n])[0])) for n in glyph_order})
    fb.setupHorizontalHeader(ascent=lm["hhea"].ascent, descent=lm["hhea"].descent)
    bf.stamp_version(fb, {"familyName": "Mills 8A Math", "styleName": "Regular",
                       "copyright": "Based on Latin Modern Math (GUST Font License); "
                                    "glyphs traced from 1947 Monotype Modern 8A printing"})
    fb.setupOS2(sTypoAscender=lm["OS/2"].sTypoAscender, sTypoDescender=lm["OS/2"].sTypoDescender,
                usWinAscent=lm["OS/2"].usWinAscent, usWinDescent=lm["OS/2"].usWinDescent,
                sxHeight=440, sCapHeight=650)
    fb.setupPost()
    # coverage tables must list glyphs in glyph-id order
    gid = {g: i for i, g in enumerate(glyph_order)}
    def resort(cov, values):
        pairs = sorted(zip(cov.glyphs, values), key=lambda p: gid[p[0]])
        cov.glyphs = [p[0] for p in pairs]
        return [p[1] for p in pairs]
    ic.ItalicsCorrection = resort(ic.Coverage, ic.ItalicsCorrection)
    ta.TopAccentAttachment = resort(ta.TopAccentCoverage, ta.TopAccentAttachment)
    if kern is not None:
        kern.MathKernInfoRecords = resort(kern.MathKernCoverage, kern.MathKernInfoRecords)
    for t in ("MATH", "GSUB", "GPOS", "GDEF"):
        fb.font[t] = lm[t]
    out = os.path.join(FONTS, "Mills8A-Math.otf")
    fb.save(out)
    print(f"wrote {out}: {len(glyph_order)} glyphs")


if __name__ == "__main__":
    main()

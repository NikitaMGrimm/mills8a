"""Trace the masters, fit the spacing, and assemble OpenType fonts.

Fonts written to fonts/:
  Mills8A-Regular.otf  roman, figures, punctuation, math operators and
                       relations, fi/ffi ligatures (liga), small caps (smcp)
  Mills8A-Italic.otf   italic letters and Greek, also encoded at the Unicode
                       math-italic code points (U+1D434...) for unicode-math

Units: 1000 per em of 11pt.  The 1947 scans are 600 dpi, so one em is
11 * 600/72.27 = 91.3 px, and a master pixel (4x) is 1000/365.3 units.
"""
import os
import pickle
import re
import subprocess
import tempfile
from collections import defaultdict

import numpy as np
from fontTools.fontBuilder import FontBuilder
from fontTools.feaLib.builder import addOpenTypeFeaturesFromString
from fontTools.pens.t2CharStringPen import T2CharStringPen
from fontTools.agl import UV2AGL
from scipy import ndimage

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, "work")
FONTS = os.path.join(HERE, "fonts")
UP = 4
PX_PER_PT = 600 / 72.27
EM_PX = 11 * PX_PER_PT                      # 1x scan px per em
U_PER_UPX = 1000 / (EM_PX * UP)             # font units per master px
U_PER_PX = 1000 / EM_PX                     # font units per scan px

SPACE = 322                                  # 6 units of 10.7 set, in font units
MATH_IT_CAP, MATH_IT_LOW = 0x1D434, 0x1D44E
GREEK_MATH_IT = {"α": 0x1D6FC, "β": 0x1D6FD, "ζ": 0x1D701, "π": 0x1D70B,
                 "σ": 0x1D70E, "ϕ": 0x1D719, "ϵ": 0x1D716}


# ---------------------------------------------------------------- outlines

def trace(img):
    """Potrace a coverage image (rows top->bottom); returns a list of
    contours, each a list of ('M'|'L'|'C', points) in image px, y up from
    the bottom row."""
    bm = img > 0.5
    h, w = bm.shape
    with tempfile.TemporaryDirectory() as td:
        pbm = os.path.join(td, "g.pbm")
        with open(pbm, "wb") as f:
            f.write(b"P4\n%d %d\n" % (w, h))
            f.write(np.packbits(bm, axis=1).tobytes())
        svg = subprocess.run(["potrace", "-b", "svg", "-u", "10", "-t", "8", "-a", "1.0",
                              "-O", "0.4", "--flat", "-o", "-", pbm],
                             check=True, capture_output=True, text=True).stdout
    d = " ".join(re.findall(r' d="([^"]*)"', svg))
    toks = re.findall(r"[MmLlCcZz]|-?\d+(?:\.\d+)?", d)
    contours, cur, pos, start, cmd, i = [], None, (0.0, 0.0), (0.0, 0.0), None, 0
    while i < len(toks):
        t = toks[i]
        if t in "MmLlCcZz":
            cmd = t
            i += 1
            if cmd in "Zz":
                if cur:
                    contours.append(cur)
                cur, pos = None, start
                continue
        nums = {"M": 2, "m": 2, "L": 2, "l": 2, "C": 6, "c": 6}[cmd]
        v = [float(x) / 10 for x in toks[i:i + nums]]
        i += nums
        rel = cmd.islower()
        pts = [(v[k] + (pos[0] if rel else 0), v[k + 1] + (pos[1] if rel else 0))
               for k in range(0, nums, 2)]
        if cmd in "Mm":
            if cur:
                contours.append(cur)
            cur, start = [("M", pts)], pts[0]
            cmd = "l" if rel else "L"        # implicit lineto after moveto
        elif cmd in "Ll":
            cur.append(("L", pts))
        else:
            cur.append(("C", pts))
        pos = pts[-1]
    if cur:
        contours.append(cur)
    return contours


def charstring(contours, dx, dy, scale, adv):
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
    return pen.getCharString()


# ---------------------------------------------------------------- spacing

SYMMETRIC = set("oOnuvwxHIMNOUVWX08=+")
# Side bearings (em) fixed by hand where the scans cannot measure them:
# the italic f is a kerned sort hanging over both neighbours.
SPACING_BY_HAND = {"I": {"f": (-0.02, -0.07)}}


def fit_spacing(style, size, widths):
    """Side bearings and advances (scan px) from within-word letter pairs.

    Monotype sets words without letterspacing, so for neighbours a, b the
    distance between their ink left edges is  P[a] + L[b]  with L the left
    side bearing and P = advance - L.  Pairs come from the sorts of one
    style and size that are neighbours on a line with an ink gap < 12 px.

    Within a connected group of glyphs the solution is fixed only up to
    P += c, L -= c; c is chosen so symmetric letters get equal side
    bearings.  A glyph seen only first in pairs (capitals, mostly) has its
    right side bearing determined and gets an equal left one; likewise the
    other way round.  Advances are finally snapped to the Monotype unit
    (1/18 of the set), whose size is itself fitted to the data.

    widths: {glyph: ink width in scan px}.  Returns {glyph: (lsb, adv)}."""
    inst = pickle.load(open(os.path.join(WORK, "instances.pkl"), "rb"))
    clusters = pickle.load(open(os.path.join(WORK, "clusters.pkl"), "rb"))
    sorts = pickle.load(open(os.path.join(WORK, "sorts.pkl"), "rb"))
    sort_of = {}
    for (g, s, z), cids in sorts.items():
        if s == style and z == size and g in widths:
            for c in cids:
                for i in clusters[c]["members"]:
                    sort_of[i] = g
    byline = defaultdict(list)
    for i, g in enumerate(inst):
        if g["line"] >= 0:
            byline[(g["page"], g["line"])].append(i)
    pairs = []
    for ids in byline.values():
        ids.sort(key=lambda i: inst[i]["bbox"][0])
        for a, b in zip(ids, ids[1:]):
            if a in sort_of and b in sort_of:
                gap = inst[b]["bbox"][0] - inst[a]["bbox"][2]
                if -6 < gap < 12:
                    pairs.append((sort_of[a], sort_of[b], inst[b]["bbox"][0] - inst[a]["bbox"][0]))
    out = {}
    if pairs:
        glyphs = sorted({p[0] for p in pairs} | {p[1] for p in pairs})
        ix = {g: k for k, g in enumerate(glyphs)}
        n = len(glyphs)
        keep = np.ones(len(pairs), bool)
        for _ in range(3):                  # least squares with outlier rejection
            kp = [p for p, k in zip(pairs, keep) if k]
            A = np.zeros((len(kp) + 2 * n, 2 * n))
            y = np.zeros(len(kp) + 2 * n)
            for r, (a, b, d) in enumerate(kp):
                A[r, ix[a]] = 1
                A[r, n + ix[b]] = 1
                y[r] = d
            A[len(kp):, :] = 1e-3 * np.eye(2 * n)   # undetermined -> ~0
            sol = np.linalg.lstsq(A, y, rcond=None)[0]
            res = np.array([sol[ix[a]] + sol[n + ix[b]] - d for a, b, d in pairs])
            keep = np.abs(res) < 3
        P = {g: sol[ix[g]] for g in glyphs}
        L = {g: sol[n + ix[g]] for g in glyphs}
        nf = defaultdict(int); ns = defaultdict(int)
        parent = {g: g for g in glyphs}

        def root(g):
            while parent[g] != g:
                g = parent[g]
            return g
        for (a, b, d), k in zip(pairs, keep):
            if k:
                nf[a] += 1; ns[b] += 1
                parent[root(a)] = root(b)
        comps = defaultdict(list)
        for g in glyphs:
            comps[root(g)].append(g)
        for members in comps.values():
            both = [g for g in members if nf[g] >= 2 and ns[g] >= 2]
            sym = [g for g in both if g in SYMMETRIC] or both
            if not sym:
                continue
            c = np.mean([(L[g] - P[g] + widths[g]) / 2 for g in sym])
            for g in members:
                if nf[g] >= 2 and ns[g] >= 2:
                    lsb, adv = L[g] - c, P[g] + L[g]
                elif nf[g] >= 2:            # right side known
                    rsb = P[g] + c - widths[g]
                    lsb, adv = rsb, 2 * rsb + widths[g]
                elif ns[g] >= 2:            # left side known
                    lsb = L[g] - c
                    adv = 2 * lsb + widths[g]
                else:
                    continue
                if adv > widths[g] and -0.2 * widths[g] < lsb < 0.6 * widths[g]:
                    out[g] = (lsb, adv)
        print(f"{style}{size}: {keep.sum()} of {len(pairs)} pairs, rms "
              f"{np.sqrt(np.mean(res[keep] ** 2)):.2f} px, spacing measured for {len(out)} glyphs")
        # the Monotype unit: the size that puts well-measured advances on integers
        well = [out[g][1] for g in out if nf[g] >= 5 and ns[g] >= 5]
    else:
        well = []
    unit = None
    if len(well) >= 8:
        cands = np.arange(4.5, 5.5, 0.002)
        cost = [np.mean((np.array(well) / u - np.round(np.array(well) / u)) ** 2) for u in cands]
        unit = cands[int(np.argmin(cost))]
        print(f"  Monotype unit {unit:.3f} px = {unit * 18 / PX_PER_PT:.2f} pt set, "
              f"rms off-grid {np.sqrt(min(cost)):.3f} units")
    # glyphs without pairs: side bearings typical of their kind
    for g, w in widths.items():
        if g not in out:
            sb = 3.5 if (len(g) == 1 and g.isupper()) else 2.5
            out[g] = (sb, w + 2 * sb)
    for g, (lsb_em, rsb_em) in SPACING_BY_HAND.get(style, {}).items():
        if g in widths:
            lsb, rsb = lsb_em * EM_PX, rsb_em * EM_PX
            out[g] = (lsb, lsb + widths[g] + rsb)
    if unit:
        for g, (lsb, adv) in out.items():
            if g in SPACING_BY_HAND.get(style, {}):
                continue
            snapped = max(1, round(adv / unit)) * unit
            out[g] = (lsb + (snapped - adv) / 2, snapped)
        digits = [out[d][1] for d in "0123456789" if d in out]
        if digits:                          # figures share one width
            fw = np.median(digits)
            for d in "0123456789":
                if d in out:
                    lsb, adv = out[d]
                    out[d] = (lsb + (fw - adv) / 2, fw)
    return out


# ---------------------------------------------------------------- specimen

_SCALE = []


def specimen_scale():
    """1947 scan px per specimen px, calibrated on the letters present in
    both sources: median ratio of their heights, less 2 px for the 1947
    ink spread the thickening of the specimen glyphs does not add back."""
    if not _SCALE:
        sp = pickle.load(open(os.path.join(WORK, "specimen.pkl"), "rb"))["glyphs"]
        M = pickle.load(open(os.path.join(WORK, "masters.pkl"), "rb"))
        r = []
        for (g, s, z), m in M.items():
            if z == 11 and (g, s) in sp and len(g) == 1 and g.isalpha():
                ys = np.nonzero((m["img"] > 0.5).any(1))[0]
                ys2 = np.nonzero((sp[(g, s)]["cov"] > 0.5).any(1))[0]
                r.append(((ys.max() - ys.min() + 1) / UP - 2) / (ys2.max() - ys2.min() + 1))
        _SCALE.append(float(np.median(r)))
        print(f"specimen scale {_SCALE[0]:.3f} from {len(r)} shared letters "
              f"(= {PX_PER_PT / _SCALE[0]:.2f} specimen px per pt)")
    return _SCALE[0]


DESCENDING = set("gjpqyQJ$")
ROUND_BOTTOM = set("CGOQSUJcdeosabqu")


def specimen_glyph(g, style, stem_target):
    """A 1922 specimen glyph resampled to master scale and thickened to the
    1947 ink weight (stem_target, in master px)."""
    sp = pickle.load(open(os.path.join(WORK, "specimen.pkl"), "rb"))
    d = sp["glyphs"].get((g, style))
    if d is None:
        return None
    f = UP * specimen_scale()
    img = ndimage.zoom(d["cov"], f, order=1)
    stem = stem_width(img)
    grow = max(0.0, (stem_target - stem) / 2)
    if grow > 0:
        out = ndimage.distance_transform_edt(img <= 0.5)
        img = np.clip((grow + 0.5 - out), 0, 1) if grow else img
        img = np.maximum(img, (out <= grow).astype(float))
    pad = 20
    img = np.pad(img, pad)
    top = d["top"] * f - pad
    if g not in DESCENDING:
        # light printing loses the bottoms of thin serifs, so the line's
        # baseline misplaces single letters: sit each one on the baseline
        # (round letters overshoot by ~1 scan px, as in the 1947 masters)
        rows = np.nonzero((img > 0.5).any(1))[0]
        bottom = top + rows.max() + 1
        want = UP * (1.0 if g in ROUND_BOTTOM else 0.0)
        top += want - bottom
    return img, top


def stem_width(img):
    """Typical vertical stem width: the most common horizontal run length."""
    bm = img > 0.5
    runs = []
    for row in bm[bm.shape[0] // 3: 2 * bm.shape[0] // 3]:
        x = np.flatnonzero(np.diff(np.r_[0, row.astype(int), 0]))
        runs += list(x[1::2] - x[0::2])
    if not runs:
        return 0
    return np.bincount(runs).argmax()


# ---------------------------------------------------------------- assembly

def glyph_name(g):
    if len(g) > 1:
        return {"fi": "fi", "ffi": "f_f_i"}[g]
    return UV2AGL.get(ord(g), "uni%04X" % ord(g))


def despeckle(img, frac=0.03):
    """Zero out ink components smaller than frac of the largest one
    (residue of misaligned or touching neighbours in the average)."""
    bm = img > 0.5
    lab, n = ndimage.label(bm)
    if n <= 1:
        return img
    areas = ndimage.sum(bm, lab, range(1, n + 1))
    small = [k + 1 for k in range(n) if areas[k] < frac * areas.max()]
    if not small:
        return img
    out = img.copy()
    out[np.isin(lab, small)] = 0
    return out


def build(style, masters, size=11, suffix=""):
    crops = {}
    for g, (img, top) in masters.items():
        img = despeckle(img)
        ys, xs = np.nonzero(img > 0.5)
        if len(ys):
            crops[g] = (img[ys.min():ys.max() + 1, xs.min():xs.max() + 1], top + ys.min())
    spacing = fit_spacing(style, size, {g: c.shape[1] / UP for g, (c, t) in crops.items()})
    glyphs = {}                              # name -> (contours, dx, dy, adv, char)
    for g, (crop, top) in crops.items():
        lsb, adv = spacing[g]
        contours = trace(np.pad(crop, 2))
        # contour coords: crop px, y up from crop bottom (incl. 2px pad)
        bottom_rel_base = (top + crop.shape[0]) / UP     # scan px below baseline (+ = below)
        dx = lsb * U_PER_PX - 2 * U_PER_UPX
        dy = -bottom_rel_base * U_PER_PX - 2 * U_PER_UPX
        glyphs[glyph_name(g) + suffix] = (contours, dx, dy, adv * U_PER_PX, g)
    return glyphs


def assemble(glyphs, family, style_name, out, extra_cmap=None, features=""):
    order = [".notdef", "space"] + sorted(glyphs)
    cs = {}
    # word space: 6 Monotype units (a third of the set), as measured
    # from the 1947 pages (median ink gap 0.36 em less side bearings)
    adv = {".notdef": 500, "space": SPACE}
    pen = T2CharStringPen(500, None)
    pen.moveTo((50, 0)); pen.lineTo((450, 0)); pen.lineTo((450, 700)); pen.lineTo((50, 700)); pen.closePath()
    cs[".notdef"] = pen.getCharString()
    cs["space"] = T2CharStringPen(SPACE, None).getCharString()
    cmap = {32: "space"}
    for name, (contours, dx, dy, a, g) in glyphs.items():
        cs[name] = charstring(contours, dx, dy, U_PER_UPX, a)
        adv[name] = round(a)
        if len(g) == 1 and not name.endswith(".sc"):
            cmap[ord(g)] = name
    cmap.update(extra_cmap or {})
    fb = FontBuilder(1000, isTTF=False)
    fb.setupGlyphOrder(order)
    fb.setupCharacterMap(cmap)
    ps = f"{family}-{style_name}".replace(" ", "")
    fb.setupCFF(ps, {"FullName": f"{family} {style_name}"}, cs, {})
    lsb = {}
    for n in order:
        b = cs[n].calcBounds(None) if n in cs else None
        lsb[n] = b[0] if b else 0
    fb.setupHorizontalMetrics({n: (adv[n], lsb[n]) for n in order})
    fb.setupHorizontalHeader(ascent=800, descent=-250)
    fb.setupNameTable({"familyName": family, "styleName": style_name})
    fb.setupOS2(sTypoAscender=800, sTypoDescender=-250, usWinAscent=900, usWinDescent=300,
                sxHeight=440, sCapHeight=650, fsSelection=0x01 if style_name == "Italic" else 0x40)
    fb.setupPost(italicAngle=-14 if style_name == "Italic" else 0)
    if style_name == "Italic":
        fb.updateHead(macStyle=2)
    if features:
        addOpenTypeFeaturesFromString(fb.font, features)
    fb.save(out)
    print(f"wrote {out}: {len(order)} glyphs")


def main():
    os.makedirs(FONTS, exist_ok=True)
    regular = {}
    M = pickle.load(open(os.path.join(WORK, "masters.pkl"), "rb"))
    for style, style_name in (("R", "Regular"), ("I", "Italic")):
        masters = {g: (m["img"], -m["base"]) for (g, s, z), m in M.items()
                   if s == style and z == 11}
        # tops are relative to baseline in master px: img row 0 is at -base
        stem = stem_width(masters["I" if style == "R" else "l"][0])
        added = []
        for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz":
            if ch not in masters:
                sg = specimen_glyph(ch, style, stem)
                if sg is not None:
                    img, top = sg
                    masters[ch] = (img, top * 1.0)
                    added.append(ch)
        if style == "R" and "-" in masters and "–" not in masters:
            # en dash: the hyphen stretched to half an em of ink
            img, top = masters["-"]
            ys, xs = np.nonzero(img > 0.5)
            crop = img[:, xs.min():xs.max() + 1]
            target = int(0.5 * EM_PX * UP)
            masters["–"] = (np.pad(ndimage.zoom(crop, (1, target / crop.shape[1]), order=1),
                                   ((0, 0), (8, 8))), top)
            added.append("–")
        print(f"{style_name}: {len(masters)} masters, from 1922 specimen: {''.join(added)}")
        # master tuples hold (img, top-of-img relative to baseline in master px)
        glyphs = build(style, masters)
        if style == "R":
            regular = dict(glyphs)
        else:
            # italic has no figures or punctuation of its own here: use roman
            for name, gl in regular.items():
                g = gl[4]
                if name not in glyphs and len(g) == 1 and not g.isalpha():
                    glyphs[name] = gl
        extra, feats = {}, ""
        if style == "R":
            # small caps: 1947 sorts where available, else the 1922 specimen
            scm = {g: (m["img"], -m["base"]) for (g, s, z), m in M.items()
                   if s == "R" and z == "SC"}
            fill = ""
            for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
                if ch not in scm:
                    sg = specimen_glyph(ch, "SC", stem)
                    if sg is not None:
                        scm[ch] = sg
                        fill += ch
            print(f"small caps: {len(scm)}, from 1922 specimen: {fill}")
            for name, gl in build("R", scm, size="SC", suffix=".sc").items():
                glyphs[name.lower()] = gl
            sc = [n[:-3] for n in glyphs if n.endswith(".sc")]
            subs = " ".join(f"sub {c} by {c}.sc;" for c in sc if c in glyphs)
            feats = ("languagesystem DFLT dflt;\nlanguagesystem latn dflt;\n"
                     "feature liga { sub f f i by f_f_i; sub f i by fi; } liga;\n"
                     f"feature smcp {{ {subs} }} smcp;\n")
        else:
            for name, (c, dx, dy, a, g) in glyphs.items():
                if len(g) == 1 and "A" <= g <= "Z":
                    extra[MATH_IT_CAP + ord(g) - 65] = name
                elif len(g) == 1 and "a" <= g <= "z":
                    extra[0x210E if g == "h" else MATH_IT_LOW + ord(g) - 97] = name
                elif g in GREEK_MATH_IT:
                    extra[GREEK_MATH_IT[g]] = name
        assemble(glyphs, "Mills 8A", style_name,
                 os.path.join(FONTS, f"Mills8A-{style_name}.otf"), extra, feats)


if __name__ == "__main__":
    main()

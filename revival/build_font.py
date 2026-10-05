"""Trace the masters, fit the spacing, and assemble OpenType fonts.

Fonts written to fonts/:
  Mills8A-Regular.otf  roman, figures, punctuation, math operators and
                       relations, fi/ffi ligatures (liga), small caps (smcp)
  Mills8A-Italic.otf   italic letters and Greek (math italic is in
                       Mills8A-Math.otf, built by build_math.py)

Units: 1000 per em of 11pt.  The 1947 scans are 600 dpi, so one em is
11 * 600/72.27 = 91.3 px, and a master pixel (4x) is 1000/365.3 units.
"""
import json
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

# Extra ink (scan px at 600 dpi, per edge) on every outline.  The Erdos and
# Niven pages the glyphs come from were printed a little lighter than the
# Mills page: 0.5 px matches the darkness of its first paragraph (measured
# against the same text set in these fonts).  MILLS8A_INK=0 = as measured.
INK_PX = float(os.environ.get("MILLS8A_INK", "1.0"))
SPACE = 322                                  # 6 units of 10.7 set, in font units
MATH_IT_CAP, MATH_IT_LOW = 0x1D434, 0x1D44E
GREEK_MATH_IT = {"α": 0x1D6FC, "β": 0x1D6FD, "ζ": 0x1D701, "π": 0x1D70B,
                 "σ": 0x1D70E, "ϕ": 0x1D719, "ϵ": 0x1D716, "ξ": 0x1D709,
                 "γ": 0x1D6FE, "η": 0x1D702, "κ": 0x1D705, "λ": 0x1D706, "μ": 0x1D707, "ν": 0x1D708,
                 "τ": 0x1D70F, "χ": 0x1D712, "ψ": 0x1D713, "ω": 0x1D714}


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
# the italic f is a kerned sort, its descender tucked under the preceding
# letter and its terminal over the next.  (The math italic f in
# Mills8A-Math.otf gets a positive left side bearing instead; see
# build_math.py.)
SPACING_BY_HAND = {"I": {"f": (-0.10, -0.07)},
                   "R": {"—": (0.02, 0.02)}}     # the em dash is constructed


_ds = os.path.join(WORK, "docscale.json")
DOCSCALE = json.load(open(_ds)) if os.path.exists(_ds) else {}   # see docweight.py


FLAT_TOPPED = set("BDEFHIKLMNPRTUVWXYZ")
FLAT_BOTH = set("BDEFHIKLMPRTXYZ")           # flat top and flat (serif) bottom


def normalize_cap_heights(M, style, size, ref=None, tol=0.01):
    """Capitals of one size share a cap height in metal type, but a sort
    averaged from few impressions (or, for bold, from titles of several
    papers set at slightly different sizes) can come out up to 4% off.
    Measured as ink extent (the baselines of title lines are noisy), each
    flat-topped capital is scaled about its baseline to the median extent of
    the letters flat at both ends; N U V W, which go below the line,
    keep the proportion they have in the reference style ref (style, size).
    Round and pointed tops (A C G J O Q S) keep their overshoot."""
    def extent(m):
        ys = np.nonzero((m["img"] > 0.5).any(1))[0]
        return ys.max() - ys.min() + 1 if len(ys) else None
    def extents(st, sz):
        e = {k[0]: extent(M[k]) for k in M if k[1] == st and k[2] == sz and k[0] in FLAT_TOPPED}
        return {g: h for g, h in e.items() if h}
    hs = extents(style, size)
    flat = [h for g, h in hs.items() if g in FLAT_BOTH]
    if len(flat) < 5:
        return
    target = float(np.median(flat))
    rel = {}
    if ref:
        r = extents(*ref)
        rflat = [h for g, h in r.items() if g in FLAT_BOTH]
        if len(rflat) >= 5:
            rel = {g: h / float(np.median(rflat)) for g, h in r.items() if g not in FLAT_BOTH}
    fixed = []
    for g, h in hs.items():
        if g in FLAT_BOTH:
            f = target / h
        elif g in rel:
            f = target * rel[g] / h
        else:
            continue
        if abs(f - 1) <= tol:
            continue
        m = M[(g, style, size)]
        m["img"] = ndimage.zoom(m["img"], f, order=1)
        m["alts"] = [ndimage.zoom(a.astype(np.float32), f, order=1).astype(np.float16)
                     for a in m.get("alts", [])]
        m["base"] = int(round(m["base"] * f))
        fixed.append(f"{g}{(f - 1) * 100:+.1f}%")
    if fixed:
        print(f"  {style}{size} capitals {target / UP:.1f} px tall: scaled " + " ".join(fixed))


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
                    sc = DOCSCALE.get(inst[a]["page"].rsplit("-", 1)[0], 1.0)
                    pairs.append((sort_of[a], sort_of[b],
                                  sc * (inst[b]["bbox"][0] - inst[a]["bbox"][0])))
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
        well_measured = {g for g in out if nf[g] >= 5 and ns[g] >= 5}
        lig_measured = {g for g in out if nf[g] >= 30 and ns[g] >= 30}
        well = [out[g][1] for g in well_measured]
    else:
        well, well_measured, lig_measured = [], set(), set()
    unit = None
    if len(well) >= 8:
        k = size / 11 if isinstance(size, (int, float)) else 1.0    # 9 pt: a smaller unit
        cands = np.arange(4.5 * k, 5.5 * k, 0.002)
        cost = [np.mean((np.array(well) / u - np.round(np.array(well) / u)) ** 2) for u in cands]
        unit = cands[int(np.argmin(cost))]
        print(f"  Monotype unit {unit:.3f} px = {unit * 18 / PX_PER_PT:.2f} pt set, "
              f"rms off-grid {np.sqrt(min(cost)):.3f} units")
    # glyphs without pairs: side bearings typical of their kind
    for g, w in widths.items():
        if g not in out:
            sb = 3.5 if (len(g) == 1 and g.isupper()) else 2.5
            out[g] = (sb, w + 2 * sb)
    if "ff" in widths and "ffi" in lig_measured and "i" in out and "ff" not in lig_measured:
        # ff: the ffi sort less the width of the i it no longer carries
        out["ff"] = (out["ffi"][0], out["ffi"][1] - out["i"][1])
    for g, (lsb_em, rsb_em) in SPACING_BY_HAND.get(style, {}).items():
        if g in widths:
            lsb, rsb = lsb_em * EM_PX, rsb_em * EM_PX
            out[g] = (lsb, lsb + widths[g] + rsb)
    # f-ligatures seen too rarely to measure (the italic ff and fi occur a
    # few times): the left bearing of f and the right bearing of the last
    # letter, as the sort is cast
    for lig, last in (("ff", "f"), ("fi", "i"), ("ffi", "i"), ("fl", "l"), ("ffl", "l")):
        if (lig in widths and "f" in out and last in out and last in widths
                and lig not in lig_measured):
            rsb = out[last][1] - out[last][0] - widths[last]
            out[lig] = (out["f"][0], out["f"][0] + widths[lig] + rsb)
    if style in FF_DX and "ff" in widths and "f" in out:
        out["ff"] = (out["f"][0], out["f"][1] + FF_DX[style] / UP)
    if unit:
        for g, (lsb, adv) in out.items():
            if g in SPACING_BY_HAND.get(style, {}) or (g == "ff" and style in FF_DX):
                continue
            snapped = max(1, round(adv / unit)) * unit
            out[g] = (lsb + (snapped - adv) / 2, snapped)
        digits = [out[d][1] for d in "0123456789" if d in out]
        if digits:                          # figures share one width, the
            fw = np.median(digits)          # old-style ones too, centred
            for d in "0123456789":
                if d in out:
                    lsb, adv = out[d]
                    out[d] = (lsb + (fw - adv) / 2, fw)
            for d in "0123456789":
                if d + ".osf" in widths:
                    out[d + ".osf"] = ((fw - widths[d + ".osf"]) / 2, fw)
    # constructed ligatures, from the final widths of their parts
    for lig, src in (("fl", "fi"), ("ffl", "ffi")):
        # roman: the fi/ffi sort less its i, plus the l
        if style == "R" and lig in widths and src in out and "i" in out and "l" in out:
            out[lig] = (out[src][0], out[src][1] - out["i"][1] + out["l"][1])
    if style == "I":
        # italic: the f (or ff) advance plus the last letter's
        for lig, first, last in (("fi", "f", "i"), ("fl", "f", "l"),
                                 ("ffi", "ff", "i"), ("ffl", "ff", "l")):
            if lig in widths and first in out and last in out:
                out[lig] = (out[first][0], out[first][1] + out[last][1])
    return out


# ---------------------------------------------------------------- specimen

_SCALE = {}


def specimen_scale(size):
    """1947 scan px per specimen px for the impressions of one point size,
    calibrated on the letters present in both sources: median ratio of
    their heights, less 2 px for the 1947 ink spread that the thickening of
    the specimen glyphs does not add back.  Calibrating each size separately
    absorbs both the page scale and the small optical-size differences."""
    if not _SCALE:
        sp = pickle.load(open(os.path.join(WORK, "specimen.pkl"), "rb"))["glyphs"]
        M = pickle.load(open(os.path.join(WORK, "masters.pkl"), "rb"))
        r = defaultdict(list)
        for (g, s, z), m in M.items():
            if z == 11 and (g, s) in sp and len(g) == 1 and g.isalpha():
                ys = np.nonzero((m["img"] > 0.5).any(1))[0]
                for imp in sp[(g, s)]:
                    ys2 = np.nonzero((imp["cov"] > 0.5).any(1))[0]
                    if len(ys2):
                        r[imp["size"]].append(((ys.max() - ys.min() + 1) / UP - 2)
                                              / (ys2.max() - ys2.min() + 1))
        for size, v in sorted(r.items()):
            _SCALE[size] = float(np.median(v))
            print(f"specimen {size}pt: scale {_SCALE[size]:.3f} from {len(v)} shared letters "
                  f"(= {PX_PER_PT * 11 / size / _SCALE[size]:.2f} specimen px per pt)")
    return _SCALE.get(size)


DESCENDING = set("gjpqyQJ$7")             # (and $ hangs below the baseline)
ROUND_BOTTOM = set("CGOQSUJcdeosabqu035689")


_GROW = {}


def specimen_grow(style, stem_target):
    """How much to thicken specimen glyphs of a style: half the difference
    between the 1947 stem and the averaged specimen I's stem.  Measured once
    on I, because the most common run length of a diagonal letter (A, M, S,
    W) is a hairline, which would make it far too bold."""
    if style not in _GROW:
        ref = specimen_glyph("I", "R" if style == "SC" else style, None, grow=0.0)
        _GROW[style] = max(0.0, (stem_target - stem_width(ref[0])) / 2) if ref else 0.0
        print(f"specimen {style}: thicken by {_GROW[style] / UP:.2f} scan px per side")
    return _GROW[style]


def specimen_glyph(g, style, stem_target, grow=None):
    """A specimen glyph: all its 1922 impressions scaled to the 1947 11pt
    master scale, aligned to sub-pixel accuracy and averaged as coverage
    (so a hairline broken in one impression is carried by the others),
    then thickened to the 1947 ink weight (stem_target, in master px)."""
    from masters import align, shift
    from scipy import fft as sfft
    sp = pickle.load(open(os.path.join(WORK, "specimen.pkl"), "rb"))
    imps = sp["glyphs"].get((g, style))
    if not imps:
        return None
    scaled = []
    for imp in imps:
        sc = specimen_scale(imp["size"])
        if sc is None:
            continue
        f = UP * sc
        scaled.append((ndimage.zoom(imp["cov"], f, order=1), imp["top"] * f))
    if not scaled:
        return None
    # common canvas, baseline at row `base`
    margin = 24
    base = int(max(-t for _, t in scaled)) + margin
    H = sfft.next_fast_len(base + int(max(t + im.shape[0] for im, t in scaled)) + margin)
    W = sfft.next_fast_len(max(im.shape[1] for im, _ in scaled) + 2 * margin)
    canv = []
    for im, t in scaled:
        c = np.zeros((H, W))
        y = base + int(round(t))
        c[y:y + im.shape[0], margin:margin + im.shape[1]] = im
        canv.append(c)
    # reference: the impression closest to 11pt
    ref = min(range(len(imps)), key=lambda k: abs(imps[k]["size"] - 11)) if len(canv) == len(imps) else 0
    t_f = sfft.rfft2(canv[ref])
    acc = sum(shift(c, *align(c, t_f)) for c in canv) / len(canv)
    t_f = sfft.rfft2(acc)
    img = sum(shift(c, *align(c, t_f)) for c in canv) / len(canv)
    # the light 1922 printing: an averaged coverage of ~0.35 is still ink
    img = np.clip(img / 0.7, 0, 1)
    if grow is None:
        grow = specimen_grow(style, stem_target)
    if grow > 0:
        out = ndimage.distance_transform_edt(img <= 0.5)
        img = np.maximum(img, np.clip(grow + 0.5 - out, 0, 1))
    top = -base
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

def stems(img, base):
    """Column runs of the vertical stems in the lower half of the x-height."""
    xh = 41 * UP
    band = img[base - xh // 2:base - xh // 8] > 0.5
    col = band.mean(0) > 0.8
    x = np.flatnonzero(np.diff(np.r_[0, col.astype(int), 0]))
    return list(zip(x[0::2], x[1::2]))            # [start, stop)


def make_ff(M):
    """The ff ligature, which the 1947 pages never use: the ffi sort cut
    between its second f and the i, with the arm and terminal of the single
    f grafted onto the second stem (as on the Monotype ff matrix)."""
    ffi, f = M.get(("ffi", "R", 11)), M.get(("f", "R", 11))
    if ffi is None or f is None:
        return None
    s3, s1 = stems(ffi["img"], ffi["base"]), stems(f["img"], f["base"])
    if len(s3) != 3 or len(s1) != 1:
        print(f"ff: unexpected stems {s3} / {s1}; skipped")
        return None
    cut = (s3[1][1] + s3[2][0]) // 2
    img = ffi["img"].copy()
    img[:, cut:] = 0
    # f's arm: everything right of its stem, placed against the 2nd stem
    dy = ffi["base"] - f["base"]
    dx = s3[1][1] - s1[0][1]
    arm = np.zeros_like(img)
    src = f["img"][:, s1[0][1]:]
    for y in range(src.shape[0]):
        yy = y + dy
        if 0 <= yy < img.shape[0]:
            x0 = s1[0][1] + dx
            w = min(src.shape[1], img.shape[1] - x0)
            arm[yy, x0:x0 + w] = src[y, :w]
    return np.maximum(img, arm), -ffi["base"]


FF_DX = {}          # style -> offset of the second f in an ff ligature (master px)


FLAT_REF = set("nmhiluHTIL")
ROUND_REF = set("oces")


def snap_sparse_to_baseline(M, style, min_n=30):
    """A sort seen only a few times inherits the baseline errors of its few
    lines (the roman I, 9 impressions, floated 2.5 px high).  Sit such
    sorts on the baseline exactly as the frequent ones sit: flat-bottomed
    letters at the median bottom of n m h i l u H T I L, round ones at
    that of o c e s (overshoot).  Shifts the master and its alternates."""
    def bottom(m):
        rows = np.nonzero((m["img"] > 0.5).any(1))[0]
        return rows.max() + 1 - m["base"]            # master px below baseline
    ref = {}
    for kind, chars in (("flat", FLAT_REF), ("round", ROUND_REF)):
        b = [bottom(m) for (g, s, z), m in M.items()
             if s == style and z == 11 and g in chars and m["n"] >= min_n]
        if b:
            ref[kind] = float(np.median(b))
    moved = []
    for (g, s, z), m in M.items():
        if s != style or z != 11 or m["n"] >= min_n or len(g) != 1:
            continue
        if not g.isalnum() or g in DESCENDING or g in "Jjpqgyf" or not g.isascii():
            continue
        want = ref.get("round" if g in ROUND_BOTTOM else "flat")
        if want is None:
            continue
        d = int(round(want - bottom(m)))
        if d and abs(d) <= 6 * UP:
            m["base"] -= d                           # lower the glyph by d
            moved.append(f"{g}{d / UP:+.1f}")
    if moved:
        print(f"{style}: baseline snapped (scan px): {' '.join(moved)}")


def make_ff_italic(M):
    """Italic ff (no ffi or ff occurs in the scans): two italic f masters,
    the second placed so its crossbar continues the first one's, and the
    first f's top terminal trimmed where it would run into the second f's
    ascender, as on the Monotype italic ff."""
    f = M.get(("f", "I", 11))
    if f is None:
        return None
    img, base = despeckle(f["img"]), f["base"]
    bm = img > 0.5
    xh = 41 * UP
    # crossbar: the row near the x-height with the widest ink extent
    rows = range(base - xh - 6 * UP, base - xh + 6 * UP)
    def extent(r):
        x = np.flatnonzero(bm[r])
        return (x.max() - x.min() + 1, x.min(), x.max()) if len(x) else (0, 0, 0)
    bar = max(rows, key=lambda r: extent(r)[0])
    _, bx0, bx1 = extent(bar)
    dx = int(bx1 - bx0 - 1 * UP)              # overlap the bars by 1 scan px
    H, W = img.shape
    out = np.zeros((H, W + dx))
    out[:, :W] = img
    second = np.zeros_like(out)
    second[:, dx:] = img
    # trim the first f above the crossbar where it comes within 2 scan px of
    # the second f's ascender
    for r in range(0, bar - 2 * UP):
        x = np.flatnonzero(second[r] > 0.5)
        if len(x):
            out[r, max(0, x.min() - 2 * UP):] = 0
    FF_DX["I"] = dx
    return np.maximum(out, second), -base


def paste(dst, dst_base, src, src_base, x0):
    """Max-composite src onto dst, baselines aligned, src column 0 at x0;
    dst is widened on the right if needed."""
    dy = dst_base - src_base
    need = x0 + src.shape[1]
    if need > dst.shape[1]:
        dst = np.pad(dst, ((0, 0), (0, need - dst.shape[1])))
    for y in range(src.shape[0]):
        yy = y + dy
        if 0 <= yy < dst.shape[0]:
            dst[yy, x0:x0 + src.shape[1]] = np.maximum(dst[yy, x0:x0 + src.shape[1]], src[y])
    return dst


LIG_DX = {}         # (style, ligature) -> x offset of its last letter (master px)


def make_l_ligature(M, base_lig, name):
    """fl / ffl, which the 1947 pages never use: the fi / ffi sort cut
    between its last f and the i, and the 1947 l set with its stem where the
    i's stem stood (its ascender meets the f's arm, as on the matrix)."""
    lig, l = M.get((base_lig, "R", 11)), M.get(("l", "R", 11))
    if lig is None or l is None:
        return None
    sl, s1 = stems(lig["img"], lig["base"]), stems(l["img"], l["base"])
    if len(sl) != len(base_lig) or len(s1) != 1:
        print(f"{name}: unexpected stems {sl} / {s1}; skipped")
        return None
    cut = (sl[-2][1] + sl[-1][0]) // 2
    img = lig["img"].copy()
    img[:, cut:] = 0
    x0 = sl[-1][0] - s1[0][0]                # l stem onto the i stem
    LIG_DX[("R", name)] = (sl[-1][0], s1[0][0])
    return paste(img, lig["base"], despeckle(l["img"]), l["base"], x0), -lig["base"]


def make_italic_ligature(M, first, second, spacing_dx):
    """Italic f-ligatures (none in the scans): the second letter set at the
    first's advance, and the f terminal trimmed wherever it comes within 2
    scan px of the second letter above the x-height."""
    a, b = M.get((first, "I", 11)) if len(first) == 1 else first, M.get((second, "I", 11))
    if a is None or b is None:
        return None
    img, base = (despeckle(a["img"]), a["base"]) if isinstance(a, dict) else a
    sec = np.zeros((img.shape[0], img.shape[1] + spacing_dx + b["img"].shape[1]))
    sec = paste(sec, base, despeckle(b["img"]), b["base"], spacing_dx)
    out = np.zeros_like(sec)
    out[:, :img.shape[1]] = img
    xh = 41 * UP
    for r in range(0, max(0, base - xh + 2 * UP)):
        x = np.flatnonzero(sec[r] > 0.5)
        if len(x):
            out[r, max(0, x.min() - 2 * UP):] = 0
    return np.maximum(out, sec), base


def glyph_name(g):
    if g.endswith(".osf"):                    # old-style figures: one.osf ...
        return UV2AGL[ord(g[0])] + ".osf"
    if len(g) > 1:
        return {"fi": "fi", "ffi": "f_f_i", "ff": "f_f", "fl": "fl", "ffl": "f_f_l"}[g]
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


def traced(img, r0, r1, c0, c1, base, c0_ink, lsb):
    """Trace img[r0:r1, c0:c1] (canvas with the baseline at row `base`) and
    return (contours, dx, dy) placing canvas column c0_ink at the left side
    bearing lsb (scan px).  Potrace coordinates are px from the padded
    crop's bottom-left corner."""
    contours = trace(np.pad(img[r0:r1, c0:c1], 2))
    dx = (c0 - 2 - c0_ink) * U_PER_UPX + lsb * U_PER_PX
    dy = (base - r1 - 2) * U_PER_UPX
    return contours, dx, dy


def embolden(img, px):
    """Grow the ink by px scan px per edge, keeping the soft edge."""
    if px <= 0:
        return img
    out = ndimage.distance_transform_edt(img <= 0.5)
    return np.maximum(img, np.clip(px * UP + 0.5 - out, 0, 1))


def alternate(alt):
    """A single impression made traceable: the bilinear upsampling of a
    1-bit scan still shows its pixel staircase, so smooth by ~1/4 scan px
    before thresholding; keep the nicks and squash that are the point."""
    return despeckle(ndimage.gaussian_filter(alt.astype(np.float32), 1.0))


def build(style, masters, size=11, suffix=""):
    """masters: {char: (img, top[, alts])}, img a coverage canvas whose row 0
    lies `top` master px from the baseline (negative = above).  Returns
    {glyph name: (contours, dx, dy, advance, char)}, alternates included as
    name.r1, name.r2, ... with the master's metrics."""
    crops = {}
    for g, v in masters.items():
        img, top = despeckle(v[0]), v[1]
        ys, xs = np.nonzero(img > 0.5)
        if len(ys):
            crops[g] = (img, -top, ys.min(), ys.max() + 1, xs.min(), xs.max() + 1,
                        v[2] if len(v) > 2 else [])
    spacing = fit_spacing(style, size, {g: (c[5] - c[4]) / UP for g, c in crops.items()})
    glyphs = {}                              # name -> (contours, dx, dy, adv, char)
    grow = int(np.ceil(INK_PX * UP)) + 1
    for g, (img, base, r0, r1, c0, c1, alts) in crops.items():
        lsb, adv = spacing[g]
        name = glyph_name(g) + suffix
        # spacing was measured on the ink as printed; extra ink grows the
        # outline around the same position (window widened to hold it)
        img = embolden(np.pad(img, grow), INK_PX)
        base, r0, r1, c0, c1 = base + grow, r0, r1 + 2 * grow, c0, c1 + 2 * grow
        glyphs[name] = (*traced(img, r0, r1, c0, c1, base, c0 + grow, lsb), adv * U_PER_PX, g)
        for k, alt in enumerate(alts, 1):
            a = embolden(np.pad(alternate(alt), grow), INK_PX)
            m = 4 * UP + grow                # impressions may reach past the mean
            ar0, ac0 = max(0, r0 - m), max(0, c0 - m)
            ar1, ac1 = min(a.shape[0], r1 + m), min(a.shape[1], c1 + m)
            if not (a[ar0:ar1, ac0:ac1] > 0.5).any():
                continue
            glyphs[f"{name}.r{k}"] = (*traced(a, ar0, ar1, ac0, ac1, base, c0 + grow, lsb),
                                      adv * U_PER_PX, g)
    return glyphs


def rand_feature(glyphs):
    """GSUB 'rand': each glyph with traced impressions is replaced by one of
    them at random (luaotfload picks per occurrence)."""
    alts = defaultdict(list)
    for name in glyphs:
        base, dot, r = name.rpartition(".r")
        if dot and r.isdigit():
            alts[base].append(name)
    rules = [f"  sub {b} from [{' '.join(sorted(v))}];" for b, v in sorted(alts.items())
             if b in glyphs]
    return "feature rand {\n" + "\n".join(rules) + "\n} rand;\n" if rules else ""


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
        if len(g) == 1 and "." not in name:
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
    for style in "RI":
        snap_sparse_to_baseline(M, style)
    for style, style_name in (("R", "Regular"), ("I", "Italic")):
        normalize_cap_heights(M, style, 11, ref=("R", 11) if style == "I" else None)
        masters = {g: (m["img"], -m["base"], m.get("alts", [])) for (g, s, z), m in M.items()
                   if s == style and z == 11}
        # tops are relative to baseline in master px: img row 0 is at -base
        stem = stem_width(masters["I" if style == "R" else "l"][0])
        added = []
        if style == "R":
            # lining figures share one height (the 7 even dips below the
            # baseline); a 1947 figure clearly shorter than the others is
            # a smaller size that slipped through: use the specimen's
            def fig_h(img):
                ys = np.nonzero((img > 0.5).any(1))[0]
                return ys.max() - ys.min() + 1
            hs = {d: fig_h(masters[d][0]) for d in "0123456789" if d in masters}
            if hs:
                med = np.median(list(hs.values()))
                for d, hh in hs.items():
                    if hh < 0.95 * med:
                        del masters[d]
                        print(f"figure {d}: 1947 sort {hh / med:.0%} of the others' height; "
                              "taking the specimen's")
        fill = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
        if style == "R":
            fill += "0123456789"
        fill += "$"                              # in the specimen's figure lines
        for ch in fill:
            if ch not in masters:
                sg = specimen_glyph(ch, style, stem)
                if sg is not None:
                    img, top = sg
                    masters[ch] = (img, top * 1.0)
                    added.append(ch)
        if style == "I" and "ff" not in masters:
            ff = make_ff_italic(M)
            if ff is not None:
                masters["ff"] = ff
                added.append("ff")
        if style == "R":
            for lig, src in (("fl", "fi"), ("ffl", "ffi")):
                if lig not in masters:
                    r = make_l_ligature(M, src, lig)
                    if r is not None:
                        masters[lig] = r
                        added.append(lig)
        if style == "I" and "f" in masters and "i" in masters and "l" in masters:
            # place each last letter one f (ff) advance after the first,
            # using the spacing the font will have
            def ink_left(img):
                return np.nonzero((despeckle(img) > 0.5).any(0))[0].min()
            widths = {g: (np.ptp(np.nonzero((despeckle(v[0]) > 0.5).any(0))[0]) + 1) / UP
                      for g, v in masters.items()}
            sp = fit_spacing("I", 11, widths)
            for lig, first, last in (("fi", "f", "i"), ("fl", "f", "l"),
                                     ("ffi", "ff", "i"), ("ffl", "ff", "l")):
                if lig in masters or first not in masters or first not in sp:
                    continue
                fimg, ftop = masters[first][0], masters[first][1]
                limg, ltop = masters[last][0], masters[last][1]
                x0 = int(round(ink_left(fimg) + (sp[first][1] - sp[first][0] + sp[last][0]) * UP
                               - ink_left(limg)))
                r = make_italic_ligature({(last, "I", 11): dict(img=limg, base=-ltop)},
                                         (despeckle(fimg), -ftop), last, x0)
                if r is not None:
                    masters[lig] = (r[0], -r[1])
                    added.append(lig)
        if style == "R" and "ff" not in masters:
            ff = make_ff(M)
            if ff is not None:
                masters["ff"] = ff
                added.append("ff")
        if style == "R" and "-" in masters and "–" not in masters:
            # en dash: the hyphen stretched to half an em of ink
            img, top = masters["-"][:2]
            ys, xs = np.nonzero(img > 0.5)
            crop = img[:, xs.min():xs.max() + 1]
            target = int(0.5 * EM_PX * UP)
            masters["–"] = (np.pad(ndimage.zoom(crop, (1, target / crop.shape[1]), order=1),
                                   ((0, 0), (8, 8))), top)
            added.append("–")
        if style == "R" and "-" in masters:
            # em dash: the 1947 "—" sort is a rule from the math (0.7 em,
            # above the hyphen); the hyphen stretched to an em of ink instead
            img, top = masters["-"][:2]
            ys, xs = np.nonzero(img > 0.5)
            crop = img[:, xs.min():xs.max() + 1]
            target = int(0.95 * EM_PX * UP)
            masters["—"] = (np.pad(ndimage.zoom(crop, (1, target / crop.shape[1]), order=1),
                                   ((0, 0), (8, 8))), top)
            added.append("—")
        print(f"{style_name}: {len(masters)} masters, from 1922 specimen: {''.join(added)}")
        # master tuples hold (img, top-of-img relative to baseline in master px)
        glyphs = build(style, masters)
        if style == "R":
            regular = dict(glyphs)
        else:
            # italic has no figures or punctuation of its own here: use roman
            for name, gl in regular.items():
                g = gl[4]
                if name not in glyphs and ((len(g) == 1 and not g.isalpha())
                                           or g.endswith(".osf")):
                    glyphs[name] = gl
        extra = {}
        feats = "languagesystem DFLT dflt;\nlanguagesystem latn dflt;\n"
        if style == "R":
            # small caps: 1947 sorts where available, else the 1922 specimen
            scm = {g: (m["img"], -m["base"], m.get("alts", [])) for (g, s, z), m in M.items()
                   if s == "R" and z == "SC"}
            fill = ""
            for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
                if ch not in scm:
                    sg = specimen_glyph(ch, "SC", stem)
                    if sg is not None:
                        scm[ch] = sg
                        fill += ch
            print(f"small caps: {len(scm)}, from 1922 specimen: {fill}")
            # one cap height for 1947 and specimen small caps alike
            tmp = {(g, "SC*", 0): dict(img=v[0], base=-v[1], alts=list(v[2]) if len(v) > 2 else [])
                   for g, v in scm.items()}
            tmp.update({k: v for k, v in M.items() if k[1:] == ("R", 11)})
            normalize_cap_heights(tmp, "SC*", 0, ref=("R", 11))
            scm = {k[0]: (v["img"], -v["base"], v["alts"]) for k, v in tmp.items() if k[1] == "SC*"}
            for name, gl in build("R", scm, size="SC", suffix=".sc").items():
                glyphs[name.lower()] = gl
            sc = [n[:-3] for n in glyphs if n.endswith(".sc")]
            subs = " ".join(f"sub {c} by {c}.sc;" for c in sc if c in glyphs)
            feats += ("feature liga { sub f f i by f_f_i; sub f f l by f_f_l; sub f f by f_f; "
                      "sub f i by fi; sub f l by fl; } liga;\n"
                      f"feature smcp {{ {subs} }} smcp;\n")
        # (math italic code points live in Mills8A-Math.otf; the text italic
        # maps only plain letters, so copied text is plain text)
        if style == "I":
            rules = [r for r, g in (("sub f f i by f_f_i;", "f_f_i"), ("sub f f l by f_f_l;", "f_f_l"),
                                    ("sub f f by f_f;", "f_f"), ("sub f i by fi;", "fi"),
                                    ("sub f l by fl;", "fl")) if g in glyphs]
            if rules:
                feats += "feature liga { " + " ".join(rules) + " } liga;\n"
        osf = [glyph_name(d) for d in "0123456789" if glyph_name(d + ".osf") in glyphs]
        if osf:                             # old-style figures on request
            feats += ("feature onum { " + " ".join(f"sub {n} by {n}.osf;" for n in osf)
                      + " } onum;\n")
        feats += rand_feature(glyphs)
        assemble(glyphs, "Mills 8A", style_name,
                 os.path.join(FONTS, f"Mills8A-{style_name}.otf"), extra, feats)


if __name__ == "__main__":
    main()

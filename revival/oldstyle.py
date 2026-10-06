"""Old-style figures, added to work/masters.pkl as ("1.osf", "R", 11) etc.

The Bulletin sets the year in its running heads in old-style figures
("1947]", "1944]"); its page numbers, the text and the Transactions use
lining figures, and the 1922 specimen shows lining figures only.  So the
scans hold the real old-style figures of their years (1940-1948: all ten),
in the ~8 pt type of the heads.

* Real: the year tokens are the four glyphs before the "]" that opens the
  running head of odd pages; their digits are known from the paper's year.
  Each figure's impressions are averaged (masters.build), scaled from the
  head's x-height to the text's, and thinned to the stem weight of the
  11 pt lowercase (a smaller size is cut relatively heavier).
* Constructed, from the 1947 lining figures, by the proportions the real
  ones show: 0 2 at the height of the old-style 1; 3 5 hung like 9 and 7
  (top at that height, bottom at their descent); 6 8 as the lining ones.
"""
import os
import pickle
from collections import defaultdict

import numpy as np
from scipy import ndimage

import masters as ms

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, "work")
UP = ms.UP
# Bulletin papers carry their year in old-style figures in the running heads;
# the year is the scan's file name's last four digits.  The Transactions
# (Kleene, Eilenberg-Mac Lane) set it in lining figures.
TRANSACTIONS = {"kleene1943", "eilenbergmaclane1945"}


def year_of(doc):
    return None if doc in TRANSACTIONS or not doc[-4:].isdigit() else doc[-4:]
XLETTERS = set("unearmovcs")


def year_tokens(inst):
    lines = defaultdict(list)
    for i, g in enumerate(inst):
        if g["line"] >= 0:
            lines[(g["page"], g["line"])].append(i)
    first_line = {}
    for (p, l), ids in lines.items():
        y = min(inst[i]["bbox"][1] for i in ids)
        if p not in first_line or y < first_line[p][0]:
            first_line[p] = (y, (p, l))
    got, head_x = defaultdict(list), []
    for p, (_, key) in first_line.items():
        doc = p.rsplit("-", 1)[0]
        if not year_of(doc):
            continue
        ids = sorted(lines[key], key=lambda i: inst[i]["bbox"][0])
        head_x += [inst[i]["bitmap"].shape[0] for i in ids
                   if inst[i]["ch"] in XLETTERS and inst[i]["conf"] > 85]
        if len(ids) < 6:
            continue
        first = ids[:5]
        h = [inst[i]["bitmap"].shape[0] for i in first]
        gap = inst[first[4]]["bbox"][0] - inst[first[3]]["bbox"][2]
        if h[4] > max(h[:4]) and gap < 15:              # 4 figures, then "]"
            for d, i in zip(year_of(doc), first[:4]):
                got[d].append(inst[i])
    return got, float(np.median(head_x))


def extent(img):
    ys = np.nonzero((img > 0.5).any(1))[0]
    return ys.min(), ys.max()


def zoom_master(m, k):
    return dict(img=ndimage.zoom(m["img"], k, order=1),
                base=int(round(m["base"] * k)),
                alts=[ndimage.zoom(a.astype(np.float32), k, order=1).astype(np.float16)
                      for a in m.get("alts", [])], n=m["n"])


def reweigh(m, d):
    """Grow (d > 0) or thin the ink by d master px per edge."""
    r = int(round(abs(d)))
    if r == 0:
        return m
    op = ndimage.grey_dilation if d > 0 else ndimage.grey_erosion
    fp = ms.disk(r)
    m = dict(m)
    m["img"] = op(np.pad(m["img"], r), footprint=fp)
    m["alts"] = [op(np.pad(a.astype(np.float32), r), footprint=fp).astype(np.float16)
                 for a in m["alts"]]
    m["base"] += r
    return m


def stem(m):
    return ms.stroke(m["img"] > 0.5)


def hairline(img):
    """Thickness of the thin strokes: the shorter ink runs down the middle
    column (top and bottom of a bowl)."""
    xs = np.flatnonzero((img > 0.5).any(0))
    col = img[:, (xs.min() + xs.max()) // 2] > 0.5
    d = np.diff(np.r_[0, col.astype(int), 0])
    runs = np.flatnonzero(d == -1) - np.flatnonzero(d == 1)
    return float(np.min(runs)) if len(runs) else 0.0


def thin_horizontals(m, r):
    """Thin the horizontal strokes by r master px per edge (vertical
    erosion, which leaves vertical stems as wide as they are), then restore
    the glyph's height."""
    if r <= 0:
        return m
    fp = np.ones((2 * r + 1, 1), bool)
    t0, b0 = extent(m["img"])
    out = dict(m)
    out["img"] = ndimage.grey_erosion(m["img"], footprint=fp)
    out["alts"] = [ndimage.grey_erosion(a.astype(np.float32), footprint=fp).astype(np.float16)
                   for a in m["alts"]]
    t1, b1 = extent(out["img"])
    f = (b0 - t0 + 1) / (b1 - t1 + 1)                 # height back, width kept
    out["img"] = ndimage.zoom(out["img"], (f, 1), order=1)
    out["alts"] = [ndimage.zoom(a.astype(np.float32), (f, 1), order=1).astype(np.float16)
                   for a in out["alts"]]
    out["base"] = extent(out["img"])[1] - (b0 - m["base"])   # bottom where it was
    return out


def proportions(got):
    """{figure: (top, descent)} in head px, ink spread (~2 px) taken off,
    measured on the impressions in the running heads."""
    out = {}
    for d, v in got.items():
        top = np.median([m["baseline_ref"] - m["bbox"][1] for m in v]) - 2
        bot = np.median([m["bbox"][3] - m["baseline_ref"] for m in v]) - 2
        out[d] = (float(top), float(bot) if bot > 4 else 0.0)
    return out


def to_proportion(m, top, bot):
    """Scale m (uniformly) and place it so its ink runs from top above the
    baseline to bot below it (master px)."""
    t, b = extent(m["img"])
    m = zoom_master(m, (top + bot) / (b - t + 1))
    t, b = extent(m["img"])
    m["base"] = int(round(b - bot))
    return m


def main():
    inst = pickle.load(open(os.path.join(WORK, "instances.pkl"), "rb"))
    M = pickle.load(open(os.path.join(WORK, "masters.pkl"), "rb"))
    for k in [k for k in M if k[0].endswith(".osf")]:
        del M[k]
    got, head_x = year_tokens(inst)
    body_x = []
    for k in (("x", "R", 11), ("v", "R", 11), ("z", "R", 11), ("u", "R", 11)):
        if k in M:
            t, b = extent(M[k]["img"])
            body_x.append((b - t + 1) / UP)
    # x-heights with the ink spread (~2 px per edge) taken off, as in assign.py
    k = (float(np.median(body_x)) - 4) / (head_x - 4)
    # old-style figures sit with the lowercase: their stems match the letters'
    # (the lining figures print ~7% heavier than the letters)
    target_stem = float(np.median([stem(M[(c, "R", 11)]) for c in "nmhuo" if (c, "R", 11) in M]))
    osf = {}
    for d, members in sorted(got.items()):
        r = ms.build(members)
        if r is None:
            continue
        img, n, base, alts = r
        osf[d] = zoom_master(dict(img=img, base=base, alts=alts, n=n), k)
        print(f"old-style {d}: {n} impressions from the running heads, scaled {k:.2f}")
    # each figure from its own year's papers: small differences in scale
    # between the scans put them out of proportion (the 0, all from 1940,
    # came out 10% too tall).  Height and descent as measured in the heads,
    # relative to the 1, which every year has
    prop = proportions(got)
    targets = {}
    if "1" in osf and "1" in prop:
        t1, b1 = extent(osf["1"]["img"])
        px = (osf["1"]["base"] - t1) / prop["1"][0]      # master px per head px
        # on the line: flat feet (1 2) exactly, round bottoms (0 6 8) by the
        # o's overshoot -- the heads' baselines are good to a pixel only
        o_m = M[("o", "R", 11)]
        over = extent(o_m["img"])[1] - o_m["base"]
        for d in list(osf):
            if d in prop:
                top, bot = prop[d][0] * px, prop[d][1] * px
                if d in "12":
                    top, bot = top + bot, 0.0
                elif d in "068":
                    top, bot = top + bot - over, over
                targets[d] = (top, bot)
                osf[d] = to_proportion(osf[d], top, bot)
    # the ~8 pt head type is cut with heavy hairlines (it must survive at
    # that size); scaled to 11 pt, the bowl of the 0 -- all hairline at top
    # and bottom -- reads heavier than the o beside it.  Its horizontal
    # strokes are thinned to the o's contrast; the other figures, whose thin
    # strokes are curves and diagonals that vertical thinning would break,
    # only get their stems matched to the letters
    o_ratio = hairline(M[("o", "R", 11)]["img"]) / stem(M[("o", "R", 11)])
    thin = 0
    if "0" in osf:
        best = None
        for rv in range(0, 25):
            m0 = reweigh(thin_horizontals(osf["0"], rv),
                         (target_stem - stem(thin_horizontals(osf["0"], rv))) / 2)
            err = abs(hairline(m0["img"]) / stem(m0) - o_ratio)
            if best is None or err < best[0]:
                best = (err, rv)
        thin = best[1]
        print(f"old-style figures: hairlines thinned {thin / UP:.2f} px per edge "
              f"(contrast of the o: {o_ratio:.2f})")
    for d in list(osf):
        m = thin_horizontals(osf[d], thin) if d == "0" else osf[d]
        for _ in range(3):                     # weight and size, until both hold
            m = reweigh(m, (target_stem - stem(m)) / 2)
            if d in targets:                   # the stem match moves the edges
                m = to_proportion(m, *targets[d])
        osf[d] = m
    if "1" not in osf or not ({"9", "7"} & set(osf)):
        print("old-style figures: too few real ones; none built")
        return
    # proportions of the real ones (master px, relative to the baseline row)
    t1, b1 = extent(osf["1"]["img"])
    x_top = osf["1"]["base"] - t1                     # height of 0 1 2
    desc = [extent(osf[d]["img"])[1] - osf[d]["base"] for d in "97" if d in osf]
    d_bot = float(np.median(desc))                    # descent of 3 4 5 7 9
    for d in "0123456789":
        if d in osf or (d, "R", 11) not in M:
            continue
        lin = M[(d, "R", 11)]
        t, b = extent(lin["img"])
        h = b - t + 1
        if d in "02":
            m = zoom_master(lin, x_top / h)
        elif d in "35":
            m = zoom_master(lin, (x_top + d_bot) / h)
            tt, bb = extent(m["img"])
            m["base"] = int(round(bb - d_bot))       # hang it below the line
        else:                                         # 6 8 ascend like lining
            m = dict(lin)
        m = reweigh(m, (target_stem - stem(m)) / 2)
        osf[d] = m
        print(f"old-style {d}: constructed from the 1947 lining {d}")
    for d, m in osf.items():
        m["img"] = m["img"].astype(np.float32)
        M[(d + ".osf", "R", 11)] = m
    pickle.dump(M, open(os.path.join(WORK, "masters.pkl"), "wb"))


if __name__ == "__main__":
    main()

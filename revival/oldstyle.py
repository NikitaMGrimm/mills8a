"""Old-style figures, added to work/masters.pkl as ("1.osf", "R", 11) etc.

The Bulletin sets the year in its running heads in old-style figures
("1947]", "1944]"); its page numbers, the text and the Transactions use
lining figures, and the 1922 specimen shows lining figures only.  So the
scans hold real old-style 1, 4, 7 and 9, in the ~8 pt type of the heads.

* Real: the year tokens are the four glyphs before the "]" that opens the
  running head of odd pages; their digits are known from the paper's year.
  Each figure's impressions are averaged (masters.build), scaled from the
  head's x-height to the text's, and thinned to the stem weight of the
  11 pt lining figures (a smaller size is cut relatively heavier).
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
YEAR = {"post1944": "1944", "doob1947": "1947", "kac1947": "1947", "erdos1947": "1947",
        "vonneumanngoldstine1947": "1947", "niven1947": "1947"}
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
        if doc not in YEAR:
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
            for d, i in zip(YEAR[doc], first[:4]):
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
    lining_stem = float(np.median([stem(M[(d, "R", 11)]) for d in "147" if (d, "R", 11) in M]))
    osf = {}
    for d, members in sorted(got.items()):
        r = ms.build(members)
        if r is None:
            continue
        img, n, base, alts = r
        m = zoom_master(dict(img=img, base=base, alts=alts, n=n), k)
        m = reweigh(m, (lining_stem - stem(m)) / 2)
        osf[d] = m
        print(f"old-style {d}: {n} impressions from the running heads, scaled {k:.2f}")
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
        m = reweigh(m, (lining_stem - stem(m)) / 2)
        osf[d] = m
        print(f"old-style {d}: constructed from the 1947 lining {d}")
    for d, m in osf.items():
        m["img"] = m["img"].astype(np.float32)
        M[(d + ".osf", "R", 11)] = m
    pickle.dump(M, open(os.path.join(WORK, "masters.pkl"), "wb"))


if __name__ == "__main__":
    main()

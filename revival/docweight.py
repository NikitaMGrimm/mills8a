"""Measure each scanned document's stroke weight against the Erdős paper.

The papers come from different scans (threshold, scanner), and a heavier
scan would make every master averaged from it heavier.  For confidently
read body-size lowercase letters, the stroke width (masters.stroke) is
compared letter by letter with the same letter in erdos1947, the scan the
ink calibration (build_font.INK_PX) was fitted on.  The median difference,
halved, is the document's extra ink per edge; masters.py removes it before
averaging.

The type in the Transactions scans is also ~4% smaller than in the
Bulletin (same 12 pt line pitch, so not the scan resolution).  Each
document's scale relative to the Erdős paper is the median ratio of the
ink-corrected widths and heights of the same letters; masters.py and the
spacing fit resample by it.  The weight is measured after scaling.

Output: work/docweight.json {document: extra px per edge} and
work/docscale.json {document: factor to the Erdős size}.
"""
import json
import os
import pickle
from collections import defaultdict

import numpy as np

from masters import stroke

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, "work")
LETTERS = set("acehmnorsu")
REF = "erdos1947"


def doc(page):
    return page.rsplit("-", 1)[0]


def main():
    inst = pickle.load(open(os.path.join(WORK, "instances.pkl"), "rb"))
    w = defaultdict(lambda: defaultdict(list))
    hts = defaultdict(list)
    for g in inst:
        if g["ch"] in LETTERS and g["conf"] > 92 and g["baseline_ref"] is not None:
            hts[g["ch"]].append(g["bitmap"].shape[0])
    body = {c: np.median(v) for c, v in hts.items()}
    for g in inst:
        c = g["ch"]
        if c in body and g["conf"] > 92 and abs(g["bitmap"].shape[0] - body[c]) <= 3:
            d = w[doc(g["page"])][c]
            if len(d) < 300:
                d.append(stroke(g["bitmap"]))
    # scale: ink-corrected bbox width and height, letter by letter
    raw = {}
    for d, per in w.items():
        diffs = [np.median(v) - np.median(w[REF][c]) for c, v in per.items()
                 if len(v) >= 10 and len(w[REF].get(c, [])) >= 10]
        raw[d] = float(np.median(diffs)) / 2 if diffs else 0.0
    dims = defaultdict(lambda: defaultdict(list))
    for g in inst:
        c = g["ch"]
        if c in body and g["conf"] > 92 and abs(g["bitmap"].shape[0] - body[c]) <= 4:
            d = doc(g["page"])
            e = 2 * raw.get(d, 0.0)
            h, wd = g["bitmap"].shape
            dims[d][c].append((h - e, wd - e))
    scale = {}
    for d, per in sorted(dims.items()):
        r = [np.median([x[k] for x in w0]) / np.median([x[k] for x in v])
             for c, v in per.items() if len(v) >= 20
             for w0 in [dims[REF].get(c, [])] if len(w0) >= 20 for k in (0, 1)]
        s = float(np.median(r)) if r else 1.0
        scale[d] = round(s, 4) if abs(s - 1) > 0.01 else 1.0
    json.dump(scale, open(os.path.join(WORK, "docscale.json"), "w"), indent=1)
    out = {}
    for d, per in sorted(w.items()):
        sc = scale.get(d, 1.0)
        per = {c: [x * sc for x in v] for c, v in per.items()}
        diffs = [np.median(v) - np.median(w[REF][c]) for c, v in per.items()
                 if len(v) >= 10 and len(w[REF].get(c, [])) >= 10]
        out[d] = round(float(np.median(diffs)) / 2, 2) if diffs else 0.0
        print(f"{d:28s} {sum(map(len, per.values())):6d} letters  scale {sc:.4f}  "
              f"stroke {np.median(diffs) if diffs else 0:+.2f} px -> {out[d]:+.2f} px per edge")
    json.dump(out, open(os.path.join(WORK, "docweight.json"), "w"), indent=1)


if __name__ == "__main__":
    main()

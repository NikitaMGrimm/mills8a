"""Measure each scanned document's stroke weight against the Erdős paper.

The papers come from different scans (threshold, scanner), and a heavier
scan would make every master averaged from it heavier.  For confidently
read body-size lowercase letters, the stroke width (masters.stroke) is
compared letter by letter with the same letter in erdos1947, the scan the
ink calibration (build_font.INK_PX) was fitted on.  The median difference,
halved, is the document's extra ink per edge; masters.py removes it before
averaging.

Output: work/docweight.json {document: extra px per edge}.
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
    out = {}
    for d, per in sorted(w.items()):
        diffs = [np.median(v) - np.median(w[REF][c]) for c, v in per.items()
                 if len(v) >= 10 and len(w[REF].get(c, [])) >= 10]
        out[d] = round(float(np.median(diffs)) / 2, 2) if diffs else 0.0
        print(f"{d:28s} {sum(map(len, per.values())):6d} letters  "
              f"stroke {np.median(diffs) if diffs else 0:+.2f} px -> {out[d]:+.2f} px per edge")
    json.dump(out, open(os.path.join(WORK, "docweight.json"), "w"), indent=1)


if __name__ == "__main__":
    main()

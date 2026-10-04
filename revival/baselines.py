"""Re-estimate each text line's baseline from the glyphs sitting on it.

Tesseract's baseline is a line fit that display math (fractions, limits)
can pull off by 10+ px.  Here a line's baseline is the median bottom edge
of its confidently recognised letters and figures without descenders.
Adds 'baseline_ref' to every instance (falls back to Tesseract's value).
Kept separate from segment.py so cluster numbering, which overrides.tsv
refers to, does not change.
"""
import os
import pickle
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, "work")
ON_BASELINE = set("acemnorsuvwxzhklbdi0123456789ABCDEFHIKLMNPRTUVWXZ")


def main():
    path = os.path.join(WORK, "instances.pkl")
    inst = pickle.load(open(path, "rb"))
    bottoms = defaultdict(list)
    for g in inst:
        if g["line"] >= 0 and g["ch"] in ON_BASELINE and g["conf"] > 85:
            bottoms[(g["page"], g["line"])].append(g["bbox"][3])
    moved = []
    for g in inst:
        b = bottoms.get((g["page"], g["line"]))
        if g["baseline"] is not None and b and len(b) >= 3:
            g["baseline_ref"] = float(np.median(b))
            moved.append(g["baseline_ref"] - g["baseline"])
        else:
            g["baseline_ref"] = g["baseline"]
    pickle.dump(inst, open(path, "wb"))
    moved = np.abs(moved)
    print(f"refined {len(moved)} instances; shift median {np.median(moved):.1f} px, "
          f">3px for {(moved > 3).sum()}")


if __name__ == "__main__":
    main()

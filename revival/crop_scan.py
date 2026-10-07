"""Crop a scanned page to its ink (dust and scan-edge marks dropped) and
save it as a grey PNG 1400 px wide: the left half of a comparison.
    python3 revival/crop_scan.py page.png out.png"""
import sys

import numpy as np
from PIL import Image
from scipy import ndimage


def main(src, dst):
    im = Image.open(src).convert("L")
    a = np.asarray(im) < 128
    lab, n = ndimage.label(a)
    objs = ndimage.find_objects(lab)
    size = ndimage.sum(a, lab, range(1, n + 1))
    H, W = a.shape
    keep = np.zeros(n + 1, bool)
    for i, (o, s) in enumerate(zip(objs, size), 1):
        y, x = o
        edge = y.start < 5 or x.start < 5 or y.stop > H - 5 or x.stop > W - 5
        keep[i] = s >= 6 and not edge
    ink = keep[lab]
    ys, xs = np.nonzero(ink)
    crop = np.where(ink, 0, 255).astype(np.uint8)[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    out = Image.fromarray(crop)
    out = out.resize((1400, round(out.height * 1400 / out.width)), Image.LANCZOS)
    out.save(dst, optimize=True)


if __name__ == "__main__":
    main(*sys.argv[1:3])

"""Propose labels for script-size clusters (indices, exponents, footnote marks).

OCR is unreliable on 6-8pt letters, so small clusters are labelled by
template matching instead: every 11pt master is turned into a candidate
at 8, 7 and 6pt -- its ~2px of ink spread removed, scaled down, the 2px
added back (ink spread is a constant amount, which makes small sizes
relatively heavier) -- and each cluster takes the best match by
intersection over union at the best small shift.

Writes work/script_proposals.tsv (key, glyph, style, size, iou, cluster id,
n) and work/scripts.png, a contact sheet of clusters next to their best
candidate, for checking before the proposals go into overrides.tsv.
"""
import os
import pickle

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, "work")
UP = 4
INK = 2.0                       # scan px of ink spread per edge
SIZES = (8, 7, 6)


def candidate(img, size):
    """An 11pt master (UP x coverage) as a 1x bitmap at `size` pt."""
    bm = img > 0.5
    thin = ndimage.binary_erosion(bm, iterations=int(INK * UP))
    if thin.sum() < 0.2 * bm.sum():
        thin = bm
    small = ndimage.zoom(thin.astype(float), size / 11 / UP, order=1) > 0.4
    return ndimage.binary_dilation(small, iterations=int(INK))


def crop(bm):
    ys, xs = np.nonzero(bm)
    return bm[ys.min():ys.max() + 1, xs.min():xs.max() + 1] if len(ys) else bm


def iou_best(a, b, shift=2):
    """Best IoU of two bitmaps, centred on each other, over small shifts."""
    H = max(a.shape[0], b.shape[0]) + 2 * shift + 2
    W = max(a.shape[1], b.shape[1]) + 2 * shift + 2
    A = np.zeros((H, W), bool)
    ya, xa = (H - a.shape[0]) // 2, (W - a.shape[1]) // 2
    A[ya:ya + a.shape[0], xa:xa + a.shape[1]] = a
    best = 0.0
    for dy in range(-shift, shift + 1):
        for dx in range(-shift, shift + 1):
            B = np.zeros((H, W), bool)
            yb, xb = (H - b.shape[0]) // 2 + dy, (W - b.shape[1]) // 2 + dx
            if yb < 0 or xb < 0 or yb + b.shape[0] > H or xb + b.shape[1] > W:
                continue
            B[yb:yb + b.shape[0], xb:xb + b.shape[1]] = b
            u = np.count_nonzero(A | B)
            best = max(best, np.count_nonzero(A & B) / u if u else 0)
    return best


def main():
    M = pickle.load(open(os.path.join(WORK, "masters.pkl"), "rb"))
    sorts = pickle.load(open(os.path.join(WORK, "sorts.pkl"), "rb"))
    clusters = pickle.load(open(os.path.join(WORK, "clusters.pkl"), "rb"))
    inst = pickle.load(open(os.path.join(WORK, "instances.pkl"), "rb"))
    assigned = {cid: k for k, v in sorts.items() for cid in v}
    cands = []
    for (g, s, z), m in M.items():
        if z != 11 or len(g) != 1:
            continue
        for size in SIZES:
            cands.append((g, s, size, crop(candidate(m["img"], size))))
    rows = []
    for c in clusters:
        if c["n"] < 2:
            continue
        k = assigned.get(c["id"])
        if k is not None and k[2] not in SIZES:
            continue                       # already a body-size (or SC, T, D) sort
        bm = crop(c["mean"] > 0.5)
        if bm.shape[0] > 50 or bm.sum() < 15:
            continue
        scores = sorted(((iou_best(bm, t), g, s, z) for g, s, z, t in cands
                         if abs(t.shape[0] - bm.shape[0]) <= 4
                         and abs(t.shape[1] - bm.shape[1]) <= 5), reverse=True)
        if not scores:
            continue
        iou, g, s, z = scores[0]
        g0 = inst[c["members"][0]]
        key = f"{g0['page']}@{g0['bbox'][0]},{g0['bbox'][1]}"
        rows.append((key, g, s, z, iou, c["id"], c["n"], bm,
                     [t for gg, ss, zz, t in cands if (gg, ss, zz) == (g, s, z)][0]))
    rows.sort(key=lambda r: -r[6])
    with open(os.path.join(WORK, "script_proposals.tsv"), "w", encoding="utf-8") as f:
        for key, g, s, z, iou, cid, n, _, _ in rows:
            f.write(f"{key}\t{g}\t{s}\t{z}\t{iou:.2f}\t{cid}\t{n}\n")
    cols, cell = 12, 110
    S = Image.new("L", (cols * cell, ((len(rows) + cols - 1) // cols) * cell), 255)
    d = ImageDraw.Draw(S)
    for j, (key, g, s, z, iou, cid, n, bm, t) in enumerate(rows):
        x, y = (j % cols) * cell, (j // cols) * cell
        S.paste(Image.fromarray(np.where(bm, 0, 255).astype(np.uint8)), (x + 4, y + 4))
        S.paste(Image.fromarray(np.where(t, 140, 255).astype(np.uint8)), (x + 56, y + 4))
        d.text((x + 3, y + cell - 26), f"#{j} n{n} iou{iou:.2f}", fill=0)
        d.text((x + 3, y + cell - 14), f"{g} {s}{z}", fill=0)
        d.rectangle([x, y, x + cell - 1, y + cell - 1], outline=210)
    S.save(os.path.join(WORK, "scripts.png"))
    print(f"{len(rows)} script-size clusters proposed")


if __name__ == "__main__":
    main()

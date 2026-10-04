"""Extract the 11pt alphabets from the 1922 Lanston Monotype specimen book
(page 49, "No. 8A, Book Arrangement C"), to supply letters the 1947 pages
never use.

The page is a ~457 dpi grayscale scan.  Each alphabet line is segmented into
glyphs (small components such as i-dots attach to the nearest large one)
and matched in order against the known string; a line whose count does not
match is reported and skipped.

Output: work/specimen.pkl {(glyph, style): dict(cov, top, left)} where cov is
ink coverage in [0,1] at the specimen's resolution and top is the row of the
crop's top relative to the baseline (negative = above), in specimen px.
"""
import os
import pickle

import numpy as np
from PIL import Image
from scipy import ndimage

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, "work")
SRC = os.path.join(HERE, "scans", "lanston1922-p49.jp2")

# Specimen px per pt: line pitch 70 px for 11pt set solid.
PX_PER_PT = 70 / 11
REGION = (150, 3330, 1380, 3720)          # x0, y0, x1, y1 of the alphabet block
LINES = [
    ("R", "12345abcdefghijklmnopqrstuvwxyz67890$"),
    ("R", "ABCDEFGHIJKLMNOPQRSTUVWXYZ"),
    ("SC", "ABCDEFGHIJKLMNOPQRSTUVWXYZ"),
    ("I", "12345abcdefghijklmnopqrstuvwxyz67890$"),
    ("I", "ABCDEFGHIJKLMNOPQRSTUVWXYZ"),
]
DESCENDERS = set("gjpqy$QJ")


def segment(sub, expect):
    """Split one text line into glyphs; None unless exactly `expect` found."""
    lab, n = ndimage.label(sub, structure=np.ones((3, 3)))
    if n == 0:
        return None
    objs = ndimage.find_objects(lab)
    areas = ndimage.sum(sub, lab, range(1, n + 1))
    big = [k for k in range(n) if areas[k] > 0.12 * np.median(areas)]
    small = [k for k in range(n) if k not in big]
    # merge big pieces that overlap horizontally (a letter broken at a hairline)
    big.sort(key=lambda k: objs[k][1].start)
    merged = []
    for k in big:
        if merged:
            p = merged[-1]
            px0 = min(objs[q][1].start for q in p); px1 = max(objs[q][1].stop for q in p)
            kx0, kx1 = objs[k][1].start, objs[k][1].stop
            if min(px1, kx1) - max(px0, kx0) > 0.5 * min(px1 - px0, kx1 - kx0):
                p.append(k)
                continue
        merged.append([k])
    groups = {p[0]: p for p in merged}
    big = list(groups)
    for k in small:                        # attach dots to the nearest glyph
        cx = (objs[k][1].start + objs[k][1].stop) / 2
        near = min(big, key=lambda b: abs((objs[b][1].start + objs[b][1].stop) / 2 - cx))
        groups[near].append(k)
    order = sorted(groups, key=lambda b: objs[b][1].start)
    if len(order) != expect:
        return None
    return lab, objs, groups, order


def main():
    g = np.array(Image.open(SRC).convert("L")).astype(float)
    x0, y0, x1, y1 = REGION
    g = g[y0:y1, x0:x1]
    paper, ink = np.percentile(g, 90), np.percentile(g, 1)
    cov = np.clip((paper - g) / (paper - ink), 0, 1)
    bm = cov > 0.4

    # text lines from the row profile
    prof = bm.sum(1)
    on = prof > 2
    bands, start = [], None
    for y, v in enumerate(on):
        if v and start is None:
            start = y
        if not v and start is not None:
            if y - start > 12:
                bands.append((start, y))
            start = None
    if start is not None:
        bands.append((start, len(on)))
    if len(bands) != len(LINES):
        raise SystemExit(f"found {len(bands)} lines, expected {len(LINES)}: {bands}")

    out = {}
    for (style, text), (b0, b1) in zip(LINES, bands):
        for thr in (0.3, 0.35, 0.4, 0.45, 0.5, 0.25, 0.55, 0.6, 0.2):
            seg = segment(cov[b0:b1] > thr, len(text))
            if seg is not None:
                break
        else:
            print(f"{style} {text[:12]}...: no threshold gives {len(text)} glyphs; skipped")
            continue
        lab, objs, groups, order = seg
        # baseline: median bottom of glyphs without descenders
        bottoms = [objs[b][0].stop for b, ch in zip(order, text) if ch not in DESCENDERS]
        base = int(np.median(bottoms))
        for b, ch in zip(order, text):
            ks = groups[b]
            ys0 = min(objs[k][0].start for k in ks); ys1 = max(objs[k][0].stop for k in ks)
            xs0 = min(objs[k][1].start for k in ks); xs1 = max(objs[k][1].stop for k in ks)
            mask = np.isin(lab[ys0:ys1, xs0:xs1], [k + 1 for k in ks])
            # keep the soft edge: coverage inside a 1px dilation of the mask
            mask = ndimage.binary_dilation(mask, iterations=1)
            c = cov[b0 + ys0:b0 + ys1, xs0:xs1] * mask
            out[(ch, style)] = dict(cov=c, top=ys0 - base, left=xs0)
        print(f"{style} {text[:12]}...: ok (threshold {thr})")
    pickle.dump(dict(glyphs=out, px_per_pt=PX_PER_PT), open(os.path.join(WORK, "specimen.pkl"), "wb"))
    print(f"{len(out)} specimen glyphs")


if __name__ == "__main__":
    main()

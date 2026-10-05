"""Average all instances of each sort into one high-resolution master image.

Every instance is upsampled UP times (bilinear, which turns the 1-bit
staircase into a usable edge profile) and placed on a canvas (sized per
sort) whose row `base` is the baseline.  Pass 1 aligns every instance to a
typical one by FFT cross-correlation, i.e. to 1/UP px; pass 2 realigns all
of them to the pass-1 mean and drops instances that overlap it poorly
(broken or filled-in sorts, mislabels).

Output: work/masters.pkl {(glyph, style, size): dict(img, base, n, alts)}
with img in [0,1] ink coverage at UP x 600 dpi, alts up to NALT single
impressions aligned to img (for the OpenType rand feature), and
work/masters.png for review.
"""
import os
import pickle

import numpy as np
from PIL import Image, ImageDraw
from scipy import fft as sfft
from scipy import ndimage

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, "work")
UP = 4
MAXSHIFT = 4 * UP                 # vertical search radius (UP px)
MARGIN = 6 * UP                   # canvas margin around the largest instance
NALT = 4                          # alternates (single impressions) per sort


def canvas_geometry(members):
    tops = [m["bbox"][1] - m["baseline_ref"] for m in members]
    bots = [m["bbox"][3] - m["baseline_ref"] for m in members]
    wid = max(m["bbox"][2] - m["bbox"][0] for m in members)
    base = int(-min(tops) * UP) + MARGIN
    h = sfft.next_fast_len(base + int(max(bots) * UP) + MARGIN)
    w = sfft.next_fast_len(int(wid * UP) + 2 * MARGIN)
    return h, w, base


def place(inst, geo):
    H, W, base = geo
    bm = inst["bitmap"].astype(float)
    up = ndimage.zoom(np.pad(bm, 1), UP, order=1)[UP:-UP, UP:-UP]
    can = np.zeros((H, W))
    y = base + int(round((inst["bbox"][1] - inst["baseline_ref"]) * UP))
    h, w = up.shape
    if y < 0 or y + h > H or MARGIN + w > W:
        return None
    can[y:y + h, MARGIN:MARGIN + w] = up
    return can


def align(img, tmpl_f):
    """Cyclic shift (dy, dx) maximising correlation with the template
    (given as its rfft2); vertical search limited to +-MAXSHIFT."""
    H, W = img.shape
    cc = sfft.irfft2(tmpl_f * np.conj(sfft.rfft2(img)), s=img.shape)
    rows = np.r_[0:MAXSHIFT + 1, H - MAXSHIFT:H]
    band = cc[rows]
    iy, ix = np.unravel_index(np.argmax(band), band.shape)
    dy = rows[iy] if rows[iy] <= H // 2 else rows[iy] - H
    dx = ix if ix <= W // 2 else ix - W
    return dy, dx


def shift(img, dy, dx):
    return np.roll(np.roll(img, dy, axis=0), dx, axis=1)


def iou(a, b):
    a, b = a > 0.5, b > 0.5
    return np.count_nonzero(a & b) / max(1, np.count_nonzero(a | b))


def build(members):
    # drop instances whose vertical position disagrees with the majority
    # (a wrong baseline on a display-math line)
    tops = np.array([m["bbox"][1] - m["baseline_ref"] for m in members])
    med = np.median(tops)
    members = [m for m, t in zip(members, tops) if abs(t - med) <= 6] or members
    geo = canvas_geometry(members)
    imgs = [p for p in (place(m, geo) for m in members) if p is not None]
    if not imgs:
        return None
    imgs.sort(key=lambda a: a.sum())
    t_f = sfft.rfft2(imgs[len(imgs) // 2])          # median-ink instance
    acc = np.zeros_like(imgs[0])
    for im in imgs:
        acc += shift(im, *align(im, t_f))
    tmpl = acc / len(imgs)
    t_f = sfft.rfft2(tmpl)
    acc, kept, aligned = np.zeros_like(tmpl), 0, []
    for im in imgs:
        s = shift(im, *align(im, t_f))
        if iou(s, tmpl) < 0.70:
            continue
        acc += s
        kept += 1
        aligned.append(s)
    if kept == 0:
        return None
    mean = acc / kept
    # alternates: real single impressions, typical in shape (IoU >= 0.8 with
    # the mean) and spread from light to heavy inking
    cand = sorted((s for s in aligned if iou(s, mean) >= 0.80), key=lambda a: a.sum())
    alts = []
    if len(cand) >= 2 * NALT:
        alts = [cand[int(q * (len(cand) - 1))].astype(np.float16)
                for q in np.linspace(0.15, 0.85, NALT)]
    return mean, kept, geo[2], alts


def main():
    inst = pickle.load(open(os.path.join(WORK, "instances.pkl"), "rb"))
    clusters = {c["id"]: c for c in pickle.load(open(os.path.join(WORK, "clusters.pkl"), "rb"))}
    sorts = pickle.load(open(os.path.join(WORK, "sorts.pkl"), "rb"))
    masters = {}
    for key, cids in sorted(sorts.items(), key=lambda kv: str(kv[0])):
        members = [inst[i] for c in cids for i in clusters[c]["members"]]
        members = [m for m in members if m["baseline_ref"] is not None]
        r = build(members)
        if r is None:
            continue
        img, n, base, alts = r
        masters[key] = dict(img=img.astype(np.float32), base=base, n=n, alts=alts)
    pickle.dump(masters, open(os.path.join(WORK, "masters.pkl"), "wb"))
    print(f"{len(masters)} masters")
    sheet(masters)


def sheet(masters, cols=14, cell=150):
    """All masters at the same scale, baseline drawn in grey."""
    keys = sorted(masters, key=lambda k: (str(k[2]), k[1], k[0]))
    rows = (len(keys) + cols - 1) // cols
    S = Image.new("L", (cols * cell, rows * cell), 255)
    d = ImageDraw.Draw(S)
    above, below, width = 380, 140, 520
    for j, k in enumerate(keys):
        m = masters[k]
        ys, xs = np.nonzero(m["img"] > 0.5)
        if len(ys) == 0:
            continue
        B = m["base"]
        win = np.zeros((above + below, width))
        y0 = max(0, B - above)
        src = m["img"][y0:B + below, max(0, xs.min() - 20):xs.min() + width - 20]
        oy = above - (B - y0)
        win[oy:oy + src.shape[0], :src.shape[1]] = src
        im = Image.fromarray((255 - 255 * np.clip(win, 0, 1)).astype(np.uint8))
        im = im.resize(((cell - 20) * width // (above + below), cell - 20))
        x, y = (j % cols) * cell, (j // cols) * cell
        S.paste(im, (x + 2, y + 2))
        by = y + 2 + (cell - 20) * above // (above + below)
        d.line([x, by, x + cell, by], fill=190)
        d.text((x + 3, y + cell - 16), f"{k[0]} {k[1]}{k[2]} n{m['n']}", fill=0)
        d.rectangle([x, y, x + cell - 1, y + cell - 1], outline=200)
    S.save(os.path.join(WORK, "masters.png"))


if __name__ == "__main__":
    main()

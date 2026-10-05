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
import json
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
NALT = 8                          # alternates (single impressions) per frequent sort;
                                  # half as many for sorts with 8-15 clean impressions
MAXN = 400                        # impressions averaged per sort, spread over all pages


def canvas_geometry(members):
    tops = [m["bbox"][1] - m["baseline_ref"] for m in members]
    bots = [m["bbox"][3] - m["baseline_ref"] for m in members]
    wid = max(m["bbox"][2] - m["bbox"][0] for m in members)
    z = UP * max(DOCSCALE.values(), default=1.0)      # room for rescaled impressions
    base = int(-min(tops) * z) + MARGIN
    h = sfft.next_fast_len(base + int(max(bots) * z) + MARGIN)
    w = sfft.next_fast_len(int(wid * z) + 2 * MARGIN)
    return h, w, base


def _docweight():
    p = os.path.join(WORK, "docweight.json")
    return json.load(open(p)) if os.path.exists(p) else {}


DOCWEIGHT = _docweight()           # extra ink per edge (scan px) of each scan, see docweight.py
DOCSCALE = (json.load(open(os.path.join(WORK, "docscale.json")))
            if os.path.exists(os.path.join(WORK, "docscale.json")) else {})


def disk(r):
    y, x = np.mgrid[-r:r + 1, -r:r + 1]
    return x * x + y * y <= r * r + r


def place(inst, geo):
    H, W, base = geo
    bm = inst["bitmap"].astype(float)
    doc = inst["page"].rsplit("-", 1)[0]
    sc = DOCSCALE.get(doc, 1.0)            # the Transactions type is ~4% smaller
    z = UP * sc
    up = ndimage.zoom(np.pad(bm, 1), z, order=1)
    p = int(round(z))
    up = up[p:-p, p:-p]
    # bring a heavier or lighter scan to the reference weight
    r = int(round(DOCWEIGHT.get(doc, 0.0) * UP))
    k = max(0, -r)                    # growth beyond the bitmap's box
    if r > 0:
        up = ndimage.grey_erosion(up, footprint=disk(r))
    elif r < 0:
        up = ndimage.grey_dilation(np.pad(up, k), footprint=disk(k))
    can = np.zeros((H, W))
    y = base + int(round((inst["bbox"][1] - inst["baseline_ref"]) * z)) - k
    h, w = up.shape
    if y < 0 or y + h > H or MARGIN - k + w > W:
        return None
    can[y:y + h, MARGIN - k:MARGIN - k + w] = up
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


def stroke(bm):
    """Stroke width of a 1-bit glyph: twice a high percentile of the
    distance to the nearest paper pixel."""
    edt = ndimage.distance_transform_edt(np.pad(bm, 1))
    return 2 * np.percentile(edt[edt > 0], 95)


def build(members, drop_bold=False, bold_out=None):
    # drop instances whose vertical position disagrees with the majority
    # (a wrong baseline on a display-math line)
    tops = np.array([m["bbox"][1] - m["baseline_ref"] for m in members])
    med = np.median(tops)
    members = [m for m, t in zip(members, tops) if abs(t - med) <= 6] or members
    if drop_bold and len(members) >= 4:
        # bold title capitals have the cap height of the 11pt text and so
        # land in the same sort; their strokes are ~25% heavier, while ink
        # varies by ~10%
        w = np.array([stroke(m["bitmap"]) for m in members])
        light = np.percentile(w, 25)
        if bold_out is not None:
            bold_out.extend(m for m, x in zip(members, w) if x > 1.18 * light)
        members = [m for m, x in zip(members, w) if x <= 1.18 * light] or members
    if len(members) > MAXN:
        members = sorted(members, key=lambda m: (m["page"], m["bbox"][1], m["bbox"][0]))
        members = [members[int(k)] for k in np.linspace(0, len(members) - 1, MAXN)]
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
    k = NALT if len(cand) >= 2 * NALT else NALT // 2 if len(cand) >= NALT else 0
    alts = [cand[int(q * (len(cand) - 1))].astype(np.float16)
            for q in np.linspace(0.1, 0.9, k)] if k else []
    return mean, kept, geo[2], alts


def main():
    inst = pickle.load(open(os.path.join(WORK, "instances.pkl"), "rb"))
    clusters = {c["id"]: c for c in pickle.load(open(os.path.join(WORK, "clusters.pkl"), "rb"))}
    sorts = pickle.load(open(os.path.join(WORK, "sorts.pkl"), "rb"))
    masters = {}
    bold = {}                  # bold title capitals found inside roman sorts
    members_of = {}
    for key, cids in sorted(sorts.items(), key=lambda kv: str(kv[0])):
        members = [inst[i] for c in cids for i in clusters[c]["members"]]
        members_of.setdefault(key, [])
        for m in members:
            if m["baseline_ref"] is None:
                continue
            # an impression OCR confidently read as another letter goes to
            # that letter's sort (bold E and F can share a cluster)
            ch = m["ch"]
            # (only into a sort that exists on its own: across many pages
            # the misreads alone would otherwise make sorts of their own)
            if (ch and len(ch) == 1 and ch.isascii() and ch.isalpha()
                    and len(key[0]) == 1 and key[0].isascii() and key[0].isalpha()
                    and ch != key[0] and m["conf"] > 90 and ch.isupper() == key[0].isupper()
                    and (ch,) + key[1:] in sorts):
                members_of.setdefault((ch,) + key[1:], []).append(m)
            else:
                members_of[key].append(m)
    for key, members in members_of.items():
        if not members:
            continue
        out = [] if key[1] == "R" and key[2] == 11 and key[0].isupper() else None
        r = build(members, drop_bold=key[1] == "R" and key[0].isupper(), bold_out=out)
        if out:
            bold.setdefault(key[0], []).extend(out)
        if r is None:
            continue
        img, n, base, alts = r
        masters[key] = dict(img=img.astype(np.float32), base=base, n=n, alts=alts)
    # bold sorts: the title-capital clusters plus the bold impressions
    # separated from the roman capitals
    for g, extra in bold.items():
        key = (g, "B", "T")
        members = members_of.get(key, []) + extra
        if len(members) < 2:
            continue
        r = build(members)
        if r is not None:
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
        x0 = max(0, xs.min() - 20)
        for r in range(above + below):       # canvas row for window row r
            cr = B - above + r
            if 0 <= cr < m["img"].shape[0]:
                src = m["img"][cr, x0:x0 + width]
                win[r, :src.shape[0]] = src
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

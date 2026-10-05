"""Group glyph instances into clusters of identical sorts.

Instances are compared as baseline-aligned bitmaps: an instance joins a
cluster when, at the best shift of up to +-SHIFT px, the intersection over
union with the cluster's running mean shape exceeds THRESH.  OCR labels are
only used to keep the search small: confident instances are first compared
with clusters of the same OCR label, everything else with all clusters of
similar size.  Roman, italic, bold and script-size versions of a letter end
up in different clusters because their shapes differ.

Output: work/clusters.pkl and work/clusters/NNNN.png (mean shape per cluster),
work/overview-*.png contact sheets for labelling.
"""
import os
import pickle
from collections import Counter

import numpy as np
from PIL import Image, ImageDraw
from scipy import signal

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, "work")
SHIFT = 2
THRESH = 0.72
PAD = SHIFT + 1


class Cluster:
    def __init__(self, inst):
        self.top = inst["top"]          # y of bitmap top relative to baseline
        bm = inst["bitmap"]
        self.h, self.w = bm.shape
        self.sum = np.zeros((self.h + 2 * PAD, self.w + 2 * PAD), float)
        self.sum[PAD:PAD + self.h, PAD:PAD + self.w] = bm
        self.n = 1
        self.members = [inst["id"]]
        self.labels = Counter([inst["ch"]])
        self._proto = None

    def proto(self):
        return self.sum / self.n > 0.5

    def match(self, inst):
        """Best IoU over shifts; returns (iou, dy, dx) placing inst in self.sum."""
        bm = inst["bitmap"]
        h, w = bm.shape
        if abs(h - self.h) > 2 * SHIFT + 2 or abs(w - self.w) > 2 * SHIFT + 2:
            return 0.0, 0, 0
        if abs(inst["top"] - self.top) > 2 * SHIFT + 2:
            return 0.0, 0, 0
        if self._proto is None:
            self._proto = self.proto()
            self._np = np.count_nonzero(self._proto)
        P = self._proto
        H, W = P.shape
        base_dy = PAD + (inst["top"] - self.top)
        dys = [dy for dy in range(base_dy - SHIFT, base_dy + SHIFT + 1) if 0 <= dy and dy + h <= H]
        x0 = PAD - SHIFT - (w - self.w) // 2
        dxs = [dx for dx in range(x0, x0 + 2 * SHIFT + 1) if 0 <= dx and dx + w <= W]
        if not dys or not dxs:
            return 0.0, 0, 0
        # intersections at all shifts at once
        sub = P[dys[0]:dys[-1] + h, dxs[0]:dxs[-1] + w].astype(np.float32)
        inter = np.rint(signal.correlate(sub, bm.astype(np.float32), mode="valid"))
        iou = inter / (self._np + np.count_nonzero(bm) - inter)
        iy, ix = np.unravel_index(np.argmax(iou), iou.shape)
        return float(iou[iy, ix]), dys[iy], dxs[ix]

    def add(self, inst, dy, dx):
        bm = inst["bitmap"]
        h, w = bm.shape
        self.sum[dy:dy + h, dx:dx + w] += bm
        self.n += 1
        self.members.append(inst["id"])
        self.labels[inst["ch"]] += 1
        # the prototype settles quickly; refresh it while the cluster is
        # small and then every 5%
        if self.n < 64 or self.n % max(1, self.n // 20) == 0:
            self._proto = None


def main():
    inst = pickle.load(open(os.path.join(WORK, "instances.pkl"), "rb"))
    usable = []
    for i, g in enumerate(inst):
        g["id"] = i
        if g["baseline"] is None:
            continue
        g["top"] = int(round(g["bbox"][1] - g["baseline"]))
        usable.append(g)
    # Big, frequent, confident glyphs first, so prototypes start clean.
    usable.sort(key=lambda g: (-(g["conf"] > 90), -g["bitmap"].sum()))

    clusters = []
    by_label = {}
    grid = {}            # (h, w, top) // 7 -> clusters; match() needs all within 6 px

    def key(g):
        h, w = g["bitmap"].shape
        return h // 7, w // 7, g["top"] // 7

    def near(g):
        a, b, c = key(g)
        for i in (a - 1, a, a + 1):
            for j in (b - 1, b, b + 1):
                for k in (c - 1, c, c + 1):
                    yield from grid.get((i, j, k), ())

    for n, g in enumerate(usable):
        if n % 20000 == 0:
            print(f"  {n}/{len(usable)}: {len(clusters)} clusters", flush=True)
        cands = by_label.get((g["ch"], key(g)[2]), []) if g["conf"] > 90 else []
        best = (THRESH, None, 0, 0)
        for c in cands:
            iou, dy, dx = c.match(g)
            if iou > best[0]:
                best = (iou, c, dy, dx)
        if best[1] is None:
            for c in near(g):
                iou, dy, dx = c.match(g)
                if iou > best[0]:
                    best = (iou, c, dy, dx)
        if best[1] is None:
            c = Cluster(g)
            clusters.append(c)
            by_label.setdefault((g["ch"], key(g)[2]), []).append(c)
            grid.setdefault(key(g), []).append(c)
        else:
            best[1].add(g, best[2], best[3])

    clusters.sort(key=lambda c: -c.n)
    os.makedirs(os.path.join(WORK, "clusters"), exist_ok=True)
    out = []
    for k, c in enumerate(clusters):
        mean = c.sum / c.n
        Image.fromarray((255 - 255 * mean).astype(np.uint8)).save(
            os.path.join(WORK, "clusters", f"{k:04d}.png"))
        out.append(dict(id=k, n=c.n, top=c.top - PAD, mean=mean,
                        members=c.members, ocr=c.labels.most_common(3)))
    pickle.dump(out, open(os.path.join(WORK, "clusters.pkl"), "wb"))
    print(f"{len(clusters)} clusters; "
          f"{sum(c.n >= 3 for c in clusters)} with >=3 members covering "
          f"{sum(c.n for c in clusters if c.n >= 3)} of {len(usable)} instances")
    contact_sheets(out)


def contact_sheets(cl, min_n=2, per_sheet=96, cols=12, cell=110):
    cl = [c for c in cl if c["n"] >= min_n]
    for s in range(0, len(cl), per_sheet):
        chunk = cl[s:s + per_sheet]
        rows = (len(chunk) + cols - 1) // cols
        sheet = Image.new("L", (cols * cell, rows * cell), 255)
        d = ImageDraw.Draw(sheet)
        for j, c in enumerate(chunk):
            im = Image.fromarray((255 - 255 * c["mean"]).astype(np.uint8))
            im.thumbnail((cell - 8, cell - 30))
            x, y = (j % cols) * cell, (j // cols) * cell
            sheet.paste(im, (x + 4, y + 4))
            lab = c["ocr"][0][0] if c["ocr"] else "?"
            d.text((x + 4, y + cell - 22), f"#{c['id']} n={c['n']} {lab!r}", fill=0)
            d.rectangle([x, y, x + cell - 1, y + cell - 1], outline=200)
        sheet.save(os.path.join(WORK, f"overview-{s // per_sheet:02d}.png"))


if __name__ == "__main__":
    main()

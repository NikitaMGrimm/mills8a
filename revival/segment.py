"""Cut every glyph out of the 600 dpi specimen scans.

For each page: OCR with Tesseract (hOCR with character boxes) to get text
lines, their baselines and a first guess at each character; then take the
connected components of the bitmap and attach each to the OCR character box
it overlaps most.  Components belonging to the same box (the dot of an i,
the bars of =) become one glyph instance.  Components no box claims (most
math symbols) are kept, unlabelled, on the nearest line.

Output: work/instances.pkl, a list of dicts, one per glyph instance.
"""
import glob
import html
import os
import pickle
import re
import subprocess
import sys

import numpy as np
from PIL import Image
from scipy import ndimage

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, "work")


def page_images():
    os.makedirs(os.path.join(WORK, "pages"), exist_ok=True)
    for pdf in sorted(glob.glob(os.path.join(HERE, "scans", "*.pdf"))):
        stem = os.path.splitext(os.path.basename(pdf))[0]
        prefix = os.path.join(WORK, "pages", stem)
        if not glob.glob(prefix + "-*.png"):
            subprocess.run(["pdfimages", "-png", pdf, prefix], check=True)
    return sorted(glob.glob(os.path.join(WORK, "pages", "*.png")))


def ocr(png):
    base = png[:-4]
    if not os.path.exists(base + ".hocr"):
        subprocess.run(["tesseract", png, base, "--dpi", "600",
                        "-c", "hocr_char_boxes=1", "hocr"],
                       check=True, capture_output=True)
    text = open(base + ".hocr", encoding="utf-8").read()
    lines, chars = [], []
    # Lines and the characters inside them, in document order.
    for m in re.finditer(r"class='(ocr_line|ocr_caption|ocr_textfloat|ocr_header)'"
                         r"[^>]*title=\"([^\"]*)\"|"
                         r"class='ocrx_cinfo' title='x_bboxes (\d+) (\d+) (\d+) (\d+);"
                         r" x_conf ([\d.]+)'>([^<]*)<", text):
        if m.group(1):
            t = m.group(2)
            x0, y0, x1, y1 = map(int, re.search(r"bbox (\d+) (\d+) (\d+) (\d+)", t).groups())
            bl = re.search(r"baseline ([-\d.]+) ([-\d.]+)", t)
            slope, off = map(float, bl.groups()) if bl else (0.0, 0.0)
            xs = re.search(r"x_size ([\d.]+)", t)
            lines.append(dict(bbox=(x0, y0, x1, y1), slope=slope, off=off,
                              x_size=float(xs.group(1)) if xs else None))
        else:
            x0, y0, x1, y1 = map(int, m.group(3, 4, 5, 6))
            chars.append(dict(bbox=(x0, y0, x1 + 1, y1 + 1), conf=float(m.group(7)),
                              ch=html.unescape(m.group(8)), line=len(lines) - 1))
    return lines, chars


def baseline_y(line, x):
    x0, y0, x1, y1 = line["bbox"]
    return y1 + line["off"] + line["slope"] * (x - x0)


def segment_page(png):
    ink = ~np.array(Image.open(png)).astype(bool)
    lines, chars = ocr(png)
    lab, n = ndimage.label(ink, structure=np.ones((3, 3)))
    slices = ndimage.find_objects(lab)

    # Character-box ownership map: pixel -> index of OCR char box.
    owner = np.full(ink.shape, -1, dtype=np.int32)
    for i, c in enumerate(chars):
        x0, y0, x1, y1 = c["bbox"]
        owner[y0:y1, x0:x1] = i

    groups = {}      # char index -> list of component labels
    orphans = []
    for k, sl in enumerate(slices, start=1):
        if sl is None:
            continue
        comp = lab[sl] == k
        area = int(comp.sum())
        if area < 6:                      # specks of dust
            continue
        h, w = comp.shape
        if h > 400 or w > 800:            # rules, page furniture
            continue
        own = owner[sl][comp]
        own = own[own >= 0]
        if own.size and np.bincount(own).max() > 0.5 * area:
            groups.setdefault(int(np.bincount(own).argmax()), []).append((k, sl))
        else:
            orphans.append([(k, sl)])

    out = []

    def emit(parts, ch, conf, line_idx):
        y0 = min(sl[0].start for _, sl in parts)
        y1 = max(sl[0].stop for _, sl in parts)
        x0 = min(sl[1].start for _, sl in parts)
        x1 = max(sl[1].stop for _, sl in parts)
        bm = np.zeros((y1 - y0, x1 - x0), bool)
        for k, sl in parts:
            sub = lab[sl] == k
            bm[sl[0].start - y0:sl[0].stop - y0, sl[1].start - x0:sl[1].stop - x0] |= sub
        if line_idx is None or line_idx < 0:
            # nearest line whose band contains the glyph's vertical centre
            cy, cx = (y0 + y1) / 2, (x0 + x1) / 2
            best = None
            for li, L in enumerate(lines):
                lx0, ly0, lx1, ly1 = L["bbox"]
                if lx0 - 50 <= cx <= lx1 + 50:
                    d = 0 if ly0 <= cy <= ly1 else min(abs(cy - ly0), abs(cy - ly1))
                    if best is None or d < best[0]:
                        best = (d, li)
            if best is None or best[0] > 60:
                line_idx = -1
            else:
                line_idx = best[1]
        base = baseline_y(lines[line_idx], (x0 + x1) / 2) if line_idx >= 0 else None
        out.append(dict(page=os.path.basename(png)[:-4], bbox=(x0, y0, x1, y1),
                        bitmap=bm, ch=ch, conf=conf, line=line_idx, baseline=base,
                        x_size=lines[line_idx]["x_size"] if line_idx >= 0 else None))

    for ci, parts in groups.items():
        c = chars[ci]
        emit(parts, c["ch"], c["conf"], c["line"])
    for parts in orphans:
        emit(parts, None, 0.0, None)
    return out


def main():
    pages = page_images()
    allinst = []
    for p in pages:
        inst = segment_page(p)
        print(f"{os.path.basename(p)}: {len(inst)} glyphs, "
              f"{sum(i['ch'] is None for i in inst)} unlabelled", file=sys.stderr)
        allinst += inst
    with open(os.path.join(WORK, "instances.pkl"), "wb") as f:
        pickle.dump(allinst, f)
    print(f"total {len(allinst)}", file=sys.stderr)


if __name__ == "__main__":
    main()

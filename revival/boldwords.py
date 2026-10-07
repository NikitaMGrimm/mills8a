"""Which impressions are bold: work/boldwords.pkl, a set of instance ids.

Bold in the 1940s Bulletin is set by the word, never by the letter: the
title lines and the run-in heads ("Introduction.", "Proof.", the numbers of
the references).  Single impressions cannot be told apart by weight, since
a heavily inked roman capital is as heavy as a bold one (the bold I and B
were mostly roman capitals that way).  So each word is weighed: the median
stroke of its letters, against the page (title lines: the whole line at
least 1.3 x) or against its own line (a head: one of the first words of a
line, ending in a period, at least 1.2 x the line, with the words before it
that are as heavy).
"""
import os
import pickle
from collections import defaultdict
from multiprocessing import get_context

import numpy as np

import masters as ms

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, "work")
WORD_GAP = 14            # px: letters closer than this belong to one word
_inst = None


def _stroke(i):
    b = _inst[i]["bitmap"]
    return ms.stroke(b > 0) if b.sum() > 30 else np.nan


def main():
    global _inst
    _inst = inst = pickle.load(open(os.path.join(WORK, "instances.pkl"), "rb"))
    idx = [i for i, g in enumerate(inst) if g["line"] >= 0]
    with get_context("fork").Pool(os.cpu_count()) as pool:
        s = pool.map(_stroke, idx, chunksize=2000)
    stroke = np.full(len(inst), np.nan)
    stroke[idx] = s
    lines, page_ref = defaultdict(list), defaultdict(list)
    for i in idx:
        lines[(inst[i]["page"], inst[i]["line"])].append(i)
        if inst[i]["ch"] and inst[i]["ch"].isalpha() and not np.isnan(stroke[i]):
            page_ref[inst[i]["page"]].append(stroke[i])
    page_ref = {p: np.median(v) for p, v in page_ref.items()}
    bold, n_title, n_head = set(), 0, 0
    for (page, _), ids in lines.items():
        ids.sort(key=lambda i: inst[i]["bbox"][0])
        words = [[ids[0]]]
        for a, b in zip(ids, ids[1:]):
            if inst[b]["bbox"][0] - inst[a]["bbox"][2] > WORD_GAP:
                words.append([])
            words[-1].append(b)
        sc = []
        for w in words:
            v = [stroke[i] for i in w if not np.isnan(stroke[i])
                 and inst[i]["ch"] and inst[i]["ch"].isalnum()]
            sc.append(np.median(v) / page_ref[page] if len(v) >= 2 and page in page_ref
                      else np.nan)
        v = [x for x in sc if not np.isnan(x)]
        if not v:
            continue
        med = np.median(v)
        if med > 1.3 and len(v) >= 2:                      # a title line
            for w in words:
                bold.update(w)
                n_title += len(w)
            continue
        if len(v) < 3:
            continue
        for k, w in enumerate(words[:4]):                  # a run-in head
            if inst[w[-1]]["ch"] == "." and not np.isnan(sc[k]) and sc[k] / med >= 1.2:
                j = k
                while j >= 0 and not np.isnan(sc[j]) and sc[j] / med >= 1.2:
                    bold.update(words[j])
                    n_head += len(words[j])
                    j -= 1
                break
    pickle.dump(bold, open(os.path.join(WORK, "boldwords.pkl"), "wb"))
    print(f"bold: {n_title} impressions in title lines, {n_head} in run-in heads")


if __name__ == "__main__":
    main()

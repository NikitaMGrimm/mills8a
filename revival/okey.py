"""Print the overrides.tsv key (page@x0,y0 of the founding impression) of
cluster ids: python3 okey.py 26 221 ..."""
import os
import pickle
import sys

WORK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "work")
inst = pickle.load(open(os.path.join(WORK, "instances.pkl"), "rb"))
cl = {c["id"]: c for c in pickle.load(open(os.path.join(WORK, "clusters.pkl"), "rb"))}
for a in sys.argv[1:]:
    g = inst[cl[int(a)]["members"][0]]
    print(f"{g['page']}@{g['bbox'][0]},{g['bbox'][1]}")

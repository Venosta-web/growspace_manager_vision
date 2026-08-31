"""PROTOTYPE — check the claimed segmentation against exposure-invariant structure."""
import datetime as dt
import numpy as np
from PIL import Image
import vision_lib as V
from segments import SEGMENTS, label

rows = V.corpus()
sig = []
for _, p in rows:
    a = np.asarray(Image.open(p).convert("L").resize((32, 24), Image.BICUBIC), float).ravel()
    sig.append((a - a.mean()) / (a.std() + 1e-6))
sig = np.array(sig)
dates = [d for d, _ in rows]
z = np.load("embeddings.npz")
X = z["full168"]

print(f"{'segment':<18} {'n':>3} {'adj struct corr':>18} {'adj emb dist':>14}")
for nm, a, b in SEGMENTS:
    idx = [i for i, d in enumerate(dates) if a <= d <= b]
    sc = [np.corrcoef(sig[i], sig[i + 1])[0, 1] for i in idx[:-1]]
    ed = [float(V.cosdist(X[i], X[i + 1])) for i in idx[:-1]]
    if sc:
        print(f"{nm:<18} {len(idx):>3}   med {np.median(sc):>5.3f} min {np.min(sc):>5.3f}"
              f"   med {np.median(ed):>5.3f} max {np.max(ed):>5.3f}")
    else:
        print(f"{nm:<18} {len(idx):>3}")

print("\n-- transitions across each claimed boundary --")
for k in range(len(SEGMENTS) - 1):
    b = SEGMENTS[k][2]
    i = dates.index(b); j = i + 1
    if (dates[j] - dates[i]).days == 1:
        print(f"  {dates[i]} -> {dates[j]}  {SEGMENTS[k][0]:<18} -> {SEGMENTS[k+1][0]:<18} "
              f"struct {np.corrcoef(sig[i], sig[j])[0,1]:+.3f}  emb {float(V.cosdist(X[i], X[j])):.3f}")

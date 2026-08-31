"""PROTOTYPE — is the top adjacent-day outlier geometry (plants moved) or appearance?"""
import datetime as dt
import numpy as np
from PIL import Image
import vision_lib as V

rows = V.corpus()
dates = [d for d, _ in rows]
sig = []
for _, p in rows:
    a = np.asarray(Image.open(p).convert("L").resize((32, 24), Image.BICUBIC), float).ravel()
    sig.append((a - a.mean()) / (a.std() + 1e-6))
sig = np.array(sig)
idx = {d: i for i, d in enumerate(dates)}
print("-- standardised 32x24 structural correlation (exposure-invariant) --")
adj = [np.corrcoef(sig[i], sig[i + 1])[0, 1] for i in range(len(dates) - 1)
       if (dates[i + 1] - dates[i]).days == 1]
print(f"  median adjacent-day corr over whole corpus: {np.median(adj):.3f}")
for a, b in [("2026-05-15", "2026-05-16"), ("2026-06-20", "2026-06-21"),
             ("2026-04-26", "2026-04-27"), ("2026-05-16", "2026-05-17")]:
    i, j = idx[dt.date.fromisoformat(a)], idx[dt.date.fromisoformat(b)]
    print(f"  {a} -> {b}: struct corr {np.corrcoef(sig[i], sig[j])[0,1]:.3f}")

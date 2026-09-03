"""Camera-move detection: where does the structural signature actually separate?

#62 measured 0.352 (camera moved) against 0.874 (plants gone) on the 32x24 standardised
signature. This asks the operational question instead: comparing each frame with the
history a Vision Checkup would actually hold, does a threshold exist that fires on the
four known repositionings and not on occlusion, harvest, or ordinary growth?
"""
import numpy as np
import gate_lib as G

rows = G.build()
sig = {r["date"]: r["sig"] for r in rows}


def c(a, b):
    return G.corr(sig[a], sig[b])


print("adjacent-day structural correlation (each frame vs the previous frame)")
prev = None
flagged = []
for r in rows:
    if prev is not None:
        v = c(prev["date"], r["date"])
        mark = "  <-- REFRAME" if r["d"] in G.REFRAME_DAYS else ""
        if v < 0.75 or mark:
            flagged.append((r["date"], r["segment"], v, mark))
    prev = r
for date, seg, v, mark in flagged:
    print(f"  {date}  {seg:18} corr={v:.3f}{mark}")

print("\nby segment: adjacent-day correlation")
prev = None
bysec = {}
for r in rows:
    if prev is not None:
        bysec.setdefault(r["segment"], []).append(c(prev["date"], r["date"]))
    prev = r
for nm, _, _ in G.SEGMENTS:
    v = bysec.get(nm)
    if v:
        print(f"  {nm:18} n={len(v):>2}  min {min(v):.3f}  median {np.median(v):.3f}  max {max(v):.3f}")

print("\nvs a 30-frame trailing MEDIAN signature (what a bucket would hold)")
hist = []
out = {}
for r in rows:
    if len(hist) >= 10:
        ref = np.median(np.array(hist[-30:]), axis=0)
        ref = (ref - ref.mean()) / (ref.std() + 1e-6)
        out.setdefault(r["segment"], []).append((r["date"], G.corr(ref, r["sig"])))
    if r["mean_luminance"] >= 40:
        hist.append(r["sig"])
for nm, _, _ in G.SEGMENTS:
    v = out.get(nm)
    if v:
        vals = [x[1] for x in v]
        lo = min(v, key=lambda x: x[1])
        print(f"  {nm:18} n={len(v):>2}  min {min(vals):.3f} ({lo[0]})  median {np.median(vals):.3f}  max {max(vals):.3f}")

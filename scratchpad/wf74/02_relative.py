"""History-relative behaviour of the two candidate gate signals.

The gate cannot be absolute (79% of healthy frames are >5% blown), so every candidate
rule here is a ratio to the trailing median of the camera's own accepted history.
Robust z-scores are deliberately NOT used: see the MAD column.
"""
import numpy as np
import gate_lib as G

rows = G.build()
names = open("detail_names.txt").read().split("\n")
dv = np.load("detail.npy")
for r, v in zip(rows, dv):
    r.update(dict(zip(names, v)))

WINDOW, WARMUP = 30, 10


def trailing(stat, accept_fn):
    """Ratio of each frame's stat to the trailing median of ACCEPTED frames."""
    hist, out = [], []
    for r in rows:
        if len(hist) < WARMUP:
            out.append((r, None, None))
        else:
            h = np.array(hist[-WINDOW:])
            med = float(np.median(h))
            mad = float(np.median(np.abs(h - med))) * 1.4826
            out.append((r, r[stat] / max(med, 1e-6), mad / max(med, 1e-6)))
        if accept_fn(r):
            hist.append(r[stat])
    return out


# Accept everything except the frames a lights-off floor would obviously stop.
lit = lambda r: r["mean_luminance"] >= 40

for stat in ("mean_luminance", "grad_full (contract)"):
    print(f"\n=== {stat}: ratio to trailing median of last {WINDOW} accepted ===")
    res = trailing(stat, lit)
    bysec = {}
    for r, ratio, relmad in res:
        if ratio is not None:
            bysec.setdefault(r["segment"], []).append((r["date"], ratio, relmad))
    for nm, _, _ in G.SEGMENTS:
        v = bysec.get(nm)
        if not v:
            continue
        ratios = [x[1] for x in v]
        lo = min(v, key=lambda x: x[1])
        hi = max(v, key=lambda x: x[1])
        print(
            f"  {nm:18} n={len(v):>2}  ratio {min(ratios):.2f}-{max(ratios):.2f}"
            f"  (min {lo[0]}, max {hi[0]})  rel-MAD median {np.median([x[2] for x in v]):.3f}"
        )

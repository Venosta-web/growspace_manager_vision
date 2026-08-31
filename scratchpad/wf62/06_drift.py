"""PROTOTYPE — growth drift inside a genuinely fixed-camera bucket, and what it does
to a fixed baseline. The corpus-wide PCA in 02 was contaminated by four camera reframes
that were not known at the time; this restricts to framing-4."""
import datetime as dt
import numpy as np
from scipy import stats as st
import vision_lib as V
import score_lib as S
from segments import label

z = np.load("embeddings.npz")
dates = [dt.date.fromisoformat(s) for s in z["dates"]]
X = z["full168"]
Sst = {k: z["stats"][:, i] for i, k in enumerate(z["stat_keys"])}
stable = [i for i, d in enumerate(dates) if label(d) == "framing-4 STABLE"]
Xs = X[stable]
day = np.array([(dates[i] - dates[stable[0]]).days for i in stable], float)

print("== PCA inside framing-4 only (fixed camera, 35 frames, no known problem) ==")
mu = Xs.mean(0)
U, sv, Vt = np.linalg.svd(Xs - mu, full_matrices=False)
ev = sv ** 2 / (sv ** 2).sum()
Pc = U * sv
print(f"explained variance PC1..PC5: {' '.join(f'{e:.3f}' for e in ev[:5])}")
drivers = {"day_of_run": day, **{k: Sst[k][stable] for k in ("mean_lum", "blown", "detail", "gr", "gb")}}
print(f"{'PC':>4} {'var%':>6} " + "".join(f"{k:>12}" for k in drivers))
for i in range(4):
    print(f"{'PC'+str(i+1):>4} {ev[i]*100:>6.1f} " +
          "".join(f"{st.spearmanr(Pc[:, i], v).statistic:>12.2f}" for v in drivers.values()))

print("\n== drift: distance from a FIXED baseline as the run proceeds ==")
W = 14
Bfix = Xs[:W]
loo_fix = S.loo_scores(Bfix)
print(f"fixed baseline = first {W} frames ({dates[stable[0]]}..{dates[stable[W-1]]})")
print(f"{'method':>14} {'tau':>8} " + "".join(f"{f'+{a}-{b}d':>12}" for a, b in
      [(0, 4), (5, 9), (10, 14), (15, 20)]))
for m in loo_fix:
    tau = loo_fix[m].mean() + 3 * loo_fix[m].std(ddof=1)
    line = f"{m:>14} {tau:>8.3f} "
    for a, b in [(0, 4), (5, 9), (10, 14), (15, 20)]:
        sel = [j for j in range(W, len(stable)) if a <= j - W <= b]
        v = np.array([float(S.score_all(Bfix, Xs[j])[m]) for j in sel])
        line += f"{np.median(v):>8.3f}({100*(v>tau).mean():>2.0f})"
    print(line)

print("\n== same frames, ROLLING baseline of the preceding 14 ==")
print(f"{'method':>14} " + "".join(f"{f'+{a}-{b}d':>12}" for a, b in
      [(0, 4), (5, 9), (10, 14), (15, 20)]))
roll = {}
for j in range(W, len(stable)):
    Br = Xs[j - W:j]
    lr = S.loo_scores(Br)
    for m, v in S.score_all(Br, Xs[j]).items():
        roll.setdefault(m, []).append((float(v), lr[m].mean() + 3 * lr[m].std(ddof=1)))
for m, pairs in roll.items():
    line = f"{m:>14} "
    for a, b in [(0, 4), (5, 9), (10, 14), (15, 20)]:
        sel = [pairs[k] for k in range(len(pairs)) if a <= k <= b]
        v = np.array([p[0] for p in sel]); t = np.array([p[1] for p in sel])
        line += f"{np.median(v):>8.3f}({100*(v>t).mean():>2.0f})"
    print(line)
print("\n(median score, and % over that baseline's own 3-sigma gate, in parentheses)")

print("\n== how long is a fixed baseline good for? cross-bucket sanity ==")
c = Bfix.mean(0); c /= np.linalg.norm(c)
for lab in ("framing-1 veg", "framing-3", "framing-4 STABLE", "post-harvest"):
    idx = [i for i, d in enumerate(dates) if label(d) == lab]
    d = V.cosdist(X[idx], c)
    print(f"  {lab:<18} median centroid-cos {np.median(d):.3f}")

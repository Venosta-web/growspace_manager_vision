"""PROTOTYPE — issue #62 main experiment.

Baseline bucket: the one stretch in the corpus with a genuinely fixed camera and no
known problem -- framing-4, 2026-05-17..2026-06-20, 35 frames.
  B = first 30 (05-17..06-15)   H = untouched holdout, last 5 (06-16..06-20)
"""
import datetime as dt
import numpy as np
from PIL import Image
import vision_lib as V
import score_lib as S
import perturb as P
from segments import label

z = np.load("embeddings.npz")
dates = [dt.date.fromisoformat(s) for s in z["dates"]]
X = z["full168"]
rows = V.corpus()
stable = [i for i, d in enumerate(dates) if label(d) == "framing-4 STABLE"]
B_idx, H_idx = stable[:30], stable[30:]
B = X[B_idx]
print(f"baseline n={len(B_idx)} {dates[B_idx[0]]}..{dates[B_idx[-1]]}   "
      f"holdout n={len(H_idx)} {dates[H_idx[0]]}..{dates[H_idx[-1]]}")

loo = S.loo_scores(B)
METHODS = list(loo)
tau = {m: loo[m].mean() + 3 * loo[m].std(ddof=1) for m in METHODS}
print("\n-- baseline leave-one-out (the noise floor) and the 3-sigma gate --")
print(f"{'method':>14} {'mean':>9} {'sd':>9} {'max':>9} {'tau(3sd)':>10}")
for m in METHODS:
    print(f"{m:>14} {loo[m].mean():>9.4f} {loo[m].std(ddof=1):>9.4f} "
          f"{loo[m].max():>9.4f} {tau[m]:>10.4f}")

print("\n-- untouched holdout (5 healthy frames, never seen by the baseline) --")
print(f"{'method':>14} " + " ".join(f"{dates[i].strftime('%m-%d'):>8}" for i in H_idx)
      + f" {'>tau':>6}")
H = X[H_idx]
hs = {}
for m in METHODS:
    v = np.array([float(S.score_all(B, H[j])[m]) for j in range(len(H_idx))])
    hs[m] = v
    print(f"{m:>14} " + " ".join(f"{x:>8.4f}" for x in v) + f" {int((v>tau[m]).sum()):>6}")

# ---- sensitivity: perturb every stable frame, LOO for baseline members ----
print("\n-- sensitivity: score rise, in baseline-sigma units, at the 3-sigma gate --")
print("   (35 stable frames perturbed; baseline members scored leave-one-out)")
imgs = {i: Image.open(rows[i][1]) for i in stable}


def score_frame(i, img):
    Bi = np.delete(X[B_idx], B_idx.index(i), axis=0) if i in B_idx else B
    return S.score_all(Bi, V.encode(img, "full168"))


base_clean = {m: [] for m in METHODS}
for i in stable:
    r = score_frame(i, imgs[i])
    for m in METHODS:
        base_clean[m].append(float(r[m]))
base_clean = {m: np.array(v) for m, v in base_clean.items()}

results = {}
for kind, table in (("PLANT", P.PLANT), ("CAMERA", P.CAMERA)):
    for nm, fn in table.items():
        acc = {m: [] for m in METHODS}
        for i in stable:
            r = score_frame(i, fn(imgs[i]))
            for m in METHODS:
                acc[m].append(float(r[m]))
        results[(kind, nm)] = {m: np.array(v) for m, v in acc.items()}
        print(".", end="", flush=True)
print()

hdr = f"{'':>6} {'perturbation':<22}"
for m in METHODS:
    hdr += f"{m[:12]:>26}"
print("\n" + hdr)
print(f"{'':>6} {'':<22}" + "".join(f"{'z(sd)':>10}{'fire%':>8}{'AUC':>8}" for _ in METHODS))
for (kind, nm), res in results.items():
    line = f"{kind[:6]:>6} {nm:<22}"
    for m in METHODS:
        v = res[m]
        z_ = (v.mean() - base_clean[m].mean()) / loo[m].std(ddof=1)
        fire = 100.0 * (v > tau[m]).mean()
        auc = (v[:, None] > base_clean[m][None, :]).mean() + \
              0.5 * (v[:, None] == base_clean[m][None, :]).mean()
        line += f"{z_:>10.1f}{fire:>8.0f}{auc:>8.2f}"
    print(line)

# ---- what the same gate does to the real events in the corpus ----
print("\n-- the same fixed baseline + gate, applied to every frame in the corpus --")
print(f"{'segment':<18} {'n':>3} " + "".join(f"{m[:12]+' fire%':>20}" for m in METHODS))
from segments import SEGMENTS
for segnm, a, b in SEGMENTS:
    idx = [i for i, d in enumerate(dates) if a <= d <= b]
    line = f"{segnm:<18} {len(idx):>3} "
    for m in METHODS:
        v = np.array([float(S.score_all(B, X[i])[m]) for i in idx])
        line += f"{np.median(v):>12.3f}{100*(v>tau[m]).mean():>8.0f}"
    print(line)
np.savez("scores.npz", **{f"{k[0]}|{k[1]}|{m}": v for k, r in results.items() for m, v in r.items()},
         **{f"BASE|clean|{m}": v for m, v in base_clean.items()},
         **{f"LOO|loo|{m}": v for m, v in loo.items()})

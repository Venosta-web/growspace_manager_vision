"""PROTOTYPE — issue #68, step 2. THE DECISIVE TEST.

Same protocol as wf62/04_score.py, same perturbation ladder, same 35 framing-4 frames --
only the statistic changes, from a 384-d embedding distance to a one-number classical CV
proxy. Baseline = framing-4 first 30; perturbations applied to all 35; baseline members
scored leave-one-out.

For each proxy the question is NOT "does it move when the symptom is applied" -- a
green-fraction obviously moves when you yellow the pixels. It is the asymmetry question
wf62 posed and the embedding failed:

    does the proxy respond to the symptom it CLAIMS MORE than it responds to a camera
    artifact the tent actually produces?

`targeted separation AUC` is that number: claimed-symptom scores vs every camera-shaped
score. 0.5 is a coin flip. Below ~0.8 the proxy cannot carry a symptom name.
"""

import os
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.join(HERE, "..", "wf62"))
import proxy_lib as P  # noqa: E402
from perturb import CAMERA, PLANT  # noqa: E402
from segments import STABLE  # noqa: E402

_, A, B = STABLE
frames = [(d, p) for d, p in P.corpus() if A <= d <= B]
print(f"framing-4: {len(frames)} frames  baseline=first 30  holdout=last 5\n")

imgs = [Image.open(p).convert("RGB") for _, p in frames]

clean = {nm: [] for nm in P.NAMES}
for im in imgs:
    pr = P.proxies(im)
    for nm in P.NAMES:
        clean[nm].append(pr[nm])
clean = {nm: np.array(v, dtype=float) for nm, v in clean.items()}

N_BASE = 30


def loo_scores(vals):
    """|z| of every frame against the 30-frame baseline, leave-one-out for members."""
    out = np.empty(len(vals))
    for i in range(len(vals)):
        idx = [j for j in range(N_BASE) if j != i]
        b = vals[idx]
        b = b[np.isfinite(b)]
        mu, sd = b.mean(), b.std(ddof=1)
        out[i] = abs(vals[i] - mu) / max(sd, 1e-12)
    return out


base_scores = {nm: loo_scores(clean[nm]) for nm in P.NAMES}

# One pass over the perturbation ladder, caching every proxy at once.
LADDER = [("PLANT", k, v) for k, v in PLANT.items()] + [
    ("CAMERA", k, v) for k, v in CAMERA.items()
]

pert_vals = {}
for kind, name, fn in LADDER:
    vals = {nm: [] for nm in P.NAMES}
    for im in imgs:
        pr = P.proxies(fn(im))
        for nm in P.NAMES:
            vals[nm].append(pr[nm])
    pert_vals[name] = {nm: np.array(v, dtype=float) for nm, v in vals.items()}
    print(f"  applied {kind:<7}{name}")

scores = {}
for kind, name, _ in LADDER:
    scores[name] = {}
    for nm in P.NAMES:
        vals = pert_vals[name][nm]
        out = np.empty(len(vals))
        for i in range(len(vals)):
            idx = [j for j in range(N_BASE) if j != i]
            b = clean[nm][idx]
            b = b[np.isfinite(b)]
            mu, sd = b.mean(), b.std(ddof=1)
            out[i] = abs(vals[i] - mu) / max(sd, 1e-12)
        scores[name][nm] = out

# ------------------------------------------------------------------ per-perturbation
print("\n\n=== AUC of each proxy vs the unperturbed frames ===")
print("(how strongly the proxy reacts; a CAMERA row that is high is a confound)\n")
hdr = f"{'':<7}{'perturbation':<26}"
for nm in P.NAMES:
    hdr += f"{nm[:11]:>13}"
print(hdr)
for kind, name, _ in LADDER:
    line = f"{kind:<7}{name:<26}"
    for nm in P.NAMES:
        line += f"{P.auc(scores[name][nm], base_scores[nm]):>13.2f}"
    print(line)

# --------------------------------------------------------------- targeted separation
print("\n\n=== THE ASYMMETRY TEST ===")
print("targeted sep AUC = P(the claimed symptom scores above a camera artifact)\n")
cam_names = list(CAMERA)
print(
    f"{'proxy':<19}{'claims':<26}{'sym':>6}{'cam':>6}{'pooled':>8}{'worst-case sep':>16}"
)
print(f"{'':<19}{'':<26}{'AUC':>6}{'AUC':>6}{'sep':>8}{'(vs worst cam)':>16}\n")
rank = []
for nm in P.NAMES:
    claim, keys = P.CLAIMS[nm]
    sym = [n for n in PLANT if any(k in n for k in keys)]
    sym_auc = {n: P.auc(scores[n][nm], base_scores[nm]) for n in sym}
    cam_auc = {n: P.auc(scores[n][nm], base_scores[nm]) for n in cam_names}
    best_s = max(sym_auc, key=lambda k: sym_auc[k])
    worst_c = max(cam_auc, key=lambda k: cam_auc[k])
    pooled = P.auc(
        np.concatenate([scores[n][nm] for n in sym]),
        np.concatenate([scores[n][nm] for n in cam_names]),
    )
    # The number that decides whether the field may carry a symptom name: can the
    # best-detected severity of the claimed symptom be told apart from the single
    # camera artifact this proxy reacts to most?
    worst = P.auc(scores[best_s][nm], scores[worst_c][nm])
    rank.append(
        (worst, nm, claim, best_s, sym_auc[best_s], worst_c, cam_auc[worst_c], pooled)
    )
    print(
        f"{nm:<19}{claim:<26}{sym_auc[best_s]:>6.2f}{cam_auc[worst_c]:>6.2f}"
        f"{pooled:>8.2f}{worst:>16.2f}"
    )
    print(f"{'':<19}{'best: ' + best_s[:19]:<26}{'':>6}{'worst: ' + worst_c[:11]:>24}")

print("\n\n=== Ranked by worst-case separation ===")
print("0.50 = the proxy cannot tell its own symptom from a camera artifact.\n")
for worst, nm, claim, bs, sa, wc, ca, pooled in sorted(rank, reverse=True):
    verdict = (
        "synthetic pass"
        if worst >= 0.90
        else "synthetic marginal"
        if worst >= 0.75
        else "synthetic fail"
    )
    print(f"{worst:>6.2f}  {nm:<19}{claim:<28}{verdict}")
    print(f"{'':>6}  {'':<19}{bs} {sa:.2f}  vs  {wc} {ca:.2f}")

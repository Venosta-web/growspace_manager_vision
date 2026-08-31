"""PROTOTYPE — issue #68, step 3. Does the one surviving proxy survive for a REASON?

`blue_ratio` (mean B / mean G over vegetation) came out of 02 with worst-case separation
0.98 against white balance. Before that can be believed, two objections have to be
answered, because both would make it an artifact of how the ladder was built:

1. **Is it separating by mechanism, or only by magnitude?** wf62's synthetic chlorosis
   multiplies B by (1 - 0.55s); at s=0.6 that is a 33% drop, while the strongest camera
   white balance in the ladder drops B by 13%. If the proxy is simply seeing the bigger
   number, its margin evaporates at the severity where the two coincide -- and the plant
   magnitudes are the ONE side of the ladder calibrated against nothing, since the corpus
   holds zero health positives. So: sweep severity and find the crossover.

2. **The camera side of the ladder is photometric plus a 4% nudge. The corpus contains
   four REAL repositions and two occlusions.** Those are the only real camera-shaped
   ground truth in existence here. A proxy that beats synthetic white balance but is
   swamped by a real reframe is not a symptom output.
"""

import os
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.join(HERE, "..", "wf62"))
import proxy_lib as P  # noqa: E402
from perturb import chlorosis_global, sensor_noise, white_balance  # noqa: E402
from segments import STABLE, label  # noqa: E402

FOCUS = ["blue_ratio", "blue_ratio_ref", "necrosis_frac_ref", "coverage_hsv"]

_, A, B = STABLE
frames = [(d, p) for d, p in P.corpus() if A <= d <= B]
imgs = [Image.open(p).convert("RGB") for _, p in frames]
N_BASE = 30

clean = {nm: [] for nm in P.NAMES}
for im in imgs:
    pr = P.proxies(im)
    for nm in P.NAMES:
        clean[nm].append(pr[nm])
clean = {nm: np.array(v, dtype=float) for nm, v in clean.items()}


def zs(fn):
    """|z| of every framing-4 frame under perturbation `fn`, leave-one-out baseline."""
    vals = {nm: [] for nm in FOCUS}
    for im in imgs:
        pr = P.proxies(fn(im))
        for nm in FOCUS:
            vals[nm].append(pr[nm])
    out = {}
    for nm in FOCUS:
        v = np.array(vals[nm], dtype=float)
        o = np.empty(len(v))
        for i in range(len(v)):
            b = clean[nm][[j for j in range(N_BASE) if j != i]]
            b = b[np.isfinite(b)]
            o[i] = abs(v[i] - b.mean()) / max(b.std(ddof=1), 1e-12)
        out[nm] = o
    return out


base = zs(lambda im: im)

print("=== 1. Severity sweep: where does the margin go? ===")
print("chlorosis_global at rising strength vs the camera white balances of the ladder.")
print("`sep` = worst-case separation against white-bal warm 15% (B x0.87).\n")
print(f"{'perturbation':<28}{'B multiplier':>14}", end="")
for nm in FOCUS:
    print(f"{nm[:12]:>15}", end="")
print()

wb15 = zs(lambda im: white_balance(im, 1.15, 0.87))
rows = []
for s in [0.05, 0.10, 0.15, 0.20, 0.30, 0.45, 0.60]:
    z = zs(lambda im, s=s: chlorosis_global(im, s))
    line = f"{'chlorosis-global s=' + format(s, '.2f'):<28}{1 - 0.55 * s:>14.2f}"
    for nm in FOCUS:
        line += f"{np.median(z[nm]):>7.1f}/{P.auc(z[nm], wb15[nm]):>6.2f}"
    rows.append((s, {nm: z[nm] for nm in FOCUS}))
    print(line)

print(f"\n{'-- camera, for comparison --':<28}")
for nm_, kr, kb in [
    ("white-bal warm 8%", 1.08, 0.93),
    ("white-bal warm 15%", 1.15, 0.87),
]:
    z = zs(lambda im, kr=kr, kb=kb: white_balance(im, kr, kb))
    line = f"{nm_:<28}{kb:>14.2f}"
    for nm in FOCUS:
        line += f"{np.median(z[nm]):>7.1f}/{'':>6}"
    print(line)
z = zs(lambda im: sensor_noise(im, 8))
line = f"{'sensor noise sd8':<28}{'-':>14}"
for nm in FOCUS:
    line += f"{np.median(z[nm]):>7.1f}/{'':>6}"
print(line)
print("\n(cell = median |z| / AUC against white-bal warm 15%)")

print("\n\n=== 2. The real camera events the ladder does not contain ===")
print("median |z| against the same framing-4 baseline.\n")
rows_j = []
for date, path in P.corpus():
    with Image.open(path) as image:
        row = P.proxies(image)
    row["date"] = date.isoformat()
    row["segment"] = label(date)
    rows_j.append(row)
stable = [r for r in rows_j if r["segment"] == "framing-4 STABLE"]
print(f"{'segment':<22}{'n':>4}", end="")
for nm in FOCUS:
    print(f"{nm[:12]:>15}", end="")
print()
for seg in [
    "framing-1 veg",
    "occlusion-1",
    "framing-2",
    "framing-3",
    "occlusion-2",
    "reframe day",
    "framing-4 STABLE",
    "post-harvest",
]:
    sel = [r for r in rows_j if r["segment"] == seg]
    if not sel:
        continue
    line = f"{seg:<22}{len(sel):>4}"
    for nm in FOCUS:
        b = np.array([r[nm] for r in stable], dtype=float)
        b = b[np.isfinite(b)]
        v = np.array([r[nm] for r in sel], dtype=float)
        zz = np.abs((v - b.mean()) / b.std(ddof=1))
        zz = zz[np.isfinite(zz)]
        line += f"{np.median(zz):>15.1f}" if zz.size else f"{'-':>15}"
    print(line)

print("\n\n=== 3. Verdict for the chlorosis candidates ===")
print("A symptom name is only defensible if the symptom outruns BOTH the synthetic")
print("camera ladder AND the real camera events above. Necrosis is not included in")
print("this chlorosis severity sweep; step 2 already shows its noise confound.\n")
real_max = {}
for nm in ["blue_ratio", "blue_ratio_ref", "coverage_hsv"]:
    b = np.array([r[nm] for r in stable], dtype=float)
    b = b[np.isfinite(b)]
    worst = 0.0
    for seg in ["occlusion-1", "framing-2", "framing-3", "occlusion-2", "reframe day"]:
        sel = [r for r in rows_j if r["segment"] == seg]
        v = np.array([r[nm] for r in sel], dtype=float)
        zz = np.abs((v - b.mean()) / b.std(ddof=1))
        zz = zz[np.isfinite(zz)]
        if zz.size:
            worst = max(worst, float(np.median(zz)))
    real_max[nm] = worst

for nm in real_max:
    print(f"{nm}:")
    print(f"   real camera events reach median |z| = {real_max[nm]:.1f}")
    for s, z in rows:
        med = float(np.median(z[nm]))
        if med >= real_max[nm]:
            print(
                f"   chlorosis must reach s >= {s:.2f} (B x{1 - 0.55 * s:.2f}, "
                f"|z|={med:.1f}) merely to MATCH a camera event"
            )
            break
    else:
        print("   NO simulated chlorosis severity, up to s=0.60, reaches that")
    print()

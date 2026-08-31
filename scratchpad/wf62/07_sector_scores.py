"""PROTOTYPE — per-sector scoring: does the SPREAD across sectors buy the asymmetry?"""
import numpy as np

z = np.load("sectors.npz")
stable = z["stable"]
conds = [k for k in z.files if k != "stable"]
CLEAN = z["clean"]                      # (35, 16, 384)
nB = 30
BASE = CLEAN[:nB]                       # baseline frames


def sector_stats(E, loo=False):
    """-> per-frame (max, median, spread) of per-sector centroid-cosine."""
    out = []
    for f in range(E.shape[0]):
        per = []
        for k in range(E.shape[1]):
            B = BASE[:, k]
            if loo and f < nB:
                B = np.delete(B, f, axis=0)
            c = B.mean(0); c /= np.linalg.norm(c)
            per.append(1.0 - float(E[f, k] @ c))
        per = np.array(per)
        out.append((per.max(), np.median(per), per.max() - np.median(per)))
    return np.array(out)


ref = sector_stats(CLEAN, loo=True)
STAT = {"max-sector": 0, "median-sector": 1, "spread(max-med)": 2}
tau = {nm: ref[:, i].mean() + 3 * ref[:, i].std(ddof=1) for nm, i in STAT.items()}

print("-- clean reference (35 stable frames, leave-one-out) --")
for nm, i in STAT.items():
    print(f"  {nm:>16}: mean {ref[:,i].mean():.4f} sd {ref[:,i].std(ddof=1):.4f} "
          f"tau {tau[nm]:.4f}")

res = {}
print(f"\n{'':>7}{'perturbation':<26}" + "".join(f"{nm:>30}" for nm in STAT))
print(f"{'':>7}{'':<26}" + "".join(f"{'z':>9}{'fire%':>8}{'AUC':>8}" + " " * 5 for _ in STAT))
for cond in sorted(conds):
    if cond == "clean":
        continue
    kind, nm_ = cond.split("|")
    s = sector_stats(z[cond], loo=True)
    res[cond] = s
    line = f"{kind[:6]:>7}{nm_:<26}"
    for nm, i in STAT.items():
        v, r = s[:, i], ref[:, i]
        auc = (v[:, None] > r[None, :]).mean()
        line += f"{(v.mean()-r.mean())/r.std(ddof=1):>9.1f}{100*(v>tau[nm]).mean():>8.0f}{auc:>8.2f}" + " " * 5
    print(line)

print("\n== the question that matters: does a statistic separate PLANT from CAMERA? ==")
print("   AUC of each statistic discriminating plant-perturbed from camera-perturbed frames")
print("   (0.50 = no separation; 1.00 = perfect. Whole-frame scoring managed ~0.50.)")
plant = [c for c in res if c.startswith("PLANT")]
cam = [c for c in res if c.startswith("CAMERA")]
for nm, i in STAT.items():
    pv = np.concatenate([res[c][:, i] for c in plant])
    cv = np.concatenate([res[c][:, i] for c in cam])
    print(f"  {nm:>16}: AUC {(pv[:,None] > cv[None,:]).mean():.3f}   "
          f"plant med {np.median(pv):.4f}  camera med {np.median(cv):.4f}")

print("\n-- per-perturbation medians of spread(max-med) --")
for c in sorted(res):
    print(f"  {c:<40} {np.median(res[c][:, 2]):.4f}")
print(f"  {'clean (leave-one-out)':<40} {np.median(ref[:, 2]):.4f}")

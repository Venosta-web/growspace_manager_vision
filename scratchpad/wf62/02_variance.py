"""PROTOTYPE — noise floor and what dominates embedding variance."""
import datetime as dt
import numpy as np
from scipy import stats as st
import vision_lib as V

z = np.load("embeddings.npz")
dates = [dt.date.fromisoformat(s) for s in z["dates"]]
day = np.array([(d - dates[0]).days for d in dates], float)
S = {k: z["stats"][:, i] for i, k in enumerate(z["stat_keys"])}

# --- frame classes, from the corpus facts recorded on issue #63 -------------
lights_off = S["dark"] > 0.90
occluded = np.array([dt.date(2026, 4, 13) <= d <= dt.date(2026, 4, 21) for d in dates])
usable = ~lights_off
clean = usable & ~occluded
print(f"frames={len(dates)}  lights_off={lights_off.sum()}  occluded={occluded.sum()}  "
      f"usable={usable.sum()}  clean={clean.sum()}")
print(f"clean range {min(np.array(dates)[clean])} .. {max(np.array(dates)[clean])}")

for geom in ("full168", "crop224"):
    X = z[geom]
    print(f"\n{'='*70}\n== {geom}\n{'='*70}")
    Xc, dc, dayc = X[clean], np.array(dates)[clean], day[clean]
    D = V.cosdist(Xc, Xc)
    iu = np.triu_indices(len(Xc), 1)
    gap = np.abs(dayc[:, None] - dayc[None, :])[iu]
    dist = D[iu]

    # --- 1. within-bucket spread as a function of day-gap ------------------
    print("\n-- distance vs day-gap (clean frames, same camera) --")
    print(f"{'gap (d)':>10} {'n':>5} {'median':>8} {'p95':>8} {'max':>8}")
    for lo, hi in [(1, 1), (2, 2), (3, 3), (4, 7), (8, 14), (15, 30), (31, 60), (61, 200)]:
        m = (gap >= lo) & (gap <= hi)
        if m.sum():
            v = dist[m]
            lab = f"{lo}" if lo == hi else f"{lo}-{hi}"
            print(f"{lab:>10} {m.sum():>5} {np.median(v):>8.4f} "
                  f"{np.percentile(v,95):>8.4f} {v.max():>8.4f}")

    # --- 2. what dominates variance ---------------------------------------
    mu = Xc.mean(0)
    Z = Xc - mu
    U, sv, Vt = np.linalg.svd(Z, full_matrices=False)
    ev = sv**2 / (sv**2).sum()
    P = U * sv  # scores
    print("\n-- PCA of clean-frame embeddings --")
    print(f"explained variance PC1..PC6: {' '.join(f'{e:.3f}' for e in ev[:6])} "
          f"(cum PC1-3 {ev[:3].sum():.3f})")
    drivers = {"day_of_run": dayc, **{k: S[k][clean] for k in ("mean_lum", "blown", "detail", "gr", "gb")}}
    print(f"{'PC':>4} {'var%':>6} " + "".join(f"{k:>12}" for k in drivers))
    for i in range(5):
        cells = "".join(f"{st.spearmanr(P[:, i], v).statistic:>12.2f}" for v in drivers.values())
        print(f"{'PC'+str(i+1):>4} {ev[i]*100:>6.1f} {cells}")

    # --- 3. does distance track time, or exposure? -------------------------
    dlum = np.abs(S["mean_lum"][clean][:, None] - S["mean_lum"][clean][None, :])[iu]
    dblown = np.abs(S["blown"][clean][:, None] - S["blown"][clean][None, :])[iu]
    print("\n-- pairwise distance vs candidate causes (Spearman) --")
    for nm, v in [("|day gap|", gap), ("|mean-lum diff|", dlum), ("|blown diff|", dblown)]:
        print(f"  {nm:>16}: rho={st.spearmanr(dist, v).statistic:+.3f}")
    # partial: distance ~ lum-difference, controlling for day gap
    def resid(a, b):
        r = st.rankdata(a); q = st.rankdata(b)
        return r - np.polyval(np.polyfit(q, r, 1), q)
    pr = st.pearsonr(resid(dist, gap), resid(dlum, gap)).statistic
    print(f"  partial rho(distance, |lum diff| | day gap) = {pr:+.3f}")
    pr2 = st.pearsonr(resid(dist, dlum), resid(gap, dlum)).statistic
    print(f"  partial rho(distance, |day gap| | lum diff) = {pr2:+.3f}")

    # --- 4. degraded frames: are they far? --------------------------------
    ref = Xc[-39:]                                    # longest clean stretch
    c = ref.mean(0); c /= np.linalg.norm(c)
    for nm, m in [("clean", clean), ("occluded", occluded), ("lights-off", lights_off)]:
        d = V.cosdist(X[m], c)
        print(f"  centroid-cos to late-clean centroid, {nm:>10}: "
              f"median {np.median(d):.4f} max {d.max():.4f}")

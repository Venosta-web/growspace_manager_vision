"""PROTOTYPE — what are the adjacent-day outliers that fatten the noise floor?"""
import datetime as dt
import numpy as np
import vision_lib as V

z = np.load("embeddings.npz")
dates = [dt.date.fromisoformat(s) for s in z["dates"]]
S = {k: z["stats"][:, i] for i, k in enumerate(z["stat_keys"])}
lights_off = S["dark"] > 0.90
occluded = np.array([dt.date(2026, 4, 13) <= d <= dt.date(2026, 4, 21) for d in dates])
clean = ~lights_off & ~occluded
X = z["full168"]

idx = np.where(clean)[0]
pairs = [(i, j) for a, i in enumerate(idx) for j in idx[a + 1:] if (dates[j] - dates[i]).days == 1]
d = [(float(V.cosdist(X[i], X[j])), i, j) for i, j in pairs]
d.sort(reverse=True)
print("-- 12 largest adjacent-day distances among 'clean' frames --")
print(f"{'dist':>7}  {'date pair':<25} {'lum':>14} {'blown':>13} {'detail':>13} {'dark':>13}")
for v, i, j in d[:12]:
    print(f"{v:>7.4f}  {dates[i]}->{dates[j]}  "
          f"{S['mean_lum'][i]:>6.0f}->{S['mean_lum'][j]:<6.0f} "
          f"{S['blown'][i]:>6.3f}->{S['blown'][j]:<6.3f} "
          f"{S['detail'][i]:>6.2f}->{S['detail'][j]:<6.2f} "
          f"{S['dark'][i]:>6.3f}->{S['dark'][j]:<6.3f}")
print("\n-- distribution of 'dark' fraction over clean frames --")
print(f"  min {S['dark'][clean].min():.3f} median {np.median(S['dark'][clean]):.3f} "
      f"p90 {np.percentile(S['dark'][clean],90):.3f} max {S['dark'][clean].max():.3f}")
print("  frames with dark>0.30:", [str(dates[i]) for i in np.where(clean & (S['dark'] > 0.30))[0]])
print("  frames with mean_lum<80:", [f"{dates[i]}({S['mean_lum'][i]:.0f})"
                                     for i in np.where(clean & (S['mean_lum'] < 80))[0]])
print("  frames with detail<6:", [f"{dates[i]}({S['detail'][i]:.1f})"
                                  for i in np.where(clean & (S['detail'] < 6))[0]])

"""PROTOTYPE — issue #68, step 1. Proxy values over the whole corpus.

Answers two things before any perturbation is applied:
  (a) what is each proxy's noise floor inside framing-4, the one genuinely fixed-camera
      bucket (wf62's corrected segmentation), and
  (b) how does each proxy move across the corpus's REAL events -- the harvest, the
      lights-off, the occlusions and the four camera repositions.

(b) matters because a proxy that cannot survive a camera move is not a symptom output,
whatever it is named.
"""

import os
import sys

import numpy as np
from PIL import Image

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "wf62"))
import proxy_lib as P  # noqa: E402
from segments import SEGMENTS, label  # noqa: E402

rows = []
for d, path in P.corpus():
    with Image.open(path) as im:
        pr = P.proxies(im)
    pr["date"] = d.isoformat()
    pr["segment"] = label(d)
    rows.append(pr)

print(
    f"{len(rows)} frames, wb reference usable on "
    f"{sum(r['_wb_ref_ok'] for r in rows):.0f}"
)

stable = [r for r in rows if r["segment"] == "framing-4 STABLE"]
print(f"\nframing-4 STABLE n={len(stable)}\n")

print("=== Noise floor inside the fixed-camera bucket ===")
print(f"{'proxy':<20}{'mean':>12}{'sd':>10}{'cv%':>8}   adjacent-day |delta| in sd")
base = {}
for nm in P.NAMES:
    v = np.array([r[nm] for r in stable], dtype=float)
    if not np.isfinite(v).all():
        print(f"{nm:<20}  <not computable on every frame>")
        continue
    mu, sd = v.mean(), v.std(ddof=1)
    base[nm] = (mu, sd)
    adj = np.abs(np.diff(v)) / sd
    print(
        f"{nm:<20}{mu:>12.4f}{sd:>10.4f}{100 * sd / abs(mu):>8.1f}"
        f"   med {np.median(adj):.2f}  max {adj.max():.2f}"
    )

print("\n=== Real events: |z| against the framing-4 baseline ===")
print("(z = (value - framing4 mean) / framing4 sd; a symptom output must not be")
print(" dominated by the camera events, which are the top rows here.)\n")
seg_order = [s[0] for s in SEGMENTS]
hdr = f"{'segment':<20}{'n':>4}"
for nm in P.NAMES:
    hdr += f"{nm[:11]:>13}"
print(hdr)
for sname in seg_order:
    sel = [r for r in rows if r["segment"] == sname]
    if not sel:
        continue
    line = f"{sname:<20}{len(sel):>4}"
    for nm in P.NAMES:
        if nm not in base:
            line += f"{'-':>13}"
            continue
        mu, sd = base[nm]
        v = np.array([r[nm] for r in sel], dtype=float)
        z = np.abs((v - mu) / sd)
        z = z[np.isfinite(z)]
        line += f"{np.median(z):>13.1f}" if z.size else f"{'-':>13}"
    print(line)

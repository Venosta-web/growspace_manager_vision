"""Which detail measure actually separates the two occlusion windows?

#63 reported a "detail proxy" collapsing to 3.7-5.5 against a median of 7.9, but that
proxy subsampled the luminance plane by 2 (wf62/vision_lib.frame_stats). The V1
contract specifies `mean_absolute_gradient` on the FULL-resolution plane. Those are not
the same statistic, and on a soft 800x600 sensor the difference is sensor noise.
"""
import numpy as np
from PIL import Image
import gate_lib as G

def variants(lum):
    out = {}
    def mag(y):
        return float(np.mean(np.abs(np.diff(y, axis=1))) + np.mean(np.abs(np.diff(y, axis=0)))) / 2
    out["grad_full (contract)"] = mag(lum)
    out["grad_stride2 (#63)"] = mag(lum[::2, ::2])
    out["grad_stride4"] = mag(lum[::4, ::4])
    h, w = lum.shape
    for f in (2, 4, 8):
        d = lum[: h // f * f, : w // f * f].reshape(h // f, f, w // f, f).mean(axis=(1, 3))
        out[f"grad_box{f}"] = mag(d)
    lap = (lum[:-2, 1:-1] + lum[2:, 1:-1] + lum[1:-1, :-2] + lum[1:-1, 2:] - 4 * lum[1:-1, 1:-1])
    out["laplacian_var_full"] = float(lap.var())
    d4 = lum[: h // 4 * 4, : w // 4 * 4].reshape(h // 4, 4, w // 4, 4).mean(axis=(1, 3))
    lap4 = (d4[:-2, 1:-1] + d4[2:, 1:-1] + d4[1:-1, :-2] + d4[1:-1, 2:] - 4 * d4[1:-1, 1:-1])
    out["laplacian_var_box4"] = float(lap4.var())
    out["grad_box4_norm"] = out["grad_box4"] / max(lum.mean(), 1e-6) * 100
    return out

rows = G.build()
for r in rows:
    r.update(variants(G.luminance(dict(G.corpus())[r["d"]])))

def auc(pos, neg):
    pos, neg = np.asarray(pos), np.asarray(neg)
    return float(np.mean([(p > neg).mean() + 0.5 * (p == neg).mean() for p in pos]))

occ = [r for r in rows if r["segment"] in G.OCCLUDED]
clean = [r for r in rows if r["segment"] not in G.UNUSABLE_SEGMENTS]
stable = [r for r in rows if r["segment"] == "framing-4 STABLE"]
names = [k for k in rows[0] if k.startswith(("grad", "lap"))]
print(f'{"measure":22} {"occl med":>9} {"clean med":>10} {"stable med":>11} {"AUC(low=occl)":>14} {"overlap":>28}')
for k in names:
    o = [r[k] for r in occ]; c = [r[k] for r in clean]; s = [r[k] for r in stable]
    a = 1 - auc(o, c)  # AUC that "lower value == occluded"
    ov = f"occl {min(o):.3g}-{max(o):.3g} | clean {min(c):.3g}-{max(c):.3g}"
    print(f"{k:22} {np.median(o):>9.3g} {np.median(c):>10.3g} {np.median(s):>11.3g} {a:>14.3f} {ov:>28}")
np.save("detail.npy", np.array([[r[k] for k in names] for r in rows]))
with open("detail_names.txt", "w") as fh:
    fh.write("\n".join(names))

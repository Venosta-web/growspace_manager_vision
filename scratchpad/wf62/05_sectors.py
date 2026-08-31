"""PROTOTYPE — does per-sector scoring buy the plant-vs-camera asymmetry?

Whole-frame scoring can't separate a localised symptom from a white-balance shift.
The hypothesis this tests: a camera-shaped change moves EVERY sector together, a
plant-shaped one moves one or two. So the discriminating statistic is the spread
across sectors, not the distance itself.

4x4 grid, the same sectors GrowspaceImageProcessor already draws (A1..D4).
"""
import datetime as dt
import numpy as np
from PIL import Image
import vision_lib as V
import perturb as P
from segments import label

GRID = 4
CELL = (154, 112)  # 11x8 patches of 14px


def sector_embeddings(img):
    """-> (16, 384) L2-normalised, one per sector, in a single batched ORT call."""
    im = img.convert("RGB")
    w, h = im.size
    batch = []
    for r in range(GRID):
        for c in range(GRID):
            crop = im.crop((c * w // GRID, r * h // GRID,
                            (c + 1) * w // GRID, (r + 1) * h // GRID)).resize(CELL, Image.BICUBIC)
            a = (np.asarray(crop, np.float32) / 255.0 - V.IMAGENET_MEAN) / V.IMAGENET_STD
            batch.append(a.transpose(2, 0, 1))
    out = V.session().run(None, {"pixel_values": np.stack(batch)})[0][:, 0].astype(np.float64)
    return out / np.linalg.norm(out, axis=1, keepdims=True)


CONDS = [("clean", lambda im: im)] + \
    [("PLANT|" + k, P.PLANT[k]) for k in ("chlorosis-patch moderate", "chlorosis-patch severe",
                                          "chlorosis-global moderate", "necrosis moderate", "droop 70px")] + \
    [("CAMERA|" + k, P.CAMERA[k]) for k in ("brightness +30%", "white-bal warm 15%",
                                            "white-bal cool 8%", "sensor noise sd8", "pose jitter 4%")]

z = np.load("embeddings.npz")
dates = [dt.date.fromisoformat(s) for s in z["dates"]]
rows = V.corpus()
stable = [i for i, d in enumerate(dates) if label(d) == "framing-4 STABLE"]
B_idx = stable[:30]

import time
t0 = time.time()
E = {}
for nm, fn in CONDS:
    E[nm] = np.array([sector_embeddings(fn(Image.open(rows[i][1]))) for i in stable])
    print(f"  {nm:<32} {time.time()-t0:>6.1f}s", flush=True)
np.savez("sectors.npz", **E, stable=np.array(stable))
print("saved sectors.npz")

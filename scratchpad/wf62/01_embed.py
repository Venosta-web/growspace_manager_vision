"""PROTOTYPE — embed the whole corpus under both geometries, with per-frame stats."""
import time
import numpy as np
from PIL import Image
import vision_lib as V

rows = V.corpus()
print(f"{len(rows)} frames, {rows[0][0]} .. {rows[-1][0]}")
E = {g: [] for g in ("full168", "crop224")}
stats, dates = [], []
t0 = time.time()
for i, (d, p) in enumerate(rows):
    img = Image.open(p)
    for g in E:
        E[g].append(V.encode(img, g))
    stats.append(V.frame_stats(img))
    dates.append(d.isoformat())
    if i % 25 == 0:
        print(f"  {i}/{len(rows)} {time.time()-t0:.1f}s", flush=True)
keys = sorted(stats[0])
np.savez(
    "embeddings.npz",
    dates=np.array(dates),
    full168=np.array(E["full168"]),
    crop224=np.array(E["crop224"]),
    stat_keys=np.array(keys),
    stats=np.array([[s[k] for k in keys] for s in stats]),
)
print(f"done in {time.time()-t0:.1f}s -> embeddings.npz")

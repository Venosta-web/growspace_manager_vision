"""PROTOTYPE — throwaway. Issue #74: what does a frame quality gate have to measure?

Every statistic here is the one the V1 contract already names in `QualitySignals`,
computed exactly as the contract's prose specifies, plus the 32x24 standardised
structural signature #62 found separates "camera moved" from "plants gone".

Nothing here needs the encoder: the whole point of the gate is that it costs no model.
"""

import datetime as dt
import json
import os
import re

import numpy as np
from PIL import Image

CORPUS = os.environ.get(
    "GROWSPACE_VISION_CORPUS", "/home/maxi/Pictures/growspace manager vision"
)
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "signals.json")
DATE_RE = re.compile(r"growcam_sog_(\d{2})\.(\d{2})\.(\d{4})\.jpg")

D = dt.date.fromisoformat

# The corrected segmentation from #62 (scratchpad/wf62/segments.py), which is the
# ground truth this ticket is measured against.
SEGMENTS = [
    ("framing-1 veg", D("2026-03-21"), D("2026-04-12")),
    ("occlusion-1", D("2026-04-13"), D("2026-04-21")),
    ("framing-2", D("2026-04-22"), D("2026-04-26")),
    ("framing-3", D("2026-04-27"), D("2026-05-03")),
    ("occlusion-2", D("2026-05-04"), D("2026-05-15")),
    ("reframe day", D("2026-05-16"), D("2026-05-16")),
    ("framing-4 STABLE", D("2026-05-17"), D("2026-06-20")),
    ("post-harvest", D("2026-06-21"), D("2026-06-24")),
    ("lights-off", D("2026-06-25"), D("2026-07-07")),
]
# Days on which the framing visibly changed (first frame of a new framing).
REFRAME_DAYS = {D("2026-04-22"), D("2026-04-27"), D("2026-05-16"), D("2026-05-17")}
OCCLUDED = {"occlusion-1", "occlusion-2"}
UNUSABLE_SEGMENTS = OCCLUDED | {"lights-off"}


def label(d):
    for nm, a, b in SEGMENTS:
        if a <= d <= b:
            return nm
    return "?"


def corpus():
    rows = []
    for name in os.listdir(CORPUS):
        m = DATE_RE.fullmatch(name)
        if m:
            dd, mo, y = (int(x) for x in m.groups())
            rows.append((dt.date(y, mo, dd), os.path.join(CORPUS, name)))
    return sorted(rows)


def luminance(path):
    a = np.asarray(Image.open(path).convert("RGB"), dtype=np.float32)
    return 0.299 * a[..., 0] + 0.587 * a[..., 1] + 0.114 * a[..., 2]


def signals(lum):
    """The three V1 QualitySignals, computed as the contract's prose specifies."""
    return {
        # "Mean 8-bit BT.601 luminance over all decoded pixels."
        "mean_luminance": float(lum.mean()),
        # "Fraction of decoded pixels whose luminance is strictly greater than 245."
        "clipped_pixel_fraction": float((lum > 245).mean()),
        # "(mean(abs(diff(Y, x))) + mean(abs(diff(Y, y)))) / 2"
        "mean_absolute_gradient": float(
            np.mean(np.abs(np.diff(lum, axis=1))) + np.mean(np.abs(np.diff(lum, axis=0)))
        )
        / 2.0,
    }


def signature(lum):
    """#62's exposure-invariant framing signature: 32x24 block means, standardised.

    Standardising kills gain and exposure, so only geometry survives. Returned flat.
    """
    h, w = lum.shape
    bh, bw = h // 24, w // 32
    blocks = lum[: bh * 24, : bw * 32].reshape(24, bh, 32, bw).mean(axis=(1, 3))
    v = blocks.ravel()
    return (v - v.mean()) / (v.std() + 1e-6)


def build(force=False):
    if os.path.exists(CACHE) and not force:
        with open(CACHE) as fh:
            raw = json.load(fh)
    else:
        raw = []
        for d, path in corpus():
            lum = luminance(path)
            row = {"date": d.isoformat(), **signals(lum)}
            row["dark_fraction"] = float((lum < 16).mean())
            row["sig"] = [round(float(x), 5) for x in signature(lum)]
            raw.append(row)
        with open(CACHE, "w") as fh:
            json.dump(raw, fh)
    for r in raw:
        r["d"] = D(r["date"])
        r["segment"] = label(r["d"])
        r["sig"] = np.asarray(r["sig"], dtype=np.float64)
    return raw


def corr(a, b):
    """Structural correlation between two standardised signatures."""
    return float(np.dot(a, b) / len(a))

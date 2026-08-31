"""PROTOTYPE — throwaway. Issue #68: do classical CV proxies carry symptom signal?

Companion to scratchpad/wf62/, which measured the DINOv2 embedding. Nothing here needs
an encoder: every proxy is a deterministic arithmetic statistic over pixels, which is
exactly what makes them candidates for an honest V1 output.

The corpus tent is lit by magenta LED (see wf62/perturb.py): mylar and walls are
pink/white, plants are the only green-dominant surface. That asymmetry is what makes a
wall-referenced white-balance correction possible at all.
"""

import datetime as dt
import os
import re

import numpy as np

CORPUS = os.environ.get(
    "GROWSPACE_VISION_CORPUS", "/home/maxi/Pictures/growspace manager vision"
)
DATE_RE = re.compile(r"growcam_sog_(\d{2})\.(\d{2})\.(\d{4})\.jpg")


def corpus():
    """-> [(date, path)] sorted by date."""
    rows = []
    for name in os.listdir(CORPUS):
        m = DATE_RE.fullmatch(name)
        if m:
            d, mo, y = (int(x) for x in m.groups())
            rows.append((dt.date(y, mo, d), os.path.join(CORPUS, name)))
    return sorted(rows)


def rgbf(img):
    return np.asarray(img.convert("RGB"), dtype=np.float32)


# ---------------------------------------------------------------- HSV (OpenCV scale)


def hsv_ocv(a):
    """a: float RGB 0-255 -> H 0-179, S 0-255, V 0-255.

    Ported from custom_components/growspace_manager/image_processor.py so that
    `coverage_hsv` below is the production statistic, not a lookalike.
    """
    r, g, b = a[..., 0] / 255.0, a[..., 1] / 255.0, a[..., 2] / 255.0
    cmax = np.maximum(np.maximum(r, g), b)
    cmin = np.minimum(np.minimum(r, g), b)
    delta = cmax - cmin
    h = np.zeros_like(r)
    nz = delta > 1e-7
    rm, gm, bm = (cmax == r) & nz, (cmax == g) & nz, (cmax == b) & nz
    h[rm] = ((g[rm] - b[rm]) / delta[rm]) % 6.0
    h[gm] = (b[gm] - r[gm]) / delta[gm] + 2.0
    h[bm] = (r[bm] - g[bm]) / delta[bm] + 4.0
    saturation = np.zeros_like(cmax)
    np.divide(delta, cmax, out=saturation, where=cmax > 1e-7)
    return (
        np.clip(h * 30.0, 0, 179),
        saturation * 255.0,
        cmax * 255.0,
    )


# ---------------------------------------------------------------------------- masks


def veg_mask(a):
    """Vegetation = green beats blue.

    Deliberately NOT green-dominance (G > max(R,B)): chlorosis pushes a leaf toward
    yellow, where R ~= G, so a dominance mask would delete the very pixels whose colour
    shift is being measured. Under magenta LED the walls are blue-dominant, so `G > B`
    keeps yellowing leaves and still excludes the tent.
    """
    return (a[..., 1] > a[..., 2] + 6.0) & (a[..., 2] < 250.0)


def wall_mask(a):
    """Non-vegetation reference: magenta/pink mylar, neither blown nor black.

    This is the white-balance reference. A plant symptom does not recolour the tent
    wall; a camera white-balance shift recolours everything. That is the whole basis of
    the `_ref` proxies below.
    """
    lum = 0.299 * a[..., 0] + 0.587 * a[..., 1] + 0.114 * a[..., 2]
    return (a[..., 2] > a[..., 1] + 6.0) & (lum > 25.0) & (lum < 240.0)


def wb_normalise(a):
    """Force the wall region grey by scaling R and B. Returns the corrected frame.

    If the reference region is too small to trust, returns the frame unchanged and
    flags it, so a proxy built on it cannot silently degrade into its raw twin.
    """
    w = wall_mask(a)
    if w.sum() < 2000:
        return a, False
    mr, mg, mb = a[..., 0][w].mean(), a[..., 1][w].mean(), a[..., 2][w].mean()
    out = a.copy()
    out[..., 0] = a[..., 0] * (mg / max(mr, 1e-6))
    out[..., 2] = a[..., 2] * (mg / max(mb, 1e-6))
    return out, True


# --------------------------------------------------------------------------- proxies


def canopy_region(a):
    """Everything that is not tent wall, and is neither crushed nor blown.

    Necrosis CANNOT be measured inside `veg_mask`: brown tissue is red-dominant, so it
    leaves that mask exactly when the symptom appears. Measuring it over a
    symptom-agnostic region is the only way the statistic can rise at all.
    """
    lum = 0.299 * a[..., 0] + 0.587 * a[..., 1] + 0.114 * a[..., 2]
    return ~wall_mask(a) & (lum > 25.0) & (lum < 245.0)


def _colour_proxies(a, tag, vmask, cmask):
    """Colour statistics over masks fixed by the RAW frame.

    The masks are passed in rather than recomputed because white-balance correction
    rescales B, which moves the `G > B` boundary and would silently swap the pixel
    population being measured -- comparing two different samples instead of one sample
    under two corrections.
    """
    out = {}
    if vmask.sum() < 500 or cmask.sum() < 500:
        return {
            f"chlorosis_rg{tag}": np.nan,
            f"blue_ratio{tag}": np.nan,
            f"necrosis_frac{tag}": np.nan,
        }
    r, g, b = a[..., 0][vmask].mean(), a[..., 1][vmask].mean(), a[..., 2][vmask].mean()
    # Yellowing raises R toward G and drops B.
    out[f"chlorosis_rg{tag}"] = float(r / max(g, 1e-6))
    out[f"blue_ratio{tag}"] = float(b / max(g, 1e-6))
    # Brown/necrotic tissue: orange-brown hue, saturated, mid-dark, within the canopy.
    h, s, val = hsv_ocv(a)
    brown = (h >= 8) & (h <= 25) & (s >= 60) & (val >= 30) & (val <= 210)
    out[f"necrosis_frac{tag}"] = float((brown & cmask).sum() / max(cmask.sum(), 1))
    return out


def proxies(img):
    """Every candidate V1 proxy for one frame."""
    a = rgbf(img)
    out = {}

    # 1. The production statistic, unchanged: image_processor.py canopy coverage.
    h, s, val = hsv_ocv(a)
    out["coverage_hsv"] = float(
        (((h >= 35) & (h <= 85) & (s >= 40) & (val >= 40)).mean()) * 100.0
    )

    # 2. Vegetation extent under the mask this file defends above.
    v = veg_mask(a)
    out["veg_frac"] = float(v.mean())

    # 3-5. Colour proxies, raw. Masks fixed here and reused for the corrected frame.
    cr = canopy_region(a)
    out.update(_colour_proxies(a, "", v, cr))

    # 3-5 again, after wall-referenced white balance, over the SAME pixels.
    corrected, ok = wb_normalise(a)
    out.update(_colour_proxies(corrected, "_ref", v, cr))
    out["_wb_ref_ok"] = float(ok)

    # 6-7. Geometry: where the canopy sits vertically.
    hgt = a.shape[0]
    ys, _ = np.nonzero(v)
    if ys.size < 500:
        out["canopy_centroid_y"] = np.nan
        out["canopy_top_y"] = np.nan
    else:
        out["canopy_centroid_y"] = float(ys.mean() / hgt)
        out["canopy_top_y"] = float(np.percentile(ys, 10) / hgt)
    return out


NAMES = [
    "coverage_hsv",
    "veg_frac",
    "chlorosis_rg",
    "blue_ratio",
    "necrosis_frac",
    "chlorosis_rg_ref",
    "blue_ratio_ref",
    "necrosis_frac_ref",
    "canopy_centroid_y",
    "canopy_top_y",
]

# What each proxy would be claiming if it were emitted as a symptom, and which
# perturbation in wf62's ladder is the thing it claims to detect.
CLAIMS = {
    "coverage_hsv": ("canopy coverage / chlorosis", ["chlorosis"]),
    "veg_frac": ("canopy extent", ["chlorosis"]),
    "chlorosis_rg": ("chlorosis", ["chlorosis"]),
    "blue_ratio": ("chlorosis", ["chlorosis"]),
    "necrosis_frac": ("necrosis", ["necrosis"]),
    "chlorosis_rg_ref": ("chlorosis (WB-referenced)", ["chlorosis"]),
    "blue_ratio_ref": ("chlorosis (WB-referenced)", ["chlorosis"]),
    "necrosis_frac_ref": ("necrosis (WB-referenced)", ["necrosis"]),
    "canopy_centroid_y": ("drooping", ["droop"]),
    "canopy_top_y": ("drooping", ["droop"]),
}


def auc(pos, neg):
    """P(a random positive scores above a random negative). Rank-based, ties at 0.5."""
    pos = np.asarray(pos, dtype=float)
    neg = np.asarray(neg, dtype=float)
    pos = pos[np.isfinite(pos)]
    neg = neg[np.isfinite(neg)]
    if pos.size == 0 or neg.size == 0:
        return np.nan
    allv = np.concatenate([pos, neg])
    r = np.argsort(np.argsort(allv)).astype(float)
    # average ranks for ties
    order = np.argsort(allv)
    sv = allv[order]
    i = 0
    while i < len(sv):
        j = i
        while j + 1 < len(sv) and sv[j + 1] == sv[i]:
            j += 1
        if j > i:
            r[order[i : j + 1]] = np.mean(r[order[i : j + 1]])
        i = j + 1
    return float(
        (r[: pos.size].sum() - pos.size * (pos.size - 1) / 2) / (pos.size * neg.size)
    )

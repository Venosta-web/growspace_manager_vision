"""PROTOTYPE — synthetic perturbations, split into plant-shaped and camera-shaped.

Camera-shaped magnitudes are calibrated against the corpus's own observed day-to-day
variation (mean luminance 96-185, median 145, sd 16.9; G/R 1.00-1.10; G/B 0.96-1.30),
so "a perturbation the camera plausibly produces" means one this camera did produce.
"""
import numpy as np
from PIL import Image
from scipy import ndimage

RNG = np.random.default_rng(20260831)


def _f(img):
    return np.asarray(img.convert("RGB"), dtype=np.float32)


def _i(a):
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def _canopy_mask(h, w, cx, cy, rx, ry, feather=25):
    y, x = np.mgrid[0:h, 0:w]
    m = (((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1.0).astype(np.float32)
    return ndimage.gaussian_filter(m, feather)[..., None]



def _veg_mask(a):
    """Vegetation pixels only.

    Under this tent's magenta LED the mylar and walls are pink/white and the plants are
    the only green-dominant surface. A plant symptom that also recolours the tent wall is
    a white-balance shift wearing a costume, and would corrupt the whole asymmetry test.
    """
    dom = a[..., 1] - np.maximum(a[..., 0], a[..., 2])
    m = np.clip(dom / 12.0, 0, 1).astype(np.float32)
    return ndimage.gaussian_filter(m, 2)[..., None]

# ---------------- plant-shaped: the detector SHOULD fire ----------------

def chlorosis(img, s, area=0.25):
    """Localised yellowing: chlorophyll loss pushes green pixels toward yellow."""
    a = _f(img); h, w, _ = a.shape
    r = np.sqrt(area * h * w / np.pi)
    m = _canopy_mask(h, w, w * 0.5, h * 0.62, r * 1.35, r * 0.75) * _veg_mask(a)
    out = a.copy()
    out[..., 0] = a[..., 0] + s * np.maximum(a[..., 1] - a[..., 0], 0)
    out[..., 2] = a[..., 2] * (1 - 0.55 * s)
    return _i(a * (1 - m) + out * m)


def chlorosis_global(img, s):
    """Whole-canopy yellowing, the nitrogen-deficiency presentation."""
    a = _f(img); out = a.copy()
    out[..., 0] = a[..., 0] + s * np.maximum(a[..., 1] - a[..., 0], 0)
    out[..., 2] = a[..., 2] * (1 - 0.55 * s)
    m = _veg_mask(a)
    return _i(a * (1 - m) + out * m)


def necrosis(img, s, area=0.12):
    """Blotchy brown dead tissue."""
    a = _f(img); h, w, _ = a.shape
    r = np.sqrt(area * h * w / np.pi)
    m = _canopy_mask(h, w, w * 0.42, h * 0.66, r * 1.3, r * 0.8, 18)
    speck = ndimage.gaussian_filter(RNG.random((h, w)).astype(np.float32), 7)
    speck = (speck - speck.min()) / (np.ptp(speck) + 1e-6)
    m = m * (speck > 0.55)[..., None] * _veg_mask(a)
    brown = np.array([132.0, 88.0, 46.0])
    return _i(a * (1 - s * m) + brown * (s * m))


def droop(img, px):
    """Wilting: canopy pixels pulled downward by a smooth field, up to `px` pixels."""
    a = _f(img); h, w, _ = a.shape
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    field = np.sin(np.pi * x / w) * np.clip((y - 0.15 * h) / (0.85 * h), 0, 1)
    sy = y - px * field
    return _i(np.stack([ndimage.map_coordinates(a[..., c], [sy, x], order=1, mode="nearest")
                        for c in range(3)], -1))


# ---------------- camera-shaped: the detector should NOT fire ----------------

def brightness(img, k):
    return _i(_f(img) * k)


def white_balance(img, kr, kb):
    a = _f(img).copy(); a[..., 0] *= kr; a[..., 2] *= kb
    return _i(a)


def sensor_noise(img, sd):
    a = _f(img)
    return _i(a + RNG.normal(0, sd, a.shape).astype(np.float32))


def recompress(img, q):
    import io
    b = io.BytesIO(); img.convert("RGB").save(b, "JPEG", quality=q); b.seek(0)
    return Image.open(b).convert("RGB")


def pose_jitter(img, frac):
    """A camera nudge: translate by `frac` of the frame and rescale to fill."""
    a = _f(img); h, w, _ = a.shape
    dx, dy = frac * w, frac * h * 0.6
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    return _i(np.stack([ndimage.map_coordinates(a[..., c], [y + dy, x + dx], order=1,
                                                mode="nearest") for c in range(3)], -1))


def contrast(img, k):
    a = _f(img); return _i((a - a.mean()) * k + a.mean())


# severity ladders. Camera magnitudes sit inside the corpus's own observed spread.
PLANT = {
    "chlorosis-patch mild":     lambda im: chlorosis(im, 0.35),
    "chlorosis-patch moderate": lambda im: chlorosis(im, 0.65),
    "chlorosis-patch severe":   lambda im: chlorosis(im, 1.00),
    "chlorosis-global mild":    lambda im: chlorosis_global(im, 0.30),
    "chlorosis-global moderate": lambda im: chlorosis_global(im, 0.60),
    "necrosis mild":            lambda im: necrosis(im, 0.45),
    "necrosis moderate":        lambda im: necrosis(im, 0.80),
    "droop 15px":               lambda im: droop(im, 15),
    "droop 35px":               lambda im: droop(im, 35),
    "droop 70px":               lambda im: droop(im, 70),
}
CAMERA = {
    "brightness -15%":  lambda im: brightness(im, 0.85),
    "brightness +15%":  lambda im: brightness(im, 1.15),
    "brightness +30%":  lambda im: brightness(im, 1.30),
    "white-bal warm 8%": lambda im: white_balance(im, 1.08, 0.93),
    "white-bal cool 8%": lambda im: white_balance(im, 0.93, 1.08),
    "white-bal warm 15%": lambda im: white_balance(im, 1.15, 0.87),
    "sensor noise sd4": lambda im: sensor_noise(im, 4),
    "sensor noise sd8": lambda im: sensor_noise(im, 8),
    "jpeg q50":         lambda im: recompress(im, 50),
    "contrast x1.15":   lambda im: contrast(im, 1.15),
    "pose jitter 2%":   lambda im: pose_jitter(im, 0.02),
    "pose jitter 4%":   lambda im: pose_jitter(im, 0.04),
}

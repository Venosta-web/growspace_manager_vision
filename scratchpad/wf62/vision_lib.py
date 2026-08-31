"""PROTOTYPE — throwaway. Issue #62: does embedding distance separate real canopy change?

Encoder is the one settled by issue #61: DINOv2 ViT-S/14 int8 ONNX, 384-d CLS token,
ONNX Runtime CPUExecutionProvider.
"""
import datetime as dt
import os
import re
import numpy as np
from PIL import Image
import onnxruntime as ort

CORPUS = "/home/maxi/Pictures/growspace manager vision"
MODEL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "model_int8.onnx")

IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)

_SESS = None


def session():
    global _SESS
    if _SESS is None:
        so = ort.SessionOptions()
        so.intra_op_num_threads = 8
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        _SESS = ort.InferenceSession(MODEL, so, providers=["CPUExecutionProvider"])
    return _SESS


def preprocess(img, geometry="full168"):
    """DINOv2 needs each side a multiple of 14.

    full168 -- resize the whole 800x600 frame to 224x168. Keeps aspect, keeps every
               pixel; the canopy fills the frame so cropping would discard real content.
    crop224 -- centre-crop to square then resize to 224x224, the conventional recipe.
    """
    if geometry == "full168":
        im = img.convert("RGB").resize((224, 168), Image.BICUBIC)
    elif geometry == "crop224":
        w, h = img.size
        s = min(w, h)
        im = img.convert("RGB").crop(((w - s) // 2, (h - s) // 2, (w + s) // 2, (h + s) // 2))
        im = im.resize((224, 224), Image.BICUBIC)
    else:
        raise ValueError(geometry)
    a = np.asarray(im, dtype=np.float32) / 255.0
    a = (a - IMAGENET_MEAN) / IMAGENET_STD
    return a.transpose(2, 0, 1)[None]


def encode(img, geometry="full168"):
    """-> L2-normalised 384-d CLS embedding."""
    out = session().run(None, {"pixel_values": preprocess(img, geometry)})[0]
    v = out[0, 0].astype(np.float64)
    return v / np.linalg.norm(v)


def frame_stats(img):
    a = np.asarray(img.convert("RGB"), dtype=np.float32)
    lum = 0.299 * a[..., 0] + 0.587 * a[..., 1] + 0.114 * a[..., 2]
    g = lum[::2, ::2]
    detail = float(np.mean(np.abs(np.diff(g, axis=0))) + np.mean(np.abs(np.diff(g, axis=1)))) / 2
    eps = 1e-6
    return {
        "mean_lum": float(lum.mean()),
        "blown": float((lum > 245).mean()),
        "dark": float((lum < 16).mean()),
        "detail": detail,
        "gr": float(a[..., 1].mean() / (a[..., 0].mean() + eps)),
        "gb": float(a[..., 1].mean() / (a[..., 2].mean() + eps)),
    }


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


def cosdist(a, b):
    """Cosine distance between L2-normalised rows."""
    return 1.0 - np.asarray(a) @ np.asarray(b).T

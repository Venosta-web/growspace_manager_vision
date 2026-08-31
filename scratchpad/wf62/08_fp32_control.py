"""PROTOTYPE — control: is the weak sensitivity an int8 artifact, or the encoder?

Re-runs the decisive subset on the fp32 artifact. If fp32 shows the plant-vs-camera
asymmetry that int8 doesn't, the verdict is about quantisation, not about the approach.
"""
import datetime as dt
import numpy as np
import onnxruntime as ort
from PIL import Image
import vision_lib as V
import score_lib as S
import perturb as P
from segments import label

so = ort.SessionOptions(); so.intra_op_num_threads = 8
FP32 = ort.InferenceSession("model_fp32.onnx", so, providers=["CPUExecutionProvider"])


def enc32(img):
    v = FP32.run(None, {"pixel_values": V.preprocess(img, "full168")})[0][0, 0].astype(np.float64)
    return v / np.linalg.norm(v)


z = np.load("embeddings.npz")
dates = [dt.date.fromisoformat(s) for s in z["dates"]]
rows = V.corpus()
stable = [i for i, d in enumerate(dates) if label(d) == "framing-4 STABLE"]
imgs = {i: Image.open(rows[i][1]) for i in stable}
X32 = np.array([enc32(imgs[i]) for i in stable])
nB = 30
B32 = X32[:nB]
loo = S.loo_scores(B32)
m = "centroid-cos"
sd = loo[m].std(ddof=1)
tau = loo[m].mean() + 3 * sd
print(f"fp32 baseline LOO ({m}): mean {loo[m].mean():.4f} sd {sd:.4f} max {loo[m].max():.4f}")

CONDS = [("PLANT", k, P.PLANT[k]) for k in ("chlorosis-patch severe", "chlorosis-global moderate",
                                            "necrosis moderate", "droop 70px")] + \
        [("CAMERA", k, P.CAMERA[k]) for k in ("white-bal warm 15%", "brightness +30%",
                                              "pose jitter 4%", "sensor noise sd8")]


def scores(fn):
    out = []
    for j, i in enumerate(stable):
        Bi = np.delete(B32, j, axis=0) if j < nB else B32
        out.append(S.centroid_cos(Bi, enc32(fn(imgs[i]))))
    return np.array(out)


ref = scores(lambda im: im)
print(f"\n{'kind':>7} {'perturbation':<26} {'z(sd)':>8} {'fire%':>7} {'AUC':>7}   [int8 AUC]")
INT8 = {"chlorosis-patch severe": 0.77, "chlorosis-global moderate": 0.77,
        "necrosis moderate": 0.69, "droop 70px": 0.56, "white-bal warm 15%": 0.71,
        "brightness +30%": 0.60, "pose jitter 4%": 0.76, "sensor noise sd8": 0.53}
pv, cv = [], []
for kind, nm, fn in CONDS:
    v = scores(fn)
    auc = (v[:, None] > ref[None, :]).mean()
    (pv if kind == "PLANT" else cv).append(v)
    print(f"{kind:>7} {nm:<26} {(v.mean()-ref.mean())/sd:>8.1f} {100*(v>tau).mean():>7.0f} "
          f"{auc:>7.2f}   [{INT8[nm]:.2f}]")
pv, cv = np.concatenate(pv), np.concatenate(cv)
print(f"\nfp32 plant-vs-camera separation AUC: {(pv[:,None] > cv[None,:]).mean():.3f}  "
      f"(0.50 = the two are indistinguishable)")

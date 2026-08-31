"""PROTOTYPE — the three candidate scoring methods from issue #62."""
import numpy as np


def centroid_cos(B, x):
    c = B.mean(0); c = c / np.linalg.norm(c)
    return 1.0 - np.asarray(x) @ c


def knn_mean(B, x, k=5):
    d = 1.0 - np.atleast_2d(x) @ B.T
    d = np.sort(d, axis=1)[:, :k]
    r = d.mean(1)
    return r if np.ndim(x) > 1 else float(r[0])


def pca_maha_fit(B, k=8):
    mu = B.mean(0)
    U, sv, Vt = np.linalg.svd(B - mu, full_matrices=False)
    n = len(B)
    comps = Vt[:k]
    sd = sv[:k] / np.sqrt(n - 1)
    return mu, comps, np.maximum(sd, 1e-8)


def pca_maha(fit, x):
    mu, comps, sd = fit
    p = (np.atleast_2d(x) - mu) @ comps.T / sd
    r = np.sqrt((p ** 2).sum(1))
    return r if np.ndim(x) > 1 else float(r[0])


def score_all(B, x, k_nn=5, k_pca=8):
    return {
        "centroid-cos": centroid_cos(B, x),
        f"knn{k_nn}-mean": knn_mean(B, x, k_nn),
        f"pca{k_pca}-maha": pca_maha(pca_maha_fit(B, k_pca), x),
    }


def loo_scores(B, k_nn=5, k_pca=8):
    """Leave-one-out scores of the baseline against itself -> calibration sample."""
    out = {}
    for i in range(len(B)):
        rest = np.delete(B, i, axis=0)
        for nm, v in score_all(rest, B[i], k_nn, k_pca).items():
            out.setdefault(nm, []).append(float(v))
    return {k: np.array(v) for k, v in out.items()}

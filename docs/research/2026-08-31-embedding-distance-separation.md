# Does embedding distance separate real canopy change from noise?

Prototype findings for
[Prove embedding distance separates real canopy change](https://github.com/Venosta-web/growspace_manager_workspace/issues/62),
the go/no-go for the anomaly-detection premise on
[Local Vision Subsystem for Growspace Manager (V1)](https://github.com/Venosta-web/growspace_manager_workspace/issues/60).

Everything below is measured on the real corpus with the encoder settled by
[Choose the visual encoder and CPU inference runtime](https://github.com/Venosta-web/growspace_manager_workspace/issues/61) —
DINOv2 ViT-S/14 int8 ONNX, 384-d CLS token, ONNX Runtime `CPUExecutionProvider`,
`onnxruntime` 1.29.0. Scripts in [`scratchpad/wf62/`](../../scratchpad/wf62/); every
number here is reproducible by running them in order.

---

## Verdict

**The premise half-holds, and the half that fails is the half V1 needs.**

Embedding distance from a healthy baseline is an excellent **gross-change** detector and
a poor **plant-health** detector.

- Within the one bucket in the corpus that has a genuinely fixed camera, the noise floor
  is **centroid-cosine 0.057 ± 0.024**, and real scene events sit at **0.29 – 0.93** —
  a 5–16× margin, with **0 false alarms in 35 in-bucket frames**.
- But the asymmetry the ticket named as crucial **fails**. A white-balance shift inside
  the camera's own observed range scores as high as visually obvious yellowing
  (AUC 0.71 vs 0.77), and a 4% camera nudge outscores every simulated plant symptom.
  Plant-vs-camera separation is **AUC 0.56** — barely above chance.
- **This is not a quantisation artifact.** The fp32 artifact reproduces every AUC within
  0.05 (§ [fp32 control](#the-fp32-control-it-is-the-encoder-not-int8)).
- **Per-sector scoring does not rescue it; it inverts.** Plant-vs-camera AUC **0.34** —
  *below* chance, because a camera nudge moves sector contents wholesale
  (§ [Sectors](#the-rescue-attempt-per-sector-scoring-makes-it-worse)).

**Scoring method: centroid-cosine.** Tied with k-NN on sensitivity, better on
specificity, cheapest and most interpretable. **PCA-Mahalanobis must be rejected
outright** — it is not merely weak, it is unsafe (§ [Methods](#scoring-methods-at-n30)).

**Baseline must roll.** A fixed baseline drifts into a 33% false-alarm rate within three
weeks *inside the same fixed-camera bucket*.

The route implication is in [What this means for the map](#what-this-means-for-the-map):
this does not close the map, but it does redraw what V1's visual channel is allowed to
claim.

---

## The corpus is not what the map records

Three facts recorded from
[Export the production snapshot corpus](https://github.com/Venosta-web/growspace_manager_workspace/issues/63)
are wrong, and all three change the experiment. They were found by looking at the frames
([sheet 1](assets/embedding-separation/corpus-sheet-1.jpg),
[sheet 2](assets/embedding-separation/corpus-sheet-2.jpg)) after the embedding distances
pointed at days that no photometric statistic explained.

### 1. The camera moved — four times

The map records *"The camera did not move; it got buried"*, on median adjacent-day
structural correlation of 0.923 recovering to 0.66–0.72 after each excursion. That
recovery was read as "no permanent reframing". It is not: the framing is visibly
different before and after each excursion.

| date | event | struct corr | embedding dist |
|---|---|---|---|
| 2026-04-12 → 04-13 | canopy grows into the lens | +0.583 | 0.155 |
| 2026-04-21 → 04-22 | **repositioned** — trellis view | +0.292 | 0.324 |
| 2026-04-26 → 04-27 | **repositioned** — fan enters frame | +0.368 | 0.397 |
| 2026-05-15 → 05-16 | **repositioned** — pulled back to wide tent view | +0.352 | 0.742 |
| 2026-05-16 → 05-17 | settles into final framing | +0.391 | 0.321 |
| 2026-06-20 → 06-21 | **canopy removed (harvest)** | **+0.874** | **0.711** |
| 2026-06-24 → 06-25 | lights off | −0.022 | 0.980 |

### 2. There is a second occlusion window

**2026-05-04 to 2026-05-15**, 12 frames, the camera engulfed by the canopy again. Only
the April window (04-13 to 04-21) is recorded.

### 3. Harvest was 2026-06-21, not ~06-24

Frames 06-21 to 06-24 are post-harvest: an empty tent with the trellis net visible and a
few remnants. Lights off from 06-25.

### The corrected segmentation

Verified by exposure-invariant structural correlation on 32×24 standardised signatures
([`03_verify_segments.py`](../../scratchpad/wf62/03_verify_segments.py)):

| segment | dates | n | adj. struct corr (med / min) |
|---|---|---|---|
| framing-1 veg | 03-21 → 04-12 | 23 | 0.925 / 0.491 |
| occlusion-1 | 04-13 → 04-21 | 9 | 0.640 / 0.334 |
| framing-2 | 04-22 → 04-26 | 5 | 0.784 / 0.749 |
| framing-3 | 04-27 → 05-03 | 7 | 0.843 / 0.711 |
| occlusion-2 | 05-04 → 05-15 | 12 | 0.822 / 0.297 |
| reframe day | 05-16 | 1 | — |
| **framing-4 STABLE** | **05-17 → 06-20** | **35** | **0.978 / 0.908** |
| post-harvest | 06-21 → 06-24 | 4 | 0.982 / 0.974 |
| lights-off | 06-25 → 07-07 | 13 | — |

**The largest same-camera bucket is 35 frames, not the 39 recorded.** Everything below
uses it: baseline = the first 30 (05-17 → 06-15), untouched holdout = the last 5
(06-16 → 06-20).

The corpus also is **not** free of real positives, as recorded. It contains one large,
dated, unambiguous canopy event — the harvest — plus four camera events. Those are the
only ground truth available, and they turn out to carry the most useful result here.

---

## The noise floor

Measured inside framing-4, leave-one-out over the 30-frame baseline
([`04_score.py`](../../scratchpad/wf62/04_score.py)):

| method | mean | sd | max | 3σ gate |
|---|---|---|---|---|
| **centroid-cosine** | **0.0566** | **0.0244** | 0.1339 | 0.1299 |
| k-NN(5) mean | 0.0573 | 0.0174 | 0.1054 | 0.1094 |
| PCA(8) Mahalanobis | 2.4123 | 0.6789 | 4.4278 | 4.4489 |

**The noise floor is ≈ 0.06, and the usable gate is ≈ 0.13.**

The corpus-wide figure is much worse and much more misleading. Measured across all
"clean" frames without the corrected segmentation, adjacent-day distance has median
0.089 but **p95 0.25 and max 0.74** — a fat tail composed *entirely* of the camera
events above. Bucketing correctly removes the tail: within framing-4, adjacent-day
median is 0.058 and max 0.169.

> Anyone setting a threshold from the uncorrected corpus would set it ~4× too high and
> lose all sensitivity. The bucketing decision is load-bearing, not tidy.

### Distance vs day-gap, all clean frames (uncorrected — shown for contrast)

| gap (days) | n | median | p95 | max |
|---|---|---|---|---|
| 1 | 85 | 0.089 | 0.251 | 0.742 |
| 2 | 83 | 0.104 | 0.390 | 0.772 |
| 4–7 | 304 | 0.165 | 0.593 | 0.792 |
| 8–14 | 470 | 0.309 | 0.631 | 0.802 |
| 15–30 | 916 | 0.361 | 0.740 | 0.848 |
| 31–60 | 1244 | 0.452 | 0.792 | 1.012 |

---

## What dominates variance

Corpus-wide PCA says day-of-run is PC1 (28.3% of variance, Spearman +0.68) — the
outcome the ticket flagged as fatal for a fixed baseline. **That reading is
contaminated**: the four camera reframes are monotonic in time, so "day-of-run" was
partly measuring them.

Restricted to framing-4, where the camera is genuinely fixed
([`06_drift.py`](../../scratchpad/wf62/06_drift.py)):

| PC | var % | day_of_run | mean_lum | blown | detail | G/R | G/B |
|---|---|---|---|---|---|---|---|
| PC1 | 24.1 | 0.22 | 0.25 | 0.02 | 0.38 | −0.05 | −0.08 |
| **PC2** | **20.6** | **−0.92** | −0.70 | −0.84 | −0.54 | **0.86** | **0.86** |
| PC3 | 7.9 | −0.15 | −0.07 | 0.02 | −0.17 | 0.23 | 0.11 |

PC2 is the growth-and-fade axis: day-of-run, falling green ratio, falling blown
highlights, all bundled together — which is exactly what late flower looks like. It is
**second**, at ~21%, not a runaway. Growth drift is real but not overwhelming.

Pairwise distance tracks time far more than exposure, and survives controlling for it:

| | Spearman ρ |
|---|---|
| distance vs \|day gap\| | +0.501 |
| distance vs \|mean-luminance diff\| | +0.209 |
| partial ρ(distance, \|lum diff\| \| day gap) | +0.183 |
| **partial ρ(distance, \|day gap\| \| lum diff)** | **+0.493** |

---

## Cross-light-window distance: not measurable

The ticket asks for cross- vs within-light-window distance. **The corpus cannot answer
it.** It is one capture per day from a separate daily automation, so there are no
light-window buckets in the history — a fact already recorded on the map.

What *is* measurable is the concern underneath it: does exposure difference drive
distance? Partly, and weakly — partial ρ = +0.18 after controlling for day gap, against
+0.49 the other way. Brightness perturbations of ±15% and ±30% (inside the corpus's own
96–185 mean-luminance range) move the score by z = 0.1–0.4σ. **Exposure is not the
dominant nuisance; camera geometry is.** Per-light-window bucketing still rests on
argument, not measurement, and this prototype does not settle it.

---

## Sensitivity: the asymmetry test fails

Perturbations applied to all 35 framing-4 frames, baseline members scored leave-one-out
([`perturb.py`](../../scratchpad/wf62/perturb.py),
[`04_score.py`](../../scratchpad/wf62/04_score.py)).

Plant-shaped perturbations are **vegetation-masked** — applied only to green-dominant
pixels. This matters: an unmasked "global chlorosis" recolours the mylar and tent walls
too, which makes it a white-balance shift wearing a costume and would have corrupted the
entire test. Camera-shaped magnitudes are calibrated to the corpus's own observed
spread (mean luminance 96–185, G/R 1.00–1.10, G/B 0.96–1.30), so "plausible" means
"this camera did this".
[Rendered perturbations](assets/embedding-separation/perturbations-plant.jpg).

`z` = score rise in baseline-σ units; `fire%` = fraction over the 3σ gate;
AUC vs the unperturbed frames.

| | perturbation | centroid-cos z / fire / AUC | k-NN(5) z / fire / AUC |
|---|---|---|---|
| PLANT | chlorosis-patch mild | 0.6 / 11 / 0.59 | 0.8 / 11 / 0.66 |
| PLANT | chlorosis-patch moderate | 1.1 / 20 / 0.70 | 1.4 / 23 / 0.77 |
| PLANT | **chlorosis-patch severe** | 1.5 / 23 / **0.77** | 1.9 / 29 / **0.84** |
| PLANT | chlorosis-global mild | 0.9 / 14 / 0.64 | 1.1 / 14 / 0.73 |
| PLANT | chlorosis-global moderate | 1.6 / 29 / 0.77 | 2.0 / 23 / 0.86 |
| PLANT | necrosis mild | 0.4 / 11 / 0.58 | 0.6 / 9 / 0.65 |
| PLANT | necrosis moderate | 1.0 / 17 / 0.69 | 1.4 / 20 / 0.76 |
| PLANT | droop 15px | 0.1 / 6 / 0.50 | 0.2 / 6 / 0.52 |
| PLANT | droop 35px | 0.2 / 9 / 0.51 | 0.3 / 9 / 0.57 |
| PLANT | droop 70px | 0.2 / 3 / 0.56 | 0.5 / 6 / 0.63 |
| CAMERA | brightness −15% | 0.1 / 6 / 0.50 | 0.2 / 6 / 0.54 |
| CAMERA | brightness +15% | −0.0 / 9 / 0.49 | 0.1 / 6 / 0.52 |
| CAMERA | brightness +30% | 0.3 / 6 / 0.60 | 0.4 / 6 / 0.63 |
| CAMERA | white-bal warm 8% | 0.3 / 6 / 0.58 | 0.7 / 9 / 0.67 |
| CAMERA | white-bal cool 8% | 0.1 / 9 / 0.53 | 0.1 / 3 / 0.55 |
| CAMERA | **white-bal warm 15%** | 1.0 / 9 / **0.71** | 1.6 / 17 / **0.82** |
| CAMERA | sensor noise sd4 | 0.0 / 9 / 0.48 | 0.0 / 6 / 0.51 |
| CAMERA | sensor noise sd8 | 0.2 / 11 / 0.53 | 0.3 / 6 / 0.56 |
| CAMERA | jpeg q50 | −0.0 / 6 / 0.49 | 0.0 / 3 / 0.53 |
| CAMERA | contrast ×1.15 | −0.0 / 3 / 0.48 | 0.0 / 3 / 0.52 |
| CAMERA | pose jitter 2% | 0.4 / 0 / 0.66 | 0.4 / 0 / 0.64 |
| CAMERA | **pose jitter 4%** | 0.8 / 3 / **0.76** | 1.3 / 11 / **0.80** |

Three things to read off this table:

1. **The strongest plant signal barely clears the strongest camera signal.** Severe
   localised chlorosis: AUC 0.77 / 0.84. Warm white balance at 15%: AUC 0.71 / 0.82.
   These are the same number. The ticket's own framing was that *"a metric that flags a
   white-balance change as hard as it flags yellowing will produce exactly the false
   alarms this project exists to eliminate."* It does.
2. **Camera pose beats plant symptoms.** A 4% nudge (AUC 0.76 / 0.80) outscores necrosis
   moderate, every chlorosis-patch level below severe, and all three droop levels.
3. **Geometric symptoms are invisible.** Droop at 70px — 12% of frame height, plainly
   visible to a human — reaches AUC 0.56 / 0.63. Whole-frame DINOv2 embeddings are
   near-blind to canopy geometry at this resolution.

Sensitivity is also just *low* in absolute terms: at a gate tuned for 0 false alarms,
visually obvious severe chlorosis is caught **23–29% of the time**.

### The fp32 control: it is the encoder, not int8

The obvious objection is that int8 quantisation blunted the geometry.
[`08_fp32_control.py`](../../scratchpad/wf62/08_fp32_control.py) re-runs the decisive
subset on the fp32 artifact (88.5 MB):

| | perturbation | fp32 AUC | int8 AUC |
|---|---|---|---|
| PLANT | chlorosis-patch severe | 0.77 | 0.77 |
| PLANT | chlorosis-global moderate | 0.78 | 0.77 |
| PLANT | necrosis moderate | 0.69 | 0.69 |
| PLANT | droop 70px | 0.56 | 0.56 |
| CAMERA | white-bal warm 15% | 0.71 | 0.71 |
| CAMERA | brightness +30% | 0.55 | 0.60 |
| CAMERA | pose jitter 4% | 0.80 | 0.76 |
| CAMERA | sensor noise sd8 | 0.53 | 0.53 |

**fp32 plant-vs-camera separation AUC: 0.564.** The limitation is the encoder's
representation, not the quantisation — and as a side benefit this confirms on real data
the int8-fidelity claim that issue #61 established on two fixtures.

### The rescue attempt: per-sector scoring makes it worse

The map reserves `regions: []` at zero cost, and a localised symptom occupying a few
percent of an 800×600 frame is plausibly just washed out by whole-frame pooling. The
hypothesis worth testing: **a camera-shaped change moves every sector together, a
plant-shaped one moves one or two — so the discriminating statistic is the spread across
sectors, not the distance.**

Tested on a 4×4 grid, the same sectors `GrowspaceImageProcessor` already draws, with
per-sector baselines ([`05_sectors.py`](../../scratchpad/wf62/05_sectors.py),
[`07_sector_scores.py`](../../scratchpad/wf62/07_sector_scores.py)).

**It fails, and it fails backwards.**

| statistic | plant-vs-camera AUC |
|---|---|
| max over sectors | 0.336 |
| median over sectors | 0.340 |
| spread (max − median) | 0.382 |

All three are *below* 0.50, meaning camera-shaped perturbations produce **larger**
sector statistics than plant-shaped ones. Pose jitter 4% is the single strongest signal
in the whole sector experiment (z = 2.5, fires 40%, AUC 0.94) — a small camera nudge
shifts what is inside each cell wholesale, which is precisely the change a per-sector
baseline is most sensitive to. Per-sector baselines are also far noisier: clean
leave-one-out max-sector is 0.231 ± 0.077, against 0.057 ± 0.024 whole-frame.

Sector-level analysis is not a rescue for the asymmetry problem, and should not be
carried forward as one.

---

## Scoring methods at n≈30

Untouched holdout (5 healthy frames the baseline has never seen):

| method | 06-16 | 06-17 | 06-18 | 06-19 | 06-20 | over gate |
|---|---|---|---|---|---|---|
| centroid-cosine | 0.0505 | 0.1252 | 0.1257 | 0.0761 | 0.0644 | **0 / 5** |
| k-NN(5) mean | 0.0619 | 0.0882 | 0.1165 | 0.0747 | 0.0796 | 1 / 5 |
| PCA(8) Mahalanobis | 1.806 | 2.536 | 3.010 | 1.786 | 1.736 | 0 / 5 |

**Recommendation: centroid-cosine.** k-NN(5) is marginally more sensitive (consistently
+0.05–0.09 AUC on plant perturbations) but gave the only holdout false alarm, needs the
whole baseline retained at scoring time rather than one 384-float centroid, and buys a
sensitivity improvement too small to change any decision when the ceiling is AUC 0.84.

**PCA-Mahalanobis: reject.** Not merely weak (AUC ≈ 0.5 on every perturbation) but
**unsafe**. Applied to the full corpus it flags **0% of lights-off frames** — frames
that are essentially black, at centroid-cosine distance 0.93. Mahalanobis in a
baseline-fitted 8-component subspace has no reconstruction-error term, so an input far
*outside* the baseline's subspace projects near its centre and scores as normal. Any
Mahalanobis variant used here would need an explicit residual term; as specified in the
ticket, it silently passes the most anomalous frames in the corpus.

---

## What the gate does to real events

Fixed baseline (framing-4 first 30), 3σ gate, applied to the whole corpus:

| segment | n | centroid-cos median | fires |
|---|---|---|---|
| framing-1 veg | 23 | 0.405 | 100% |
| occlusion-1 | 9 | 0.593 | 100% |
| framing-2 | 5 | 0.431 | 100% |
| framing-3 | 7 | 0.325 | 100% |
| occlusion-2 | 12 | 0.446 | 100% |
| reframe day | 1 | 0.358 | 100% |
| **framing-4 STABLE** | **35** | **0.053** | **0%** |
| post-harvest | 4 | 0.688 | 100% |
| lights-off | 13 | 0.928 | 100% |

**Specificity inside the correct bucket is perfect, and every real scene event is caught
with a 5–16× margin.** This is the strong positive result, and it is about gross change,
not health.

### The one genuinely useful discriminator found

| event | struct corr | embedding dist |
|---|---|---|
| camera reframe (05-15 → 05-16) | **0.352** | 0.742 |
| harvest (06-20 → 06-21) | **0.874** | 0.711 |

Embedding distance alone **cannot** tell "the camera moved" from "the plants are gone" —
both sit at ≈ 0.72. A 32×24 standardised structural correlation separates them cleanly
and costs microseconds. **Pairing the embedding score with an exposure-invariant
structural check is the cheapest real capability this prototype found**, and it feeds
[Define the frame quality gate](https://github.com/Venosta-web/growspace_manager_workspace/issues/74)
directly.

---

## Baseline validity: fixed vs rolling

Within framing-4 — same camera, no known problem — a 14-frame baseline, scoring the
frames that follow ([`06_drift.py`](../../scratchpad/wf62/06_drift.py)). Median score,
and % over that baseline's own 3σ gate:

| baseline | +0–4d | +5–9d | +10–14d | +15–20d |
|---|---|---|---|---|
| **fixed** (first 14) | 0.073 (0%) | 0.070 (0%) | 0.096 (0%) | 0.102 (**33%**) |
| **rolling** (preceding 14) | 0.050 (0%) | 0.041 (0%) | 0.063 (20%) | 0.059 (17%) |

**A fixed baseline drifts into a 33% false-alarm rate within three weeks**, inside a
single bucket with a fixed camera and healthy plants. Rolling holds the median flat
(0.041–0.063 with no trend) and roughly halves the alarm rate. The baseline must roll.

Two caveats worth carrying forward rather than burying:

- **Rolling does not reach 0%.** A tighter local window shrinks σ, so the 3σ gate
  tightens with it, and 17–20% still cross. The gate, not just the baseline, is wrong.
- **The 3σ Gaussian rule is the wrong shape.** Leave-one-out scores are right-skewed
  (centroid-cosine mean 0.057, sd 0.024, max 0.134 — the max is 3.2σ out on 30 samples).
  An empirical quantile or max-based rule fits the data; a Gaussian gate does not.

---

## What this means for the map

**This does not close the map. It redraws what V1's visual channel may claim.**

The map's core invariant — visual inference never receives environmental data — is
untouched and still worth building. What fails is the ambition that a distance score can
report *plant health*. The measured capability is narrower and genuinely useful:

> **"This scene is materially different from its recent history"** — harvest, lights
> failure, camera moved, lens occluded, capture unusable — detected with a 5–16× margin
> and no in-bucket false alarms.

Not:

> **"The plant looks unhealthy."** At the gate that gives zero false alarms, obvious
> chlorosis is caught under a third of the time, droop not at all, and a white-balance
> shift scores as high as yellowing.

Shipping the second claim on this evidence would reproduce the exact failure the map
exists to fix — the current cloud VLM confidently reporting symptoms that aren't there —
with a local model instead of a remote one.

### Consequences for open tickets

- **[Define baseline validity, distance metric and thresholds](https://github.com/Venosta-web/growspace_manager_workspace/issues/66)** —
  has its numbers: metric centroid-cosine, noise floor 0.057 ± 0.024, gate ≈ 0.13,
  rolling window required, empirical-quantile gate rather than 3σ, minimum bucket ~30
  frames of one fixed framing.
- **[Decide which symptom outputs V1 can honestly emit](https://github.com/Venosta-web/growspace_manager_workspace/issues/68)** —
  the honest answer is now measured, and it is "none, at symptom granularity". This
  ticket becomes the most important one on the map.
- **[Define the frame quality gate](https://github.com/Venosta-web/growspace_manager_workspace/issues/74)** —
  gains a concrete mechanism: structural correlation separates camera-move from
  content-change where embedding distance cannot.
- **[Decide what evidence justifies alerting on an anomaly score](https://github.com/Venosta-web/growspace_manager_workspace/issues/75)** —
  the answer cannot be "a high distance", since camera events dominate the high-distance
  population in the only corpus available.
- **Sector / region-level analysis** should move from "reserved at zero cost" to
  measured-and-rejected for this purpose.

### What this prototype could not answer

- **Sensitivity to real symptoms.** Every plant-shaped number here is synthetic. The
  corpus contains zero health positives, so all sensitivity figures are a proxy whose
  realism is unvalidated. The asymmetry failure is robust regardless — it is driven by
  how high the *camera-shaped* scores are, which is measured on real perturbations of
  real frames.
- **Per-light-window bucketing** — no light-window structure exists in the corpus.
- **Whether a different encoder would do better.** CLIP ViT-B/32 is the named runner-up
  and was not tested here. Given the failure is that the representation encodes camera
  geometry and global colour more strongly than local plant colour, a text-aligned
  encoder is unlikely to fix it, but that is an argument, not a measurement.

---

## Appendix — method

Corpus: 109 JPEGs at `~/Pictures/growspace manager vision/`, 800×600, one camera, one
Grow Run, 2026-03-21 → 2026-07-07.

Encoder: `onnx-community/dinov2-small` → `onnx/model_int8.onnx` (24.4 MB) and
`onnx/model.onnx` (88.5 MB) for the control. ONNX Runtime 1.29.0,
`CPUExecutionProvider`, `intra_op_num_threads=8`. Embedding is token 0 of
`last_hidden_state`, L2-normalised.

Preprocessing: whole frame resized to **224×168** (both sides multiples of 14, aspect
preserved, no crop — the canopy fills the frame, so cropping discards real content),
ImageNet mean/std normalisation. A 224×224 centre-crop variant was computed throughout
and tracks the same conclusions (adjacent-day median 0.079 vs 0.089; corpus PC1
day-of-run ρ +0.71 vs +0.68).

Sector variant: 4×4 grid, each cell resized to 154×112, all 16 batched into one ORT
call.

Run order:

```
01_embed.py            # corpus embeddings + per-frame photometric stats
02_variance.py         # noise floor, corpus-wide PCA, distance-vs-cause correlations
02b_outliers.py        # which adjacent-day pairs fatten the tail
02c_struct.py          # exposure-invariant structural signatures
03_verify_segments.py  # verifies the corrected segmentation
04_score.py            # MAIN: three methods, sensitivity, gate vs real events
05_sectors.py          # per-sector embeddings (batched)
06_drift.py            # in-bucket PCA, fixed vs rolling baseline
07_sector_scores.py    # per-sector statistics, plant-vs-camera separation
08_fp32_control.py     # quantisation control
```

# Which captures are unfit to score, and unfit to enter a baseline?

Prototype findings for
[Define the frame quality gate](https://github.com/Venosta-web/growspace_manager_workspace/issues/74)
on [Local Vision Subsystem for Growspace Manager (V1)](https://github.com/Venosta-web/growspace_manager_workspace/issues/60).

Measured on the same 109-frame production corpus as
[#62](2026-08-31-embedding-distance-separation.md) and #63, against that corpus's
corrected segmentation. Nothing here needs the encoder: every statistic is arithmetic
over pixels, which is the whole reason a gate can run before inference. Scripts in
[`scratchpad/wf74/`](../../scratchpad/wf74/); every number below is reproducible by
running them in order.

---

## Verdict

**One of the two things the ticket set out to gate is not a quality problem at all.**

- **Darkness is decisive and absolute.** Lights-off frames sit at mean luminance
  **1.2 – 4.1**; the dimmest usable frame is **96.4**. A floor at **16** clears the
  brightest dark frame by 3.9x and the dimmest usable frame by 6.0x. No history is
  needed, and none would help.
- **Occlusion is not a blur event and no detail measure finds it.** Nine candidate
  detail statistics were tested against the two known occlusion windows. The best
  separates them from clean frames at **AUC 0.69**, the contract's own
  `mean_absolute_gradient` at **0.62**, and the coarse variants at **chance**. The
  reason is physical: a leaf pressed against the lens is *texture*, not blur. The three
  highest-detail frames in the entire corpus (`grad` 7.7 – 8.0 against a clean median
  of 5.0) are inside occlusion window 2.
- **Which is correct, because those frames must not be gated.** An occluded frame is a
  true material scene change — #62 measured occlusion at centroid-cosine **0.45 – 0.59**
  against a 0.13 noise ceiling — and the correct response is to say so, not to hide it.
  Gating them would suppress the equipment fault the grower needs to hear about.
- **The relative rails cannot be calibrated, only bounded.** The corpus contains no
  transient exposure excursion. Every clean frame lands within **0.79 – 1.30** of its
  own trailing median luminance and **0.71 – 1.46** of its trailing median detail. Rails
  at 0.5 / 2.0 and 0.5 therefore fire on **nothing** in 75 clean frames, at every
  window and warm-up tried. They are specificity-only bounds, not a tuned detector.
- **Structural correlation cannot tell a camera move from a lens burial.** The four
  known repositionings score 0.291, 0.351, 0.373, 0.390; occlusion days interleave with
  them at 0.299, 0.309, 0.339, 0.485. There is no threshold that separates the two, and
  the nearest clean frame sits at 0.492 — 1.09x above any cut that catches all four
  moves.

The gate that follows rejects **14 of 109 frames**, all of them dark, with **zero**
rejections among 75 clean frames.

---

## The corpus's own quality signals

All three signals are computed exactly as the V1 contract's `QualitySignals` prose
specifies: BT.601 luminance over every decoded pixel, the fraction strictly above 245,
and `(mean|diff(Y,x)| + mean|diff(Y,y)|)/2` on the full-resolution luminance plane.

| segment                | n   | mean luminance | clipped fraction | mean abs gradient |
| ---------------------- | --- | -------------- | ---------------- | ----------------- |
| framing-1 veg          | 23  | 115 – 165      | 0.094 – 0.178    | 4.27 – 5.53       |
| occlusion-1            | 9   | 153 – 185      | 0.092 – 0.174    | 2.37 – 5.82       |
| framing-2              | 5   | 154 – 163      | 0.076 – 0.163    | 4.93 – 5.57       |
| framing-3              | 7   | 145 – 156      | 0.113 – 0.143    | 5.01 – 5.67       |
| occlusion-2            | 12  | 96 – 165       | 0.000 – 0.168    | 3.83 – **8.03**   |
| reframe day            | 1   | 119            | 0.057            | 4.43              |
| framing-4 STABLE       | 35  | 123 – 148      | 0.017 – 0.160    | 4.15 – 6.20       |
| post-harvest           | 4   | 153 – 158      | 0.133 – 0.149    | 4.02 – 4.27       |
| lights-off             | 13  | **1.2 – 4.1**  | 0                | **0.00 – 0.34**   |

**Blown highlights confirmed as the norm:** 76 of 96 lit frames exceed 5% clipped, and
the maximum anywhere is 0.178. #63's headline finding survives unchanged, and it is
what rules out an absolute clipping threshold anywhere near the interesting range.

---

## Detail measures do not find occlusion

#63 recorded the occlusion signature as *"detail proxy collapses to 3.7 – 5.5 against a
median of 7.9"*. That proxy subsampled the luminance plane by 2
(`wf62/vision_lib.frame_stats`); the contract's statistic does not. They are different
numbers, and neither separates the windows once **both** occlusion windows are included
— #63 only knew about the first.

AUC is stated for the hypothesis a gate would actually use, *lower value means
occluded*, over 21 occlusion frames against 75 clean ones:

| measure                                   | occl. median | clean median | AUC       |
| ----------------------------------------- | ------------ | ------------ | --------- |
| `laplacian_var` full resolution           | 300          | 468          | **0.689** |
| `mean_absolute_gradient` (V1 contract)    | 4.36         | 5.01         | 0.615     |
| gradient, stride 2 (#63's proxy)          | 7.93         | 8.68         | 0.566     |
| gradient, stride 4                        | 13.4         | 14.2         | 0.530     |
| gradient, 2x2 box decimation              | 7.35         | 7.88         | 0.542     |
| gradient, 4x4 box decimation              | 10.6         | 11.4         | 0.507     |
| gradient, 8x8 box decimation              | 14.0         | 14.8         | 0.462     |
| `laplacian_var`, 4x4 box decimation       | 1710         | 1910         | 0.500     |
| gradient normalised by mean luminance     | 8.09         | 7.89         | 0.452     |

Suppressing sensor noise by decimation makes it **worse**, not better, which is the
tell: the signal being lost is not noise, and the frames are not blurred.

The per-frame picture says why. Occlusion window 1 does contain three genuinely soft
frames (04-14, 04-15 at gradient 2.4 – 2.5, and 04-21 at 3.1) — a canopy pressed flat
against the lens and blown out. Occlusion window 2 contains the corpus's sharpest
frames (05-07, 05-10, 05-11 at 7.7 – 8.0): foliage a few centimetres from the lens, in
focus, full of edges. One physical event, two opposite readings on every detail
statistic. No threshold survives that.

---

## The relative rails, and why they are bounds rather than a detector

Each frame is compared with the trailing median of the last 30 **accepted** frames from
the same camera, warm-up 10. Ratio, not a robust z-score: inside framing-4 the camera is
so stable that the relative MAD of the gradient falls to 0.036, which would turn the
entirely benign 05-31 exposure step into a z-score near 100.

| segment          | luminance ratio | detail ratio  |
| ---------------- | --------------- | ------------- |
| framing-1 veg    | 0.91 – 1.30     | 0.88 – 1.16   |
| occlusion-1      | 1.18 – 1.40     | **0.49** – 1.22 |
| framing-2        | 0.99 – 1.14     | 1.02 – 1.17   |
| framing-3        | 0.93 – 1.00     | 1.01 – 1.16   |
| occlusion-2      | 0.63 – 1.06     | 0.74 – 1.57   |
| reframe day      | 0.79            | 0.86          |
| framing-4 STABLE | 0.85 – 1.17     | 0.83 – 1.46   |
| post-harvest     | 1.05 – 1.08     | 0.71 – 0.76   |
| lights-off       | **0.01 – 0.03** | **0.00 – 0.06** |

Two things follow. Clean frames span 0.79 – 1.30 and 0.71 – 1.46, so rails at 0.5 / 2.0
and 0.5 hold margins of 1.58x, 1.54x and 1.42x — real, but there is **no measured
positive** on the other side of them. And the post-harvest floor of 0.71 is a warning:
an empty tent is legitimately low-detail, so a detail rail tightened much above 0.5
starts rejecting the largest true scene change in the corpus.

The 05-31 step inside framing-4 — luminance 126 to 147, clipped 0.02 to 0.11, gradient
4.2 to 6.0, and persistent for the remaining 21 frames — is the closest thing to a real
exposure event here, and it is at ratio **1.17**. #62 measured no false alarm from it
either. A rail that caught it would be more aggressive than the scorer it protects.

---

## Running the gate over the corpus

Absolute, in the service: `mean_luminance < 16`, `mean_absolute_gradient < 0.5`,
`clipped_pixel_fraction >= 0.90`. Relative, in Home Assistant: luminance ratio outside
`[0.5, 2.0]`, detail ratio below `0.5`, capped at two consecutive rejections.

```
rejected: 14 of 109
  2026-04-14              detail_collapse
  2026-06-25 .. 07-07     too_dark, low_detail, light_state_mismatch   (13 frames)

false rejections among 75 clean frames:   0
rejected in occlusion-1:                  1/9
rejected in occlusion-2:                  0/12
rejected in lights-off:                  13/13
```

Sensitivity was checked at trailing windows of 10, 20, 30 and 60 frames and warm-ups of
5 and 10: **0 clean rejections and 13/13 lights-off rejections in every combination.**
The gate's behaviour on this corpus does not depend on the window size, which is the
only honest thing that can be said about a parameter with no positives to fit.

Absolute-floor margins:

| floor                                | worst dark frame | floor | dimmest usable | margin      |
| ------------------------------------ | ---------------- | ----- | -------------- | ----------- |
| `mean_luminance < 16`                | 4.14             | 16    | 96.4           | 3.9x / 6.0x |
| `mean_absolute_gradient < 0.5`       | 0.342            | 0.5   | 2.369          | 1.5x / 4.7x |
| `clipped_pixel_fraction >= 0.90`     | —                | 0.90  | 0.178 (max)    | 5.1x        |

---

## Camera moves cannot be told from lens burials

#62 reported structural correlation splitting *"camera moved"* (0.352) from *"plants
gone"* (0.874). That was one pair of frames. As an operating detector over the corpus,
adjacent-day correlation on the 32x24 standardised signature orders like this:

```
0.291  04-22  REFRAME        0.351  05-16  REFRAME
0.299  05-07  occlusion      0.373  04-27  REFRAME
0.309  05-08  occlusion      0.390  05-17  REFRAME
0.339  04-21  occlusion      0.485  05-09  occlusion
                             0.492  04-12  clean (growth)
```

The two populations interleave completely. Any cut that catches all four repositionings
also fires on three or four occlusion days, and sits 1.09x below an ordinary growth day.
Comparing against a 30-frame trailing median signature instead of the previous frame
does not fix it: framing-4's own minimum is 0.726 while occlusion-2 reaches 0.119 and
the 05-16 reframe only 0.476.

This does not mean the signature is useless — it separates *"comparable to recent
history"* from *"not comparable"* well. It means it cannot supply the **cause**, and
therefore cannot be trusted to decide, unattended, that a Baseline Bucket should be
discarded and rebuilt.

---

## What this means for the map

1. **The gate is a darkness gate.** Everything else it does is a bound with no measured
   positive behind it. Say so rather than implying calibration that does not exist.
2. **The ticket's premise that ~20% of the corpus is unfit is half right.** The 13
   lights-off frames are unfit and would produce an entirely spurious 0.93. The ~21
   occlusion frames are *fit to score and correctly alarming*; suppressing them would
   delete the only real equipment fault in the data.
3. **No automatic camera-move detection in V1**, and therefore no automatic Framing
   Epoch boundary from one. ADR 0004 and the integration's ADR 0041 both assume one
   exists.
4. **Escalation is the mechanism that carries all of it**, because the consequence of a
   move, a burial, a dead lamp and a filthy lens is identical: this camera's captures
   are no longer comparable to its own history, and a human has to look.

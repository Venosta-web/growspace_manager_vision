# ADR 0005 — The frame quality gate rejects darkness and bounds the rest

**Status:** Accepted

Decided on 2026-08-31 in
[hub#74](https://github.com/Venosta-web/growspace_manager_workspace/issues/74), on the
measurements in
[Which captures are unfit to score, and unfit to enter a baseline?](../research/2026-08-31-frame-quality-gate.md).
It amends ADR 0004's Framing Epoch trigger and supplies the accepted/rejected outcome
that ADR 0004 consumes.

The Frame Quality Gate decides whether a Camera Snapshot may be scored and whether it
may enter a Baseline Bucket. It runs in two layers: an **absolute floor** inside
Growspace Vision, decidable from one image, and **history-relative rails** inside Home
Assistant, evaluated against the camera's own Quality History. Neither layer attempts to
detect occlusion, and V1 has no automatic camera-move detection.

## Why the gate cannot be absolute, and why one layer of it must be

76 of 96 lit corpus frames blow more than 5% of their pixels past luminance 245, because
the tent is lined with mylar under LED. Any absolute exposure threshold near the
interesting range discards four fifths of a healthy corpus. Relativity is not a
refinement here; it is the only way an exposure rail can exist at all.

But relativity requires history, and ADR 0003 makes Growspace Vision stateless by
construction. A stateless service can still refuse what one frame decides on its own,
and it must, or a bad integration release silently poisons every baseline it writes. So
the floor is absolute *because* the service holds no history — not as a compromise, but
because those are exactly the rejections that need none.

## Layer one: the absolute floor, in the service

Growspace Vision computes the three `QualitySignals` on every request and rejects the
frame, without running inference, when any of these hold:

| condition                             | reason                 | margin in the corpus              |
| ------------------------------------- | ---------------------- | --------------------------------- |
| `mean_luminance < 16`                 | `too_dark`             | 3.9x above the darkest lights-off frame, 6.0x below the dimmest usable one |
| `mean_absolute_gradient < 0.5`        | `low_detail`           | 1.5x / 4.7x                       |
| `clipped_pixel_fraction >= 0.90`      | `overexposed`          | 5.1x above the highest observed clipping |
| `light_state` disagrees with the image | `light_state_mismatch` | — |

`low_detail` is a **blank-frame** floor, not a blur detector: a frame with essentially
no spatial variation is a dead sensor, a lens cap, or a wall. It is deliberately three
orders of magnitude away from any judgment about sharpness, because no detail measure
tested separates a soft frame from a sharp one at a useful rate. `overexposed` is
likewise an all-highlight floor and explicitly not the 5%-blown case, which is normal.

These thresholds are service behaviour, not wire shape. They change with
`service_version`, which ADR 0041 already records per capture; they never change
`schema_version`. The V1 wire contract is unchanged by this decision.

## Light state is cross-checked, not inferred

Home Assistant's light-cycle state decides when a capture happens and which Baseline
Bucket it belongs to. The image decides whether that capture is usable. The two are
compared rather than ranked:

- `light_state: "on"` with a frame below the darkness floor is `too_dark` **and**
  `light_state_mismatch`. The lamp, the schedule or the camera is wrong, and that
  disagreement is more useful than either signal alone.
- `light_state: "off"` is `light_state_mismatch` regardless of brightness. V1 scores
  only lit captures, so an unlit one means the schedule and the light disagree.
- `light_state: "unknown"` is never a mismatch. There is nothing to disagree with, and
  the image floor stands alone.

## Layer two: the relative rails, in Home Assistant

Home Assistant evaluates the returned signals against the **Quality History**: the
trailing 30 accepted captures for that camera, across light windows, with a warm-up of
10 during which no rail is evaluated. Each rail is a ratio to the trailing median.

```text
exposure_excursion:  mean_luminance / median < 0.5  or  > 2.0
detail_collapse:     mean_absolute_gradient / median < 0.5
```

A ratio, not a robust z-score. Inside the corpus's stable framing the relative MAD of
the gradient falls to 0.036, which would score a benign and entirely legitimate exposure
step near z = 100. A rail that fires more readily than the scorer it protects is not
protection.

**A relative rail may reject at most two consecutive captures.** A third consecutive
excursion is not noise, it is a changed regime — a rebalanced light, a repositioned
lamp, a new camera exposure setting — and the correct response is to re-anchor and tell
the grower, not to blind the camera indefinitely. The absolute floor has no such cap: a
black frame is unusable however long it persists, and the corpus's 13-frame lights-off
run must stay rejected for all 13.

Rejected captures never enter the Quality History. Only accepted ones do, or the rails
would drift onto the very excursion they exist to detect.

**These rails are bounds, not a calibrated detector.** The corpus holds no transient
exposure excursion at all: every clean frame lies within 0.79 – 1.30 of its trailing
median luminance and 0.71 – 1.46 of its trailing median detail, so the rails have
measured specificity (0 rejections in 75 clean frames, unchanged across trailing windows
of 10 to 60) and entirely unmeasured sensitivity. They may not be tightened on argument;
tightening needs dated real excursions.

## Occlusion is not gated

Two windows in the corpus show a canopy grown into the lens, and no detail statistic
finds them: the best of nine candidates reaches AUC 0.69 and the contract's own
gradient 0.62, while coarser variants sit at chance. The three sharpest frames in the
whole corpus are inside an occlusion window, because foliage at four centimetres is
texture, not blur.

That is the right outcome, not a gap. An occluded frame is a **true** material scene
change — #62 measured occlusion at centroid-cosine 0.45 – 0.59 against a 0.13 noise
ceiling — and ADR 0004 already prevents it from entering a baseline, because only
`normal` results are admitted. Gating it would convert the loudest available signal
that a camera needs attention into silence.

## No automatic camera-move detection, and therefore no automatic Framing Epoch

**This amends ADR 0004**, which states that a Framing Epoch begins when a camera move is
detected or the grower restarts the baseline. In V1 only the second clause applies,
alongside the Grow Run and model-version boundaries.

The 32x24 standardised structural signature cannot supply the cause. The four known
repositionings score 0.291, 0.351, 0.373 and 0.390 on adjacent-day correlation, and
occlusion days interleave with them at 0.299, 0.309, 0.339 and 0.485; the nearest clean
growth day is 0.492, 1.09x above any cut that catches all four moves. #62's clean 0.352
against 0.874 was one pair of frames, not an operating threshold.

An automatic boundary on that signal is not merely imprecise, it is unsafe in one
direction. A false boundary discards a valid 30-member baseline and returns the camera
to ten days of monitoring; worse, a boundary triggered by an occlusion **re-learns the
occlusion as normal**, after which the camera reports nothing wrong while looking at a
leaf. Nothing in the data distinguishes that case from a real move.

Home Assistant still computes and stores the correlation as evidence on every capture —
it costs microseconds, and it is the only quantity that could later be calibrated
against real positives. Nothing automatic derives from it in V1.

The absence costs less than it appears to, because ADR 0004 already handles a moved
camera without knowing that it moved: every subsequent capture scores
`material_scene_change`, none is admitted, and the bucket goes stale after 14 days. The
only thing missing was telling the grower promptly, which is what escalation does.

## What a gated capture produces

A rejected capture is a first-class result, distinct from both normal and anomalous:

- It produces a **Frame Quality Result** with `accepted: false` and at least one reason,
  stored on the capture row like any other. It produces **no** Visual Comparison Result,
  no Anomaly Score and no verdict, consistent with ADR 0004.
- It **never** enters a Baseline Bucket, a trend, or the Quality History.
- It is **never** silently dropped. The capture row exists, the image is retained under
  ADR 0041's window, and the user-facing state is `capture_unusable` — its own state
  alongside `monitoring`, `normal`, `uncertain` and `material_scene_change`, never
  rendered as missing data or as a healthy result.
- A transport, authentication, model, timeout or internal failure is **not** a
  rejection. ADR 0003's no-write semantics stand: those produce no Frame Quality Result
  at all, and they do not count toward escalation.

## Escalation: the Capture Continuity Break

Home Assistant counts consecutive **non-comparable** captures per camera, in capture
order, across light windows: a capture is non-comparable when it is quality-rejected or
its verdict is `material_scene_change`. `uncertain` does not count; it is inside the
calibrated tail by construction.

**Three consecutive** non-comparable captures raise one Capture Continuity Break. At the
settled three captures per day that is within a single day, while a single capture
spoiled by a grower standing in the tent cannot raise anything. Both measured false-rate
bounds are per-capture and near zero — 0 rejections in 75 clean frames here, 0 false
material-change verdicts in 35 in-bucket frames in #62 — so three consecutive is far
below any plausible chance run. Every real event in the corpus ran 4 to 13 captures at
one per day, which is 12 to 39 at production cadence.

One break is raised per streak, not per capture, and the streak ends on the first
comparable capture. The break names the equipment, not the plant: *this camera's
captures no longer match its own recent history*. It never asserts a cause, because the
measurements above show the cause cannot be identified, and it never asserts anything
about plant health. Whether and how it reaches the grower as a Triage Alert belongs to
[hub#75](https://github.com/Venosta-web/growspace_manager_workspace/issues/75); this
decision owns the condition, not the delivery.

## Where each part runs, and why not otherwise

The integration does **not** pre-gate before calling the service. Pre-gating would save
one HTTP round trip on roughly 0.4 captures per camera per day, and would cost a second
implementation of a normative measurement: two definitions of mean luminance that can
drift apart silently, after which the integration's gate and the service's floor
disagree about the same frame. The service already skips inference on a floor rejection,
so the expensive half is not spent either way.

The service refuses independently of anything Home Assistant does, which is the property
the ticket asked for: a released integration that forgets to gate cannot push a black
frame into a baseline, because it never receives an embedding for one.

## Considered options

- **An absolute clipping or brightness threshold** was rejected on measurement: 79% of
  healthy frames exceed 5% clipped pixels.
- **A detail measure as the occlusion detector** was rejected on measurement. Nine
  candidates, best AUC 0.69, and decimation — which suppresses sensor noise — made it
  worse, because the frames are not blurred.
- **A robust z-score against the trailing distribution** was rejected because a stable
  camera drives its own MAD toward zero and turns benign steps into extreme scores.
- **A pure quantile rule** ("reject below the trailing 5th percentile") was rejected
  because it rejects a fixed fraction of captures by construction, including from a
  camera that has nothing wrong with it.
- **Gating occluded frames** was rejected because the occlusion is real, correctly
  scored, and the only equipment fault the corpus contains.
- **Automatic Framing Epoch boundaries from structural correlation** were rejected as
  unsafe: the detector cannot separate a move from an occlusion, and the failure mode
  re-learns an occluded view as normal.
- **Escalating on the first non-comparable capture** was rejected because a single
  spoiled capture is the most common benign event in a tent someone works in.
- **Letting a relative rail reject indefinitely** was rejected because a persistent
  legitimate change would blind the camera forever while the Quality History, which
  admits only accepted captures, could never adapt.

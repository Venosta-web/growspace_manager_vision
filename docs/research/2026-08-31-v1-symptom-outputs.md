# Which symptom outputs can V1 honestly emit?

Measured resolution of [issue #68](https://github.com/Venosta-web/growspace_manager_workspace/issues/68)
on the [Local Vision Subsystem V1 map](https://github.com/Venosta-web/growspace_manager_workspace/issues/60).
This extends the embedding experiment in
[issue #62](2026-08-31-embedding-distance-separation.md) by testing the classical
computer-vision proxies that remained plausible after embedding distance failed at
plant-health granularity.

## Decision

**V1 emits no symptom outputs.** Its symptom list is empty at the product level and
absent at the API level:

- no `symptoms`, `chlorosis`, `necrosis`, `drooping`, curl, leaf-spot, or tip-damage
  field;
- no raw colour or geometry proxy presented as plant evidence;
- no reserved empty symptom key;
- unknown response fields are rejected by the V1 contract, with a contract test proving
  symptom-shaped payloads invalid.

V1 may claim only that the **scene is materially different from its recent history**.
It may not claim that the plant looks unhealthy. This is stricter than merely naming a
proxy honestly: a camera-dominated measurement can still invite a grower to infer plant
change from its trend.

Zero-shot text scoring is not a V1 option. The encoder selected by issue #61 is DINOv2,
which has no text tower. Adding a second text-aligned model would reverse the measured
encoder decision rather than cheaply filling an output field.

## Method

Scripts: [`scratchpad/wf68/`](../../scratchpad/wf68/). They reuse issue #62's corrected
corpus segmentation and synthetic perturbation ladder.

- Corpus: 109 raw 800x600 JPEGs, one camera, one Grow Run, no real health positives.
- Stable population: framing-4, 35 frames from 2026-05-17 through 2026-06-20.
- Baseline: first 30 stable frames; members scored leave-one-out; final 5 are holdout.
- Plant perturbations: chlorosis patches, global chlorosis, necrosis and vertical droop.
- Camera perturbations: brightness, warm/cool white balance, sensor noise, JPEG
  compression, contrast and 2-4% pose jitter.
- Real camera controls: four reframings and two occlusion windows from the corpus.
- Proxy score: absolute z-score from the clean baseline.
- Separation: rank AUC. The decisive statistic is the chance that the best-detected
  claimed symptom scores above the camera artifact to which that proxy responds most.

Ten deterministic proxies were tested: the production HSV coverage statistic,
vegetation fraction, two chlorosis colour ratios, a brown-pixel fraction, wall-referenced
versions of the three colour statistics, and two vertical canopy geometry statistics.
The wall-referenced variants use the magenta tent wall as a white-balance reference and
hold the raw-frame pixel mask fixed while applying the correction.

The image corpus itself is not committed. The ordered manifest digest, calculated as
SHA-256 over the sorted `"<file sha256>  <basename>"` lines, is
`a12ce97806789fce4a7cc8d8b3c343d23ebf17f20eb94d7911ab75bd56b7f236`.
Set `GROWSPACE_VISION_CORPUS` to run against a different local copy.

## Results

### The production HSV number is not canopy coverage here

The exact HSV statistic from `growspace_manager/image_processor.py` averages **6.31%**
with standard deviation **1.99 percentage points** inside the fixed-camera healthy
bucket: **31.5% coefficient of variation**. A real occlusion moves it by median
**17.4 baseline standard deviations**. Sensor noise at standard deviation 8 produces
AUC **1.00**, the same as its best synthetic chlorosis response.

The current cloud prompt states this value as authoritative fact: `CANOPY COVERAGE: X%
of the image area is green plant matter`. That live false-authority claim is routed to a
separate task rather than carried into V1.

### Classical proxies fail the plant-vs-camera asymmetry

| proxy | intended claim | best symptom AUC | worst camera AUC | best-symptom vs worst-camera AUC |
|---|---|---:|---:|---:|
| blue / green ratio | chlorosis | 1.00 | 0.97 | **0.98** |
| referenced necrotic fraction | necrosis | 1.00 | 1.00 | 0.86 |
| referenced blue / green ratio | chlorosis | 1.00 | 1.00 | 0.73 |
| production HSV coverage | coverage / chlorosis | 1.00 | 1.00 | 0.70 |
| referenced red / green ratio | chlorosis | 0.86 | 0.90 | 0.42 |
| vegetation fraction | canopy extent | 1.00 | 1.00 | 0.00 |
| raw necrotic fraction | necrosis | 1.00 | 1.00 | 0.00 |
| raw red / green ratio | chlorosis | 0.99 | 1.00 | 0.00 |
| canopy top | drooping | 0.72 | 1.00 | 0.00 |
| canopy centroid | drooping | 0.78 | 1.00 | 0.00 |

The apparent survivor, blue / green ratio, separates by perturbation magnitude rather
than plant mechanism. Against the corpus-calibrated 15% warm white-balance shift, its
chlorosis separation is **0.05** at synthetic severity 0.05, **0.23** at 0.15,
**0.32** at 0.20, **0.74** at 0.30, and only reaches **0.99** at 0.45. The top-rung
headline therefore cannot be generalized to real symptoms, whose severity distribution
is unknown.

Real camera events remove the remaining margin. Occlusions and reframings move the raw
blue / green ratio by median **4.2-7.9 standard deviations**. Synthetic global
chlorosis must reach severity **0.60**, which multiplies blue by **0.67**, merely to
outscore the worst real camera-event population. The wall-referenced variant needs the
same extreme severity. Wall referencing is physically motivated, but does not rescue
the measurement.

Geometry is worse: an 8% warm white-balance shift gives AUC **1.00** on both canopy
centroid and canopy top because it changes the vegetation mask; a 70-pixel synthetic
droop reaches only 0.78 and 0.72 respectively. A measurement-named field would be
technically literal but product-level misleading because its excursions are dominated
by camera behavior.

## Re-entry bar

A named symptom may enter a later API version only when all of these are true for that
specific symptom:

1. at least **30 dated, grower-labelled real positive frames** spanning at least
   **two Grow Runs**;
2. worst-case separation AUC **at least 0.90** against both the synthetic camera ladder
   and a real camera-event population from the same capture environment;
3. sensitivity measured at a gate with zero in-bucket false alarms, reporting the
   **fire rate as well as AUC**.

Synthetic plant perturbations can probe failure modes but cannot satisfy the positive
evidence requirement. The current one-Run, zero-positive corpus therefore is not a
future symptom-validation dataset. Preserve this analysis and its manifest digest, not
the private images.

## Routed consequences

- Issue #67 owns structural enforcement: omit symptom keys, reject unknown fields, and
  include a negative contract fixture for symptom-shaped payloads.
- Issue #73 must not migrate the existing HSV coverage claim into the new contract.
- Issue #74 receives the observed colour/noise response only as a lead for its frame
  quality gate, not as a new committed mechanism; real degraded frames would be needed
  to validate it.
- Removing the current prompt's authoritative `CANOPY COVERAGE` line is a separate
  executable task because it is a live false-authority bug, not part of this planning
  ticket.

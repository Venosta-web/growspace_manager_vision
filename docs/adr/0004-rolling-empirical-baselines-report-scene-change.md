# ADR 0004 — Rolling empirical baselines report scene change

**Status:** Accepted

Decided on 2026-08-31 in
[hub#66](https://github.com/Venosta-web/growspace_manager_workspace/issues/66),
using the fixed-framing corpus measurements from
[hub#62](https://github.com/Venosta-web/growspace_manager_workspace/issues/62).
Home Assistant compares each accepted Visual Embedding with a 30-member rolling
Baseline Bucket by centroid-cosine distance, calibrates that distance by its empirical
rank within the bucket, and reports only departure from recent scene history. It does
not interpret the score, verdict, or confidence as plant health.

## Bucket identity and membership

A Baseline Bucket belongs to exactly one camera, light window, Grow Run, model version,
and Framing Epoch. The light-window dimension remains deliberately conservative but
empirically unvalidated: the available corpus contains only one capture per day. A
Framing Epoch begins when a camera move is detected or the grower manually restarts the
visual baseline. Grow Run and model-version changes also start fresh buckets.

Only quality-accepted, framing-stable captures may become members. During bootstrap,
every eligible capture enters the bucket; membership describes an intended stable
scene, not user-confirmed plant health. After the bucket is ready, the current capture
is scored before any update and enters only when its verdict is `normal`. `uncertain`,
`material_scene_change`, and quality-rejected captures never update the bucket. A
normal capture replaces the oldest member, after which Home Assistant recomputes the
centroid and calibration distances.

The frame-quality and camera-move mechanisms are owned by
[hub#74](https://github.com/Venosta-web/growspace_manager_workspace/issues/74).
This decision consumes their accepted/rejected and framing-boundary outcomes; it does
not preempt their measures or thresholds.

## Baseline states

A bucket has one of three Baseline States:

- `monitoring`: fewer than 30 eligible members exist. Every accepted Vision Analysis
  records a first-class monitoring-only Visual Comparison Result with
  `samples_collected` and `samples_required: 30`, but no Anomaly Score, Comparison
  Confidence, or scene-change verdict. The capture that supplies member 30 remains a
  monitoring result; the next eligible capture is the first one scored.
- `ready`: exactly 30 rolling members exist and the newest admitted member is no more
  than 14 elapsed days old. The bucket may produce scored results.
- `stale`: no member has been admitted for 14 elapsed days. After bootstrap, only a
  normal capture can be admitted. Stale captures
  produce first-class monitoring-only results without a score, confidence, or verdict.
  The old members and calibration remain available for audit, but scoring and automatic
  admission stop until a manual restart or an automatic Grow Run, model-version, or
  Framing Epoch boundary starts a fresh bucket.

A quality rejection remains a Frame Quality Result and creates no Visual Comparison
Result. Transport, authentication, model, timeout, and internal failures retain the
no-write semantics from ADR 0003.

Thirty is a validity gate, not a confidence multiplier. It is the only baseline size
for which the available corpus measured a leave-one-out noise distribution and an
untouched holdout. Fourteen members were used only to prove that a fixed baseline
drifts; that experiment did not validate a 14-member scoring baseline.

## Distance and empirical score

Let the bucket `B` contain 30 unit-normalized embeddings, and let `normalize` return a
unit vector. Its centroid and the current embedding's raw centroid-cosine distance are:

```text
centroid(B) = normalize(sum(B))
d = 1 - dot(current_embedding, centroid(B))
```

Each member supplies one leave-one-out calibration distance:

```text
d[i] = 1 - dot(B[i], normalize(sum(B excluding B[i])))
```

The Anomaly Score is the strict empirical rank:

```text
anomaly_score = count(d[i] < d) / 30
```

It ranges from 0 to 1 in increments of `1/30`. Strict comparison makes a tie with
observed calibration distance conservative. A score of 1 means only that the current
distance exceeds every leave-one-out distance in this bucket; it is not an anomaly
probability or a health probability.

This rank gives scores the same semantics across buckets: the fraction of recent
in-bucket variation below the current distance. Actual calibration across cameras,
Grow Runs, and light windows remains unmeasured. There is no global operational raw
threshold. The measured fixed-framing maximum, 0.1339, remains research evidence and a
regression reference rather than a constant applied to other buckets.

## Verdicts and Comparison Confidence

The empirical thresholds deliberately reserve the complete upper tail for uncertainty:

|          Anomaly Score | verdict                 |
| ---------------------: | ----------------------- |
|               `< 0.90` | `normal`                |
| `>= 0.90` and `< 1.00` | `uncertain`             |
|                `= 1.0` | `material_scene_change` |

With 30 calibration distances, `uncertain` spans roughly the highest 10% of recent
variation. A material-scene-change verdict requires raw distance strictly above the
observed maximum.

Comparison Confidence measures distance from the uncertain band, not correctness or
plant health. Let `m` be the median calibration distance, `t` its nearest-rank 90th
percentile (sorted member 27), `u = max(d[i])`, and `w = max(u - t, 0.000001)`. For raw
distance `d`:

```text
normal:                confidence = clamp((t - d) / max(t - m, 0.000001), 0, 1)
uncertain:             confidence = 0
material_scene_change: confidence = clamp((d - u) / w, 0, 1)
```

Sample count and frame quality do not multiply this value: they are hard prerequisites
for a scored result. Only a `material_scene_change` result with Comparison Confidence
1 may be considered for alerting, and even that combination is necessary rather than
sufficient. [Hub#75](https://github.com/Venosta-web/growspace_manager_workspace/issues/75)
owns the shipping decision about whether and when V1 creates a Triage Alert.

## Reset semantics

The user-facing camera action is **Restart visual baseline**. After confirmation it
starts a new Framing Epoch and resets every light-window bucket for that camera in the
active Grow Run. It discards only active baseline members and calibration data; Camera
Snapshots, Vision Analyses, Frame Quality Results, and Visual Comparison Results remain
historical evidence. Automatic Grow Run, model-version, and detected-framing boundaries
have the same fresh-monitoring effect without deleting history.

## Evidence limits and consequences

The 30-frame corpus baseline measured centroid-cosine noise at 0.0566 +/- 0.0244 with a
maximum of 0.1339 and zero false alarms in five untouched in-bucket holdout frames. A
fixed 14-frame baseline reached a 33% false-alarm rate by days 15-20, while the rolling
version held its median flat. Leave-one-out distances are right-skewed, so the Gaussian
three-sigma rule is rejected in favour of the empirical rank and maximum.

These thresholds are calibrated only for specificity. The corpus contains no real
plant-health positives, plant-vs-camera separation measured AUC 0.56, and gross scene
events dominate high distances. Consequently V1 may say that a scene is materially
different from recent history, but never that the plant is unhealthy. A slowly
developing visual change can still enter a rolling baseline through successive normal
steps; that limitation is accepted because suppressing healthy growth drift and
detecting gradual plant symptoms are not separable with the available representation.

## Considered options

- **A fixed baseline** was rejected because healthy growth produced a 33% false-alarm
  rate within three weeks.
- **A 14-member valid baseline** was rejected because 14 was a drift probe, whereas the
  empirical tail and holdout were measured at 30.
- **A global raw threshold near 0.13** was rejected because incorrect camera-framing
  segmentation inflated the measured noise floor roughly fourfold, and only one camera
  and Grow Run have been measured.
- **A Gaussian three-sigma gate** was rejected because the empirical distances are
  right-skewed and the rolling window tightens its own standard deviation.
- **Admitting every scored capture** was rejected because a material change would
  redefine normal. Requiring individually confirmed healthy frames was also rejected:
  the encoder cannot establish health, and that workflow would misname the baseline.
- **A composite confidence from sample count, image quality, and spread** was rejected
  as false precision. Count and quality are hard gates; the per-bucket spread defines
  the uncertainty band and Comparison Confidence.

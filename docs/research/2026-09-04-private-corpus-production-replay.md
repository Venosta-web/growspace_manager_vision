# Private corpus production replay

Aggregate, non-image-bearing result for
[Build the private corpus replay and visual evidence report](https://github.com/Venosta-web/growspace_manager_workspace/issues/94),
under the V1 delivery map in workspace issue #79.

Date: 2026-09-04. The source images, per-frame ledger, embeddings, thumbnails, and
visual report remain local and ignored. This document contains aggregate results only.

## Result

The production pipeline completed all 109 captures. Growspace Vision analyzed 96 and
rejected the 13 lights-off captures at its absolute floor. Home Assistant rejected one
additional occluded capture on its camera-relative detail rail, reproducing the locked
combined Frame Quality Gate result of **14 rejected and 95 accepted**.

The production comparison did **not** reproduce the earlier fixed-bucket experiment.
With the historical captures replayed as one uninterrupted Framing Epoch, known scene
events were admitted as normal, the subsequent stable regime was compared against a
mixed earlier baseline, and the bucket eventually became stale. That is operational
evidence, not permission to tune the score silently: the corpus does not record the
manual Framing Epoch actions a grower would or would not have made.

| Outcome | Frames |
|---|---:|
| Baseline monitoring / warm-up | 30 |
| Normal | 14 |
| Uncertain | 5 |
| Material scene change | 13 |
| Stale-baseline monitoring | 33 |
| Quality rejected / comparison unavailable | 14 |

Only 32 captures received scores before the baseline became stale. Their raw
centroid-cosine distance ranged from 0.1073 to 0.6296, with median 0.2254 and p95
0.4504. Their Anomaly Score ranged from 0.1667 to 1.0, with median 0.9333 and p95 1.0.
The saturation confirms the earlier finding: the rank cannot express the severity of
different scene events.

## Quality signals

| Signal | Minimum | Median | P95 | Maximum |
|---|---:|---:|---:|---:|
| Mean luminance | 1.2108 | 143.6214 | 165.2995 | 184.8862 |
| Clipped pixel fraction | 0 | 0.1063 | 0.1630 | 0.1785 |
| Mean absolute gradient | 0.0028 | 4.7940 | 6.1434 | 8.0310 |

Vision's 13 absolute rejections each reported `too_dark` and `low_detail`. Home
Assistant additionally reported one `detail_collapse`, producing the combined 14-frame
result documented by the Frame Quality Gate research. No relative-history reanchor
occurred.

## Discrepancy ledger

### Known scene events scored normal

Fourteen captures inside human-reviewed occlusion or reframe segments scored `normal`
under the uninterrupted bucket and were eligible for rolling admission. The comparison
therefore learned across changed scenes. This does not contradict the V1 rule code; it
exposes the consequence of replaying a corpus with no historical manual Framing Epoch
actions.

### Stable framing produced material-change verdicts

The first six scored captures in the human-reviewed stable-framing segment all returned
`material_scene_change`, with raw distances from 0.3930 to 0.4566. They were being
compared with the mixed earlier bucket, not a baseline established inside that stable
regime. The approved prototype's claim that the stable run stayed quiet is therefore
not supportable from the production chronology without an explicit epoch-reset replay.

### The bucket became stale

After fourteen days without a normal admission, the Baseline Bucket changed to
`stale`. Thirty-three later quality-accepted captures—including the remainder of the
stable segment and the post-harvest segment—could then produce only monitoring results.
The production replay consequently cannot evaluate the earlier fixed-baseline claim
about the post-harvest distance or later stable specificity.

These three entries require product or acceptance-scenario review. They must not be
resolved by changing thresholds against this zero-positive corpus. The next decision is
whether the acceptance replay should also model explicit, recorded grower Framing Epoch
restarts; the unintervened replay above must remain as the operational control.

## Native amd64 timing and memory

The hash-locked production App image ran natively on `x86_64` in the development
container. Measurements include HTTP multipart handling, decode, quality measurement,
and inference.

| Measure | Result |
|---|---:|
| Analyzed-frame latency, median | 31.6 ms |
| Analyzed-frame latency, p95 | 35.8 ms |
| Analyzed-frame latency, maximum | 45.4 ms |
| Absolute-floor rejection latency, median | 6.9 ms |
| Absolute-floor rejection latency, p95 | 8.2 ms |
| Container cgroup peak memory | 138.6 MiB |
| Production inference deadline | 10 s |

Physical arm64 latency and memory remain unmeasured, as required by the delivery map.

## Provenance and reproduction

- Corpus: 109 consecutive daily JPEGs; ordered content-manifest SHA-256
  `44e05795e1c34af7638acd5d9424ce5b4f98b9adaf98ebd0c82339d31d6a9479`.
- Vision source: `growspace_manager_vision@c0e1ea615593dbdfa7fbdeb6857c8609f6925284`,
  with no production-source changes.
- Container image ID:
  `sha256:eb8cb54290405002449b372e1690c9cb0c0600d634a554d59a1fc2f8c6f5c4ef`.
- Model: `dinov2-vit-s-14-int8-onnx`, version `1.0.0`, 384 dimensions.
- Home Assistant rules: `growspace_manager@0a5ad5be2511afc27b4307c32ae8c0cacee081ba`,
  clean checkout, scoring policy 1. The replay also records SHA-256 values for each
  imported rule source file in its publishable `aggregate.json`.

Run [`scripts/private_corpus_replay.py`](../../scripts/private_corpus_replay.py) with
the production Vision container, the private corpus path, the local App token file,
and a clean `growspace_manager` checkout. It validates the 109-frame consecutive input
contract, negotiates the loaded model, performs one HTTP Vision Analysis at a time,
round-trips embeddings through float32 exactly as the integration persists them, and
then executes the integration's real `QualityHistory` and `VisualComparisonEngine`
classes.

The historical corpus carries no trustworthy light-state, light-window, or manual
Framing Epoch records. This control replay therefore sends `light_state=unknown`, uses
one synthetic mid-light bucket, and preserves one uninterrupted epoch. The local report
states those limitations next to the evidence.

## Privacy boundary

The ignored local `private-corpus-report/` contains the approved one-thumbnail-per-frame
filmstrip, a measurement disclosure, the per-frame JSON ledger, and the aggregate JSON.
The script holds Visual Embeddings only in memory. Its publishable aggregate explicitly
asserts that it contains no source paths, images, embeddings, or per-frame results.

Scene-change monitoring only. **Plant-health calibration: none in V1.** The corpus has
zero real health positives, so plant-health sensitivity is not measured and is not
claimed.

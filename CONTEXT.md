# Growspace Vision

This context names the visual-analysis boundary shared by Growspace Manager and
Growspace Vision. Home Assistant owns time, memory, and interpretation; Growspace
Vision owns one stateless image analysis.

## Language

**Growspace Vision**:
The local, stateless service that evaluates one Camera Snapshot without receiving
environmental observations or retaining history.
_Avoid_: Vision AI, plant-health model, anomaly service

**Vision Analysis**:
One Growspace Vision operation that either produces a Visual Embedding or rejects the
Camera Snapshot as unusable.
_Avoid_: Vision Checkup, scoring, diagnosis

**Visual Embedding**:
The model-versioned vector representation of one Camera Snapshot returned by a
successful Vision Analysis.
_Avoid_: Anomaly score, health score, feature score

**Frame Quality Result**:
The non-plant image measurements and any unusable-frame reasons returned by a Vision
Analysis.
_Avoid_: Plant evidence, health evidence

**Vision Checkup**:
The Home Assistant workflow that captures Camera Snapshots, requests Vision Analyses,
compares accepted embeddings with a Baseline Bucket, and records a Visual Comparison
Result.
_Avoid_: Vision Analysis

**Baseline Bucket**:
The Home Assistant-owned rolling recent history for one camera, light window, Grow
Run, model version, and Framing Epoch against which Visual Embeddings may be compared.
_Avoid_: Vision-service baseline, global baseline

**Framing Epoch**:
A period in which one camera's physical framing is treated as materially unchanged.
A detected camera move or a manual visual-baseline restart begins another epoch.
_Avoid_: Camera position, framing bucket

**Baseline State**:
The comparison readiness of a Baseline Bucket: `monitoring`, `ready`, or `stale`.
_Avoid_: Validity flag, baseline confidence

**Anomaly Score**:
The empirical 0-1 rank of a Camera Snapshot's visual distance within its Baseline
Bucket. It describes departure from recent scene history, not plant health or risk.
_Avoid_: Health score, risk score, model probability

**Comparison Confidence**:
The separation margin between a Visual Comparison Result and its Baseline Bucket's
uncertain band. It is not plant-health probability or model self-confidence.
_Avoid_: Health confidence, model confidence

**Visual Comparison Result**:
The Home Assistant-owned result of interpreting a Vision Analysis against temporal
context, including an anomaly score and any trend or material-scene-change verdict.
_Avoid_: Evaluation Snapshot, analysis response, model result

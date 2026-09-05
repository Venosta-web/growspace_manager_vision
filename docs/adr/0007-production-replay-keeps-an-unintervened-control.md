# ADR 0007 — Production replay keeps an unintervened control

**Status:** Accepted for V1; the intervention replay remains unmeasured.

Decided for [hub#137](https://github.com/Venosta-web/growspace_manager_workspace/issues/137).
The [production replay](../research/2026-09-04-private-corpus-production-replay.md)
completed all 109 captures and reproduced the 14 rejected / 95 accepted Frame Quality
Gate result, but contradicted the comparison claims borrowed from earlier experiments.
Keep that uninterrupted chronology as the operational control, add a separately
declared grower-intervention acceptance scenario, retain the stale-baseline policy,
and correct the presentation's claims. No model, quality rail, score threshold,
baseline size, or admission policy changes follow from this corpus.

## What the evidence decides

| Observation in the control | Decision and limit |
|---|---|
| 14 captures in reviewed occlusion or reframe segments scored `normal` and were eligible for admission | A normal verdict does not establish unchanged framing. V1 cannot promise to detect scene events or prevent their admission without grower intervention. |
| The first six scored stable-segment captures were `material_scene_change`, at raw distances 0.3930–0.4566 | Withdraw the claim that the production stable run stayed quiet. Physical framing stability does not establish comparability to a bucket built in an earlier scene. |
| 33 later accepted captures were stale monitoring results | Those captures provide no scored stable-specificity or post-harvest result. Monitoring is unavailable comparison, never a negative finding. |
| Across 32 scored captures, rank median/p95 were 0.9333/1.0, while raw-distance median/p95 were 0.2254/0.4504 | Keep rank as departure from recent history. Neither rank nor raw distance is calibrated scene-event severity or plant-health probability. |

The corpus has zero real health positives. Execution success and reproduced quality
counts remain valid evidence for [hub#79](https://github.com/Venosta-web/growspace_manager_workspace/issues/79);
they do not establish reliable unattended scene-event detection or plant-health
sensitivity. Earlier fixed-bucket results remain historical experiments with their
own baseline and segmentation assumptions, not predictions of production chronology.

## Acceptance with explicit grower actions

Require two separately named runs. Preserve the existing **unintervened control**,
including its discrepancies. The additional **grower-intervention scenario** models
explicit `Restart visual baseline` actions recorded in a scenario manifest before
examining that run's scores. The corpus has no historical action records: these are
counterfactual grower actions, never reconstructed facts or automatic move detection.

The implementation follow-up must:

- Freeze the ordered input manifest, source/model identities, rule hashes and all
  current scoring and quality settings for both runs. Keep the same unknown light
  state, synthetic light window and chronological frame order.
- Record each action's capture boundary, camera, reason and scenario provenance.
  Include a restart immediately before the reviewed stable-framing segment, after
  the assumed grower has restored the intended view. Declare any other actions from
  reviewed scene boundaries before scoring; never add resets to suppress a verdict.
- Apply the integration's actual camera-wide Framing Epoch reset semantics across
  light windows. Preserve historical evidence and follow production Quality History
  behavior; do not silently reset all history or prefill baseline members.
- Bootstrap anew with the existing 30-member and admission-cadence rules. Member 30
  remains monitoring; only subsequent eligible captures can be scored. Report the
  scored denominator and all quality-rejected, warm-up and stale captures by segment
  and scenario, including segments with no scored captures.
- To evaluate post-harvest departure, carry the stable-segment bucket across harvest
  in that scenario. A restart at harvest would instead measure a new bootstrap and
  cannot substantiate the earlier post-harvest comparison claim.
- Emit both aggregate ledgers and their discrepancies side by side, with action
  provenance and baseline readiness visible in the local filmstrip. Keep images,
  paths and per-frame private evidence local and ignored.

This is a requirement for the next acceptance replay, not a claim it has passed.
Success means faithful execution and honest accounting, not zero material-change
verdicts. Further contradictory results require review rather than schedule or
threshold tuning. The intervention run cannot replace the control as evidence about
a grower who never touches the camera or restarts its baseline.

## Staleness is an intentional stop with a recovery obligation

Retain [ADR 0004](0004-rolling-empirical-baselines-report-scene-change.md): a ready
bucket stops scoring once its last admitted member is more than 14 elapsed days old
(the production comparison uses `> 14 days`). This means no **admission**, not no
capture, no camera movement, or fourteen days of reassuring observations. A physically
untouched camera can still reach this state through sustained non-normal results.

Keep old members for audit and return monitoring-only results with no score,
confidence or scene-change verdict. Do not automatically admit stale captures,
restart the epoch, or continue scoring the old bucket. Recovery requires the grower
to inspect the view and choose **Restart visual baseline**, or an existing Grow Run
or model-version boundary; recovery then requires a fresh bootstrap. Automatic
relearning could normalize an occlusion, while indefinite scoring uses an obsolete
reference. The cost accepted for V1 is indefinite comparison unavailability when the
grower does nothing, even though accepted Vision Analyses can continue.

The recovery path must be visible beside a stale result. Suggested copy: “Visual
comparison paused: no capture has entered this baseline for more than 14 days.
Check the camera view. Restart visual baseline when the intended view is established;
comparison resumes after a new baseline is collected.” The Capture Continuity Break
can warn on its specified streak, but is not a guaranteed precursor to staleness or
a detector of every changed scene. The control's normal admissions demonstrate why.

## Amendment to the approved presentation

Keep [hub#92](https://github.com/Venosta-web/growspace_manager_workspace/issues/92)'s
two-channel card ledger and local filmstrip with collapsed measurements. Keep scene
and environmental evidence separate, and keep both permanent statements:
**Scene-change monitoring only** and **Plant-health calibration: none in V1**.

Replace the prototype's “stable run stayed quiet” / “58 in-bucket frames with zero
false alarms” production implication with: “In the uninterrupted production replay,
the first six scored stable-framing captures differed materially from the earlier
baseline. Later stable and post-harvest captures were not scored after it became
stale. A replay with declared baseline restarts has not yet been measured.”
The old prototype is a historical review artifact, not current acceptance evidence.

The Anomaly Score remains a sentence about rank relative to this camera's baseline,
with score, raw distance and Comparison Confidence behind disclosure. Add the
interpretive limit “Relative to this baseline; not the severity or cause of a scene
change.” Do not substitute a raw-distance severity gauge when rank saturates. Distinguish
warm-up from stale monitoring in the gate strip and filmstrip; neither is `normal`.

Downstream implementation scope is bounded: Vision owns the paired replay and report;
the card owns the stale-recovery and rank-limit presentation, using the existing HA
baseline action and evidence API. HA's comparison policy and the stateless Vision
contract remain unchanged. These follow-ups must cite this decision and report their
own validation; this ADR supplies no new replay or browser-test results.

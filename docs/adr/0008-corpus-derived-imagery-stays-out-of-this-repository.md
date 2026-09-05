# ADR 0008 — Corpus-derived imagery stays out of this repository

**Status:** Accepted. The working tree is clean as of this commit. The hub's public
history has been rewritten; a residual there, and this repository's own history, remain
open.

Decided for [hub#138](https://github.com/Venosta-web/growspace_manager_workspace/issues/138),
under the corpus-privacy rule of
[hub#79](https://github.com/Venosta-web/growspace_manager_workspace/issues/79): *the 109
source images remain local, ignored, and unpublished; repositories carry aggregate,
non-identifying results only.*

Four corpus-derived JPEGs were tracked here, at
`docs/research/assets/embedding-separation/`, and illustrated the
[embedding-distance separation prototype](../research/2026-08-31-embedding-distance-separation.md):

| File | Contents | Referenced by the document |
|---|---|---|
| `corpus-sheet-1.jpg` | 48 frames of the run as a contact sheet, each captioned with its date | yes |
| `corpus-sheet-2.jpg` | the rest of the run, same form | yes |
| `perturbations-plant.jpg` | one corpus frame under the rendered perturbation set | yes |
| `camera-events.jpg` | four corpus frames at legible resolution | **no — untracked orphan** |

Between them they publish the whole 109-frame run, dated, plus four frames large enough
to read. That is the corpus itself, not an aggregate result about it.

## Decision

**Remove them, keep the prose.** No file overriding hub#79 was worth writing: the map
names its corpus-privacy rule as a locked foundation decision, and the only argument for
keeping these four was that they are useful — which is an argument for regenerating them
locally, not for shipping them. The alternative on the ticket, keeping them under a
recorded override plus a promise to rewrite history later, buys the same illustrations
at the cost of a standing obligation and one more chance to forget it.

What the document actually loses is small. The three corrections the sheets produced —
four camera repositionings, a second occlusion window, harvest on 2026-06-21 — are
recorded as tables in the prose and verified by a tracked script,
[`03_verify_segments.py`](../../scratchpad/wf62/03_verify_segments.py). The sheets were
how they were *found*, not how they are *held*. The document now says so, and says where
to look again: the local corpus, or the per-frame filmstrip that
[`scripts/private_corpus_replay.py`](../../scripts/private_corpus_replay.py) already
writes to the ignored `private-corpus-report/` — the discipline these assets predate.

Nothing regenerates the sheets from a tracked script. They were assembled by hand, and
this decision does not add a generator: a tracked tool whose output must never be tracked
is a trap, and the replay filmstrip covers the same frames in the same order.

`.gitignore` now carries the rule beside the `private-corpus-report/` entry that states
the same principle, covering `docs/research/assets/`, raster output under `scratchpad/`,
and the corpus's own `growcam_sog_*.jpg` filenames. App store artwork under
`growspace_vision/` is deliberately left uncovered; it is not corpus-derived.

## The premise this ticket was written on is false

hub#138 reasons from *"the repository is private today, which is why nothing has
leaked"*, and treats history rewriting as cheap insurance taken before publication.
That is true of this repository and false of the frames.

These assets were first committed in the hub, `growspace_manager_workspace`, in
`5c95d74 prototype(vision): measure whether embedding distance separates canopy change`,
and moved out of its tree by `e2beb08 chore(vision): move service assets to dedicated
repository`. Moving a file out of a tree does not remove it from history. `5c95d74` is
an ancestor of the hub's `main`, and **the hub is a public repository**. All four blobs
are anonymously downloadable from it today, and have been since 2026-08-31.

So this was not a pre-publication precaution. The corpus imagery was already published,
and removing it from this repository's tree — this commit — does not change that. The
remediation belongs to the hub, which owns the public remote; it is summarised here
because this repository is where the rule now lives.

## What was done in the hub

All 43 hub branches were rewritten with `git filter-repo --invert-paths --path
docs/research/assets/embedding-separation` and force-pushed. The rewrite is surgical:
every branch tip's tree is byte-identical to its predecessor except the four that still
carried the files, where the only difference is those four paths, and `main`'s tree hash
is unchanged. A `git clone` of the hub no longer carries the frames.

## Obligations this ADR does not discharge

- **The hub's `refs/pull/*`.** Thirteen pull-request refs still reach the blobs, and
  GitHub makes those read-only: no force-push can rewrite or delete them, and the
  original commits stay fetchable by SHA until GitHub garbage-collects. Only GitHub
  Support can purge them. Until that request is filed and completed, the frames remain
  publicly retrievable by anyone holding a commit SHA.
- **This repository's own history.** Sixteen branches on this repository's `origin`
  still carry the blobs, `main` among them, and the history is short enough that a
  rewrite is cheap. Worth doing before this repository is made public, a mirror is cut,
  or a support bundle is taken from it. It has no bearing on the hub residual above.

Treat the four frames as disclosed. They were anonymously fetchable from a public
repository from 2026-08-31 until the rewrite, and remain so by SHA until GitHub
completes the purge; no rewrite recalls what was already served.

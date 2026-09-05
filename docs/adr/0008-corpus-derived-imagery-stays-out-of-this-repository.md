# ADR 0008 — Corpus-derived imagery stays out of this repository

**Status:** Accepted. The working tree is clean as of this commit; the history purge is
an open obligation, and it is larger than this repository.

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

So this is not a pre-publication precaution. The corpus imagery is already published,
and removing it from this repository's tree — this commit — does not change that. The
remaining work is disclosure remediation in the hub, which owns the tracker and the
public remote; it is recorded there rather than here.

## Obligations this ADR does not discharge

- **The hub's public history.** Purging `5c95d74`'s blobs from
  `growspace_manager_workspace` requires rewriting a public `main`, force-pushing, and
  asking GitHub to expire the cached blob views that survive a rewrite. Owned by the
  hub, and by whoever decides whether a rewrite is worth it now that the frames have
  been publicly fetchable for months.
- **This repository's own history.** Sixteen branches on this repository's `origin`
  still carry the blobs, `main` among them, and the history is short enough that a
  rewrite is cheap. It is worth doing before this
  repository is made public, a mirror is cut, or a support bundle is taken from it —
  but it is not urgent while it is private and unforked, and it is worthless on its own
  while the hub still serves the same bytes.

Both are gated on an explicit decision, not on this ADR. Until they are done, treat the
four frames as public.

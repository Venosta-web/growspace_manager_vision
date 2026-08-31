"""PROTOTYPE — the corpus's real segmentation, read off the frames and verified below.

Issue #63 recorded one occlusion window and a fixed camera. The frames show a camera
that was repositioned repeatedly, a SECOND occlusion window, and a harvest three days
earlier than recorded. See 02c/04 output.
"""
import datetime as dt

D = dt.date.fromisoformat
SEGMENTS = [
    ("framing-1 veg",      D("2026-03-21"), D("2026-04-12")),
    ("occlusion-1",        D("2026-04-13"), D("2026-04-21")),
    ("framing-2",          D("2026-04-22"), D("2026-04-26")),
    ("framing-3",          D("2026-04-27"), D("2026-05-03")),
    ("occlusion-2",        D("2026-05-04"), D("2026-05-15")),
    ("reframe day",        D("2026-05-16"), D("2026-05-16")),
    ("framing-4 STABLE",   D("2026-05-17"), D("2026-06-20")),
    ("post-harvest",       D("2026-06-21"), D("2026-06-24")),
    ("lights-off",         D("2026-06-25"), D("2026-07-07")),
]
STABLE = ("framing-4 STABLE", D("2026-05-17"), D("2026-06-20"))


def label(d):
    for nm, a, b in SEGMENTS:
        if a <= d <= b:
            return nm
    return "?"
